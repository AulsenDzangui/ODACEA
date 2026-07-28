"""Endpoint `/enrich` — étape 0 facultative exposée au front.

Backend **local uniquement** : le serveur ouvre les binaires sous `sourceRoot`.
On couvre l'empreinte SHA-256 (lecture binaire réelle, doublons stricts), la
description (extracteurs monkeypatchés), la garde dossier introuvable, le refus
en mode démonstration et l'avertissement d'accès au contenu.
"""
import pandas as pd
from fastapi.testclient import TestClient

import api.main as main
import core.enrich as enrich_mod
from api.main import app
from core.enrich import FINGERPRINT_COLUMN

client = TestClient(app)


def _csv(rows: list[dict]) -> str:
    cols = [
        "ID", "ParentID", "File", "Content.DescriptionLevel",
        "Content.Title", "Content.StartDate", "Content.EndDate",
    ]
    return pd.DataFrame(rows, columns=cols).to_csv(index=False, sep=";")


def _row(id_, parent, file, level, title=""):
    return {
        "ID": id_, "ParentID": parent, "File": file,
        "Content.DescriptionLevel": level, "Content.Title": title or file,
        "Content.StartDate": "", "Content.EndDate": "",
    }


def _tree(tmp_path):
    """Vrac local factice : a.pdf et b.pdf binairement identiques (doublon strict),
    photo.jpg distinct. Renvoie (source_root, csv_text)."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.pdf").write_bytes(b"contenu identique")
    (docs / "b.pdf").write_bytes(b"contenu identique")
    (tmp_path / "photo.jpg").write_bytes(b"image binaire differente")
    csv = _csv([
        _row("1", "", ".", "RecordGrp", "Racine"),
        _row("2", "1", "docs/a.pdf", "Item"),
        _row("3", "1", "docs/b.pdf", "Item"),
        _row("4", "1", "photo.jpg", "Item"),
    ])
    return str(tmp_path), csv


def test_enrich_fingerprint_only_detects_strict_duplicates(tmp_path):
    source_root, csv = _tree(tmp_path)
    resp = client.post("/enrich", json={
        "csv": csv, "sourceRoot": source_root, "fingerprintOnly": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    # Colonne d'empreinte injectée dans le CSV renvoyé.
    assert FINGERPRINT_COLUMN in data["enrichedCsv"]
    # 3 items hachés, dont 2 binairement identiques.
    assert data["fingerprint"]["hashed"] == 3
    assert data["duplicates"]["groups"] == 1
    assert data["duplicates"]["redundant"] == 1
    # Empreintes seules : pas d'extraction de texte.
    assert "report" not in data
    assert "accès au contenu" in data["contentAccessNotice"]


def test_enrich_writes_descriptions(tmp_path, monkeypatch):
    source_root, csv = _tree(tmp_path)
    # Extracteur .pdf déterministe (on ne lit pas réellement le binaire factice).
    monkeypatch.setitem(
        enrich_mod._EXTRACTORS,
        ".pdf",
        lambda path: {"Sujet": "Budget cantine", "Extrait": f"Texte de {path.name}"},
    )
    resp = client.post("/enrich", json={"csv": csv, "sourceRoot": source_root})
    assert resp.status_code == 200
    data = resp.json()
    # 2 .pdf décrits ; le .jpg est hors périmètre (non bureautique).
    assert data["report"]["enriched"] == 2
    assert data["report"]["unsupported"] == 1
    assert "Budget cantine" in data["enrichedCsv"]
    # Sans le flag, pas d'empreinte.
    assert "fingerprint" not in data


def test_enrich_source_root_missing(tmp_path):
    _, csv = _tree(tmp_path)
    resp = client.post("/enrich", json={
        "csv": csv, "sourceRoot": str(tmp_path / "inexistant"),
    })
    assert resp.status_code == 400
    assert resp.json()["code"] == "enrich_source_missing"


def test_enrich_disabled_in_demo_mode(tmp_path, monkeypatch):
    source_root, csv = _tree(tmp_path)
    monkeypatch.setattr(main, "DEMO_MODE", True)
    resp = client.post("/enrich", json={"csv": csv, "sourceRoot": source_root})
    assert resp.status_code == 403
    assert resp.json()["code"] == "enrich_disabled"
