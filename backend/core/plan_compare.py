"""Comparaison structurelle de plans de classement (audit comparatif multi-plans).

Lancer AUD-001 N fois produit N variantes de plan (la stochasticité du modèle
suffit à les différencier). Ce module les compare de façon **déterministe et sans
LLM** pour aider l'archiviste à choisir : forme de chaque arbre (`plan_shape`) et
croisement des dossiers (communs à toutes les variantes / propres à une seule).

La présentation « côte à côte » appartient au front ; le moteur (contrainte
moteur unique) fournit la matière comparable. Comme pour les autres comparaisons
d'arborescence, les dossiers sont rapprochés par leur **libellé sémantique**
(préfixe numérique retiré, casse normalisée) : deux variantes peuvent numéroter
différemment un même dossier — c'est le concept qu'on compare, pas le préfixe.
"""
from __future__ import annotations

from core.csv_handler import parse_plan_tree

# `semantic_label` vit désormais dans core.evals (source unique, partagée avec
# la métrique de conservation) ; réexporté ici pour les consommateurs de la comparaison.
from core.evals import plan_shape, semantic_label

__all__ = ["semantic_label", "compare_plan_variants", "format_comparison_table"]


def _variant_metrics(plan: str) -> tuple[dict, set[str]]:
    """Forme structurelle d'une variante + ensemble de ses libellés de dossier."""
    tree = parse_plan_tree(plan)
    shape = plan_shape(tree)
    labels = {label for name in tree if (label := semantic_label(name))}
    metrics = {
        "planExtracted": bool(tree),
        "folders": shape["folders"],
        "depth": shape["depth"],
        "maxWidth": shape["maxWidth"],
        "leaves": shape["leaves"],
    }
    return metrics, labels


def compare_plan_variants(plans: list[str]) -> dict:
    """Compare N variantes de plan (textes du bloc « Arborescence technique »).

    Retourne un dict prêt pour JSON :
      * ``variants`` — par variante : `index`, forme (`folders`/`depth`/
        `maxWidth`/`leaves`), `planExtracted`, `folderLabels` (triés) et
        `uniqueFolders` (libellés présents dans cette variante et **aucune**
        autre) ;
      * ``comparison`` — `variantCount`, `commonFolders` (présents dans **toutes**
        les variantes non vides) + `commonFolderCount`, `allFolders` (union),
        `identical` (mêmes dossiers partout, au moins une variante non vide), et
        les amplitudes `folderCountRange`/`depthRange`/`leavesRange`.
    """
    variants: list[dict] = []
    label_sets: list[set[str]] = []
    for index, plan in enumerate(plans, start=1):
        metrics, labels = _variant_metrics(plan)
        metrics["index"] = index
        variants.append(metrics)
        label_sets.append(labels)

    for idx, labels in enumerate(label_sets):
        others: set[str] = set()
        for j, other in enumerate(label_sets):
            if j != idx:
                others |= other
        variants[idx]["folderLabels"] = sorted(labels)
        variants[idx]["uniqueFolders"] = sorted(labels - others)

    non_empty = [s for s in label_sets if s]
    common: set[str] = set(non_empty[0]) if non_empty else set()
    for s in non_empty[1:]:
        common &= s
    union: set[str] = set()
    for s in label_sets:
        union |= s
    identical = bool(non_empty) and all(s == non_empty[0] for s in label_sets)

    folder_counts = [v["folders"] for v in variants]
    depths = [v["depth"] for v in variants]
    leaves = [v["leaves"] for v in variants]

    def _range(values: list[int]) -> dict:
        return {"min": min(values), "max": max(values)} if values else {"min": 0, "max": 0}

    comparison = {
        "variantCount": len(plans),
        "commonFolders": sorted(common),
        "commonFolderCount": len(common),
        "allFolders": sorted(union),
        "identical": identical,
        "folderCountRange": _range(folder_counts),
        "depthRange": _range(depths),
        "leavesRange": _range(leaves),
    }
    return {"variants": variants, "comparison": comparison}


def format_comparison_table(result: dict) -> str:
    """Rendu texte lisible de la comparaison (stdout CLI) — sans dépendance."""
    from core.evals import format_table

    variants = result["variants"]
    comp = result["comparison"]
    rows = [
        [
            f"#{v['index']}",
            str(v["folders"]),
            str(v["depth"]),
            str(v["leaves"]),
            str(len(v["uniqueFolders"])),
        ]
        for v in variants
    ]
    table = format_table(
        ["Variante", "Dossiers", "Profondeur", "Feuilles", "Propres"], rows
    )
    lines = [table, ""]
    lines.append(f"Dossiers communs à toutes les variantes : {comp['commonFolderCount']}")
    if comp["commonFolders"]:
        lines.append("  " + ", ".join(comp["commonFolders"]))
    lines.append(
        "Variantes structurellement identiques : "
        + ("oui" if comp["identical"] else "non")
    )
    return "\n".join(lines)
