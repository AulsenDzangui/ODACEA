"""App FastAPI ODACEA. Démarrage (depuis backend/) :

    uvicorn api.main:app --port 8000 --reload

Endpoints :
    POST /parse                  — parse + valide un CSV → lignes/stats/aperçu préparé/estimation tokens
    POST /enrich                 — étape 0 facultative (backend local) : description/empreinte des binaires
    POST /audit                  — AUD-001 en SSE (reasoning/text → done{report,plan,notes,planTree})
    POST /classement/prepare     — items à classer (pilotage du découpage en lots côté front)
    POST /classement/batch       — CLA-001 sur une tranche, en SSE (reasoning/text → done{llmRows})
    POST /classement/finalize    — conversion RESIP en une passe → {resip}
    POST /journal — journal de traitement horodaté → {markdown, journal}
    POST /manifest — manifeste d'arborescence modèle → {markdown, manifest}
    POST /plan-compare — comparaison multi-plans → {variants, comparison, markdown}
    POST /agt/session — session d'exploration de vrac (dérogation « sans état »)
    GET/DELETE /agt/session/{id} — statut / suppression d'une session
    POST /agt/chat               — agent AGT-001 en SSE (tool/toolResult/text → done), lecture seule
    DELETE /agt/session/{id}/history — réinitialise la conversation en cours (session conservée)
    POST /validate-connection    — teste la connexion LLM
    GET  /models                 — modèles + endpoints locaux par défaut
    POST /reference-plan/from-csv — CSV Resip « dossiers seuls » → plan de classement de référence
    POST /plan/from-file — plan fourni par l'archiviste adopté sans appel LLM
    POST /plan/materialize — matérialise le plan en dossiers vides réels (backend local)
    POST /plan/from-folder — re-scanne le répertoire réorganisé → plan canonique (backend local)
    POST /parse/from-folder — scanne un dossier local → CSV canonique + réponse /parse (backend local)
    POST /apply/preview — aperçu de l'application physique du classement (backend local)
    POST /apply — copie du classement vers l'arborescence cible en SSE (backend local)
    GET  /health                 — sonde de vie
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import pathlib

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from api import demo_limits, engine, sse
from api.schemas import (
    AgtChatRequest,
    AgtSessionRequest,
    ApplyPreviewRequest,
    ApplyRequest,
    AuditRequest,
    ClassementBatchRequest,
    ClassementFinalizeRequest,
    ClassementPrepareRequest,
    EnrichRequest,
    ExtractPlansRequest,
    JournalRequest,
    ManifestRequest,
    ParseFromFolderRequest,
    ParseRequest,
    PlanCompareRequest,
    PlanFromFileRequest,
    PlanFromFolderRequest,
    PlanMaterializeRequest,
    ReferencePlanFromCsvRequest,
    ValidateConnectionRequest,
)
from config.settings import (
    ALLOWED_ORIGINS,
    DEFAULT_LOCAL_ENDPOINTS,
    DEFAULT_MODEL,
    DEFAULT_MODELS,
    DEMO_CSV_PATH,
    DEMO_MAX_BODY_BYTES,
    DEMO_MAX_BODY_MB,
    DEMO_MODE,
    DEMO_MODEL,
    DEMO_PROXY_SECRET,
    SSE_HEARTBEAT_S,
)
from llm import get_provider

app = FastAPI(title="ODACEA API", version="0.2.0")

# Dev : le front Next (localhost:9000) peut appeler directement le backend.
# En prod (démo), ALLOWED_ORIGINS restreint l'origine à l'URL du front.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _demo_body_too_large(request: Request) -> JSONResponse | None:
    """Durcissement démo : rejette un corps de requête au-delà du plafond
    `DEMO_MAX_BODY_BYTES` d'après l'en-tête `Content-Length`, **avant** de lire le
    corps — borne la mémoire/CPU par appel sur la démo publique. La démo
    n'analyse que le CSV embarqué (forcé), donc aucun corps volumineux n'est
    légitime. Content-Length absent (corps en chunked) → laissé passer ; la garde
    d'entrée (taille CSV) prend alors le relais après parsing."""
    cl = request.headers.get("content-length")
    if cl is None:
        return None
    try:
        size = int(cl)
    except ValueError:
        return None
    if size <= DEMO_MAX_BODY_BYTES:
        return None
    return JSONResponse(
        {
            "error": (
                f"Requête trop volumineuse pour la démonstration "
                f"({size / (1024 * 1024):.1f} Mo reçus ; maximum {DEMO_MAX_BODY_MB:g} Mo)."
            ),
            "code": "demo_payload_too_large",
            "hint": (
                "La démonstration n'analyse qu'un jeu de données imposé. "
                "Installez ODACEA en local pour traiter vos propres vracs."
            ),
        },
        status_code=413,
    )


