# Image du moteur ODACEA exposé en backend HTTP (FastAPI).
# Installation institutionnelle de référence : voir compose.yml à la
# racine et docs/INSTALLATION_ONPREM.md.
FROM python:3.12-slim

# Pas de .pyc, sortie non bufferisée (logs immédiats sous Docker).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Couche de dépendances séparée (cache de build tant que requirements ne bouge pas).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code du moteur + interfaces (api/, cli.py, core/, llm/, prompts/, config/…).
COPY . .

# Backend sans état : rien n'est persisté côté serveur. Utilisateur non-root.
RUN useradd --create-home --uid 10001 odacea
USER odacea

EXPOSE 8000

# Sonde de vie native (sans dépendance ajoutée) : GET /health.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
