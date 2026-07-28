"""Estimation de coût € pour modèles cloud connus (`core.pricing`).

Table de prix locale, datée, indicative : on teste la logique de correspondance
(spécifique avant général), l'exclusion des modèles locaux/inconnus, le calcul
proportionnel aux tokens et le formatage français. Aucun appel réseau.
"""
import pytest

from core.pricing import (
    PRICE_TABLE,
    PRICE_TABLE_DATE,
    estimate_cost_eur,
    format_cost_eur,
    is_local,
    model_pricing,
)

# ── is_local ──────────────────────────────────────────────────────────────────

def test_is_local_base_url_always_local():
    # Un base_url renseigné = serveur local, même pour un nom de modèle cloud.
    assert is_local("claude-opus-4-8", base_url="http://localhost:1234/v1")
    assert is_local("gpt-5.1", base_url="http://localhost:1234")


def test_is_local_prefix():
    assert is_local("ollama/qwen3-14b")
    assert is_local("openai/openai/qwen3-14b")  # convention LM Studio


def test_is_local_cloud_not_local():
    assert not is_local("claude-opus-4-8")
    assert not is_local("gpt-5.1")
    assert not is_local("gemini/gemini-2.5-flash")


# ── model_pricing : correspondance ──────────────────────────────────────────────

def test_model_pricing_known_cloud_families():
    assert model_pricing("claude-opus-4-8")["label"] == "Claude Opus"
    assert model_pricing("claude-sonnet-4-6")["label"] == "Claude Sonnet"
    assert model_pricing("claude-haiku-4-5-20251001")["label"] == "Claude Haiku"
    assert model_pricing("gpt-5.1")["label"] == "GPT-5"
    assert model_pricing("gemini/gemini-2.5-flash")["label"] == "Gemini Flash"


def test_model_pricing_specific_before_general():
    # « mini » doit l'emporter sur la famille GPT-5 large.
    mini = model_pricing("gpt-5.4-mini-2026-03-17")
    full = model_pricing("gpt-5.1")
    assert mini["label"] in ("GPT-5 mini", "GPT mini")
    assert mini["inputEurPerM"] < full["inputEurPerM"]


def test_model_pricing_carries_date():
    assert model_pricing("claude-opus-4-8")["priceDate"] == PRICE_TABLE_DATE


def test_model_pricing_local_and_unknown_return_none():
    assert model_pricing("ollama/qwen3-14b") is None
    assert model_pricing("claude-opus-4-8", base_url="http://localhost:1234") is None
    assert model_pricing("un-modele-inconnu-xyz") is None
    assert model_pricing("") is None


def test_price_table_well_formed():
    for entry in PRICE_TABLE:
        assert set(entry) >= {"match", "label", "inputEurPerM", "outputEurPerM"}
        assert entry["inputEurPerM"] > 0
        assert entry["outputEurPerM"] >= entry["inputEurPerM"]  # sortie ≥ entrée


# ── estimate_cost_eur ───────────────────────────────────────────────────────────

def test_estimate_cost_proportional_to_tokens():
    pricing = model_pricing("claude-opus-4-8")
    cost = estimate_cost_eur(model="claude-opus-4-8", input_tokens=1_000_000)
    assert cost["inputEur"] == pytest.approx(pricing["inputEurPerM"])
    assert cost["outputEur"] == 0  # output non connu a priori
    assert cost["totalEur"] == cost["inputEur"]


def test_estimate_cost_input_and_output():
    cost = estimate_cost_eur(
        model="claude-opus-4-8", input_tokens=2_000_000, output_tokens=1_000_000
    )
    pricing = model_pricing("claude-opus-4-8")
    assert cost["inputEur"] == pytest.approx(2 * pricing["inputEurPerM"])
    assert cost["outputEur"] == pytest.approx(pricing["outputEurPerM"])
    assert cost["totalEur"] == pytest.approx(cost["inputEur"] + cost["outputEur"])


def test_estimate_cost_local_and_unknown_none():
    assert estimate_cost_eur(model="ollama/qwen3-14b", input_tokens=10_000) is None
    assert estimate_cost_eur(model="inconnu", input_tokens=10_000) is None
    assert estimate_cost_eur(
        model="gpt-5.1", base_url="http://localhost:1234", input_tokens=10_000
    ) is None


def test_estimate_cost_negative_tokens_clamped():
    cost = estimate_cost_eur(model="gpt-5.1", input_tokens=-100, output_tokens=-5)
    assert cost["totalEur"] == 0


# ── format_cost_eur ─────────────────────────────────────────────────────────────

def test_format_cost_eur():
    assert format_cost_eur(None) == ""
    assert format_cost_eur(0) == "0,00 €"
    assert format_cost_eur(0.0005) == "< 0,01 €"
    assert format_cost_eur(0.12) == "0,12 €"
    assert format_cost_eur(12.4) == "12,40 €"
