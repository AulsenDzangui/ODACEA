"""Adaptateurs minces entre l'API HTTP et le moteur (`core/`, `llm/`, `prompts/`).

Aucune logique métier ici : on parse le CSV reçu en texte, on appelle les fonctions
existantes, et on produit soit du JSON, soit des événements SSE. Les générateurs
sont synchrones — Starlette les itère dans un threadpool, ce qui convient au stream
LLM bloquant.

Découpage du classement : le front *orchestre* les lots (affichage, relance par
lot), mais toute la logique vit ici. `/classement/prepare` renvoie les items,
`/classement/batch` traite une tranche (re-dérivée côté serveur) et `/classement/
finalize` convertit l'ensemble accumulé en RESIP en une seule passe.
"""
from __future__ import annotations

import csv as csv_mod
import io
import os
import pathlib
import time
from collections.abc import Iterator

import pandas as pd

from api import demo_limits, sse
from api.schemas import (
    AgtChatRequest,
    AgtSessionRequest,
    AuditRequest,
    ClassementBatchRequest,
    ClassementFinalizeRequest,
    ClassementPrepareRequest,
    EnrichRequest,
    JournalRequest,
    ManifestRequest,
    PlanCompareRequest,
    PrepOptions,
)
from config import settings
from core.agt_agent import agent_turn, resolve_tool_mode
from core.agt_session import STORE as AGT_STORE
from core.agt_session import AgentSession, SessionNotFound
from core.anomalies import categorize_warnings
from core.apply_classement import (
    build_apply_plan,
    check_target_guards,
    iter_apply,
)
from core.audit_scan import format_digest, scan_metadata
from core.cla_directives import (
    allowed_parents as directives_allowed_parents,
)
from core.cla_directives import (
    directives_from_rows,
    render_directives,
)
from core.corrections import corrections_from_rows, render_corrections_examples
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
    validate_output_csv,
)
from core.enrich import (
    content_access_notice_lines,
    enrich_descriptions,
    fingerprint_files,
)
from core.export_manifest import build_tree_manifest, format_tree_manifest_markdown
from core.journal import build_journal, format_journal_markdown
from core.plan_compare import compare_plan_variants, format_comparison_table
from core.plan_folders import (
    adopt_markdown_plan,
    diff_plans,
    looks_like_csv,
    materialize_plan,
    plan_nodes_from_folders_df,
    plan_nodes_from_plan_text,
    scan_folder_tree,
    serialize_plan_block,
)
from core.prep_budget import recommend_prep
from core.pricing import estimate_cost_eur
from core.reference_plans import (
    compose_observation,
    custom_reference_plan,
)
from core.source_scan import SourceScanError, scan_source_csv
from core.tokens import estimate_tokens
from llm import get_provider, llm_error_info
from prompts import AGT_001, AUD_001, CLA_001


class CsvLimitError(ValueError):
    """CSV refusé car au-delà des limites d'entrée. Porte le `hint`."""

    def __init__(self, message: str, hint: str):
        super().__init__(message)
        self.hint = hint


# ── Mode démonstration ───────────────────────────────────────────────────────

_demo_csv_cache: str | None = None


def _demo_csv_text() -> str:
    """CSV de démonstration embarqué (lu une fois, mis en cache)."""
    global _demo_csv_cache
    if _demo_csv_cache is None:
        _demo_csv_cache = pathlib.Path(settings.DEMO_CSV_PATH).read_text(
            encoding="utf-8-sig"
        )
    return _demo_csv_cache


def _force_demo(req) -> None:
    """En DEMO_MODE : impose le CSV de démo et la config LLM du serveur.

    Garantit qu'**aucune donnée utilisateur** n'est traitée ni envoyée au LLM,
    quoi qu'envoie le client (le CSV reçu est ignoré et remplacé). Sur les
    requêtes LLM (audit / classement), force aussi le modèle et la clé serveur.
    Appliqué aussi à /parse (durcissement) : la démo n'analyse que le CSV
    embarqué, jamais un CSV fourni par le client.
    """
    if not settings.DEMO_MODE:
        return
    if hasattr(req, "csv"):
        req.csv = _demo_csv_text()
    if hasattr(req, "model"):  # ModelConfig (audit / classement/batch) ou ParseRequest
        req.model = settings.DEMO_MODEL
        req.base_url = ""
        # ParseRequest ne porte pas de clé (aucun appel LLM) : ne pas l'imposer.
        if hasattr(req, "api_key"):
            req.api_key = os.getenv("OPENAI_API_KEY")


# ── CSV ──────────────────────────────────────────────────────────────────────

def parse_csv_text(csv_text: str) -> pd.DataFrame:
    """Parse un CSV reçu en texte, sous les limites d'entrée explicites.

    utf-8-sig gère un éventuel BOM. Lève `CsvLimitError` (message + hint) quand
    le fichier dépasse la taille maximale ou la garde mémoire en lignes — tous
    les endpoints qui reçoivent un CSV passent par ici.
    """
    raw = csv_text.encode("utf-8")
    if len(raw) > settings.MAX_CSV_BYTES:
        raise CsvLimitError(
            f"CSV trop volumineux : {len(raw) / (1024 * 1024):.1f} Mo reçus, "
            f"maximum accepté {settings.ODACEA_MAX_CSV_MB:g} Mo.",
            hint=(
                "Découpez le vrac en plusieurs CSV (par sous-dossier de premier "
                "niveau, par exemple) et traitez-les séparément ; ou augmentez "
                "ODACEA_MAX_CSV_MB côté serveur si la machine le permet."
            ),
        )
    df = read_csv(io.BytesIO(raw))
    if len(df) > settings.MAX_CSV_ROWS:
        raise CsvLimitError(
            f"CSV trop long : {len(df)} lignes, maximum accepté "
            f"{settings.MAX_CSV_ROWS} (garde mémoire).",
            hint=(
                "Un vrac de cette taille doit être découpé avant traitement "
                "(plusieurs exports Archifiltre par branche) ; ou augmentez "
                "ODACEA_MAX_CSV_ROWS côté serveur si la machine le permet."
            ),
        )
    return df


