"""Scan d'un dossier local → CSV canonique Archifiltre/SEDA.

À l'entrée du pipeline, ODACEA attend un CSV exporté par Archifiltre Docs. Le
backend étant **local**, il peut se
passer de cette étape chronophage et **scanner le dossier du vrac directement** :
ce module dérive le CSV canonique à partir de l'arborescence réelle, comme le
ferait Archifiltre, mais sans installer ni lancer Archifiltre.

**Métadonnées seules (strict).** Le contenu des fichiers n'est **jamais**
ouvert : seules les métadonnées de système de fichiers sont lues (nom, chemin,
`mtime` via ``stat()``). C'est la garantie centrale du module (vérifiée par test :
un scan réussit même si ``open`` est rendu inopérant).

Déterministe (parcours trié), sans réseau. Le CSV produit est au format canonique
attendu par ``core.csv_handler.read_csv`` :

- colonnes ``ID;ParentID;File;Content.DescriptionLevel;Content.Title;Content.StartDate;Content.EndDate`` ;
- racine ``ID=1``, ``ParentID`` vide, ``File="."``, niveau ``RecordGrp`` ;
- dossiers → ``RecordGrp`` ; fichiers → ``Item`` ;
- ``File`` = chemin relatif POSIX depuis la racine ; ``Content.Title`` = nom sans
  extension, ``_`` → espace ;
- dates des ``Item`` = ``mtime`` (YYYY-MM-DD) ; dates d'un dossier = min/max des
  dates de ses descendants (vide s'il est vide).

Écarts assumés vs un export Archifiltre : les dates sont des **dates de
modification du système de fichiers**, pas des dates métier — quand un export
Archifiltre existe, il reste préférable (l'appelant en avertit l'archiviste).

Exclusions (bruit qui n'a rien d'archivistique) : fichiers/dossiers **cachés**
(nom commençant par ``.``), **fichiers système** (``Thumbs.db``, ``desktop.ini``,
``.DS_Store``…) et **fichiers de verrouillage** bureautiques (``~$*``). Les
**liens symboliques ne sont pas suivis** (ni fichiers ni dossiers) — évite les
boucles et la sortie du périmètre du vrac.
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timezone
from pathlib import Path

COLUMNS = [
    "ID", "ParentID", "File", "Content.DescriptionLevel",
    "Content.Title", "Content.StartDate", "Content.EndDate",
]

# Noms de fichiers système/techniques toujours ignorés (comparaison insensible à
# la casse). Les fichiers de verrouillage Office (`~$rapport.docx`) et tout nom
# commençant par « . » (cachés Unix) sont traités séparément (préfixe).
_EXCLUDED_FILENAMES = {
    "thumbs.db", "desktop.ini", ".ds_store", "ehthumbs.db",
    "$recycle.bin", "system volume information",
}


def _is_excluded_name(name: str) -> bool:
    """Un nom (fichier ou dossier) à ignorer : caché (`.`), verrou Office (`~$`)
    ou fichier système connu. Déterministe, purement lexical (aucun accès disque)."""
    low = name.lower()
    if name.startswith(".") or name.startswith("~$"):
        return True
    return low in _EXCLUDED_FILENAMES


def _title(name: str) -> str:
    """Titre lisible : nom sans extension, underscores → espaces."""
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return stem.replace("_", " ").strip()


def _date(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


class SourceScanError(ValueError):
    """Scan refusé (racine invalide, ou volumétrie au-delà de la garde mémoire).

    Porte un ``hint`` actionnable, comme ``api.engine.CsvLimitError``."""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


def _walk(root: Path) -> tuple[list[Path], list[Path], dict]:
    """Parcours récursif **déterministe** de ``root`` (trié), sans suivre les
    liens symboliques ni descendre dans les entrées exclues.

    Retourne ``(dirs, files, counters)`` — ``dirs``/``files`` triés par chemin
    (ordre stable des IDs), ``counters`` = décomptes d'exclusions. **N'ouvre
    aucun binaire** : seuls ``scandir``/``is_dir``/``is_file`` sont utilisés."""
    dirs: list[Path] = []
    files: list[Path] = []
    counters = {"excluded": 0, "skippedSymlinks": 0}

    def descend(current: Path) -> None:
        try:
            entries = list(os.scandir(current))
        except OSError:
            return
        for entry in sorted(entries, key=lambda e: e.name):
            # Un lien symbolique n'est jamais suivi (boucles, sortie de périmètre).
            if entry.is_symlink():
                counters["skippedSymlinks"] += 1
                continue
            if _is_excluded_name(entry.name):
                counters["excluded"] += 1
                continue
            path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                dirs.append(path)
                descend(path)
            elif entry.is_file(follow_symlinks=False):
                files.append(path)

    descend(root)
    dirs.sort()
    files.sort()
    return dirs, files, counters


def scan_source_tree(
    root: Path, *, max_items: int | None = None
) -> tuple[list[dict[str, str]], dict]:
    """Dérive les lignes Archifiltre canoniques de l'arborescence ``root``.

    Déterministe, **métadonnées seules** (aucun binaire ouvert). ``max_items``
    (garde mémoire) borne le nombre d'``Item`` : au-delà, ``SourceScanError``
    avec un ``hint`` de découpage. Retourne ``(rows, stats)`` où ``stats`` porte
    ``itemCount``/``folderCount``/``rootTitle``/``excludedCount``/``skippedSymlinks``.

    Lève ``SourceScanError`` si ``root`` n'est pas un répertoire.
    """
    root = root.expanduser()
    if not root.is_dir():
        raise SourceScanError(
            f"Dossier source introuvable : {root}",
            hint=("Indiquez un dossier local existant (le vrac à traiter), "
                  "accessible depuis la machine qui héberge le backend."),
        )

    dirs, files, counters = _walk(root)

    if max_items is not None and len(files) > max_items:
        raise SourceScanError(
            f"Vrac trop volumineux : {len(files)} fichiers, maximum accepté "
            f"{max_items} (garde mémoire).",
            hint=("Un vrac de cette taille doit être découpé avant traitement "
                  "(scanner un sous-dossier de premier niveau à la fois) ; ou "
                  "augmentez ODACEA_MAX_CSV_ROWS côté serveur si la machine le permet."),
        )

    ids: dict[Path, int] = {root: 1}
    folder_dates: dict[Path, list[str]] = {root: []}
    next_id = 2
    for dirpath in dirs:
        ids[dirpath] = next_id
        folder_dates[dirpath] = []
        next_id += 1

    # Lignes Item + propagation des dates (mtime) aux dossiers ancêtres.
    item_rows: list[dict[str, str]] = []
    for fp in files:
        fid = next_id
        next_id += 1
        d = _date(fp.stat().st_mtime)
        item_rows.append({
            "ID": str(fid),
            "ParentID": str(ids[fp.parent]),
            "File": fp.relative_to(root).as_posix(),
            "Content.DescriptionLevel": "Item",
            "Content.Title": _title(fp.name),
            "Content.StartDate": d,
            "Content.EndDate": d,
        })
        ancestor = fp.parent
        while ancestor in folder_dates:
            folder_dates[ancestor].append(d)
            if ancestor == root:
                break
            ancestor = ancestor.parent

    rows: list[dict[str, str]] = []
    root_dates = folder_dates[root]
    rows.append({
        "ID": "1", "ParentID": "", "File": ".",
        "Content.DescriptionLevel": "RecordGrp",
        "Content.Title": _title(root.name),
        "Content.StartDate": min(root_dates) if root_dates else "",
        "Content.EndDate": max(root_dates) if root_dates else "",
    })
    for dirpath in dirs:
        dates = folder_dates[dirpath]
        rows.append({
            "ID": str(ids[dirpath]),
            "ParentID": str(ids[dirpath.parent]),
            "File": dirpath.relative_to(root).as_posix(),
            "Content.DescriptionLevel": "RecordGrp",
            "Content.Title": _title(dirpath.name),
            "Content.StartDate": min(dates) if dates else "",
            "Content.EndDate": max(dates) if dates else "",
        })
    rows.extend(item_rows)

    stats = {
        "itemCount": len(files),
        "folderCount": len(dirs),
        "rootTitle": _title(root.name),
        "excludedCount": counters["excluded"],
        "skippedSymlinks": counters["skippedSymlinks"],
    }
    return rows, stats


def rows_to_csv(rows: list[dict[str, str]]) -> str:
    """Sérialise les lignes en CSV canonique (`;`, `QUOTE_ALL`) — chaîne texte.

    Pas de BOM ici : la chaîne est destinée soit à ``read_csv`` (qui gère le BOM),
    soit au transport JSON vers le front (qui ajoute le BOM au téléchargement)."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, delimiter=";", quoting=csv.QUOTE_ALL)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def scan_source_csv(root: Path, *, max_items: int | None = None) -> tuple[str, dict]:
    """Scan → CSV canonique (texte) + stats. Raccourci ``scan_source_tree`` +
    ``rows_to_csv`` (source unique, partagée API ``/parse/from-folder`` ⇄ CLI ``scan``)."""
    rows, stats = scan_source_tree(root, max_items=max_items)
    return rows_to_csv(rows), stats


def write_source_csv(root: Path, dest: Path, *, max_items: int | None = None) -> dict:
    """Scan ``root`` → écrit le CSV canonique dans ``dest`` (UTF-8-BOM, comme RESIP).
    Retourne les stats du scan. Utilisé par la CLI ``odacea scan``."""
    rows, stats = scan_source_tree(root, max_items=max_items)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter=";", quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    return stats
