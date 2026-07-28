"""Consignes de classement ancrées au plan — moteur déterministe.

Deux volets, tous **sans LLM** :
  • `core.cla_directives` : modèle, lecture de fichier, rendu Markdown, dérivation
    d'`allowed_parents`, détection d'ancrages périmés ;
  • `convert_classement_to_resip(..., allowed_parents=…)` : création de
    sous-dossiers autorisée (rattachement au bon parent, numérotation de position,
    conformité `planMatches` préservée), et **non-régression** sans autorisation.
Plus la garde de prompt (byte-identique sans consigne) et la métrique.
"""
import pandas as pd
import pytest

from core.cla_directives import (
    Directive,
    allowed_parents,
    directives_from_rows,
    read_directives_file,
    render_directives,
    stale_anchors,
)
from core.csv_handler import REQUIRED_COLUMNS, convert_classement_to_resip
from core.evals import classement_metrics, directives_followed
from prompts import CLA_001

PLAN = """
## Arborescence technique

```text
1_Candidatures/
├── 1-1_AD92/
└── 1-6_Autres_employeurs/
2_Administratif/
```

## Préconisations
RAS.
"""

PLAN_FOLDERS = {"1_Candidatures", "1-1_AD92", "1-6_Autres_employeurs", "2_Administratif"}


def _original(items):
    root = {
        "ID": "1", "ParentID": "", "File": ".",
        "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Racine",
        "Content.StartDate": "", "Content.EndDate": "",
    }
    rows = [root]
    for i, (file, start, end) in enumerate(items, start=2):
        rows.append({
            "ID": str(i), "ParentID": "1", "File": file,
            "Content.DescriptionLevel": "Item", "Content.Title": file,
            "Content.StartDate": start, "Content.EndDate": end,
        })
    return pd.DataFrame(rows, columns=REQUIRED_COLUMNS)


def _llm(rows):
    return pd.DataFrame(rows, columns=["Path", "TargetFolder", "NewTitle"])


# ── Modèle & construction ────────────────────────────────────────────────────

def test_directives_from_rows_camel_and_snake_and_skips_empty():
    ds = directives_from_rows([
        {"folder": "1-6_Autres_employeurs", "text": "Regrouper", "allowCreation": True},
        {"folder": "", "text": "  Fonds  ", "allow_creation": False},
        {"folder": "x", "text": "   "},  # texte vide → ignorée
    ])
    assert len(ds) == 2
    assert ds[0] == Directive(text="Regrouper", folder="1-6_Autres_employeurs", allow_creation=True)
    assert ds[1] == Directive(text="Fonds", folder=None, allow_creation=False)


def test_read_directives_file(tmp_path):
    f = tmp_path / "consignes.txt"
    f.write_text(
        "# commentaire ignoré\n"
        "1-6_Autres_employeurs: un sous-dossier par employeur [+sous-dossiers]\n"
        "Nommer les fichiers en français\n"
        "\n"
        "Voir avec le service : cas particulier\n",  # « : » dans une phrase → fonds
        encoding="utf-8",
    )
    ds = read_directives_file(f)
    assert len(ds) == 3
    assert ds[0].folder == "1-6_Autres_employeurs" and ds[0].allow_creation
    assert "[+sous-dossiers]" not in ds[0].text
    assert ds[1].folder is None and not ds[1].allow_creation
    assert ds[2].folder is None  # le « : » d'une phrase n'est pas un ancrage


# ── allowed_parents / ancrages périmés ───────────────────────────────────────

def test_allowed_parents_anchored():
    ds = [Directive(text="t", folder="1-6_Autres_employeurs", allow_creation=True),
          Directive(text="t2", folder="1-1_AD92", allow_creation=False)]
    assert allowed_parents(ds, PLAN_FOLDERS) == {"1-6_Autres_employeurs"}


def test_allowed_parents_fonds_level_authorizes_everywhere():
    ds = [Directive(text="créer si besoin", folder=None, allow_creation=True)]
    assert allowed_parents(ds, PLAN_FOLDERS) == PLAN_FOLDERS