def df_to_rows(df: pd.DataFrame) -> list[dict]:
    return df.fillna("").astype(str).to_dict(orient="records")


def csv_stats(df: pd.DataFrame) -> dict:
    level = df.get("Content.DescriptionLevel")
    item_count = int((level == "Item").sum()) if level is not None else 0
    rg_count = int((level == "RecordGrp").sum()) if level is not None else 0
    return {"rowCount": len(df), "itemCount": item_count, "recordGrpCount": rg_count}


def _budget_recommendation(
    df: pd.DataFrame, prep: PrepOptions, audit_tokens_current: int
) -> dict:
    """Recommandation d'échantillonnage d'entrée AUD-001 par taille de vrac.

    La table de paliers locale et datée (`core.prep_budget.recommend_prep`) propose
    un `sample_items_n` (et le nettoyage des dates) en fonction du **nombre d'Item**
    du vrac. On chiffre aussi les tokens d'audit **au réglage recommandé** pour
    rendre l'apport tangible — sans aucun appel LLM. Même contrat que la section
    AUD-001 du `--dry-run` de la CLI (baseline = l'estimation `auditTokens`).
    `currentSampleN=0` / `recommendedSampleN=0` = aucun échantillonnage (tout
    envoyer)."""
    level = df.get("Content.DescriptionLevel")
    item_count = int((level == "Item").sum()) if level is not None else 0
    rec = recommend_prep(item_count)
    current_sample_n = prep.effective_sample_n
    current_clean_dates = prep.clean_dates
    matches = (
        current_sample_n == rec["sampleN"]
        and current_clean_dates == rec["cleanDates"]
    )
    rec_tokens = audit_tokens_current
    if not matches:
        rec_tokens = estimate_tokens(
            df,
            filter_columns=prep.filter_columns,
            clean_dates=rec["cleanDates"],
            sample_items_n=rec["sampleN"],
            include_description=prep.include_description,
            include_items=prep.include_items,
        )["audit_tokens"]
    return {
        "itemCount": item_count,
        "tier": rec["tier"],
        "currentSampleN": current_sample_n,
        "currentCleanDates": current_clean_dates,
        "recommendedSampleN": rec["sampleN"],
        "recommendedCleanDates": rec["cleanDates"],
        "matchesRecommendation": matches,
        "estimatedAuditTokensAtRecommended": rec_tokens,
        "rationale": rec["rationale"],
        "tableDate": rec["tableDate"],
    }


