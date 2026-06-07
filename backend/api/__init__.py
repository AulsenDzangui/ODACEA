"""Backend HTTP ODACEA — expose le moteur Python (core/llm/prompts) au front
React/Next via une API JSON + SSE. Sans état : le front renvoie le CSV brut à
chaque appel. Voir api/main.py pour les endpoints."""
