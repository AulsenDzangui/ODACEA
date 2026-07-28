import os
import pathlib

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "openai/openai/qwen3-14b")

# ── Mode démonstration (déploiement public, ex. Render) ──────────────────────
# Quand DEMO_MODE est actif, le backend :
#   * impose le CSV de démonstration embarqué (aucune donnée utilisateur n'est
#     envoyée au LLM, quoi qu'envoie le client) ;
#   * impose le modèle DEMO_MODEL et la clé OPENAI_API_KEY du serveur ;
#   * applique les quotas de api/demo_limits.py ;
#   * exige l'en-tête X-Demo-Proxy-Secret (si DEMO_PROXY_SECRET est défini) pour
#     bloquer les appels directs contournant le proxy front.
def _flag(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in ("1", "true", "yes", "on")

DEMO_MODE = _flag("DEMO_MODE")
DEMO_MODEL = os.getenv("DEMO_MODEL", "gpt-5.4-mini-2026-03-17")
DEMO_PROXY_SECRET = os.getenv("DEMO_PROXY_SECRET", "")
DEMO_CSV_PATH = os.getenv("DEMO_CSV_PATH") or str(
    pathlib.Path(__file__).resolve().parent.parent / "demo_assets" / "demo.csv"
)

# Origine(s) autorisée(s) pour CORS (séparées par des virgules). Vide ⇒ "*"
# (dev). En prod, renseigner l'URL du front pour restreindre.
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()
] or ["*"]

DEFAULT_MODELS = [
    "openai/openai/qwen2.5-coder-14b-instruct",
    "openai/openai/ministral-3-14b-reasoning",
    "openai/openai/qwen3-14b",
    "gpt-5.1",
    "gpt-5.4-mini-2026-03-17",
]

DEFAULT_LOCAL_ENDPOINTS = {
    "Ollama":     "http://localhost:11434",
    "LM Studio":  "http://localhost:1234/v1",
    "JAN":        "http://localhost:1337/v1",
}

LOCAL_MODEL_PREFIXES = ("ollama/", "openai/", "lm_studio/")


# ── Limites d'entrée ──────────────────────────────────────────────────────────
# Taille maximale du CSV accepté par l'API (octets, UTF-8) et garde mémoire sur
# le nombre de lignes : au-delà, la requête est refusée avec un message clair
# recommandant le découpage du vrac. Ajustables par variables d'environnement.
ODACEA_MAX_CSV_MB = float(os.getenv("ODACEA_MAX_CSV_MB", "20"))
MAX_CSV_BYTES = int(ODACEA_MAX_CSV_MB * 1024 * 1024)
MAX_CSV_ROWS = int(os.getenv("ODACEA_MAX_CSV_ROWS", "50000"))

# ── Durcissement démo ─────────────────────────────────────────────────────────
# En mode démonstration (déploiement public), une garde de taille du corps de
# requête borne la mémoire/CPU par appel, **avant même de lire le corps** (le
# Content-Length est rejeté s'il dépasse le plafond). Le seul CSV traité en démo
# étant le CSV embarqué (imposé par _force_demo, y compris sur /parse), aucun
# corps volumineux n'est légitime : 2 Mo couvrent largement les requêtes réelles
# (CSV de démo ~16 Ko + plan + lignes LLM). Ajustable par variable d'environnement.
DEMO_MAX_BODY_MB = float(os.getenv("DEMO_MAX_BODY_MB", "2"))
DEMO_MAX_BODY_BYTES = int(DEMO_MAX_BODY_MB * 1024 * 1024)

# ── Heartbeat SSE ─────────────────────────────────────────────────────────────
# Intervalle (secondes) sous lequel un commentaire SSE `: ping` est injecté quand
# le flux reste silencieux — empêche les proxys/reverse-proxys de couper une
# connexion inactive pendant les longues réflexions des modèles de raisonnement
# (avant le premier token). 0 désactive le heartbeat.
SSE_HEARTBEAT_S = float(os.getenv("ODACEA_SSE_HEARTBEAT_S", "15"))
