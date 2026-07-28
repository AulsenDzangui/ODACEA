"""Pipeline déterministe complet sur fixtures figées — sans LLM ni réseau.

Rejoue le parcours réel : CSV Archifiltre figé + réponses LLM enregistrées
(golden files) → extraction → conversion RESIP → contrôle d'intégrité. Sert de
non-régression sur le format de sortie (contrainte transverse).
"""
import io

import pandas as pd
import pytest

from core.csv_handler import (
    REQUIRED_COLUMNS,
    convert_classement_to_resip,
    csv_to_string,
    extract_csv_from_response,
    read_csv,
    validate_output_csv,
)


def _convert(golden, small_df, plan_valide, id_col):
    df_llm = extract_csv_from_response(golden, id_col=id_col)
    return convert_classement_to_resip(df_llm, small_df, plan_valide)


@pytest.mark.parametrize("mode", ["path", "ref"])
def test_golden_pipeline_full_conformity(
    mode, small_df, plan_valide, golden_cla_path, golden_cla_ref
):
    """Les deux méthodes d'identifiant produisent le même classement conforme."""
    golden = golden_cla_path if mode == "path" else golden_cla_ref
    df_resip, warnings, stats = _convert(
        golden, small_df, plan_valide, "Path" if mode == "path" else "Ref"
    )

    # Conformité au plan : tous les dossiers réalisés, aucun inventé.
    assert stats["planMatches"] is True
    assert stats["itemsMalformed"] == 0
    # 6 items classés, racine préservée, intégrité du SIP.
    assert (df_resip["Content.DescriptionLevel"] == "Item").sum() == 6
    assert (df_resip["File"] == ".").sum() == 1
    assert validate_output_csv(df_resip) == []
    assert not any("non classé" in w for w in warnings)

    # Les chemins physiques d'origine sont intacts.
    items = df_resip[df_resip["Content.DescriptionLevel"] == "Item"]
    assert set(items["File"]) == set(
        small_df[small_df["Content.DescriptionLevel"] == "Item"]["File"]
    )

    # Dates agrégées : la racine couvre les extrêmes du fonds.
    root = df_resip[df_resip["File"] == "."].iloc[0]
    assert (root["Content.StartDate"], root["Content.EndDate"]) == ("2019-01-10", "2023-09-04")
    cantine = df_resip[df_resip["File"] == "2_Cantine"].iloc[0]
    assert (cantine["Content.StartDate"], cantine["Content.EndDate"]) == ("2021-11-15", "2022-01-03")

    # Titres descriptifs portés par l'arborescence fusionnée.
    insc = df_resip[df_resip["File"] == "1_Inscriptions"].iloc[0]
    assert insc["Content.Title"] == "Inscriptions scolaires"


def test_golden_pipeline_output_format_is_resip(small_df, plan_valide, golden_cla_path):
    """Non-régression : sortie au format Archifiltre (colonnes, `;`, racine)."""
    df_resip, _, _ = _convert(golden_cla_path, small_df, plan_valide, "Path")
    assert list(df_resip.columns) == REQUIRED_COLUMNS
    text = csv_to_string(df_resip)
    assert text.splitlines()[0] == ";".join(REQUIRED_COLUMNS)
    # Re-lecture par le moteur : le CSV produit rentre tel quel dans read_csv.
    df_back = read_csv(io.BytesIO(text.encode("utf-8")))
    assert len(df_back) == len(df_resip)


def test_golden_pipeline_from_resip_native_input(resip_csv_text, plan_valide, golden_cla_path):
    """Entrée Resip native → normalisation → même résultat que l'entrée canonique."""
    df_original = read_csv(io.BytesIO(resip_csv_text.encode("utf-8")))
    df_resip, _, stats = _convert(golden_cla_path, df_original, plan_valide, "Path")
    assert stats["planMatches"] is True
    assert validate_output_csv(df_resip) == []


# ── Garde d'entrée et normalisation des cibles ───────────────────────────────

def test_convert_missing_columns_raises_explicit(small_df, plan_valide):
    df_llm = pd.DataFrame({"Quoi": ["a"], "Cible": ["b"]})
    with pytest.raises(ValueError, match="TargetFolder"):
        convert_classement_to_resip(df_llm, small_df, plan_valide)


def test_convert_full_path_target_reduced_to_leaf(small_df, plan_valide):
    """Le LLM produit parfois `Parent/Feuille` : seul le nom de feuille compte."""
    df_llm = pd.DataFrame({
        "Path": ["cantine/menus_janvier.docx"],
        "TargetFolder": ["2_Cantine/2-1_Menus"],
        "NewTitle": ["2022-01-03_menus.docx"],
    })
    df_resip, _, stats = convert_classement_to_resip(df_llm, small_df, plan_valide)
    menus = df_resip[df_resip["File"] == "2-1_Menus"]
    assert len(menus) == 1
    assert "2_Cantine/2-1_Menus" not in set(df_resip["File"])


def test_convert_extra_columns_preserved(small_df, plan_valide):
    """Les colonnes hors REQUIRED_COLUMNS du CSV source sont conservées."""
    df = small_df.copy()
    df["Content.Description"] = "desc"
    df_llm = pd.DataFrame({
        "Path": ["divers/note service.doc"],
        "TargetFolder": ["3_Vie_scolaire"],
        "NewTitle": ["2019-01-10_note.doc"],
    })
    df_resip, _, _ = convert_classement_to_resip(df_llm, df, plan_valide)
    assert "Content.Description" in df_resip.columns
    item = df_resip[df_resip["File"] == "divers/note service.doc"].iloc[0]
    assert item["Content.Description"] == "desc"
