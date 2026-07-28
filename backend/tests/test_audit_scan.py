"""Tests déterministes du scan de métadonnées (`core.audit_scan`).

Le scan est calculé sans LLM, à partir des seules métadonnées — il est donc
entièrement vérifiable ici. On couvre la volumétrie, le recensement des formats
(dont formats à risque et compressés), le repérage mécanique du bruit numérique
(noms système, verrous bureautiques, extensions temporaires), plus la robustesse
sur gros volume et le formatage du digest. Les analyses sémantiques (doublons,
nommage) restent laissées au modèle et ne sont donc pas calculées par le scan.
"""
import pandas as pd

from core.audit_scan import format_digest, scan_metadata
from core.csv_handler import REQUIRED_COLUMNS
from core.enrich import FINGERPRINT_COLUMN


def _df(rows):
    """rows : liste de dicts partiels ; complète les colonnes requises manquantes."""
    full = []
    for r in rows:
        base = {c: "" for c in REQUIRED_COLUMNS}
        base.update(r)
        full.append(base)
    return pd.DataFrame(full, columns=REQUIRED_COLUMNS)


def _item(id_, file, title, level="Item"):
    return {"ID": id_, "ParentID": "1", "File": file,
            "Content.DescriptionLevel": level, "Content.Title": title}


# ── Volumétrie ──────────────────────────────────────────────────────────────

def test_volumetry_counts_and_depth():
    df = _df([
        {"ID": "1", "ParentID": "", "File": ".", "Content.DescriptionLevel": "RecordGrp",
         "Content.Title": "Fonds"},
        {"ID": "2", "ParentID": "1", "File": "Dossier", "Content.DescriptionLevel": "RecordGrp",
         "Content.Title": "Dossier"},
        _item("3", "Dossier/sous/a.docx", "a.docx"),
        _item("4", "Dossier/b.pdf", "b.pdf"),
    ])
    v = scan_metadata(df)["volumetry"]
    assert v["items"] == 2
    assert v["recordGrps"] == 2
    assert v["rows"] == 4
    # Dossier/sous/a.docx → 3 composants ; la racine "." ne compte pas.
    assert v["maxDepth"] == 3


# ── Formats ─────────────────────────────────────────────────────────────────

def test_formats_top_risky_and_compressed():
    df = _df([
        _item("2", "x/a.doc", "a.doc"),
        _item("3", "x/b.doc", "b.doc"),
        _item("4", "x/c.xls", "c.xls"),
        _item("5", "x/d.pdf", "d.pdf"),
        _item("6", "x/archive.zip", "archive.zip"),
        _item("7", "x/sansext", "sansext"),
    ])
    scan = scan_metadata(df)
    top = dict(scan["formats"]["top"])
    assert top["doc"] == 2
    assert top["(sans extension)"] == 1
    assert scan["formats"]["distinct"] == 5  # doc, xls, pdf, zip, ""
    assert dict(scan["riskyFormats"]) == {"doc": 2, "xls": 1}
    assert dict(scan["compressedFormats"]) == {"zip": 1}


# ── Bruit numérique (repérage mécanique) ────────────────────────────────────

def test_noise_detection_counts_by_kind():
    df = _df([
        _item("2", "x/Thumbs.db", "Thumbs.db"),
        _item("3", "y/.DS_Store", ".DS_Store"),       # casse + nom système
        _item("4", "z/~$rapport.docx", "~$rapport.docx"),  # verrou Office
        _item("5", "z/brouillon.tmp", "brouillon.tmp"),    # temporaire
        _item("6", "z/page.crdownload", "page.crdownload"),
        _item("7", "z/vrai-document.pdf", "vrai-document.pdf"),  # NON bruit
    ])
    noise = scan_metadata(df)["noise"]
    assert noise["total"] == 5
    by_kind = dict(noise["byKind"])
    assert by_kind["fichier système"] == 2
    assert by_kind["verrou bureautique"] == 1
    assert by_kind["fichier temporaire"] == 2
    # Le vrai document n'apparaît pas dans les exemples.
    assert "vrai-document.pdf" not in noise["examples"]


