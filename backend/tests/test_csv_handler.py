"""Tests déterministes du post-traitement RESIP (`core.csv_handler`).

Première suite de tests du moteur. On couvre ici le code *déterministe* —
testable sans LLM — autour du classement : agrégation des plages de dates des
RecordGrp (et sa robustesse sur gros volumes), invariants de la conversion
LLM → RESIP, et quelques fonctions de lecture/validation.
"""
import pandas as pd
import pytest

from core.csv_handler import (
    REQUIRED_COLUMNS,
    _ancestors_inclusive,
    convert_classement_to_resip,
    normalize_resip_export,
    parse_plan_tree,
    strip_folder_numbers,
    validate_csv,
    validate_output_csv,
)

PLAN_VALIDE = """
## Arborescence technique

```text
1_Administratif/
├── 1-1_Courriers/
└── 1-2_Factures/
2_Technique/
```

## Préconisations
RAS.
"""


def _make_original(items):
    """Construit un df_original canonique : racine `File="."` + lignes Item.

    `items` : liste de tuples (file, title, start, end).
    """
    root = {
        "ID": "1", "ParentID": "", "File": ".",
        "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Racine",
        "Content.StartDate": "", "Content.EndDate": "",
    }
    rows = [root]
    for i, (file, title, start, end) in enumerate(items, start=2):
        rows.append({
            "ID": str(i), "ParentID": "1", "File": file,
            "Content.DescriptionLevel": "Item", "Content.Title": title,
            "Content.StartDate": start, "Content.EndDate": end,
        })
    return pd.DataFrame(rows, columns=REQUIRED_COLUMNS)


def _make_llm(rows):
    """rows : liste de tuples (path, target, new_title)."""
    return pd.DataFrame(rows, columns=["Path", "TargetFolder", "NewTitle"])


# ── Agrégation des dates des RecordGrp (cœur de l'optimisation linéaire) ─────────

def test_recordgrp_dates_propagate_up_the_tree():
    df_original = _make_original([
        ("doc1.docx", "Courrier", "2020-01-01", "2020-06-01"),
        ("doc2.pdf", "Facture", "2019-01-01", "2019-12-31"),
        ("doc3.xlsx", "Plan", "2021-03-01", "2021-03-15"),
    ])
    df_llm = _make_llm([
        ("doc1.docx", "1-1_Courriers", "Courrier Dupont.docx"),
        ("doc2.pdf", "1-2_Factures", "Facture 2019.pdf"),
        ("doc3.xlsx", "2_Technique", "Plan technique.xlsx"),
    ])

    df_resip, warnings, _ = convert_classement_to_resip(df_llm, df_original, PLAN_VALIDE)
    dates = {
        r["File"]: (r["Content.StartDate"], r["Content.EndDate"])
        for _, r in df_resip.iterrows()
        if r["Content.DescriptionLevel"] == "RecordGrp"
    }

    # Feuilles : plage de leur unique item.
    assert dates["1-1_Courriers"] == ("2020-01-01", "2020-06-01")
    assert dates["1-2_Factures"] == ("2019-01-01", "2019-12-31")
    assert dates["2_Technique"] == ("2021-03-01", "2021-03-15")
    # Parent : union des plages de ses deux sous-dossiers.
    assert dates["1_Administratif"] == ("2019-01-01", "2020-06-01")


def test_recordgrp_dates_ignore_empty_values():
    df_original = _make_original([
        ("a.txt", "A", "", ""),
        ("b.txt", "B", "2022-05-01", "2022-05-02"),
    ])
    df_llm = _make_llm([
        ("a.txt", "1-1_Courriers", "A.txt"),
        ("b.txt", "1-1_Courriers", "B.txt"),
    ])
    df_resip, _, _ = convert_classement_to_resip(df_llm, df_original, PLAN_VALIDE)
    rg = df_resip[df_resip["File"] == "1-1_Courriers"].iloc[0]
    # La date vide ne tire pas la plage vers "" : seule b.txt compte.
    assert rg["Content.StartDate"] == "2022-05-01"
    assert rg["Content.EndDate"] == "2022-05-02"


