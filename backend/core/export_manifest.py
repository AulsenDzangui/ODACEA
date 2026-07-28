"""Manifeste d'arborescence modèle — export au-delà du CSV.

À partir du **CSV RESIP produit** par le classement (`convert_classement_to_resip`),
ce module dérive une **arborescence de répertoires modèle** : la structure de
dossiers cible (RecordGrp) et la localisation de chaque fichier reclassé. C'est
une **vue déterministe du SIP produit**, exploitable de deux façons par
l'archiviste :

- comme **document de vérification** (relire la structure cible sans ouvrir le
  CSV ligne à ligne) ;
- comme **modèle de répertoires** à matérialiser sur disque, que RESIP sait
  importer par glisser-déposer d'un dossier (voir la documentation d'export pour
  l'étude des formats d'import RESIP et la décision de périmètre).

Moteur **pur, déterministe, sans LLM ni I/O** — consommé par la CLI
(`odacea {classement,run} … --manifest FICHIER`) et l'API (`POST /manifest`).
**Métadonnées seules** : le manifeste ne porte que des noms de dossiers,
des titres et des dates — jamais le contenu des documents.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

# Version du *format* du manifeste (distincte de PROMPT_VERSION) : à incrémenter
# si la structure du document change, pour qu'un manifeste archivé reste
# interprétable.
MANIFEST_VERSION = "1"


def _safe(value: object) -> str:
    """Texte propre d'une cellule (None / NaN → chaîne vide)."""
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _span(dates: list[tuple[str, str]]) -> tuple[str, str]:
    """Plage (min start, max end) à partir de couples de dates non vides."""
    starts = [s for s, _ in dates if s]
    ends = [e for _, e in dates if e]
    return (min(starts) if starts else "", max(ends) if ends else "")


def build_tree_manifest(df_resip: pd.DataFrame, *, generated_at: str | None = None) -> dict:
    """Construit le manifeste structuré (JSON-ready, camelCase) du SIP produit.

    `df_resip` est le DataFrame RESIP canonique (sortie de
    `convert_classement_to_resip`) : colonnes `ID`/`ParentID`/`File`/
    `Content.DescriptionLevel`/`Content.Title`/`Content.StartDate`/`Content.EndDate`.
    La racine (`File="."`, `ParentID` vide) n'apparaît pas dans les chemins de
    répertoires. Les dossiers sont triés par nom technique, les fichiers par
    titre — sortie déterministe.
    """
    rows = [r for _, r in df_resip.iterrows()]
    by_id: dict[str, dict] = {}
    children: dict[str, list[str]] = {}
    parentless: list[str] = []  # candidats racine (ParentID vide), dans l'ordre

    for r in rows:
        rid = _safe(r.get("ID"))
        pid = _safe(r.get("ParentID"))
        if not rid:
            continue
        by_id[rid] = r
        children.setdefault(rid, [])
        children.setdefault(pid, []).append(rid)
        if not pid:
            parentless.append(rid)

    # Racine : on préfère le marqueur Archifiltre/RESIP (`File="."`), sinon le
    # premier nœud sans parent.
    root_id: str | None = next(
        (rid for rid in parentless if _safe(by_id[rid].get("File")) == "."),
        parentless[0] if parentless else None,
    )

    directories: list[str] = []
    items: list[dict] = []
    folder_count = 0
    item_count = 0
    max_depth = 0

    def _build_node(node_id: str, prefix: str, depth: int) -> dict:
        nonlocal folder_count, item_count, max_depth
        row = by_id[node_id]
        name = _safe(row.get("File"))
        title = _safe(row.get("Content.Title"))
        # Chemin de répertoire relatif (la racine "." n'y figure pas).
        is_root = depth == 0
        path = "" if is_root else (f"{prefix}/{name}" if prefix else name)
        if not is_root:
            folder_count += 1
            directories.append(path)
            max_depth = max(max_depth, depth)

        kids = children.get(node_id, [])
        child_folders: list[dict] = []
        child_items: list[dict] = []
        for cid in kids:
            crow = by_id.get(cid)
            if crow is None:
                continue
            level = _safe(crow.get("Content.DescriptionLevel"))
            if level == "Item":
                item_count += 1
                entry = {
                    "name": _safe(crow.get("Content.Title")),
                    "originalFile": _safe(crow.get("File")),
                    "startDate": _safe(crow.get("Content.StartDate")),
                    "endDate": _safe(crow.get("Content.EndDate")),
                }
                child_items.append(entry)
                items.append({
                    "dir": path,
                    "path": f"{path}/{entry['name']}" if path else entry["name"],
                    **entry,
                })
            else:
                child_folders.append(_build_node(cid, path, depth + 1))

        child_folders.sort(key=lambda n: n["name"])
        child_items.sort(key=lambda e: (e["name"], e["originalFile"]))
        return {
            "name": name,
            "title": title,
            "level": _safe(row.get("Content.DescriptionLevel")) or "RecordGrp",
            "path": path,
            "startDate": _safe(row.get("Content.StartDate")),
            "endDate": _safe(row.get("Content.EndDate")),
            "folders": child_folders,
            "items": child_items,
        }

    if root_id is not None:
        tree = _build_node(root_id, "", 0)
    else:
        tree = {
            "name": ".", "title": "", "level": "RecordGrp", "path": "",
            "startDate": "", "endDate": "", "folders": [], "items": [],
        }

    directories.sort()
    items.sort(key=lambda e: (e["dir"], e["name"], e["originalFile"]))
    span = _span([(it["startDate"], it["endDate"]) for it in items])

    return {
        "tool": "ODACEA",
        "manifestVersion": MANIFEST_VERSION,
        "generatedAt": generated_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": {
            "folders": folder_count,
            "items": item_count,
            "maxDepth": max_depth,
            "startDate": span[0],
            "endDate": span[1],
        },
        "directories": directories,
        "items": items,
        "tree": tree,
    }


