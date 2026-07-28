"""Souveraineté de l'archiviste sur le plan de classement.

On couvre le moteur (`core.plan_folders`) et les endpoints :
- Adoption d'un plan fourni (CSV Resip « dossiers seuls » / Markdown) sans LLM ;
- Matérialisation en dossiers vides réels, re-scan, round-trip fidèle,
  aperçu des changements, garde-fous (fichiers ignorés, vidage confirmé) ;
- Traçabilité de l'origine du plan dans le journal.
"""
import io

import pytest
from fastapi.testclient import TestClient

from api.main import app
from core import plan_folders as pf
from core.csv_handler import parse_plan_tree, read_csv
from core.journal import build_journal, format_journal_markdown

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


# ── conversion CSV « dossiers seuls » → plan canonique parsable ──────────────

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
    block = pf.serialize_plan_block(
        [pf.PlanNode("Pilotage", "Pilotage")], "Fonds"
    )
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


# ── round-trip matérialiser ↔ re-scanner ─────────────────────────────────────

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


def test_scan_from_scratch_empty_dir_names(tmp_path):
    """Un plan créé de zéro dans un répertoire vide (noms libres) est slugifié et
    numéroté sensément, et produit un plan parsable."""
    root = tmp_path / "neuf"
    (root / "Ressources humaines").mkdir(parents=True)
    (root / "Marchés publics").mkdir()
    nodes, rt, _w, _s = pf.scan_folder_tree(root)
    block = pf.serialize_plan_block(nodes, rt)
    tree = parse_plan_tree(block)
    # Noms libres triés alphabétiquement (« Marchés » avant « Ressources ») puis
    # numérotés ; accents retirés à la slugification.
    assert set(tree) == {"1_Marches_publics", "2_Ressources_humaines"}


def test_scan_ignores_and_reports_files(tmp_path):
    root = tmp_path / "w"
    (root / "1_Dossier").mkdir(parents=True)
    (root / "parasite.txt").write_text("x", encoding="utf-8")
    (root / "1_Dossier" / "interne.pdf").write_text("x", encoding="utf-8")
    nodes, _rt, warnings, stats = pf.scan_folder_tree(root)
    assert [n.slug for n in nodes] == ["Dossier"]
    assert stats["ignoredFileCount"] == 2
    assert any("fichier" in w.lower() for w in warnings)


def test_materialize_requires_parsable_plan(tmp_path):
    with pytest.raises(ValueError):
        pf.materialize_plan("aucune arborescence ici", tmp_path / "w")


def test_clear_only_wipes_directory_contents(tmp_path):
    root = tmp_path / "w"
    (root / "ancien").mkdir(parents=True)
    sibling = tmp_path / "voisin"
    sibling.mkdir()
    block = pf.serialize_plan_block([pf.PlanNode("Neuf", "Neuf")], "Fonds")
    pf.materialize_plan(block, root, clear=True)
    assert not (root / "ancien").exists()  # vidé
    assert (root / "1_Neuf").exists()
    assert sibling.exists()  # jamais touché hors du répertoire de travail


# ── Aperçu des changements ───────────────────────────────────────────────────

def test_diff_detects_rename_and_add_absorbing_subtree(tmp_path):
    nodes, rt, _w, _s = pf.plan_nodes_from_folders_df(_df(_FOLDERS_CSV))
    block = pf.serialize_plan_block(nodes, rt)
    root = tmp_path / "w"
    pf.materialize_plan(block, root)
    before, _rt, _w, _s = pf.scan_folder_tree(root)
    (root / "2_B_dossiers").rename(root / "2_Dossiers_renommes")
    (root / "3_Nouveau").mkdir()
    after, _rt2, _w2, _s2 = pf.scan_folder_tree(root)
    changes = pf.diff_plans(before, after)
    assert {"from": "B_dossiers", "to": "Dossiers_renommes"} in changes["renamed"]
    assert "Nouveau" in changes["added"]
    # Le sous-dossier « sous » a suivi son parent : pas re-signalé.
    assert not any("sous" in x for x in changes["added"] + changes["removed"])


