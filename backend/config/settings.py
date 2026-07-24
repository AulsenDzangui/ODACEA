import os
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "openai/openai/qwen3-14b")

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

# Garde mémoire : nombre maximal de lignes acceptées à l'entrée (CSV ou scan de
# dossier). Au-delà, le vrac doit être découpé avant traitement.
MAX_CSV_ROWS = int(os.getenv("ODACEA_MAX_CSV_ROWS", "50000"))

