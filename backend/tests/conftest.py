"""Fixtures partagées des tests backend.

Deux familles :
  * fichiers figés (`tests/fixtures/`) — CSV de référence (Archifiltre canonique
    et export Resip natif) + golden files LLM (réponses AUD-001/CLA-001
    enregistrées) pour des tests déterministes sans appel réseau ;
  * `FakeProvider` — doublure de `llm.base.LLMProvider` qui rejoue une réponse
    canée en streaming, utilisée par les tests API (TestClient) et CLI.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Contenu texte d'une fixture (`golden/aud_small.md`, `archifiltre_small.csv`…)."""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


class FakeProvider:
    """Doublure de LLMProvider : rejoue `response` (et `reasoning`) en streaming.

    Compatible avec l'usage réel du moteur : `stream_with_reasoning()` yield des
    tuples (is_thinking, chunk), `last_usage` est disponible après épuisement,
    `complete()` répond pour `validate_connection()`.
    """

    def __init__(self, response: str = "", reasoning: str = "", chunk_size: int = 64):
        self.response = response
        self.reasoning = reasoning
        self.chunk_size = chunk_size
        self.last_usage: dict | None = None
        self.last_error: str | None = None
        self.calls: list[tuple[str, str]] = []  # (system_prompt, user_message)
        # Exceptions à lever, dans l'ordre, avant de streamer (tests retry/erreur).
        self.failures: list[Exception] = []

    # — API consommée par le moteur —

    def stream_with_reasoning(
        self, system_prompt: str, user_message: str, *, cache_user_boundary: str | None = None
    ):
        self.calls.append((system_prompt, user_message))
        if self.failures:
            raise self.failures.pop(0)
        self.last_usage = None
        for i in range(0, len(self.reasoning), self.chunk_size):
            yield True, self.reasoning[i : i + self.chunk_size]
        for i in range(0, len(self.response), self.chunk_size):
            yield False, self.response[i : i + self.chunk_size]
        self.last_usage = {
            "input_tokens": 1000,
            "output_tokens": 200,
            "total_tokens": 1200,
            "cache_read_tokens": None,
            "reasoning_tokens": None,
        }

    def complete(
        self, system_prompt: str, user_message: str, *, cache_user_boundary: str | None = None
    ) -> str:
        self.calls.append((system_prompt, user_message))
        return self.response or "OK"

    def validate_connection(self) -> bool:
        return True


class FakeToolProvider:
    """Doublure de la boucle agent : rejoue une séquence scriptée de
    réponses `complete_with_tools`.

    Chaque pas du script est soit une chaîne (contenu texte — réponse finale en
    mode natif, objet JSON sérialisé en mode repli), soit une liste d'appels
    d'outils `[(name, arguments_json), …]`. Les messages de chaque appel sont
    capturés dans `calls` (assertions « le CSV ne transite jamais »)."""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[dict] = []
        self.last_usage: dict | None = None
        self.last_error: str | None = None
        self.on_retry = None

    def complete_with_tools(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        if not self.script:
            raise AssertionError("FakeToolProvider épuisé : appel LLM de trop.")
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        step = self.script.pop(0)
        self.last_usage = {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "cache_read_tokens": None,
            "reasoning_tokens": None,
        }
        if isinstance(step, str):
            return {"content": step, "tool_calls": []}
        return {
            "content": "",
            "tool_calls": [
                {"id": f"call_{i}", "name": name, "arguments": arguments}
                for i, (name, arguments) in enumerate(step)
            ],
        }


class SequenceProvider(FakeProvider):
    """FakeProvider multi-appels : rejoue une réponse différente par appel
    (audit puis lots de classement, par exemple)."""

    def __init__(self, responses: list[str], **kwargs):
        super().__init__(response="", **kwargs)
        self.responses = list(responses)

    def stream_with_reasoning(
        self, system_prompt: str, user_message: str, *, cache_user_boundary: str | None = None
    ):
        if not self.responses:
            raise AssertionError("SequenceProvider épuisé : appel LLM de trop.")
        self.response = self.responses.pop(0)
        yield from super().stream_with_reasoning(
            system_prompt, user_message, cache_user_boundary=cache_user_boundary
        )


# ── Fixtures pytest ───────────────────────────────────────────────────────────

@pytest.fixture
def small_csv_text() -> str:
    return load_fixture("archifiltre_small.csv")


@pytest.fixture
def resip_csv_text() -> str:
    return load_fixture("resip_native_small.csv")


@pytest.fixture
def small_df(small_csv_text) -> pd.DataFrame:
    from core.csv_handler import read_csv

    return read_csv(io.BytesIO(small_csv_text.encode("utf-8")))


@pytest.fixture
def golden_aud() -> str:
    return load_fixture("golden/aud_small.md")


@pytest.fixture
def golden_cla_path() -> str:
    return load_fixture("golden/cla_small_path.md")


@pytest.fixture
def golden_cla_ref() -> str:
    return load_fixture("golden/cla_small_ref.md")


@pytest.fixture
def plan_valide(golden_aud) -> str:
    """Plan extrait du golden AUD-001 — la même matière que le wizard réel."""
    from core.csv_handler import extract_plans

    return extract_plans(golden_aud)["plan"]