def test_large_volume_dates_and_completeness():
    """Régression gros volumes : la conversion reste correcte et complète sur
    plusieurs milliers d'items répartis dans les sous-dossiers."""
    n = 3000
    items = [
        (f"doc{i}.txt", f"Doc {i}", f"20{10 + (i % 10):02d}-01-01", f"20{10 + (i % 10):02d}-12-31")
        for i in range(n)
    ]
    df_original = _make_original(items)
    targets = ["1-1_Courriers", "1-2_Factures", "2_Technique"]
    df_llm = _make_llm([
        (f"doc{i}.txt", targets[i % len(targets)], f"Doc {i}.txt")
        for i in range(n)
    ])

    df_resip, warnings, _ = convert_classement_to_resip(df_llm, df_original, PLAN_VALIDE)

    # Tous les items reclassés, aucun perdu, aucun avertissement de fichier non classé.
    assert (df_resip["Content.DescriptionLevel"] == "Item").sum() == n
    assert not any("non classé" in w for w in warnings)
    # Le parent agrège la plage complète de ses descendants.
    admin = df_resip[df_resip["File"] == "1_Administratif"].iloc[0]
    assert admin["Content.StartDate"] == "2010-01-01"
    assert admin["Content.EndDate"] == "2019-12-31"


# ── Invariants de la conversion LLM → RESIP ─────────────────────────────────────

def test_paths_preserved_and_output_valid():
    df_original = _make_original([
        ("dir/doc1.docx", "Doc1", "2020-01-01", "2020-01-02"),
        ("dir/doc2.pdf", "Doc2", "2020-02-01", "2020-02-02"),
    ])
    df_llm = _make_llm([
        ("dir/doc1.docx", "1-1_Courriers", "Renommé 1.docx"),
        ("dir/doc2.pdf", "2_Technique", "Renommé 2.pdf"),
    ])
    df_resip, _, _ = convert_classement_to_resip(df_llm, df_original, PLAN_VALIDE)

    items = df_resip[df_resip["Content.DescriptionLevel"] == "Item"]
    # Les chemins physiques d'origine sont préservés à l'identique.
    assert set(items["File"]) == {"dir/doc1.docx", "dir/doc2.pdf"}
    # Le CSV produit passe la validation renforcée (pas d'orphelin, racine présente).
    assert validate_output_csv(df_resip) == []


def test_extension_realigned_on_source():
    """Le LLM change parfois l'extension ; elle doit être réalignée sur le Path."""
    df_original = _make_original([("rapport.docx", "Rapport", "2020-01-01", "2020-01-02")])
    df_llm = _make_llm([("rapport.docx", "2_Technique", "Rapport final.pdf")])
    df_resip, warnings, _ = convert_classement_to_resip(df_llm, df_original, PLAN_VALIDE)

    item = df_resip[df_resip["Content.DescriptionLevel"] == "Item"].iloc[0]
    assert item["Content.Title"] == "Rapport final.docx"
    assert any("extension" in w for w in warnings)


# ── Conformité au plan (arborescence du classement == arborescence du plan) ─────

def test_plan_matches_when_trees_identical():
    """Tous les dossiers feuilles du plan sont réalisés et aucun n'est inventé →
    arborescence produite == arborescence validée."""
    df_original = _make_original([
        ("a.txt", "A", "2020-01-01", "2020-01-02"),
        ("b.txt", "B", "2020-01-01", "2020-01-02"),
        ("c.txt", "C", "2020-01-01", "2020-01-02"),
    ])
    df_llm = _make_llm([
        ("a.txt", "1-1_Courriers", "A.txt"),
        ("b.txt", "1-2_Factures", "B.txt"),
        ("c.txt", "2_Technique", "C.txt"),
    ])
    _, warnings, stats = convert_classement_to_resip(df_llm, df_original, PLAN_VALIDE)
    assert stats["planMatches"] is True
    assert stats["foldersOffPlan"] == []
    assert stats["foldersMissing"] == []
    assert not any("hors plan" in w or "non réalisé" in w for w in warnings)