def test_diff_pairs_the_closest_name_and_is_deterministic(tmp_path):
    """Renommage + déplacement + création simultanés : chaque geste doit être
    nommé pour ce qu'il est. Les candidats de même signature de sous-arbre sont
    départagés par **ressemblance du nom** — sinon deux feuilles interchangeables
    s'apparient dans l'ordre d'itération d'un `set` (variable d'un run à l'autre)
    et l'aperçu annonce un renommage que l'archiviste n'a pas fait."""
    nodes, rt, _w, _s = pf.plan_nodes_from_folders_df(_df(_FOLDERS_CSV))
    block = pf.serialize_plan_block(nodes, rt)
    root = tmp_path / "w"
    pf.materialize_plan(block, root)
    before, _rt, _w, _s = pf.scan_folder_tree(root)

    (root / "1_A_pilotage").rename(root / "1_Pilotage_general")
    (root / "3_Nouveau_dossier").mkdir()
    (root / "2_B_dossiers" / "2-1_sous").rename(root / "2-1_sous")
    (root / "2_B_dossiers").rmdir()
    after, _rt2, _w2, _s2 = pf.scan_folder_tree(root)

    changes = pf.diff_plans(before, after)
    assert changes["renamed"] == [{"from": "A_pilotage", "to": "Pilotage_general"}]
    assert changes["moved"] == [{"from": "B_dossiers/sous", "to": "sous"}]
    assert changes["added"] == ["Nouveau_dossier"]
    assert changes["removed"] == ["B_dossiers"]
    # Stable d'un appel à l'autre (aucune dépendance à l'ordre d'un `set`).
    assert all(pf.diff_plans(before, after) == changes for _ in range(3))


# ── Endpoints ────────────────────────────────────────────────────────────────

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
    data = client.post("/plan/from-file", json={"name": "x.md", "content": "rien"})
    assert data.status_code == 400
    assert data.json()["code"] == "plan_unreadable"


def test_plan_materialize_and_from_folder_endpoints(tmp_path):
    block = pf.serialize_plan_block([pf.PlanNode("Pilotage", "Pilotage")], "Fonds")
    work = str(tmp_path / "w")
    mat = client.post(
        "/plan/materialize", json={"planValide": block, "workDir": work}
    ).json()
    assert mat["folderCount"] == 1
    scan = client.post(
        "/plan/from-folder", json={"workDir": work, "currentPlan": block}
    ).json()
    assert scan["folderCount"] == 1
    assert scan["changes"]["identical"]


def test_plan_materialize_clear_requires_confirmation(tmp_path):
    block = pf.serialize_plan_block([pf.PlanNode("A", "A")], "Fonds")
    resp = client.post(
        "/plan/materialize",
        json={"planValide": block, "workDir": str(tmp_path / "w"), "clear": True},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "plan_clear_unconfirmed"


def test_plan_from_folder_missing_dir():
    resp = client.post("/plan/from-folder", json={"workDir": "/n/existe/pas/odacea"})
    assert resp.status_code == 400


# ── traçabilité de l'origine du plan ─────────────────────────────────────────

def test_journal_records_plan_origin_fourni():
    j = build_journal(
        command="classement", input_name="v.csv", model="m",
        prompt_versions={"CLA-001": "1.3.0"}, plan_origin="fourni", plan_modified=True,
    )
    md = format_journal_markdown(j)
    assert j["planOrigin"] == "fourni"
    assert "fourni par l'archiviste" in md
    assert "retouches manuelles" in md


def test_journal_records_plan_origin_audit_llm():
    j = build_journal(
        command="run", input_name="v.csv", model="m",
        prompt_versions={}, plan_origin="audit_llm",
    )
    assert "audit LLM" in format_journal_markdown(j)


def test_journal_omits_origin_when_unset():
    j = build_journal(command="audit", input_name="v.csv", model="m", prompt_versions={})
    assert j["planOrigin"] is None
    assert "Origine du plan" not in format_journal_markdown(j)


def test_journal_endpoint_threads_plan_origin():
    data = client.post("/journal", json={
        "command": "classement", "inputName": "v.csv", "model": "m",
        "planOrigin": "fourni",
    }).json()
    assert data["journal"]["planOrigin"] == "fourni"
    assert "fourni par l'archiviste" in data["markdown"]