def test_allowed_parents_ignores_stale_anchor():
    ds = [Directive(text="t", folder="9-9_Inexistant", allow_creation=True)]
    assert allowed_parents(ds, PLAN_FOLDERS) == set()
    assert stale_anchors(ds, PLAN_FOLDERS) == ["9-9_Inexistant"]


def test_render_stale_anchor_becomes_fonds_directive():
    ds = [Directive(text="consigne", folder="9-9_Inexistant")]
    block = render_directives(ds, PLAN_FOLDERS)
    assert "9-9_Inexistant" not in block  # rattachement perdu → rendu en fonds
    assert "consigne" in block


# ── Prompt : byte-identique sans consigne ────────────────────────────────────

def test_prompt_byte_identical_without_directives():
    assert CLA_001.build_user_message("CSV", "PLAN") == \
        CLA_001.build_user_message("CSV", "PLAN", directives=None)
    assert CLA_001.build_user_message("CSV", "PLAN", directives="") == \
        CLA_001.build_user_message("CSV", "PLAN")
    assert CLA_001.build_system_prompt() == CLA_001.build_system_prompt(directives=False)


def test_prompt_carries_directives_block():
    block = render_directives(
        [Directive(text="Ranger par employeur", folder="1-6_Autres_employeurs", allow_creation=True)],
        PLAN_FOLDERS,
    )
    msg = CLA_001.build_user_message("CSV", PLAN, directives=block)
    assert "Ranger par employeur" in msg
    sysp = CLA_001.build_system_prompt(directives=True)
    assert "Création de sous-dossiers" in sysp


# ── Conversion : création autorisée ──────────────────────────────────────────

def test_creation_authorized_attaches_to_parent_not_root():
    df_o = _original([
        ("cv_dupont.pdf", "2020-01-01", "2020-01-01"),
        ("lm_dupont.pdf", "2020-02-01", "2020-02-01"),
        ("cv_martin.pdf", "2021-01-01", "2021-01-01"),
    ])
    df_l = _llm([
        ("cv_dupont.pdf", "1-6_Autres_employeurs/Dupont SA", "a.pdf"),
        ("lm_dupont.pdf", "1-6_Autres_employeurs/Dupont SA", "b.pdf"),
        ("cv_martin.pdf", "1-6_Autres_employeurs/Martin", "c.pdf"),
    ])
    df, warnings, stats = convert_classement_to_resip(
        df_l, df_o, PLAN, allowed_parents={"1-6_Autres_employeurs"}
    )
    created = stats["foldersCreatedAuthorized"]
    # Deux frères distincts, numérotation de position séquentielle.
    assert created == ["1-6-1_Dupont_SA", "1-6-2_Martin"]
    # Rattachés au parent réel, jamais à la racine.
    rg = {r["File"]: r for _, r in df.iterrows() if r["Content.DescriptionLevel"] == "RecordGrp"}
    parent_id = rg["1-6_Autres_employeurs"]["ID"]
    assert rg["1-6-1_Dupont_SA"]["ParentID"] == parent_id
    assert rg["1-6-2_Martin"]["ParentID"] == parent_id
    # Deux CV Dupont regroupés dans le même sous-dossier créé.
    items = {r["File"]: r for _, r in df.iterrows() if r["Content.DescriptionLevel"] == "Item"}
    assert items["cv_dupont.pdf"]["ParentID"] == rg["1-6-1_Dupont_SA"]["ID"]
    assert items["lm_dupont.pdf"]["ParentID"] == rg["1-6-1_Dupont_SA"]["ID"]
    # Conformité préservée : une création autorisée n'est pas un hors-plan.
    assert stats["foldersOffPlan"] == []
    assert stats["foldersCreatedParents"]["1-6-1_Dupont_SA"] == "1-6_Autres_employeurs"