def _render_tree_lines(node: dict, prefix: str, is_last: bool, is_root: bool) -> list[str]:
    """Rend récursivement un nœud en arbre ASCII (style `tree`)."""
    lines: list[str] = []
    if is_root:
        lines.append(".")
    else:
        connector = "└── " if is_last else "├── "
        label = f"{node['name']}/"
        title = node.get("title")
        if title and title != node["name"]:
            label += f"  ({title})"
        lines.append(f"{prefix}{connector}{label}")

    child_prefix = prefix if is_root else prefix + ("    " if is_last else "│   ")
    folders = node.get("folders", [])
    item_entries = node.get("items", [])
    entries: list[tuple[str, dict]] = [("folder", f) for f in folders] + [("item", i) for i in item_entries]
    for idx, (kind, child) in enumerate(entries):
        last = idx == len(entries) - 1
        if kind == "folder":
            lines += _render_tree_lines(child, child_prefix, last, is_root=False)
        else:
            connector = "└── " if last else "├── "
            lines.append(f"{child_prefix}{connector}{child['name']}")
    return lines


def format_tree_manifest_markdown(manifest: dict) -> str:
    """Rend le manifeste en Markdown lisible — le document exporté.

    Pendant déterministe de `build_tree_manifest` : mise en forme seule, aucune
    donnée nouvelle. Une section « Arborescence cible » (arbre ASCII) suivie d'un
    inventaire des répertoires modèle.
    """
    summary = manifest.get("summary", {})
    tree = manifest.get("tree", {})

    lines: list[str] = [
        "# Arborescence de répertoires modèle ODACEA",
        "",
        f"*Vue du plan de classement réalisé — généré le "
        f"{manifest.get('generatedAt', '—')} "
        f"(format v{manifest.get('manifestVersion', MANIFEST_VERSION)}).*",
        "",
        "## Synthèse",
        "",
        f"- Dossiers (RecordGrp) : {summary.get('folders', 0)}",
        f"- Fichiers classés (Item) : {summary.get('items', 0)}",
        f"- Profondeur maximale : {summary.get('maxDepth', 0)}",
    ]
    start, end = summary.get("startDate"), summary.get("endDate")
    if start or end:
        lines.append(f"- Couverture temporelle : {start or '?'} → {end or '?'}")

    lines += ["", "## Arborescence cible", "", "```text"]
    lines += _render_tree_lines(tree, "", is_last=True, is_root=True)
    lines.append("```")

    directories = manifest.get("directories", [])
    lines += ["", f"## Répertoires modèle ({len(directories)})", ""]
    lines.append(
        "> Structure de dossiers à matérialiser pour un import par glisser-déposer "
        "dans RESIP."
    )
    lines.append("")
    if directories:
        lines += [f"- `{d}`" for d in directories]
    else:
        lines.append("Aucun dossier produit.")

    lines.append("")
    lines.append(
        "*Métadonnées seules : ce manifeste ne contient aucun contenu de document.*"
    )
    lines.append("")
    return "\n".join(lines)
