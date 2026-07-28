#!/usr/bin/env python3
"""Convertit une arborescence de fichiers en CSV au format Archifiltre/SEDA.

Les générateurs `demo/generate_demo_tree*.py` produisent une **arborescence**
de fichiers (vides), pas un CSV — normalement Archifiltre Docs s'en charge. Pour
un harnais d'éval **autonome** (sans Archifiltre), ce script dérive le CSV
canonique attendu par le moteur directement de l'arborescence.

Depuis le, la logique de scan vit dans le **moteur**
(`backend/core/source_scan.py`, promu depuis ce script) : ce fichier n'est plus
qu'un mince point d'entrée en ligne de commande. Le moteur est aussi exposé par
l'API (`POST /parse/from-folder`) et la CLI (`odacea scan`) — source unique.

Déterministe (parcours trié), **métadonnées seules** (le contenu des fichiers
n'est jamais lu), sans réseau. Sortie `;` + `QUOTE_ALL`, UTF-8-BOM (comme RESIP).

Usage::

    python scripts/tree_to_archifiltre_csv.py ARBRE_RACINE --out vrac.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Le scan vit dans le moteur (backend/core/source_scan.py) — on l'importe.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from core.source_scan import SourceScanError, write_source_csv  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="Répertoire racine de l'arborescence à convertir")
    parser.add_argument("--out", required=True, help="Fichier CSV de sortie")
    args = parser.parse_args(argv)

    try:
        stats = write_source_csv(Path(args.root), Path(args.out))
    except SourceScanError as e:
        raise SystemExit(str(e))
    print(
        f"{stats['folderCount'] + stats['itemCount'] + 1} lignes "
        f"({stats['itemCount']} fichiers) → {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