# Garde d'accès en démonstration : tous les appels passent par le proxy front,
# qui injecte X-Demo-Proxy-Secret. Sans ce secret, on bloque — ce qui empêche
# d'attaquer le backend en direct (la clé OpenAI et les quotas vivent ici).
# /health est exempté (sonde Render, sans secret). Un plafond de taille de corps
# Borne en amont la consommation par requête sur la démo publique.
@app.middleware("http")
async def demo_guard(request: Request, call_next):
    if DEMO_MODE:
        too_large = _demo_body_too_large(request)
        if too_large is not None:
            return too_large
        if DEMO_PROXY_SECRET and request.url.path != "/health":
            if request.headers.get("x-demo-proxy-secret") != DEMO_PROXY_SECRET:
                return JSONResponse({"error": "Accès refusé."}, status_code=403)
    return await call_next(request)


def _client_ip(request: Request) -> str:
    """IP réelle du visiteur. En démo, le proxy front (authentifié par le secret)
    la dérive du hop de confiance et la pose dans `X-Demo-Client-IP` — on s'y fie
    en priorité. À défaut (dev / appel direct), repli sur le premier maillon de
    X-Forwarded-For puis sur l'IP de connexion. On ne lit *pas* le premier maillon
    de X-Forwarded-For en priorité : il est fourni par le client, donc falsifiable."""
    posed = request.headers.get("x-demo-client-ip")
    if posed:
        return posed.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

# En-têtes pour un vrai flux SSE (désactive la bufferisation des proxys).
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(generator) -> StreamingResponse:
    # Heartbeat : `: ping` pendant les silences > SSE_HEARTBEAT_S (longues
    # réflexions des modèles de raisonnement) pour ne pas se faire couper par un
    # proxy. Désactivable via ODACEA_SSE_HEARTBEAT_S=0.
    stream = sse.with_heartbeat(generator, SSE_HEARTBEAT_S)
    return StreamingResponse(stream, media_type="text/event-stream", headers=_SSE_HEADERS)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/models")
def models() -> dict:
    return {
        "default": DEMO_MODEL if DEMO_MODE else DEFAULT_MODEL,
        "models": [DEMO_MODEL] if DEMO_MODE else DEFAULT_MODELS,
        "localEndpoints": {} if DEMO_MODE else DEFAULT_LOCAL_ENDPOINTS,
        "demoMode": DEMO_MODE,
    }


@app.get("/demo/csv")
def demo_csv():
    """Sert le CSV de démonstration embarqué (chargé par le front en mode démo)."""
    text = pathlib.Path(DEMO_CSV_PATH).read_text(encoding="utf-8-sig")
    return PlainTextResponse(text, media_type="text/csv; charset=utf-8")


@app.get("/demo/status")
def demo_status() -> dict:
    """Quota global du jour (pour l'affichage). Aucune donnée personnelle."""
    return {"demoMode": DEMO_MODE, **demo_limits.snapshot()}


@app.post("/parse")
def parse(req: ParseRequest):
    # Durcissement : en démo, n'analyser que le CSV embarqué (jamais un CSV
    # fourni par le client), comme /audit et /classement.
    engine._force_demo(req)
    try:
        return engine.parse_payload(
            req.csv, req.prep, req.batch_size, model=req.model, base_url=req.base_url
        )
    except engine.CsvLimitError as e:
        return JSONResponse(
            {"error": str(e), "code": "csv_too_large", "hint": e.hint},
            status_code=413,
        )
    except Exception as e:
        return JSONResponse(
            {
                "error": f"Lecture CSV impossible : {e}",
                "code": "csv_unreadable",
                "hint": "Vérifiez que le fichier est un export Archifiltre/Resip (séparateur « ; », UTF-8).",
            },
            status_code=400,
        )