def test_plan_detects_invented_folder():
    """Un dossier inventé par le classement (absent du plan) est signalé. Sans le
    test contre `folder_tree`, l'ancien `target in folder_ids` l'acceptait
    silencieusement (circulaire)."""
    df_original = _make_original([
        ("a.txt", "A", "2020-01-01", "2020-01-02"),
        ("b.txt", "B", "2020-01-01", "2020-01-02"),
        ("c.txt", "C", "2020-01-01", "2020-01-02"),
        ("d.txt", "D", "2020-01-01", "2020-01-02"),
    ])
    df_llm = _make_llm([
        ("a.txt", "1-1_Courriers", "A.txt"),
        ("b.txt", "1-2_Factures", "B.txt"),
        ("c.txt", "2_Technique", "C.txt"),
        ("d.txt", "9_Invente", "D.txt"),  # absent du plan
    ])
    df_resip, warnings, stats = convert_classement_to_resip(df_llm, df_original, PLAN_VALIDE)
    assert stats["foldersOffPlan"] == ["9_Invente"]
    assert stats["foldersMissing"] == []
    assert stats["planMatches"] is False
    assert any("hors plan" in w and "9_Invente" in w for w in warnings)
    # Le fichier n'est pas perdu : le dossier inventé est tout de même créé.
    assert "d.txt" in set(df_resip["File"])


def test_plan_detects_missing_folder():
    """Un dossier du plan où rien n'est classé doit alerter l'archiviste."""
    df_original = _make_original([
        ("a.txt", "A", "2020-01-01", "2020-01-02"),
        ("c.txt", "C", "2020-01-01", "2020-01-02"),
    ])
    df_llm = _make_llm([
        ("a.txt", "1-1_Courriers", "A.txt"),
        ("c.txt", "2_Technique", "C.txt"),
        # 1-2_Factures n'est jamais utilisé → manquant
    ])
    _, warnings, stats = convert_classement_to_resip(df_llm, df_original, PLAN_VALIDE)
    assert stats["foldersMissing"] == ["1-2_Factures"]
    assert stats["foldersOffPlan"] == []
    assert stats["planMatches"] is False
    assert any("non réalisé" in w and "1-2_Factures" in w for w in warnings)


def test_malformed_target_routed_to_root_not_a_folder():
    """Le LLM met un nom de fichier dans TargetFolder : pas de dossier-poubelle,
    l'item est rattaché à la racine et compté `itemsMalformed`."""
    df_original = _make_original([
        ("a.txt", "A", "2020-01-01", "2020-01-02"),
        ("kermesse_2022_002.jpg", "K", "2022-06-25", "2022-06-25"),
    ])
    df_llm = _make_llm([
        ("a.txt", "1-1_Courriers", "A.txt"),
        # cible = le nom du fichier lui-même (sortie malformée)
        ("kermesse_2022_002.jpg", "kermesse_2022_002.jpg", "2022-06-25.jpg"),
    ])
    df_resip, warnings, stats = convert_classement_to_resip(df_llm, df_original, PLAN_VALIDE)
    # Aucun dossier nommé d'après le fichier n'est créé.
    rg_files = set(df_resip[df_resip["Content.DescriptionLevel"] == "RecordGrp"]["File"])
    assert "kermesse_2022_002.jpg" not in rg_files
    assert stats["itemsMalformed"] == 1
    assert "kermesse_2022_002.jpg" not in stats["foldersOffPlan"]
    # L'item n'est pas perdu : rattaché à la racine.
    item = df_resip[df_resip["File"] == "kermesse_2022_002.jpg"].iloc[0]
    assert item["Content.DescriptionLevel"] == "Item"
    root_id = df_resip[df_resip["File"] == "."].iloc[0]["ID"]
    assert item["ParentID"] == root_id
    assert any("malformée" in w for w in warnings)


