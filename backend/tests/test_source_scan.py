"""Tests du scan de dossier local → CSV canonique (core/source_scan.py)."""
from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from core.csv_handler import read_csv, validate_csv
from core.source_scan import (
    SourceScanError,
    rows_to_csv,
    scan_source_csv,
    scan_source_tree,
    write_source_csv,
)


def _make_tree(root: Path) -> None:
    """Petite arborescence déterministe (2 dossiers, 3 fichiers)."""
    (root / "Administration").mkdir()
    (root / "Administration" / "Contrats").mkdir()
    (root / "Administration" / "note de service.docx").write_text("x", encoding="utf-8")
    (root / "Administration" / "Contrats" / "contrat 2020.pdf").write_text("x", encoding="utf-8")
    (root / "budget 2021.xlsx").write_text("x", encoding="utf-8")


def test_scan_produces_canonical_rows(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    rows, stats = scan_source_tree(tmp_path)

    assert stats["itemCount"] == 3
    assert stats["folderCount"] == 2  # Administration + Contrats

    root_row = rows[0]
    assert root_row["ID"] == "1"
    assert root_row["ParentID"] == ""
    assert root_row["File"] == "."
    assert root_row["Content.DescriptionLevel"] == "RecordGrp"

    items = [r for r in rows if r["Content.DescriptionLevel"] == "Item"]
    assert len(items) == 3
    # Titre = nom sans extension, underscores → espaces
    titles = {r["Content.Title"] for r in items}
    assert "budget 2021" in titles
    # File relatif POSIX
    files = {r["File"] for r in items}
    assert "Administration/Contrats/contrat 2020.pdf" in files


def test_scan_csv_roundtrips_through_read_csv(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    csv_text, _ = scan_source_csv(tmp_path)
    df = read_csv(io.BytesIO(csv_text.encode("utf-8")))
    assert validate_csv(df) == []  # le CSV dérivé est canonique et valide
    assert (df["Content.DescriptionLevel"] == "Item").sum() == 3


def test_scan_excludes_system_and_hidden(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    (tmp_path / "Thumbs.db").write_text("x", encoding="utf-8")
    (tmp_path / "desktop.ini").write_text("x", encoding="utf-8")
    (tmp_path / "~$note de service.docx").write_text("x", encoding="utf-8")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "junk.tmp").write_text("x", encoding="utf-8")
    (tmp_path / ".hiddenfile").write_text("x", encoding="utf-8")

    rows, stats = scan_source_tree(tmp_path)
    assert stats["itemCount"] == 3  # inchangé : le bruit système est écarté
    assert stats["excludedCount"] >= 5
    files = {r["File"] for r in rows}
    assert not any("Thumbs" in f or ".cache" in f or "~$" in f for f in files)


def test_scan_never_opens_binaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantie centrale : le scan ne lit **jamais** le contenu — il réussit
    même si `open` est rendu inopérant."""
    _make_tree(tmp_path)

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("le scan ne doit jamais ouvrir un fichier")

    monkeypatch.setattr("builtins.open", _boom)
    rows, stats = scan_source_tree(tmp_path)
    assert stats["itemCount"] == 3


def test_scan_symlinks_not_followed(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    target = tmp_path / "Administration"
    link = tmp_path / "raccourci"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("création de lien symbolique non autorisée sur cet hôte")
    rows, stats = scan_source_tree(tmp_path)
    assert stats["skippedSymlinks"] >= 1
    files = {r["File"] for r in rows}
    assert not any(f.startswith("raccourci") for f in files)


def test_scan_max_items_guard(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    with pytest.raises(SourceScanError) as exc:
        scan_source_tree(tmp_path, max_items=2)
    assert "trop volumineux" in str(exc.value)
    assert exc.value.hint # message actionnable


def test_scan_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(SourceScanError):
        scan_source_tree(tmp_path / "nexistepas")


def test_folder_dates_span_descendants(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    f1 = tmp_path / "sub" / "a.txt"
    f2 = tmp_path / "sub" / "b.txt"
    f1.write_text("x", encoding="utf-8")
    f2.write_text("x", encoding="utf-8")
    # Dates de modification distinctes : 2020-01-01 et 2022-06-15 (UTC).
    os.utime(f1, (1577880000, 1577880000))   # 2020-01-01
    os.utime(f2, (1655280000, 1655280000))   # 2022-06-15
    rows, _ = scan_source_tree(tmp_path)
    sub = next(r for r in rows if r["File"] == "sub")
    assert sub["Content.StartDate"] == "2020-01-01"
    assert sub["Content.EndDate"] == "2022-06-15"


def test_write_source_csv_utf8_bom(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    dest = tmp_path.parent / "out.csv"
    stats = write_source_csv(tmp_path, dest)
    assert stats["itemCount"] == 3
    raw = dest.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM (comme RESIP)


def test_rows_to_csv_deterministic(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    rows, _ = scan_source_tree(tmp_path)
    assert rows_to_csv(rows) == rows_to_csv(rows)
