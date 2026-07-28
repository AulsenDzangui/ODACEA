"""Tests du budget de profondeur d'entrée — `core/prep_budget.py`.

Fonctions pures et déterministes (aucun LLM) : recommandation d'échantillonnage
par taille de vrac + mise en forme de la ligne de diagnostic du dry-run.
"""
from core.prep_budget import (
    BUDGET_TIERS,
    RECOMMENDED_CLEAN_DATES,
    format_budget_line,
    recommend_prep,
)


def test_small_vrac_recommends_no_sampling():
    rec = recommend_prep(50)
    assert rec["tier"] == "petit"
    assert rec["sampleN"] == 0  # tout envoyer
    assert rec["cleanDates"] is RECOMMENDED_CLEAN_DATES
    assert rec["itemCount"] == 50
    assert rec["tableDate"]
    assert rec["rationale"]


def test_tiers_are_monotone_in_size():
    """Plus le vrac est gros, moins on échantillonne (sampleN décroissant, sauf
    le palier 0 = « tous » réservé au plus petit)."""
    petit = recommend_prep(200)["sampleN"]
    moyen = recommend_prep(1000)["sampleN"]
    grand = recommend_prep(5000)["sampleN"]
    tres_grand = recommend_prep(50000)["sampleN"]
    assert petit == 0  # « tous »
    assert moyen >= grand >= tres_grand >= 1


def test_boundaries_inclusive():
    # Borne haute incluse dans le palier (≤ maxItems).
    assert recommend_prep(200)["tier"] == "petit"
    assert recommend_prep(201)["tier"] == "moyen"
    assert recommend_prep(1000)["tier"] == "moyen"
    assert recommend_prep(1001)["tier"] == "grand"


def test_negative_and_zero_clamped():
    assert recommend_prep(0)["itemCount"] == 0
    assert recommend_prep(-5)["itemCount"] == 0
    assert recommend_prep(0)["tier"] == "petit"


def test_last_tier_is_catch_all():
    assert BUDGET_TIERS[-1]["maxItems"] is None
    huge = recommend_prep(10_000_000)
    assert huge["tier"] == BUDGET_TIERS[-1]["tier"]


def test_format_line_match_marks_ok():
    rec = recommend_prep(50)  # sampleN=0
    line = format_budget_line(rec, current_sample_n=0)
    assert "recommandé ✓" in line
    assert "petit" in line


def test_format_line_diff_shows_recommended_and_delta():
    rec = recommend_prep(50)  # recommande 0 (tous)
    line = format_budget_line(
        rec, current_sample_n=5, current_tokens=1000, recommended_tokens=1400
    )
    assert "recommandé tous" in line
    assert "1400" in line
    assert "+400" in line  # delta positif (envoyer tous = plus de tokens)


def test_format_line_negative_delta_uses_minus_sign():
    rec = recommend_prep(5000)  # grand → sampleN=3
    line = format_budget_line(
        rec, current_sample_n=5, current_tokens=2000, recommended_tokens=1500
    )
    assert "recommandé 3/dossier" in line
    assert "−500" in line  # signe moins typographique