@app.post("/reference-plan/from-csv")
def reference_plan_from_csv(req: ReferencePlanFromCsvRequest):
    """Convertit un CSV Resip « dossiers seuls » en plan de classement de
    référence → `{tree, validationErrors, warnings, folderCount,
    ignoredItemCount, rootTitle}`. Mêmes contrôles d'entrée que /parse."""
    try:
        return engine.reference_plan_from_csv(req.csv)
    except engine.CsvLimitError as e:
        return JSONResponse(
            {"error": str(e), "code": "csv_too_large", "hint": e.hint},
            status_code=413,
        )
    except Exception as e:
        return JSONResponse(
            {
                "error": f"Lecture CSV impossible : {e}",
                "code": "csv_unreadable",
                "hint": "Vérifiez que le fichier est un export Archifiltre/Resip (séparateur « ; », UTF-8).",
            },
            status_code=400,
        )


@app.post("/plan/from-file")
def plan_from_file(req: PlanFromFileRequest):
    """Adopte un plan fourni par l'archiviste (CSV Resip « dossiers seuls » ou
    Markdown canonique) **sans appel LLM** → `{plan, planTree, folderCount,
    rootTitle, warnings, format}`. Aucun accès disque : conversion en mémoire, donc
    disponible aussi en démonstration."""
    payload = engine.plan_from_file_payload(req.name, req.content)
    if "error" in payload:
        status = 413 if payload.get("code") == "csv_too_large" else 400
        return JSONResponse(payload, status_code=status)
    return payload


def _local_only_refused(message: str, code: str) -> JSONResponse | None:
    """Refus générique en mode démonstration pour un endpoint qui **lit/écrit des
    dossiers locaux** (comme `enrich`) : sur un déploiement hébergé, le chemin
    fourni n'existerait pas côté serveur et exposer le système de fichiers serait
    une faille. `None` hors démo (endpoint autorisé)."""
    if not DEMO_MODE:
        return None
    return JSONResponse(
        {
            "error": message,
            "code": code,
            "hint": ("Cette fonction lit/écrit des dossiers locaux : installez ODACEA "
                     "en local (backend sur votre machine)."),
        },
        status_code=403,
    )


def _plan_local_only_refused() -> JSONResponse | None:
    """Ces endpoints lisent/écrivent des dossiers **locaux** : refusés en mode démonstration."""
    return _local_only_refused(
        "Édition du plan par l'Explorateur indisponible en mode démonstration.",
        "plan_local_only",
    )


@app.post("/plan/materialize")
def plan_materialize(req: PlanMaterializeRequest):
    """Matérialise le plan courant en **dossiers vides réels** dans un
    répertoire de travail local (**backend local uniquement**)."""
    refused = _plan_local_only_refused()
    if refused is not None:
        return refused
    payload = engine.plan_materialize_payload(req)
    if "error" in payload:
        return JSONResponse(payload, status_code=400)
    return payload


@app.post("/plan/from-folder")
def plan_from_folder(req: PlanFromFolderRequest):
    """Re-scanne le répertoire de travail réorganisé dans l'Explorateur et
    reconstruit le plan canonique + un aperçu des changements (**backend local
    uniquement**)."""
    refused = _plan_local_only_refused()
    if refused is not None:
        return refused
    payload = engine.plan_from_folder_payload(req)
    if "error" in payload:
        return JSONResponse(payload, status_code=400)
    return payload


@app.post("/parse/from-folder")
def parse_from_folder(req: ParseFromFolderRequest):
    """Importe un **dossier local** en dérivant son CSV canonique (scan de
    métadonnées, aucun binaire ouvert) puis renvoie la même réponse que /parse +
    `derivedCsv` + `scan`. **Backend local uniquement** (refus démo)."""
    refused = _local_only_refused(
        "Import direct d'un dossier indisponible en mode démonstration.",
        "parse_local_only",
    )
    if refused is not None:
        return refused
    payload = engine.parse_from_folder_payload(req)
    if "error" in payload:
        status = 413 if payload.get("code") == "csv_too_large" else 400
        return JSONResponse(payload, status_code=status)
    return payload