def test_creation_authorized_keeps_plan_matches_true():
    """Sur un plan dont tous les dossiers reçoivent du contenu, la création
    autorisée n'introduit aucun écart : planMatches reste True."""
    plan = """## Arborescence technique
```text
1-6_Autres_employeurs/
```
"""
    df_o = _original([("cv.pdf", "2020-01-01", "2020-01-01")])
    df_l = _llm([("cv.pdf", "1-6_Autres_employeurs/Dupont", "a.pdf")])
    _, _, stats = convert_classement_to_resip(
        df_l, df_o, plan, allowed_parents={"1-6_Autres_employeurs"}
    )
    assert stats["foldersCreatedAuthorized"] == ["1-6-1_Dupont"]
    assert stats["foldersOffPlan"] == []
    assert stats["foldersMissing"] == []
    assert stats["planMatches"] is True


def test_creation_dates_propagate_to_created_and_ancestors():
    df_o = _original([
        ("a.pdf", "2020-01-01", "2020-01-01"),
        ("b.pdf", "2022-06-01", "2022-06-01"),
    ])
    df_l = _llm([
        ("a.pdf", "1-6_Autres_employeurs/Dupont", "a.pdf"),
        ("b.pdf", "1-6_Autres_employeurs/Dupont", "b.pdf"),
    ])
    df, _, stats = convert_classement_to_resip(
        df_l, df_o, PLAN, allowed_parents={"1-6_Autres_employeurs"}
    )
    rg = {r["File"]: (r["Content.StartDate"], r["Content.EndDate"])
          for _, r in df.iterrows() if r["Content.DescriptionLevel"] == "RecordGrp"}
    assert rg["1-6-1_Dupont"] == ("2020-01-01", "2022-06-01")
    # Le parent réel agrège aussi les dates du sous-dossier créé.
    assert rg["1-6_Autres_employeurs"] == ("2020-01-01", "2022-06-01")


def test_no_creation_without_authorization_stays_off_plan():
    """Sans autorisation, un dossier inventé reste un hors-plan (non-régression)."""
    df_o = _original([("cv.pdf", "2020-01-01", "2020-01-01")])
    df_l = _llm([("cv.pdf", "1-6_Autres_employeurs/Dupont", "a.pdf")])
    df, warnings, stats = convert_classement_to_resip(df_l, df_o, PLAN)  # pas d'allowed_parents
    assert stats["foldersCreatedAuthorized"] == []
    # Le chemin est réduit à la feuille « Dupont » → hors-plan, comme avant O.
    assert "Dupont" in stats["foldersOffPlan"]
    assert stats["planMatches"] is False


def test_authorization_only_under_designated_parent():
    """Une feuille sous un parent NON autorisé n'est pas créée."""
    df_o = _original([("x.pdf", "2020-01-01", "2020-01-01")])
    df_l = _llm([("x.pdf", "1-1_AD92/Sous", "a.pdf")])
    # autorisation portant sur un AUTRE dossier
    _, _, stats = convert_classement_to_resip(
        df_l, df_o, PLAN, allowed_parents={"1-6_Autres_employeurs"}
    )
    assert stats["foldersCreatedAuthorized"] == []
    assert "Sous" in stats["foldersOffPlan"]


def test_target_looking_like_a_file_is_never_created_as_subfolder():
    """Une feuille qui ressemble à un fichier n'est jamais promue en sous-dossier,
    même sous un parent autorisé : la garde porte sur la feuille **brute**, car
    l'assainissement écrase le point de l'extension (`facture.pdf` →
    `facture_pdf`) et la rendrait invisible."""
    df_o = _original([("x.pdf", "2020-01-01", "2020-01-01")])
    df_l = _llm([("x.pdf", "1-6_Autres_employeurs/facture.pdf", "a.pdf")])
    df, _, stats = convert_classement_to_resip(
        df_l, df_o, PLAN, allowed_parents={"1-6_Autres_employeurs"}
    )
    assert stats["foldersCreatedAuthorized"] == []
    assert stats["itemsMalformed"] == 1
    # Le fichier n'est jamais perdu : rattaché à la racine et signalé.
    root_id = df_o[df_o["File"] == "."].iloc[0]["ID"]
    items = {r["File"]: r for _, r in df.iterrows() if r["Content.DescriptionLevel"] == "Item"}
    assert items["x.pdf"]["ParentID"] == root_id


