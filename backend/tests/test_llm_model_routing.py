"""Routage du nom de modèle vers un provider LiteLLM (`_effective_model`).

LiteLLM encode le fournisseur **dans le nom du modèle** (`openai/…`, `ollama/…`) ;
sans préfixe reconnu il lève « LLM Provider NOT provided ». Un serveur joint par
`base_url` (LM Studio, JAN, mais aussi une passerelle distante vLLM / TGI /
LiteLLM Proxy) parle le dialecte OpenAI : c'est donc `openai/` qu'il faut poser.

Le piège verrouillé ici : la convention HuggingFace `organisation/modèle` contient
un `/` **sans** être un préfixe de provider. Tester la présence d'un `/` laissait
passer `mistralai/Mistral-Small-…` tel quel, et l'appel échouait.

Aucun appel réseau : `_effective_model` est une fonction pure.
"""
from __future__ import annotations

import pytest

from llm.litellm_provider import LiteLLMProvider, _litellm_provider_prefixes

LOCAL = "http://passerelle.interne/v1"


def _model(name: str, base_url: str | None = LOCAL) -> str:
    return LiteLLMProvider._effective_model(name, base_url)


# ── Serveur compatible OpenAI (base_url renseigné) ───────────────────────────

def test_nom_court_est_prefixe():
    """Cas LM Studio / JAN : un nom sans `/` reçoit le préfixe."""
    assert _model("qwen3-14b") == "openai/qwen3-14b"


def test_nom_huggingface_est_prefixe():
    """Cas passerelle vLLM : `organisation/modèle` doit être préfixé aussi.

    Non-régression du problème remonté à l'installation : le `/` de la
    convention HuggingFace n'est pas un préfixe de provider.
    """
    assert (
        _model("mistralai/Mistral-Small-3.2-24B-Instruct-2506")
        == "openai/mistralai/Mistral-Small-3.2-24B-Instruct-2506"
    )


@pytest.mark.parametrize(
    "name",
    [
        "ollama/qwen2.5:14b",
        "openai/mistralai/Mistral-Small-3.2-24B-Instruct-2506",
        "gemini/gemini-2.0-flash",
        "anthropic/claude-sonnet-4-6",
    ],
)
def test_prefixe_explicite_respecte(name: str):
    """Un préfixe de provider déjà posé n'est jamais redoublé."""
    assert _model(name) == name


def test_organisation_homonyme_dun_provider_non_reprefixee():
    """Ambiguïté assumée : `openai/…` est lu comme un préfixe, pas une organisation."""
    assert _model("openai/gpt-oss-120b") == "openai/gpt-oss-120b"


def test_modele_vide_retombe_sur_le_modele_charge():
    """Sans nom, on laisse le serveur servir le modèle qu'il a déjà chargé."""
    assert _model("") == "openai/local-model"
    assert _model("   ") == "openai/local-model"


# ── Fournisseur cloud (aucun base_url) ───────────────────────────────────────

@pytest.mark.parametrize("name", ["claude-sonnet-4-6", "gpt-5.1", "gemini/gemini-2.0-flash"])
def test_sans_base_url_le_nom_est_intouche(name: str):
    """Le dispatch cloud se fait sur le préfixe du nom : ne rien ajouter."""
    assert _model(name, base_url=None) == name
    assert _model(name, base_url="") == name


# ── Source des préfixes ──────────────────────────────────────────────────────

def test_prefixes_lus_depuis_litellm():
    """La liste vient de LiteLLM et couvre les fournisseurs que le projet route."""
    prefixes = _litellm_provider_prefixes()
    assert {"openai", "anthropic", "gemini", "ollama"} <= prefixes
    # L'organisation HuggingFace du cas remonté n'est pas un fournisseur.
    assert "mistralai" not in prefixes
