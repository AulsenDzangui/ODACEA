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

import io
import pathlib
import time
from typing import Iterator

import pandas as pd

from api import sse
from api.schemas import (
    AuditRequest,
    ClassementBatchRequest,
    ClassementFinalizeRequest,
    ClassementPrepareRequest,
    PrepOptions,
)
from config.settings import MAX_CSV_ROWS
from core.audit_scan import format_digest, scan_metadata
from core.source_scan import SourceScanError, scan_source_csv
from core.apply_classement import build_apply_plan, check_target_guards, iter_apply
from core.cla_directives import (
    allowed_parents as directives_allowed_parents,
)
from core.cla_directives import directives_from_rows, render_directives
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
    validate_output_csv,
)
from core.tokens import estimate_tokens
from llm import get_provider
from prompts import AUD_001, CLA_001


# ── CSV ──────────────────────────────────────────────────────────────────────

def parse_csv_text(csv_text: str) -> pd.DataFrame:
    """Parse un CSV reçu en texte. utf-8-sig gère un éventuel BOM."""
    return read_csv(io.BytesIO(csv_text.encode("utf-8")))


def df_to_rows(df: pd.DataFrame) -> list[dict]:
    return df.fillna("").astype(str).to_dict(orient="records")


def csv_stats(df: pd.DataFrame) -> dict:
    level = df.get("Content.DescriptionLevel")
    item_count = int((level == "Item").sum()) if level is not None else 0
    rg_count = int((level == "RecordGrp").sum()) if level is not None else 0
    return {"rowCount": len(df), "itemCount": item_count, "recordGrpCount": rg_count}


def _token_estimate(df: pd.DataFrame, prep: PrepOptions, batch_size: int) -> dict:
    """Estimation tokens, remappée en camelCase pour le front (TokenEstimate)."""
    e = estimate_tokens(
        df,
        filter_columns=prep.filter_columns,
        clean_dates=prep.clean_dates,
        sample_items_n=prep.effective_sample_n,
        include_description=prep.include_description,
        batch_size=batch_size,
    )
    return {
        "auditTokens": e["audit_tokens"],
        "classementTokensPerBatch": e["classement_tokens_per_batch"],
        "classementBatches": e["classement_batches"],
        "classementTotalTokens": e["classement_total_tokens"],
        "totalTokens": e["total_tokens"],
    }


def parse_payload(csv: str, prep: PrepOptions, batch_size: int) -> dict:
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
        )
        prepared_items = int((prepared.get("Content.DescriptionLevel") == "Item").sum())
        payload["prepared"] = {
            "previewRows": df_to_rows(prepared.head(5)),
            "columns": list(prepared.columns),
            "columnCount": len(prepared.columns),
            "itemCount": prepared_items,
        }
        payload["tokenEstimate"] = _token_estimate(df, prep, batch_size)
    return payload


def parse_from_folder_payload(req) -> dict:
    """Import direct d'un dossier local (backend local uniquement). Scanne
    l'arborescence réelle sous `source_root` pour en dériver le CSV canonique
    (métadonnées seules, **aucun binaire ouvert**), puis renvoie la **même
    réponse que /parse** sur ce CSV dérivé + `derivedCsv` (téléchargeable) +
    `scan` (stats du scan). Une seule porte d'entrée : le CSV dérivé repasse par
    `read_csv` via `parse_payload`."""
    root = pathlib.Path((req.source_root or "").strip())
    try:
        derived_csv, scan = scan_source_csv(root, max_items=MAX_CSV_ROWS)
    except SourceScanError as e:
        code = "csv_too_large" if "trop volumineux" in str(e) else "source_missing"
        return {"error": str(e), "code": code, "hint": e.hint}
    payload = parse_payload(derived_csv, req.prep, req.batch_size)
    payload["derivedCsv"] = derived_csv
    payload["scan"] = scan
    return payload


