"""Déploiement on-prem de référence (Docker Compose).

On verrouille le *contrat* de distribution sans construire d'image (déterministe,
hors ligne — le registre Docker n'est pas requis) :
- `compose.yml` à la racine décrit bien les deux services (backend + web buildés
  depuis leurs Dockerfile), le front parlant au backend interne ;
- chaque Dockerfile porte la base et la commande d'exécution attendues ;
- les variables d'environnement structurantes sont documentées (compose +
  exemple `.env.compose.example`).

La vérification *runtime* (« testé sous Linux ») — `docker compose up` — relève
de l'installation réelle (accès au registre d'images) ; le contenu exécuté par
les images (build standalone du front, `uvicorn`/`/health` du backend) est, lui,
validé séparément.
"""
from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent
COMPOSE = REPO_ROOT / "compose.yml"
BACKEND_DOCKERFILE = BACKEND / "Dockerfile"
WEB_DOCKERFILE = REPO_ROOT / "web" / "Dockerfile"
ENV_EXAMPLE = REPO_ROOT / ".env.compose.example"


def test_compose_file_present():
    assert COMPOSE.is_file()


def test_compose_declares_both_services():
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "backend:" in compose
    assert "web:" in compose
    # Les deux services sont buildés depuis le dépôt (pas d'image externe figée).
    assert "context: ./backend" in compose
    assert "context: ./web" in compose


def test_compose_front_talks_to_internal_backend():
    compose = COMPOSE.read_text(encoding="utf-8")
    # Le proxy front (route handler) relaie vers le backend interne du réseau.
    assert "ODACEA_API_URL: http://backend:8000" in compose
    # Le front dépend du backend.
    assert "depends_on:" in compose
    # Le front est exposé sur l'hôte (port 9000 par défaut, surchargeable).
    assert "9000" in compose


def test_compose_defaults_to_institutional_mode():
    compose = COMPOSE.read_text(encoding="utf-8")
    # Installation institutionnelle : mode démonstration désactivé par défaut.
    assert "DEMO_MODE: ${DEMO_MODE:-0}" in compose


def test_backend_dockerfile_contract():
    dockerfile = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    assert "FROM python:" in dockerfile
    assert "requirements.txt" in dockerfile
    # Commande d'exécution : le moteur exposé en backend HTTP.
    assert "uvicorn" in dockerfile
    assert "api.main:app" in dockerfile
    # Sonde de vie native (sans dépendance ajoutée).
    assert "HEALTHCHECK" in dockerfile


def test_web_dockerfile_contract():
    dockerfile = WEB_DOCKERFILE.read_text(encoding="utf-8")
    assert "FROM node:" in dockerfile
    # Build autonome (image légère) activé par NEXT_OUTPUT=standalone.
    assert "NEXT_OUTPUT=standalone" in dockerfile
    assert "npm run build" in dockerfile
    # Le serveur autonome de Next.
    assert "server.js" in dockerfile


def test_env_example_documents_keys():
    env = ENV_EXAMPLE.read_text(encoding="utf-8")
    for key in ("DEFAULT_MODEL", "ODACEA_WEB_PORT", "DEMO_MODE"):
        assert key in env

