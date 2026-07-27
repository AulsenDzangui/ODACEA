"""Tests déterministes des consignes de classement (`core.cla_directives`) et de
leur effet sur la conversion RESIP — sans aucun appel LLM.

Deux volets :
- le **rendu** du bloc de consignes injecté dans CLA-001 (métadonnées seules) et
  la dérivation des dossiers à création autorisée ;
- la **conversion** : un `TargetFolder` en chemin `parent/Nouveau` est une
  création légitime *seulement* sous un parent autorisé — sinon le comportement
  historique (feuille seule) est strictement préservé.
"""
import pandas as pd

from core.cla_directives import (
    Directive,
    allowed_parents,
    directives_from_rows,
    read_directives_file,
    render_directives,
    stale_anchors,
)
from core.csv_handler import convert_classement_to_resip
from prompts import CLA_001

PLAN_VALIDE = """
## Arborescence technique

```text
1_Administratif/
├── 1-1_Courriers/
└── 1-2_Factures/
2_Technique/
```
"""

PLAN_FOLDERS = {"1_Administratif", "1-1_Courriers", "1-2_Factures", "2_Technique"}


def _original(paths):
    root = {
        "ID": "1", "ParentID": "", "File": ".",
        "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Racine",
        "Content.StartDate": "", "Content.EndDate": "",
    }
    rows = [root]
    for i, path in enumerate(paths, start=2):
        rows.append({
            "ID": str(i), "ParentID": "1", "File": path,
            "Content.DescriptionLevel": "Item", "Content.Title": path,
            "Content.StartDate": "2020-01-01", "Content.EndDate": "2020-01-01",
        })
    return pd.DataFrame(rows)


# ── Construction et rendu ────────────────────────────────────────────────────

def test_directives_from_rows_ignore_texte_vide_et_lit_camel_case():
    directives = directives_from_rows([
        {"text": "  ", "folder": "1-1_Courriers"},
        {"text": "un sous-dossier par employeur", "folder": " 1-2_Factures ",
         "allowCreation": True},
        {"text": "dater tous les fichiers"},
    ])
    assert directives == [
        Directive(text="un sous-dossier par employeur", folder="1-2_Factures",
                  allow_creation=True),
        Directive(text="dater tous les fichiers", folder=None, allow_creation=False),
    ]


def test_render_directives_sans_consigne_est_vide():
    assert render_directives([], PLAN_FOLDERS) == ""


def test_render_directives_separe_fonds_et_dossier_et_annonce_la_creation():
    block = render_directives(
        [
            Directive(text="dater tous les fichiers"),
            Directive(text="un dossier par employeur", folder="1-2_Factures",
                      allow_creation=True),
        ],
        PLAN_FOLDERS,
    )
    assert "- dater tous les fichiers" in block
    assert "Pour le dossier `1-2_Factures` : un dossier par employeur" in block
    assert "1-2_Factures/Nouveau_sous_dossier" in block


def test_render_directives_ancrage_perime_retombe_au_niveau_du_fonds():
    directive = Directive(text="regrouper par année", folder="9_Disparu")
    block = render_directives([directive], PLAN_FOLDERS)
    assert "- regrouper par année" in block
    assert "9_Disparu" not in block
    assert stale_anchors([directive], PLAN_FOLDERS) == ["9_Disparu"]


def test_allowed_parents_ancre_cible_et_fonds_ouvre_tout():
    assert allowed_parents(
        [Directive(text="x", folder="1-2_Factures", allow_creation=True)], PLAN_FOLDERS
    ) == {"1-2_Factures"}
    # Ancrage périmé : jamais d'autorisation sur un dossier inexistant.
    assert allowed_parents(
        [Directive(text="x", folder="9_Disparu", allow_creation=True)], PLAN_FOLDERS
    ) == set()
    # Consigne de fonds : autorisation partout.
    assert allowed_parents(
        [Directive(text="x", allow_creation=True)], PLAN_FOLDERS
    ) == PLAN_FOLDERS
    # Sans autorisation explicite : rien.
    assert allowed_parents([Directive(text="x", folder="1-2_Factures")], PLAN_FOLDERS) == set()


def test_read_directives_file(tmp_path):
    f = tmp_path / "consignes.txt"
    f.write_text(
        "# commentaire ignoré\n"
        "\n"
        "dater tous les fichiers\n"
        "1-2_Factures: un sous-dossier par employeur [+sous-dossiers]\n"
        "Attention : cette phrase contient deux points\n",
        encoding="utf-8",
    )
    directives = read_directives_file(f)
    assert directives == [
        Directive(text="dater tous les fichiers"),
        Directive(text="un sous-dossier par employeur", folder="1-2_Factures",
                  allow_creation=True),
        # « Attention » n'est pas un nom technique de dossier → consigne de fonds.
        Directive(text="Attention : cette phrase contient deux points"),
    ]


# ── Canal de prompt (additif) ────────────────────────────────────────────────

def test_prompt_inchange_sans_consignes():
    assert CLA_001.build_system_prompt() == CLA_001.SYSTEM_PROMPT
    assert CLA_001.build_user_message("csv", "plan", directives="") == (
        CLA_001.build_user_message("csv", "plan")
    )


