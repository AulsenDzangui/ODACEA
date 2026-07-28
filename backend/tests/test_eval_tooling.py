"""Outillage du harnais d'éval (scripts/) — déterministe, sans LLM.

- `tree_to_archifiltre_csv.py` : arborescence → CSV Archifiltre canonique
  (corpus d'éval autonome, sans Archifiltre Docs) ; depuis le la logique
  vit dans `core.source_scan` (le script n'est qu'un mince point d'entrée) ;
- `make_corrections_from_run.py` : dérive un fichier de corrections des
  classements *sur-plan* d'un run de référence.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from core.csv_handler import read_csv
from core.source_scan import scan_source_tree, write_source_csv

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- tree_to_archifiltre_csv -----------------------------------------------


def _make_tree(root: Path) -> None:
    (root / "01_Inscriptions").mkdir(parents=True)
    (root / "02_Cantine").mkdir()
    (root / "01_Inscriptions" / "liste.xlsx").write_text("", encoding="utf-8")
    (root / "01_Inscriptions" / "fiche_eleve.pdf").write_text("", encoding="utf-8")
    (root / "02_Cantine" / "menus.docx").write_text("", encoding="utf-8")


def test_tree_converter_builds_canonical_rows(tmp_path):
    root = tmp_path / "Fonds"
    _make_tree(root)
    rows, _ = scan_source_tree(root)

    by_level = [r["Content.DescriptionLevel"] for r in rows]
    assert by_level.count("Item") == 3
    # Racine canonique.
    rootrow = rows[0]
    assert rootrow["ID"] == "1" and rootrow["ParentID"] == "" and rootrow["File"] == "."
    assert rootrow["Content.DescriptionLevel"] == "RecordGrp"
    # Les Item portent un chemin POSIX relatif et une date.
    items = [r for r in rows if r["Content.DescriptionLevel"] == "Item"]
    assert all("/" in r["File"] for r in items)
    assert all(len(r["Content.StartDate"]) == 10 for r in items)


def test_tree_converter_output_parses_via_engine(tmp_path):
    """Le script (mince wrapper) écrit un CSV canonique lisible par le moteur."""
    conv = _load("tree_to_archifiltre_csv")
    root = tmp_path / "Fonds"
    _make_tree(root)
    dest = tmp_path / "vrac.csv"
    conv.main([str(root), "--out", str(dest)])

    df = read_csv(dest)
    assert (df["Content.DescriptionLevel"] == "Item").sum() == 3
    # Racine marquée File="." (contrat Archifiltre/RESIP).
    assert (df["File"] == ".").sum() == 1


def test_tree_converter_is_deterministic(tmp_path):
    root = tmp_path / "Fonds"
    _make_tree(root)
    first = write_source_csv(root, tmp_path / "a.csv")
    second = write_source_csv(root, tmp_path / "b.csv")
    assert first == second
    assert (tmp_path / "a.csv").read_bytes() == (tmp_path / "b.csv").read_bytes()


# --- make_corrections_from_run ---------------------------------------------

PLAN = """**Arborescence technique :**
```
Fonds → AFFAIRES/
  ├── 1. Inscriptions → 1_Inscriptions/
  └── 2. Cantine → 2_Cantine/
```
"""

RAW_CLA = """```csv
Path;TargetFolder;NewTitle
a/liste.xlsx;1_Inscriptions;2022_liste.xlsx
a/fiche.pdf;1_Inscriptions;2022_fiche.pdf
b/menus.docx;2_Cantine;2022_menus.docx
c/perdu.txt;Dossier_Invente;perdu.txt
d/egare.pdf;egare.pdf;egare.pdf
```
"""


def _make_run_dir(root: Path) -> Path:
    out = root / "run"
    (out / "raw").mkdir(parents=True)
    (out / "plan.md").write_text(PLAN, encoding="utf-8")
    (out / "raw" / "batch_001.txt").write_text(RAW_CLA, encoding="utf-8")
    return out


def test_corrections_generator_keeps_only_on_plan(tmp_path):
    gen = _load("make_corrections_from_run")
    out = _make_run_dir(tmp_path)
    df = gen.build_corrections_df(out, max_rows=12)

    targets = set(df["TargetFolder"])
    # Dossiers réels du plan conservés ; cible inventée / nom de fichier écartés.
    assert targets == {"1_Inscriptions", "2_Cantine"}
    assert "Dossier_Invente" not in targets
    # Métadonnées seules : exactement les trois colonnes.
    assert list(df.columns) == ["Path", "TargetFolder", "NewTitle"]


def test_corrections_generator_diversifies_by_folder(tmp_path):
    gen = _load("make_corrections_from_run")
    out = _make_run_dir(tmp_path)
    df = gen.build_corrections_df(out, max_rows=2)
    # max=2 → un exemple par dossier cible distinct d'abord (couverture).
    assert set(df["TargetFolder"]) == {"1_Inscriptions", "2_Cantine"}