def _token_estimate(
    df: pd.DataFrame,
    prep: PrepOptions,
    batch_size: int,
    *,
    model: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Estimation tokens, remappée en camelCase pour le front (TokenEstimate).

    Quand un `model` cloud connu est fourni, joint un **coût d'entrée indicatif €**
 sur le total estimé — `None` pour un modèle local ou inconnu. Joint aussi
    une **recommandation de budget d'entrée**, indépendante du modèle."""
    e = estimate_tokens(
        df,
        filter_columns=prep.filter_columns,
        clean_dates=prep.clean_dates,
        sample_items_n=prep.effective_sample_n,
        include_description=prep.include_description,
        include_items=prep.include_items,
        batch_size=batch_size,
    )
    out = {
        "auditTokens": e["audit_tokens"],
        "classementTokensPerBatch": e["classement_tokens_per_batch"],
        "classementBatches": e["classement_batches"],
        "classementTotalTokens": e["classement_total_tokens"],
        "totalTokens": e["total_tokens"],
        "budgetRecommendation": _budget_recommendation(df, prep, e["audit_tokens"]),
    }
    if model:
        out["costEstimate"] = estimate_cost_eur(
            model=model, base_url=base_url, input_tokens=e["total_tokens"]
        )
    return out


def parse_payload(
    csv: str,
    prep: PrepOptions,
    batch_size: int,
    *,
    model: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Réponse de /parse : lignes originales, erreurs, stats, aperçu préparé,
    estimation tokens (pour les options courantes)."""
    df = parse_csv_text(csv)
    errors = validate_csv(df)
    payload: dict = {
        "rows": df_to_rows(df),
        "columns": list(df.columns),
        "validationErrors": errors,
        "stats": csv_stats(df),
    }
    if not errors:
        prepared = prepare_for_llm(
            df,
            filter_columns=prep.filter_columns,
            clean_dates=prep.clean_dates,
            sample_items_n=prep.effective_sample_n,
            include_description=prep.include_description,
            include_items=prep.include_items,
        )
        prepared_items = int((prepared.get("Content.DescriptionLevel") == "Item").sum())
        payload["prepared"] = {
            "previewRows": df_to_rows(prepared.head(5)),
            "columns": list(prepared.columns),
            "columnCount": len(prepared.columns),
            "itemCount": prepared_items,
        }
        payload["tokenEstimate"] = _token_estimate(
            df, prep, batch_size, model=model, base_url=base_url
        )
    return payload


def parse_from_folder_payload(req) -> dict:
    """Import direct d'un dossier local (backend local uniquement ; refus démo
    assuré par api.main). Scanne l'arborescence réelle sous `source_root` pour en
    dériver le CSV canonique (métadonnées seules, **aucun binaire ouvert**),
    puis renvoie la **même réponse que /parse** sur ce CSV dérivé + `derivedCsv`
    (téléchargeable) + `scan` (stats du scan). Une seule porte d'entrée : le CSV
    dérivé repasse par `read_csv` via `parse_payload`."""
    root = pathlib.Path((req.source_root or "").strip())
    try:
        derived_csv, scan = scan_source_csv(root, max_items=settings.MAX_CSV_ROWS)
    except SourceScanError as e:
        code = "csv_too_large" if "trop volumineux" in str(e) else "source_missing"
        return {"error": str(e), "code": code, "hint": e.hint}
    payload = parse_payload(
        derived_csv, req.prep, req.batch_size, model=req.model, base_url=req.base_url
    )
    payload["derivedCsv"] = derived_csv
    payload["scan"] = scan
    return payload


def reference_plan_from_csv(csv: str) -> dict:
    """Réponse de /reference-plan/from-csv : convertit un CSV Resip « dossiers
    seuls » en bloc arborescence injectable comme plan de classement de référence
    à l'audit. Mêmes contrôles d'entrée que /parse (limites,
    `validate_csv`) ; les fichiers (Item) sont ignorés avec avertissement.

    Renvoie `{tree, validationErrors, warnings, folderCount, ignoredItemCount,
    rootTitle}`. Un CSV invalide (colonnes, IDs) remonte via `validationErrors`
    (bloquant côté front) ; un CSV valide mais sans dossier via `validationErrors`
    également (message explicite)."""
    df = parse_csv_text(csv)
    errors = validate_csv(df)
    if errors:
        return {"tree": "", "validationErrors": errors, "warnings": [],
                "folderCount": 0, "ignoredItemCount": 0, "rootTitle": ""}
    try:
        tree, warnings, stats = build_reference_tree_from_folders(df)
    except ValueError as e:
        return {"tree": "", "validationErrors": [str(e)], "warnings": [],
                "folderCount": 0, "ignoredItemCount": 0, "rootTitle": ""}
    return {
        "tree": tree,
        "validationErrors": [],
        "warnings": warnings,
        "folderCount": stats["folderCount"],
        "ignoredItemCount": stats["ignoredItemCount"],
        "rootTitle": stats["rootTitle"],
    }


# ── Plan souverain ───────────────────────────────────────────────────────────

def plan_from_file_payload(name: str, content: str) -> dict:
    """Adopte un plan fourni par l'archiviste **sans appel LLM** (POST
    /plan/from-file). Route sur le format (CSV Resip « dossiers seuls » ou bloc
    Markdown canonique), renvoie un document de plan **parsable par
    parse_plan_tree** : `{plan, planTree, folderCount, rootTitle, warnings,
    format}`. Erreur de conversion → `{error, code, hint}` (statut HTTP par
    l'appelant). Le front ne fait que transporter le texte."""
    if not (content or "").strip():
        return {"error": "Fichier vide.", "code": "plan_empty",
                "hint": "Importez un CSV Resip « dossiers seuls » ou un plan Markdown."}
    try:
        if looks_like_csv(name, content):
            df = parse_csv_text(content)
            nodes, root_title, warnings, stats = plan_nodes_from_folders_df(df)
            plan = serialize_plan_block(nodes, root_title)
            return {
                "plan": plan,
                "planTree": parse_plan_tree(plan),
                "folderCount": stats["folderCount"],
                "ignoredItemCount": stats["ignoredItemCount"],
                "rootTitle": root_title,
                "warnings": warnings,
                "format": "csv",
            }
        plan, warnings = adopt_markdown_plan(content)
        tree = parse_plan_tree(plan)
        return {
            "plan": plan,
            "planTree": tree,
            "folderCount": len(tree),
            "ignoredItemCount": 0,
            "rootTitle": "",
            "warnings": warnings,
            "format": "markdown",
        }
    except CsvLimitError as e:
        return {"error": str(e), "code": "csv_too_large", "hint": e.hint}
    except ValueError as e:
        return {
            "error": str(e),
            "code": "plan_unreadable",
            "hint": ("Fournissez un CSV Resip ne contenant que des dossiers, ou un "
                     "plan Markdown avec un bloc « Arborescence technique »."),
        }
    except Exception as e:
        return {
            "error": f"Lecture du plan impossible : {e}",
            "code": "plan_unreadable",
            "hint": "Vérifiez le format du fichier (CSV Resip « dossiers seuls » ou Markdown).",
        }


def plan_materialize_payload(req) -> dict:
    """Matérialise le plan courant en dossiers vides réels sous `work_dir`
    (**backend local uniquement** ; refus démo assuré par api.main). Le vidage
    préalable (`clear`) n'est honoré qu'avec `confirm=True` (garde-fou)."""
    work_dir = (req.work_dir or "").strip()
    if not work_dir:
        return {"error": "Répertoire de travail manquant.", "code": "plan_workdir_missing",
                "hint": "Indiquez un dossier local où matérialiser l'arborescence du plan."}
    if req.clear and not req.confirm:
        return {"error": "Vidage du répertoire non confirmé.", "code": "plan_clear_unconfirmed",
                "hint": "Le vidage du répertoire de travail exige une confirmation explicite."}
    try:
        stats = materialize_plan(
            req.plan_valide, pathlib.Path(work_dir), clear=req.clear
        )
    except ValueError as e:
        return {"error": str(e), "code": "plan_unreadable",
                "hint": "Le plan doit contenir une arborescence technique exploitable."}
    except OSError as e:
        return {"error": f"Écriture impossible dans {work_dir} : {e}", "code": "plan_workdir_error",
                "hint": "Vérifiez que le chemin est accessible en écriture depuis le backend local."}
    return {
        "folderCount": stats["folderCount"],
        "workDir": stats["root"],
        "cleared": bool(req.clear),
    }


def plan_from_folder_payload(req) -> dict:
    """Re-scanne `work_dir` et reconstruit le plan canonique (**backend local
    uniquement**). Joint un **aperçu des changements** vs `current_plan` quand il est
    fourni : `{plan, planTree, folderCount, rootTitle, warnings, changes}`."""
    work_dir = (req.work_dir or "").strip()
    if not work_dir:
        return {"error": "Répertoire de travail manquant.", "code": "plan_workdir_missing",
                "hint": "Indiquez le dossier local réorganisé dans l'Explorateur."}
    try:
        nodes, root_title, warnings, stats = scan_folder_tree(pathlib.Path(work_dir))
    except ValueError as e:
        return {"error": str(e), "code": "plan_workdir_missing",
                "hint": "Le répertoire de travail est introuvable ; matérialisez d'abord le plan."}
    plan = serialize_plan_block(nodes, root_title)
    payload: dict = {
        "plan": plan,
        "planTree": parse_plan_tree(plan),
        "folderCount": stats["folderCount"],
        "ignoredFileCount": stats["ignoredFileCount"],
        "rootTitle": root_title,
        "warnings": warnings,
    }
    if (req.current_plan or "").strip():
        payload["changes"] = diff_plans(
            plan_nodes_from_plan_text(req.current_plan), nodes
        )
    return payload


# ── Audit (AUD-001) ──────────────────────────────────────────────────────────

def audit_stream(
    req: AuditRequest, reservation: demo_limits.Reservation | None = None
) -> Iterator[str]:
    _force_demo(req)
    committed = False
    try:
        try:
            df = parse_csv_text(req.csv)
        except CsvLimitError as e:
            yield sse.error(str(e), code="csv_too_large", hint=e.hint)
            return
        except Exception as e:
            yield sse.error(
                f"Lecture CSV impossible : {e}",
                code="csv_unreadable",
                hint="Vérifiez que le fichier est un export Archifiltre/Resip (séparateur « ; », UTF-8).",
            )
            return

        errors = validate_csv(df)
        if errors:
            yield sse.error(
                "CSV invalide : " + " ; ".join(errors),
                code="csv_invalid",
                hint="Corrigez le CSV source (colonnes requises, IDs uniques) puis réimportez-le.",
            )
            return

        df_prepared = prepare_for_llm(
            df,
            filter_columns=req.prep.filter_columns,
            clean_dates=req.prep.clean_dates,
            sample_items_n=req.prep.effective_sample_n,
            include_description=req.prep.include_description,
            include_items=req.prep.include_items,
        )
        # Constats déterministes calculés sur le vrac complet (et non l'aperçu
        # préparé/échantillonné) pour ancrer l'audit sur des chiffres exacts.
        # Désactivable via l'option « Mesures automatiques » (prep.auto_measures).
        digest = format_digest(scan_metadata(df)) if req.prep.auto_measures else ""
        system_prompt = AUD_001.SYSTEM_PROMPT_BRIEF if req.brief else AUD_001.SYSTEM_PROMPT
        # Plan de classement de référence — injecté dans la note contextuelle.
        # Le front envoie un bloc d'arborescence (`reference_plan`), dérivé d'un CSV
        # Resip « dossiers seuls » importé par l'archiviste (POST /reference-plan/from-csv).
        ref_plan = (
            custom_reference_plan(req.reference_plan)
            if req.reference_plan.strip()
            else None
        )
        observation = compose_observation(req.observation, ref_plan, req.reference_mode)
        user_msg = AUD_001.build_user_message(
            csv_to_string(df_prepared),
            observation=observation,
            metadata_digest=digest,
            brief=req.brief,
        )
        provider = get_provider(model=req.model, api_key=req.api_key, base_url=req.base_url)
        # Retry B9 : le callback alimente une file, émise en `notice` SSE au fil
        # du flux (et après coup si la tentative suivante aboutit d'emblée).
        retry_notices: list[str] = []
        provider.on_retry = retry_notices.append

        full_response = ""
        start = time.monotonic()
        try:
            for is_thinking, chunk in provider.stream_with_reasoning(system_prompt, user_msg):
                while retry_notices:
                    yield sse.notice(retry_notices.pop(0))
                if is_thinking:
                    yield sse.reasoning(chunk)
                else:
                    full_response += chunk
                    yield sse.text(chunk)
            while retry_notices:
                yield sse.notice(retry_notices.pop(0))
        except Exception as e:
            yield sse.error(**llm_error_info(e))
            return

        sections = extract_plans(full_response)
        plan = sections.get("plan", "")
        # Démo : on solde la réservation avec l'usage réel *avant* d'émettre `done`,
        # pour garantir l'exécution même si le client cesse de lire ensuite. Les
        # retours d'erreur ci-dessus tombent dans le `finally` → remboursement.
        if reservation is not None:
            demo_limits.commit(reservation, (provider.last_usage or {}).get("total_tokens"))
            committed = True
        yield sse.done(
            report=full_response,
            plan=plan,
            notes=sections.get("notes", ""),
            planTree=parse_plan_tree(plan),
            usage=provider.last_usage,
            durationMs=round((time.monotonic() - start) * 1000),
            promptVersion=AUD_001.PROMPT_VERSION,
            model=req.model,
        )
    finally:
        # Échec, abandon (GeneratorExit) ou exception : rend l'essai et les tokens
        # provisionnés. Un parcours abouti a déjà soldé (committed=True).
        if reservation is not None and not committed:
            demo_limits.rollback(reservation)


# ── Enrichissement (étape 0 — `enrich`, backend local uniquement) ─────────────

def enrich_payload(req: EnrichRequest) -> dict:
    """Exécute l'étape 0 `enrich` côté backend : extraction de métadonnées
    de contenu et/ou empreinte SHA-256 des binaires sous `req.source_root`.

    **Backend local uniquement** — le serveur ouvre les fichiers locaux ; le mode
    démonstration est refusé en amont (`api.main`). Renvoie le CSV enrichi (texte)
    plutôt que d'écrire un fichier : le backend reste **sans état**, le front
    persiste et réutilise le CSV pour l'audit. La structure des rapports reprend
    celle du `--json` de la CLI (`report`, `fingerprint`, `duplicates`).
    """
    notice = " ".join(content_access_notice_lines(req.source_root))

    root = pathlib.Path(req.source_root)
    if not root.is_dir():
        return {
            "error": f"Dossier source introuvable : {req.source_root}",
            "code": "enrich_source_missing",
            "hint": (
                "Indiquez la racine locale du vrac (le dossier réellement analysé "
                "par Archifiltre) accessible depuis la machine qui héberge le backend."
            ),
            "contentAccessNotice": notice,
        }

    try:
        df = parse_csv_text(req.csv)
    except CsvLimitError as e:
        return {"error": str(e), "code": "csv_too_large", "hint": e.hint}
    except Exception as e:
        return {
            "error": f"Lecture CSV impossible : {e}",
            "code": "csv_unreadable",
            "hint": "Vérifiez que le fichier est un export Archifiltre/Resip (séparateur « ; », UTF-8).",
        }

    df_out = df
    payload: dict = {"contentAccessNotice": notice}

    if not req.fingerprint_only:
        df_out, report = enrich_descriptions(
            df_out, root, overwrite=req.overwrite, max_chars=req.max_chars
        )
        payload["report"] = {
            "totalItems": report.total_items,
            "enriched": report.enriched,
            "alreadyFilled": report.already_filled,
            "noText": report.no_text,
            "unsupported": report.unsupported,
            "missing": report.missing,
            "errors": len(report.errors),
        }

    if req.fingerprint or req.fingerprint_only:
        df_out, fp_report = fingerprint_files(df_out, root, overwrite=req.overwrite)
        payload["fingerprint"] = {
            "totalItems": fp_report.total_items,
            "hashed": fp_report.hashed,
            "alreadyHashed": fp_report.already_hashed,
            "missing": fp_report.missing,
            "skipped": fp_report.skipped,
            "errors": len(fp_report.errors),
        }
        # Rapport déterministe des groupes binairement identiques (même logique
        # que le digest AUD-001) — surfacé tel quel au front.
        dups = scan_metadata(df_out).get("strictDuplicates", {})
        payload["duplicates"] = {
            "groups": dups.get("total", 0),
            "files": dups.get("files", 0),
            "redundant": dups.get("redundant", 0),
            "examples": dups.get("examples", []),
        }

    payload["enrichedCsv"] = df_out.to_csv(
        index=False, sep=";", quoting=csv_mod.QUOTE_ALL
    )
    return payload


def extract_plans_payload(report: str) -> dict:
    """Re-extrait plan/notes/arbre depuis un rapport d'audit (sans appel LLM)."""
    sections = extract_plans(report)
    plan = sections.get("plan", "")
    return {"plan": plan, "notes": sections.get("notes", ""), "planTree": parse_plan_tree(plan)}


def journal_payload(req: JournalRequest) -> dict:
    """Journal de traitement : construit le document de traçabilité depuis
    les métadonnées renvoyées par le front (jamais de contenu documentaire) et le
    rend en Markdown — source unique du rendu côté moteur. Renvoie `{markdown,
    journal}` (le front télécharge/affiche, le backend reste sans état)."""
    journal = build_journal(
        command=req.command,
        input_name=req.input_name,
        model=req.model,
        models=req.models,
        prompt_versions=req.prompt_versions,
        started_at=req.started_at,
        finished_at=req.finished_at,
        duration_s=req.duration_s,
        rows=req.rows,
        usage=req.usage,
        resumed=req.resumed,
        ok=req.ok,
        exit_code=req.exit_code,
        warnings=req.warnings,
        conformity=req.conformity,
        description_sent=req.description_sent,
        plan_origin=req.plan_origin,
        plan_modified=req.plan_modified,
    )
    return {"markdown": format_journal_markdown(journal), "journal": journal}


def manifest_payload(req: ManifestRequest) -> dict:
    """Manifeste d'arborescence modèle : dérive l'arborescence de répertoires
    cible des lignes RESIP renvoyées par le front (`resip.rows` de finalize) et la
    rend en Markdown — source unique du rendu côté moteur. Renvoie `{markdown,
    manifest}` (le front télécharge/affiche, le backend reste sans état)."""
    df_resip = pd.DataFrame(req.rows).astype(str)
    manifest = build_tree_manifest(df_resip)
    return {"markdown": format_tree_manifest_markdown(manifest), "manifest": manifest}


# ── Application physique du classement (backend local uniquement) ─────────────

def _apply_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows).astype(str)