def test_prompt_accueille_le_bloc_de_consignes():
    system = CLA_001.build_system_prompt(directives=True)
    assert "Consignes de classement de l'archiviste" in system
    assert system.index("Consignes de classement") < system.index("# Avis de classement")
    user = CLA_001.build_user_message("csv", "plan", directives="- consigne")
    assert "- consigne" in user
    assert user.index("- consigne") < user.index("**Fichiers à classer :**")


# ── Effet sur la conversion RESIP ────────────────────────────────────────────

def test_creation_autorisee_rattache_le_sous_dossier_a_son_parent():
    df_original = _original(["fact/a.pdf", "fact/b.pdf"])
    df_llm = pd.DataFrame([
        {"Path": "fact/a.pdf", "TargetFolder": "1-2_Factures/Mairie", "NewTitle": "a.pdf"},
        {"Path": "fact/b.pdf", "TargetFolder": "1-2_Factures/Mairie", "NewTitle": "b.pdf"},
    ])
    df, warnings, stats = convert_classement_to_resip(
        df_llm, df_original, PLAN_VALIDE, allowed_parents={"1-2_Factures"}
    )

    created = stats["foldersCreatedAuthorized"]
    assert created == ["1-2-1_Mairie"]
    assert stats["foldersCreatedParents"] == {"1-2-1_Mairie": "1-2_Factures"}
    # Une création autorisée n'est pas un écart au plan.
    assert stats["foldersOffPlan"] == []
    assert any("Sous-dossier créé (autorisé)" in w for w in warnings)

    rg = df[df["Content.DescriptionLevel"] == "RecordGrp"].set_index("File")
    # Le sous-dossier est rattaché à son parent, jamais à la racine.
    assert rg.loc["1-2-1_Mairie", "ParentID"] == rg.loc["1-2_Factures", "ID"]
    # Les deux fichiers du même ensemble y sont classés.
    items = df[df["Content.DescriptionLevel"] == "Item"]
    assert set(items["ParentID"]) == {rg.loc["1-2-1_Mairie", "ID"]}
    # La plage de dates remonte jusqu'au parent.
    assert rg.loc["1-2_Factures", "Content.StartDate"] == "2020-01-01"


def test_sans_autorisation_le_chemin_retombe_sur_la_feuille():
    """Comportement historique préservé : sans consigne, `parent/enfant` est réduit
    à sa feuille — un dossier inventé reste un hors-plan."""
    df_original = _original(["fact/a.pdf"])
    df_llm = pd.DataFrame([
        {"Path": "fact/a.pdf", "TargetFolder": "1-2_Factures/Mairie", "NewTitle": "a.pdf"},
    ])
    df, _, stats = convert_classement_to_resip(df_llm, df_original, PLAN_VALIDE)
    assert stats["foldersCreatedAuthorized"] == []
    assert stats["foldersOffPlan"] == ["Mairie"]
    assert stats["planMatches"] is False


def test_chemin_vers_un_dossier_reel_du_plan_reste_resolu_par_sa_feuille():
    df_original = _original(["c/a.pdf"])
    df_llm = pd.DataFrame([
        {"Path": "c/a.pdf", "TargetFolder": "1_Administratif/1-1_Courriers", "NewTitle": "a.pdf"},
    ])
    df, _, stats = convert_classement_to_resip(
        df_llm, df_original, PLAN_VALIDE, allowed_parents={"1_Administratif"}
    )
    assert stats["foldersCreatedAuthorized"] == []
    assert stats["foldersOffPlan"] == []
    rg = df[df["Content.DescriptionLevel"] == "RecordGrp"].set_index("File")
    item = df[df["Content.DescriptionLevel"] == "Item"].iloc[0]
    assert item["ParentID"] == rg.loc["1-1_Courriers", "ID"]


def test_freres_crees_recoivent_des_indices_distincts_apres_le_plan():
    df_original = _original(["a.pdf", "b.pdf"])
    df_llm = pd.DataFrame([
        {"Path": "a.pdf", "TargetFolder": "1_Administratif/Rectorat", "NewTitle": "a.pdf"},
        {"Path": "b.pdf", "TargetFolder": "1_Administratif/Prefecture", "NewTitle": "b.pdf"},
    ])
    _, _, stats = convert_classement_to_resip(
        df_llm, df_original, PLAN_VALIDE, allowed_parents={"1_Administratif"}
    )
    # Le plan occupe déjà 1-1 et 1-2 → les créations reprennent à 1-3.
    assert stats["foldersCreatedAuthorized"] == ["1-3_Prefecture", "1-4_Rectorat"]


def test_cible_ressemblant_a_un_fichier_n_est_jamais_creee():
    df_original = _original(["a.pdf"])
    df_llm = pd.DataFrame([
        {"Path": "a.pdf", "TargetFolder": "1-2_Factures/facture.pdf", "NewTitle": "a.pdf"},
    ])
    df, _, stats = convert_classement_to_resip(
        df_llm, df_original, PLAN_VALIDE, allowed_parents={"1-2_Factures"}
    )
    assert stats["foldersCreatedAuthorized"] == []
    assert stats["itemsMalformed"] == 1
    item = df[df["Content.DescriptionLevel"] == "Item"].iloc[0]
    assert item["ParentID"] == "1"  # rattaché à la racine, jamais perdu
