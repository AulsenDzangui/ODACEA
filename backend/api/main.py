"""App FastAPI ODACEA. Démarrage (depuis backend/) :

    uvicorn api.main:app --port 8000 --reload

Endpoints :
    POST /parse                  — parse + valide un CSV → lignes/stats/aperçu préparé/estimation tokens
    POST /parse/from-folder      — scanne un dossier local → CSV canonique dérivé + réponse /parse (backend local)
    POST /plan/from-file         — adopte un plan fourni par l'archiviste (CSV « dossiers seuls » ou Markdown), sans LLM
    POST /plan/from-folder       — scanne un dossier local existant → plan de classement (backend local, sans LLM)
    POST /apply/preview          — aperçu de l'application physique du classement (backend local, aucune écriture)
    POST /apply                  — copie physique du classement vers un dossier cible, en SSE (backend local)
    POST /audit                  — AUD-001 en SSE (reasoning/text → done{report,plan,notes,planTree})
    POST /classement/prepare     — items à classer (pilotage du découpage en lots côté front)
    POST /classement/batch       — CLA-001 sur une tranche, en SSE (reasoning/text → done{llmRows})
    POST /classement/finalize    — conversion RESIP en une passe → {resip}
    POST /validate-connection    — teste la connexion LLM
    GET  /models                 — modèles + endpoints locaux par défaut
    GET  /health                 — sonde de vie
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from api import engine
from api.schemas import (
    ApplyPreviewRequest,
    ApplyRequest,
    AuditRequest,
    ClassementBatchRequest,
    ClassementFinalizeRequest,
    ClassementPrepareRequest,
    ExtractPlansRequest,
    ParseFromFolderRequest,
    ParseRequest,
    PlanFromFileRequest,
    PlanFromFolderRequest,
    ValidateConnectionRequest,
)
from config.settings import (
    DEFAULT_LOCAL_ENDPOINTS,
    DEFAULT_MODEL,
    DEFAULT_MODELS,
)
from llm import get_provider

app = FastAPI(title="ODACEA API", version="0.2.0")

# Dev : le front Next (localhost:9000) peut appeler directement le backend.
# En prod, privilégier un proxy same-origin (rewrites Next) plutôt que CORS large.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# En-têtes pour un vrai flux SSE (désactive la bufferisation des proxys).
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(generator) -> StreamingResponse:
    return StreamingResponse(generator, media_type="text/event-stream", headers=_SSE_HEADERS)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/models")
def models() -> dict:
    return {
        "default": DEFAULT_MODEL,
        "models": DEFAULT_MODELS,
        "localEndpoints": DEFAULT_LOCAL_ENDPOINTS,
    }


@app.post("/parse")
def parse(req: ParseRequest):
    try:
        return engine.parse_payload(req.csv, req.prep, req.batch_size)
    except Exception as e:
        return JSONResponse({"error": f"Lecture CSV impossible : {e}"}, status_code=400)


@app.post("/parse/from-folder")
def parse_from_folder(req: ParseFromFolderRequest):
    """Importe un **dossier local** en dérivant son CSV canonique (scan de
    métadonnées, aucun binaire ouvert) puis renvoie la même réponse que /parse +
    `derivedCsv` + `scan`. **Backend local uniquement.**"""
    payload = engine.parse_from_folder_payload(req)
    if "error" in payload:
        status = 413 if payload.get("code") == "csv_too_large" else 400
        return JSONResponse(payload, status_code=status)
    return payload


@app.post("/plan/from-file")
def plan_from_file(req: PlanFromFileRequest):
    """Adopte un plan fourni par l'archiviste (CSV Resip « dossiers seuls » ou
    Markdown canonique) **sans appel LLM** → `{plan, planTree, folderCount,
    rootTitle, warnings, format}`. Conversion en mémoire (aucun accès disque)."""
    payload = engine.plan_from_file_payload(req.name, req.content)
    if "error" in payload:
        return JSONResponse(payload, status_code=400)
    return payload


@app.post("/plan/from-folder")
def plan_from_folder(req: PlanFromFolderRequest):
    """Scanne un **dossier local** existant et en reconstruit un plan de
    classement (noms de dossiers seuls, aucun binaire ouvert). **Backend local
    uniquement.**"""
    payload = engine.plan_from_folder_payload(req)
    if "error" in payload:
        return JSONResponse(payload, status_code=400)
    return payload


@app.post("/apply/preview")
def apply_preview(req: ApplyPreviewRequest):
    """Aperçu de l'application physique du classement (total, collisions, binaires
    introuvables, items à la racine, garde-fous cible) **avant toute écriture**.
    **Backend local uniquement.**"""
    payload = engine.apply_preview_payload(req)
    if "error" in payload:
        return JSONResponse(payload, status_code=400)
    return payload


@app.post("/apply")
def apply(req: ApplyRequest):
    """Copie physique du classement vers `target_root` en SSE (`progress` puis
    `done{stats}`). **La source n'est jamais mutée** (copie seule). **Backend
    local uniquement.**"""
    return _sse(engine.apply_stream(req))


@app.post("/audit")
def audit(req: AuditRequest):
    return _sse(engine.audit_stream(req))


@app.post("/classement/prepare")
def classement_prepare(req: ClassementPrepareRequest):
    return engine.classement_prepare(req)


@app.post("/classement/batch")
def classement_batch(req: ClassementBatchRequest):
    return _sse(engine.classement_batch_stream(req))


@app.post("/classement/finalize")
def classement_finalize(req: ClassementFinalizeRequest):
    return engine.classement_finalize(req)


@app.post("/extract-plans")
def extract_plans(req: ExtractPlansRequest):
    return engine.extract_plans_payload(req.report)


@app.post("/validate-connection")
def validate_connection(req: ValidateConnectionRequest):
    try:
        provider = get_provider(model=req.model, api_key=req.api_key, base_url=req.base_url)
        if provider.validate_connection():
            return {"ok": True}
        return {"ok": False, "error": provider.last_error or "Échec"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
