"""CLI ODACEA — audit et classement d'archives en ligne de commande.

Expose les agents AUD-001 et CLA-001 sans Streamlit, pour intégration dans
des workflows automatisés (GED, scripts d'import, pipelines de versement).
Partage strictement la même logique métier que l'app Streamlit.

Usage : odacea {audit,classement,run} ... (après `pip install -e .`)
        ou : python cli.py {audit,classement,run} ...
"""
from __future__ import annotations

import argparse
import csv as csv_mod
import json
import math
import os
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# Le CLI écrit des accents et des caractères décoratifs (→, ═, ✓) sur stdout/stderr.
# Sur une console Windows par défaut (cp1252), cela lève un UnicodeEncodeError dès
# la première ligne. On force l'UTF-8 sans dépendre de PYTHONUTF8 (réversible et
# silencieux si le flux ne le supporte pas — p. ex. déjà remplacé par un test).
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        try:
            _reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

load_dotenv()

from config.file_config import ConfigError, discover_config, load_config, section_get
from config.settings import DEFAULT_MODEL
from core.agt_agent import agent_turn, resolve_tool_mode
from core.agt_session import SessionStore
from core.apply_classement import (
    build_apply_plan,
    check_target_guards,
    iter_apply,
    verify_apply,
)
from core.audit_scan import format_digest, scan_metadata
from core.cla_directives import allowed_parents as directives_allowed_parents
from core.cla_directives import read_directives_file, render_directives
from core.corrections import read_corrections_file, render_corrections_examples
from core.csv_handler import (
    build_reference_tree_from_folders,
    classement_llm_csv,
    convert_classement_to_resip,
    csv_to_string,
    extract_csv_from_response,
    extract_plans,
    parse_plan_tree,
    prepare_for_classement,
    prepare_for_llm,
    read_csv,
    strip_folder_numbers,
    validate_csv,
)
from core.enrich import (
    content_access_notice_lines,
    enrich_descriptions,
    fingerprint_files,
)
from core.evals import (
    agent_case_metrics,
    agent_run_metrics,
    audit_metrics,
    classement_metrics,
    format_eval_tables,
)
from core.export_manifest import build_tree_manifest, format_tree_manifest_markdown
from core.journal import build_journal, format_journal_markdown
from core.plan_compare import compare_plan_variants, format_comparison_table
from core.plan_folders import (
    looks_like_csv,
    plan_nodes_from_folders_df,
    serialize_plan_block,
)
from core.prep_budget import format_budget_line, recommend_prep
from core.pricing import estimate_cost_eur, format_cost_eur, is_local
from core.reference_plans import (
    compose_observation,
    custom_reference_plan,
)
from core.source_scan import SourceScanError, write_source_csv
from core.tokens import (
    estimate_text_tokens,
    format_duration,
    format_tokens,
    sum_usage,
)
from llm import get_provider
from prompts import AGT_001, AUD_001, CLA_001

EXIT_OK = 0
EXIT_LLM_ERROR = 1
EXIT_INPUT_INVALID = 2
EXIT_OUTPUT_INVALID = 3
EXIT_CONFIG_ERROR = 4


# ── Helpers ──────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _emit_json(args, payload: dict) -> None:
    """Sortie machine : écrit le résumé structuré sur **stdout** quand
    `--json` est demandé. Les logs humains restent sur stderr (`_log`), si bien
    que stdout ne porte qu'un seul document JSON, redirigeable et scriptable
    sans parsing de texte libre (`odacea run … --json | jq …`)."""
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


def _maybe_write_journal(args, **kwargs) -> dict | None:
    """Journal de traitement : si `--journal FICHIER` est demandé, construit
    le journal de traçabilité (moteur `core.journal`), l'écrit en Markdown au
    chemin indiqué et le renvoie (pour l'imbriquer dans la sortie `--json`).
    Aucune écriture sans le flag — c'est une **option d'export** opt-in. Le
    journal ne porte que des métadonnées (jamais le contenu des documents)."""
    if not getattr(args, "journal", None):
        return None
    journal = build_journal(**kwargs)
    path = Path(args.journal)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_journal_markdown(journal), encoding="utf-8")
    _log(f"✓ Journal de traitement écrit : {path}")
    return journal


def _maybe_write_manifest(args, df_resip) -> dict | None:
    """Manifeste d'arborescence modèle : si `--manifest FICHIER` est demandé,
    dérive l'arborescence de répertoires cible du CSV RESIP produit (moteur
    `core.export_manifest`), l'écrit en Markdown et renvoie l'objet structuré
    (pour l'imbriquer dans la sortie `--json`). Aucune écriture sans le flag —
    **option d'export** opt-in, **métadonnées seules** (jamais le contenu)."""
    if not getattr(args, "manifest", None):
        return None
    manifest = build_tree_manifest(df_resip)
    path = Path(args.manifest)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_tree_manifest_markdown(manifest), encoding="utf-8")
    _log(f"✓ Manifeste d'arborescence modèle écrit : {path}")
    return manifest


def _corrections_examples(args) -> str:
    """Apprentissage des corrections : si `--corrections FICHIER` est fourni,
    lit les corrections (`Path;TargetFolder;NewTitle`) et rend le bloc
    d'exemples few-shot injectable dans CLA-001 — **métadonnées seules**, rendu
    par le moteur (`core.corrections`). `""` sans le flag (comportement inchangé).

    ⚠️ Le few-shot **modifie le prompt** : son efficacité reste à mesurer sur
    modèles réels (harnais d'évaluation, expérience (a)). Le câblage est déterministe."""
    path = getattr(args, "corrections", None)
    if not path:
        return ""
    df_corr = read_corrections_file(Path(path))
    block = render_corrections_examples(df_corr)
    if block:
        n = block.count("\n- ")
        _log(f"✓ Corrections : {n} exemple(s) injecté(s) dans CLA-001")
    else:
        _log("⚠ Corrections : aucun exemple exploitable — classement sans few-shot")
    return block


def _load_directives(args) -> list:
    """Consignes de classement : si `--directives FICHIER` est fourni, lit
    les consignes (texte, une par ligne, `dossier: consigne` ou consigne de fonds,
    marqueur `[+sous-dossiers]` pour autoriser la création) → liste de Directive.
    `[]` sans le flag (comportement inchangé). Rendu et dérivation d'`allowed_parents`
    côté moteur (`core.cla_directives`) — **métadonnées seules**.

    ⚠️ Accueillir des consignes **modifie le prompt** : efficacité à mesurer
    sur modèles réels (métrique `directivesFollowedPct`)."""
    path = getattr(args, "directives", None)
    if not path:
        return []
    directives = read_directives_file(Path(path))
    n_anc = sum(1 for d in directives if d.folder)
    n_crea = sum(1 for d in directives if d.allow_creation)
    _log(
        f"✓ Consignes : {len(directives)} consigne(s) — "
        f"{n_anc} ancrée(s), {n_crea} autorisant la création de sous-dossiers"
    )
    return directives


def _confirm(question: str) -> bool:
    """Confirmation interactive : pose `question` sur **stderr** (le canal
    d'interaction, stdout restant réservé au livrable) et lit la réponse sur
    stdin. Renvoie True seulement sur o/oui/y/yes ; EOF (stdin fermé/non-TTY) ou
    réponse vide = refus — l'écriture par défaut ne se fait pas sans accord."""
    sys.stderr.write(question)
    sys.stderr.flush()
    try:
        answer = input().strip().lower()
    except EOFError:
        sys.stderr.write("\n")
        return False
    return answer in ("o", "oui", "y", "yes")


# ── Fichier de configuration odacea.toml ──────────────────────────────────────
# Précédence CLI > config > .env. Les options surchargeables par le fichier ont
# pour défaut argparse `None` (= « non passé en ligne de commande ») ; après le
# parsing, `_apply_file_config` remplace chaque `None` par la valeur du fichier
# de config si elle existe, sinon par le défaut intégré. Tout le reste du code
# voit donc toujours une valeur concrète.

# Options à valeur directe : (attr, section, clé, défaut intégré).
_CONFIG_VALUE_OPTS = [
    ("model", "llm", "model", None),
    ("base_url", "llm", "base_url", None),
    ("sample_n", "prep", "sample_n", 5),
    ("description", "prep", "description", False),
    ("batch_size", "classement", "batch_size", 0),
    ("ref", "classement", "ref", False),
    ("concurrency", "classement", "concurrency", 1),
]

# Drapeaux « négatifs » (`--no-X`, store_true) : la clé de config est l'option
# *positive* (activer). (attr_cli `no_x`, section, clé positive).
_CONFIG_NEGATED_FLAGS = [
    ("no_filter_columns", "prep", "filter_columns"),
    ("no_clean_dates", "prep", "clean_dates"),
    ("no_sample", "prep", "sample_items"),
    ("no_items", "prep", "include_items"),
    ("no_auto_measures", "prep", "auto_measures"),
    ("no_avis", "classement", "avis"),
]

_MISSING = object()


def _resolve_config_into_args(args, config: dict) -> None:
    """Remplace les valeurs `None` (non passées en CLI) par la config puis par le
    défaut intégré. Appelée même sans fichier de config (`config={}`) pour que
    chaque option ait une valeur concrète."""
    for attr, section, key, builtin in _CONFIG_VALUE_OPTS:
        cur = getattr(args, attr, _MISSING)
        if cur is _MISSING or isinstance(cur, list):
            # Absente de cette sous-commande, ou liste (eval `--model` répétable :
            # une valeur unique de config ne s'y applique pas).
            continue
        if cur is None:
            cfg = section_get(config, section, key)
            setattr(args, attr, cfg if cfg is not None else builtin)

    for attr, section, key in _CONFIG_NEGATED_FLAGS:
        cur = getattr(args, attr, _MISSING)
        if cur is _MISSING:
            continue
        if cur is None:  # `--no-X` non passé : la config peut désactiver l'option
            enabled = section_get(config, section, key)
            setattr(args, attr, enabled is False)
        # `--no-X` passé (True) : la CLI prime, on laisse tel quel.


def _apply_file_config(args) -> None:
    """Charge `odacea.toml` (si pertinent) et l'applique aux options non passées
    en ligne de commande. Quitte avec EXIT_CONFIG_ERROR si le fichier explicite
    est introuvable ou invalide."""
    if not hasattr(args, "config"):
        return  # sous-commande sans options surchargeables (enrich)
    config: dict = {}
    try:
        path = discover_config(args.config)
        if path is not None:
            config, warnings = load_config(path)
            _log(f"⚙ Configuration : {path}")
            for w in warnings:
                _log(f"  ⚠ {w}")
    except ConfigError as e:
        _log(f"✗ {e}")
        sys.exit(EXIT_CONFIG_ERROR)
    _resolve_config_into_args(args, config)


def _build_provider(args):
    model = args.model or DEFAULT_MODEL
    if not model:
        _log("✗ Aucun modèle LLM configuré (--model ou DEFAULT_MODEL dans .env).")
        sys.exit(EXIT_CONFIG_ERROR)
    return get_provider(
        model=model,
        api_key=args.api_key or None,
        base_url=args.base_url or None,
    ), model


# Nombre maximum de lots CLA-001 « en vol » simultanément. Au-delà, le gain
# plafonne et le risque de 429 (limite de débit du fournisseur) augmente.
MAX_CONCURRENCY = 4

# Nombre maximum de variantes d'audit comparées en un appel. Au-delà, le coût
# (N appels LLM complets) dépasse l'intérêt d'un choix par l'archiviste.
MAX_VARIANTS = 5


def _resolve_variants(args) -> int:
    """Nombre de variantes d'audit à produire. 1 par défaut (audit simple),
    borné à `[1, MAX_VARIANTS]` ; une valeur < 1 est invalide."""
    raw = getattr(args, "variants", 1)
    requested = 1 if raw is None else int(raw)
    if requested < 1:
        _log("✗ --variants doit être ≥ 1.")
        sys.exit(EXIT_INPUT_INVALID)
    if requested > MAX_VARIANTS:
        _log(f"⚠ --variants {requested} ramené à {MAX_VARIANTS} (maximum).")
        return MAX_VARIANTS
    return requested


def _resolve_concurrency(args) -> int:
    """Nombre de lots CLA-001 à traiter en parallèle.

    **Séquentiel (1) par défaut.** Une valeur > 1 (option `--concurrency`/config)
    est bornée à `[1, MAX_CONCURRENCY]`. **Forcé séquentiel pour un serveur
    local** (`base_url` renseigné ou préfixe de modèle local) : ces serveurs
    traitent une requête à la fois — paralléliser les sérialiserait de toute
    façon, voire saturerait la machine. L'avertissement est émis sur stderr."""
    requested = int(getattr(args, "concurrency", 1) or 1)
    if requested <= 1:
        return 1
    requested = max(1, min(MAX_CONCURRENCY, requested))
    model = getattr(args, "model", None) or DEFAULT_MODEL
    base_url = getattr(args, "base_url", None) or None
    if is_local(model, base_url):
        _log(
            f"⚠ --concurrency {requested} ignoré : serveur local (mono-requête) "
            "— classement traité séquentiellement."
        )
        return 1
    return requested


class LLMStreamError(RuntimeError):
    """Erreur LLM pendant le stream (réseau, auth, serveur). Levée par
    `_stream_or_raise` ; les commandes du pipeline la convertissent en
    EXIT_LLM_ERROR (`_stream`), le harnais d'évaluation (`cmd_eval`) la
    consigne dans le run concerné et poursuit la matrice."""


def _stream(
    provider, system_prompt: str, user_msg: str, verbose: bool,
    *, cache_user_boundary: str | None = None,
) -> tuple[str, str, float]:
    """Variante « pipeline » de `_stream_or_raise` : toute erreur LLM est fatale."""
    try:
        return _stream_or_raise(
            provider, system_prompt, user_msg, verbose,
            cache_user_boundary=cache_user_boundary,
        )
    except LLMStreamError as e:
        _log(f"\n✗ Erreur LLM : {e}")
        sys.exit(EXIT_LLM_ERROR)


