"""Parsing des réponses LLM (`extract_plans`, `extract_csv_from_response`).

Tout est déterministe : on rejoue des réponses figées (golden files B5) et des
variantes dégradées observées en production (en-tête manquant, séparateur
virgule, lignes irrégulières, marqueurs de livraison).
"""
import pytest

from core.csv_handler import (
    extract_csv_from_response,
    extract_plans,
    parse_plan_titles,
    parse_plan_tree,
)

# ── extract_plans (AUD-001) ──────────────────────────────────────────────────

def test_extract_plans_golden_sections(golden_aud):
    sections = extract_plans(golden_aud)
    # Le bloc balisé PLAN_STRUCTURE est préféré à la section complète.
    assert "Arborescence technique" in sections["plan"]
    assert "AFFAIRES_SCOLAIRES/" in sections["plan"]
    assert "Approche retenue" not in sections["plan"]  # hors balises
    # Les notes s'arrêtent avant le marqueur de fin.
    assert "liste d'élèves 2023" in sections["notes"]
    assert "FIN DU RAPPORT" not in sections["notes"]


def test_extract_plans_header_variants():
    """Les amorces alternatives (« PLAN DE CLASSEMENT », « RECOMMANDATION »)
    sont reconnues, et le titre n'est pas capturé dans le contenu."""
    response = (
        "## ÉTAT DES LIEUX\nprose\n"
        "## PLAN DE CLASSEMENT PROPOSÉ\ncontenu plan\n"
        "## RECOMMANDATIONS\ncontenu notes\n"
    )
    sections = extract_plans(response)
    assert sections["plan"] == "contenu plan"
    assert sections["notes"] == "contenu notes"


def test_extract_plans_without_structure_block():
    """Sans balises PLAN_STRUCTURE, repli sur la section complète."""
    response = "## PARTIE 2 — PLAN\narbre brut\n## PARTIE 3 — NOTES\nnotes\n"
    assert extract_plans(response)["plan"] == "arbre brut"


def test_extract_plans_missing_sections_empty():
    sections = extract_plans("réponse sans aucune section reconnaissable")
    assert sections == {"plan": "", "notes": ""}


# ── Arbre et titres du plan golden ───────────────────────────────────────────

def test_golden_plan_tree_and_titles(plan_valide):
    tree = parse_plan_tree(plan_valide)
    # La racine non-numérique reparent les dossiers de premier niveau.
    assert tree == {
        "AFFAIRES_SCOLAIRES": None,
        "1_Inscriptions": "AFFAIRES_SCOLAIRES",
        "2_Cantine": "AFFAIRES_SCOLAIRES",
        "2-1_Menus": "2_Cantine",
        "2-2_Factures": "2_Cantine",
        "3_Vie_scolaire": "AFFAIRES_SCOLAIRES",
    }
    titles = parse_plan_titles(plan_valide)
    assert titles["1_Inscriptions"] == "Inscriptions scolaires"
    assert titles["2-1_Menus"] == "Menus"


# ── extract_csv_from_response (CLA-001) ──────────────────────────────────────

def test_extract_csv_golden_path(golden_cla_path):
    df = extract_csv_from_response(golden_cla_path, id_col="Path")
    assert list(df.columns) == ["Path", "TargetFolder", "NewTitle"]
    assert len(df) == 6  # le marqueur [FIN DE LA PARTIE 1/1] est retiré
    assert "inscriptions/liste_eleves_2022.xlsx" in set(df["Path"])


def test_extract_csv_golden_ref(golden_cla_ref):
    df = extract_csv_from_response(golden_cla_ref, id_col="Ref")
    assert list(df.columns) == ["Ref", "TargetFolder", "NewTitle"]
    assert list(df["Ref"]) == ["1", "2", "3", "4", "5", "6"]


def test_extract_csv_takes_last_fence():
    """Plusieurs blocs ```csv``` : seul le dernier (résultat final) compte."""
    response = (
        "Phase 1 :\n```csv\nPath;TargetFolder;NewTitle\nbrouillon.txt;1_X;b.txt\n```\n"
        "Final :\n```csv\nPath;TargetFolder;NewTitle\na.txt;1_Final;a.txt\n```\n"
    )
    df = extract_csv_from_response(response)
    assert list(df["TargetFolder"]) == ["1_Final"]


def test_extract_csv_without_fence_raw_fallback():
    response = "Path;TargetFolder;NewTitle\na.txt;1_X;a.txt\n"
    df = extract_csv_from_response(response)
    assert len(df) == 1


def test_extract_csv_header_injected_when_missing():
    """Certains modèles omettent l'en-tête : il est réinjecté (mode Path et Ref)."""
    df = extract_csv_from_response("```csv\na.txt;1_X;a-nouveau.txt\n```")
    assert list(df.columns) == ["Path", "TargetFolder", "NewTitle"]
    df_ref = extract_csv_from_response("```csv\n1;1_X;a-nouveau.txt\n```", id_col="Ref")
    assert list(df_ref.columns) == ["Ref", "TargetFolder", "NewTitle"]
    assert list(df_ref["Ref"]) == ["1"]


def test_extract_csv_comma_separator_autodetected():
    """Modèles de raisonnement : séparateur `,` malgré la consigne `;`."""
    response = "```csv\nPath,TargetFolder,NewTitle\na.txt,1_X,a.txt\nb.txt,2_Y,b.txt\n```"
    df = extract_csv_from_response(response)
    assert list(df.columns) == ["Path", "TargetFolder", "NewTitle"]
    assert len(df) == 2


def test_extract_csv_salvages_irregular_rows():
    """Une ligne à 4 champs (« ; » parasite) ne fait pas perdre la réponse :
    parse tolérant ramené à 3 colonnes."""
    response = (
        "```csv\nPath;TargetFolder;NewTitle\n"
        "b.txt;2_Y;b.txt\n"
        "a.txt;1_X;titre; parasite\n```"
    )
    df = extract_csv_from_response(response)
    assert len(df) == 2
    assert list(df.columns) == ["Path", "TargetFolder", "NewTitle"]
    assert df.iloc[1]["NewTitle"] == "titre"


def test_extract_csv_strips_index_and_marker_rows():
    """Colonnes d'index parasites suppr. + lignes marqueurs [FIN…] retirées."""
    response = (
        "```csv\n;Path;TargetFolder;NewTitle\n"
        "0;a.txt;1_X;a.txt\n"
        "1;[FIN DE LA PARTIE 2/3];;\n```"
    )
    df = extract_csv_from_response(response)
    assert list(df.columns) == ["Path", "TargetFolder", "NewTitle"]
    assert list(df["Path"]) == ["a.txt"]


def test_extract_csv_empty_response_raises():
    import csv

    import pandas as pd

    # Sniffer (csv.Error) ou pandas (EmptyDataError) selon le chemin : dans les
    # deux cas une réponse vide doit lever, jamais renvoyer un df silencieux.
    with pytest.raises((pd.errors.EmptyDataError, csv.Error)):
        extract_csv_from_response("")


def test_extract_csv_bom_and_quotes():
    response = '﻿"Path";"TargetFolder";"NewTitle"\n"a.txt";"1_X";"a.txt"\n'
    df = extract_csv_from_response(response)
    assert list(df.columns) == ["Path", "TargetFolder", "NewTitle"]
    assert df.iloc[0]["Path"] == "a.txt"