def test_off_plan_folder_without_extension_still_created():
    """Un vrai dossier hors plan (sans extension) reste créé et compté en écart —
    le garde-fou ne vise que les cibles en forme de fichier."""
    df_original = _make_original([("a.txt", "A", "2020-01-01", "2020-01-02")])
    df_llm = _make_llm([("a.txt", "9_Invente", "A.txt")])
    df_resip, _, stats = convert_classement_to_resip(df_llm, df_original, PLAN_VALIDE)
    assert "9_Invente" in set(df_resip["File"])
    assert stats["foldersOffPlan"] == ["9_Invente"]
    assert stats["itemsMalformed"] == 0


def test_plan_not_parsed_is_not_a_match():
    """Plan sans bloc d'arborescence → mesure impossible : planParsed False,
    jamais déclaré conforme."""
    df_original = _make_original([("a.txt", "A", "2020-01-01", "2020-01-02")])
    df_llm = _make_llm([("a.txt", "Dossier_libre", "A.txt")])
    _, _, stats = convert_classement_to_resip(df_llm, df_original, "## Préconisations\nRAS.")
    assert stats["planParsed"] is False
    assert stats["planMatches"] is False


# ── Option d'export : retrait des numéros de position (strip_folder_numbers) ─────

def test_strip_folder_numbers_rewrites_only_recordgrp_file():
    """Retire le préfixe des noms de dossier (File des RecordGrp) sans toucher ni
    la racine, ni le chemin source des Items, ni les titres descriptifs."""
    df_original = _make_original([
        ("doc1.docx", "Courrier", "2020-01-01", "2020-06-01"),
        ("doc2.pdf", "Facture", "2019-01-01", "2019-12-31"),
    ])
    df_llm = _make_llm([
        ("doc1.docx", "1-1_Courriers", "Courrier.docx"),
        ("doc2.pdf", "1-2_Factures", "Facture.pdf"),
    ])
    df_resip, _, _ = convert_classement_to_resip(df_llm, df_original, PLAN_VALIDE)
    stripped, renamed = strip_folder_numbers(df_resip)

    assert renamed == []
    files = {
        r["File"] for _, r in stripped.iterrows()
        if r["Content.DescriptionLevel"] == "RecordGrp"
    }
    # Numéros retirés partout, y compris les dossiers intermédiaires.
    assert files == {".", "Administratif", "Courriers", "Factures"}
    # Chemins source des Items (clé de jointure/copie) intacts.
    item_files = {
        r["File"] for _, r in stripped.iterrows()
        if r["Content.DescriptionLevel"] == "Item"
    }
    assert item_files == {"doc1.docx", "doc2.pdf"}
    # Structure préservée : ParentID inchangés (mêmes IDs qu'avant).
    assert list(stripped["ParentID"]) == list(df_resip["ParentID"])
    # L'original n'est pas muté.
    assert "1-1_Courriers" in set(df_resip["File"])


def test_strip_folder_numbers_dedup_sibling_collision():
    """Deux frères qui deviennent homonymes après retrait sont dédoublonnés et
    signalés — la copie physique reste matérialisable."""
    plan = """
## Arborescence technique

```text
1_Racine/
├── 1-1_Rapports/
└── 1-2_Rapports/
```
"""
    df_original = _make_original([
        ("a.txt", "A", "2020-01-01", "2020-01-02"),
        ("b.txt", "B", "2021-01-01", "2021-01-02"),
    ])
    df_llm = _make_llm([
        ("a.txt", "1-1_Rapports", "A.txt"),
        ("b.txt", "1-2_Rapports", "B.txt"),
    ])
    df_resip, _, _ = convert_classement_to_resip(df_llm, df_original, plan)
    stripped, renamed = strip_folder_numbers(df_resip)

    rg_files = [
        r["File"] for _, r in stripped.iterrows()
        if r["Content.DescriptionLevel"] == "RecordGrp" and r["File"] != "."
    ]
    assert sorted(rg_files) == ["Racine", "Rapports", "Rapports_2"]
    assert len(renamed) == 1 and "Rapports_2" in renamed[0]


