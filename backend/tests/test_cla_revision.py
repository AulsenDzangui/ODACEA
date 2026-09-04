"""Révision conversationnelle du classement — moteur déterministe.

Trois volets, tous **sans LLM** :
  • `core.cla_revision` : modèle des tours, lecture de fichier, rendu du bloc
    (consignes + synthèse mesurée), bornes du préfixe stable ;
  • `csv_handler.classement_llm_csv(..., previous=…)` : report ligne à ligne du
    classement précédent en colonnes `PrevFolder`/`PrevTitle`, y compris quand ce
    classement a été produit en mode `Ref` (réhydratation `Ref→Path`) ;
  • `core.evals.revision_metrics` / `classement_metrics(previous_stats=…)` : la
    **stabilité** d'une révision (part du classement touchée) et les deltas.
Plus la garde de prompt : sans révision, CLA-001 est **byte-identique** à la 1.5.0.
"""
import pandas as pd

from core.cla_revision import (
    MAX_TURNS,
    RevisionTurn,
    read_revision_file,
    render_previous_synthesis,
    render_revision,
    turns_from_rows,
    turns_from_text,
)
from core.csv_handler import (
    REQUIRED_COLUMNS,
    classement_llm_csv,
    ensure_path_column,
    prepare_for_classement,
)
from core.evals import classement_metrics, revision_metrics
from prompts import CLA_001


def _original(files):
    rows = [{
        "ID": "1", "ParentID": "", "File": ".",
        "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Racine",
        "Content.StartDate": "", "Content.EndDate": "",
    }]
    for i, file in enumerate(files, start=2):
        rows.append({
            "ID": str(i), "ParentID": "1", "File": file,
            # Content.Title = nom de fichier (forme d'un export Archifiltre réel).
            "Content.DescriptionLevel": "Item", "Content.Title": file.rsplit("/", 1)[-1],
            "Content.StartDate": "2020-01-01", "Content.EndDate": "",
        })
    return pd.DataFrame(rows, columns=REQUIRED_COLUMNS)


def _prev(rows, columns=("Path", "TargetFolder", "NewTitle")):
    return pd.DataFrame(rows, columns=list(columns))


# ── Modèle & construction des tours ──────────────────────────────────────────

def test_turns_from_rows_aliases_and_skips_empty():
    turns = turns_from_rows([
        {"consigne": "Les CV vont dans 1-2"},
        {"text": "  Garder les dates  "},
        {"consigne": "   "},  # vide → ignorée
        {"autre": "bruit"},   # aucune clé reconnue → ignorée
    ])
    assert turns == [
        RevisionTurn(consigne="Les CV vont dans 1-2"),
        RevisionTurn(consigne="Garder les dates"),
    ]


def test_turns_are_bounded_to_the_most_recent():
    """L'historique ne doit jamais faire dériver le préfixe stable : on garde les
    tours les plus **récents** (les plus pertinents pour l'état courant)."""
    turns = turns_from_rows([{"consigne": f"c{i}"} for i in range(MAX_TURNS + 5)])
    assert len(turns) == MAX_TURNS
    assert turns[-1].consigne == f"c{MAX_TURNS + 4}"
    assert turns[0].consigne == "c5"


def test_turns_from_text_one_per_line_skips_comments():
    turns = turns_from_text("Consigne A\n\n# commentaire\n  Consigne B  ")
    assert [t.consigne for t in turns] == ["Consigne A", "Consigne B"]


def test_read_revision_file(tmp_path):
    path = tmp_path / "revision.txt"
    path.write_text("# à corriger\nLes CV dans 1-2\n\nNe pas dater les titres\n", encoding="utf-8")
    assert [t.consigne for t in read_revision_file(path)] == [
        "Les CV dans 1-2",
        "Ne pas dater les titres",
    ]


# ── Synthèse mesurée du run précédent ────────────────────────────────────────

def test_synthesis_reports_what_the_model_cannot_know():
    block = render_previous_synthesis(
        {
            "itemsTotal": 10, "itemsClassified": 8, "itemsUnclassified": 2,
            "foldersMissing": ["1-3_Vide"], "foldersOffPlan": ["Divers"],
            "itemsMalformed": 1, "extensionsFixed": 3,
        },
        ["avertissement 1", "avertissement 2"],
    )
    assert "10 au total, 8 classé(s), 2 non classé(s)" in block
    assert "`1-3_Vide`" in block
    assert "`Divers`" in block
    assert "malformé (1)" in block
    assert "corrigées automatiquement : 3" in block
    assert "relevés : 2" in block


def test_synthesis_empty_without_measurable_stats():
    assert render_previous_synthesis(None) == ""
    assert render_previous_synthesis({}) == ""
    assert render_previous_synthesis({"itemsTotal": 0}) == ""