def test_created_name_avoids_collision_with_existing_plan_child():
    """Un enfant existant `1-1_AD92` sous `1_Candidatures` fait démarrer la
    numérotation des créations après lui."""
    plan = """## Arborescence technique
```text
1_Candidatures/
├── 1-1_AD92/
```
"""
    df_o = _original([("x.pdf", "2020-01-01", "2020-01-01")])
    df_l = _llm([("x.pdf", "1_Candidatures/Nouveau", "a.pdf")])
    _, _, stats = convert_classement_to_resip(
        df_l, df_o, plan, allowed_parents={"1_Candidatures"}
    )
    # 1-1 est pris → la création reçoit 1-2.
    assert stats["foldersCreatedAuthorized"] == ["1-2_Nouveau"]


def test_existing_plan_path_target_unchanged_by_resolution():
    """Un TargetFolder `parent/enfant` où l'enfant est un vrai dossier du plan
    reste résolu à l'enfant (comportement historique), même avec autorisation."""
    df_o = _original([("x.pdf", "2020-01-01", "2020-01-01")])
    df_l = _llm([("x.pdf", "1_Candidatures/1-1_AD92", "a.pdf")])
    df, _, stats = convert_classement_to_resip(
        df_l, df_o, PLAN, allowed_parents={"1_Candidatures"}
    )
    assert stats["foldersCreatedAuthorized"] == []
    items = {r["File"]: r for _, r in df.iterrows() if r["Content.DescriptionLevel"] == "Item"}
    rg = {r["File"]: r for _, r in df.iterrows() if r["Content.DescriptionLevel"] == "RecordGrp"}
    assert items["x.pdf"]["ParentID"] == rg["1-1_AD92"]["ID"]


# ── Métrique de suivi des consignes ──────────────────────────────────────────────────────────────

def test_classement_metrics_surfaces_created_count():
    stats = {"foldersCreatedAuthorized": ["1-6-1_Dupont", "1-6-2_Martin"], "itemsTotal": 3}
    assert classement_metrics(stats)["foldersCreated"] == 2
    assert classement_metrics({})["foldersCreated"] == 0


def test_directives_followed_exact_and_under():
    rows = [
        {"ID": "1", "ParentID": "", "File": ".", "Content.DescriptionLevel": "RecordGrp"},
        {"ID": "10", "ParentID": "1", "File": "1-6_Autres_employeurs", "Content.DescriptionLevel": "RecordGrp"},
        {"ID": "11", "ParentID": "10", "File": "1-6-1_Dupont", "Content.DescriptionLevel": "RecordGrp"},
        {"ID": "20", "ParentID": "11", "File": "cv.pdf", "Content.DescriptionLevel": "Item"},
        {"ID": "21", "ParentID": "10", "File": "autre.pdf", "Content.DescriptionLevel": "Item"},
    ]
    # cv.pdf doit être sous 1-6_Autres_employeurs (via le sous-dossier créé) → OK ;
    # autre.pdf attendu dans un dossier précis mais est ailleurs → miss.
    res = directives_followed(rows, [
        {"path": "cv.pdf", "expectedUnder": "1-6_Autres_employeurs"},
        {"path": "cv.pdf", "expectedFolder": "1-6-1_Dupont"},
        {"path": "autre.pdf", "expectedFolder": "1-6-1_Dupont"},
    ])
    assert res["total"] == 3
    assert res["followed"] == 2
    assert res["followedPct"] == pytest.approx(66.7)
    assert res["misses"][0]["path"] == "autre.pdf"