@app.post("/apply/preview")
def apply_preview(req: ApplyPreviewRequest):
    """Aperçu de l'application physique du classement (total, collisions,
    binaires introuvables, items à la racine, garde-fous cible) **avant toute
    écriture**. **Backend local uniquement** (refus démo)."""
    refused = _local_only_refused(
        "Application du classement indisponible en mode démonstration.",
        "apply_local_only",
    )
    if refused is not None:
        return refused
    payload = engine.apply_preview_payload(req)
    if "error" in payload:
        return JSONResponse(payload, status_code=400)
    return payload


@app.post("/apply")
def apply(req: ApplyRequest):
    """Copie physique du classement vers l'arborescence cible, en SSE
    (progression + `done{stats}`). La **source n'est jamais mutée**. **Backend
    local uniquement** (refus démo)."""
    refused = _local_only_refused(
        "Application du classement indisponible en mode démonstration.",
        "apply_local_only",
    )
    if refused is not None:
        return refused
    return _sse(engine.apply_stream(req))


@app.post("/audit")
def audit(req: AuditRequest, request: Request):
    reservation = None
    if DEMO_MODE:
        try:
            reservation = demo_limits.begin(_client_ip(request), "audit")
        except demo_limits.DemoLimitError as e:
            return JSONResponse(
                {"error": e.message, "code": "demo_quota",
                 "hint": "Quota de démonstration atteint : réessayez demain ou installez ODACEA en local."},
                status_code=429,
            )
    return _sse(engine.audit_stream(req, reservation=reservation))


@app.post("/classement/prepare")
def classement_prepare(req: ClassementPrepareRequest):
    return engine.classement_prepare(req)


@app.post("/classement/batch")
def classement_batch(req: ClassementBatchRequest, request: Request):
    reservation = None
    if DEMO_MODE:
        try:
            reservation = demo_limits.begin(_client_ip(request), "classement")
        except demo_limits.DemoLimitError as e:
            return JSONResponse(
                {"error": e.message, "code": "demo_quota",
                 "hint": "Quota de démonstration atteint : réessayez demain ou installez ODACEA en local."},
                status_code=429,
            )
    return _sse(engine.classement_batch_stream(req, reservation=reservation))


@app.post("/classement/finalize")
def classement_finalize(req: ClassementFinalizeRequest):
    return engine.classement_finalize(req)


@app.post("/enrich")
def enrich(req: EnrichRequest):
    """Étape 0 facultative `enrich` — **backend local uniquement**.

    Le serveur lit les binaires sous `sourceRoot` (machine de l'archiviste). En
    mode démonstration (déploiement hébergé), l'endpoint est refusé : exposer le
    système de fichiers du serveur serait une faille, et le chemin fourni par le
    front n'existerait pas côté serveur de toute façon.
    """
    if DEMO_MODE:
        return JSONResponse(
            {
                "error": "Enrichissement indisponible en mode démonstration.",
                "code": "enrich_disabled",
                "hint": (
                    "Cette étape lit des fichiers locaux : installez ODACEA en "
                    "local (backend sur votre machine) pour enrichir un vrac."
                ),
            },
            status_code=403,
        )
    payload = engine.enrich_payload(req)
    if "error" in payload:
        status = 413 if payload.get("code") == "csv_too_large" else 400
        return JSONResponse(payload, status_code=status)
    return payload


@app.post("/extract-plans")
def extract_plans(req: ExtractPlansRequest):
    return engine.extract_plans_payload(req.report)


@app.post("/journal")
def journal(req: JournalRequest):
    """Journal de traitement — traçabilité réglementaire, rendu local.

    Le front renvoie les métadonnées du traitement (jamais le contenu) ; le moteur
    rend un journal horodaté (`{markdown, journal}`) à télécharger/archiver. Sans
    état, sans appel LLM ; le rendu reste côté moteur (source unique)."""
    return engine.journal_payload(req)


@app.post("/manifest")
def manifest(req: ManifestRequest):
    """Manifeste d'arborescence modèle — export local au-delà du CSV.

    Le front renvoie les lignes du CSV RESIP produit (`resip.rows` de finalize) ;
    le moteur en dérive l'arborescence de répertoires cible (`{markdown,
    manifest}`) à télécharger/archiver. Sans état, sans appel LLM ; métadonnées
    seules ; rendu côté moteur (source unique)."""
    return engine.manifest_payload(req)