def apply_preview_payload(req) -> dict:
    """Aperçu avant écriture (backend local uniquement ; refus démo assuré par
    api.main). Dérive le plan de copie des lignes RESIP (`rows`) et de la racine
    source, sans copier aucun fichier (seule l'existence des sources est testée).
    Joint le contrôle des garde-fous du répertoire cible quand `target_root`
    est fourni. Renvoie `{plan…, targetGuard}`."""
    if not req.rows:
        return {"error": "Aucune ligne RESIP à appliquer.", "code": "apply_no_rows",
                "hint": "Finalisez d'abord le classement (l'application copie le SIP produit)."}
    source_root = pathlib.Path((req.source_root or "").strip())
    if not source_root.is_dir():
        return {"error": f"Dossier source introuvable : {req.source_root}",
                "code": "source_missing",
                "hint": "Indiquez la racine locale du fonds (le dossier réellement classé)."}
    plan = build_apply_plan(_apply_df(req.rows), source_root)
    payload = plan.as_dict()
    guard = None
    if (req.target_root or "").strip():
        guard = check_target_guards(
            source_root, pathlib.Path(req.target_root.strip()), resume=req.resume
        )
    payload["targetGuard"] = guard
    return payload


def apply_stream(req) -> Iterator[str]:
    """Exécute l'application physique du classement en SSE (backend local
    uniquement). Événements `progress` (copiés/total/fichier courant) puis
    `done{stats}`. Erreurs par fichier **collectées sans interrompre** le run.
    La **source n'est jamais mutée** (copie seule). Annulation B8 : à la
    déconnexion, Starlette ferme le générateur (la copie en cours s'achève, aucune
    suivante n'est lancée — pas d'état corrompu)."""
    if not req.confirm:
        yield sse.error(
            "Application non confirmée.",
            code="apply_unconfirmed",
            hint="L'écriture n'a lieu qu'après confirmation explicite.",
        )
        return
    if not req.rows:
        yield sse.error(
            "Aucune ligne RESIP à appliquer.",
            code="apply_no_rows",
            hint="Finalisez d'abord le classement.",
        )
        return
    source_root = pathlib.Path((req.source_root or "").strip())
    target_root = pathlib.Path((req.target_root or "").strip())
    if not source_root.is_dir():
        yield sse.error(
            f"Dossier source introuvable : {req.source_root}",
            code="source_missing",
            hint="Indiquez la racine locale du fonds (le dossier réellement classé).",
        )
        return
    guard = check_target_guards(source_root, target_root, resume=req.resume)
    if guard is not None:
        yield sse.error(guard["error"], code=guard["code"], hint=guard["hint"])
        return

    plan = build_apply_plan(_apply_df(req.rows), source_root)
    start = time.monotonic()
    for event in iter_apply(plan, source_root, target_root):
        if event["type"] == "progress":
            yield sse.event(
                "progress",
                copied=event["copied"],
                skipped=event["skipped"],
                failed=event["failed"],
                total=event["total"],
                current=event["current"],
            )
        elif event["type"] == "done":
            yield sse.done(
                stats=event["stats"],
                durationMs=round((time.monotonic() - start) * 1000),
            )


