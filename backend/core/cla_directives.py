"""Consignes de classement ancrées au plan — préconisations de
l'archiviste, **par dossier** du plan ou **au niveau du fonds**, réinjectées dans
un re-run CLA-001 du **même fonds** pour affiner le classement (« range les CV
et LM par employeur dans ce dossier »).

Principe (contrainte « moteur unique ») : la **formulation** du bloc de consignes
vit dans le moteur — comme `reference_plans.render_reference_constraint` et
`corrections.render_corrections_examples` — et non dans le texte du prompt.
`prompts/CLA_001.py` ne fait qu'**accueillir** le bloc via un canal optionnel
(`directives=`), au même titre que la note contextuelle d'AUD-001. Sans consigne,
le prompt est **byte-identique** à la version précédente.

**Métadonnées seules** : une consigne est un **texte rédigé par
l'archiviste** (+ éventuellement le nom technique d'un dossier du plan qu'elle
vise), jamais le contenu d'un document.

**Création de sous-dossiers autorisée** : une consigne peut porter
``allow_creation=True`` — elle **autorise** alors le classement à créer des
sous-dossiers sous le dossier visé (cas déclencheur : « un sous-dossier par
employeur », qui ne peut être pré-créé à la main). ``allowed_parents`` en dérive
l'ensemble des dossiers du plan sous lesquels ``convert_classement_to_resip`` doit
traiter un ``TargetFolder`` de la forme ``dossier/Nouveau_sous_dossier`` comme une
création légitime (rattachée au bon parent), et non comme un dossier hors plan.

⚠️ **Attention** — accueillir des consignes *modifie le prompt* (le modèle
reçoit un contenu nouveau) : ``PROMPT_VERSION`` de CLA-001 est incrémenté et
l'**efficacité** se mesure sur modèles réels via le harnais d'évaluation (métrique
``directivesFollowedPct``, `core.evals`). Le présent module et son câblage
(CLI/API) sont **déterministes et testés sans LLM**.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Directive:
    """Une consigne de classement.

    ``folder`` = nom technique d'un dossier du plan (ex. ``1-6_Autres_employeurs``)
    quand la consigne est **ancrée** ; ``None`` (ou vide) = consigne **au niveau
    du fonds** (globale). ``text`` = la préconisation rédigée par l'archiviste.
    ``allow_creation`` = autorise le classement à créer des sous-dossiers sous le
    dossier visé (au niveau du fonds : sous n'importe quel dossier du plan).
    """

    text: str
    folder: str | None = None
    allow_creation: bool = False


def _norm_folder(value: object) -> str | None:
    s = "" if value is None else str(value).strip()
    return s or None


def directives_from_rows(rows: Iterable[Mapping[str, object]]) -> list[Directive]:
    """Construit les consignes depuis des objets (API : clés camelCase
    ``folder``/``text``/``allowCreation``, ou snake_case). Ne retient que les
    consignes dont le **texte** est non vide (une consigne sans texte n'a aucune
    valeur d'instruction)."""
    alias = {
        "folder": "folder",
        "text": "text",
        "allowcreation": "allow_creation",
    }
    out: list[Directive] = []
    for row in rows:
        rec: dict[str, object] = {}
        for key, value in row.items():
            canon = alias.get(str(key).lower().replace("_", ""))
            if canon is not None:
                rec[canon] = value
        text = str(rec.get("text", "") or "").strip()
        if not text:
            continue
        out.append(
            Directive(
                text=text,
                folder=_norm_folder(rec.get("folder")),
                allow_creation=bool(rec.get("allow_creation", False)),
            )
        )
    return out


def read_directives_file(path: str | Path) -> list[Directive]:
    """Lit un fichier de consignes texte (une par ligne). Format :

    - ``dossier_technique: consigne`` → consigne **ancrée** au dossier ;
    - ``consigne`` (sans « : ») → consigne **au niveau du fonds** ;
    - un marqueur ``[+sous-dossiers]`` n'importe où dans la ligne autorise la
      création de sous-dossiers pour cette consigne (retiré du texte affiché) ;
    - lignes vides et lignes commençant par ``#`` (commentaires) ignorées.

    L'ancrage n'est reconnu que si le segment avant « : » ressemble à un nom
    technique de dossier (contient « _ », sans espace) — sinon la ligne entière
    est une consigne de fonds (un « : » peut apparaître dans une phrase).
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    rows: list[dict[str, object]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        allow = "[+sous-dossiers]" in line
        line = line.replace("[+sous-dossiers]", "").strip()
        folder: str | None = None
        body = line
        if ":" in line:
            head, rest = line.split(":", 1)
            head = head.strip()
            if head and "_" in head and " " not in head:
                folder = head
                body = rest.strip()
        if body:
            rows.append({"folder": folder, "text": body, "allow_creation": allow})
    return directives_from_rows(rows)


def allowed_parents(
    directives: Iterable[Directive], plan_folder_names: Iterable[str]
) -> set[str]:
    """Ensemble des dossiers du plan sous lesquels la création de sous-dossiers est
    autorisée, dérivé des consignes portant ``allow_creation``.

    - consigne **ancrée** (``folder``) avec autorisation → son dossier (s'il existe
      encore dans le plan — un ancrage périmé est ignoré, déjà signalé par
      ``stale_anchors``) ;
    - consigne **de fonds** avec autorisation → **tous** les dossiers du plan
      (l'archiviste a opté pour la création au niveau du fonds, sans cibler).

    Ne retourne que des noms présents dans ``plan_folder_names`` (garde forte pour
    ``convert_classement_to_resip`` : on n'autorise jamais une création sous un
    dossier inexistant).
    """
    plan = set(plan_folder_names)
    out: set[str] = set()
    for d in directives:
        if not d.allow_creation:
            continue
        if d.folder is None:
            return set(plan)  # fonds : création autorisée partout
        if d.folder in plan:
            out.add(d.folder)
    return out


def stale_anchors(
    directives: Iterable[Directive], plan_folder_names: Iterable[str]
) -> list[str]:
    """Noms de dossiers visés par une consigne ancrée mais **absents du plan
    courant** (plan réédité depuis la pose de la consigne). Signalés à
    l'archiviste, jamais ignorés en silence."""
    plan = set(plan_folder_names)
    seen: set[str] = set()
    out: list[str] = []
    for d in directives:
        if d.folder is not None and d.folder not in plan and d.folder not in seen:
            seen.add(d.folder)
            out.append(d.folder)
    return out


def render_directives(
    directives: Iterable[Directive], plan_folder_names: Iterable[str] | None = None
) -> str:
    """Rend le bloc de consignes (Markdown) injectable dans le user message de
    CLA-001, ou ``""`` s'il n'y a aucune consigne exploitable. **Métadonnées
    seules** : texte de l'archiviste (+ nom de dossier visé).

    Quand ``plan_folder_names`` est fourni, une consigne ancrée sur un dossier
    **absent** du plan est rendue comme consigne de fonds (rattachement perdu),
    son ancrage périmé étant par ailleurs signalé (``stale_anchors``)."""
    directives = list(directives)
    if not directives:
        return ""
    plan = set(plan_folder_names) if plan_folder_names is not None else None
    general: list[Directive] = []
    anchored: list[Directive] = []
    for d in directives:
        if d.folder is not None and (plan is None or d.folder in plan):
            anchored.append(d)
        else:
            general.append(d)

    lines = [
        "**Consignes de classement de l'archiviste (à respecter en priorité, "
        "dans le cadre du plan) :**"
    ]
    for d in general:
        suffix = ""
        if d.allow_creation:
            suffix = (
                " *(vous pouvez créer les sous-dossiers nécessaires sous les "
                "dossiers concernés : `TargetFolder` = `Dossier_du_plan/Nouveau_sous_dossier`)*"
            )
        lines.append(f"- {d.text}{suffix}")
    for d in anchored:
        if d.allow_creation:
            suffix = (
                f" *(vous pouvez créer des sous-dossiers sous `{d.folder}` : "
                f"`TargetFolder` = `{d.folder}/Nouveau_sous_dossier`, un nom court et parlant)*"
            )
        else:
            suffix = ""
        lines.append(f"- Pour le dossier `{d.folder}` : {d.text}{suffix}")
    return "\n".join(lines)
