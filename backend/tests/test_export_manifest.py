"""Tests déterministes du manifeste d'arborescence modèle (`core.export_manifest`).

Le moteur dérive une arborescence de répertoires cible du **CSV RESIP produit** —
pur, déterministe, sans LLM. On vérifie : structure de l'arbre, liste de
répertoires, localisation des fichiers, plage de dates, déterminisme du tri,
robustesse (df vide / racine non marquée), rendu Markdown, et la garantie
« métadonnées seules ».
"""
import pandas as pd

from core.csv_handler import REQUIRED_COLUMNS, convert_classement_to_resip
from core.export_manifest import (
    MANIFEST_VERSION,
    build_tree_manifest,
    format_tree_manifest_markdown,
)

PLAN_VALIDE = """
## Arborescence technique

```text
1_Administratif/
├── 1-1_Courriers/
└── 1-2_Factures/
2_Technique/
```
"""


def _make_original(items):
    root = {
        "ID": "1", "ParentID": "", "File": ".",
        "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Racine",
        "Content.StartDate": "", "Content.EndDate": "",
    }
    rows = [root]
    for i, (file, title, start, end) in enumerate(items, start=2):
        rows.append({
            "ID": str(i), "ParentID": "1", "File": file,
            "Content.DescriptionLevel": "Item", "Content.Title": title,
            "Content.StartDate": start, "Content.EndDate": end,
        })
    return pd.DataFrame(rows, columns=REQUIRED_COLUMNS)


def _resip():
    df_original = _make_original([
        ("doc1.docx", "Courrier", "2020-01-01", "2020-06-01"),
        ("doc2.pdf", "Facture", "2019-01-01", "2019-12-31"),
        ("doc3.xlsx", "Plan", "2021-03-01", "2021-03-15"),
    ])
    df_llm = pd.DataFrame([
        ("doc1.docx", "1-1_Courriers", "Courrier Dupont.docx"),
        ("doc2.pdf", "1-2_Factures", "Facture 2019.pdf"),
        ("doc3.xlsx", "2_Technique", "Plan technique.xlsx"),
    ], columns=["Path", "TargetFolder", "NewTitle"])
    df_resip, _, _ = convert_classement_to_resip(df_llm, df_original, PLAN_VALIDE)
    return df_resip


# ── Structure ────────────────────────────────────────────────────────────────

def test_directories_list_is_the_target_folder_tree():
    m = build_tree_manifest(_resip(), generated_at="2026-06-15T00:00:00+00:00")
    assert m["directories"] == [
        "1_Administratif",
        "1_Administratif/1-1_Courriers",
        "1_Administratif/1-2_Factures",
        "2_Technique",
    ]


def test_summary_counts_folders_items_depth_and_span():
    m = build_tree_manifest(_resip())
    s = m["summary"]
    assert s["folders"] == 4
    assert s["items"] == 3
    assert s["maxDepth"] == 2
    # Plage temporelle = min/max sur tous les Items.
    assert s["startDate"] == "2019-01-01"
    assert s["endDate"] == "2021-03-15"


def test_items_carry_their_target_directory_and_model_name():
    m = build_tree_manifest(_resip())
    by_orig = {it["originalFile"]: it for it in m["items"]}
    assert by_orig["doc1.docx"]["dir"] == "1_Administratif/1-1_Courriers"
    assert by_orig["doc1.docx"]["name"] == "Courrier Dupont.docx"
    assert by_orig["doc1.docx"]["path"] == "1_Administratif/1-1_Courriers/Courrier Dupont.docx"
    assert by_orig["doc3.xlsx"]["dir"] == "2_Technique"


def test_tree_root_excluded_from_paths_and_nests_folders():
    m = build_tree_manifest(_resip())
    tree = m["tree"]
    assert tree["name"] == "."
    assert tree["path"] == ""
    admin = next(f for f in tree["folders"] if f["name"] == "1_Administratif")
    # Le parent agrège la plage de ses sous-dossiers (RESIP).
    assert admin["startDate"] == "2019-01-01"
    assert admin["endDate"] == "2020-06-01"
    sub = {f["name"] for f in admin["folders"]}
    assert sub == {"1-1_Courriers", "1-2_Factures"}


# ── Déterminisme ─────────────────────────────────────────────────────────────

def test_output_is_deterministic_regardless_of_row_order():
    df = _resip()
    shuffled = df.iloc[::-1].reset_index(drop=True)
    a = build_tree_manifest(df, generated_at="t")
    b = build_tree_manifest(shuffled, generated_at="t")
    assert a == b


# ── Robustesse ───────────────────────────────────────────────────────────────

def test_empty_dataframe_yields_empty_manifest():
    m = build_tree_manifest(pd.DataFrame(columns=REQUIRED_COLUMNS))
    assert m["directories"] == []
    assert m["items"] == []
    assert m["summary"]["folders"] == 0
    assert m["tree"]["name"] == "."


def test_root_without_dot_marker_falls_back_to_parentless_row():
    # Racine sans `File="."` : on retombe sur le premier nœud sans ParentID.
    df = pd.DataFrame([
        {"ID": "1", "ParentID": "", "File": "Fonds",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Fonds",
         "Content.StartDate": "", "Content.EndDate": ""},
        {"ID": "2", "ParentID": "1", "File": "a.txt",
         "Content.DescriptionLevel": "Item", "Content.Title": "A.txt",
         "Content.StartDate": "", "Content.EndDate": ""},
    ], columns=REQUIRED_COLUMNS)
    m = build_tree_manifest(df)
    assert m["tree"]["name"] == "Fonds"
    assert m["items"][0]["dir"] == ""


# ── Rendu Markdown ───────────────────────────────────────────────────────────

def test_markdown_renders_ascii_tree_and_directory_listing():
    m = build_tree_manifest(_resip(), generated_at="2026-06-15T00:00:00+00:00")
    md = format_tree_manifest_markdown(m)
    assert "# Arborescence de répertoires modèle ODACEA" in md
    assert f"(format v{MANIFEST_VERSION})" in md
    assert "```text" in md
    # Arbre ASCII : un dossier avec son titre descriptif, un fichier en feuille.
    assert "1_Administratif/  (Administratif)" in md
    assert "Courrier Dupont.docx" in md
    # Inventaire des répertoires modèle.
    assert "`1_Administratif/1-1_Courriers`" in md
    assert "## Répertoires modèle (4)" in md


def test_manifest_carries_no_document_content():
    """Garde : seules métadonnées (noms/titres/dates), jamais de contenu."""
    m = build_tree_manifest(_resip())
    md = format_tree_manifest_markdown(m)
    assert "métadonnées seules" in md.lower()
    # Les seuls champs textuels d'un item sont nom de fichier / titre / dates.
    for it in m["items"]:
        assert set(it.keys()) == {"dir", "path", "name", "originalFile", "startDate", "endDate"}