def plan_compare_payload(req: PlanCompareRequest) -> dict:
    """Comparaison multi-plans : compare les variantes de plan renvoyées par
    le front (textes du bloc « Arborescence technique » obtenus par N audits) et
    rend le tableau récapitulatif — source unique du rendu côté moteur. Renvoie
    `{variants, comparison, markdown}` (le front présente et choisit ; le backend
    reste sans état, aucun appel LLM)."""
    result = compare_plan_variants(req.plans)
    return {**result, "markdown": format_comparison_table(result)}


# ── Agent (AGT-001) : session / chat (lecture seule) ─────────────────────────

_AGT_EXPIRED_HINT = (
    "La session serveur a expiré (cache de travail à TTL) : recréez-la depuis "
    "votre projet via POST /agt/session — l'état durable vit côté client."
)


def agt_session_create(req: AgtSessionRequest) -> dict:
    """Crée une session d'exploration : CSV parsé/validé une fois, DataFrame
    + résumé compact (digest audit_scan) gardés en mémoire process avec TTL."""
    df = parse_csv_text(req.csv)
    errors = validate_csv(df)
    if errors:
        return {
            "error": "CSV invalide : " + " ; ".join(errors),
            "code": "csv_invalid",
            "hint": "Corrigez le CSV source (colonnes requises, IDs uniques) puis réimportez-le.",
        }
    digest = format_digest(scan_metadata(df))
    # Rapport d'audit du projet en contexte optionnel (0.6.0) : figé à la
    # création. Vide/absent ⇒ exploration « à froid », system prompt inchangé.
    audit_report = (req.audit_report or "").strip() or None
    session = AGT_STORE.create(df, digest, audit_report=audit_report)
    return {
        "sessionId": session.session_id,
        "stats": csv_stats(df),
        "digest": digest,
        "ttlS": AGT_STORE.ttl_s,
        "auditReportUsed": audit_report is not None,
    }


