"""Scan déterministe des métadonnées d'un vrac (sans IA, sans contenu).

Calcule, à partir des *seules* métadonnées du CSV (chemins, extensions, niveaux),
les constats **purement mécaniques** d'un vrac — volumétrie et recensement des
formats — destinés à **ancrer** l'audit AUD-001.

Périmètre volontairement restreint : on ne fournit au modèle que ce qu'un script
calcule sans aucun risque d'erreur ni de jugement (compter des lignes, lister des
extensions, classer une extension dans une liste fixe « formats à risque » /
« compressés », repérer un nom de fichier dans une liste fixe de bruit numérique).
Tout ce qui relève de l'**analyse** — doublons sémantiques, anomalies de nommage —
reste laissé au modèle : c'est sa valeur ajoutée, pas celle d'un compteur. Le
brider sur ces points dégraderait l'audit.

Le **bruit numérique** (fichiers système `Thumbs.db`/`.DS_Store`, verrous
bureautiques `~$…`, fichiers temporaires `.tmp`/`.download`…) fait exception et est
pré-calculé : il s'agit d'un appariement à **liste fixe de noms/extensions**, sans
plus de jugement que la liste des formats à risque. Un modèle local scannant des
milliers de lignes rate ce bruit dispersé ; un comptage déterministe faisant
autorité supprime l'oubli et rend l'audit reproductible.

De même, les **noms de fichiers répétés** (un même nom de base porté par plusieurs
fichiers) sont pré-calculés : c'est une **égalité de chaîne**, pas un jugement. On
ne fournit que la *liste des candidats* — le modèle garde la décision de doublon
sémantique (mêmes titre/date/taille ?), qu'il sait faire mais ne sait pas repérer
de façon exhaustive sur des milliers de lignes.

Les **indicateurs de structuration** (fichiers à la racine, plus gros dossiers par
fichiers directs, préfixes d'ordre numérique) et le recensement des **dossiers
sources** suivent la même règle : comptages mécaniques ancrant le verdict « Ordre
existant » demandé par AUD-001 (respect de l'ordre originel) — le verdict lui-même
(structuré / partiel / absent) reste un jugement du modèle.

Pourquoi ancrer la volumétrie et les formats : un modèle local compact (workflow
on-prem d'ODACEA) compte et agrège mal sur des milliers de lignes (total
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

from core.enrich import FINGERPRINT_COLUMN

# Formats bureautiques anciens/propriétaires à migrer (PDF/A, ODF…).
RISKY_FORMATS = {
    "doc", "xls", "ppt", "mdb", "accdb", "pub", "vsd", "wps", "wpd", "wri",
}
# Archives compressées : à décompresser ou intégrer comme dossiers virtuels.
COMPRESSED_FORMATS = {"zip", "rar", "7z", "gz", "tgz", "tar", "bz2", "cab", "arj"}

# ── Bruit numérique (listes fixes, repérage mécanique) ───────────────────────
# Noms de fichiers système sans valeur archivistique (comparaison sur le nom de
# base, insensible à la casse). Générés par l'OS / l'explorateur de fichiers.
NOISE_SYSTEM_NAMES = {
    "thumbs.db", "ehthumbs.db", ".ds_store", "desktop.ini", ".localized",
    ".apdisk", "icon\r",
}
# Extensions de fichiers temporaires / brouillons de récupération / sauvegardes
# automatiques (sans le point, en minuscules).
NOISE_TEMP_EXTENSIONS = {
    "tmp", "temp", "download", "crdownload", "part", "partial", "swp", "swo",
}


def _noise_kind(path: str) -> str | None:
    """Classe un chemin dans une catégorie de bruit numérique, ou None.

    Repérage purement mécanique sur le **nom de base** : appariement à des listes
    fixes (noms système, verrous bureautiques `~$…`, extensions temporaires). Ne
    porte aucun jugement — analogue à la liste des formats à risque.
    """
    name = _basename(path).strip().lower()
    if not name:
        return None
    # Verrous Office/LibreOffice : ~$rapport.docx, .~lock.fichier.odt#
    if name.startswith("~$") or name.startswith(".~lock."):
        return "verrou bureautique"
    if name in NOISE_SYSTEM_NAMES:
        return "fichier système"
    if _extension(name) in NOISE_TEMP_EXTENSIONS:
        return "fichier temporaire"
    return None


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


def _nonempty_folder_ids(data: pd.DataFrame) -> set[str]:
    """IDs des RecordGrp ayant au moins un Item dans leur sous-arbre.

    Remontée des ascendants depuis chaque Item (arrêt anticipé dès qu'un
    ascendant déjà marqué est atteint, d'où un coût quasi linéaire même sur des
    milliers de lignes). Partagé par le repérage des dossiers vides et le
    recensement des dossiers sources (conservation de l'ordre existant).
    """
    ids = data["ID"]
    parents = data["ParentID"]
    level = data["Content.DescriptionLevel"]
    id_to_parent = dict(zip(ids, parents, strict=True))

    nonempty: set[str] = set()
    for i in range(len(data)):
        if level.iat[i] != "Item":
            continue
        p = parents.iat[i]
        while p and p in id_to_parent and p not in nonempty:
            nonempty.add(p)
            p = id_to_parent.get(p, "")
    return nonempty


def _find_empty_folders(data: pd.DataFrame) -> dict:
    """Repère les RecordGrp dont l'arborescence ne contient AUCUN Item.

    Constat purement mécanique : on reconstruit la relation parent/enfant
    (`ID`/`ParentID`) et on marque « non vide » tout dossier ayant au moins un
    Item dans son sous-arbre (`_nonempty_folder_ids`). Les RecordGrp restants
    sont vides : sans valeur archivistique, candidats à la suppression. Un modèle
    local ne peut pas calculer ce parcours d'arbre de façon fiable — d'où
    l'ancrage déterministe, dans l'esprit du repérage du bruit numérique.

    La racine du fonds (`File="."`) est exclue : ce n'est pas un « dossier vide »
    au sens du tri, c'est le nœud de plus haut niveau du fonds. Robuste aux
    colonnes manquantes (retourne un total nul).
    """
    needed = {"ID", "ParentID", "Content.DescriptionLevel"}
    if not needed.issubset(data.columns):
        return {"total": 0, "examples": []}

    ids = data["ID"]
    level = data["Content.DescriptionLevel"]
    files = data["File"] if "File" in data.columns else pd.Series([""] * len(data))
    titles = data["Content.Title"] if "Content.Title" in data.columns else pd.Series([""] * len(data))

    nonempty = _nonempty_folder_ids(data)

    total = 0
    examples: list[str] = []
    for i in range(len(data)):
        if level.iat[i] != "RecordGrp" or files.iat[i] == ".":
            continue
        if ids.iat[i] in nonempty:
            continue
        total += 1
        if len(examples) < 5:
            label = titles.iat[i].strip() or _basename(files.iat[i]).strip()
            examples.append(label or "(sans titre)")
    return {"total": total, "examples": examples}


def _find_name_collisions(item_files: pd.Series) -> dict:
    """Repère les noms de fichiers identiques apparaissant à plusieurs endroits.

    Constat purement **mécanique** : on regroupe les Item par nom de base
    (insensible à la casse, Windows l'étant), et on retient les noms portés par
    au moins deux fichiers — un même fichier copié dans plusieurs dossiers, motif
    classique d'un vrac (`Compte rendu.docx` dupliqué dans cinq dossiers). Le bruit
    numérique (`Thumbs.db`…) est exclu : ces noms collisionnent partout sans valeur,
    et sont déjà comptés ailleurs.

    Ce n'est **pas** une analyse sémantique de doublons (titre + date + taille,
    qui relève du jugement et reste au modèle) : c'est l'**égalité de nom**, qu'un
    modèle local ne peut pas repérer de façon fiable sur des milliers de lignes. Le
    digest fournit donc au modèle la liste des **candidats** ; lui seul tranche s'il
    s'agit du même document ou de fichiers distincts au nom identique (gabarit §1.4).
    """
    counter: Counter[str] = Counter()
    display: dict[str, str] = {}
    for f in item_files:
        if _noise_kind(f) is not None:
            continue
        name = _basename(f).strip()
        key = name.lower()
        if not key:
            continue
        counter[key] += 1
        display.setdefault(key, name)

    repeated = [(key, n) for key, n in counter.items() if n >= 2]
    # Tri déterministe : nb d'occurrences décroissant, puis nom.
    repeated.sort(key=lambda kv: (-kv[1], kv[0]))
    examples = [(display[key], n) for key, n in repeated[:5]]
    return {
        "total": len(repeated),
        "files": sum(n for _, n in repeated),
        "examples": examples,
    }


def _find_strict_duplicates(data: pd.DataFrame) -> dict:
    """Regroupe les Item de même empreinte SHA-256 (doublons binaires stricts).

    **Inactif tant que la colonne d'empreinte est absente** : la détection stricte
    exige le hash, calculé en local sur les binaires par l'étape facultative
    `enrich --fingerprint`. Quand elle est présente, le regroupement est une
    **égalité de hash** — déterministe, sans jugement, plus fort que la simple
    collision de noms (`_find_name_collisions`) : deux fichiers de même empreinte
    sont **binairement identiques**, donc des doublons stricts confirmés.

    Retourne `available=False` (rien à dire) si aucune empreinte n'est fournie.
    Sinon : nombre de groupes, total de fichiers concernés, redondances
    supprimables (un exemplaire conservé par groupe), et quelques exemples.
    """
    if FINGERPRINT_COLUMN not in data.columns:
        return {"available": False, "total": 0, "files": 0, "redundant": 0, "examples": []}

    level = data["Content.DescriptionLevel"] if "Content.DescriptionLevel" in data.columns else None
    files = data["File"] if "File" in data.columns else pd.Series([""] * len(data))
    fingerprints = data[FINGERPRINT_COLUMN]

    groups: dict[str, list[str]] = {}
    for i in range(len(data)):
        if level is not None and level.iat[i] != "Item":
            continue
        fp = str(fingerprints.iat[i]).strip().lower()
        if not fp:
            continue
        name = _basename(str(files.iat[i])).strip() or "(sans nom)"
        groups.setdefault(fp, []).append(name)

    duplicates = {fp: names for fp, names in groups.items() if len(names) >= 2}
    # Tri déterministe : groupes les plus volumineux d'abord, puis par hash.
    ordered = sorted(duplicates.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    examples = [
        {"hash": fp[:12], "count": len(names), "names": sorted(set(names))[:4]}
        for fp, names in ordered[:5]
    ]
    return {
        "available": True,
        "total": len(duplicates),
        "files": sum(len(names) for names in duplicates.values()),
        "redundant": sum(len(names) - 1 for names in duplicates.values()),
        "examples": examples,
    }


def _source_folders(data: pd.DataFrame) -> dict:
    """Recense les dossiers **sources** du vrac (RecordGrp hors racine).

    Constat mécanique au service de la conservation de l'ordre existant :
    `titles` liste les libellés des dossiers **non vides** (ceux qu'un plan
    conservateur doit retenir — un dossier vide est un défaut, sa disparition
    n'est pas un écart). La comparaison sémantique avec le plan produit vit dans
    `core.evals` (métrique de conservation) ; ici on ne fait que compter et
    lister, sans jugement. Robuste aux colonnes manquantes.
    """
    needed = {"ID", "ParentID", "Content.DescriptionLevel"}
    if not needed.issubset(data.columns):
        return {"total": 0, "nonEmpty": 0, "titles": []}

    ids = data["ID"]
    level = data["Content.DescriptionLevel"]
    files = data["File"] if "File" in data.columns else pd.Series([""] * len(data))
    titles = data["Content.Title"] if "Content.Title" in data.columns else pd.Series([""] * len(data))

    nonempty = _nonempty_folder_ids(data)
    total = 0
    labels: list[str] = []
    for i in range(len(data)):
        if level.iat[i] != "RecordGrp" or files.iat[i] == ".":
            continue
        total += 1
        if ids.iat[i] not in nonempty:
            continue
        label = titles.iat[i].strip() or _basename(files.iat[i]).strip()
        if label:
            labels.append(label)
    return {"total": total, "nonEmpty": len(labels), "titles": labels}


# Préfixe d'ordre en tête d'un nom de dossier (`01_`, `1.`, `2 -`…) : trace
# mécanique d'un schéma de classement voulu par le producteur.
_ORDER_PREFIX_RE = re.compile(r"^\d+[\s._)-]")


def _structure_indicators(data: pd.DataFrame, is_item: pd.Series, files: pd.Series) -> dict:
    """Indicateurs mécaniques de structuration de l'arborescence existante.

    Uniquement des comptages sans jugement — le verdict sur l'ordre existant
    (structuré / partiel / absent) reste au modèle, ancré sur ces chiffres :
    * `rootItems` — fichiers posés directement à la racine (hors tout dossier) ;
    * `topFolders` — dossiers portant le plus de fichiers **directs** (candidats
      fourre-tout, mais c'est au modèle d'en juger) ;
    * `prefixedFolders` — dossiers dont le nom commence par un préfixe d'ordre
      numérique (`01_`, `1.`…), trace d'un schéma de classement préexistant.
    """
    item_paths = [f for f, it in zip(files, is_item, strict=True) if it] if len(is_item) else list(files)
    item_count = len(item_paths)

    root_items = sum(1 for f in item_paths if len(_segments(f)) == 1)

    direct_counter: Counter[str] = Counter()
    for f in item_paths:
        segs = _segments(f)
        if len(segs) >= 2:
            direct_counter[segs[-2]] += 1
    top_folders = direct_counter.most_common(5)

    level = data["Content.DescriptionLevel"] if "Content.DescriptionLevel" in data.columns else pd.Series([], dtype=str)
    folder_names = [
        _basename(files.iat[i]).strip()
        for i in range(len(level))
        if level.iat[i] == "RecordGrp" and files.iat[i] != "."
    ]
    prefixed = sum(1 for name in folder_names if _ORDER_PREFIX_RE.match(name))

    return {
        "rootItems": root_items,
        "rootItemsPct": round(100 * root_items / item_count, 1) if item_count else 0.0,
        "topFolders": top_folders,
        "prefixedFolders": prefixed,
        "folderCount": len(folder_names),
    }


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

    # ── Bruit numérique (repérage mécanique sur le nom, listes fixes) ────────
    noise_counter: Counter[str] = Counter()
    noise_examples: list[str] = []
    for f in item_files:
        kind = _noise_kind(f)
        if kind is None:
            continue
        noise_counter[kind] += 1
        if len(noise_examples) < 5:
            noise_examples.append(_basename(f))

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
        "noise": {
            "total": int(sum(noise_counter.values())),
            "byKind": sorted(noise_counter.items(), key=lambda kv: -kv[1]),
            "examples": noise_examples,
        },
        "emptyFolders": _find_empty_folders(data),
        "nameCollisions": _find_name_collisions(item_files),
        "strictDuplicates": _find_strict_duplicates(data),
        "sourceFolders": _source_folders(data),
        "structure": _structure_indicators(data, is_item, files),
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

    # Structuration existante : chiffres mécaniques ancrant le verdict « Ordre
    # existant » demandé par AUD-001 (Partie 2) — le jugement reste au modèle.
    structure = scan.get("structure", {})
    if structure and (structure.get("folderCount") or v["items"]):
        if not structure["folderCount"]:
            lines.append(
                "- **Structuration existante (constats mécaniques)** : aucun dossier "
                f"recensé ; {structure['rootItems']} fichier(s) à la racine "
                f"({structure['rootItemsPct']} % des fichiers)."
            )
        else:
            parts = [
                f"{structure['rootItems']} fichier(s) à la racine "
                f"({structure['rootItemsPct']} % des fichiers)"
            ]
            if structure.get("topFolders"):
                top_str = ", ".join(f"{name} ({n})" for name, n in structure["topFolders"])
                parts.append(f"plus gros dossiers (fichiers directs) : {top_str}")
            parts.append(
                f"{structure['prefixedFolders']} dossier(s) sur "
                f"{structure['folderCount']} à préfixe d'ordre numérique"
            )
            lines.append(
                "- **Structuration existante (constats mécaniques)** : "
                + " ; ".join(parts) + "."
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

    noise = scan.get("noise", {})
    if noise.get("total"):
        kind_str = ", ".join(f"{kind} ({n})" for kind, n in noise["byKind"])
        line = (
            f"- **Bruit numérique (repérage mécanique, sans valeur archivistique)** : "
            f"{noise['total']} fichier(s) — {kind_str}."
        )
        if noise.get("examples"):
            line += " Ex. : " + ", ".join(noise["examples"]) + "."
        lines.append(line)
    else:
        lines.append(
            "- **Bruit numérique (repérage mécanique)** : aucun fichier système / "
            "temporaire / verrou bureautique détecté."
        )

    empty = scan.get("emptyFolders", {})
    if empty.get("total"):
        line = (
            f"- **Dossiers vides (aucun fichier dans leur arborescence)** : "
            f"{empty['total']} dossier(s)."
        )
        if empty.get("examples"):
            line += " Ex. : " + ", ".join(empty["examples"]) + "."
        lines.append(line)
    else:
        lines.append("- **Dossiers vides** : aucun détecté.")

    coll = scan.get("nameCollisions", {})
    if coll.get("total"):
        line = (
            f"- **Noms de fichiers répétés (repérage mécanique — candidats doublons "
            f"à confirmer par titre/date)** : {coll['total']} nom(s) porté(s) par "
            f"plusieurs fichiers ({coll['files']} fichiers au total)."
        )
        if coll.get("examples"):
            ex = ", ".join(f"{name} (×{n})" for name, n in coll["examples"])
            line += " Ex. : " + ex + "."
        lines.append(line)
    else:
        lines.append("- **Noms de fichiers répétés** : aucun détecté.")

    # Doublons stricts : rendus uniquement si une empreinte a été fournie
    # (étape `enrich --fingerprint`). Sans empreinte, on n'encombre pas le digest
    # — l'analyse sémantique des doublons reste au modèle (cf. noms répétés).
    dups = scan.get("strictDuplicates", {})
    if dups.get("available"):
        if dups.get("total"):
            line = (
                f"- **Doublons stricts (empreinte SHA-256 — fichiers binairement "
                f"identiques)** : {dups['total']} groupe(s), {dups['files']} fichiers, "
                f"{dups['redundant']} redondance(s) supprimable(s)."
            )
            if dups.get("examples"):
                ex = ", ".join(
                    f"{e['count']}× {' = '.join(e['names'])}" for e in dups["examples"]
                )
                line += " Ex. : " + ex + "."
            lines.append(line)
        else:
            lines.append(
                "- **Doublons stricts (empreinte SHA-256 fournie)** : aucun fichier "
                "binairement identique détecté."
            )

    return "\n".join(lines)
