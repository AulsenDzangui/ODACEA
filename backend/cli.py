"""CLI ODACEA — audit et classement d'archives en ligne de commande.

Expose les agents AUD-001 et CLA-001 sans Streamlit, pour intégration dans
des workflows automatisés (GED, scripts d'import, pipelines de versement).
Partage strictement la même logique métier que l'app Streamlit.

Usage : python cli.py {audit,classement,run} ...
"""
from __future__ import annotations

import argparse
import csv as csv_mod
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from dotenv import load_dotenv

load_dotenv()

from config.settings import DEFAULT_MODEL
from core.csv_handler import (
    convert_classement_to_resip,
    csv_to_string,
    extract_csv_from_response,
    extract_plans,
    parse_plan_tree,
    prepare_for_classement,
    prepare_for_llm,
    read_csv,
    validate_csv,
)
from core.audit_scan import format_digest, scan_metadata
from core.cla_directives import allowed_parents as directives_allowed_parents
from core.cla_directives import read_directives_file, render_directives, stale_anchors
from core.enrich import enrich_descriptions
from core.source_scan import SourceScanError, write_source_csv
from core.tokens import format_duration
from llm import get_provider
from prompts import AUD_001, CLA_001


EXIT_OK = 0
EXIT_LLM_ERROR = 1
EXIT_INPUT_INVALID = 2
EXIT_OUTPUT_INVALID = 3
EXIT_CONFIG_ERROR = 4


# ── Helpers ──────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


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