def plan_from_file_payload(name: str, content: str) -> dict:
    """Adopte un plan fourni par l'archiviste **sans appel LLM** (POST
    /plan/from-file). Route sur le format (CSV Resip « dossiers seuls » ou bloc
    Markdown canonique), renvoie un document de plan **parsable par
    parse_plan_tree** : `{plan, planTree, folderCount, rootTitle, warnings,
    format}`. Erreur de conversion → `{error, code, hint}`. Le front ne fait que
    transporter le texte."""
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
    """Matérialise le plan courant en **dossiers vides réels** sous `work_dir`
    (**backend local uniquement**), pour que l'archiviste le réorganise dans son
    explorateur de fichiers. Le vidage préalable (`clear`) n'est honoré qu'avec
    `confirm=True` — il est destructif."""
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
    """Scanne un dossier existant du poste et en reconstruit un plan de classement
    canonique (**backend local uniquement**) : `{plan, planTree, folderCount,
    ignoredFileCount, rootTitle, warnings}`. Le contenu des fichiers n'est jamais
    lu — seuls les **noms de dossiers** comptent (les fichiers sont ignorés).

    Quand `current_plan` est fourni (aller-retour par l'explorateur de fichiers),
    la réponse joint un **aperçu des changements** (`changes`) vs ce plan."""
    work_dir = (req.work_dir or "").strip()
    if not work_dir:
        return {"error": "Dossier manquant.", "code": "plan_workdir_missing",
                "hint": "Indiquez un dossier local dont l'arborescence servira de plan."}
    try:
        nodes, root_title, warnings, stats = scan_folder_tree(pathlib.Path(work_dir))
    except ValueError as e:
        return {"error": str(e), "code": "plan_workdir_missing",
                "hint": "Le dossier est introuvable ou illisible."}
    plan = serialize_plan_block(nodes, root_title)
    payload: dict = {
        "plan": plan,
        "planTree": parse_plan_tree(plan),
        "folderCount": stats["folderCount"],
        "ignoredFileCount": stats["ignoredFileCount"],
        "rootTitle": root_title,
        "warnings": warnings,
    }
    if (getattr(req, "current_plan", "") or "").strip():
        payload["changes"] = diff_plans(
            plan_nodes_from_plan_text(req.current_plan), nodes
        )
    return payload


# ── Application physique du classement (backend local uniquement) ────────────

def _apply_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows).astype(str)


def apply_preview_payload(req) -> dict:
    """Aperçu avant écriture (backend local uniquement). Dérive le plan de copie
    des lignes RESIP (`rows`) et de la racine source, **sans copier aucun fichier**
    (seule l'existence des sources est testée). Joint le contrôle des garde-fous
    du répertoire cible quand `target_root` est fourni → `{plan…, targetGuard}`."""
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
    La **source n'est jamais mutée** (copie seule)."""
    if not req.confirm:
        yield sse.error(
            "Application non confirmée — l'écriture n'a lieu qu'après confirmation explicite."
        )
        return
    if not req.rows:
        yield sse.error("Aucune ligne RESIP à appliquer. Finalisez d'abord le classement.")
        return
    source_root = pathlib.Path((req.source_root or "").strip())
    target_root = pathlib.Path((req.target_root or "").strip())
    if not source_root.is_dir():
        yield sse.error(
            f"Dossier source introuvable : {req.source_root}. "
            "Indiquez la racine locale du fonds (le dossier réellement classé)."
        )
        return
    guard = check_target_guards(source_root, target_root, resume=req.resume)
    if guard is not None:
        yield sse.error(f"{guard['error']} {guard['hint']}")
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


# ── Audit (AUD-001) ──────────────────────────────────────────────────────────

def audit_stream(req: AuditRequest) -> Iterator[str]:
    try:
        df = parse_csv_text(req.csv)
    except Exception as e:
        yield sse.error(f"Lecture CSV impossible : {e}")
        return

    errors = validate_csv(df)
    if errors:
        yield sse.error("CSV invalide : " + " ; ".join(errors))
        return

    df_prepared = prepare_for_llm(
        df,
        filter_columns=req.prep.filter_columns,
        clean_dates=req.prep.clean_dates,
        sample_items_n=req.prep.effective_sample_n,
        include_description=req.prep.include_description,
    )
    # Constats déterministes calculés sur le vrac complet (et non l'aperçu
    # préparé/échantillonné) pour ancrer l'audit sur des chiffres exacts.
    # Désactivable via l'option « Mesures automatiques » (prep.auto_measures).
    digest = format_digest(scan_metadata(df)) if req.prep.auto_measures else ""
    system_prompt = AUD_001.SYSTEM_PROMPT_BRIEF if req.brief else AUD_001.SYSTEM_PROMPT
    user_msg = AUD_001.build_user_message(
        csv_to_string(df_prepared),
        observation=req.observation,
        metadata_digest=digest,
        brief=req.brief,
    )
    provider = get_provider(model=req.model, api_key=req.api_key, base_url=req.base_url)

    full_response = ""
    start = time.monotonic()
    try:
        for is_thinking, chunk in provider.stream_with_reasoning(system_prompt, user_msg):
            if is_thinking:
                yield sse.reasoning(chunk)
            else:
                full_response += chunk
                yield sse.text(chunk)
    except Exception as e:
        yield sse.error(f"Erreur LLM : {e}")
        return

    sections = extract_plans(full_response)
    plan = sections.get("plan", "")
    yield sse.done(
        report=full_response,
        plan=plan,
        notes=sections.get("notes", ""),
        planTree=parse_plan_tree(plan),
        usage=provider.last_usage,
        durationMs=round((time.monotonic() - start) * 1000),
    )


