"""Tests déterministes du formatage des mesures de performance (`core.tokens`).

Couvre `format_tokens` (déjà utilisé en prod, non testé jusqu'ici) et la nouvelle
`format_duration` (mesure de la durée de traitement). Ces deux fonctions sont
purement déterministes : aucune dépendance LLM, vérifiables ici.
"""
import math

from core.tokens import format_duration, format_tokens


# ── format_tokens ─────────────────────────────────────────────────────────────

def test_format_tokens_below_thousand_is_plain():
    assert format_tokens(0) == "0"
    assert format_tokens(850) == "850"
    assert format_tokens(999) == "999"


def test_format_tokens_thousands_use_french_decimal():
    assert format_tokens(1500) == "1,5 k"
    assert format_tokens(12300) == "12,3 k"


# ── format_duration ───────────────────────────────────────────────────────────

def test_duration_seconds_one_decimal_french():
    assert format_duration(0) == "0,0 s"
    assert format_duration(0.34) == "0,3 s"
    assert format_duration(12.45) == "12,4 s"
    assert format_duration(59.9) == "59,9 s"


def test_duration_minutes_pads_seconds():
    assert format_duration(60) == "1 min 00 s"
    assert format_duration(185) == "3 min 05 s"
    # Arrondi à la seconde : 119,6 s → 2 min 00 s.
    assert format_duration(119.6) == "2 min 00 s"


def test_duration_hours_pads_minutes():
    assert format_duration(3600) == "1 h 00 min"
    assert format_duration(3720) == "1 h 02 min"
    assert format_duration(7384) == "2 h 03 min"


def test_duration_handles_negative_and_non_finite():
    # Une horloge monotone ne devrait jamais reculer, mais on reste robuste.
    assert format_duration(-5) == "0,0 s"
    assert format_duration(float("nan")) == "0,0 s"
    assert format_duration(float("inf")) == "0,0 s"
    assert math.isfinite(0)  # garde-fou : le module math est bien importé
