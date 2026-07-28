"""Plan de classement de référence.

Un *plan de référence* est une arborescence de dossiers **fournie par l'archiviste**
— importée sous forme de CSV Resip « dossiers seuls »
(`csv_handler.build_reference_tree_from_folders`) ou d'un fichier de bloc brut (CLI
`--reference-plan-file`) — exprimée dans le **bloc arborescence canonique** d'AUD-001
(titre descriptif « → » nom technique). On peut la fournir à l'audit comme
**contrainte** : « s'en inspirer » (`inspire`) ou « s'y conformer » (`conform`). La
bibliothèque de plans intégrés (scolarité/RH/marchés) a été retirée : la source
unique d'un référentiel est désormais l'import de l'archiviste.

Contrainte moteur unique : la **formulation** d'injection (le cadre « voici un
référentiel à suivre… ») vit ici, dans le moteur Python, **pas** dans le texte du
prompt AUD-001 (`prompts/AUD_001.py` reste inchangé). L'injection emprunte le
canal de la *note contextuelle de l'archiviste* (`observation`), que le prompt
système honore déjà (depuis la 1.1.0 : « Si une note contextuelle de
l'archiviste indique une préférence (approche, seuils, refonte libre), s'y
conformer : elle prime sur les règles ci-dessus ») — même modèle que l'enrichissement (contenu
injecté dans un canal déjà prévu par le prompt, sans modifier le prompt ni
`PROMPT_VERSION`). La
*qualité* de l'adhérence d'un modèle réel au référentiel relève d'une évaluation
(harnais d'évaluation, contrainte) ; le présent module n'en fournit que le matériau.
"""
from __future__ import annotations

from dataclasses import dataclass

# Les deux modes d'usage d'un plan de référence.
REFERENCE_MODES = ("inspire", "conform")
DEFAULT_REFERENCE_MODE = "inspire"


@dataclass(frozen=True)
class ReferencePlan:
    """Un plan de classement type, prêt à injecter dans l'audit.

    `tree` est le **bloc arborescence canonique** (titre descriptif « → » nom
    technique) tel qu'AUD-001 le produirait — fences ` ```text ` comprises.
    """

    id: str
    label: str
    service: str
    summary: str
    tree: str
    source: str = "custom"


def custom_reference_plan(tree: str, *, label: str = "Plan de référence fourni") -> ReferencePlan:
    """Construit un plan de référence à partir d'un bloc d'arborescence fourni par
    l'archiviste — soit un fichier de bloc brut (CLI `--reference-plan-file`), soit
    l'arborescence dérivée d'un CSV Resip « dossiers seuls »
    (`csv_handler.build_reference_tree_from_folders`, endpoint
    `POST /reference-plan/from-csv`). C'est désormais l'**unique** source d'un plan
    de référence : la bibliothèque de plans intégrés a été retirée."""
    return ReferencePlan(
        id="custom",
        label=label,
        service="(plan fourni par l'archiviste)",
        summary="Référentiel fourni par l'archiviste.",
        tree=tree.strip(),
        source="custom",
    )


def normalize_mode(mode: str | None) -> str:
    """Mode valide (`inspire`/`conform`), défaut `inspire`. Tolère None/casse."""
    candidate = (mode or DEFAULT_REFERENCE_MODE).strip().lower()
    return candidate if candidate in REFERENCE_MODES else DEFAULT_REFERENCE_MODE


# Formulation d'injection (cadre moteur, hors prompt). Deux registres :
#   inspire — référentiel indicatif, à adapter au fonds ;
#   conform — référentiel prescriptif, structure à conserver.
_MODE_HEADER = {
    "inspire": "à utiliser comme source d'inspiration",
    "conform": "à respecter (structure prescrite)",
}
_MODE_INSTRUCTION = {
    "inspire": (
        "Inspirez-vous de ce référentiel pour structurer le plan de classement, "
        "en l'adaptant au fonds réellement analysé : ajoutez, retirez ou renommez "
        "les rubriques selon les documents effectivement présents."
    ),
    "conform": (
        "Conformez-vous à la structure de ce référentiel : conservez ses rubriques "
        "et leur hiérarchie. N'ajoutez de dossier que pour les documents qui n'y "
        "trouveraient aucune place, et signalez toute rubrique du référentiel "
        "restée vide."
    ),
}


def render_reference_constraint(plan: ReferencePlan, mode: str) -> str:
    """Bloc texte injecté dans la note contextuelle de l'audit.

    Ne contient aucun appel au modèle : c'est du contexte que le prompt système
    d'AUD-001 honore déjà via la note de l'archiviste.
    """
    mode = normalize_mode(mode)
    return (
        f"Plan de classement de référence — {plan.service} "
        f"({_MODE_HEADER[mode]}) :\n\n"
        f"{plan.tree.strip()}\n\n"
        f"{_MODE_INSTRUCTION[mode]}"
    )


def compose_observation(note: str, plan: ReferencePlan | None, mode: str) -> str:
    """Combine la note de l'archiviste et la contrainte de plan de référence en
    une seule note contextuelle, transmise telle quelle à
    `AUD_001.build_user_message(observation=…)`. Sans plan, renvoie la note
    inchangée (aucun effet sans plan de référence)."""
    note = (note or "").strip()
    if plan is None:
        return note
    constraint = render_reference_constraint(plan, mode)
    return f"{note}\n\n{constraint}" if note else constraint