def test_synthesis_omits_sections_with_nothing_to_say():
    block = render_previous_synthesis({"itemsTotal": 4, "itemsClassified": 4})
    assert "vides" not in block
    assert "absents du plan" not in block
    assert "non classé" not in block


def test_synthesis_folder_lists_are_bounded():
    """Sur un plan large, la liste ne doit pas faire exploser un préfixe O(1)."""
    block = render_previous_synthesis(
        {"itemsTotal": 1, "foldersMissing": [f"1-{i}_D" for i in range(40)]}
    )
    assert "et 28 autres" in block
    assert block.count("`1-") == 12


def test_synthesis_tolerates_garbage_stats():
    """Les stats viennent du client (front) : une valeur aberrante ne doit jamais
    faire tomber l'assemblage du prompt."""
    block = render_previous_synthesis(
        {"itemsTotal": "6", "itemsClassified": None, "foldersMissing": "pas-une-liste"}
    )
    assert "6 au total" in block
    assert "vides" not in block


# ── Rendu du bloc de révision ────────────────────────────────────────────────

def test_render_revision_single_turn_is_not_numbered():
    block = render_revision([RevisionTurn(consigne="Les CV dans 1-2")])
    assert "- Les CV dans 1-2" in block
    assert "tour" not in block


def test_render_revision_numbers_turns_and_marks_the_current_one():
    """Le modèle doit distinguer l'acquis (ne pas régresser) de la demande du jour."""
    block = render_revision([
        RevisionTurn(consigne="Les CV dans 1-2"),
        RevisionTurn(consigne="Ne pas dater les titres"),
    ])
    assert "- (tour 1) Les CV dans 1-2" in block
    assert "- (tour courant) Ne pas dater les titres" in block


def test_render_revision_carries_synthesis_and_is_empty_when_nothing():
    assert render_revision([], "") == ""
    assert "Résultat de votre classement précédent" in render_revision(
        [], render_previous_synthesis({"itemsTotal": 3, "itemsClassified": 3})
    )


def test_render_revision_is_bounded_like_the_history():
    block = render_revision([RevisionTurn(consigne=f"c{i}") for i in range(MAX_TURNS + 3)])
    assert block.count("\n- ") == MAX_TURNS
    assert "c0" not in block  # les tours les plus anciens sont tombés


# ── Garde de prompt ──────────────────────────────────────────────────────────

def test_prompt_byte_identical_without_revision():
    """Sans révision, CLA-001 doit être **byte-identique** à la version précédente
    — un canal opt-in ne change jamais le comportement par défaut."""
    assert CLA_001.build_system_prompt(revision=False) == CLA_001.build_system_prompt()
    base = CLA_001.build_user_message("csv", "plan")
    assert CLA_001.build_user_message("csv", "plan", revision=None) == base
    assert CLA_001.build_user_message("csv", "plan", revision="   ") == base


def test_prompt_carries_revision_block_and_stability_rule():
    system = CLA_001.build_system_prompt(revision=True)
    assert "# Révision d'un classement précédent" in system
    assert "PrevFolder" in system and "PrevTitle" in system
    assert "à l'identique" in system  # règle de stabilité
    user = CLA_001.build_user_message("csv", "plan", revision="**Révision :**\n- corriger")
    assert "**Révision :**" in user
    # Le bloc doit rester dans le préfixe stable mis en cache.
    assert user.index("**Révision :**") < user.index(CLA_001.CACHE_BOUNDARY)


def test_revision_channel_composes_with_directives_and_examples():
    system = CLA_001.build_system_prompt(examples=True, directives=True, revision=True)
    assert "# Exemples de classements validés" in system
    assert "# Consignes de classement de l'archiviste" in system
    assert "# Révision d'un classement précédent" in system
    user = CLA_001.build_user_message(
        "csv", "plan", examples="EX", directives="DIR", revision="REV"
    )
    assert user.index("EX") < user.index("DIR") < user.index("REV")


# ── Report du classement précédent ligne à ligne ─────────────────────────────

def test_previous_adds_prev_columns():
    items = prepare_for_classement(_original(["a/x.pdf", "a/y.pdf"]))
    csv = classement_llm_csv(
        items, previous=_prev([["a/x.pdf", "1-1_A", "X.pdf"]])
    )
    assert csv.splitlines()[0] == "Path;CurrentTitle;Date;PrevFolder;PrevTitle"
    assert "a/x.pdf;x.pdf;2020-01-01;1-1_A;X.pdf" in csv


