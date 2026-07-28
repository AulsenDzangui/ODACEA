"""Enrichissement mécanique (`core.enrich`) avec extracteurs mockés.

On ne teste pas pypdf/openpyxl (dépendances tierces) mais la logique du module :
sélection des lignes, préservation des descriptions existantes, comptages du
rapport, tolérance aux erreurs, formatage et garde-fous anti-bruit.
"""
import hashlib

import pandas as pd
import pytest

import core.enrich as enrich_mod
from core.enrich import (
    FINGERPRINT_COLUMN,
    EnrichReport,
    _clean,
    _detect_boilerplate_lines,
    _format_description,
    _is_noise_title,
    _pick_content_title,
    _plausible_snippet,
    _recurring_keywords,
    _redact_emails,
    _resolve,
    _sample_indices,
    _windowed_indices,
    enrich_descriptions,
    fingerprint_files,
)


@pytest.fixture
def source_root(tmp_path):
    """Arborescence locale factice : les binaires existent mais leur contenu
    n'est jamais lu (extracteurs monkeypatchés)."""
    (tmp_path / "dossier").mkdir()
    for name in ("rapport.pdf", "tableur.xlsx"):
        (tmp_path / "dossier" / name).write_bytes(b"binaire factice")
    return tmp_path


def _df(rows):
    return pd.DataFrame(rows)


def _item(file, desc=""):
    return {
        "File": file,
        "Content.DescriptionLevel": "Item",
        "Content.Title": file,
        "Content.Description": desc,
    }


@pytest.fixture
def fake_extractors(monkeypatch):
    """Remplace les extracteurs par des doublures déterministes."""
    calls = []

    def fake_pdf(path):
        calls.append(path.name)
        return {"Sujet": "Budget cantine", "Extrait": "Texte du rapport annuel."}

    def fake_xlsx(path):
        calls.append(path.name)
        return {}  # rien d'exploitable → no_text

    monkeypatch.setitem(enrich_mod._EXTRACTORS, ".pdf", fake_pdf)
    monkeypatch.setitem(enrich_mod._EXTRACTORS, ".xlsx", fake_xlsx)
    return calls


def test_enrich_writes_description_and_reports(source_root, fake_extractors):
    df = _df([
        {"File": ".", "Content.DescriptionLevel": "RecordGrp",
         "Content.Title": "racine", "Content.Description": ""},
        _item("dossier/rapport.pdf"),
        _item("dossier/tableur.xlsx"),          # extracteur vide → no_text
        _item("dossier/photo.jpg"),             # extension hors périmètre
        _item("dossier/absent.pdf"),            # binaire introuvable
        _item("dossier/rapport.pdf", desc="Déjà renseignée"),
    ])
    out, report = enrich_descriptions(df, source_root)

    assert out.loc[1, "Content.Description"] == "Sujet : Budget cantine · Extrait : Texte du rapport annuel."
    # La description existante est préservée sans --overwrite.
    assert out.loc[5, "Content.Description"] == "Déjà renseignée"
    assert (report.total_items, report.enriched) == (5, 1)
    assert report.already_filled == 1
    assert report.no_text == 1
    assert report.unsupported == 1
    assert report.missing == 1
    # La ligne RecordGrp n'est jamais traitée.
    assert fake_extractors == ["rapport.pdf", "tableur.xlsx"]


def test_enrich_overwrite_replaces_existing(source_root, fake_extractors):
    df = _df([_item("dossier/rapport.pdf", desc="Ancienne")])
    out, report = enrich_descriptions(df, source_root, overwrite=True)
    assert "Budget cantine" in out.loc[0, "Content.Description"]
    assert report.enriched == 1


def test_enrich_extractor_error_is_isolated(source_root, monkeypatch):
    def boom(path):
        raise RuntimeError("PDF corrompu")

    monkeypatch.setitem(enrich_mod._EXTRACTORS, ".pdf", boom)
    df = _df([_item("dossier/rapport.pdf"), _item("dossier/photo.jpg")])
    out, report = enrich_descriptions(df, source_root)
    assert report.errors and "PDF corrompu" in report.errors[0]
    assert report.unsupported == 1  # le lot continue après l'erreur


def test_enrich_original_df_untouched(source_root, fake_extractors):
    df = _df([_item("dossier/rapport.pdf")])
    before = df.copy()
    enrich_descriptions(df, source_root)
    pd.testing.assert_frame_equal(df, before)


def test_enrich_progress_callback(source_root, fake_extractors):
    seen = []
    df = _df([_item("dossier/rapport.pdf")])
    enrich_descriptions(df, source_root, on_progress=seen.append)
    assert seen == ["dossier/rapport.pdf"]


def test_enrich_max_chars_truncates(source_root, monkeypatch):
    monkeypatch.setitem(
        enrich_mod._EXTRACTORS, ".pdf", lambda p: {"Extrait": "x" * 500}
    )
    df = _df([_item("dossier/rapport.pdf")])
    out, _ = enrich_descriptions(df, source_root, max_chars=50)
    desc = out.loc[0, "Content.Description"]
    assert len(desc) <= 50 and desc.endswith("…")