def agt_session_status(session_id: str) -> dict:
    """État d'une session (âge, expiration, tours, tokens cumulés) — ou
    `{error, code}` si expirée/inconnue (le front recrée)."""
    try:
        return AGT_STORE.status(session_id)
    except SessionNotFound:
        return {
            "error": "Session inconnue ou expirée.",
            "code": "agt_session_expired",
            "hint": _AGT_EXPIRED_HINT,
        }


def agt_session_delete(session_id: str) -> dict:
    return {"deleted": AGT_STORE.delete(session_id)}


_AGT_EXPIRED_PAYLOAD = {
    "error": "Session inconnue ou expirée.",
    "code": "agt_session_expired",
    "hint": _AGT_EXPIRED_HINT,
}


def _agt_session_or_none(session_id: str) -> AgentSession | None:
    try:
        return AGT_STORE.get(session_id)
    except SessionNotFound:
        return None


def agt_conversation_reset(session_id: str) -> dict:
    """Réinitialise la conversation en cours : vide l'historique de
    dialogue de la session **sans la détruire** — seule la mémoire des tours
    précédents est effacée, l'agent repart sur un fil vierge. Une session
    expirée renvoie le code stable (le front recrée, déjà sans historique)."""
    session = _agt_session_or_none(session_id)
    if session is None:
        return dict(_AGT_EXPIRED_PAYLOAD)
    session.history.clear()
    return {"sessionId": session.session_id, "reset": True, "turns": 0}


