"""Apprentissage des corrections — moteur déterministe `core.corrections`.

Sans LLM : sélection/rendu des exemples few-shot, garde « métadonnées seules »,
lecture d'un fichier de corrections, robustesse aux entrées partielles.
"""
import pandas as pd
import pytest

from core.corrections import (
    CORRECTION_COLUMNS,
    MAX_EXAMPLES,
    corrections_from_rows,
    normalize_corrections,
    read_corrections_file,
    render_corrections_examples,
    select_examples,
)


def _df(rows):
    return pd.DataFrame(rows, columns=list(CORRECTION_COLUMNS))


def test_render_block_contains_path_target_and_title():
    df = _df([{"Path": "crous/lm.pdf", "TargetFolder": "1-1_Lettres",
               "NewTitle": "2019-09-11_LM_VF.pdf"}])
    block = render_corrections_examples(df)
    assert "appliquez la même logique" in block
    assert "`crous/lm.pdf`" in block
    assert "`1-1_Lettres`" in block
    assert "`2019-09-11_LM_VF.pdf`" in block


def test_render_empty_when_no_usable_correction():
    # Cible manquante ⇒ inexploitable comme exemple.
    df = _df([{"Path": "a.pdf", "TargetFolder": "", "NewTitle": "x.pdf"}])
    assert render_corrections_examples(df) == ""
    assert render_corrections_examples(_df([])) == ""


def test_newtitle_optional_in_render():
    df = _df([{"Path": "a/b.docx", "TargetFolder": "2_Budget", "NewTitle": ""}])
    block = render_corrections_examples(df)
    assert "`a/b.docx` → dossier `2_Budget`" in block
    assert "; nom" not in block  # pas de nom vide affiché


def test_metadata_only_guard_drops_extra_columns():
    """Une colonne de contenu (Content.Description) ne doit jamais survivre :
    seules Path/TargetFolder/NewTitle sont conservées."""
    df = pd.DataFrame([{
        "Path": "a.pdf", "TargetFolder": "X", "NewTitle": "n.pdf",
        "Content.Description": "CORPS CONFIDENTIEL DU DOCUMENT",
    }])
    out = normalize_corrections(df)
    assert list(out.columns) == list(CORRECTION_COLUMNS)
    block = render_corrections_examples(df)
    assert "CONFIDENTIEL" not in block


def test_missing_required_column_raises():
    with pytest.raises(ValueError, match="colonnes manquantes"):
        normalize_corrections(pd.DataFrame([{"Path": "a", "NewTitle": "b"}]))


def test_select_covers_distinct_targets_first():
    df = _df([
        {"Path": "a", "TargetFolder": "F1", "NewTitle": ""},
        {"Path": "b", "TargetFolder": "F1", "NewTitle": ""},
        {"Path": "c", "TargetFolder": "F2", "NewTitle": ""},
    ])
    # Avec 2 exemples : on couvre F1 puis F2 (cibles distinctes) avant de doubler.
    chosen = select_examples(df, max_examples=2)
    assert [e["TargetFolder"] for e in chosen] == ["F1", "F2"]
    assert [e["Path"] for e in chosen] == ["a", "c"]


def test_select_is_bounded_and_deterministic():
    df = _df([{"Path": f"p{i}", "TargetFolder": f"F{i}", "NewTitle": ""}
              for i in range(MAX_EXAMPLES + 5)])
    chosen = select_examples(df)
    assert len(chosen) == MAX_EXAMPLES
    assert select_examples(df) == chosen  # déterministe


def test_corrections_from_rows_accepts_camel_and_canonical_keys():
    df = corrections_from_rows([
        {"path": "a.pdf", "targetFolder": "X", "newTitle": "n.pdf"},
        {"Path": "b.pdf", "TargetFolder": "Y", "NewTitle": "m.pdf"},
    ])
    assert list(df["Path"]) == ["a.pdf", "b.pdf"]
    assert list(df["TargetFolder"]) == ["X", "Y"]


def test_read_corrections_file_roundtrip(tmp_path):
    p = tmp_path / "corr.csv"
    p.write_text(
        "Path;TargetFolder;NewTitle\n"
        "crous/lm.pdf;1-1_Lettres;2019_LM.pdf\n"
        "; ; \n",  # ligne vide ⇒ écartée
        encoding="utf-8",
    )
    df = read_corrections_file(p)
    assert len(df) == 1
    assert df.iloc[0]["TargetFolder"] == "1-1_Lettres"
