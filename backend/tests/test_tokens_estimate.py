"""Estimation a priori et comptabilité d'usage réel (`core.tokens`).

Complète test_tokens.py (formatage) : ici l'estimation AUD/CLA avec découpage
en lots, et l'agrégation/affichage de l'usage réel renvoyé par le serveur.
"""
from core.tokens import estimate_tokens, format_usage_line, sum_usage

# ── estimate_tokens ──────────────────────────────────────────────────────────

def test_estimate_tokens_structure_and_consistency(small_df):
    e = estimate_tokens(small_df)
    assert set(e) == {
        "audit_tokens", "classement_tokens_per_batch", "classement_batches",
        "classement_total_tokens", "total_tokens",
    }
    assert e["audit_tokens"] > 0
    assert e["classement_batches"] == 1  # pas de découpage : 6 items en un lot
    assert e["classement_total_tokens"] == e["classement_tokens_per_batch"]
    assert e["total_tokens"] == e["audit_tokens"] + e["classement_total_tokens"]


def test_estimate_tokens_batching_splits_cost(small_df):
    e = estimate_tokens(small_df, batch_size=2)
    assert e["classement_batches"] == 3  # 6 items / 2
    # Le total des lots dépasse un lot seul (boilerplate répété par lot).
    assert e["classement_total_tokens"] > e["classement_tokens_per_batch"]


def test_estimate_tokens_sampling_reduces_audit_cost(small_df):
    full = estimate_tokens(small_df, sample_items_n=0)
    sampled = estimate_tokens(small_df, sample_items_n=1)
    assert sampled["audit_tokens"] < full["audit_tokens"]
    # L'échantillonnage ne touche que l'audit, pas le classement.
    assert sampled["classement_total_tokens"] == full["classement_total_tokens"]


def test_estimate_tokens_folders_only_reduces_audit_cost(small_df):
    """Arborescence seule (include_items=False) : audit moins coûteux que
    l'envoi de tous les fichiers, sans toucher au classement."""
    full = estimate_tokens(small_df, sample_items_n=0)
    folders_only = estimate_tokens(small_df, include_items=False)
    assert folders_only["audit_tokens"] < full["audit_tokens"]
    assert folders_only["classement_total_tokens"] == full["classement_total_tokens"]


def test_estimate_tokens_empty_items():
    import pandas as pd

    from core.csv_handler import REQUIRED_COLUMNS

    df = pd.DataFrame(
        [{c: "" for c in REQUIRED_COLUMNS}], columns=REQUIRED_COLUMNS
    )
    df.loc[0, ["ID", "File", "Content.DescriptionLevel"]] = ["1", ".", "RecordGrp"]
    e = estimate_tokens(df)
    assert e["classement_batches"] == 1
    assert e["total_tokens"] > 0


# ── sum_usage / format_usage_line ────────────────────────────────────────────

def _usage(inp, out, total, cache=None, reasoning=None):
    return {
        "input_tokens": inp, "output_tokens": out, "total_tokens": total,
        "cache_read_tokens": cache, "reasoning_tokens": reasoning,
    }


def test_sum_usage_aggregates_and_skips_invalid():
    total = sum_usage([
        _usage(100, 50, 150),
        None,
        {"total_tokens": None},
        _usage(200, 100, 300, cache=40),
    ])
    assert total == {
        "input_tokens": 300, "output_tokens": 150, "total_tokens": 450,
        "cache_read_tokens": 40, "reasoning_tokens": 0,
    }


def test_sum_usage_none_when_nothing_usable():
    assert sum_usage([None, {"total_tokens": 0}]) is None
    assert sum_usage([]) is None


def test_format_usage_line_full():
    line = format_usage_line(_usage(1500, 200, 1700, cache=100, reasoning=50), "AUD-001")
    assert line.startswith("**AUD-001** — ")
    assert "1,7 k tokens réels" in line
    assert "entrée : 1,5 k" in line
    assert "cache : 100" in line and "thinking : 50" in line


def test_format_usage_line_empty_cases():
    assert format_usage_line(None) == ""
    assert format_usage_line({"total_tokens": 0}) == ""
