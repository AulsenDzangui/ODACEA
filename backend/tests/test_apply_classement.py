"""Tests de l'application physique du classement (core/apply_classement.py).

Garantie centrale vérifiée ici : la **source n'est jamais mutée** (copie seule),
l'application est **idempotente** (reprise), et les garde-fous du répertoire cible
tiennent."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.apply_classement import (
    apply_plan,
    build_apply_plan,
    check_target_guards,
    iter_apply,
    verify_apply,
)

COLUMNS = [
    "ID", "ParentID", "File", "Content.DescriptionLevel",
    "Content.Title", "Content.StartDate", "Content.EndDate",
]


def _resip_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows).reindex(columns=COLUMNS).fillna("").astype(str)


def _basic_resip() -> pd.DataFrame:
    """SIP produit : racine → 1_Administration → 1-1_Contrats, avec 2 items."""
    return _resip_df([
        {"ID": "1", "ParentID": "", "File": ".", "Content.DescriptionLevel": "RecordGrp",
         "Content.Title": "Fonds"},
        {"ID": "2", "ParentID": "1", "File": "1_Administration",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Administration"},
        {"ID": "3", "ParentID": "2", "File": "1-1_Contrats",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Contrats"},
        {"ID": "4", "ParentID": "3", "File": "vieux/contrat a.pdf",
         "Content.DescriptionLevel": "Item", "Content.Title": "2020-01-01_contrat.pdf"},
        {"ID": "5", "ParentID": "2", "File": "note.docx",
         "Content.DescriptionLevel": "Item", "Content.Title": "2021-03-02_note.docx"},
    ])


def _make_source(root: Path) -> None:
    (root / "vieux").mkdir(parents=True)
    (root / "vieux" / "contrat a.pdf").write_text("CONTRAT", encoding="utf-8")
    (root / "note.docx").write_text("NOTE", encoding="utf-8")


def _inventory(root: Path) -> dict[str, int]:
    """Empreinte structurelle {chemin relatif: taille} du répertoire (métadonnées)."""
    return {
        str(p.relative_to(root)): p.stat().st_size
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_apply_copies_to_target_tree(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "out"
    _make_source(src)
    plan = build_apply_plan(_basic_resip(), src)
    stats = apply_plan(plan, src, tgt)

    assert stats["copied"] == 2
    assert stats["failed"] == 0
    assert (tgt / "1_Administration" / "1-1_Contrats" / "2020-01-01_contrat.pdf").is_file()
    assert (tgt / "1_Administration" / "2021-03-02_note.docx").is_file()
    # Contenu recopié à l'identique.
    assert (tgt / "1_Administration" / "2021-03-02_note.docx").read_text(encoding="utf-8") == "NOTE"


def test_source_never_mutated(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "out"
    _make_source(src)
    before = _inventory(src)
    apply_plan(build_apply_plan(_basic_resip(), src), src, tgt)
    after = _inventory(src)
    assert before == after  # aucun déplacement, renommage ni suppression dans la source


def test_apply_is_idempotent_resume(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "out"
    _make_source(src)
    plan = build_apply_plan(_basic_resip(), src)
    first = apply_plan(plan, src, tgt)
    assert first["copied"] == 2
    # Deuxième passe : tout est déjà là à l'identique → sauté (reprise).
    second = apply_plan(build_apply_plan(_basic_resip(), src), src, tgt)
    assert second["copied"] == 0
    assert second["skipped"] == 2


def test_interrupted_then_resume_completes(tmp_path: Path) -> None:
    """Une application interrompue puis relancée achève la copie sans doublon."""
    src = tmp_path / "src"
    tgt = tmp_path / "out"
    _make_source(src)
    plan = build_apply_plan(_basic_resip(), src)
    # Consomme un seul événement de progression (première copie) puis « coupe ».
    gen = iter_apply(plan, src, tgt)
    next(gen)
    gen.close()
    # Reprise : le fichier déjà copié est sauté, le reste est copié.
    final = apply_plan(build_apply_plan(_basic_resip(), src), src, tgt)
    verify = verify_apply(plan, tgt)
    assert verify["present"] == verify["expected"] == 2
    assert final["copied"] + final["skipped"] == 2


def test_missing_binary_reported(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "out"
    (src / "note.docx").parent.mkdir(parents=True, exist_ok=True)
    (src / "note.docx").write_text("NOTE", encoding="utf-8")
    # « vieux/contrat a.pdf » n'existe pas.
    plan = build_apply_plan(_basic_resip(), src)
    assert "vieux/contrat a.pdf" in plan.missing
    stats = apply_plan(plan, src, tgt)
    assert stats["failed"] == 1
    assert stats["copied"] == 1


def test_name_collision_deduplicated(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "out"
    (src / "a").mkdir(parents=True)
    (src / "b").mkdir(parents=True)
    (src / "a" / "x.pdf").write_text("A", encoding="utf-8")
    (src / "b" / "y.pdf").write_text("B", encoding="utf-8")
    # Deux items différents assignés au MÊME dossier cible avec le MÊME nouveau nom.
    df = _resip_df([
        {"ID": "1", "ParentID": "", "File": ".", "Content.DescriptionLevel": "RecordGrp",
         "Content.Title": "Fonds"},
        {"ID": "2", "ParentID": "1", "File": "1_Dossier",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Dossier"},
        {"ID": "3", "ParentID": "2", "File": "a/x.pdf",
         "Content.DescriptionLevel": "Item", "Content.Title": "doc.pdf"},
        {"ID": "4", "ParentID": "2", "File": "b/y.pdf",
         "Content.DescriptionLevel": "Item", "Content.Title": "doc.pdf"},
    ])
    plan = build_apply_plan(df, src)
    assert len(plan.renamed_collisions) == 1
    stats = apply_plan(plan, src, tgt)
    assert stats["copied"] == 2
    names = sorted(p.name for p in (tgt / "1_Dossier").iterdir())
    assert names == ["doc (2).pdf", "doc.pdf"]  # aucun écrasement


def test_invalid_target_name_sanitized(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "out"
    src.mkdir()
    (src / "f.txt").write_text("X", encoding="utf-8")
    df = _resip_df([
        {"ID": "1", "ParentID": "", "File": ".", "Content.DescriptionLevel": "RecordGrp",
         "Content.Title": "Fonds"},
        {"ID": "2", "ParentID": "1", "File": "1_D",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "D"},
        {"ID": "3", "ParentID": "2", "File": "f.txt",
         "Content.DescriptionLevel": "Item", "Content.Title": 'a:b*c?.txt'},
    ])
    plan = build_apply_plan(df, src)
    assert plan.sanitized_names
    apply_plan(plan, src, tgt)
    # Le nom cible ne contient plus de caractère FS invalide.
    written = list((tgt / "1_D").iterdir())
    assert len(written) == 1
    assert not any(c in written[0].name for c in '<>:"/\\|?*')


def test_target_name_keeps_source_extension(tmp_path: Path) -> None:
    """Un titre cible sans extension (ex. option d'export « conserver le titre
    d'origine » : titre Archifiltre sans extension) est copié avec l'extension de
    la source — l'extension est mécanique et obligatoire sur disque."""
    src = tmp_path / "src"
    tgt = tmp_path / "out"
    (src / "vieux").mkdir(parents=True)
    (src / "vieux" / "contrat a.pdf").write_text("CONTRAT", encoding="utf-8")
    (src / "note.docx").write_text("NOTE", encoding="utf-8")
    df = _resip_df([
        {"ID": "1", "ParentID": "", "File": ".", "Content.DescriptionLevel": "RecordGrp",
         "Content.Title": "Fonds"},
        {"ID": "2", "ParentID": "1", "File": "1_Administration",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Administration"},
        # Titres cibles SANS extension (titre d'origine restitué).
        {"ID": "3", "ParentID": "2", "File": "vieux/contrat a.pdf",
         "Content.DescriptionLevel": "Item", "Content.Title": "Contrat de bail"},
        {"ID": "4", "ParentID": "2", "File": "note.docx",
         "Content.DescriptionLevel": "Item", "Content.Title": "Note de service"},
    ])
    plan = build_apply_plan(df, src)
    stats = apply_plan(plan, src, tgt)
    assert stats["copied"] == 2
    names = sorted(p.name for p in (tgt / "1_Administration").iterdir())
    assert names == ["Contrat de bail.pdf", "Note de service.docx"]


def test_target_guard_same_as_source(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    guard = check_target_guards(src, src)
    assert guard is not None
    assert guard["code"] == "apply_target_is_source"


def test_target_guard_under_source(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    guard = check_target_guards(src, src / "sortie")
    assert guard is not None
    assert guard["code"] == "apply_target_in_source"


def test_target_guard_source_under_target(tmp_path: Path) -> None:
    tgt = tmp_path / "out"
    tgt.mkdir()
    src = tgt / "fonds"
    src.mkdir()
    guard = check_target_guards(src, tgt)
    assert guard is not None
    assert guard["code"] == "apply_source_in_target"


def test_target_guard_non_empty_refused_without_resume(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "out"
    src.mkdir()
    tgt.mkdir()
    (tgt / "deja.txt").write_text("x", encoding="utf-8")
    assert check_target_guards(src, tgt)["code"] == "apply_target_not_empty"
    # Avec reprise, un répertoire peuplé est autorisé.
    assert check_target_guards(src, tgt, resume=True) is None
