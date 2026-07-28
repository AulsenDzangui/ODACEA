"""Tests CLI — `odacea scan`, détection de dossier à l'entrée
et `odacea apply` (N9)."""
from __future__ import annotations

import json
from pathlib import Path

import cli
from core.csv_handler import read_csv, validate_csv
from tests.conftest import FakeProvider


def _use_provider(monkeypatch, provider):
    monkeypatch.setattr(cli, "get_provider", lambda **kw: provider)
    return provider


def _make_source(root: Path) -> None:
    (root / "Administration" / "Contrats").mkdir(parents=True)
    (root / "Administration" / "note.docx").write_text("NOTE", encoding="utf-8")
    (root / "Administration" / "Contrats" / "contrat.pdf").write_text("CONTRAT", encoding="utf-8")
    (root / "budget.xlsx").write_text("BUDGET", encoding="utf-8")


# ── odacea scan ──────────────────────────────────────────────────────────────

def test_scan_writes_canonical_csv(tmp_path, capsys):
    src = tmp_path / "vrac"
    src.mkdir()
    _make_source(src)
    out = tmp_path / "vrac.csv"
    rc = cli.main(["scan", str(src), "-o", str(out), "--json"])
    assert rc == cli.EXIT_OK
    with open(out, "rb") as f:
        df = read_csv(f)
    assert validate_csv(df) == []
    assert (df["Content.DescriptionLevel"] == "Item").sum() == 3
    summary = json.loads(capsys.readouterr().out)
    assert summary["scan"]["itemCount"] == 3


def test_scan_missing_dir(tmp_path):
    rc = cli.main(["scan", str(tmp_path / "nope"), "-o", str(tmp_path / "x.csv")])
    assert rc == cli.EXIT_INPUT_INVALID


# ── audit/run acceptent un dossier ───────────────────────────────────────────

def test_audit_accepts_a_folder(monkeypatch, tmp_path, golden_aud):
    _use_provider(monkeypatch, FakeProvider(response=golden_aud))
    src = tmp_path / "vrac"
    src.mkdir()
    _make_source(src)
    rc = cli.main([
        "audit", str(src),
        "--out-report", str(tmp_path / "rapport.md"),
        "--model", "test-model",
    ])
    assert rc == cli.EXIT_OK
    assert (tmp_path / "rapport.md").read_text(encoding="utf-8") == golden_aud


# ── N9 : odacea apply ────────────────────────────────────────────────────────

def _resip_csv(path: Path) -> None:
    """Écrit un petit CSV RESIP (sortie de classement) canonique."""
    rows = [
        ("1", "", ".", "RecordGrp", "Fonds", "", ""),
        ("2", "1", "1_Administration", "RecordGrp", "Administration", "", ""),
        ("3", "2", "Administration/Contrats/contrat.pdf", "Item", "2020-01-01_contrat.pdf", "", ""),
        ("4", "2", "budget.xlsx", "Item", "2021-03-02_budget.xlsx", "", ""),
    ]
    header = "ID;ParentID;File;Content.DescriptionLevel;Content.Title;Content.StartDate;Content.EndDate"
    lines = [header] + [";".join(r) for r in rows]
    path.write_text("\n".join(lines), encoding="utf-8-sig")


def test_apply_copies_source_intact(tmp_path, capsys):
    src = tmp_path / "vrac"
    src.mkdir()
    _make_source(src)
    resip = tmp_path / "resultat.csv"
    _resip_csv(resip)
    tgt = tmp_path / "classe"
    before = sorted(str(p.relative_to(src)) for p in src.rglob("*") if p.is_file())

    rc = cli.main([
        "apply", str(resip),
        "--source-root", str(src), "--target-root", str(tgt),
        "--yes", "--json",
    ])
    assert rc == cli.EXIT_OK
    assert (tgt / "1_Administration" / "2020-01-01_contrat.pdf").is_file()
    assert (tgt / "1_Administration" / "2021-03-02_budget.xlsx").is_file()
    # Source strictement identique (copie seule, jamais de mutation).
    after = sorted(str(p.relative_to(src)) for p in src.rglob("*") if p.is_file())
    assert before == after
    summary = json.loads(capsys.readouterr().out)
    assert summary["stats"]["copied"] == 2
    assert summary["verify"]["present"] == 2


def test_apply_dry_run_writes_nothing(tmp_path, capsys):
    src = tmp_path / "vrac"
    src.mkdir()
    _make_source(src)
    resip = tmp_path / "resultat.csv"
    _resip_csv(resip)
    tgt = tmp_path / "classe"
    rc = cli.main([
        "apply", str(resip),
        "--source-root", str(src), "--target-root", str(tgt),
        "--dry-run", "--json",
    ])
    assert rc == cli.EXIT_OK
    assert not tgt.exists()  # aucun fichier écrit
    summary = json.loads(capsys.readouterr().out)
    assert summary["dryRun"] is True
    assert summary["preview"]["total"] == 2


def test_apply_resume_completes(tmp_path):
    src = tmp_path / "vrac"
    src.mkdir()
    _make_source(src)
    resip = tmp_path / "resultat.csv"
    _resip_csv(resip)
    tgt = tmp_path / "classe"
    # Première application complète.
    cli.main(["apply", str(resip), "--source-root", str(src), "--target-root", str(tgt), "--yes"])
    # Reprise : cible déjà peuplée, autorisée par --resume ; tout sauté, EXIT_OK.
    rc = cli.main([
        "apply", str(resip), "--source-root", str(src), "--target-root", str(tgt),
        "--resume", "--yes",
    ])
    assert rc == cli.EXIT_OK


def test_apply_target_under_source_refused(tmp_path):
    src = tmp_path / "vrac"
    src.mkdir()
    _make_source(src)
    resip = tmp_path / "resultat.csv"
    _resip_csv(resip)
    rc = cli.main([
        "apply", str(resip),
        "--source-root", str(src), "--target-root", str(src / "sortie"),
        "--yes",
    ])
    assert rc == cli.EXIT_INPUT_INVALID


def test_apply_journal(tmp_path):
    src = tmp_path / "vrac"
    src.mkdir()
    _make_source(src)
    resip = tmp_path / "resultat.csv"
    _resip_csv(resip)
    tgt = tmp_path / "classe"
    journal = tmp_path / "journal.md"
    rc = cli.main([
        "apply", str(resip),
        "--source-root", str(src), "--target-root", str(tgt),
        "--yes", "--journal", str(journal),
    ])
    assert rc == cli.EXIT_OK
    text = journal.read_text(encoding="utf-8")
    assert "Application physique du classement" in text
