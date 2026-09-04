"""Révision conversationnelle du classement — l'archiviste relance
CLA-001 sur le **même fonds** en disant *ce qu'il faut corriger*, et le modèle
reçoit son propre classement précédent pour le réviser au lieu de repartir
aveugle.

**Principe : l'état remplace le transcript.** CLA-001 est sans état et découpé
en lots ; on ne peut pas empiler un historique de conversation. Un tour de
révision porte donc deux choses, et deux seulement :

1. **les décisions précédentes, en ligne** — chaque fichier du lot arrive avec
   deux colonnes de plus (``PrevFolder``/``PrevTitle``, cf.
   ``csv_handler.classement_llm_csv(previous=…)``). Le coût en contexte est
   proportionnel au **lot**, jamais au fonds : un vrac de 10 000 fichiers en
   lots de 400 coûte le même contexte par appel qu'un vrac de 400. Et le modèle
   n'a **aucune jointure** à faire (robuste pour les petits modèles locaux) ;
2. **un préfixe stable borné** — rendu ici : l'historique des consignes de
   révision (borné à ``MAX_TURNS``) + une **synthèse mesurée** du run précédent
   (dossiers du plan restés vides, dossiers hors plan, cibles malformées, non
   classés — listes bornées à ``MAX_LISTED``). Taille O(1) : elle ne dérive ni
   avec le nombre de fichiers, ni avec le nombre de tours.

Le bloc rendu se place **avant** ``CLA_001.CACHE_BOUNDARY``, donc dans le
préfixe mis en cache : il est constant d'un lot à l'autre, exactement comme
les canaux ``examples`` et ``directives`` dont ce module reprend le
patron.

Principe (contrainte « moteur unique ») : la **formulation** vit dans le moteur ;
``prompts/CLA_001.py`` ne fait qu'**accueillir** le bloc via un canal optionnel
(``revision=``). Sans révision, le prompt est **byte-identique** à la version
précédente.

**Distinction avec les consignes de classement** : une consigne
est une *instruction de classement ancrée au plan*, persistée et réinjectée à
chaque run ; une consigne de révision est une *correction relative au résultat
précédent*, attachée à un tour de dialogue. Deux canaux, deux natures.

**Métadonnées seules** : une consigne de révision est un texte rédigé
par l'archiviste ; la synthèse ne porte que des compteurs et des noms de
dossiers du plan. Jamais le contenu d'un document.

⚠️ **Contrainte** — accueillir une révision *modifie le prompt* :
``PROMPT_VERSION`` de CLA-001 est incrémenté et l'**efficacité** se mesure sur
modèles réels via le harnais d'évaluation (métriques ``revisionChangedPct`` et deltas,
`core.evals`). Le présent module et son câblage (CLI/API) sont **déterministes
et testés sans LLM**.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

# Bornes du préfixe stable. L'historique des consignes est borné comme celui de
# l'agent (`agt_agent.MAX_HISTORY_MESSAGES`) : au-delà, on garde les tours les
# **plus récents** (les plus pertinents pour l'état courant).
MAX_TURNS = 10
# Les listes de la synthèse (dossiers vides, hors plan) sont tronquées : sur un
# plan large elles feraient dériver un préfixe qui doit rester O(1).
MAX_LISTED = 12


@dataclass(frozen=True)
class RevisionTurn:
    """Une consigne de révision — ce que l'archiviste demande de corriger au vu
    du classement précédent (« les CV vont dans 1-2, pas dans 1-1 »)."""

    consigne: str


def turns_from_rows(rows: Iterable[Mapping[str, object]]) -> list[RevisionTurn]:
    """Construit les tours depuis des objets (API : clé ``consigne``, ou ``text``
    en tolérance). Ne retient que les consignes non vides et ne garde que les
    ``MAX_TURNS`` **derniers** tours (l'historique ne dérive jamais)."""
    alias = {"consigne": "consigne", "text": "consigne", "texte": "consigne"}
    out: list[RevisionTurn] = []
    for row in rows:
        consigne = ""
        for key, value in row.items():
            if alias.get(str(key).lower().replace("_", "")) == "consigne":
                consigne = str(value or "").strip()
                if consigne:
                    break
        if not consigne:
            continue
        out.append(RevisionTurn(consigne=consigne))
    return out[-MAX_TURNS:]


def read_revision_file(path: str | Path) -> list[RevisionTurn]:
    """Lit un fichier de consignes de révision (une par ligne). Lignes vides et
    lignes commençant par ``#`` (commentaires) ignorées. Lu en ``utf-8-sig``."""
    text = Path(path).read_text(encoding="utf-8-sig")
    rows: list[dict[str, object]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        rows.append({"consigne": line})
    return turns_from_rows(rows)


def turns_from_text(text: str) -> list[RevisionTurn]:
    """Construit les tours depuis un texte libre (une consigne par ligne) —
    forme CLI ``--revision "…"`` sans passer par un fichier."""
    rows = [
        {"consigne": line.strip()}
        for line in (text or "").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return turns_from_rows(rows)


def _listed(names: Iterable[str]) -> str:
    """Liste bornée, lisible : ``a`, `b`` … et N autres`` (jamais de dérive)."""
    items = [str(n) for n in names if str(n).strip()]
    shown = items[:MAX_LISTED]
    rendered = ", ".join(f"`{n}`" for n in shown)
    rest = len(items) - len(shown)
    if rest > 0:
        rendered += f" … et {rest} autre{'s' if rest > 1 else ''}"
    return rendered


def render_previous_synthesis(
    stats: Mapping[str, object] | None, warnings: Iterable[str] | None = None
) -> str:
    """Rend la **synthèse mesurée** du classement précédent, ou ``""`` s'il n'y a
    rien de mesurable.

    Passe-plat borné des compteurs déjà calculés **à la source** par
    ``convert_classement_to_resip`` (`stats`) — on ne re-dérive jamais un chiffre
    depuis les messages d'avertissement (même principe que `core.anomalies`).
    ``warnings`` n'est lu que pour son **nombre** : le détail relève du triage
    côté archiviste, pas du prompt.

    Ce sont les faits que le modèle ignore et qui pilotent la révision : ce qu'il
    a laissé vide, ce qu'il a inventé, ce qu'il n'a pas classé.
    """
    stats = stats or {}

    def _count(key: str) -> int:
        value = stats.get(key) if stats else None
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return 0
        try:
            return int(value)
        except ValueError:
            return 0

    def _names(key: str) -> list[str]:
        value = stats.get(key) if stats else None
        return [str(f) for f in value] if isinstance(value, (list, tuple, set)) else []

    total = _count("itemsTotal")
    if not total:
        return ""

    classified = _count("itemsClassified")
    unclassified = _count("itemsUnclassified")
    missing = _names("foldersMissing")
    off_plan = _names("foldersOffPlan")
    created = _names("foldersCreatedAuthorized")
    malformed = _count("itemsMalformed")
    fixed = _count("extensionsFixed")
    n_warnings = len(list(warnings or []))

    lines = [
        "**Résultat de votre classement précédent (constats mesurés) :**",
        f"- Fichiers : {total} au total, {classified} classé(s)"
        + (f", {unclassified} non classé(s)" if unclassified else ""),
    ]
    if missing:
        lines.append(
            f"- Dossiers du plan restés **vides** ({len(missing)}) : {_listed(missing)}"
        )
    if off_plan:
        lines.append(
            f"- Dossiers produits **absents du plan** ({len(off_plan)}) : {_listed(off_plan)}"
        )
    if created:
        lines.append(
            f"- Sous-dossiers créés sous autorisation ({len(created)}) : {_listed(created)}"
        )
    if malformed:
        lines.append(
            f"- Lignes à `TargetFolder` malformé ({malformed}) : un nom de fichier y "
            "avait été mis au lieu d'un nom de dossier"
        )
    if fixed:
        lines.append(f"- Extensions de fichier corrigées automatiquement : {fixed}")
    if n_warnings:
        lines.append(f"- Avertissements de conversion relevés : {n_warnings}")
    return "\n".join(lines)


def render_revision(turns: Iterable[RevisionTurn], synthesis: str = "") -> str:
    """Rend le bloc de révision (Markdown) injectable dans le user message de
    CLA-001, ou ``""`` s'il n'y a rien d'exploitable (ni consigne, ni synthèse).

    Structure : les consignes de l'archiviste (dans l'ordre des tours, le tour
    courant en dernier) **puis** la synthèse mesurée du run précédent. Les
    décisions ligne à ligne, elles, ne sont pas ici : elles voyagent dans les
    colonnes ``PrevFolder``/``PrevTitle`` de la liste des fichiers (après la
    frontière de cache), là où le modèle les lit sans jointure.
    """
    turns = list(turns)[-MAX_TURNS:]
    synthesis = (synthesis or "").strip()
    if not turns and not synthesis:
        return ""

    lines: list[str] = []
    if turns:
        lines.append(
            "**Révision demandée par l'archiviste (à respecter en priorité, "
            "dans le cadre du plan) :**"
        )
        if len(turns) == 1:
            lines.append(f"- {turns[0].consigne}")
        else:
            # Numéroter les tours rend l'ordre explicite : le dernier est la
            # demande courante, les précédents restent acquis (ne pas régresser).
            for i, turn in enumerate(turns, start=1):
                label = "tour courant" if i == len(turns) else f"tour {i}"
                lines.append(f"- ({label}) {turn.consigne}")
    if synthesis:
        if lines:
            lines.append("")
        lines.append(synthesis)
    return "\n".join(lines)