def _stream_or_raise(
    provider, system_prompt: str, user_msg: str, verbose: bool,
    *, cache_user_boundary: str | None = None,
) -> tuple[str, str, float]:
    """Consomme provider.stream_with_reasoning() et retourne (thinking, response, durée).

    La durée (en secondes, horloge monotone) mesure le temps de traitement réel
    du LLM — du premier au dernier chunk — pour la mesure de performance.

    En verbose, écrit les chunks sur stderr en live. Sinon, affiche un compteur
    de progression discret toutes les ~2s. Lève `LLMStreamError` en cas d'échec.
    """
    thinking_text = ""
    full_response = ""
    start = time.monotonic()
    last_tick = start
    chunk_count = 0
    in_thinking_block = False

    # Retry B9 : visibilité immédiate de chaque nouvelle tentative sur stderr.
    provider.on_retry = lambda msg: _log(f"↻ {msg}")

    try:
        for is_thinking, chunk in provider.stream_with_reasoning(
            system_prompt, user_msg, cache_user_boundary=cache_user_boundary
        ):
            chunk_count += 1
            if is_thinking:
                thinking_text += chunk
                if verbose:
                    if not in_thinking_block:
                        sys.stderr.write("\n[🧠 thinking] ")
                        in_thinking_block = True
                    sys.stderr.write(chunk)
                    sys.stderr.flush()
            else:
                full_response += chunk
                if verbose:
                    if in_thinking_block:
                        sys.stderr.write("\n[📝 response] ")
                        in_thinking_block = False
                    sys.stderr.write(chunk)
                    sys.stderr.flush()
                else:
                    now = time.monotonic()
                    if now - last_tick > 2.0:
                        _log(f"  … {len(full_response)} car. reçus")
                        last_tick = now
    except Exception as e:
        raise LLMStreamError(str(e)) from e

    if verbose:
        sys.stderr.write("\n")
        sys.stderr.flush()
    return thinking_text, full_response, time.monotonic() - start


def _load_input_csv(path: Path):
    if not path.exists():
        _log(f"✗ Fichier introuvable : {path}")
        sys.exit(EXIT_INPUT_INVALID)
    try:
        with open(path, "rb") as f:
            df = read_csv(f)
    except Exception as e:
        _log(f"✗ Impossible de lire {path} : {e}")
        sys.exit(EXIT_INPUT_INVALID)

    errors = validate_csv(df)
    if errors:
        _log("✗ CSV invalide :")
        for err in errors:
            _log(f"  • {err}")
        sys.exit(EXIT_INPUT_INVALID)
    return df


def _resolve_input_folder(args) -> None:
    """Prise directe d'un **dossier local** à l'entrée (bypass Archifiltre).

    Si `args.input` désigne un répertoire, on le **scanne** en CSV canonique
    (`core.source_scan`, métadonnées seules, aucun binaire ouvert) écrit dans un
    fichier temporaire, et on redirige `args.input` vers ce CSV — la suite du
    pipeline (audit/classement/run) est inchangée. Un libellé lisible
    (`input_display`) est conservé pour la traçabilité (journal). No-op si l'entrée
    est déjà un fichier CSV.
    """
    raw = getattr(args, "input", None)
    if not isinstance(raw, str) or not Path(raw).is_dir():
        return
    src = Path(raw)
    fd, tmp_path = tempfile.mkstemp(suffix=".csv", prefix="odacea_scan_")
    os.close(fd)
    try:
        stats = write_source_csv(src, Path(tmp_path))
    except SourceScanError as e:
        _log(f"✗ {e}")
        sys.exit(EXIT_INPUT_INVALID)
    _log(
        f"✓ Dossier scanné : {stats['itemCount']} fichier(s), "
        f"{stats['folderCount']} dossier(s) → CSV dérivé"
    )
    if stats["excludedCount"] or stats["skippedSymlinks"]:
        _log(
            f"  ({stats['excludedCount']} entrée(s) système ignorée(s), "
            f"{stats['skippedSymlinks']} lien(s) symbolique(s) non suivi(s))"
        )
    _log(
        "  ⚠ Dates issues de la modification du système de fichiers (pas de dates "
        "métier) — un export Archifiltre reste préférable quand il existe."
    )
    args.input_display = f"{src.name} (dossier local scanné)"
    args.input = tmp_path


def _input_label(args) -> str:
    """Nom lisible du fichier traité pour la traçabilité (journal) : le libellé du
    dossier scanné le cas échéant, sinon le nom du CSV d'entrée."""
    return getattr(args, "input_display", None) or Path(args.input).name


def _load_plan_file(path: Path) -> str:
    """Charge un plan de classement validé (parité CLI du bypass d'audit).

    Accepte deux formats, comme le wizard :
    - un **CSV Resip « dossiers seuls »** (extension `.csv` ou séparateur « ; ») —
      converti par `plan_nodes_from_folders_df` en bloc arborescence canonique
      **parsable par `parse_plan_tree`** (mêmes noms renumérotés que le front) ;
    - sinon, un **Markdown** contenant un bloc « Arborescence technique » (plan
      exporté d'un projet antérieur ou issu de l'audit), lu tel quel.

    Sort en erreur (`EXIT_INPUT_INVALID`) si le fichier est absent ou si le CSV ne
    décrit aucun dossier.
    """
    if not path.exists():
        _log(f"✗ Fichier plan introuvable : {path}")
        sys.exit(EXIT_INPUT_INVALID)
    text = path.read_text(encoding="utf-8")
    if not looks_like_csv(path.name, text):
        return text
    try:
        with open(path, "rb") as f:
            df = read_csv(f)
        nodes, root_title, warnings, _stats = plan_nodes_from_folders_df(df)
    except Exception as e:
        _log(f"✗ Plan CSV « dossiers seuls » illisible ({path}) : {e}")
        sys.exit(EXIT_INPUT_INVALID)
    for w in warnings:
        _log(f"  • {w}")
    return serialize_plan_block(nodes, root_title)


def _resolve_audit_note(args) -> str:
    """Compose la note contextuelle d'audit.

    Combine la note de l'archiviste (`--note`) et un éventuel plan de classement
    de référence fourni via `--reference-plan-file FICHIER`, injecté comme
    contrainte (`--reference-mode inspire|conform`). Le fichier est soit un **CSV
    Resip « dossiers seuls »** (converti en arborescence par
    `build_reference_tree_from_folders`), soit un **bloc d'arborescence brut**
    (toute autre extension). Sans plan de référence, renvoie simplement `--note`
    — comportement inchangé.
    """
    note = getattr(args, "note", "") or ""
    plan_file = getattr(args, "reference_plan_file", None)
    plan = None
    if plan_file:
        path = Path(plan_file)
        if not path.is_file():
            _log(f"✗ Fichier de plan de référence introuvable : {path}")
            sys.exit(EXIT_INPUT_INVALID)
        if path.suffix.lower() == ".csv":
            with open(path, "rb") as f:
                df = read_csv(f)
            errors = validate_csv(df)
            if errors:
                _log("✗ CSV de plan de référence invalide :")
                for err in errors:
                    _log(f"  • {err}")
                sys.exit(EXIT_INPUT_INVALID)
            try:
                tree, warnings, stats = build_reference_tree_from_folders(df)
            except ValueError as e:
                _log(f"✗ {e}")
                sys.exit(EXIT_INPUT_INVALID)
            for w in warnings:
                _log(f"  ⚠ {w}")
            _log(f"→ Plan de référence dérivé de {path} ({stats['folderCount']} dossier(s)).")
        else:
            tree = path.read_text(encoding="utf-8").strip()
            if not tree:
                _log(f"✗ Fichier de plan de référence vide : {path}")
                sys.exit(EXIT_INPUT_INVALID)
            _log(f"→ Plan de référence chargé depuis {path}")
        plan = custom_reference_plan(tree, label=f"Plan de référence ({path.name})")
    mode = getattr(args, "reference_mode", None)
    return compose_observation(note, plan, mode)


# ── Diagnostic à blanc --dry-run ──────────────────────────────────────────────
# Sans aucun appel LLM : prépare le CSV, calcule le digest, assemble les prompts
# AUD-001/CLA-001 et estime le coût en tokens d'entrée. Aide au diagnostic et au
# chiffrage avant de payer un run (ou avant même de disposer d'une clé API).

def _aud_dry_run(df, args, note: str) -> dict:
    """Section dry-run pour AUD-001 : CSV préparé, digest, prompt assemblé, tokens,
    et recommandation de budget d'entrée par taille de vrac."""
    sample_n = 0 if args.no_sample else args.sample_n
    include_items = not getattr(args, "no_items", False)
    clean_dates = not args.no_clean_dates
    filter_columns = not args.no_filter_columns
    include_description = args.description
    brief = getattr(args, "brief", False)
    scan = scan_metadata(df)
    digest = "" if getattr(args, "no_auto_measures", False) else format_digest(scan)
    system_prompt = AUD_001.SYSTEM_PROMPT_BRIEF if brief else AUD_001.SYSTEM_PROMPT

    def _tokens_at(sample_value: int, clean: bool) -> tuple[str, int]:
        prepared = prepare_for_llm(
            df,
            filter_columns=filter_columns,
            clean_dates=clean,
            sample_items_n=sample_value,
            include_description=include_description,
            include_items=include_items,
        )
        text = csv_to_string(prepared)
        msg = AUD_001.build_user_message(
            text, observation=note, metadata_digest=digest, brief=brief
        )
        return text, estimate_text_tokens(system_prompt + msg)

    csv_text, est_tokens = _tokens_at(sample_n, clean_dates)
    df_prepared = prepare_for_llm(
        df, filter_columns=filter_columns, clean_dates=clean_dates,
        sample_items_n=sample_n, include_description=include_description,
        include_items=include_items,
    )
    user_msg = AUD_001.build_user_message(
        csv_text, observation=note, metadata_digest=digest, brief=brief
    )

    # Recommandation de budget d'entrée par taille de vrac. On chiffre aussi
    # les tokens au réglage recommandé pour rendre l'apport tangible (sans LLM).
    item_count = int(scan.get("volumetry", {}).get("items", 0) or 0)
    rec = recommend_prep(item_count)
    rec_tokens = est_tokens
    if rec["sampleN"] != sample_n or rec["cleanDates"] != clean_dates:
        _, rec_tokens = _tokens_at(rec["sampleN"], rec["cleanDates"])

    return {
        "agent": "AUD-001",
        "promptVersion": AUD_001.PROMPT_VERSION,
        "brief": brief,
        "preparedRows": len(df_prepared),
        "preparedColumns": len(df_prepared.columns),
        "preparedCsv": csv_text,
        "digest": digest,
        "estimatedInputTokens": est_tokens,
        "budgetRecommendation": {
            "itemCount": item_count,
            "tier": rec["tier"],
            "currentSampleN": sample_n,
            "currentCleanDates": clean_dates,
            "recommendedSampleN": rec["sampleN"],
            "recommendedCleanDates": rec["cleanDates"],
            "matchesRecommendation": (
                sample_n == rec["sampleN"] and clean_dates == rec["cleanDates"]
            ),
            "estimatedInputTokensAtRecommended": rec_tokens,
            "rationale": rec["rationale"],
            "tableDate": rec["tableDate"],
        },
        "prompts": {"system": system_prompt, "user": user_msg},
    }


def _cla_dry_run(df_original, plan_valide: str, args) -> dict:
    """Section dry-run pour CLA-001. Le prompt et les tokens portent sur le 1er
    lot ; l'estimation de tokens agrège tous les lots (le plan est inclus quand il
    est connu — c'est le cas pour `classement`, pas pour `run` où l'audit ne l'a
    pas encore produit)."""
    df_input = prepare_for_classement(df_original, include_description=args.description)
    ref_mode = getattr(args, "ref", False)
    # Apprentissage des corrections : le dry-run reflète l'éventuel few-shot
    # (--corrections) dans le prompt assemblé et l'estimation de tokens.
    examples = _corrections_examples(args)
    # Consignes de classement : reflétées elles aussi dans le prompt et
    # l'estimation de tokens (le plan n'est connu qu'en `classement`, pas en `run`).
    directives = _load_directives(args)
    directives_block = (
        render_directives(directives, set(parse_plan_tree(plan_valide)))
        if directives else ""
    )
    system_prompt = CLA_001.build_system_prompt(
        avis=not getattr(args, "no_avis", False), ref_mode=ref_mode,
        examples=bool(examples), directives=bool(directives_block),
    )
    n_total = len(df_input)
    batch_size = getattr(args, "batch_size", 0) or 0
    if batch_size > 0 and n_total > batch_size:
        n_batches = math.ceil(n_total / batch_size)
        batches = [df_input.iloc[i * batch_size : (i + 1) * batch_size] for i in range(n_batches)]
    else:
        batches = [df_input]

    def _batch_tokens(batch) -> int:
        msg = CLA_001.build_user_message(
            csv_content=classement_llm_csv(batch, ref_mode=ref_mode),
            plan_valide=plan_valide, ref_mode=ref_mode, examples=examples,
            directives=directives_block,
        )
        return estimate_text_tokens(system_prompt + msg)

    per_batch = [_batch_tokens(b) for b in batches]
    csv_text = classement_llm_csv(batches[0], ref_mode=ref_mode)
    user_msg = CLA_001.build_user_message(
        csv_content=csv_text, plan_valide=plan_valide, ref_mode=ref_mode,
        examples=examples, directives=directives_block,
    )
    return {
        "agent": "CLA-001",
        "promptVersion": CLA_001.PROMPT_VERSION,
        "refMode": ref_mode,
        "itemsTotal": n_total,
        "batches": len(batches),
        "planKnown": bool(plan_valide),
        "preparedCsv": csv_text,
        "estimatedInputTokens": sum(per_batch),
        "estimatedInputTokensPerBatch": per_batch[0] if per_batch else 0,
        "prompts": {"system": system_prompt, "user": user_msg},
    }