def agt_chat_stream(req: AgtChatRequest) -> Iterator[str]:
    """Un tour de dialogue avec l'agent, en SSE. Événements : `tool` /
    `toolResult` (transparence des appels d'outils), `text` (réponse),
    `notice` (retry B9), puis `done{answer, steps, usage, usageSession,
    toolMode, promptVersion, model}`. Le CSV ne transite jamais dans un prompt :
    le modèle ne voit que le digest et les résultats d'outils."""
    try:
        session = AGT_STORE.get(req.session_id)
    except SessionNotFound:
        yield sse.error(
            "Session inconnue ou expirée.",
            code="agt_session_expired",
            hint=_AGT_EXPIRED_HINT,
        )
        return
    if not req.message.strip():
        yield sse.error(
            "Message vide.",
            code="agt_message_empty",
            hint="Posez une question sur le vrac (volumes, types, périodes, dossiers…).",
        )
        return

    provider = get_provider(model=req.model, api_key=req.api_key, base_url=req.base_url)
    retry_notices: list[str] = []
    provider.on_retry = retry_notices.append
    mode = resolve_tool_mode(req.tool_mode, req.model, req.base_url)

    final: dict = {}
    start = time.monotonic()
    try:
        for event in agent_turn(session, req.message, provider, tool_mode=mode):
            while retry_notices:
                yield sse.notice(retry_notices.pop(0))
            if event["type"] == "tool":
                yield sse.event(
                    "tool", step=event["step"], name=event["name"], arguments=event["arguments"]
                )
            elif event["type"] == "toolResult":
                yield sse.event(
                    "toolResult", step=event["step"], name=event["name"], result=event["result"]
                )
            elif event["type"] == "answer":
                yield sse.text(event["text"])
            elif event["type"] == "final":
                final = event
        while retry_notices:
            yield sse.notice(retry_notices.pop(0))
    except Exception as e:
        yield sse.error(**llm_error_info(e))
        return

    # Coût € indicatif cumulé de la session : le tour est valorisé à la
    # grille locale (`core.pricing`) — None pour un modèle local ou cloud
    # inconnu (rien à afficher), le cumul reste alors absent.
    turn_usage = final.get("usage") or {}
    cost = estimate_cost_eur(
        model=req.model,
        base_url=req.base_url,
        input_tokens=int(turn_usage.get("input_tokens") or 0),
        output_tokens=int(turn_usage.get("output_tokens") or 0),
    )
    if cost is not None:
        session.cost_eur = (session.cost_eur or 0.0) + cost["totalEur"]

    yield sse.done(
        answer=final.get("answer", ""),
        steps=final.get("steps", 0),
        usage=final.get("usage"),
        usageSession=session.usage_total or None,
        costSessionEur=(
            round(session.cost_eur, 4) if session.cost_eur is not None else None
        ),
        toolMode=mode,
        durationMs=round((time.monotonic() - start) * 1000),
        promptVersion=AGT_001.PROMPT_VERSION,
        model=req.model,
    )


# ── Classement (CLA-001) : prepare / batch / finalize ────────────────────────

def _classement_items(csv: str, prep: PrepOptions) -> pd.DataFrame:
    df_original = parse_csv_text(csv)
    return prepare_for_classement(df_original, include_description=prep.include_description)


def classement_prepare(req: ClassementPrepareRequest) -> dict:
    """Items à classer (opaques pour le front : sert au comptage et à l'aperçu)."""
    _force_demo(req)
    try:
        df_original = parse_csv_text(req.csv)
    except CsvLimitError as e:
        return {"error": str(e), "code": "csv_too_large", "hint": e.hint}
    errors = validate_csv(df_original)
    if errors:
        return {
            "error": "CSV invalide : " + " ; ".join(errors),
            "code": "csv_invalid",
            "hint": "Corrigez le CSV source (colonnes requises, IDs uniques) puis réimportez-le.",
        }
    items = prepare_for_classement(df_original, include_description=req.prep.include_description)
    return {"items": df_to_rows(items), "total": len(items), "columns": list(items.columns)}


def _is_data_line(line: str) -> bool:
    """Une ligne de données CLA-001 (`Path;TargetFolder;NewTitle`) a au moins deux
    séparateurs. On accepte `;` comme `,` (certains modèles reasoning ignorent la
    consigne `;`). Les fences Markdown sont ignorées."""
    s = line.strip()
    if not s or s.startswith("```"):
        return False
    return s.count(";") >= 2 or s.count(",") >= 2


