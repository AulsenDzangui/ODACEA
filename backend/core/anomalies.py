"""Triage des anomalies de conversion — catégorisation côté moteur.

Les avertissements de `convert_classement_to_resip` (`core/csv_handler.py`) sont
des chaînes en prose destinées à l'archiviste. Pour les présenter en tableau de
triage (groupées, filtrables, reliées à l'item), il faut les transformer en
anomalies **typées**. Cette catégorisation vit ici, dans le moteur, **à côté**
des chaînes qu'elle interprète — et non en TypeScript : le front ne fait que
présenter la liste structurée renvoyée par `/classement/finalize`
(`resip.anomalies`), conformément à la contrainte « moteur unique ». Toute
évolution du format d'un message dans `csv_handler.py` se répercute donc **ici
seulement**, dans le même langage et le même dépôt que la production des chaînes.

Les compteurs agrégés (combien de fichiers non classés, de cibles inconnues…)
n'ont **pas** besoin de cette analyse : ils sont déjà calculés à la source dans
le `stats` de `convert_classement_to_resip` (cf. commentaire « doublent les
avertissements texte pour être agrégeables sans re-parser »). Ce module ne sert
qu'au **détail par item** du tableau de triage. Tout format non reconnu retombe
en catégorie « autre », le message brut étant conservé (jamais perdu).
"""

from __future__ import annotations

import re
from typing import TypedDict


class Anomaly(TypedDict):
    """Anomalie typée — forme JSON consommée telle quelle par le front."""

    category: str
    item: str
    detail: str
    isItem: bool


# Catégories (alignées sur `web/lib/csv/anomalies.ts::AnomalyCategory`).
CATEGORIES = (
    "nonClasse",
    "cibleInconnue",
    "pathIntrouvable",
    "cibleMalformee",
    "horsPlan",
    "nonRealise",
    "sousDossierCree",
    "extension",
    "autre",
)

# Motifs ancrés sur les chaînes produites par `convert_classement_to_resip`.
# Chaque entrée construit une anomalie depuis le `re.Match`.
_NON_CLASSE = re.compile(r"Fichier non classé \(absent de la sortie LLM\) : '(.+)'")
_CIBLE_INCONNUE = re.compile(r"TargetFolder inconnu : '(.*)' pour '(.+)'")
_PATH_INTROUVABLE = re.compile(r"Path introuvable dans l'original : '(.+)'")
_CIBLE_MALFORMEE = re.compile(
    r"Sortie LLM malformée : TargetFolder '(.+)' ressemble à un fichier"
    r".*'(.+)' rattaché à la racine\."
)
_HORS_PLAN = re.compile(r"Dossier hors plan : '(.+)' créé par le classement.*")
_NON_REALISE = re.compile(
    r"Dossier du plan non réalisé : '(.+)' \(aucun contenu classé dedans\)\."
)
_SOUS_DOSSIER = re.compile(
    r"Sous-dossier créé \(autorisé\) : '(.+)' sous '(.+)'\."
)

# Ligne-fleuve des extensions corrigées → une anomalie par fichier.
_EXTENSION_SUMMARY = re.compile(r"\d+ NewTitle\(s\) corrigé\(s\).*?Détails : (.+)", re.DOTALL)
_EXTENSION_DETAIL = re.compile(r"`(.+?)` : `(.+?)` → `(.+?)`")


def _categorize_one(w: str) -> list[Anomaly]:
    """Catégorise un avertissement en une ou plusieurs anomalies typées."""
    ext = _EXTENSION_SUMMARY.fullmatch(w)
    if ext:
        out: list[Anomaly] = []
        for part in ext.group(1).split("; "):
            d = _EXTENSION_DETAIL.fullmatch(part)
            if d:
                out.append(
                    {
                        "category": "extension",
                        "item": d.group(1),
                        "detail": f"{d.group(2)} → {d.group(3)}",
                        "isItem": True,
                    }
                )
            else:
                out.append({"category": "extension", "item": "", "detail": part, "isItem": False})
        return out

    m = _NON_CLASSE.fullmatch(w)
    if m:
        return [
            {
                "category": "nonClasse",
                "item": m.group(1),
                "detail": "absent de la sortie LLM",
                "isItem": True,
            }
        ]

    m = _CIBLE_INCONNUE.fullmatch(w)
    if m:
        target = m.group(1)
        return [
            {
                "category": "cibleInconnue",
                "item": m.group(2),
                "detail": f"cible « {target} »" if target else "cible vide",
                "isItem": True,
            }
        ]

    m = _PATH_INTROUVABLE.fullmatch(w)
    if m:
        return [
            {
                "category": "pathIntrouvable",
                "item": m.group(1),
                "detail": "identifiant inconnu du CSV source",
                "isItem": True,
            }
        ]

    m = _CIBLE_MALFORMEE.fullmatch(w)
    if m:
        return [
            {
                "category": "cibleMalformee",
                "item": m.group(2),
                "detail": f"cible « {m.group(1)} » — rattaché à la racine",
                "isItem": True,
            }
        ]

    m = _HORS_PLAN.fullmatch(w)
    if m:
        return [
            {
                "category": "horsPlan",
                "item": m.group(1),
                "detail": "créé par le classement, absent du plan validé",
                "isItem": False,
            }
        ]

    m = _NON_REALISE.fullmatch(w)
    if m:
        return [
            {
                "category": "nonRealise",
                "item": m.group(1),
                "detail": "aucun contenu classé dedans",
                "isItem": False,
            }
        ]

    m = _SOUS_DOSSIER.fullmatch(w)
    if m:
        return [
            {
                "category": "sousDossierCree",
                "item": m.group(1),
                "detail": f"créé (autorisé) sous « {m.group(2)} »",
                "isItem": False,
            }
        ]

    # Format inconnu (ex. « Contrôle d'intégrité : … », « Arborescence technique
    # non trouvée… ») : conservé tel quel, jamais perdu.
    return [{"category": "autre", "item": "", "detail": w, "isItem": False}]


def categorize_warnings(warnings: list[str]) -> list[Anomaly]:
    """Transforme les avertissements de conversion en anomalies typées.

    L'ordre des avertissements est préservé ; la ligne-fleuve des extensions est
    éclatée en une anomalie par fichier corrigé.
    """
    out: list[Anomaly] = []
    for w in warnings:
        out.extend(_categorize_one(w))
    return out
