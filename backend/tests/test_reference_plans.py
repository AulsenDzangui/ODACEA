"""Plan de classement de référence.

La source d'un référentiel est désormais un **CSV Resip « dossiers seuls »**
importé par l'archiviste, converti en bloc arborescence par
`csv_handler.build_reference_tree_from_folders` puis injecté à l'audit via la note
contextuelle (`observation`), sans modifier le prompt AUD-001. On couvre : la
conversion CSV→arbre (noms verbatim, hiérarchie, fichiers ignorés), la composition
de la note (modes inspire/conform), l'endpoint `/reference-plan/from-csv` et
l'injection effective via `/audit`.
"""
import io

import pytest
from fastapi.testclient import TestClient

from api import engine
from api.main import app
from core import reference_plans as rp
from core.csv_handler import build_reference_tree_from_folders, read_csv
from tests.conftest import FakeProvider

client = TestClient(app)


_FOLDERS_CSV = (
    "ID;ParentID;File;Content.DescriptionLevel;Content.Title;Content.StartDate;Content.EndDate\n"
    "1;;.;RecordGrp;Mon fonds;;\n"
    "2;1;Mon_fonds/A_pilotage;RecordGrp;Pilotage;;\n"
    "3;1;Mon_fonds/B_dossiers;RecordGrp;Dossiers individuels;;\n"
    "4;3;Mon_fonds/B_dossiers/sous;RecordGrp;Sous-dossier;;\n"
    "5;3;Mon_fonds/B_dossiers/doc.pdf;Item;doc.pdf;2020;2020\n"
)


def _df(text):
    return read_csv(io.BytesIO(text.encode("utf-8")))


# ── Conversion CSV « dossiers seuls » → bloc arborescence ────────────────────

def test_build_reference_tree_preserves_names_and_hierarchy():
    tree, warnings, stats = build_reference_tree_from_folders(_df(_FOLDERS_CSV))
    # Noms de dossiers conservés verbatim (pas de renumérotation canonique).
    assert "→ A_pilotage/" in tree
    assert "→ B_dossiers/" in tree
    assert "→ sous/" in tree
    # Titre descriptif = Content.Title ; racine encadrée.
    assert "Fonds — [Mon fonds] → Mon_fonds/" in tree
    assert "Pilotage → A_pilotage/" in tree
    # Hiérarchie : le sous-dossier est plus indenté et vient après B_dossiers.
    lines = tree.splitlines()
    idx_b = next(i for i, ln in enumerate(lines) if "B_dossiers/" in ln)
    idx_sous = next(i for i, ln in enumerate(lines) if "→ sous/" in ln)
    assert idx_sous > idx_b
    def indent(ln: str) -> int:
        return len(ln) - len(ln.lstrip())

    assert indent(lines[idx_sous]) > indent(lines[idx_b])
    assert stats["folderCount"] == 4
    assert stats["rootTitle"] == "Mon fonds"


def test_build_reference_tree_ignores_items_with_warning():
    _tree, warnings, stats = build_reference_tree_from_folders(_df(_FOLDERS_CSV))
    assert stats["ignoredItemCount"] == 1
    assert any("Item" in w for w in warnings)


def test_build_reference_tree_no_recordgrp_raises():
    only_items = (
        "ID;ParentID;File;Content.DescriptionLevel;Content.Title;Content.StartDate;Content.EndDate\n"
        "1;;a.pdf;Item;a.pdf;2020;2020\n"
    )
    with pytest.raises(ValueError, match="RecordGrp"):
        build_reference_tree_from_folders(_df(only_items))


def test_build_reference_tree_from_resip_native_export():
    """Un export Resip natif (Id/ParentId, ObjectFiles, Import-N) est normalisé
    en amont par read_csv — la conversion doit fonctionner de la même façon."""
    resip = (
        "Id;ParentId;Content.DescriptionLevel;Content.Title;Content.StartDate;Content.EndDate;ObjectFiles\n"
        "Import-1;;RecordGrp;Fonds;;;.\n"
        "Import-2;Import-1;RecordGrp;Rubrique;;;Fonds/Rubrique\n"
    )
    tree, _w, stats = build_reference_tree_from_folders(_df(resip))
    assert "→ Rubrique/" in tree
    assert stats["folderCount"] == 2