def test_unclassified_item_gets_empty_prev_columns():
    """Un `Prev*` vide est un **signal** (« ce fichier n'avait pas été classé »),
    pas un trou : il doit arriver au modèle comme tel."""
    items = prepare_for_classement(_original(["a/x.pdf", "a/y.pdf"]))
    csv = classement_llm_csv(items, previous=_prev([["a/x.pdf", "1-1_A", "X.pdf"]]))
    assert "a/y.pdf;y.pdf;2020-01-01;;" in csv


def test_without_previous_the_input_is_unchanged():
    items = prepare_for_classement(_original(["a/x.pdf"]))
    base = classement_llm_csv(items)
    assert classement_llm_csv(items, previous=None) == base
    assert classement_llm_csv(items, previous=pd.DataFrame()) == base
    assert "Prev" not in base


def test_previous_produced_in_ref_mode_is_rehydrated_then_joined():
    """Un tour de révision peut basculer Path ⇄ Ref : la jointure passe toujours
    par `Path`, réhydraté depuis le CSV source."""
    original = _original(["a/x.pdf", "a/y.pdf"])
    # Ref 2 = second item de `prepare_for_classement` (ordre 1..N déterministe).
    previous_ref = _prev([["2", "1-1_A", "Y.pdf"]], columns=("Ref", "TargetFolder", "NewTitle"))
    previous = ensure_path_column(previous_ref, original)
    csv = classement_llm_csv(prepare_for_classement(original), previous=previous)
    assert "a/y.pdf;y.pdf;2020-01-01;1-1_A;Y.pdf" in csv
    assert "a/x.pdf;x.pdf;2020-01-01;;" in csv


def test_previous_columns_come_last_in_ref_mode_too():
    items = prepare_for_classement(_original(["a/x.pdf"]))
    csv = classement_llm_csv(
        items, ref_mode=True, previous=_prev([["a/x.pdf", "1-1_A", "X.pdf"]])
    )
    assert csv.splitlines()[0] == "Ref;Path;CurrentTitle;Date;PrevFolder;PrevTitle"


def test_duplicate_previous_paths_keep_the_last_decision():
    """Les lots sont réassemblés puis corrigés à la main : un chemin peut
    apparaître deux fois, la dernière décision fait foi."""
    items = prepare_for_classement(_original(["a/x.pdf"]))
    csv = classement_llm_csv(
        items,
        previous=_prev([["a/x.pdf", "1-1_A", "vieux.pdf"], ["a/x.pdf", "2_B", "neuf.pdf"]]),
    )
    assert "2_B;neuf.pdf" in csv
    assert "vieux.pdf" not in csv


# ── Métriques de révision ────────────────────────────────────────────────────

def test_revision_metrics_counts_only_what_changed():
    previous = [
        {"Path": "a.pdf", "TargetFolder": "1_A", "NewTitle": "A.pdf"},
        {"Path": "b.pdf", "TargetFolder": "1_A", "NewTitle": "B.pdf"},
        {"Path": "c.pdf", "TargetFolder": "1_A", "NewTitle": "C.pdf"},
    ]
    current = [
        {"Path": "a.pdf", "TargetFolder": "2_B", "NewTitle": "A.pdf"},   # déplacé
        {"Path": "b.pdf", "TargetFolder": "1_A", "NewTitle": "Bis.pdf"},  # renommé
        {"Path": "c.pdf", "TargetFolder": "1_A", "NewTitle": "C.pdf"},    # intact
    ]
    m = revision_metrics(current, previous)
    assert m["revisionCompared"] == 3
    assert m["revisionChanged"] == 2
    assert m["revisionChangedPct"] == 66.7
    assert m["revisionFolderChanged"] == 1
    assert m["revisionTitleChanged"] == 1


def test_revision_metrics_ignores_items_absent_from_the_previous_run():
    """Un fichier que le tour précédent n'avait pas classé n'est pas un
    « changement » : il n'y avait rien à changer."""
    m = revision_metrics(
        [{"Path": "a.pdf", "TargetFolder": "1_A", "NewTitle": "A.pdf"}],
        [],
    )
    assert m["revisionCompared"] == 0
    assert m["revisionChangedPct"] is None
    assert m["revisionNotInPrevious"] == 1


def test_classement_metrics_adds_deltas_only_with_a_previous_run():
    stats = {"itemsTotal": 10, "foldersMissing": ["x"], "itemsUnclassified": 1}
    assert "revisionUnclassifiedDelta" not in classement_metrics(stats)
    m = classement_metrics(
        stats, {"itemsTotal": 10, "foldersMissing": ["x", "y", "z"], "itemsUnclassified": 4}
    )
    assert m["revisionFoldersMissingDelta"] == -2  # négatif = la révision a réparé
    assert m["revisionUnclassifiedDelta"] == -3
