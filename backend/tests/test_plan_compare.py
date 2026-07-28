"""Tests de la comparaison structurelle de plans (audit comparatif multi-plans).

Déterministe, sans LLM : `compare_plan_variants` rapproche les variantes de plan
par libellé sémantique de dossier (préfixe numérique ignoré).
"""
from __future__ import annotations

from core.plan_compare import (
    compare_plan_variants,
    format_comparison_table,
    semantic_label,
)


def _plan(*folders: str) -> str:
    body = "\n".join(f"{f}/" for f in folders)
    return f"Arborescence technique\n{body}\n"


def test_semantic_label_strips_prefix_and_folds_case():
    assert semantic_label("1-1_Marchés_Publics") == "marchés publics"
    assert semantic_label("2_Cantine") == "cantine"
    # Deux variantes numérotant différemment le même dossier → même libellé.
    assert semantic_label("3-2_Vie_scolaire") == semantic_label("1_Vie_scolaire")


def test_compare_identical_plans_flagged_identical():
    plan = _plan("1_Inscriptions", "2_Cantine", "2-1_Menus")
    result = compare_plan_variants([plan, plan])
    comp = result["comparison"]
    assert comp["variantCount"] == 2
    assert comp["identical"] is True
    assert comp["commonFolderCount"] == 3
    # Aucun dossier propre à une seule variante.
    assert all(v["uniqueFolders"] == [] for v in result["variants"])


def test_compare_divergent_plans_reports_common_and_unique():
    a = _plan("1_Inscriptions", "2_Cantine", "2-1_Menus")
    # Variante b : numérotation différente du dossier commun + un dossier propre.
    b = _plan("1_Cantine", "1-1_Menus", "2_Vie_scolaire")
    result = compare_plan_variants([a, b])
    comp = result["comparison"]
    assert comp["identical"] is False
    assert "cantine" in comp["commonFolders"] and "menus" in comp["commonFolders"]
    assert "inscriptions" in comp["allFolders"]

    v1, v2 = result["variants"]
    assert v1["uniqueFolders"] == ["inscriptions"]
    assert v2["uniqueFolders"] == ["vie scolaire"]


def test_compare_ranges_and_structure():
    a = _plan("1_A", "2_B")               # 2 dossiers, profondeur 1
    b = _plan("1_A", "1-1_B", "1-2_C")    # 3 dossiers, profondeur 2
    result = compare_plan_variants([a, b])
    comp = result["comparison"]
    assert comp["folderCountRange"] == {"min": 2, "max": 3}
    assert comp["depthRange"]["max"] == 2
    assert result["variants"][0]["folders"] == 2
    assert result["variants"][1]["depth"] == 2


def test_compare_handles_empty_plan_variant():
    a = _plan("1_Inscriptions", "2_Cantine")
    empty = "aucun plan exploitable ici"
    result = compare_plan_variants([a, empty])
    comp = result["comparison"]
    # Une variante sans arbre extrait : commun = dossiers de la seule non vide.
    assert comp["commonFolderCount"] == 2
    v_empty = result["variants"][1]
    assert v_empty["planExtracted"] is False
    assert v_empty["folders"] == 0


def test_format_comparison_table_renders_rows():
    a = _plan("1_Inscriptions", "2_Cantine")
    b = _plan("1_Inscriptions", "2_Cantine", "3_Vie_scolaire")
    text = format_comparison_table(compare_plan_variants([a, b]))
    assert "Variante" in text and "Dossiers" in text
    assert "#1" in text and "#2" in text
    assert "Variantes structurellement identiques : non" in text