def _print_dry_run_human(command: str, model: str | None, sections: list[dict]) -> None:
    """Diagnostic lisible sur **stdout** (la sortie est le livrable du dry-run ;
    les logs restent sur stderr)."""
    print(f"═══ DRY-RUN — {command} (aucun appel LLM) ═══")
    print(f"Modèle prévu : {model or '(non configuré)'}")
    for s in sections:
        print()
        print(f"── {s['agent']} (prompt v{s['promptVersion']}) ──")
        if "preparedRows" in s:
            print(f"CSV préparé : {s['preparedRows']} lignes × {s['preparedColumns']} colonnes")
        if "itemsTotal" in s:
            scope = "(plan inclus)" if s.get("planKnown") else "(plan inconnu à ce stade — sous-estimation)"
            print(f"Items à classer : {s['itemsTotal']} en {s['batches']} lot(s) {scope}")
        cost = s.get("estimatedCostEur")
        cost_suffix = ""
        if cost is not None:
            cost_suffix = (f" → coût d'entrée indicatif : ~{format_cost_eur(cost['totalEur'])}"
                           f" ({cost['label']}, prix du {cost['priceDate']})")
        print(f"Tokens d'entrée estimés (~3,5 car./token) : "
              f"~{format_tokens(s['estimatedInputTokens'])}{cost_suffix}")
        budget = s.get("budgetRecommendation")
        if budget:
            print(format_budget_line(
                {
                    "itemCount": budget["itemCount"],
                    "tier": budget["tier"],
                    "sampleN": budget["recommendedSampleN"],
                    "rationale": budget["rationale"],
                },
                budget["currentSampleN"],
                current_tokens=s["estimatedInputTokens"],
                recommended_tokens=budget["estimatedInputTokensAtRecommended"],
            ))
        if s.get("digest"):
            print("\nMesures automatiques (digest) :")
            print(s["digest"])
        print(f"\n--- {s['agent']} SYSTEM ---")
        print(s["prompts"]["system"])
        print(f"\n--- {s['agent']} USER (CSV préparé inclus) ---")
        print(s["prompts"]["user"])


def _emit_dry_run(args, command: str, sections: list[dict], extra: dict | None = None) -> int:
    """Émet le diagnostic dry-run : JSON sur stdout en mode `--json`, sinon
    texte lisible sur stdout. Retourne toujours EXIT_OK (aucun appel LLM)."""
    model = (getattr(args, "model", None) or DEFAULT_MODEL) or None
    base_url = getattr(args, "base_url", None) or None
    # Coût d'entrée indicatif : à côté de l'estimation de tokens, par agent
    # et au total. `None` pour un modèle local ou cloud inconnu (rien à afficher).
    total_input_tokens = 0
    for s in sections:
        tokens = s.get("estimatedInputTokens", 0)
        total_input_tokens += tokens
        if model:
            s["estimatedCostEur"] = estimate_cost_eur(
                model=model, base_url=base_url, input_tokens=tokens
            )
    total_cost = (
        estimate_cost_eur(model=model, base_url=base_url, input_tokens=total_input_tokens)
        if model else None
    )
    payload = {
        "command": command,
        "dryRun": True,
        "ok": True,
        "exitCode": EXIT_OK,
        "model": model,
        "estimatedInputTokens": total_input_tokens,
        "estimatedCostEur": total_cost,
        "agents": sections,
    }
    if extra:
        payload.update(extra)
    if getattr(args, "json", False):
        _emit_json(args, payload)
    else:
        _print_dry_run_human(command, model, sections)
        if len(sections) > 1:
            print()
            total_suffix = (f" → coût d'entrée indicatif : ~{format_cost_eur(total_cost['totalEur'])}"
                            f" ({total_cost['label']}, prix du {total_cost['priceDate']})"
                            if total_cost is not None else "")
            print(f"TOTAL tokens d'entrée estimés : "
                  f"~{format_tokens(total_input_tokens)}{total_suffix}")
    return EXIT_OK


# ── Sous-commandes ───────────────────────────────────────────────────────────