# ── Garde-fous unitaires ─────────────────────────────────────────────────────

def test_noise_titles_rejected():
    assert _is_noise_title("rapport.pdf", "rapport.pdf")
    assert _is_noise_title("rapport", "rapport.pdf")           # stem
    assert _is_noise_title("Microsoft Word - doc1", "x.docx")
    assert _is_noise_title("Sans titre", "x.docx")
    assert not _is_noise_title("Budget cantine 2022", "x.docx")


def test_plausible_snippet_rejects_garbled_text():
    assert _plausible_snippet("3$<*Y 05'=$1 9(2;&+*") == ""
    assert _plausible_snippet("  Compte   rendu\ndu conseil  ") == "Compte rendu du conseil"


def test_redact_emails_keeps_only_domain_with_placeholder():
    text = "Contact : jean.dupont@mairie-test.fr"
    assert _redact_emails(text) == "Contact : [email]@mairie-test.fr"


def test_redact_emails_handles_multiple_addresses():
    text = "De: a.b@ville.fr A: c.d@region.fr"
    assert _redact_emails(text) == "De: [email]@ville.fr A: [email]@region.fr"


def test_redact_emails_no_op_without_email():
    assert _redact_emails("Compte rendu du conseil") == "Compte rendu du conseil"


def test_clean_redacts_email_local_part():
    assert _clean("  Envoyé par jean.dupont@mairie-test.fr  ") == "Envoyé par [email]@mairie-test.fr"


def test_recurring_keywords_drops_email_local_part_and_placeholder_word():
    # "dupont" (nom de personne, partie locale de l'email) ne doit jamais
    # devenir un mot récurrent, même s'il apparaît plusieurs fois via une
    # signature répétée ; "mairie"/domaine reste un signal valide. Le mot du
    # placeholder ("email") ne doit pas non plus se faire passer pour un thème.
    text = (
        "jean.dupont@mairie-test.fr budget cantine budget "
        "jean.dupont@mairie-test.fr cantine"
    )
    keywords = _recurring_keywords(text)
    assert "dupont" not in keywords
    assert "email" not in keywords
    assert _plausible_snippet(None) == ""


def test_resolve_handles_windows_separators(tmp_path):
    assert _resolve(tmp_path, r".\dossier\fichier.pdf") == tmp_path / "dossier" / "fichier.pdf"


def test_format_description_joins_and_skips_empty():
    assert _format_description({"A": "1", "B": "", "C": "3"}, 100) == "A : 1 · C : 3"


def test_report_summary_lines():
    report = EnrichReport(total_items=4, enriched=2, missing=1, errors=["x : Err"])
    lines = report.summary_lines()
    assert any("2 description(s)" in line for line in lines)
    assert any("introuvable" in line for line in lines)
    assert any("1 erreur" in line for line in lines)


# ── Extraction intelligente : échantillonnage, thème, en-tête/pied de page ────

def test_sample_indices_full_range_when_small():
    assert _sample_indices(0) == []
    assert _sample_indices(2) == [0, 1]
    assert _sample_indices(3) == [0, 1, 2]


def test_sample_indices_begin_middle_end_when_large():
    assert _sample_indices(10) == [0, 5, 9]
    assert _sample_indices(101) == [0, 50, 100]


def test_windowed_indices_expands_around_anchors():
    assert _windowed_indices([5], 20, 2) == [3, 4, 5, 6, 7]
    # Bornes respectées, pas de débordement hors de [0, total).
    assert _windowed_indices([0, 19], 20, 2) == [0, 1, 2, 17, 18, 19]


def test_recurring_keywords_keeps_repeated_meaningful_words():
    text = "budget cantine budget scolaire cantine reunion budget"
    assert _recurring_keywords(text) == "budget, cantine"


def test_recurring_keywords_drops_stopwords_and_single_mentions():
    # "le"/"la"/"de"/"un" sont des mots vides ; "mot" n'apparaît qu'une fois.
    assert _recurring_keywords("le la de un mot") == ""


def test_recurring_keywords_empty_on_no_signal():
    assert _recurring_keywords("") == ""
    assert _recurring_keywords("   ") == ""


def test_detect_boilerplate_lines_flags_repeated_lines_only():
    texts = [
        "Mairie de Testville\nCompte rendu du conseil\npage 1",
        "Mairie de Testville\nBudget previsionnel\npage 2",
    ]
    boilerplate = _detect_boilerplate_lines(texts)
    assert "Mairie de Testville" in boilerplate
    assert "Compte rendu du conseil" not in boilerplate
    assert "Budget previsionnel" not in boilerplate


def test_detect_boilerplate_lines_needs_at_least_two_samples():
    assert _detect_boilerplate_lines(["Une seule page ici"]) == set()
    assert _detect_boilerplate_lines([]) == set()


def test_pick_content_title_prefers_styled_candidate_over_earlier_plain_one():
    candidates = [
        ("Introduction generale du document", ""),
        ("Bilan budgetaire 2022", "Heading 1"),
    ]
    assert _pick_content_title(candidates, "rapport.docx") == "Bilan budgetaire 2022"