def test_strip_folder_numbers_noop_without_prefix():
    """Un nom déjà sans numéro est laissé tel quel (idempotent)."""
    df_original = _make_original([("a.txt", "A", "2020-01-01", "2020-01-02")])
    df_llm = _make_llm([("a.txt", "1-1_Courriers", "A.txt")])
    df_resip, _, _ = convert_classement_to_resip(df_llm, df_original, PLAN_VALIDE)
    once, _ = strip_folder_numbers(df_resip)
    twice, renamed = strip_folder_numbers(once)
    assert renamed == []
    assert list(once["File"]) == list(twice["File"])


# ── Parsing du plan (tolérance à l'absence d'en-tête) ───────────────────────────

def test_parse_plan_tree_with_header():
    tree = parse_plan_tree(PLAN_VALIDE)
    assert tree == {
        "1_Administratif": None,
        "1-1_Courriers": "1_Administratif",
        "1-2_Factures": "1_Administratif",
        "2_Technique": None,
    }


def test_parse_plan_tree_without_header():
    """Repli : un arbre produit sans le titre « Arborescence technique » (petit
    modèle ou plan collé à la main) reste parsé — pas d'édition manuelle forcée."""
    plan = """Mairie — Affaires scolaires → MAIRIE_AFFAIRES/
├── 1. Inscriptions → 1_Inscriptions/
│   └── Inscriptions 2023 → 1-1_Inscriptions_2023/
└── 2. Périscolaire → 2_Periscolaire/
"""
    tree = parse_plan_tree(plan)
    assert tree == {
        "MAIRIE_AFFAIRES": None,
        "1_Inscriptions": "MAIRIE_AFFAIRES",
        "1-1_Inscriptions_2023": "1_Inscriptions",
        "2_Periscolaire": "MAIRIE_AFFAIRES",
    }


def test_parse_plan_tree_empty_on_prose_only():
    """Sans en-tête ET sans ligne de dossier (texte de prose) → dict vide :
    le repli n'invente rien, planParsed reste False en aval."""
    assert parse_plan_tree("## Préconisations\nRien à signaler.") == {}


# ── Helper d'ascendance (parcours + garde anti-cycle) ───────────────────────────

def test_ancestors_inclusive_chain():
    tree = {"1-1_a": "1_root", "1_root": None}
    assert _ancestors_inclusive("1-1_a", tree) == ["1-1_a", "1_root"]
    assert _ancestors_inclusive("1_root", tree) == ["1_root"]


def test_ancestors_inclusive_cycle_guard():
    # folder_tree malformé avec cycle a→b→a : la remontée doit s'arrêter.
    tree = {"a": "b", "b": "a"}
    result = _ancestors_inclusive("a", tree)
    assert result == ["a", "b"]


def test_ancestors_inclusive_uses_cache():
    tree = {"x": None}
    cache = {}
    first = _ancestors_inclusive("x", tree, cache)
    assert cache["x"] is first
    assert _ancestors_inclusive("x", tree, cache) is first


# ── Lecture / validation ────────────────────────────────────────────────────────

def test_normalize_resip_native_export():
    """Export Resip natif (Id/ParentId, ObjectFiles, IDs textuels) → canonique."""
    df = pd.DataFrame({
        "Id": ["Import-1", "Import-2"],
        "ParentId": ["", "Import-1"],
        "ObjectFiles": ["", "dossier/fichier.docx"],
        "Content.DescriptionLevel": ["RecordGrp", "Item"],
    })
    out = normalize_resip_export(df)
    assert list(out["ID"]) == ["1", "2"]
    assert list(out["ParentID"]) == ["", "1"]
    assert out.loc[0, "File"] == "."          # racine sans parent marquée "."
    assert out.loc[1, "File"] == "dossier/fichier.docx"
    assert "ObjectFiles" not in out.columns


