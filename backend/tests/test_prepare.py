"""Préparation des données pour le LLM (`prepare_for_llm`,
`prepare_for_classement`, `classement_llm_csv`, réhydratation Ref).
"""
import pandas as pd

from core.csv_handler import (
    REQUIRED_COLUMNS,
    _ensure_path_column,
    classement_llm_csv,
    normalize_resip_export,
    prepare_for_classement,
    prepare_for_llm,
    read_csv,
)

# ── prepare_for_llm (AUD-001) ────────────────────────────────────────────────

def _df_with_extras(small_df):
    df = small_df.copy()
    df["Content.Description"] = ""
    df.loc[df["File"] == "cantine/menus_janvier.docx", "Content.Description"] = "Menus du mois"
    df["Colonne.Parasite"] = "bruit"
    return df


def test_filter_columns_keeps_required_only(small_df):
    df = _df_with_extras(small_df)
    out = prepare_for_llm(df, filter_columns=True, include_description=False)
    assert list(out.columns) == REQUIRED_COLUMNS


def test_include_description_appends_last(small_df):
    df = _df_with_extras(small_df)
    out = prepare_for_llm(df, filter_columns=True, include_description=True)
    assert list(out.columns) == REQUIRED_COLUMNS + ["Content.Description"]
    assert "Colonne.Parasite" not in out.columns


def test_no_filter_passes_everything(small_df):
    df = _df_with_extras(small_df)
    out = prepare_for_llm(df, filter_columns=False)
    assert "Colonne.Parasite" in out.columns


def test_clean_dates_blanks_items_only(small_df):
    out = prepare_for_llm(small_df, clean_dates=True)
    items = out[out["Content.DescriptionLevel"] == "Item"]
    folders = out[out["Content.DescriptionLevel"] == "RecordGrp"]
    assert (items["Content.StartDate"] == "").all()
    assert (items["Content.EndDate"] == "").all()
    # Les dossiers gardent leurs plages.
    assert (folders["Content.StartDate"] != "").any()


def test_sampling_caps_items_per_parent(small_df):
    out = prepare_for_llm(small_df, clean_dates=False, sample_items_n=1)
    items = out[out["Content.DescriptionLevel"] == "Item"]
    # 3 dossiers parents → 1 item max chacun ; les RecordGrp restent tous.
    assert len(items) == 3
    assert (out["Content.DescriptionLevel"] == "RecordGrp").sum() == 4


def test_include_items_false_drops_all_files(small_df):
    """Arborescence seule : aucun Item, tous les RecordGrp conservés."""
    out = prepare_for_llm(small_df, include_items=False)
    assert (out["Content.DescriptionLevel"] == "Item").sum() == 0
    assert (out["Content.DescriptionLevel"] == "RecordGrp").sum() == 4


def test_include_items_false_overrides_sampling(small_df):
    """`include_items=False` prime sur l'échantillonnage : aucun fichier même
    avec un `sample_items_n` élevé."""
    out = prepare_for_llm(small_df, include_items=False, sample_items_n=10)
    assert (out["Content.DescriptionLevel"] == "Item").sum() == 0


def test_original_df_untouched(small_df):
    before = small_df.copy()
    prepare_for_llm(small_df, clean_dates=True, sample_items_n=1)
    pd.testing.assert_frame_equal(small_df, before)


# ── prepare_for_classement (CLA-001) ─────────────────────────────────────────

def test_prepare_classement_refs_are_sequential(small_df):
    items = prepare_for_classement(small_df)
    assert list(items.columns) == ["Ref", "Path", "CurrentTitle", "Date"]
    assert list(items["Ref"]) == [1, 2, 3, 4, 5, 6]
    assert items.iloc[0]["Path"] == "inscriptions/liste_eleves_2022.xlsx"


def test_prepare_classement_description_toggle(small_df):
    df = small_df.copy()
    df["Content.Description"] = "desc"
    with_desc = prepare_for_classement(df, include_description=True)
    without = prepare_for_classement(df, include_description=False)
    assert "Description" in with_desc.columns
    assert "Description" not in without.columns


def test_classement_llm_csv_column_sets(small_df):
    items = prepare_for_classement(small_df)
    path_csv = classement_llm_csv(items, ref_mode=False)
    ref_csv = classement_llm_csv(items, ref_mode=True)
    assert path_csv.splitlines()[0] == "Path;CurrentTitle;Date"
    assert ref_csv.splitlines()[0] == "Ref;Path;CurrentTitle;Date"


# ── Réhydratation Ref → Path ─────────────────────────────────────────────────

def test_ensure_path_column_rehydrates(small_df):
    df_llm = pd.DataFrame(
        {"Ref": ["2", "1"], "TargetFolder": ["1_X", "1_X"], "NewTitle": ["b", "a"]}
    )
    out = _ensure_path_column(df_llm, small_df)
    assert list(out["Path"]) == [
        "inscriptions/liste eleves 2023 v2.xlsx",
        "inscriptions/liste_eleves_2022.xlsx",
    ]


def test_ensure_path_column_unresolved_ref_is_empty(small_df):
    df_llm = pd.DataFrame({"Ref": ["999"], "TargetFolder": ["1_X"], "NewTitle": ["x"]})
    out = _ensure_path_column(df_llm, small_df)
    assert out.iloc[0]["Path"] == ""


def test_ensure_path_column_noop_when_path_present(small_df):
    df_llm = pd.DataFrame({"Path": ["a.txt"], "TargetFolder": ["1_X"], "NewTitle": ["x"]})
    assert _ensure_path_column(df_llm, small_df) is df_llm


# ── normalize_resip_export (sur fixture figée) ───────────────────────────────

def test_resip_fixture_normalised_to_canonical(resip_csv_text):
    import io

    df = read_csv(io.BytesIO(resip_csv_text.encode("utf-8")))
    assert {"ID", "ParentID", "File"} <= set(df.columns)
    assert "ObjectFiles" not in df.columns
    root = df[df["ParentID"].fillna("") == ""]
    assert list(root["File"]) == ["."]
    assert list(df["ID"]) == [str(i) for i in range(1, 11)]


def test_normalize_is_noop_on_canonical(small_df):
    out = normalize_resip_export(small_df)
    pd.testing.assert_frame_equal(out, small_df)
