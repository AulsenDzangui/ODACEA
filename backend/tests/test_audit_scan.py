"""Tests déterministes du scan de métadonnées (`core.audit_scan`).

Le scan est calculé sans LLM, à partir des seules métadonnées — il est donc
entièrement vérifiable ici. On couvre la volumétrie et le recensement des formats
(dont formats à risque et compressés), plus la robustesse sur gros volume et le
formatage du digest. Les analyses (doublons, nommage, bruit) sont volontairement
laissées au modèle et ne sont donc pas calculées par le scan.
"""
import pandas as pd

from core.audit_scan import format_digest, scan_metadata
from core.csv_handler import REQUIRED_COLUMNS


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
    ])
    digest = format_digest(scan_metadata(df))
    assert "Volumétrie" in digest
    assert "Formats à risque" in digest
    assert "doc" in digest
    # Les analyses (doublons, nommage, bruit) sont laissées au modèle : absentes du digest.
    assert "Doublons" not in digest
    assert "nommage" not in digest
    assert "Bruit" not in digest