def cmd_enrich(args) -> int:
    input_path = Path(args.input)
    source_root = Path(args.source_root)
    if not source_root.is_dir():
        _log(f"✗ Dossier source introuvable : {source_root}")
        return EXIT_INPUT_INVALID

    df = _load_input_csv(input_path)
    _log(f"✓ CSV chargé : {len(df)} lignes")

    # Message clair sur l'accès aux données — cette étape OUVRE le contenu
    # des fichiers (contrairement au reste du moteur). Tout reste en local.
    # Texte partagé avec le backend `/enrich` : source unique.
    notice = content_access_notice_lines(source_root)
    _log("")
    _log(f"ℹ️  {notice[0]}")
    for line in notice[1:]:
        _log(f"   {line}")
    _log("")

    def _progress(file_value: str) -> None:
        if args.verbose:
            _log(f"  → {file_value}")

    df_out = df
    report = None
    if not getattr(args, "fingerprint_only", False):
        df_out, report = enrich_descriptions(
            df_out,
            source_root,
            overwrite=args.overwrite,
            max_chars=args.max_chars,
            on_progress=_progress,
        )
        for line in report.summary_lines():
            _log(f"  • {line}")
        for err in report.errors[:20]:
            _log(f"    ⚠ {err}")

    # Empreinte SHA-256 (opt-in) : doublons stricts confirmés par hash.
    fp_report = None
    duplicates_json = None
    if getattr(args, "fingerprint", False) or getattr(args, "fingerprint_only", False):
        _log("")
        _log("ℹ️  Empreinte SHA-256 — lecture binaire de chaque fichier (local).")
        df_out, fp_report = fingerprint_files(
            df_out,
            source_root,
            overwrite=args.overwrite,
            on_progress=_progress,
        )
        for line in fp_report.summary_lines():
            _log(f"  • {line}")
        for err in fp_report.errors[:20]:
            _log(f"    ⚠ {err}")

        # Rapport déterministe des groupes identiques (même logique que le digest).
        dups = scan_metadata(df_out).get("strictDuplicates", {})
        duplicates_json = {
            "groups": dups.get("total", 0),
            "files": dups.get("files", 0),
            "redundant": dups.get("redundant", 0),
            "examples": dups.get("examples", []),
        }
        if dups.get("total"):
            _log(
                f"  • Doublons stricts : {dups['total']} groupe(s) "
                f"({dups['redundant']} redondance(s) supprimable(s))"
            )
            for e in dups.get("examples", []):
                _log(f"    ↳ {e['count']}× {' = '.join(e['names'])} [{e['hash']}…]")
        else:
            _log("  • Doublons stricts : aucun fichier binairement identique détecté")

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = input_path.with_name(f"{input_path.stem}_enrichi{input_path.suffix}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(out_path, index=False, sep=";", quoting=csv_mod.QUOTE_ALL, encoding="utf-8-sig")
    _log(f"✓ CSV enrichi écrit : {out_path}")

    payload: dict = {
        "command": "enrich",
        "ok": True,
        "exitCode": EXIT_OK,
        "paths": {"out": str(out_path)},
    }
    if report is not None:
        payload["report"] = {
            "totalItems": report.total_items,
            "enriched": report.enriched,
            "alreadyFilled": report.already_filled,
            "noText": report.no_text,
            "unsupported": report.unsupported,
            "missing": report.missing,
            "errors": len(report.errors),
        }
    if fp_report is not None:
        payload["fingerprint"] = {
            "totalItems": fp_report.total_items,
            "hashed": fp_report.hashed,
            "alreadyHashed": fp_report.already_hashed,
            "missing": fp_report.missing,
            "skipped": fp_report.skipped,
            "errors": len(fp_report.errors),
        }
        payload["duplicates"] = duplicates_json
    _emit_json(args, payload)
    return EXIT_OK


def cmd_audit(args) -> int:
    _resolve_input_folder(args)  # Dossier local à l'entrée (bypass Archifiltre)
    note = _resolve_audit_note(args)
    if getattr(args, "dry_run", False):
        df = _load_input_csv(Path(args.input))
        _log(f"✓ CSV chargé : {len(df)} lignes (dry-run — aucun appel LLM)")
        return _emit_dry_run(args, "audit", [_aud_dry_run(df, args, note)])
    if _resolve_variants(args) > 1:
        return _cmd_audit_variants(args, note)
    result = _run_audit(
        input_path=Path(args.input),
        out_report=Path(args.out_report) if args.out_report else None,
        out_plan=Path(args.out_plan) if args.out_plan else None,
        out_notes=Path(args.out_notes) if args.out_notes else None,
        note=note,
        args=args,
    )
    summary = _audit_summary(result)
    journal = _maybe_write_journal(
        args,
        command="audit",
        input_name=_input_label(args),
        model=summary.get("model"),
        prompt_versions={"AUD-001": AUD_001.PROMPT_VERSION},
        duration_s=summary.get("durationS"),
        rows=summary.get("rows"),
        usage=summary.get("usage"),
        resumed=summary.get("resumed", False),
        ok=summary.get("ok", True),
        exit_code=summary.get("exitCode", EXIT_OK),
        warnings=[] if summary.get("planExtracted") else ["Plan non extrait du rapport d'audit."],
        description_sent=bool(getattr(args, "description", False)),
    )
    if journal is not None:
        summary = {**summary, "journal": journal}
    _emit_json(args, summary)
    return EXIT_OK


def _audit_summary(result: dict) -> dict:
    """Résumé machine d'un run d'audit, dérivé du dict de `_run_audit`."""
    return {
        "command": "audit",
        "ok": True,
        "exitCode": EXIT_OK,
        "model": result.get("model"),
        "rows": result.get("rows"),
        "durationS": round(result.get("duration", 0.0), 2),
        "usage": result.get("usage"),
        "resumed": result.get("resumed", False),
        "planExtracted": bool(result.get("plan")),
        "promptVersion": AUD_001.PROMPT_VERSION,
        "paths": result.get("paths", {}),
    }


def _cmd_audit_variants(args, note: str) -> int:
    """Audit comparatif multi-plans : lance AUD-001 N fois sur le même vrac
    et compare les plans obtenus pour que l'archiviste choisisse.

    Le CSV est préparé et le prompt assemblé **une seule fois** (entrée identique
    d'une variante à l'autre — c'est la stochasticité du modèle qui les
    différencie) ; seul l'appel LLM est répété. Avec --out-dir, chaque variante
    est écrite séparément (`variante-K_rapport/plan/notes.md`) aux côtés d'un
    `comparaison.json`. La présentation côte à côte appartient au front ; le
    moteur fournit ici la comparaison structurelle déterministe.
    """
    n = _resolve_variants(args)
    df = _load_input_csv(Path(args.input))
    _log(f"✓ CSV chargé : {len(df)} lignes — audit comparatif sur {n} variantes")

    sample_n = 0 if args.no_sample else args.sample_n
    df_prepared = prepare_for_llm(
        df,
        filter_columns=not args.no_filter_columns,
        clean_dates=not args.no_clean_dates,
        sample_items_n=sample_n,
        include_description=args.description,
        include_items=not args.no_items,
    )
    brief = getattr(args, "brief", False)
    csv_text = csv_to_string(df_prepared)
    scan = scan_metadata(df)
    digest = "" if getattr(args, "no_auto_measures", False) else format_digest(scan)
    user_msg = AUD_001.build_user_message(
        csv_text, observation=note, metadata_digest=digest, brief=brief
    )
    system_prompt = AUD_001.SYSTEM_PROMPT_BRIEF if brief else AUD_001.SYSTEM_PROMPT

    provider, model = _build_provider(args)
    out_dir = Path(args.out_dir) if getattr(args, "out_dir", None) else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    plans: list[str] = []
    variant_summaries: list[dict] = []
    for i in range(1, n + 1):
        _log(f"→ Variante {i}/{n} — AUD-001{' (mode plan seul)' if brief else ''} (modèle : {model})…")
        _, full_response, elapsed = _stream(provider, system_prompt, user_msg, args.verbose)
        usage = provider.last_usage
        sections = extract_plans(full_response)
        plan = sections.get("plan", "")
        notes = sections.get("notes", "")
        plans.append(plan)
        _log(f"✓ Variante {i} reçue ({len(full_response)} car.) en {format_duration(elapsed)}")

        paths: dict = {}
        if out_dir:
            rpt = out_dir / f"variante-{i}_rapport.md"
            pln = out_dir / f"variante-{i}_plan.md"
            nts = out_dir / f"variante-{i}_notes.md"
            rpt.write_text(full_response, encoding="utf-8")
            pln.write_text(plan, encoding="utf-8")
            nts.write_text(notes, encoding="utf-8")
            paths = {"report": str(rpt), "plan": str(pln), "notes": str(nts)}

        variant_summaries.append({
            "index": i,
            "durationS": round(elapsed, 2),
            "usage": usage,
            "planExtracted": bool(plan.strip()),
            "metrics": audit_metrics(full_response, scan, brief=brief),
            "paths": paths,
        })

    comparison = compare_plan_variants(plans)
    # Fusionne la forme structurelle (compare_plan_variants) dans chaque résumé.
    for summary, shape in zip(variant_summaries, comparison["variants"], strict=True):
        summary["structure"] = shape

    if out_dir:
        comp_path = out_dir / "comparaison.json"
        comp_path.write_text(
            json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _log(f"✓ Comparaison écrite : {comp_path}")

    _log("")
    _log(format_comparison_table(comparison))

    _emit_json(args, {
        "command": "audit",
        "ok": True,
        "exitCode": EXIT_OK,
        "model": model,
        "rows": len(df),
        "variants": variant_summaries,
        "comparison": comparison["comparison"],
        "promptVersion": AUD_001.PROMPT_VERSION,
    })
    return EXIT_OK


def _run_audit(*, input_path, out_report, out_plan, out_notes, note, args, resume=False):
    df = _load_input_csv(input_path)
    _log(f"✓ CSV chargé : {len(df)} lignes, {len(df.columns)} colonnes")

    usage: dict | None = None
    model: str | None = None
    was_resumed = False
    # Reprise : un rapport déjà produit par un run interrompu est réutilisé
    # tel quel — l'appel LLM (la partie coûteuse) n'est pas repayé.
    if resume and out_report and out_report.is_file() and out_report.read_text(encoding="utf-8").strip():
        full_response = out_report.read_text(encoding="utf-8")
        _log(f"↩ Audit repris depuis {out_report} ({len(full_response)} car.) — appel LLM évité")
        elapsed = 0.0
        was_resumed = True
    else:
        sample_n = 0 if args.no_sample else args.sample_n
        df_prepared = prepare_for_llm(
            df,
            filter_columns=not args.no_filter_columns,
            clean_dates=not args.no_clean_dates,
            sample_items_n=sample_n,
            include_description=args.description,
            include_items=not args.no_items,
        )
        _log(f"→ CSV préparé pour LLM : {len(df_prepared)} lignes, {len(df_prepared.columns)} colonnes")

        brief = getattr(args, "brief", False)
        csv_text = csv_to_string(df_prepared)
        digest = "" if getattr(args, "no_auto_measures", False) else format_digest(scan_metadata(df))
        user_msg = AUD_001.build_user_message(
            csv_text, observation=note, metadata_digest=digest, brief=brief
        )

        system_prompt = AUD_001.SYSTEM_PROMPT_BRIEF if brief else AUD_001.SYSTEM_PROMPT
        provider, model = _build_provider(args)
        _log(f"→ Audit AUD-001{' (mode plan seul)' if brief else ''} (modèle : {model})…")

        _, full_response, elapsed = _stream(provider, system_prompt, user_msg, args.verbose)
        usage = provider.last_usage
        _log(f"✓ Réponse reçue ({len(full_response)} car.) en {format_duration(elapsed)}")

    sections = extract_plans(full_response)
    plan = sections.get("plan", "")
    notes = sections.get("notes", "")
    if not plan:
        _log("⚠ Section 'plan' non détectée dans la réponse LLM (rapport sauvegardé tout de même).")

    if out_report:
        out_report.write_text(full_response, encoding="utf-8")
        _log(f"✓ Rapport écrit : {out_report}")
    if out_plan:
        out_plan.write_text(plan, encoding="utf-8")
        _log(f"✓ Plan écrit : {out_plan} ({len(plan)} car.)")
    if out_notes:
        out_notes.write_text(notes, encoding="utf-8")
        _log(f"✓ Notes écrites : {out_notes} ({len(notes)} car.)")

    return {"report": full_response, "plan": plan, "notes": notes,
            "df_original": df, "duration": elapsed, "usage": usage,
            "model": model, "rows": len(df), "resumed": was_resumed,
            "paths": {
                "report": str(out_report) if out_report else None,
                "plan": str(out_plan) if out_plan else None,
                "notes": str(out_notes) if out_notes else None,
            }}


def cmd_classement(args) -> int:
    _resolve_input_folder(args)  # Dossier local à l'entrée (bypass Archifiltre)
    # `--plan` accepte un CSV Resip « dossiers seuls » (converti en bloc
    # arborescence canonique) autant qu'un Markdown de plan.
    plan_valide = _load_plan_file(Path(args.plan))

    if getattr(args, "corrections", None) and not Path(args.corrections).exists():
        _log(f"✗ Fichier de corrections introuvable : {args.corrections}")
        return EXIT_INPUT_INVALID
    if getattr(args, "directives", None) and not Path(args.directives).exists():
        _log(f"✗ Fichier de consignes introuvable : {args.directives}")
        return EXIT_INPUT_INVALID

    df_original = _load_input_csv(Path(args.input))
    if getattr(args, "dry_run", False):
        _log(f"✓ CSV chargé : {len(df_original)} lignes (dry-run — aucun appel LLM)")
        return _emit_dry_run(args, "classement", [_cla_dry_run(df_original, plan_valide, args)])
    if not args.out:
        _log("✗ --out est requis (chemin du CSV RESIP de sortie) hors --dry-run.")
        return EXIT_INPUT_INVALID
    out_path = Path(args.out)
    raw_dir = Path(args.raw_dir) if getattr(args, "raw_dir", None) else None
    result = _run_classement(
        df_original=df_original,
        plan_valide=plan_valide,
        out_path=out_path,
        args=args,
        raw_dir=raw_dir,
        resume=getattr(args, "resume", False),
        interactive=getattr(args, "interactive", False),
    )
    summary = _classement_summary(result)
    journal = _maybe_write_journal(
        args,
        command="classement",
        input_name=_input_label(args),
        model=summary.get("model"),
        prompt_versions={"CLA-001": CLA_001.PROMPT_VERSION},
        duration_s=summary.get("durationS"),
        rows=summary.get("rowsTotal"),
        usage=summary.get("usage"),
        ok=summary.get("ok", True),
        exit_code=summary.get("exitCode", EXIT_OK),
        warnings=summary.get("warnings", []),
        conformity=summary.get("stats"),
        description_sent=bool(getattr(args, "description", False)),
        # `classement` part d'un plan fourni (aucun audit LLM dans cette commande).
        plan_origin="fourni",
    )
    if journal is not None:
        summary = {**summary, "journal": journal}
    _emit_json(args, summary)
    return result["exitCode"]


def _classement_summary(result: dict) -> dict:
    """Résumé machine d'un run de classement, dérivé du dict de
    `_run_classement` (succès comme erreur)."""
    code = result["exitCode"]
    summary = {
        "command": "classement",
        "ok": code == EXIT_OK,
        "exitCode": code,
        "model": result.get("model"),
        "promptVersion": CLA_001.PROMPT_VERSION,
    }
    if code == EXIT_OK:
        summary.update({
            "durationS": result.get("durationS"),
            "usage": result.get("usage"),
            "rowsTotal": result.get("rowsTotal"),
            "recordGroups": result.get("recordGroups"),
            "items": result.get("items"),
            "stats": result.get("stats"),
            "warnings": result.get("warnings", []),
            # written=False quand --interactive a été refusé : aucun CSV écrit.
            "written": result.get("written", True),
            "paths": result.get("paths", {}),
        })
        # Manifeste d'arborescence modèle — présent seulement si --manifest.
        if result.get("manifest") is not None:
            summary["manifest"] = result["manifest"]
    return summary


def _save_raw(raw_dir: Path | None, name: str, text: str) -> None:
    """Artefact de run : réponse LLM brute, base de la reprise --resume."""
    if raw_dir is None:
        return
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / name).write_text(text, encoding="utf-8")


def _load_raw(raw_dir: Path | None, name: str, resume: bool) -> str | None:
    """Réponse brute sauvegardée par un run précédent, si reprise demandée."""
    if not resume or raw_dir is None:
        return None
    path = raw_dir / name
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if text.strip():
            return text
    return None


def _log_classement_conformity(n_rg: int, n_items: int, stats: dict) -> None:
    """Aperçu de conformité sur stderr : volumétrie produite, respect du plan
    d'audit et items à cible malformée. Émis **avant** l'écriture du CSV pour que
    `--interactive` puisse demander une confirmation en connaissance de cause."""
    _log(f"  → {n_rg} dossier(s), {n_items} item(s) classé(s)")
    if not stats.get("planParsed"):
        _log("  → Respect du plan : non mesurable (arborescence du plan illisible)")
    elif stats.get("planMatches"):
        _log("  → Respect du plan : arborescence identique au plan d'audit ✓")
    else:
        off = stats.get("foldersOffPlan", [])
        miss = stats.get("foldersMissing", [])
        _log(f"  → Respect du plan : écart(s) — {len(off)} dossier(s) hors plan, {len(miss)} dossier(s) du plan non réalisé(s)")
        for f in off:
            _log(f"      • hors plan : {f}")
        for f in miss:
            _log(f"      • non réalisé : {f}")
    if stats.get("itemsMalformed"):
        _log(f"  → {stats['itemsMalformed']} item(s) à cible malformée rattaché(s) à la racine")


def _run_classement(*, df_original, plan_valide, out_path, args, raw_dir=None,
                    resume=False, interactive=False) -> dict:
    """Exécute le classement CLA-001. Retourne un dict-résumé :
    `exitCode` + `paths`/`stats`/`usage`/`durationS`… sur succès comme sur erreur
    (les erreurs portent un `exitCode` non nul et restent loggées sur stderr).

    Si `interactive`, l'aperçu de conformité au plan est affiché puis une
    confirmation est demandée **avant** d'écrire le CSV : un refus n'écrit rien
    (`exitCode` EXIT_OK, `written=False`) — utile en pipeline semi-automatique."""
    _log("→ Préparation des items à classer…")
    df_input = prepare_for_classement(df_original, include_description=args.description)
    n_total = len(df_input)
    _log(f"✓ {n_total} item(s) à classer")

    batch_size = getattr(args, "batch_size", 0) or 0
    cla_duration = 0.0
    usages: list[dict | None] = []
    # Méthode d'identifiant : « Ref » (court, rapide) si --ref, sinon « Path »
    # historique (recopie du chemin complet, ancrage plus fort).
    ref_mode = getattr(args, "ref", False)
    id_col = "Ref" if ref_mode else "Path"
    # Apprentissage des corrections : exemples few-shot issus de --corrections
    # (vide sans le flag → prompt inchangé). Constants sur tout le run (mêmes
    # corrections du fonds) → dans le préfixe stable mis en cache.
    examples = _corrections_examples(args)
    # Consignes de classement : rendu du bloc + dossiers à création
    # autorisée, dérivés côté moteur. Constants sur tout le run → préfixe caché.
    directives = _load_directives(args)
    plan_folder_names = set(parse_plan_tree(plan_valide))
    directives_block = render_directives(directives, plan_folder_names) if directives else ""
    allowed = directives_allowed_parents(directives, plan_folder_names) if directives else set()
    # Avis de classement (« Démarche de l'IA ») dans le prompt — désactivable.
    system_prompt = CLA_001.build_system_prompt(
        avis=not getattr(args, "no_avis", False), ref_mode=ref_mode,
        examples=bool(examples), directives=bool(directives_block),
    )
    # Provider construit paresseusement : une reprise intégrale (tous les lots
    # déjà sur disque) n'exige aucune configuration LLM.
    provider = None
    model = None

    def _user_msg_for(df_batch) -> str:
        return CLA_001.build_user_message(
            csv_content=classement_llm_csv(df_batch, ref_mode=ref_mode),
            plan_valide=plan_valide, ref_mode=ref_mode, examples=examples,
            directives=directives_block,
        )

    def _llm_response_for(df_batch, raw_name: str, label: str) -> str:
        """Réponse LLM d'un lot (chemin séquentiel) : reprise depuis l'artefact
        brut si disponible (l'appel n'est pas repayé), sinon appel streamé
        + sauvegarde. Provider construit paresseusement et partagé entre lots."""
        nonlocal provider, model, cla_duration
        cached = _load_raw(raw_dir, raw_name, resume)
        if cached is not None:
            _log(f"↩ {label} repris depuis {raw_dir / raw_name} — appel LLM évité")
            return cached
        if provider is None:
            provider, model = _build_provider(args)
        _log(f"→ {label} — CLA-001 (modèle : {model})…")
        _, llm_response, elapsed = _stream(
            provider, system_prompt, _user_msg_for(df_batch), args.verbose,
            cache_user_boundary=CLA_001.CACHE_BOUNDARY,
        )
        cla_duration += elapsed
        usages.append(provider.last_usage)
        _log(f"✓ {label} — réponse reçue ({len(llm_response)} car.) en {format_duration(elapsed)}")
        _save_raw(raw_dir, raw_name, llm_response)
        return llm_response

    def _llm_response_isolated(df_batch, raw_name: str, label: str) -> tuple[str, float, dict | None]:
        """Réponse LLM d'un lot **isolée pour exécution concurrente**.

        Chaque appel construit son **propre** provider : l'état mutable du
        provider (`last_usage`, `on_retry`, compteur de retries) n'est jamais
        partagé entre threads. Lève `LLMStreamError` sur échec LLM (capturé par
        l'orchestrateur). La reprise (`--resume`) est gérée en amont."""
        own_provider = get_provider(
            model=model, api_key=args.api_key or None, base_url=args.base_url or None
        )
        _log(f"→ {label} — CLA-001 (modèle : {model})…")
        _, llm_response, elapsed = _stream_or_raise(
            own_provider, system_prompt, _user_msg_for(df_batch), args.verbose,
            cache_user_boundary=CLA_001.CACHE_BOUNDARY,
        )
        _log(f"✓ {label} — réponse reçue ({len(llm_response)} car.) en {format_duration(elapsed)}")
        _save_raw(raw_dir, raw_name, llm_response)
        return llm_response, elapsed, own_provider.last_usage

    def _classement_batches_parallel(batch_slices, n_batches, concurrency) -> list[str] | None:
        """Traite les lots avec jusqu'à `concurrency` appels LLM en vol.

        Reprend d'abord les lots déjà sur disque (sans LLM), puis lance les
        lots restants dans un pool de threads. Retourne les réponses **dans
        l'ordre des lots**, ou `None` sur erreur LLM (déjà loggée)."""
        nonlocal provider, model, cla_duration
        responses: list[str | None] = [None] * n_batches
        pending: list[int] = []
        for i in range(n_batches):
            raw_name = f"cla_lot_{i + 1:03d}.txt"
            cached = _load_raw(raw_dir, raw_name, resume)
            if cached is not None:
                _log(f"↩ Lot {i + 1}/{n_batches} repris depuis {raw_dir / raw_name} — appel LLM évité")
                responses[i] = cached
            else:
                pending.append(i)
        if not pending:
            return [r or "" for r in responses]
        # Valide la configuration LLM une fois (modèle requis) avant de paralléliser.
        _, model = _build_provider(args)
        wall_start = time.monotonic()
        try:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {
                    pool.submit(
                        _llm_response_isolated,
                        batch_slices[i], f"cla_lot_{i + 1:03d}.txt",
                        f"Lot {i + 1}/{n_batches} ({len(batch_slices[i])} items)",
                    ): i
                    for i in pending
                }
                for fut in as_completed(futures):
                    i = futures[fut]
                    resp, _elapsed, usage = fut.result()
                    responses[i] = resp
                    usages.append(usage)
        except LLMStreamError as e:
            _log(f"\n✗ Erreur LLM : {e}")
            return None
        # En parallèle, la durée pertinente est le temps mural de la phase (pas la
        # somme des lots, qui se recouvrent).
        cla_duration += time.monotonic() - wall_start
        return [r or "" for r in responses]

    concurrency = _resolve_concurrency(args)

    if batch_size > 0 and n_total > batch_size:
        n_batches = math.ceil(n_total / batch_size)
        batch_slices = [
            df_input.iloc[i * batch_size : (i + 1) * batch_size] for i in range(n_batches)
        ]
        if concurrency > 1:
            _log(f"→ Traitement par lots : {n_batches} lot(s) de {batch_size} items max "
                 f"— jusqu'à {concurrency} appel(s) en parallèle")
            responses = _classement_batches_parallel(batch_slices, n_batches, concurrency)
            if responses is None:
                return {"exitCode": EXIT_LLM_ERROR, "model": model}
        else:
            _log(f"→ Traitement par lots : {n_batches} lot(s) de {batch_size} items max")
            responses = [
                _llm_response_for(batch_slices[i], f"cla_lot_{i + 1:03d}.txt",
                                  f"Lot {i + 1}/{n_batches} ({len(batch_slices[i])} items)")
                for i in range(n_batches)
            ]
        df_llm_parts = []
        for i, llm_response in enumerate(responses):
            try:
                df_llm_parts.append(extract_csv_from_response(llm_response, id_col=id_col))
            except Exception as e:
                _log(f"✗ Lot {i + 1}/{n_batches} — impossible d'extraire un CSV : {e}")
                return {"exitCode": EXIT_OUTPUT_INVALID, "model": model}
        df_llm = pd.concat(df_llm_parts, ignore_index=True)
        _log(f"✓ Tous les lots traités — {len(df_llm)} ligne(s) LLM au total en {format_duration(cla_duration)}")
    else:
        llm_response = _llm_response_for(df_input, "cla_complet.txt", "Classement")
        try:
            df_llm = extract_csv_from_response(llm_response, id_col=id_col)
        except Exception as e:
            _log(f"✗ Impossible d'extraire un CSV de la réponse LLM : {e}")
            return {"exitCode": EXIT_OUTPUT_INVALID, "model": model}

    try:
        df_final, warnings_list, stats = convert_classement_to_resip(
            df_llm, df_original, plan_valide, allowed_parents=allowed
        )
    except Exception as e:
        _log(f"✗ Conversion RESIP impossible : {e}")
        return {"exitCode": EXIT_OUTPUT_INVALID, "model": model}

    # Option d'export : retrait des numéros de position des noms de dossier —
    # après conversion (stats de conformité calculées sur le plan numéroté), avant
    # écriture. Le CSV, le manifeste et une copie physique (apply) en héritent.
    if getattr(args, "no_folder_numbers", False):
        df_final, renamed = strip_folder_numbers(df_final)
        warnings_list = list(warnings_list) + renamed

    if warnings_list:
        _log(f"⚠ {len(warnings_list)} avertissement(s) de conversion :")
        for w in warnings_list:
            _log(f"  • {w}")

    n_items = int((df_final["Content.DescriptionLevel"] == "Item").sum())
    n_rg = int((df_final["Content.DescriptionLevel"] == "RecordGrp").sum())
    # Aperçu de conformité affiché AVANT toute écriture — base de la
    # confirmation interactive.
    _log_classement_conformity(n_rg, n_items, stats)

    base_summary = {
        "model": model,
        "durationS": round(cla_duration, 2),
        "usage": sum_usage(usages),
        "rowsTotal": int(len(df_final)),
        "recordGroups": n_rg,
        "items": n_items,
        "warnings": list(warnings_list),
        "stats": stats,
    }

    if interactive and not _confirm(f"› Écrire le CSV RESIP dans {out_path} ? [o/N] "):
        _log("✗ Écriture annulée (--interactive) — aucun fichier produit.")
        return {**base_summary, "exitCode": EXIT_OK, "written": False, "paths": {}}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_final.to_csv(out_path, index=False, sep=";", quoting=csv_mod.QUOTE_ALL, encoding="utf-8")
    _log(f"✓ CSV RESIP écrit : {out_path} ({len(df_final)} lignes)")
    _log(f"  ⏱ Classement traité en {format_duration(cla_duration)}")

    # Manifeste d'arborescence modèle — opt-in, dérivé du SIP produit.
    paths = {"out": str(out_path)}
    manifest = _maybe_write_manifest(args, df_final)
    if manifest is not None:
        paths["manifest"] = str(Path(args.manifest))

    result = {**base_summary, "exitCode": EXIT_OK, "written": True, "paths": paths}
    if manifest is not None:
        result["manifest"] = manifest
    return result


# ── Harnais d'évaluation des prompts ─────────────────────────────────────────

def _eval_audit_run(df, scan, model, args, prep_override: dict | None = None) -> tuple[dict, str | None]:
    """Un run AUD-001 de la matrice d'éval. Retourne (run, plan_extrait).

    `prep_override` (sweep) force `sampleN`/`cleanDates` pour mesurer l'apport
    du budget d'entrée sur la qualité ; `None` = réglages de `args`."""
    sample_n = 0 if args.no_sample else args.sample_n
    clean_dates = not args.no_clean_dates
    if prep_override:
        if prep_override.get("sampleN") is not None:
            sample_n = prep_override["sampleN"]
        if prep_override.get("cleanDates") is not None:
            clean_dates = prep_override["cleanDates"]
    run: dict = {
        "dataset": None, "model": model, "agent": "AUD-001",
        "brief": bool(args.brief), "mode": None,
        "prep": {"sampleN": sample_n, "cleanDates": clean_dates},
        "durationS": None, "usage": None, "metrics": None, "error": None,
    }
    plan: str | None = None
    try:
        provider = get_provider(
            model=model, api_key=args.api_key or None, base_url=args.base_url or None
        )
        df_prepared = prepare_for_llm(
            df,
            filter_columns=not args.no_filter_columns,
            clean_dates=clean_dates,
            sample_items_n=sample_n,
            include_description=args.description,
            include_items=not args.no_items,
        )
        digest = "" if args.no_auto_measures else format_digest(scan)
        user_msg = AUD_001.build_user_message(
            csv_to_string(df_prepared),
            observation=args.note or "",
            metadata_digest=digest,
            brief=args.brief,
        )
        system_prompt = AUD_001.SYSTEM_PROMPT_BRIEF if args.brief else AUD_001.SYSTEM_PROMPT
        _log(f"→ AUD-001 ({model})…")
        _, response, elapsed = _stream_or_raise(provider, system_prompt, user_msg, args.verbose)
        run["durationS"] = round(elapsed, 2)
        run["usage"] = provider.last_usage
        run["metrics"] = audit_metrics(response, scan=scan, brief=args.brief)
        plan = extract_plans(response).get("plan") or None
        _log(f"✓ AUD-001 — {len(response)} car. en {format_duration(elapsed)}")
    except LLMStreamError as e:
        run["error"] = str(e)
        _log(f"✗ AUD-001 ({model}) : {e}")
    return run, plan


def _eval_classement_run(df_original, plan_valide, model, ref_mode, args) -> dict:
    """Un run CLA-001 de la matrice d'éval (un mode d'identifiant donné)."""
    mode_label = "ref" if ref_mode else "path"
    run: dict = {
        "dataset": None, "model": model, "agent": "CLA-001",
        "brief": False, "mode": mode_label,
        "durationS": None, "usage": None, "metrics": None, "error": None,
    }
    try:
        provider = get_provider(
            model=model, api_key=args.api_key or None, base_url=args.base_url or None
        )
        df_input = prepare_for_classement(df_original, include_description=args.description)
        id_col = "Ref" if ref_mode else "Path"
        # Apprentissage des corrections : few-shot issu de --corrections (vide
        # sans le flag → prompt byte-identique). Constant sur tout le run.
        examples = _corrections_examples(args)
        system_prompt = CLA_001.build_system_prompt(
            avis=not args.no_avis, ref_mode=ref_mode, examples=bool(examples)
        )

        batch_size = args.batch_size or 0
        n_total = len(df_input)
        if batch_size > 0 and n_total > batch_size:
            n_batches = math.ceil(n_total / batch_size)
            batches = [
                df_input.iloc[i * batch_size : (i + 1) * batch_size]
                for i in range(n_batches)
            ]
        else:
            batches = [df_input]

        duration = 0.0
        usages: list[dict | None] = []
        df_llm_parts = []
        for i, df_batch in enumerate(batches):
            _log(f"→ CLA-001 [{mode_label}] ({model}) — lot {i + 1}/{len(batches)}…")
            user_msg = CLA_001.build_user_message(
                csv_content=classement_llm_csv(df_batch, ref_mode=ref_mode),
                plan_valide=plan_valide,
                ref_mode=ref_mode,
                examples=examples,
            )
            _, response, elapsed = _stream_or_raise(
                provider, system_prompt, user_msg, args.verbose,
                cache_user_boundary=CLA_001.CACHE_BOUNDARY,
            )
            duration += elapsed
            usages.append(provider.last_usage)
            df_llm_parts.append(extract_csv_from_response(response, id_col=id_col))

        df_llm = pd.concat(df_llm_parts, ignore_index=True)
        _, _, stats = convert_classement_to_resip(df_llm, df_original, plan_valide)
        run["durationS"] = round(duration, 2)
        run["usage"] = sum_usage(usages)
        run["metrics"] = classement_metrics(stats)
        _log(f"✓ CLA-001 [{mode_label}] — {stats.get('itemsClassified', 0)}/"
             f"{stats.get('itemsTotal', 0)} classés en {format_duration(duration)}")
    except Exception as e:
        # Matrice tolérante : erreur LLM, extraction ou conversion impossible —
        # le run est consigné en erreur, les autres cellules continuent.
        run["error"] = str(e)
        _log(f"✗ CLA-001 [{mode_label}] ({model}) : {e}")
    return run


def _load_agent_cases(path: Path) -> list[dict]:
    """Charge et valide (a minima) un corpus de cas AGT-001 : liste
    `{id, question, attendu}` — le golden `attendu` est décrit dans
    `core.evals.agent_case_metrics` et `evals/README.md`."""
    cases = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(cases, dict):
        cases = cases.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("le corpus doit être une liste de cas non vide")
    for i, case in enumerate(cases):
        if not isinstance(case, dict) or not case.get("question") \
                or not isinstance(case.get("attendu"), dict):
            raise ValueError(f"cas {i} invalide : champs `question` et `attendu` requis")
        case.setdefault("id", f"cas-{i + 1}")
    return cases


def _eval_agent_run(df, scan, model, cases, args) -> dict:
    """Un run AGT-001 de la matrice d'éval : chaque cas du corpus est un
    tour d'agent sur une **session fraîche** (pas d'historique entre cas), puis
    mesuré contre son golden (`agent_case_metrics` — exactitude des tool-calls
    et des filtres émis). Un cas en échec LLM n'interrompt pas le run."""
    tool_mode = resolve_tool_mode(args.tool_mode, model, args.base_url or None)
    run: dict = {
        "dataset": None, "model": model, "agent": "AGT-001",
        "brief": False, "mode": tool_mode,
        "durationS": None, "usage": None, "metrics": None,
        "cases": [], "error": None,
    }
    try:
        provider = get_provider(
            model=model, api_key=args.api_key or None, base_url=args.base_url or None
        )
    except Exception as e:
        run["error"] = str(e)
        _log(f"✗ AGT-001 ({model}) : {e}")
        return run

    digest = format_digest(scan)
    store = SessionStore()
    duration = 0.0
    usages: list[dict | None] = []
    for case in cases:
        session = store.create(df, digest)
        _log(f"→ AGT-001 [{tool_mode}] ({model}) — cas « {case['id']} »…")
        started = time.time()
        try:
            events = list(agent_turn(session, case["question"], provider, tool_mode))
        except Exception as e:
            # Matrice tolérante (même politique que CLA-001) : le cas est
            # consigné en erreur, les suivants continuent.
            run["cases"].append({"id": case["id"], "reussi": False, "error": str(e)})
            _log(f"✗ cas « {case['id']} » : {e}")
            continue
        elapsed = time.time() - started
        duration += elapsed
        final = events[-1] if events and events[-1].get("type") == "final" else {}
        usages.append(final.get("usage"))
        result = {"id": case["id"], **agent_case_metrics(events, case["attendu"], df)}
        run["cases"].append(result)
        _log(f"{'✓' if result['reussi'] else '✗'} cas « {case['id']} » — "
             f"{final.get('steps', '?')} étape(s) en {format_duration(elapsed)}")

    run["durationS"] = round(duration, 2)
    run["usage"] = sum_usage(usages)
    run["metrics"] = agent_run_metrics(run["cases"])
    m = run["metrics"]
    _log(f"✓ AGT-001 [{tool_mode}] — exactitude {m['reussis']}/{m['cases']}"
         + (f" ({m['exactitudePct']}%)" if m["exactitudePct"] is not None else ""))
    return run


def cmd_eval(args) -> int:
    """Harnais d'évaluation des prompts : corpus × modèles × modes,
    rapport JSON historisé + tableau lisible sur stdout."""
    models = args.model or ([DEFAULT_MODEL] if DEFAULT_MODEL else [])
    if not models:
        _log("✗ Aucun modèle LLM configuré (--model ou DEFAULT_MODEL dans .env).")
        return EXIT_CONFIG_ERROR
    if getattr(args, "corrections", None) and not Path(args.corrections).exists():
        _log(f"✗ Fichier de corrections introuvable : {args.corrections}")
        return EXIT_INPUT_INVALID
    if getattr(args, "directives", None) and not Path(args.directives).exists():
        _log(f"✗ Fichier de consignes introuvable : {args.directives}")
        return EXIT_INPUT_INVALID

    eval_aud = args.agent in ("aud", "both")
    eval_cla = args.agent in ("cla", "both")
    eval_agt = args.agent == "agt"
    ref_modes = {"path": [False], "ref": [True], "both": [False, True]}[args.cla_mode]

    # Éval agent : un corpus de requêtes en langage naturel → golden
    # files des opérations attendues (`--cases`), spécifique au jeu évalué.
    agent_cases: list[dict] = []
    if eval_agt:
        if not args.cases:
            _log("✗ --agent agt exige --cases (corpus golden de requêtes, cf. evals/README.md).")
            return EXIT_CONFIG_ERROR
        if len(args.input) > 1:
            _log("✗ --agent agt : un seul --input (le corpus golden est spécifique au jeu).")
            return EXIT_INPUT_INVALID
        cases_path = Path(args.cases)
        if not cases_path.exists():
            _log(f"✗ Corpus de cas introuvable : {cases_path}")
            return EXIT_INPUT_INVALID
        try:
            agent_cases = _load_agent_cases(cases_path)
        except (ValueError, json.JSONDecodeError) as e:
            _log(f"✗ Corpus de cas invalide ({cases_path}) : {e}")
            return EXIT_INPUT_INVALID
    elif args.cases:
        _log("✗ --cases ne sert qu'avec --agent agt.")
        return EXIT_CONFIG_ERROR

    # Sweep budget d'entrée : faire varier `sample_items_n` (et le nettoyage
    # de dates) pour mesurer leur apport sur la qualité AUD-001. Sans `--sweep-*`,
    # une seule variante « None » = réglages de `args` (comportement inchangé).
    sample_variants = args.sweep_sample if args.sweep_sample else [None]
    clean_variants = [True, False] if args.sweep_clean_dates else [None]
    prep_variants = [
        {"sampleN": s, "cleanDates": c}
        for c in clean_variants
        for s in sample_variants
    ]

    plan_override = None
    if args.plan:
        # Accepte aussi un CSV Resip « dossiers seuls » comme plan.
        plan_override = _load_plan_file(Path(args.plan))
    if eval_cla and not eval_aud and plan_override is None:
        _log("✗ --agent cla exige --plan (pas d'audit dans ce run pour produire le plan).")
        return EXIT_CONFIG_ERROR

    runs: list[dict] = []
    for input_str in args.input:
        input_path = Path(input_str)
        df = _load_input_csv(input_path)
        scan = scan_metadata(df)
        dataset = input_path.name
        _log(f"━━ Jeu : {dataset} ({len(df)} lignes) ━━")
        for model in models:
            if eval_agt:
                run = _eval_agent_run(df, scan, model, agent_cases, args)
                run["dataset"] = dataset
                runs.append(run)
                continue
            plan_for_cla = plan_override
            if eval_aud:
                for variant in prep_variants:
                    run, plan = _eval_audit_run(df, scan, model, args, prep_override=variant)
                    run["dataset"] = dataset
                    runs.append(run)
                    # Le classement enchaîne sur le plan de la **première** variante
                    # produisant un plan (le sweep ne porte que sur l'audit ;
                    # CLA-001 n'échantillonne pas).
                    if plan_override is None and plan_for_cla is None and plan:
                        plan_for_cla = plan
            if eval_cla:
                if not plan_for_cla:
                    for ref_mode in ref_modes:
                        runs.append({
                            "dataset": dataset, "model": model, "agent": "CLA-001",
                            "brief": False, "mode": "ref" if ref_mode else "path",
                            "durationS": None, "usage": None, "metrics": None,
                            "error": "plan indisponible (audit sans plan extrait)",
                        })
                    continue
                for ref_mode in ref_modes:
                    run = _eval_classement_run(df, plan_for_cla, model, ref_mode, args)
                    run["dataset"] = dataset
                    runs.append(run)

    prompt_versions = {
        "AUD-001": AUD_001.PROMPT_VERSION,
        "CLA-001": CLA_001.PROMPT_VERSION,
        "AGT-001": AGT_001.PROMPT_VERSION,
    }
    report = {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "label": args.label or "",
        "promptVersions": prompt_versions,
        "options": {
            "agent": args.agent,
            "claMode": args.cla_mode,
            "brief": bool(args.brief),
            "batchSize": int(args.batch_size or 0),
            "noAvis": bool(args.no_avis),
            "description": bool(args.description),
            "models": models,
            "inputs": [str(p) for p in args.input],
            "planOverride": bool(plan_override),
            "sweepSample": list(args.sweep_sample) if args.sweep_sample else None,
            "sweepCleanDates": bool(args.sweep_clean_dates),
            "corrections": bool(getattr(args, "corrections", None)),
            "cases": str(args.cases) if args.cases else None,
            "toolMode": args.tool_mode,
        },
        "runs": runs,
    }

    # Historisation : un JSON daté par exécution — la comparaison
    # avant/après une modification de prompt se fait entre deux fichiers.
    if not args.no_save:
        results_dir = Path(args.results_dir)
        results_dir.mkdir(parents=True, exist_ok=True)
        label_part = re.sub(r"[^\w\-]+", "_", args.label).strip("_") if args.label else "eval"
        out_path = results_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{label_part}.json"
        out_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _log(f"✓ Rapport d'éval écrit : {out_path}")

    if getattr(args, "json", False):
        # Sortie machine : le rapport complet sur stdout (le même objet
        # qu'historisé), à la place du tableau lisible.
        _emit_json(args, report)
    else:
        # Tableau lisible (critère d'acceptation) sur stdout — les logs
        # restent sur stderr, le tableau est donc redirigeable proprement.
        print(f"Prompts : AUD-001 v{prompt_versions['AUD-001']} · "
              f"CLA-001 v{prompt_versions['CLA-001']} · "
              f"AGT-001 v{prompt_versions['AGT-001']}")
        print()
        print(format_eval_tables(runs))

    if runs and all(r["error"] for r in runs):
        return EXIT_LLM_ERROR
    return EXIT_OK


def _collect_run_artifacts(out_dir: Path) -> list[dict]:
    """Inventaire des fichiers réellement produits dans `--out-dir`, avec un rôle
    et un chemin **relatif** (manifeste portable, indépendant du chemin absolu).
    N'liste que ce qui existe — un run interrompu n'inventorie que ses artefacts
    présents. Les réponses LLM brutes : `rapport.md` (audit, réponse
    complète) et `raw/*.txt` (classement, une par lot)."""
    artifacts: list[dict] = []
    named = [
        ("rapport.md", "audit_raw", "AUD-001"),  # réponse LLM brute de l'audit
        ("plan.md", "plan", "AUD-001"),
        ("notes.md", "notes", "AUD-001"),
    ]
    for name, role, agent in named:
        if (out_dir / name).is_file():
            artifacts.append({"path": name, "role": role, "agent": agent})
    # Réponses brutes du classement (une par lot), triées pour un manifeste stable.
    raw_dir = out_dir / "raw"
    if raw_dir.is_dir():
        for raw in sorted(raw_dir.glob("*.txt")):
            artifacts.append({
                "path": str(raw.relative_to(out_dir).as_posix()),
                "role": "classement_raw", "agent": "CLA-001",
            })
    for csv_path in sorted(out_dir.glob("classement_final_*.csv")):
        artifacts.append({
            "path": csv_path.name, "role": "classement_csv", "agent": "CLA-001",
        })
    return artifacts


def _write_run_manifest(out_dir: Path, manifest: dict) -> Path:
    """Écrit `manifest.json` dans `--out-dir` : un descriptif self-contained
    du run (modèle, versions de prompt, durées, usage, stats, issue) référençant
    tous ses artefacts — base de traçabilité et de reprise. Toujours réécrit en
    fin de run, succès comme échec partiel."""
    manifest = {**manifest, "artifacts": _collect_run_artifacts(out_dir)}
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"✓ Manifeste écrit : {path} ({len(manifest['artifacts'])} artefact(s))")
    return path