def classement_batch_stream(
    req: ClassementBatchRequest, reservation: demo_limits.Reservation | None = None
) -> Iterator[str]:
    """Traite une tranche d'items. Le serveur re-dérive les items à l'identique
    puis sélectionne [batch_index*batch_size : +batch_size].

    Émet des événements `progress` (items_done) au fil du flux : on compte les
    lignes CSV produites *après* l'en-tête/fence, pour ignorer le préambule et le
    raisonnement. C'est une estimation live (le modèle peut omettre ou dupliquer
    des lignes) ; le front la recale sur le compte réel à l'événement `done`."""
    _force_demo(req)
    if settings.DEMO_MODE:
        req.batch_index = 0
        req.batch_size = 0  # un seul lot : un classement = un appel LLM/essai
    committed = False
    try:
        try:
            items = _classement_items(req.csv, req.prep)
        except CsvLimitError as e:
            yield sse.error(str(e), code="csv_too_large", hint=e.hint)
            return
        except Exception as e:
            yield sse.error(
                f"Lecture CSV impossible : {e}",
                code="csv_unreadable",
                hint="Vérifiez que le fichier est un export Archifiltre/Resip (séparateur « ; », UTF-8).",
            )
            return

        if req.batch_size and req.batch_size > 0:
            offset = req.batch_index * req.batch_size
            batch = items.iloc[offset:offset + req.batch_size]
        else:
            batch = items

        ref_mode = req.prep.classement_ref
        # Apprentissage des corrections : rend le bloc few-shot côté moteur
        # (source unique) ; vide sans corrections → prompt inchangé.
        examples = render_corrections_examples(
            corrections_from_rows(c.model_dump() for c in req.corrections)
        ) if req.corrections else ""
        # Consignes de classement de l'archiviste : rendu côté moteur,
        # dans le préfixe stable mis en cache ; vide sans consigne → prompt inchangé.
        directives_block = render_directives(
            directives_from_rows(d.model_dump() for d in req.directives),
            set(parse_plan_tree(req.plan_valide)),
        ) if req.directives else ""
        user_msg = CLA_001.build_user_message(
            csv_content=classement_llm_csv(batch, ref_mode=ref_mode),
            plan_valide=req.plan_valide,
            ref_mode=ref_mode,
            examples=examples,
            directives=directives_block,
        )
        provider = get_provider(model=req.model, api_key=req.api_key, base_url=req.base_url)
        retry_notices: list[str] = []
        provider.on_retry = retry_notices.append

        full_response = ""
        line_buf = ""       # ligne en cours (non encore terminée par \n)
        seen_csv = False    # a-t-on franchi l'en-tête/fence CSV ?
        items_done = 0
        start = time.monotonic()
        try:
            system_prompt = CLA_001.build_system_prompt(
                avis=req.prep.classement_avis, ref_mode=ref_mode,
                examples=bool(examples),
                directives=bool(directives_block),
            )
            for is_thinking, chunk in provider.stream_with_reasoning(
                system_prompt, user_msg, cache_user_boundary=CLA_001.CACHE_BOUNDARY
            ):
                while retry_notices:
                    yield sse.notice(retry_notices.pop(0))
                if is_thinking:
                    yield sse.reasoning(chunk)
                    continue
                full_response += chunk
                yield sse.text(chunk)

                # Comptage incrémental ligne à ligne.
                line_buf += chunk
                counted_new = False
                while "\n" in line_buf:
                    line, line_buf = line_buf.split("\n", 1)
                    s = line.strip()
                    if not seen_csv:
                        if "TargetFolder" in s or s.lower().startswith("```csv"):
                            seen_csv = True
                        continue
                    if _is_data_line(s):
                        items_done += 1
                        counted_new = True
                if counted_new:
                    yield sse.progress(
                        batch=req.batch_index, total_batches=0, items_done=items_done
                    )
            while retry_notices:
                yield sse.notice(retry_notices.pop(0))
        except Exception as e:
            yield sse.error(**llm_error_info(e))
            return

        try:
            df_llm = extract_csv_from_response(
                full_response, id_col="Ref" if ref_mode else "Path"
            )
        except Exception as e:
            yield sse.error(
                f"Extraction CSV impossible : {e}",
                code="extract_failed",
                hint=(
                    "Le modèle n'a pas produit de CSV exploitable : consultez la "
                    "réponse brute, puis relancez le lot (un modèle plus régulier "
                    "ou le mode Path peuvent aider)."
                ),
            )
            return

        # Démo : solde *avant* `done` (cf. audit_stream) ; les retours d'erreur
        # ci-dessus tombent dans le `finally` → remboursement de l'essai.
        if reservation is not None:
            demo_limits.commit(reservation, (provider.last_usage or {}).get("total_tokens"))
            committed = True
        yield sse.done(
            llmRows=df_to_rows(df_llm),
            rawText=full_response,
            usage=provider.last_usage,
            durationMs=round((time.monotonic() - start) * 1000),
            promptVersion=CLA_001.PROMPT_VERSION,
            model=req.model,
        )
    finally:
        if reservation is not None and not committed:
            demo_limits.rollback(reservation)


def classement_finalize(req: ClassementFinalizeRequest) -> dict:
    """Convertit les lignes LLM accumulées (tous lots) en CSV RESIP — passe unique :
    dédoublonnage des dossiers, IDs et plages de dates cohérents sur tout le vrac."""
    _force_demo(req)
    try:
        df_original = parse_csv_text(req.csv)
    except CsvLimitError as e:
        return {"error": str(e), "code": "csv_too_large", "hint": e.hint}
    if not req.llm_rows:
        return {
            "error": "Aucune ligne LLM à convertir.",
            "code": "no_llm_rows",
            "hint": "Relancez le classement : aucun lot n'a produit de lignes exploitables.",
        }
    df_llm = pd.DataFrame(req.llm_rows).astype(str)
    # Consignes de classement : les dossiers du plan sous lesquels la
    # création de sous-dossiers est autorisée. Vide sans consigne → conversion
    # inchangée (un dossier inventé reste un hors-plan).
    allowed = directives_allowed_parents(
        directives_from_rows(d.model_dump() for d in req.directives),
        set(parse_plan_tree(req.plan_valide)),
    ) if req.directives else set()
    try:
        df_final, warnings, stats = convert_classement_to_resip(
            df_llm, df_original, req.plan_valide, allowed_parents=allowed
        )
    except Exception as e:
        return {
            "error": f"Conversion RESIP impossible : {e}",
            "code": "conversion_failed",
            "hint": (
                "Vérifiez le plan validé (bloc « Arborescence technique ») et "
                "les lots produits ; relancez les lots en erreur le cas échéant."
            ),
        }
    # Option d'export (retrait des numéros de position des noms de dossier) —
    # appliquée APRÈS le calcul des stats de conformité (qui référencent le plan
    # numéroté) ; le CSV, le manifeste et la copie physique héritent des noms
    # nettoyés via la seule colonne File. Collisions de frères signalées.
    if req.strip_folder_numbers:
        df_final, renamed = strip_folder_numbers(df_final)
        warnings = list(warnings) + renamed
    # Contrôle d'intégrité du SIP produit (orphelins, racine, cycles de parenté,
    # inversions de dates) : déterministe, sans appel LLM. Les anomalies — issues
    # de données source bruitées ou d'un plan édité à la main — sont remontées en
    # avertissements à l'archiviste, sans bloquer le téléchargement.
    warnings = list(warnings) + [
        f"Contrôle d'intégrité : {e}" for e in validate_output_csv(df_final)
    ]
    return {
        "resip": {
            "rows": df_to_rows(df_final),
            "columns": list(df_final.columns),
            "warnings": warnings,
            # Anomalies typées pour le triage — catégorisées côté moteur
            # (source unique) ; le front ne fait que les présenter.
            "anomalies": categorize_warnings(warnings),
            "stats": stats,
        },
    }