# ── Composition de la note (pur moteur) ──────────────────────────────────────

def test_custom_reference_plan_marks_source():
    plan = rp.custom_reference_plan("```text\nFonds → F/\n```", label="Mon plan")
    assert plan.source == "custom"
    assert plan.label == "Mon plan"
    assert "Fonds → F/" in rp.compose_observation("", plan, "inspire")


def test_compose_observation_injects_tree_and_keeps_note():
    plan = rp.custom_reference_plan("```text\nFonds → F/\n```")
    out = rp.compose_observation("Fonds RH 2010-2020.", plan, "inspire")
    assert "Fonds RH 2010-2020." in out
    assert "Fonds → F/" in out
    assert "Inspirez-vous" in out


def test_compose_observation_conform_mode_is_prescriptive():
    plan = rp.custom_reference_plan("```text\nFonds → F/\n```")
    out = rp.compose_observation("", plan, "conform")
    assert "Conformez-vous" in out
    assert "respecter" in out


def test_compose_observation_no_plan_is_passthrough():
    assert rp.compose_observation("note seule", None, "inspire") == "note seule"
    assert rp.compose_observation("", None, "conform") == ""


def test_normalize_mode_defaults_to_inspire():
    assert rp.normalize_mode(None) == "inspire"
    assert rp.normalize_mode("CONFORM") == "conform"
    assert rp.normalize_mode("n'importe quoi") == "inspire"


# ── Endpoints ────────────────────────────────────────────────────────────────

def test_reference_plan_from_csv_endpoint_success():
    data = client.post("/reference-plan/from-csv", json={"csv": _FOLDERS_CSV}).json()
    assert data["validationErrors"] == []
    assert data["folderCount"] == 4
    assert data["ignoredItemCount"] == 1
    assert "A_pilotage/" in data["tree"]
    assert data["rootTitle"] == "Mon fonds"


def test_reference_plan_from_csv_endpoint_invalid_csv():
    bad = "ID;ParentID;File\n1;;.\n"  # colonnes manquantes
    data = client.post("/reference-plan/from-csv", json={"csv": bad}).json()
    assert data["validationErrors"]
    assert data["tree"] == ""


def test_reference_plan_from_csv_endpoint_no_folders():
    only_items = (
        "ID;ParentID;File;Content.DescriptionLevel;Content.Title;Content.StartDate;Content.EndDate\n"
        "1;;a.pdf;Item;a.pdf;2020;2020\n"
    )
    data = client.post("/reference-plan/from-csv", json={"csv": only_items}).json()
    assert any("RecordGrp" in e for e in data["validationErrors"])


def test_audit_accepts_reference_plan_block(monkeypatch, small_csv_text):
    provider = FakeProvider(response="rapport", reasoning="")
    monkeypatch.setattr(engine, "get_provider", lambda **kw: provider)
    custom = "```text\nFonds → F/\n  └── Divers → Divers/\n```"
    client.post("/audit", json={
        "csv": small_csv_text, "model": "m",
        "referencePlan": custom, "referenceMode": "conform",
    })
    user_msg = provider.calls[-1][1]
    assert "Divers/" in user_msg
    assert "Conformez-vous" in user_msg


def test_audit_without_reference_plan_is_unchanged(monkeypatch, small_csv_text):
    """Sans référentiel, la note injectée est vide — comportement d'origine."""
    provider = FakeProvider(response="rapport", reasoning="")
    monkeypatch.setattr(engine, "get_provider", lambda **kw: provider)
    client.post("/audit", json={"csv": small_csv_text, "model": "m"})
    user_msg = provider.calls[-1][1]
    assert "Plan de classement de référence" not in user_msg