def cmd_run(args) -> int:
    _resolve_input_folder(args)  # Dossier local à l'entrée (bypass Archifiltre)
    note = _resolve_audit_note(args)
    if getattr(args, "corrections", None) and not Path(args.corrections).exists():
        _log(f"✗ Fichier de corrections introuvable : {args.corrections}")
        return EXIT_INPUT_INVALID
    if getattr(args, "directives", None) and not Path(args.directives).exists():
        _log(f"✗ Fichier de consignes introuvable : {args.directives}")
        return EXIT_INPUT_INVALID
    if getattr(args, "dry_run", False):
        df = _load_input_csv(Path(args.input))
        _log(f"✓ CSV chargé : {len(df)} lignes (dry-run — aucun appel LLM)")
        # Le classement est assemblé avec un plan vide : à ce stade l'audit ne l'a
        # pas encore produit (aucun LLM appelé). L'estimation CLA-001 sous-estime
        # donc d'autant les tokens du plan — signalé par planKnown=false.
        sections = [_aud_dry_run(df, args, note), _cla_dry_run(df, "", args)]
        return _emit_dry_run(args, "run", sections)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    pipeline_start = time.monotonic()

    audit_result = _run_audit(
        input_path=Path(args.input),
        out_report=out_dir / "rapport.md",
        out_plan=out_dir / "plan.md",
        out_notes=out_dir / "notes.md",
        note=note,
        args=args,
        resume=getattr(args, "resume", False),
    )

    plan = audit_result["plan"]
    if not plan:
        _log("✗ Plan non extrait — impossible d'enchaîner sur le classement.")
        summary = {
            "command": "run", "ok": False, "exitCode": EXIT_OUTPUT_INVALID,
            "outDir": str(out_dir), "audit": _audit_summary(audit_result),
            "classement": None,
        }
        # Manifeste écrit même sur échec : il inventorie les artefacts d'audit
        # produits (rapport brut, plan vide, notes) et consigne l'issue.
        _write_run_manifest(out_dir, {
            **summary,
            "startedAt": started_at,
            "finishedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "durationS": round(time.monotonic() - pipeline_start, 2),
            "promptVersions": {
                "AUD-001": AUD_001.PROMPT_VERSION, "CLA-001": CLA_001.PROMPT_VERSION,
            },
            "input": str(Path(args.input)),
            "resumed": audit_result.get("resumed", False),
        })
        journal = _maybe_write_journal(
            args,
            command="run",
            input_name=_input_label(args),
            model=summary["audit"].get("model"),
            prompt_versions={
                "AUD-001": AUD_001.PROMPT_VERSION, "CLA-001": CLA_001.PROMPT_VERSION,
            },
            started_at=started_at,
            finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            duration_s=round(time.monotonic() - pipeline_start, 2),
            rows=summary["audit"].get("rows"),
            usage=summary["audit"].get("usage"),
            resumed=audit_result.get("resumed", False),
            ok=False,
            exit_code=EXIT_OUTPUT_INVALID,
            warnings=["Plan non extrait du rapport d'audit — classement non exécuté."],
            description_sent=bool(getattr(args, "description", False)),
            plan_origin="audit_llm",
        )
        if journal is not None:
            summary = {**summary, "journal": journal}
        _emit_json(args, summary)
        return EXIT_OUTPUT_INVALID

    out_csv = out_dir / f"classement_final_{ts}.csv"
    result = _run_classement(
        df_original=audit_result["df_original"],
        plan_valide=plan,
        out_path=out_csv,
        args=args,
        # Les réponses brutes du classement vont dans --out-dir/raw : base de la
        # reprise --resume — un run interrompu ne repaye pas les lots réussis.
        raw_dir=out_dir / "raw",
        resume=getattr(args, "resume", False),
    )
    pipeline_s = time.monotonic() - pipeline_start
    _log(f"⏱ Pipeline complet (audit + classement) traité en {format_duration(pipeline_s)}")
    audit_summary = _audit_summary(audit_result)
    classement_summary = _classement_summary(result)
    manifest_path = _write_run_manifest(out_dir, {
        "command": "run",
        "ok": result["exitCode"] == EXIT_OK,
        "exitCode": result["exitCode"],
        "outDir": str(out_dir),
        "input": str(Path(args.input)),
        "model": audit_summary.get("model") or classement_summary.get("model"),
        "resumed": audit_result.get("resumed", False),
        "startedAt": started_at,
        "finishedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "durationS": round(pipeline_s, 2),
        "promptVersions": {
            "AUD-001": AUD_001.PROMPT_VERSION, "CLA-001": CLA_001.PROMPT_VERSION,
        },
        "usage": sum_usage([audit_summary.get("usage"), classement_summary.get("usage")]),
        "audit": audit_summary,
        "classement": classement_summary,
    })
    run_payload = {
        "command": "run",
        "ok": result["exitCode"] == EXIT_OK,
        "exitCode": result["exitCode"],
        "outDir": str(out_dir),
        "durationS": round(pipeline_s, 2),
        "manifest": str(manifest_path),
        "audit": audit_summary,
        "classement": classement_summary,
    }
    journal = _maybe_write_journal(
        args,
        command="run",
        input_name=_input_label(args),
        model=audit_summary.get("model") or classement_summary.get("model"),
        prompt_versions={
            "AUD-001": AUD_001.PROMPT_VERSION, "CLA-001": CLA_001.PROMPT_VERSION,
        },
        started_at=started_at,
        finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        duration_s=round(pipeline_s, 2),
        rows=audit_summary.get("rows"),
        usage=sum_usage([audit_summary.get("usage"), classement_summary.get("usage")]),
        resumed=audit_result.get("resumed", False),
        ok=result["exitCode"] == EXIT_OK,
        exit_code=result["exitCode"],
        warnings=classement_summary.get("warnings", []),
        conformity=classement_summary.get("stats"),
        description_sent=bool(getattr(args, "description", False)),
        # `run` produit le plan par l'audit LLM (AUD-001).
        plan_origin="audit_llm",
    )
    if journal is not None:
        run_payload = {**run_payload, "journal": journal}
    _emit_json(args, run_payload)
    return result["exitCode"]


