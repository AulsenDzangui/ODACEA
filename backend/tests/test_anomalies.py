"""Catégorisation des anomalies de conversion — `core/anomalies.py`.

Les chaînes testées sont les messages **réels** produits par
`convert_classement_to_resip` (`core/csv_handler.py`). Cette suite est la garde
de non-régression du format : une évolution d'un message côté moteur doit être
répercutée dans `categorize_warnings` (et ici), plus jamais en TypeScript.
"""

from core.anomalies import categorize_warnings

WARNINGS = [
    "Fichier non classé (absent de la sortie LLM) : 'divers\\photo fete ecole.jpg'",
    "TargetFolder inconnu : '' pour 'cantine\\menu mars.pdf'",
    "Path introuvable dans l'original : 'invente\\fantome.pdf'",
    (
        "Sortie LLM malformée : TargetFolder '2024-01-01_liste.pdf' ressemble à un "
        "fichier, pas à un dossier du plan ; 'inscriptions\\liste eleves.xlsx' "
        "rattaché à la racine."
    ),
    "Dossier hors plan : '9_Invente' créé par le classement, absent du plan validé.",
    "Dossier du plan non réalisé : '2-2_Factures' (aucun contenu classé dedans).",
    (
        "2 NewTitle(s) corrigé(s) : extension réalignée sur celle du Path d'origine. "
        "Détails : `a\\b.docx` : `b.pdf` → `b.docx`; `c\\d.xlsx` : `d.csv` → `d.xlsx`"
    ),
    "Un message inattendu, format inconnu.",
]


def test_categorise_chaque_format() -> None:
    anomalies = categorize_warnings(WARNINGS)
    # La ligne-fleuve des extensions est éclatée : 2 anomalies.
    assert len(anomalies) == 9

    assert anomalies[0] == {
        "category": "nonClasse",
        "item": "divers\\photo fete ecole.jpg",
        "detail": "absent de la sortie LLM",
        "isItem": True,
    }
    assert anomalies[1]["category"] == "cibleInconnue"
    assert anomalies[1]["item"] == "cantine\\menu mars.pdf"
    assert anomalies[1]["detail"] == "cible vide"
    assert anomalies[2]["category"] == "pathIntrouvable"
    assert anomalies[2]["item"] == "invente\\fantome.pdf"
    assert anomalies[3]["category"] == "cibleMalformee"
    assert anomalies[3]["item"] == "inscriptions\\liste eleves.xlsx"
    assert "2024-01-01_liste.pdf" in anomalies[3]["detail"]
    assert anomalies[4]["category"] == "horsPlan"
    assert anomalies[4]["item"] == "9_Invente"
    assert anomalies[4]["isItem"] is False
    assert anomalies[5]["category"] == "nonRealise"
    assert anomalies[5]["item"] == "2-2_Factures"
    assert anomalies[6] == {
        "category": "extension",
        "item": "a\\b.docx",
        "detail": "b.pdf → b.docx",
        "isItem": True,
    }
    assert anomalies[7]["category"] == "extension"
    assert anomalies[7]["item"] == "c\\d.xlsx"
    # Format inconnu : conservé tel quel, jamais perdu.
    assert anomalies[8] == {
        "category": "autre",
        "item": "",
        "detail": "Un message inattendu, format inconnu.",
        "isItem": False,
    }


def test_sous_dossier_cree_autorise() -> None:
    # Le sous-dossier créé sous autorisation est une anomalie informative
    # (isItem False), catégorie dédiée, avec son parent en détail.
    msg = "Sous-dossier créé (autorisé) : '1-6-1_Dupont_SA' sous '1-6_Autres_employeurs'."
    [a] = categorize_warnings([msg])
    assert a["category"] == "sousDossierCree"
    assert a["item"] == "1-6-1_Dupont_SA"
    assert a["detail"] == "créé (autorisé) sous « 1-6_Autres_employeurs »"
    assert a["isItem"] is False


def test_cible_inconnue_avec_nom() -> None:
    [a] = categorize_warnings(["TargetFolder inconnu : 'Brouillon' pour 'x\\y.pdf'"])
    assert a["category"] == "cibleInconnue"
    assert a["detail"] == "cible « Brouillon »"


def test_controle_integrite_retombe_en_autre() -> None:
    # Le préfixe « Contrôle d'intégrité : » n'a pas de catégorie dédiée → autre,
    # message brut conservé (le front l'affiche déjà en alerte distincte).
    msg = "Contrôle d'intégrité : ligne orpheline (ParentID 42 introuvable)."
    [a] = categorize_warnings([msg])
    assert a == {"category": "autre", "item": "", "detail": msg, "isItem": False}


def test_liste_vide() -> None:
    assert categorize_warnings([]) == []


def test_ordre_preserve() -> None:
    anomalies = categorize_warnings(
        [
            "Dossier hors plan : '9_X' créé par le classement, absent du plan validé.",
            "Path introuvable dans l'original : 'a\\b.pdf'",
        ]
    )
    assert [a["category"] for a in anomalies] == ["horsPlan", "pathIntrouvable"]
