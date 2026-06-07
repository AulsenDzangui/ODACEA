"""Scan déterministe des métadonnées d'un vrac (sans IA, sans contenu).

Calcule, à partir des *seules* métadonnées du CSV (chemins, extensions, niveaux),
les constats **purement mécaniques** d'un vrac — volumétrie et recensement des
formats — destinés à **ancrer** l'audit AUD-001.

Périmètre volontairement restreint : on ne fournit au modèle que ce qu'un script
calcule sans aucun risque d'erreur ni de jugement (compter des lignes, lister des
extensions, classer une extension dans une liste fixe « formats à risque » /
« compressés »). Tout ce qui relève de l'**analyse** — doublons, anomalies de
nommage, bruit numérique — est laissé au modèle : c'est sa valeur ajoutée, pas
celle d'un compteur. Le brider sur ces points dégraderait l'audit.

Pourquoi ancrer la volumétrie et les formats : un modèle local (typiquement 14B,
workflow on-prem d'ODACEA) compte et agrège mal sur des milliers de lignes (total
d'items, profondeur, top formats). Lui donner ces chiffres déterministes *faisant
autorité* supprime les hallucinations numériques et rend l'audit reproductible. La
partie calcul est entièrement déterministe (testable sans LLM) ; seule la
consommation du digest par le modèle est à valider en local.

Principe fondateur intangible : **métadonnées uniquement, jamais le contenu** des
documents.
"""
from __future__ import annotations

import re
from collections import Counter

import pandas as pd

# Formats bureautiques anciens/propriétaires à migrer (PDF/A, ODF…).
RISKY_FORMATS = {
    "doc", "xls", "ppt", "mdb", "accdb", "pub", "vsd", "wps", "wpd", "wri",
}
# Archives compressées : à décompresser ou intégrer comme dossiers virtuels.
COMPRESSED_FORMATS = {"zip", "rar", "7z", "gz", "tgz", "tar", "bz2", "cab", "arj"}


def _basename(path: str) -> str:
    return path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]


def _extension(path: str) -> str:
    """Extension en minuscules, sans le point. '' si absente ou nom caché sans ext."""
    name = _basename(path)
    if "." not in name or name.startswith(".") and name.count(".") == 1:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def _segments(path: str) -> list[str]:
    return [p for p in re.split(r"[\\/]+", path) if p and p != "."]


def scan_metadata(df: pd.DataFrame) -> dict:
    """Calcule les constats mécaniques sur les métadonnées d'un vrac.

    Retourne un dict structuré (volumétrie, formats). Robuste aux colonnes
    optionnelles absentes ; n'exploite jamais le contenu. Volontairement limité
    aux constats sans jugement : l'analyse (doublons, nommage, bruit) revient au
    modèle.
    """
    data = df.fillna("").astype(str)
    level = data["Content.DescriptionLevel"] if "Content.DescriptionLevel" in data.columns else pd.Series([], dtype=str)
    is_item = level == "Item"

    files = data["File"] if "File" in data.columns else pd.Series([""] * len(data))

    # ── Volumétrie ──────────────────────────────────────────────────────────
    item_count = int(is_item.sum()) if len(level) else 0
    rg_count = int((level == "RecordGrp").sum()) if len(level) else 0
    max_depth = max((len(_segments(f)) for f in files), default=0)

    # ── Formats (sur les Item uniquement) ───────────────────────────────────
    item_files = files[is_item] if len(level) else files

    ext_counter: Counter[str] = Counter(_extension(f) for f in item_files)
    top_formats = [
        (ext or "(sans extension)", n)
        for ext, n in ext_counter.most_common(10)
    ]
    risky = sorted(
        ((ext, n) for ext, n in ext_counter.items() if ext in RISKY_FORMATS),
        key=lambda kv: -kv[1],
    )
    compressed = sorted(
        ((ext, n) for ext, n in ext_counter.items() if ext in COMPRESSED_FORMATS),
        key=lambda kv: -kv[1],
    )

    return {
        "volumetry": {
            "items": item_count,
            "recordGrps": rg_count,
            "rows": len(data),
            "maxDepth": max_depth,
        },
        "formats": {"top": top_formats, "distinct": len(ext_counter)},
        "riskyFormats": risky,
        "compressedFormats": compressed,
    }


def format_digest(scan: dict) -> str:
    """Met en forme le scan en un bloc Markdown factuel et concis.

    Destiné à être injecté dans le message utilisateur AUD-001 comme source
    faisant autorité pour la volumétrie et les formats. Reste compact pour ne pas
    gonfler le contexte.
    """
    v = scan["volumetry"]
    lines: list[str] = []
    lines.append(
        f"- **Volumétrie** : {v['items']} Item, {v['recordGrps']} RecordGrp, "
        f"{v['rows']} lignes ; profondeur max {v['maxDepth']} niveaux."
    )

    f = scan["formats"]
    if f["top"]:
        top_str = ", ".join(f"{ext} ({n})" for ext, n in f["top"])
        lines.append(f"- **Formats** ({f['distinct']} distincts) — top : {top_str}.")

    if scan["riskyFormats"]:
        risky_str = ", ".join(f"{ext} ({n})" for ext, n in scan["riskyFormats"])
        lines.append(f"- **Formats à risque** : {risky_str}.")
    else:
        lines.append("- **Formats à risque** : aucun détecté.")

    if scan["compressedFormats"]:
        comp_str = ", ".join(f"{ext} ({n})" for ext, n in scan["compressedFormats"])
        lines.append(f"- **Archives compressées** : {comp_str}.")

    return "\n".join(lines)