@app.post("/plan-compare")
def plan_compare(req: PlanCompareRequest):
    """Comparaison multi-plans — audit comparatif piloté par le front.

    Le front lance AUD-001 plusieurs fois et renvoie les plans obtenus (`plans`) ;
    le moteur les compare structurellement (`{variants, comparison, markdown}`)
    pour que l'archiviste choisisse. Sans état, sans appel LLM ; métadonnées
    seules ; rendu côté moteur (source unique)."""
    return engine.plan_compare_payload(req)


def _agt_demo_refused() -> JSONResponse | None:
    """L'agent est refusé en démonstration : il introduit de l'état
    serveur (sessions en mémoire) et des appels LLM multi-tours non bornés par
    les quotas par étape — surface inutile sur le déploiement public."""
    if not DEMO_MODE:
        return None
    return JSONResponse(
        {
            "error": "Agent indisponible en mode démonstration.",
            "code": "agt_disabled",
            "hint": "Installez ODACEA en local pour dialoguer avec l'agent d'exploration.",
        },
        status_code=403,
    )


@app.post("/agt/session")
def agt_session(req: AgtSessionRequest):
    """Crée une session d'exploration de vrac — dérogation documentée au
    « backend sans état » : cache de travail en mémoire process avec TTL,
    recréable depuis le projet client."""
    refused = _agt_demo_refused()
    if refused is not None:
        return refused
    try:
        payload = engine.agt_session_create(req)
    except engine.CsvLimitError as e:
        return JSONResponse(
            {"error": str(e), "code": "csv_too_large", "hint": e.hint}, status_code=413
        )
    except Exception as e:
        return JSONResponse(
            {
                "error": f"Lecture CSV impossible : {e}",
                "code": "csv_unreadable",
                "hint": "Vérifiez que le fichier est un export Archifiltre/Resip (séparateur « ; », UTF-8).",
            },
            status_code=400,
        )
    if "error" in payload:
        return JSONResponse(payload, status_code=400)
    return payload


@app.get("/agt/session/{session_id}")
def agt_session_status(session_id: str):
    refused = _agt_demo_refused()
    if refused is not None:
        return refused
    payload = engine.agt_session_status(session_id)
    if "error" in payload:
        return JSONResponse(payload, status_code=404)
    return payload


@app.delete("/agt/session/{session_id}")
def agt_session_delete(session_id: str):
    refused = _agt_demo_refused()
    if refused is not None:
        return refused
    return engine.agt_session_delete(session_id)


_AGT_ERROR_STATUS = {
    "agt_session_expired": 404,
}


def _agt_json(payload: dict):
    """Mappe les erreurs à code stable des endpoints agent sur leur statut HTTP."""
    if "error" in payload:
        return JSONResponse(
            payload, status_code=_AGT_ERROR_STATUS.get(payload.get("code", ""), 400)
        )
    return payload


@app.delete("/agt/session/{session_id}/history")
def agt_conversation_reset(session_id: str):
    """Réinitialise la conversation en cours : vide l'historique de
    dialogue sans détruire la session."""
    refused = _agt_demo_refused()
    if refused is not None:
        return refused
    return _agt_json(engine.agt_conversation_reset(session_id))


@app.post("/agt/chat")
def agt_chat(req: AgtChatRequest):
    """Un tour de dialogue avec l'agent (AGT-001) en SSE — événements
    `tool`/`toolResult` (transparence), `text`, puis `done{answer, usage…}`."""
    refused = _agt_demo_refused()
    if refused is not None:
        return refused
    return _sse(engine.agt_chat_stream(req))


@app.post("/validate-connection")
def validate_connection(req: ValidateConnectionRequest):
    if DEMO_MODE:
        return {"ok": False, "error": "Test de connexion désactivé en mode démonstration."}
    try:
        provider = get_provider(model=req.model, api_key=req.api_key, base_url=req.base_url)
        if provider.validate_connection():
            return {"ok": True}
        return {"ok": False, "error": provider.last_error or "Échec"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