# ── — scan d'un dossier / application physique du classement ──────────────────

def cmd_scan(args) -> int:
    """Scanne un dossier local et écrit le CSV canonique Archifiltre (sans
    installer ni lancer Archifiltre). Métadonnées seules, aucun binaire ouvert."""
    src = Path(args.input)
    if not src.is_dir():
        _log(f"✗ Dossier introuvable : {src}")
        return EXIT_INPUT_INVALID
    try:
        stats = write_source_csv(src, Path(args.out))
    except SourceScanError as e:
        _log(f"✗ {e}")
        return EXIT_INPUT_INVALID
    _log(
        f"✓ {stats['itemCount']} fichier(s), {stats['folderCount']} dossier(s) → {args.out}"
    )
    if stats["excludedCount"] or stats["skippedSymlinks"]:
        _log(
            f"  ({stats['excludedCount']} entrée(s) système ignorée(s), "
            f"{stats['skippedSymlinks']} lien(s) symbolique(s) non suivi(s))"
        )
    _log("  ⚠ Dates issues de la modification du système de fichiers (pas de dates métier).")
    _emit_json(args, {
        "command": "scan", "ok": True, "exitCode": EXIT_OK,
        "paths": {"csv": str(args.out)}, "scan": stats,
    })
    return EXIT_OK