def extract_plans_payload(report: str) -> dict:
    """Re-extrait plan/notes/arbre depuis un rapport d'audit (sans appel LLM)."""
    sections = extract_plans(report)
    plan = sections.get("plan", "")
    return {"plan": plan, "notes": sections.get("notes", ""), "planTree": parse_plan_tree(plan)}


# ── Classement (CLA-001) : prepare / batch / finalize ────────────────────────

def _classement_items(csv: str, prep: PrepOptions) -> pd.DataFrame:
    df_original = parse_csv_text(csv)
    return prepare_for_classement(df_original, include_description=prep.include_description)


def classement_prepare(req: ClassementPrepareRequest) -> dict:
    """Items à classer (opaques pour le front : sert au comptage et à l'aperçu)."""
    df_original = parse_csv_text(req.csv)
    errors = validate_csv(df_original)
    if errors:
        return {"error": "CSV invalide : " + " ; ".join(errors)}
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


def classement_batch_stream(req: ClassementBatchRequest) -> Iterator[str]:
    """Traite une tranche d'items. Le serveur re-dérive les items à l'identique
    puis sélectionne [batch_index*batch_size : +batch_size].

    Émet des événements `progress` (items_done) au fil du flux : on compte les
    lignes CSV produites *après* l'en-tête/fence, pour ignorer le préambule et le
    raisonnement. C'est une estimation live (le modèle peut omettre ou dupliquer
    des lignes) ; le front la recale sur le compte réel à l'événement `done`."""
    try:
        items = _classement_items(req.csv, req.prep)
    except Exception as e:
        yield sse.error(f"Lecture CSV impossible : {e}")
        return

    if req.batch_size and req.batch_size > 0:
        start = req.batch_index * req.batch_size
        batch = items.iloc[start:start + req.batch_size]
    else:
        batch = items

    # Consignes de classement de l'archiviste : rendu côté moteur (source unique) ;
    # vide sans consigne → prompt inchangé.
    directives_block = render_directives(
        directives_from_rows(d.model_dump() for d in req.directives),
        set(parse_plan_tree(req.plan_valide)),
    ) if req.directives else ""
    user_msg = CLA_001.build_user_message(
        csv_content=csv_to_string(batch),
        plan_valide=req.plan_valide,
        directives=directives_block,
    )
    system_prompt = CLA_001.build_system_prompt(directives=bool(directives_block))
    provider = get_provider(model=req.model, api_key=req.api_key, base_url=req.base_url)

    full_response = ""
    line_buf = ""       # ligne en cours (non encore terminée par \n)
    seen_csv = False    # a-t-on franchi l'en-tête/fence CSV ?
    items_done = 0
    start = time.monotonic()
    try:
        for is_thinking, chunk in provider.stream_with_reasoning(system_prompt, user_msg):
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
    except Exception as e:
        yield sse.error(f"Erreur LLM : {e}")
        return

    try:
        df_llm = extract_csv_from_response(full_response)
    except Exception as e:
        yield sse.error(f"Extraction CSV impossible : {e}")
        return

    yield sse.done(
        llmRows=df_to_rows(df_llm),
        rawText=full_response,
        usage=provider.last_usage,
        durationMs=round((time.monotonic() - start) * 1000),
    )


def classement_finalize(req: ClassementFinalizeRequest) -> dict:
    """Convertit les lignes LLM accumulées (tous lots) en CSV RESIP — passe unique :
    dédoublonnage des dossiers, IDs et plages de dates cohérents sur tout le vrac."""
    df_original = parse_csv_text(req.csv)
    if not req.llm_rows:
        return {"error": "Aucune ligne LLM à convertir."}
    df_llm = pd.DataFrame(req.llm_rows).astype(str)
    # Consignes : les dossiers du plan sous lesquels la création de sous-dossiers
    # est autorisée. Vide sans consigne → conversion inchangée (un dossier inventé
    # reste un hors-plan).
    allowed = directives_allowed_parents(
        directives_from_rows(d.model_dump() for d in req.directives),
        set(parse_plan_tree(req.plan_valide)),
    ) if req.directives else set()
    try:
        df_final, warnings, stats = convert_classement_to_resip(
            df_llm, df_original, req.plan_valide, allowed_parents=allowed
        )
    except Exception as e:
        return {"error": f"Conversion RESIP impossible : {e}"}
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
            "stats": stats,
        },
    }