def test_noise_ignores_legitimate_dotfiles_and_recordgrps():
    df = _df([
        # Un RecordGrp nommé comme du bruit ne doit PAS être compté (Item only).
        {"ID": "2", "ParentID": "1", "File": "Thumbs.db",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Thumbs.db"},
        # Un fichier caché légitime n'est pas du bruit.
        _item("3", "x/.gitignore", ".gitignore"),
        _item("4", "x/rapport.pdf", "rapport.pdf"),
    ])
    noise = scan_metadata(df)["noise"]
    assert noise["total"] == 0
    assert noise["byKind"] == []


def test_no_noise_is_safe():
    df = _df([_item("2", "x/a.pdf", "a.pdf")])
    noise = scan_metadata(df)["noise"]
    assert noise == {"total": 0, "byKind": [], "examples": []}


# ── Dossiers vides (repérage mécanique sur l'arbre ID/ParentID) ─────────────

def test_empty_folders_detected_and_nonempty_ignored():
    df = _df([
        {"ID": "1", "ParentID": "", "File": ".",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Fonds"},
        # Dossier plein (contient un Item directement).
        {"ID": "2", "ParentID": "1", "File": "Plein",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Dossier plein"},
        {"ID": "3", "ParentID": "2", "File": "Plein/a.pdf",
         "Content.DescriptionLevel": "Item", "Content.Title": "a.pdf"},
        # Dossier vide (aucun Item dans son arborescence).
        {"ID": "4", "ParentID": "1", "File": "Vide",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Dossier vide"},
        # Sous-dossier vide d'un dossier lui-même vide → les deux comptent.
        {"ID": "5", "ParentID": "4", "File": "Vide/SousVide",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Sous-dossier vide"},
    ])
    empty = scan_metadata(df)["emptyFolders"]
    assert empty["total"] == 2
    assert "Dossier vide" in empty["examples"]
    assert "Sous-dossier vide" in empty["examples"]
    # La racine et le dossier plein ne sont jamais comptés.
    assert "Fonds" not in empty["examples"]
    assert "Dossier plein" not in empty["examples"]


def test_empty_folders_indirect_item_makes_branch_nonempty():
    # Un Item profond rend « non vides » tous ses dossiers ascendants.
    df = _df([
        {"ID": "1", "ParentID": "", "File": ".",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Fonds"},
        {"ID": "2", "ParentID": "1", "File": "A",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "A"},
        {"ID": "3", "ParentID": "2", "File": "A/B",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "B"},
        {"ID": "4", "ParentID": "3", "File": "A/B/doc.pdf",
         "Content.DescriptionLevel": "Item", "Content.Title": "doc.pdf"},
    ])
    assert scan_metadata(df)["emptyFolders"]["total"] == 0


def test_empty_folders_safe_without_columns():
    # Sans ID/ParentID, le repérage retourne un total nul (pas d'erreur).
    df = pd.DataFrame([{"File": "x/a.pdf", "Content.DescriptionLevel": "Item"}])
    assert scan_metadata(df)["emptyFolders"] == {"total": 0, "examples": []}


# ── Noms de fichiers répétés (repérage mécanique sur le nom de base) ─────────

def test_name_collisions_detected_case_insensitive():
    df = _df([
        # Même nom dans trois dossiers (casse mêlée) → un seul nom, 3 fichiers.
        _item("2", "a/Compte rendu.docx", "Compte rendu.docx"),
        _item("3", "b/compte rendu.docx", "compte rendu.docx"),
        _item("4", "c/COMPTE RENDU.docx", "COMPTE RENDU.docx"),
        # Nom unique → ignoré.
        _item("5", "a/budget.xlsx", "budget.xlsx"),
        # Bruit numérique : exclu même répété.
        _item("6", "a/Thumbs.db", "Thumbs.db"),
        _item("7", "b/Thumbs.db", "Thumbs.db"),
    ])
    coll = scan_metadata(df)["nameCollisions"]
    assert coll["total"] == 1          # un seul nom collisionne
    assert coll["files"] == 3          # porté par trois fichiers
    name, n = coll["examples"][0]
    assert n == 3
    assert name.lower() == "compte rendu.docx"


def test_name_collisions_sorted_by_count():
    df = _df([
        _item("2", "x/a.pdf", "a.pdf"),
        _item("3", "y/a.pdf", "a.pdf"),
        _item("4", "x/b.pdf", "b.pdf"),
        _item("5", "y/b.pdf", "b.pdf"),
        _item("6", "z/b.pdf", "b.pdf"),
    ])
    coll = scan_metadata(df)["nameCollisions"]
    assert coll["total"] == 2
    # b.pdf (3) avant a.pdf (2).
    assert coll["examples"][0] == ("b.pdf", 3)
    assert coll["examples"][1] == ("a.pdf", 2)


def test_name_collisions_none_when_unique():
    df = _df([
        _item("2", "x/a.pdf", "a.pdf"),
        _item("3", "x/b.pdf", "b.pdf"),
    ])
    coll = scan_metadata(df)["nameCollisions"]
    assert coll == {"total": 0, "files": 0, "examples": []}


def test_digest_reports_name_collisions():
    df = _df([
        _item("2", "a/rapport.docx", "rapport.docx"),
        _item("3", "b/rapport.docx", "rapport.docx"),
    ])
    digest = format_digest(scan_metadata(df))
    assert "Noms de fichiers répétés" in digest
    assert "rapport.docx (×2)" in digest


# ── Doublons stricts par empreinte SHA-256 ───────────────────────────────────

def _df_fp(rows):
    """Comme _df mais conserve une colonne d'empreinte (hors RESIP requis)."""
    cols = [*REQUIRED_COLUMNS, FINGERPRINT_COLUMN]
    full = []
    for r in rows:
        base = {c: "" for c in cols}
        base.update(r)
        full.append(base)
    return pd.DataFrame(full, columns=cols)


def _fp_item(id_, file, fp, title="x.pdf"):
    return {**_item(id_, file, title), FINGERPRINT_COLUMN: fp}


def test_strict_duplicates_inactive_without_fingerprint_column():
    df = _df([_item("2", "a/x.pdf", "x.pdf"), _item("3", "b/x.pdf", "x.pdf")])
    dups = scan_metadata(df)["strictDuplicates"]
    assert dups["available"] is False
    # Et le digest n'en parle pas du tout (pas de bruit quand l'empreinte manque).
    assert "Doublons stricts" not in format_digest(scan_metadata(df))


def test_strict_duplicates_groups_identical_hashes():
    df = _df_fp([
        _fp_item("2", "a/rapport.pdf", "aaa"),
        _fp_item("3", "b/rapport.pdf", "AAA"),   # casse ignorée
        _fp_item("4", "c/autre.docx", "bbb"),    # unique
    ])
    dups = scan_metadata(df)["strictDuplicates"]
    assert dups["available"] is True
    assert dups["total"] == 1           # un seul groupe de doublons
    assert dups["files"] == 2           # deux fichiers concernés
    assert dups["redundant"] == 1       # une redondance supprimable
    assert dups["examples"][0]["count"] == 2


def test_strict_duplicates_ignores_recordgrp_and_empty_hash():
    df = _df_fp([
        _fp_item("2", "a/x.pdf", "h1"),
        _fp_item("3", "b/x.pdf", ""),            # non haché → ignoré
        {"ID": "1", "ParentID": "", "File": ".",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "racine",
         FINGERPRINT_COLUMN: "h1"},              # RecordGrp → ignoré même si hash
    ])
    dups = scan_metadata(df)["strictDuplicates"]
    # Un seul Item haché → pas de groupe.
    assert dups["total"] == 0
    assert dups["available"] is True


def test_digest_reports_strict_duplicates():
    df = _df_fp([
        _fp_item("2", "a/rapport.pdf", "abc123def456"),
        _fp_item("3", "b/rapport.pdf", "abc123def456"),
    ])
    digest = format_digest(scan_metadata(df))
    assert "Doublons stricts (empreinte SHA-256" in digest
    assert "1 groupe(s)" in digest


def test_digest_reports_absence_of_strict_duplicates():
    df = _df_fp([
        _fp_item("2", "a/x.pdf", "h1"),
        _fp_item("3", "b/y.pdf", "h2"),
    ])
    digest = format_digest(scan_metadata(df))
    assert "aucun fichier binairement identique" in digest


# ── Dossiers sources & structuration existante (respect de l'ordre originel) ─

def test_source_folders_nonempty_titles_root_excluded():
    df = _df([
        {"ID": "1", "ParentID": "", "File": ".",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Fonds"},
        {"ID": "2", "ParentID": "1", "File": "Compta",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Comptabilité"},
        {"ID": "3", "ParentID": "2", "File": "Compta/budget.xlsx",
         "Content.DescriptionLevel": "Item", "Content.Title": "budget"},
        # Dossier vide : compté dans total, exclu des titres (sa disparition
        # d'un plan conservateur n'est pas un écart).
        {"ID": "4", "ParentID": "1", "File": "Vide",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Dossier vide"},
    ])
    src = scan_metadata(df)["sourceFolders"]
    assert src["total"] == 2          # racine "." jamais comptée
    assert src["nonEmpty"] == 1
    assert src["titles"] == ["Comptabilité"]


def test_source_folders_title_falls_back_to_folder_name():
    df = _df([
        {"ID": "1", "ParentID": "", "File": ".",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Fonds"},
        {"ID": "2", "ParentID": "1", "File": "chemin/01_Compta",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": ""},
        {"ID": "3", "ParentID": "2", "File": "chemin/01_Compta/a.pdf",
         "Content.DescriptionLevel": "Item", "Content.Title": "a"},
    ])
    assert scan_metadata(df)["sourceFolders"]["titles"] == ["01_Compta"]


def test_source_folders_safe_without_columns():
    df = pd.DataFrame([{"File": "x/a.pdf", "Content.DescriptionLevel": "Item"}])
    assert scan_metadata(df)["sourceFolders"] == {
        "total": 0, "nonEmpty": 0, "titles": [],
    }


def test_structure_indicators_root_items_top_folders_and_prefixes():
    df = _df([
        {"ID": "1", "ParentID": "", "File": ".",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Fonds"},
        {"ID": "2", "ParentID": "1", "File": "01_Compta",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "01_Compta"},
        {"ID": "3", "ParentID": "1", "File": "Photos",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Photos"},
        _item("4", "en_vrac.pdf", "en_vrac.pdf"),         # à la racine
        _item("5", "01_Compta/a.pdf", "a.pdf"),
        _item("6", "01_Compta/b.pdf", "b.pdf"),
        _item("7", "Photos/c.jpg", "c.jpg"),
    ])
    s = scan_metadata(df)["structure"]
    assert s["rootItems"] == 1
    assert s["rootItemsPct"] == 25.0
    assert s["topFolders"][0] == ("01_Compta", 2)   # fichiers DIRECTS
    assert s["prefixedFolders"] == 1                # 01_Compta, pas Photos
    assert s["folderCount"] == 2                    # racine exclue


def test_structure_year_folder_is_not_an_order_prefix():
    # « 2024 » sans séparateur `_ . ) -` après les chiffres n'est PAS un préfixe
    # d'ordre… mais « 2024 » suivi d'une espace en est un au sens mécanique ;
    # on vérifie surtout qu'un nom purement numérique ne casse rien.
    df = _df([
        {"ID": "1", "ParentID": "", "File": ".",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Fonds"},
        {"ID": "2", "ParentID": "1", "File": "2024",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "2024"},
        _item("3", "2024/rapport.pdf", "rapport"),
    ])
    s = scan_metadata(df)["structure"]
    assert s["prefixedFolders"] == 0
    assert s["folderCount"] == 1


def test_digest_reports_structure():
    df = _df([
        {"ID": "1", "ParentID": "", "File": ".",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Fonds"},
        {"ID": "2", "ParentID": "1", "File": "01_Compta",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "01_Compta"},
        _item("3", "01_Compta/a.pdf", "a.pdf"),
        _item("4", "perdu.pdf", "perdu.pdf"),
    ])
    digest = format_digest(scan_metadata(df))
    assert "Structuration existante" in digest
    assert "1 fichier(s) à la racine (50.0 % des fichiers)" in digest
    assert "01_Compta (1)" in digest
    assert "1 dossier(s) sur 1 à préfixe d'ordre numérique" in digest


def test_digest_structure_without_folders_stays_accurate():
    # Aucun RecordGrp recensé : la ligne reste mécaniquement exacte (pas de
    # « tous les fichiers à la racine » si les chemins sont profonds).
    df = _df([_item("2", "x/a.pdf", "a.pdf")])
    digest = format_digest(scan_metadata(df))
    assert "aucun dossier recensé" in digest
    assert "0 fichier(s) à la racine" in digest


def test_digest_structure_absent_on_empty_scan():
    digest = format_digest(scan_metadata(_df([])))
    assert "Structuration existante" not in digest


# ── Robustesse / cas limites ────────────────────────────────────────────────

def test_empty_dataframe_is_safe():
    df = _df([])
    scan = scan_metadata(df)
    assert scan["volumetry"] == {"items": 0, "recordGrps": 0, "rows": 0, "maxDepth": 0}
    # Le digest doit se formater sans erreur même vide.
    assert isinstance(format_digest(scan), str)


def test_large_volume_scan():
    rows = [{"ID": "1", "ParentID": "", "File": ".",
             "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Fonds"}]
    for i in range(5000):
        rows.append(_item(str(i + 2), f"d/doc{i}.pdf", f"Doc {i % 100}"))
    scan = scan_metadata(_df(rows))
    assert scan["volumetry"]["items"] == 5000
    assert scan["formats"]["top"][0] == ("pdf", 5000)


# ── Digest ──────────────────────────────────────────────────────────────────

def test_digest_contains_key_facts():
    df = _df([
        _item("2", "x/a.doc", "Rapport"),
        _item("3", "y/b.doc", "Rapport"),
        _item("4", "x/Thumbs.db", "Thumbs.db"),
    ])
    digest = format_digest(scan_metadata(df))
    assert "Volumétrie" in digest
    assert "Formats à risque" in digest
    assert "doc" in digest
    # Le bruit numérique est un repérage mécanique (liste fixe) : présent dans le digest.
    assert "Bruit numérique" in digest
    assert "fichier système (1)" in digest
    # Les analyses sémantiques (doublons, nommage) restent au modèle : absentes du digest.
    assert "Doublons" not in digest
    assert "nommage" not in digest


def test_digest_reports_absence_of_noise():
    df = _df([_item("2", "x/a.pdf", "a.pdf")])
    digest = format_digest(scan_metadata(df))
    assert "aucun fichier système" in digest


def test_digest_reports_empty_folders():
    df = _df([
        {"ID": "1", "ParentID": "", "File": ".",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Fonds"},
        {"ID": "2", "ParentID": "1", "File": "Vide",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Dossier vide"},
        _item("3", "Plein/a.pdf", "a.pdf"),
        {"ID": "4", "ParentID": "1", "File": "Plein",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Plein"},
    ])
    # NB : l'Item "3" est rattaché à ParentID "1" via _item() ; on vérifie surtout
    # que la ligne « Dossiers vides » apparaît quand au moins un dossier est vide.
    digest = format_digest(scan_metadata(df))
    assert "Dossiers vides" in digest
