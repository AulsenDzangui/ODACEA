"""Apprentissage des corrections — réinjection des corrections manuelles
 comme exemples *few-shot* dans un re-run CLA-001 du **même fonds**
(« ces N fichiers ont été reclassés ainsi, appliquer la même logique »).

Principe (contrainte « moteur unique ») : la **formulation** du bloc d'exemples
vit dans le moteur — comme `reference_plans.render_reference_constraint` —
et non dans le texte du prompt. `prompts/CLA_001.py` ne fait qu'**accueillir** le
bloc via un canal optionnel (`examples=`), au même titre que la note contextuelle
de l'archiviste pour AUD-001.

**Métadonnées seules** : un exemple ne porte que le chemin source
(`Path`), le dossier cible retenu (`TargetFolder`) et le nouveau nom normalisé
(`NewTitle`) — jamais le contenu d'un document. C'est exactement le format de
sortie de CLA-001 (donc d'une correction). Garde-fou testé.

⚠️ **Attention** — injecter des exemples *modifie le prompt* (le modèle
reçoit un contenu nouveau). L'**efficacité** de ce few-shot se mesure sur modèles
réels via le harnais d'évaluation (expérience (a) du `evals/README.md`). Le présent
module et son câblage (CLI/API) sont **déterministes et testés sans LLM** ;
l'adoption en production attend les chiffres avant/après.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

import pandas as pd

# Colonnes d'une correction = format de sortie CLA-001. Métadonnées seules.
CORRECTION_COLUMNS = ("Path", "TargetFolder", "NewTitle")

# Few-shot **compact** : on borne le nombre d'exemples injectés (coût de tokens
# maîtrisé, signal lisible). Au-delà, on échantillonne en couvrant le plus de
# dossiers cibles distincts possible — le signal de « logique de classement » le
# plus riche pour le modèle.
MAX_EXAMPLES = 12


def read_corrections_file(path: str | Path) -> pd.DataFrame:
    """Lit un fichier de corrections (CSV `Path;TargetFolder;NewTitle`, p. ex. un
    export). Séparateur auto-détecté, tout en texte, NA non interprétés."""
    df = pd.read_csv(
        path, sep=None, engine="python", dtype=str, keep_default_na=False
    )
    return normalize_corrections(df)


def corrections_from_rows(rows: Iterable[Mapping[str, object]]) -> pd.DataFrame:
    """Construit les corrections depuis des objets (API : clés camelCase
    `path`/`targetFolder`/`newTitle`, ou déjà `Path`/`TargetFolder`/`NewTitle`)."""
    # Tolère camelCase (`targetFolder`) comme snake_case (`target_folder`) : on
    # rapproche les clés en ignorant la casse et les `_`.
    alias = {
        "path": "Path", "targetfolder": "TargetFolder", "newtitle": "NewTitle",
    }
    records: list[dict[str, str]] = []
    for row in rows:
        rec: dict[str, str] = {}
        for key, value in row.items():
            canon = alias.get(str(key).lower().replace("_", ""))
            if canon is not None:
                rec[canon] = "" if value is None else str(value)
        records.append(rec)
    df = pd.DataFrame(records, columns=list(CORRECTION_COLUMNS))
    return normalize_corrections(df)


def normalize_corrections(df: pd.DataFrame) -> pd.DataFrame:
    """Restreint aux colonnes d'une correction (**métadonnées seules** — toute
    autre colonne, p. ex. un contenu, est écartée), nettoie les espaces et ne
    garde que les lignes exploitables (chemin **et** dossier cible présents)."""
    missing = [c for c in CORRECTION_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            "Corrections : colonnes manquantes "
            + ", ".join(missing)
            + " (attendu : Path;TargetFolder;NewTitle)."
        )
    out = df.loc[:, list(CORRECTION_COLUMNS)].copy()
    for col in CORRECTION_COLUMNS:
        out[col] = out[col].fillna("").astype(str).str.strip()
    # Une correction n'a de valeur d'exemple que si la source et la cible sont
    # connues ; le NewTitle peut rester vide (le modèle le re-normalisera).
    out = out[(out["Path"] != "") & (out["TargetFolder"] != "")]
    return out.reset_index(drop=True)


def select_examples(
    df: pd.DataFrame, *, max_examples: int = MAX_EXAMPLES
) -> list[dict[str, str]]:
    """Sélectionne au plus `max_examples` corrections, **déterministe**, en
    couvrant d'abord le plus de dossiers cibles **distincts** (un exemple par
    cible dans l'ordre d'apparition), puis en complétant dans l'ordre. Maximise
    la diversité de la logique de classement montrée au modèle."""
    rows = df.to_dict("records")
    if max_examples <= 0 or not rows:
        return []
    primary: list[dict[str, str]] = []
    fillers: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        target = str(row["TargetFolder"])
        bucket = primary if target not in seen else fillers
        bucket.append({c: str(row[c]) for c in CORRECTION_COLUMNS})
        seen.add(target)
    return (primary + fillers)[:max_examples]


def render_corrections_examples(
    df: pd.DataFrame, *, max_examples: int = MAX_EXAMPLES
) -> str:
    """Rend le bloc d'exemples few-shot (Markdown) injectable dans le user message
    de CLA-001, ou `""` s'il n'y a aucune correction exploitable. **Métadonnées
    seules** : chemin source → dossier cible (+ nom normalisé). Normalise
    défensivement (idempotent) — la garde « métadonnées seules » tient quelle que
    soit la provenance du DataFrame."""
    examples = select_examples(normalize_corrections(df), max_examples=max_examples)
    if not examples:
        return ""
    lines = [
        "**Exemples de classements déjà validés par l'archiviste sur ce fonds "
        "(appliquez la même logique aux fichiers similaires) :**"
    ]
    for ex in examples:
        line = f"- `{ex['Path']}` → dossier `{ex['TargetFolder']}`"
        if ex["NewTitle"]:
            line += f" ; nom `{ex['NewTitle']}`"
        lines.append(line)
    return "\n".join(lines)