def cmd_apply(args) -> int:
    """N9 — applique physiquement le classement : copie chaque fichier du CSV RESIP
    vers l'arborescence cible, sous son nouveau titre. **La source n'est jamais
    mutée** (copie seule). Aperçu obligatoire puis confirmation (sauf --yes) ;
    reprise idempotente (--resume) ; erreurs par fichier collectées."""
    resip_path = Path(args.input)
    source_root = Path(args.source_root)
    target_root = Path(args.target_root)
    if not resip_path.is_file():
        _log(f"✗ CSV RESIP introuvable : {resip_path}")
        return EXIT_INPUT_INVALID
    if not source_root.is_dir():
        _log(f"✗ Racine source introuvable : {source_root}")
        return EXIT_INPUT_INVALID
    guard = check_target_guards(source_root, target_root, resume=args.resume)
    if guard is not None:
        _log(f"✗ {guard['error']}")
        return EXIT_INPUT_INVALID
    try:
        with open(resip_path, "rb") as f:
            df_resip = read_csv(f)
    except Exception as e:
        _log(f"✗ CSV RESIP illisible : {e}")
        return EXIT_INPUT_INVALID

    plan = build_apply_plan(df_resip, source_root)
    n = len(plan.operations)
    _log(f"→ Application du classement : {n} fichier(s) à copier vers {target_root}")
    if plan.missing:
        _log(f"  ⚠ {len(plan.missing)} binaire(s) introuvable(s) sous la source")
    if plan.renamed_collisions:
        _log(f"  ⚠ {len(plan.renamed_collisions)} collision(s) de nom cible dédoublonnée(s)")
    if plan.at_root:
        _log(f"  ⚠ {len(plan.at_root)} item(s) laissé(s) à la racine (non classés/hors-plan)")

    if getattr(args, "dry_run", False):
        _emit_json(args, {
            "command": "apply", "ok": True, "exitCode": EXIT_OK,
            "dryRun": True, "preview": plan.as_dict(),
        })
        return EXIT_OK

    if not getattr(args, "yes", False) and not _confirm(
        f"Copier {n} fichier(s) vers {target_root} ? (la source reste intacte) [o/N] "
    ):
        _log("Application annulée (aucune écriture).")
        _emit_json(args, {"command": "apply", "ok": True, "exitCode": EXIT_OK, "written": False})
        return EXIT_OK

    start = time.monotonic()
    stats: dict = {}
    for event in iter_apply(plan, source_root, target_root):
        if event["type"] == "progress":
            sys.stderr.write(
                f"\r  … {event['copied']} copié(s) / {event['total']} "
                f"(sautés : {event['skipped']}, échecs : {event['failed']})   "
            )
            sys.stderr.flush()
        elif event["type"] == "done":
            stats = event["stats"]
    sys.stderr.write("\n")
    sys.stderr.flush()

    verify = verify_apply(plan, target_root)
    duration = time.monotonic() - start
    _log(
        f"✓ Copie terminée : {stats['copied']} copié(s), {stats['skipped']} sauté(s), "
        f"{stats['failed']} échec(s) en {format_duration(duration)}"
    )
    _log(f"  Vérification : {verify['present']}/{verify['expected']} fichier(s) présent(s) dans la cible")

    warnings = [f"{e['sourceRel']} : {e['error']}" for e in stats.get("errors", [])]
    ok = stats.get("failed", 0) == 0
    journal = _maybe_write_journal(
        args,
        command="apply",
        input_name=resip_path.name,
        model=None,
        prompt_versions={},
        duration_s=round(duration, 2),
        rows=stats.get("copied"),
        ok=ok,
        exit_code=EXIT_OK,
        warnings=warnings,
    )
    summary = {
        "command": "apply", "ok": ok, "exitCode": EXIT_OK,
        "written": True, "durationS": round(duration, 2),
        "stats": stats, "verify": verify,
        "paths": {"targetRoot": str(target_root)},
    }
    if journal is not None:
        summary["journal"] = journal
    _emit_json(args, summary)
    return EXIT_OK


# ── Argparse ─────────────────────────────────────────────────────────────────

def _add_llm_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--model", default=None, help="Modèle LiteLLM (override de DEFAULT_MODEL)")
    p.add_argument("--api-key", default=None, help="Clé API (cloud)")
    p.add_argument("--base-url", default=None, help="URL serveur local (LM Studio, Ollama, JAN)")
    p.add_argument("--verbose", "-v", action="store_true", help="Streamer les chunks LLM sur stderr")


def _add_config_arg(p: argparse.ArgumentParser) -> None:
    # Défaut None pour toutes les options surchargeables par odacea.toml : None =
    # « non passé en CLI » (résolu par _apply_file_config —).
    p.add_argument("--config", default=None, metavar="FILE",
                   help="Fichier de configuration odacea.toml (défaut : recherché en "
                        "remontant depuis le répertoire courant). Précédence : CLI > config > .env.")


def _add_json_arg(p: argparse.ArgumentParser) -> None:
    # Sortie machine : résumé JSON sur stdout, logs humains sur stderr.
    p.add_argument("--json", action="store_true",
                   help="Sortie machine : un résumé JSON (chemins produits, stats, "
                        "usage, durée) sur stdout — scriptable, logs humains sur stderr")


def _add_journal_arg(p: argparse.ArgumentParser) -> None:
    # Journal de traitement : export horodaté de traçabilité réglementaire.
    p.add_argument("--journal", default=None, metavar="FICHIER",
                   help="Écrire un journal de traitement horodaté (traçabilité "
                        "réglementaire) : fichier traité, modèle, versions de "
                        "prompt, durée, anomalies, déclaration de confidentialité. "
                        "Local, métadonnées seules. Combinable avec --json (clé `journal`).")


def _add_manifest_arg(p: argparse.ArgumentParser) -> None:
    # Manifeste d'arborescence modèle : vue des répertoires cible du SIP produit.
    p.add_argument("--manifest", default=None, metavar="FICHIER",
                   help="Écrire un manifeste d'arborescence de répertoires modèle "
                        " dérivé du CSV RESIP produit : structure de dossiers "
                        "cible et localisation de chaque fichier classé, importable "
                        "par glisser-déposer dans RESIP. Local, métadonnées seules. "
                        "Combinable avec --json (clé `manifest`).")


def _add_folder_numbers_arg(p: argparse.ArgumentParser) -> None:
    # Option d'export : retirer le préfixe de position ('1-1_') des noms techniques
    # de dossier. Le CSV, le manifeste et la copie physique en héritent
    # (source unique = colonne File). Défaut : numéros conservés (ordre du fonds).
    p.add_argument("--no-folder-numbers", action="store_true",
                   help="Retirer le préfixe de position des noms de dossier "
                        "('1-1_Lettres' → 'Lettres') dans le CSV, le manifeste et la "
                        "copie physique. Attention : les dossiers se trient alors "
                        "alphabétiquement, plus dans l'ordre 1, 2, 3…")


def _add_dry_run_arg(p: argparse.ArgumentParser) -> None:
    # Diagnostic à blanc : assemble prompts + digest + estimation de tokens
    # sans aucun appel LLM. Combinable avec --json (sortie structurée).
    p.add_argument("--dry-run", action="store_true",
                   help="Diagnostic sans appel LLM : affiche le CSV préparé, le digest, "
                        "les prompts assemblés et l'estimation de tokens (aide au coût)")


def _add_reference_plan_args(p: argparse.ArgumentParser) -> None:
    # Plan de classement de référence : injecté comme contrainte dans
    # l'audit via la note contextuelle (le prompt AUD-001 reste inchangé).
    p.add_argument("--reference-plan-file", default=None, metavar="FICHIER",
                   help="Plan de classement de référence à injecter dans l'audit : "
                        "un CSV Resip « dossiers seuls » (converti en arborescence) ou "
                        "un fichier contenant un bloc arborescence canonique brut")
    p.add_argument("--reference-mode", choices=["inspire", "conform"], default="inspire",
                   help="Registre d'injection du plan de référence : « inspire » (indicatif, "
                        "à adapter — défaut) ou « conform » (structure à respecter)")


