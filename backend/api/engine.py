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
from core.audit_scan import format_digest, scan_metadata
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

    user_msg = CLA_001.build_user_message(
        csv_content=csv_to_string(batch), plan_valide=req.plan_valide
    )
    provider = get_provider(model=req.model, api_key=req.api_key, base_url=req.base_url)

    full_response = ""
    line_buf = ""       # ligne en cours (non encore terminée par \n)
    seen_csv = False    # a-t-on franchi l'en-tête/fence CSV ?
    items_done = 0
    start = time.monotonic()
    try:
        for is_thinking, chunk in provider.stream_with_reasoning(CLA_001.SYSTEM_PROMPT, user_msg):
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
    try:
        df_final, warnings, stats = convert_classement_to_resip(df_llm, df_original, req.plan_valide)
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
