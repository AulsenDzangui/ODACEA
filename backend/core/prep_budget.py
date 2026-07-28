"""Budget de profondeur d'entrée : recommandation d'échantillonnage par
taille de vrac.

AUD-001 ne reçoit pas forcément *tous* les fichiers : `prepare_for_llm` peut
**échantillonner** au plus `sample_items_n` Item par dossier parent (et blanchir
les dates des Item, redondantes avec le digest). Ces deux leviers bornent les
tokens d'entrée — au prix d'un fonds vu moins en détail. Le bon réglage dépend
de la **taille du vrac** : un petit fonds tient entier dans le contexte ; un gros
vrac doit être resserré.

Ce module fournit, à côté de l'estimation de tokens (`core.tokens`) et de coût
(`core.pricing`), une **recommandation de défaut par taille** — une table locale,
datée et éditable, dans le même esprit que la grille tarifaire. Surfacée par le
`--dry-run` de la CLI (avant de payer un run), elle aide l'archiviste à choisir un
budget d'entrée adapté.

> **Valeurs à valider/affiner via le harnais d'éval.** Les seuils et les
> `sampleN` ci-dessous sont des **défauts heuristiques** : l'apport réel de
> l'échantillonnage (et du nettoyage de dates) sur la *qualité* d'AUD-001 se
> mesure en faisant varier `sample_items_n` sur des modèles réels
> (`odacea eval --sweep-sample …`, cf. `evals/README.md`). Cette table est le
> point d'entrée à réviser une fois ces chiffres obtenus — elle n'est pas un
> changement de prompt (contrainte non concernée).
"""
from __future__ import annotations

# Date des seuils (affichée à côté de la recommandation). À mettre à jour avec les
# valeurs une fois la matrice d'éval réelle exécutée (cf. docstring).
BUDGET_TIERS_DATE = "2026-06-15"

# Nettoyage des dates d'Item recommandé par défaut, toutes tailles confondues :
# les plages de dates utiles à l'audit remontent déjà, agrégées, dans le digest
# déterministe — les dates par fichier sont surtout du bruit en tokens. (À mesurer
# aussi via le sweep d'éval ; recommandation constante en attendant.)
RECOMMENDED_CLEAN_DATES = True

# Paliers par **nombre d'Item** (fichiers) du vrac, du plus petit au plus grand.
# `maxItems=None` = palier de queue (sans borne haute). `sampleN=0` = aucun
# échantillonnage (tous les fichiers envoyés). À éditer ici (et `BUDGET_TIERS_DATE`).
BUDGET_TIERS: list[dict] = [
    {
        "maxItems": 200,
        "tier": "petit",
        "sampleN": 0,
        "rationale": (
            "petit vrac : envoyer tous les fichiers (aucun échantillonnage) — "
            "le modèle voit le fonds entier, le coût en tokens reste modeste"
        ),
    },
    {
        "maxItems": 1000,
        "tier": "moyen",
        "sampleN": 5,
        "rationale": (
            "vrac moyen : un échantillon de 5 fichiers par dossier suffit à "
            "caractériser chaque dossier sans envoyer toute la volumétrie"
        ),
    },
    {
        "maxItems": 5000,
        "tier": "grand",
        "sampleN": 3,
        "rationale": (
            "grand vrac : resserrer à 3 fichiers par dossier pour borner les "
            "tokens d'entrée tout en gardant un aperçu représentatif"
        ),
    },
    {
        "maxItems": None,
        "tier": "très grand",
        "sampleN": 2,
        "rationale": (
            "très grand vrac : 2 fichiers par dossier — l'essentiel de la "
            "structure passe par les noms de dossiers et le digest agrégé"
        ),
    },
]


def recommend_prep(item_count: int) -> dict:
    """Recommandation de préparation d'entrée pour un vrac de `item_count` Item.

    Retourne `{itemCount, tier, sampleN, cleanDates, rationale, tableDate}`.
    `sampleN=0` signifie « aucun échantillonnage » (tous les fichiers envoyés).
    """
    n = max(int(item_count or 0), 0)
    for tier in BUDGET_TIERS:
        if tier["maxItems"] is None or n <= tier["maxItems"]:
            return {
                "itemCount": n,
                "tier": tier["tier"],
                "sampleN": tier["sampleN"],
                "cleanDates": RECOMMENDED_CLEAN_DATES,
                "rationale": tier["rationale"],
                "tableDate": BUDGET_TIERS_DATE,
            }
    # Inatteignable (le dernier palier a maxItems=None), mais on reste défensif.
    last = BUDGET_TIERS[-1]
    return {
        "itemCount": n,
        "tier": last["tier"],
        "sampleN": last["sampleN"],
        "cleanDates": RECOMMENDED_CLEAN_DATES,
        "rationale": last["rationale"],
        "tableDate": BUDGET_TIERS_DATE,
    }


def _sample_label(sample_n: int) -> str:
    """« tous » pour 0 (pas d'échantillonnage), sinon « N/dossier »."""
    return "tous" if sample_n <= 0 else f"{sample_n}/dossier"


def format_budget_line(
    rec: dict, current_sample_n: int,
    current_tokens: int | None = None, recommended_tokens: int | None = None,
) -> str:
    """Ligne lisible pour le `--dry-run` : échantillon actuel vs recommandé pour
    la taille du vrac, avec le delta de tokens quand il est connu.

    `current_tokens`/`recommended_tokens` sont les estimations d'entrée aux deux
    réglages (facultatives) ; le delta n'est affiché que s'il est significatif.
    """
    current_label = _sample_label(current_sample_n)
    rec_n = rec["sampleN"]
    rec_label = _sample_label(rec_n)
    head = (
        f"Budget d'entrée : {rec['itemCount']} fichiers — vrac {rec['tier']} ; "
        f"échantillon actuel {current_label}"
    )
    if current_sample_n == rec_n:
        return f"{head} = recommandé ✓ ({rec['rationale']})"
    tail = f"recommandé {rec_label}"
    if current_tokens is not None and recommended_tokens is not None:
        delta = recommended_tokens - current_tokens
        if delta == 0:
            note = "volume d'entrée inchangé"
        else:
            note = f"{'+' if delta > 0 else '−'}{abs(delta)}"
        tail += f" → ~{recommended_tokens} tokens d'entrée ({note})"
    return f"{head} | {tail} ({rec['rationale']})"