def _add_prep_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--no-filter-columns", action="store_true", default=None,
                   help="Envoyer toutes les colonnes au LLM (au lieu des 7 requises)")
    p.add_argument("--no-clean-dates", action="store_true", default=None,
                   help="Conserver les dates StartDate/EndDate sur les Items")
    p.add_argument("--no-sample", action="store_true", default=None,
                   help="Envoyer tous les Items au LLM (au lieu d'un échantillon)")
    p.add_argument("--no-items", action="store_true", default=None,
                   help="Arborescence seule : n'envoyer que les dossiers à l'audit, aucun fichier")
    p.add_argument("--no-auto-measures", action="store_true", default=None,
                   help="Ne pas injecter les mesures automatiques (volumétrie, formats) dans l'audit")
    p.add_argument("--sample-n", type=int, default=None,
                   help="Nombre max d'Items par dossier parent (défaut : 5)")
    p.add_argument("--description", action="store_true", default=None,
                   help="Transmettre Content.Description au LLM (audit ET classement). Désactivé par défaut.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        # prog laissé implicite : argparse prend le basename de sys.argv[0] —
        # « odacea » via le point d'entrée installé, « cli.py » via
        # `python cli.py`.
        description="ODACEA en ligne de commande — audit et classement d'archives électroniques.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # enrich (préparation facultative — lit les binaires en local)
    p_enrich = sub.add_parser(
        "enrich",
        help="Étape 0 (facultative) — enrichit Content.Description depuis les binaires locaux",
    )
    p_enrich.add_argument("input", help="CSV Archifiltre (UTF-8, ;)")
    p_enrich.add_argument("--source-root", required=True,
                          help="Dossier racine contenant les binaires référencés par la colonne File")
    p_enrich.add_argument("--output", default=None,
                          help="CSV de sortie (défaut : <input>_enrichi.csv)")
    p_enrich.add_argument("--overwrite", action="store_true",
                          help="Écraser les Content.Description déjà renseignées (défaut : préservées)")
    p_enrich.add_argument("--max-chars", type=int, default=300,
                          help="Longueur max d'une description produite (défaut : 300)")
    p_enrich.add_argument("--fingerprint", action="store_true",
                          help="Calculer l'empreinte SHA-256 de chaque binaire — "
                               "doublons stricts injectés dans le digest d'audit")
    p_enrich.add_argument("--fingerprint-only", action="store_true",
                          help="Calculer uniquement les empreintes (sans extraction de description)")
    p_enrich.add_argument("--verbose", "-v", action="store_true",
                          help="Afficher chaque fichier traité")
    _add_json_arg(p_enrich)
    p_enrich.set_defaults(func=cmd_enrich)


    # audit
    p_audit = sub.add_parser("audit", help="Étape 1 — AUD-001 : audit + plan de classement")
    p_audit.add_argument("input", help="CSV Archifiltre (UTF-8, ;) OU un dossier local à scanner")
    p_audit.add_argument("--out-report", help="Chemin du rapport complet (.md)")
    p_audit.add_argument("--out-plan", help="Chemin du plan extrait (.md)")
    p_audit.add_argument("--out-notes", help="Chemin des notes archiviste (.md)")
    p_audit.add_argument("--note", default="", help="Note contextuelle de l'archiviste")
    p_audit.add_argument("--brief", action="store_true",
                         help="Mode plan seul — ne demande que le plan de classement (sans état des lieux ni notes)")
    p_audit.add_argument("--variants", type=int, default=1, metavar="N",
                         help=f"Audit comparatif : lancer AUD-001 N fois et comparer les plans "
                              f"obtenus (1 = audit simple, défaut ; max {MAX_VARIANTS}). "
                              "Avec --out-dir, chaque variante est écrite séparément.")
    p_audit.add_argument("--out-dir", default=None, metavar="DIR",
                         help="Répertoire où écrire les variantes (--variants > 1) : "
                              "variante-K_rapport/plan/notes.md + comparaison.json")
    _add_reference_plan_args(p_audit)
    _add_prep_args(p_audit)
    _add_llm_args(p_audit)
    _add_config_arg(p_audit)
    _add_json_arg(p_audit)
    _add_dry_run_arg(p_audit)
    _add_journal_arg(p_audit)
    p_audit.set_defaults(func=cmd_audit)

    # classement
    p_cla = sub.add_parser("classement", help="Étape 2 — CLA-001 : classement RESIP")
    p_cla.add_argument("input", help="CSV Archifiltre original")
    p_cla.add_argument("--plan", required=True,
                       help="Plan validé : .md issu de l'audit OU CSV Resip « dossiers seuls »")
    p_cla.add_argument("--out", default=None,
                       help="CSV RESIP de sortie (requis hors --dry-run)")
    p_cla.add_argument("--description", action="store_true", default=None,
                       help="Transmettre Content.Description au LLM de classement. Désactivé par défaut.")
    p_cla.add_argument("--batch-size", type=int, default=None, metavar="N",
                       help="Découper le classement en lots de N items (0 = pas de découpage, défaut)")
    p_cla.add_argument("--concurrency", type=int, default=None, metavar="N",
                       help=f"Lots CLA-001 traités en parallèle (1 = séquentiel, défaut ; max {MAX_CONCURRENCY}). "
                            "Cloud uniquement — ignoré (séquentiel forcé) pour un serveur local mono-requête.")
    p_cla.add_argument("--no-avis", action="store_true", default=None,
                       help="Ne pas demander l'avis de classement (« Démarche de l'IA ») — retire le bloc du prompt CLA-001 (moins de tokens de sortie)")
    p_cla.add_argument("--ref", action="store_true", default=None,
                       help="Méthode « Ref » : le modèle recopie un identifiant court au lieu du chemin complet (sortie plus rapide, ancrage moindre). Défaut : méthode « Path ».")
    p_cla.add_argument("--corrections", default=None, metavar="FICHIER",
                       help="Apprentissage des corrections : CSV de corrections validées "
                            "(Path;TargetFolder;NewTitle, p. ex. un export) réinjectées comme "
                            "exemples few-shot dans CLA-001 (« appliquer la même logique »). "
                            "Proposition à valider sur modèles réels.")
    p_cla.add_argument("--directives", default=None, metavar="FICHIER",
                       help="Consignes de classement de l'archiviste : fichier texte, une "
                            "consigne par ligne. « dossier_technique: consigne » = consigne ancrée ; "
                            "« consigne » seule = consigne de fonds ; marqueur « [+sous-dossiers] » = "
                            "autorise CLA-001 à créer des sous-dossiers sous le dossier visé. "
                            "Modifie le prompt.")
    p_cla.add_argument("--raw-dir", default=None, metavar="DIR",
                       help="Répertoire où sauvegarder les réponses LLM brutes (une par lot) — base de la reprise --resume")
    p_cla.add_argument("--resume", action="store_true",
                       help="Réutiliser les réponses brutes déjà présentes dans --raw-dir au lieu de rappeler le LLM (reprise d'un run interrompu)")
    p_cla.add_argument("--interactive", "-i", action="store_true",
                       help="Afficher l'aperçu de conformité au plan puis demander confirmation avant d'écrire le CSV (pipeline semi-automatique) — un refus n'écrit rien")
    _add_llm_args(p_cla)
    _add_config_arg(p_cla)
    _add_json_arg(p_cla)
    _add_dry_run_arg(p_cla)
    _add_journal_arg(p_cla)
    _add_manifest_arg(p_cla)
    _add_folder_numbers_arg(p_cla)
    p_cla.set_defaults(func=cmd_classement)

    # scan (dossier local → CSV canonique, sans Archifiltre)
    p_scan = sub.add_parser(
        "scan",
        help="Scanner un dossier local → CSV canonique Archifiltre (métadonnées seules, sans Archifiltre)",
    )
    p_scan.add_argument("input", help="Dossier racine du vrac à scanner")
    p_scan.add_argument("--out", "-o", required=True, help="CSV de sortie (canonique Archifiltre)")
    _add_json_arg(p_scan)
    p_scan.set_defaults(func=cmd_scan)

    # apply (N9 — application physique du classement : copie vers l'arborescence cible)
    p_apply = sub.add_parser(
        "apply",
        help="Appliquer physiquement le classement — copie du CSV RESIP vers l'arborescence cible (source intacte)",
    )
    p_apply.add_argument("input", help="CSV RESIP produit par le classement (odacea classement/run)")
    p_apply.add_argument("--source-root", required=True,
                         help="Racine du fonds source (binaires d'origine référencés par la colonne File)")
    p_apply.add_argument("--target-root", required=True,
                         help="Répertoire cible où copier l'arborescence classée (la source n'est jamais modifiée)")
    p_apply.add_argument("--resume", action="store_true",
                         help="Reprise idempotente : compléter une application interrompue (répertoire cible déjà peuplé autorisé)")
    p_apply.add_argument("--yes", "-y", action="store_true",
                         help="Ne pas demander de confirmation avant d'écrire (pipeline non interactif)")
    p_apply.add_argument("--dry-run", action="store_true",
                         help="Aperçu seul (total, collisions, binaires introuvables, items à la racine) sans copier")
    _add_json_arg(p_apply)
    _add_journal_arg(p_apply)
    p_apply.set_defaults(func=cmd_apply)

    # eval (harnais d'évaluation des prompts —)
    p_eval = sub.add_parser(
        "eval",
        help="Harnais d'évaluation des prompts — corpus × modèles, rapport JSON + tableau",
    )
    p_eval.add_argument("--input", action="append", required=True, metavar="CSV",
                        help="CSV du corpus (répétable : --input a.csv --input b.csv)")
    p_eval.add_argument("--model", action="append", default=None, metavar="MODEL",
                        help="Modèle à évaluer (répétable — matrice prompt × modèle). "
                             "Défaut : DEFAULT_MODEL du .env")
    p_eval.add_argument("--api-key", default=None, help="Clé API (cloud)")
    p_eval.add_argument("--base-url", default=None,
                        help="URL serveur local (LM Studio, Ollama, JAN) — partagée par tous les modèles du run")
    p_eval.add_argument("--verbose", "-v", action="store_true",
                        help="Streamer les chunks LLM sur stderr")
    p_eval.add_argument("--agent", choices=["aud", "cla", "both", "agt"], default="both",
                        help="Agent(s) à évaluer (défaut : both — l'audit fournit le plan au "
                             "classement ; agt = agent AGT-001, exige --cases)")
    p_eval.add_argument("--cases", default=None, metavar="FICHIER",
                        help="Éval agent : corpus golden JSON — requêtes en langage "
                             "naturel → opérations attendues (exactitude des tool-calls et des "
                             "filtres émis). Spécifique au jeu --input (cf. evals/cases/).")
    p_eval.add_argument("--tool-mode", choices=["auto", "native", "json"], default="auto",
                        help="Mode d'appel des outils de l'agent : auto (défaut — "
                             "natif pour un cloud, repli JSON pour un serveur local), ou forcé")
    p_eval.add_argument("--cla-mode", choices=["path", "ref", "both"], default="path",
                        help="Méthode d'identifiant CLA-001 à évaluer (both = objectiver le compromis Path/Ref)")
    p_eval.add_argument("--plan", default=None,
                        help="Plan imposé (.md ou CSV Resip « dossiers seuls ») — requis avec "
                             "--agent cla ; avec both, remplace le plan issu de l'audit")
    p_eval.add_argument("--corrections", default=None, metavar="FICHIER",
                        help="Apprentissage des corrections : CSV de corrections validées "
                             "(Path;TargetFolder;NewTitle) réinjectées comme exemples few-shot "
                             "dans CLA-001 — pour mesurer l'apport du few-shot (expérience (a)). "
                             "Comparer un run avec et un run sans ce flag (labels avant/après).")
    p_eval.add_argument("--note", default="", help="Note contextuelle de l'archiviste (audit)")
    p_eval.add_argument("--brief", action="store_true",
                        help="Mode plan seul pour l'audit (les métriques de gabarit deviennent non mesurables)")
    p_eval.add_argument("--batch-size", type=int, default=None, metavar="N",
                        help="Découper le classement en lots de N items (0 = pas de découpage, défaut)")
    p_eval.add_argument("--no-avis", action="store_true", default=None,
                        help="Ne pas demander l'avis de classement dans CLA-001")
    p_eval.add_argument("--sweep-sample", action="append", type=int, default=None, metavar="N",
                        help="Budget d'entrée : faire varier sample_items_n pour AUD-001 "
                             "(répétable : --sweep-sample 0 --sweep-sample 3 --sweep-sample 5). "
                             "0 = aucun échantillonnage. Mesure l'apport du budget sur la qualité.")
    p_eval.add_argument("--sweep-clean-dates", action="store_true",
                        help="Budget d'entrée : évaluer AUD-001 avec ET sans nettoyage des "
                             "dates d'Item (deux variantes), pour mesurer son apport")
    p_eval.add_argument("--label", default="",
                        help="Étiquette du run (suffixe du fichier de résultats, ex. : avant_fewshot)")
    p_eval.add_argument("--results-dir", default="evals/results", metavar="DIR",
                        help="Répertoire d'historisation des rapports JSON (défaut : evals/results)")
    p_eval.add_argument("--no-save", action="store_true",
                        help="Ne pas écrire le rapport JSON (tableau seul)")
    _add_prep_args(p_eval)
    _add_config_arg(p_eval)
    _add_json_arg(p_eval)
    p_eval.set_defaults(func=cmd_eval)

    # run (pipeline complet)
    p_run = sub.add_parser("run", help="Pipeline complet — audit puis classement automatique")
    p_run.add_argument("input", help="CSV Archifiltre OU un dossier local à scanner")
    p_run.add_argument("--out-dir", required=True, help="Répertoire de sortie")
    p_run.add_argument("--note", default="", help="Note contextuelle de l'archiviste")
    p_run.add_argument("--brief", action="store_true",
                       help="Mode plan seul pour l'audit — ne demande que le plan de classement (sans état des lieux ni notes)")
    p_run.add_argument("--batch-size", type=int, default=None, metavar="N",
                       help="Découper le classement en lots de N items (0 = pas de découpage, défaut)")
    p_run.add_argument("--concurrency", type=int, default=None, metavar="N",
                       help=f"Lots CLA-001 traités en parallèle (1 = séquentiel, défaut ; max {MAX_CONCURRENCY}). "
                            "Cloud uniquement — ignoré (séquentiel forcé) pour un serveur local mono-requête.")
    p_run.add_argument("--no-avis", action="store_true", default=None,
                       help="Ne pas demander l'avis de classement (« Démarche de l'IA ») — retire le bloc du prompt CLA-001 (moins de tokens de sortie)")
    p_run.add_argument("--ref", action="store_true", default=None,
                       help="Méthode « Ref » : le modèle recopie un identifiant court au lieu du chemin complet (sortie plus rapide, ancrage moindre). Défaut : méthode « Path ».")
    p_run.add_argument("--corrections", default=None, metavar="FICHIER",
                       help="Apprentissage des corrections : CSV de corrections validées "
                            "(Path;TargetFolder;NewTitle) réinjectées comme exemples few-shot "
                            "dans le classement. Proposition à valider sur modèles réels.")
    p_run.add_argument("--directives", default=None, metavar="FICHIER",
                       help="Consignes de classement de l'archiviste : fichier texte, une "
                            "consigne par ligne (« dossier: consigne » ancrée, « consigne » de fonds, "
                            "« [+sous-dossiers] » autorise la création). Modifie le prompt.")
    p_run.add_argument("--resume", action="store_true",
                       help="Reprendre un run interrompu depuis --out-dir : rapport d'audit (rapport.md) et lots de classement (raw/) déjà produits sont réutilisés sans rappeler le LLM")
    _add_reference_plan_args(p_run)
    _add_prep_args(p_run)
    _add_llm_args(p_run)
    _add_config_arg(p_run)
    _add_json_arg(p_run)
    _add_dry_run_arg(p_run)
    _add_journal_arg(p_run)
    _add_manifest_arg(p_run)
    _add_folder_numbers_arg(p_run)
    p_run.set_defaults(func=cmd_run)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    _apply_file_config(args)
    try:
        result = args.func(args)
    except SystemExit as e:
        # Erreurs profondes (CSV introuvable/invalide, modèle absent, erreur LLM)
        # quittées via sys.exit dans les helpers : en mode --json, on émet quand
        # même une enveloppe d'erreur sur stdout avant de propager le code, pour
        # qu'un script puisse la lire sans parser stderr. Le détail humain
        # reste sur stderr.
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        if code != EXIT_OK:
            _emit_json(args, {
                "command": getattr(args, "command", None),
                "ok": False, "exitCode": code,
            })
        raise
    if isinstance(result, dict):
        return EXIT_OK
    return int(result) if result is not None else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