def test_pick_content_title_falls_back_to_first_non_noise_plain_line():
    candidates = [("", ""), ("Sans titre", ""), ("Compte rendu de reunion", "")]
    assert _pick_content_title(candidates, "rapport.docx") == "Compte rendu de reunion"


def test_pick_content_title_rejects_garbled_text():
    # Régression : un PDF à encodage de police non standard peut produire une
    # première ligne de code brut illisible (« 3$<*Y ») — ne doit jamais finir
    # en « Titre (contenu) ».
    candidates = [("3$<*Y 05'=$1 9(2;&+*", "position")]
    assert _pick_content_title(candidates, "facture.pdf") == ""


def test_pick_content_title_skips_garbled_candidate_for_next_one():
    candidates = [("3$<*Y 05'=$1", "position"), ("Compte rendu de reunion", "position")]
    assert _pick_content_title(candidates, "rapport.pdf") == "Compte rendu de reunion"


def test_pick_content_title_empty_when_all_noise():
    assert _pick_content_title([("Sans titre", ""), ("", "Heading 1")], "rapport.docx") == ""


# ── Empreinte SHA-256 ────────────────────────────────────────────────────────

@pytest.fixture
def hashable_root(tmp_path):
    """Arborescence locale avec des contenus binaires connus (hash vérifiable)."""
    (tmp_path / "dossier").mkdir()
    (tmp_path / "copie").mkdir()
    # rapport.pdf et copie/rapport.pdf : contenu identique → même empreinte.
    for path in ("dossier/rapport.pdf", "copie/rapport.pdf"):
        (tmp_path / path).write_bytes(b"contenu identique")
    # autre.docx : contenu distinct.
    (tmp_path / "dossier" / "autre.docx").write_bytes(b"contenu different")
    # une image : hachée aussi (toutes extensions, pas seulement bureautiques).
    (tmp_path / "dossier" / "photo.jpg").write_bytes(b"\x89PNGfaux")
    return tmp_path


def test_fingerprint_computes_sha256(hashable_root):
    df = _df([_item("dossier/rapport.pdf")])
    out, report = fingerprint_files(df, hashable_root)
    expected = hashlib.sha256(b"contenu identique").hexdigest()
    assert out.loc[0, FINGERPRINT_COLUMN] == expected
    assert (report.total_items, report.hashed) == (1, 1)


def test_fingerprint_hashes_all_extensions(hashable_root):
    # Contrairement à l'extraction de texte, le hachage couvre .jpg (doublons
    # stricts possibles sur tout binaire).
    df = _df([_item("dossier/photo.jpg")])
    out, report = fingerprint_files(df, hashable_root)
    assert out.loc[0, FINGERPRINT_COLUMN] == hashlib.sha256(b"\x89PNGfaux").hexdigest()
    assert report.hashed == 1


def test_fingerprint_identical_content_same_hash(hashable_root):
    df = _df([
        _item("dossier/rapport.pdf"),
        _item("copie/rapport.pdf"),
        _item("dossier/autre.docx"),
    ])
    out, _ = fingerprint_files(df, hashable_root)
    assert out.loc[0, FINGERPRINT_COLUMN] == out.loc[1, FINGERPRINT_COLUMN]
    assert out.loc[2, FINGERPRINT_COLUMN] != out.loc[0, FINGERPRINT_COLUMN]


def test_fingerprint_skips_root_and_missing(hashable_root):
    df = _df([
        {"File": ".", "Content.DescriptionLevel": "RecordGrp",
         "Content.Title": "racine", "Content.Description": ""},
        _item("dossier/rapport.pdf"),
        _item("dossier/absent.pdf"),
    ])
    out, report = fingerprint_files(df, hashable_root)
    # La racine (RecordGrp) n'est jamais traitée ; l'absent est compté.
    assert report.total_items == 2
    assert report.hashed == 1
    assert report.missing == 1
    assert out.loc[2, FINGERPRINT_COLUMN] == ""


def test_fingerprint_preserves_existing_without_overwrite(hashable_root):
    df = _df([_item("dossier/rapport.pdf")])
    df[FINGERPRINT_COLUMN] = "deadbeef"
    out, report = fingerprint_files(df, hashable_root)
    assert out.loc[0, FINGERPRINT_COLUMN] == "deadbeef"
    assert report.already_hashed == 1 and report.hashed == 0

    out2, report2 = fingerprint_files(df, hashable_root, overwrite=True)
    assert out2.loc[0, FINGERPRINT_COLUMN] == hashlib.sha256(b"contenu identique").hexdigest()
    assert report2.hashed == 1


def test_fingerprint_original_df_untouched(hashable_root):
    df = _df([_item("dossier/rapport.pdf")])
    before = df.copy()
    fingerprint_files(df, hashable_root)
    pd.testing.assert_frame_equal(df, before)


def test_fingerprint_report_summary_lines():
    report = enrich_mod.FingerprintReport(total_items=3, hashed=2, missing=1)
    lines = report.summary_lines()
    assert any("2 empreinte(s)" in line for line in lines)
    assert any("introuvable" in line for line in lines)