def test_normalize_resip_windows_path_separators():
    """RESIP sous Windows exporte les chemins avec « \\ » : normalisés en « / »
    (forme canonique Archifiltre — profondeur du digest, stats par dossier et
    outils vrac supposent « / »). No-op sur un CSV déjà canonique."""
    df = pd.DataFrame({
        "ID": ["1", "2", "3"],
        "ParentID": ["", "1", "1"],
        "File": [".", "RESTAURATION\\Factures\\facture 2022.xlsx", "deja/canonique.pdf"],
        "Content.DescriptionLevel": ["RecordGrp", "Item", "Item"],
    })
    out = normalize_resip_export(df)
    assert out.loc[1, "File"] == "RESTAURATION/Factures/facture 2022.xlsx"
    assert out.loc[2, "File"] == "deja/canonique.pdf"


def test_validate_csv_detects_problems():
    df = pd.DataFrame({
        "ID": ["1", "1"],  # doublon
        "ParentID": ["", "1"],
        "File": [".", "a"],
        "Content.DescriptionLevel": ["RecordGrp", "Niveau bidon"],  # invalide
        "Content.Title": ["R", "A"],
        "Content.StartDate": ["", ""],
        "Content.EndDate": ["", ""],
    })
    errors = validate_csv(df)
    assert any("dupliqué" in e for e in errors)
    assert any("DescriptionLevel" in e for e in errors)


def test_validate_csv_clean():
    df = _make_original([("a.txt", "A", "2020-01-01", "2020-01-02")])
    assert validate_csv(df) == []


# ── Validation renforcée du CSV de sortie (cycles, inversions de dates) ──────────

def test_validate_output_detects_date_inversion():
    """Une ligne dont la date de début est postérieure à la date de fin est signalée."""
    df = _make_original([
        ("ok.txt", "OK", "2020-01-01", "2020-12-31"),
        ("ko.txt", "KO", "2021-06-01", "2020-01-01"),  # début > fin
    ])
    errors = validate_output_csv(df)
    assert any("date de début postérieure" in e for e in errors)


def test_validate_output_ignores_partial_dates():
    """Une borne vide n'est jamais une inversion (item sans date de fin connue)."""
    df = _make_original([("a.txt", "A", "2020-01-01", "")])
    assert validate_output_csv(df) == []


def test_validate_output_detects_parent_cycle():
    """Un cycle de parenté (a→b→a) rend l'arbre SEDA invalide et doit être détecté."""
    df = pd.DataFrame([
        {"ID": "1", "ParentID": "2", "File": "a",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "A",
         "Content.StartDate": "", "Content.EndDate": ""},
        {"ID": "2", "ParentID": "1", "File": "b",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "B",
         "Content.StartDate": "", "Content.EndDate": ""},
    ], columns=REQUIRED_COLUMNS)
    errors = validate_output_csv(df)
    assert any("Cycle de parenté" in e for e in errors)


def test_validate_output_no_cycle_on_long_chain():
    """Une chaîne linéaire profonde n'est pas un cycle (et reste linéaire à valider)."""
    n = 2000
    rows = [{
        "ID": "1", "ParentID": "", "File": ".",
        "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Racine",
        "Content.StartDate": "", "Content.EndDate": "",
    }]
    for i in range(2, n + 1):
        rows.append({
            "ID": str(i), "ParentID": str(i - 1), "File": f"d{i}",
            "Content.DescriptionLevel": "RecordGrp", "Content.Title": f"D{i}",
            "Content.StartDate": "", "Content.EndDate": "",
        })
    df = pd.DataFrame(rows, columns=REQUIRED_COLUMNS)
    assert not any("Cycle" in e for e in validate_output_csv(df))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
