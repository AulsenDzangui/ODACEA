"""Tests de l'adoption d'un plan fourni par l'archiviste (core/plan_folders.py) :
conversion CSV « dossiers seuls » / Markdown → plan canonique parsable, endpoint
/plan/from-file, et round-trip matérialiser ↔ re-scanner."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from api.main import app
from core import plan_folders as pf
from core.csv_handler import parse_plan_tree, read_csv

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


# ── Conversion CSV « dossiers seuls » → plan canonique parsable ──────────────

def test_plan_nodes_from_folders_builds_parsable_plan():
    nodes, root_title, warnings, stats = pf.plan_nodes_from_folders_df(_df(_FOLDERS_CSV))
    block = pf.serialize_plan_block(nodes, root_title)
    tree = parse_plan_tree(block)
    # 3 dossiers (la racine File="." est exclue), hiérarchie correcte.
    assert len(tree) == 3
    assert tree["2-1_sous"] == "2_B_dossiers"
    assert root_title == "Mon fonds"
    assert stats["folderCount"] == 3
    assert stats["ignoredItemCount"] == 1
    assert any("Item" in w for w in warnings)


def test_plan_nodes_from_folders_no_recordgrp_raises():
    only_items = (
        "ID;ParentID;File;Content.DescriptionLevel;Content.Title;Content.StartDate;Content.EndDate\n"
        "1;;a.pdf;Item;a.pdf;2020;2020\n"
    )
    with pytest.raises(ValueError, match="RecordGrp"):
        pf.plan_nodes_from_folders_df(_df(only_items))


def test_adopt_markdown_plan_passthrough_and_reject():
    block = pf.serialize_plan_block([pf.PlanNode("Pilotage", "Pilotage")], "Fonds")
    plan, _w = pf.adopt_markdown_plan(block)
    assert parse_plan_tree(plan)
    with pytest.raises(ValueError):
        pf.adopt_markdown_plan("juste de la prose, aucune arborescence")


def test_looks_like_csv_routing():
    assert pf.looks_like_csv("plan.csv", "ID;ParentID\n1;")
    assert pf.looks_like_csv("", "a;b;c\n1;2;3")
    assert not pf.looks_like_csv("plan.md", "Fonds → F/")
    # Un Markdown à flèches n'est jamais pris pour un CSV même avec des « ; ».
    assert not pf.looks_like_csv("", "Fonds — X → F/ ; suite")


# ── Round-trip : matérialiser ↔ re-scanner (fidélité par construction) ───────

def test_materialize_then_scan_round_trip_identical(tmp_path):
    nodes, root_title, _w, _s = pf.plan_nodes_from_folders_df(_df(_FOLDERS_CSV))
    block = pf.serialize_plan_block(nodes, root_title)

    root = tmp_path / "work"
    pf.materialize_plan(block, root)
    # Dossiers écrits avec leur nom technique verbatim, aucun fichier.
    created = {p.name for p in root.rglob("*")}
    assert "1_A_pilotage" in created and "2-1_sous" in created
    assert all(p.is_dir() for p in root.rglob("*"))

    nodes2, rt2, _w2, _s2 = pf.scan_folder_tree(root)
    block2 = pf.serialize_plan_block(nodes2, rt2)
    # Re-matérialiser le plan re-scanné puis re-scanner : strictement identique.
    pf.materialize_plan(block2, root, clear=True)
    nodes3, rt3, _w3, _s3 = pf.scan_folder_tree(root)
    assert pf.serialize_plan_block(nodes3, rt3) == block2


def test_scan_natural_sort_beyond_nine_siblings(tmp_path):
    root = tmp_path / "w"
    root.mkdir()
    for i in range(1, 13):
        (root / f"{i}_Item{i:02d}").mkdir()
    nodes, _rt, _w, _s = pf.scan_folder_tree(root)
    slugs = [n.slug for n in nodes]
    assert slugs[0] == "Item01" and slugs[-1] == "Item12"


# ── Endpoint /plan/from-file ─────────────────────────────────────────────────

def test_plan_from_file_csv_endpoint():
    data = client.post("/plan/from-file", json={"name": "p.csv", "content": _FOLDERS_CSV}).json()
    assert data["format"] == "csv"
    assert data["folderCount"] == 3
    assert data["ignoredItemCount"] == 1
    assert "2-1_sous" in data["planTree"]


def test_plan_from_file_markdown_endpoint():
    block = pf.serialize_plan_block([pf.PlanNode("Pilotage", "Pilotage")], "Fonds")
    data = client.post("/plan/from-file", json={"name": "plan.md", "content": block}).json()
    assert data["format"] == "markdown"
    assert data["folderCount"] == 1


def test_plan_from_file_rejects_unusable():
    resp = client.post("/plan/from-file", json={"name": "x.md", "content": "rien"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "plan_unreadable"


def test_plan_from_folder_endpoint(tmp_path):
    (tmp_path / "Ressources humaines").mkdir()
    (tmp_path / "Marchés publics" / "2019").mkdir(parents=True)
    data = client.post("/plan/from-folder", json={"workDir": str(tmp_path)}).json()
    assert data["folderCount"] == 3
    assert "1_Marches_publics" in data["planTree"]
    assert parse_plan_tree(data["plan"])


def test_plan_from_folder_missing_dir():
    resp = client.post("/plan/from-folder", json={"workDir": ""})
    assert resp.status_code == 400
    assert resp.json()["code"] == "plan_workdir_missing"