def _stream(provider, system_prompt: str, user_msg: str, verbose: bool) -> tuple[str, str, float]:
    """Consomme provider.stream_with_reasoning() et retourne (thinking, response, durée).

    La durée (en secondes, horloge monotone) mesure le temps de traitement réel
    du LLM — du premier au dernier chunk — pour la mesure de performance.

    En verbose, écrit les chunks sur stderr en live. Sinon, affiche un compteur
    de progression discret toutes les ~2s.
    """
    thinking_text = ""
    full_response = ""
    start = time.monotonic()
    last_tick = start
    chunk_count = 0
    in_thinking_block = False

    try:
        for is_thinking, chunk in provider.stream_with_reasoning(system_prompt, user_msg):
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
        _log(f"\n✗ Erreur LLM : {e}")
        sys.exit(EXIT_LLM_ERROR)

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
    _log("")
    _log("ℹ️  Étape de préparation (facultative) — accès au contenu des fichiers")
    _log(f"   Les binaires de « {source_root} » vont être OUVERTS en local pour en")
    _log("   extraire des métadonnées (propriétés, mots-clés, premières lignes).")
    _log("   Aucune donnée ne quitte la machine ; aucun appel LLM ; pas d'OCR.")
    _log("")

    def _progress(file_value: str) -> None:
        if args.verbose:
            _log(f"  → {file_value}")

    df_out, report = enrich_descriptions(
        df,
        source_root,
        overwrite=args.overwrite,
        max_chars=args.max_chars,
        on_progress=_progress,
    )

    for line in report.summary_lines():
        _log(f"  • {line}")
    for err in report.errors[:20]:
        _log(f"    ⚠ {err}")

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = input_path.with_name(f"{input_path.stem}_enrichi{input_path.suffix}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(out_path, index=False, sep=";", quoting=csv_mod.QUOTE_ALL, encoding="utf-8-sig")
    _log(f"✓ CSV enrichi écrit : {out_path}")
    return EXIT_OK


def cmd_audit(args) -> int:
    return _run_audit(
        input_path=Path(args.input),
        out_report=Path(args.out_report) if args.out_report else None,
        out_plan=Path(args.out_plan) if args.out_plan else None,
        out_notes=Path(args.out_notes) if args.out_notes else None,
        note=args.note or "",
        args=args,
    )


def _run_audit(*, input_path, out_report, out_plan, out_notes, note, args):
    df = _load_input_csv(input_path)
    _log(f"✓ CSV chargé : {len(df)} lignes, {len(df.columns)} colonnes")

    sample_n = 0 if args.no_sample else args.sample_n
    df_prepared = prepare_for_llm(
        df,
        filter_columns=not args.no_filter_columns,
        clean_dates=not args.no_clean_dates,
        sample_items_n=sample_n,
        include_description=args.description,
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
            "df_original": df, "duration": elapsed}


def cmd_classement(args) -> int:
    if getattr(args, "directives", None) and not Path(args.directives).exists():
        _log(f"✗ Fichier de consignes introuvable : {args.directives}")
        return EXIT_INPUT_INVALID
    plan_path = Path(args.plan)
    if not plan_path.exists():
        _log(f"✗ Fichier plan introuvable : {plan_path}")
        return EXIT_INPUT_INVALID
    plan_valide = plan_path.read_text(encoding="utf-8")

    df_original = _load_input_csv(Path(args.input))
    return _run_classement(
        df_original=df_original,
        plan_valide=plan_valide,
        out_path=Path(args.out),
        args=args,
    )


def _load_directives(args) -> list:
    """Consignes de classement : si `--directives FICHIER` est fourni, lit le
    fichier (une consigne par ligne, cf. `core.cla_directives.read_directives_file`)
    et journalise ce qui a été retenu. Sans le flag, aucune consigne — le prompt
    reste inchangé. La formulation du bloc injecté vit côté moteur —
    **métadonnées seules**."""
    path = getattr(args, "directives", None)
    if not path:
        return []
    directives = read_directives_file(Path(path))
    n_anc = sum(1 for d in directives if d.folder)
    n_crea = sum(1 for d in directives if d.allow_creation)
    _log(
        f"✓ Consignes : {len(directives)} consigne(s) — "
        f"{n_anc} ancrée(s) à un dossier, {n_crea} autorisant la création de sous-dossiers"
    )
    return directives


def _run_classement(*, df_original, plan_valide, out_path, args) -> int:
    _log("→ Préparation des items à classer…")
    df_input = prepare_for_classement(df_original, include_description=args.description)
    n_total = len(df_input)
    _log(f"✓ {n_total} item(s) à classer")

    directives = _load_directives(args)
    plan_folder_names = set(parse_plan_tree(plan_valide))
    directives_block = render_directives(directives, plan_folder_names) if directives else ""
    for stale in stale_anchors(directives, plan_folder_names):
        _log(f"⚠ Consigne ancrée au dossier '{stale}', absent du plan — traitée au niveau du fonds")
    system_prompt = CLA_001.build_system_prompt(directives=bool(directives_block))

    provider, model = _build_provider(args)
    batch_size = getattr(args, "batch_size", 0) or 0
    cla_duration = 0.0

    if batch_size > 0 and n_total > batch_size:
        n_batches = math.ceil(n_total / batch_size)
        _log(f"→ Traitement par lots : {n_batches} lot(s) de {batch_size} items max")
        df_llm_parts = []
        for i in range(n_batches):
            df_batch = df_input.iloc[i * batch_size : (i + 1) * batch_size]
            _log(f"→ Lot {i + 1}/{n_batches} ({len(df_batch)} items) — CLA-001 (modèle : {model})…")
            csv_text = csv_to_string(df_batch)
            user_msg = CLA_001.build_user_message(
                csv_content=csv_text, plan_valide=plan_valide, directives=directives_block
            )
            _, llm_response, elapsed = _stream(provider, system_prompt, user_msg, args.verbose)
            cla_duration += elapsed
            _log(f"✓ Lot {i + 1}/{n_batches} — réponse reçue ({len(llm_response)} car.) en {format_duration(elapsed)}")
            try:
                df_llm_parts.append(extract_csv_from_response(llm_response))
            except Exception as e:
                _log(f"✗ Lot {i + 1}/{n_batches} — impossible d'extraire un CSV : {e}")
                return EXIT_OUTPUT_INVALID
        df_llm = pd.concat(df_llm_parts, ignore_index=True)
        _log(f"✓ Tous les lots traités — {len(df_llm)} ligne(s) LLM au total en {format_duration(cla_duration)}")
    else:
        csv_text = csv_to_string(df_input)
        user_msg = CLA_001.build_user_message(
            csv_content=csv_text, plan_valide=plan_valide, directives=directives_block
        )
        _log(f"→ Classement CLA-001 (modèle : {model})…")
        _, llm_response, cla_duration = _stream(provider, system_prompt, user_msg, args.verbose)
        _log(f"✓ Réponse reçue ({len(llm_response)} car.) en {format_duration(cla_duration)}")
        try:
            df_llm = extract_csv_from_response(llm_response)
        except Exception as e:
            _log(f"✗ Impossible d'extraire un CSV de la réponse LLM : {e}")
            return EXIT_OUTPUT_INVALID

    try:
        df_final, warnings_list, stats = convert_classement_to_resip(
            df_llm,
            df_original,
            plan_valide,
            allowed_parents=directives_allowed_parents(directives, plan_folder_names),
        )
    except Exception as e:
        _log(f"✗ Conversion RESIP impossible : {e}")
        return EXIT_OUTPUT_INVALID

    if warnings_list:
        _log(f"⚠ {len(warnings_list)} avertissement(s) de conversion :")
        for w in warnings_list:
            _log(f"  • {w}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_final.to_csv(out_path, index=False, sep=";", quoting=csv_mod.QUOTE_ALL, encoding="utf-8")
    _log(f"✓ CSV RESIP écrit : {out_path} ({len(df_final)} lignes)")

    n_items = int((df_final["Content.DescriptionLevel"] == "Item").sum())
    n_rg = int((df_final["Content.DescriptionLevel"] == "RecordGrp").sum())
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
    created = stats.get("foldersCreatedAuthorized") or []
    if created:
        parents = stats.get("foldersCreatedParents", {})
        _log(f"  → {len(created)} sous-dossier(s) créé(s) sous vos consignes :")
        for f in created:
            _log(f"      • {f} (sous {parents.get(f, '?')})")
    if stats.get("itemsMalformed"):
        _log(f"  → {stats['itemsMalformed']} item(s) à cible malformée rattaché(s) à la racine")
    _log(f"  ⏱ Classement traité en {format_duration(cla_duration)}")

    return EXIT_OK


def cmd_run(args) -> int:
    if getattr(args, "directives", None) and not Path(args.directives).exists():
        _log(f"✗ Fichier de consignes introuvable : {args.directives}")
        return EXIT_INPUT_INVALID
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pipeline_start = time.monotonic()

    audit_result = _run_audit(
        input_path=Path(args.input),
        out_report=out_dir / "rapport.md",
        out_plan=out_dir / "plan.md",
        out_notes=out_dir / "notes.md",
        note=args.note or "",
        args=args,
    )
    if not isinstance(audit_result, dict):
        return audit_result

    plan = audit_result["plan"]
    if not plan:
        _log("✗ Plan non extrait — impossible d'enchaîner sur le classement.")
        return EXIT_OUTPUT_INVALID

    out_csv = out_dir / f"classement_final_{ts}.csv"
    result = _run_classement(
        df_original=audit_result["df_original"],
        plan_valide=plan,
        out_path=out_csv,
        args=args,
    )
    _log(f"⏱ Pipeline complet (audit + classement) traité en "
         f"{format_duration(time.monotonic() - pipeline_start)}")
    return result


# ── Argparse ─────────────────────────────────────────────────────────────────

def _add_llm_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--model", default=None, help="Modèle LiteLLM (override de DEFAULT_MODEL)")
    p.add_argument("--api-key", default=None, help="Clé API (cloud)")
    p.add_argument("--base-url", default=None, help="URL serveur local (LM Studio, Ollama, JAN)")
    p.add_argument("--verbose", "-v", action="store_true", help="Streamer les chunks LLM sur stderr")


def _add_directives_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--directives", default=None, metavar="FICHIER",
        help=(
            "Fichier de consignes de classement (une par ligne : « consigne » pour "
            "le fonds, « dossier_technique: consigne » pour un dossier du plan ; "
            "marqueur [+sous-dossiers] pour autoriser la création de sous-dossiers)"
        ),
    )


def _add_prep_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--no-filter-columns", action="store_true",
                   help="Envoyer toutes les colonnes au LLM (au lieu des 7 requises)")
    p.add_argument("--no-clean-dates", action="store_true",
                   help="Conserver les dates StartDate/EndDate sur les Items")
    p.add_argument("--no-sample", action="store_true",
                   help="Envoyer tous les Items au LLM (au lieu d'un échantillon)")
    p.add_argument("--no-auto-measures", action="store_true",
                   help="Ne pas injecter les mesures automatiques (volumétrie, formats) dans l'audit")
    p.add_argument("--sample-n", type=int, default=5,
                   help="Nombre max d'Items par dossier parent (défaut : 5)")
    p.add_argument("--description", action="store_true",
                   help="Transmettre Content.Description au LLM (audit ET classement). Désactivé par défaut.")


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
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
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
    p_enrich.add_argument("--verbose", "-v", action="store_true",
                          help="Afficher chaque fichier traité")
    p_enrich.set_defaults(func=cmd_enrich)

    # audit
    p_audit = sub.add_parser("audit", help="Étape 1 — AUD-001 : audit + plan de classement")
    p_audit.add_argument("input", help="CSV Archifiltre (UTF-8, ;)")
    p_audit.add_argument("--out-report", help="Chemin du rapport complet (.md)")
    p_audit.add_argument("--out-plan", help="Chemin du plan extrait (.md)")
    p_audit.add_argument("--out-notes", help="Chemin des notes archiviste (.md)")
    p_audit.add_argument("--note", default="", help="Note contextuelle de l'archiviste")
    p_audit.add_argument("--brief", action="store_true",
                         help="Mode plan seul — ne demande que le plan de classement (sans état des lieux ni notes)")
    _add_prep_args(p_audit)
    _add_llm_args(p_audit)
    p_audit.set_defaults(func=cmd_audit)

    # classement
    p_cla = sub.add_parser("classement", help="Étape 2 — CLA-001 : classement RESIP")
    p_cla.add_argument("input", help="CSV Archifiltre original")
    p_cla.add_argument("--plan", required=True, help="Fichier plan validé (.md issu de l'audit)")
    p_cla.add_argument("--out", required=True, help="CSV RESIP de sortie")
    p_cla.add_argument("--description", action="store_true",
                       help="Transmettre Content.Description au LLM de classement. Désactivé par défaut.")
    p_cla.add_argument("--batch-size", type=int, default=0, metavar="N",
                       help="Découper le classement en lots de N items (0 = pas de découpage, défaut)")
    _add_directives_arg(p_cla)
    _add_llm_args(p_cla)
    p_cla.set_defaults(func=cmd_classement)

    # run (pipeline complet)
    p_run = sub.add_parser("run", help="Pipeline complet — audit puis classement automatique")
    p_run.add_argument("input", help="CSV Archifiltre")
    p_run.add_argument("--out-dir", required=True, help="Répertoire de sortie")
    p_run.add_argument("--note", default="", help="Note contextuelle de l'archiviste")
    p_run.add_argument("--brief", action="store_true",
                       help="Mode plan seul pour l'audit — ne demande que le plan de classement (sans état des lieux ni notes)")
    p_run.add_argument("--batch-size", type=int, default=0, metavar="N",
                       help="Découper le classement en lots de N items (0 = pas de découpage, défaut)")
    _add_directives_arg(p_run)
    _add_prep_args(p_run)
    _add_llm_args(p_run)
    p_run.set_defaults(func=cmd_run)

    # scan (dossier local → CSV canonique, sans Archifiltre)
    p_scan = sub.add_parser(
        "scan",
        help="Scanne un dossier local → CSV canonique Archifiltre (sans installer Archifiltre)",
    )
    p_scan.add_argument("input", help="Dossier racine du vrac à scanner")
    p_scan.add_argument("--out", "-o", required=True,
                        help="CSV de sortie (canonique Archifiltre)")
    p_scan.set_defaults(func=cmd_scan)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    result = args.func(args)
    if isinstance(result, dict):
        return EXIT_OK
    return int(result) if result is not None else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
