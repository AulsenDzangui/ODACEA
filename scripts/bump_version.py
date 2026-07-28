#!/usr/bin/env python3
"""Synchronisation de la version du projet (source unique logique).

La version d'ODACEA est portée par trois fichiers qui **doivent rester égaux** :

- ``backend/pyproject.toml``  → ``version = "X.Y.Z"`` (packaging du wheel CLI)
- ``web/package.json``        → ``"version": "X.Y.Z"`` (front)
- ``backend/api/main.py``     → ``FastAPI(title="ODACEA API", version="X.Y.Z")``

Ce script lit la version courante, en calcule une nouvelle (``major``/``minor``/
``patch`` ou valeur explicite ``X.Y.Z``), et réécrit les trois fichiers d'un coup
— pour qu'un release ne laisse jamais une version divergente (cf. la dérive des
tags ``v0.1.1``/``v0.1.2`` documentée dans ``CHANGELOG.md``).

Usage::

    python scripts/bump_version.py            # affiche la version courante
    python scripts/bump_version.py patch      # 0.1.0 -> 0.1.1
    python scripts/bump_version.py minor      # 0.1.0 -> 0.2.0
    python scripts/bump_version.py major      # 0.1.0 -> 1.0.0
    python scripts/bump_version.py 0.3.0      # valeur explicite
    python scripts/bump_version.py --check    # code de sortie 0 ssi les 3 fichiers concordent

Aucun effet de bord réseau ; n'écrit pas de tag git (la pose du tag reste l'acte
de release — voir ``docs/RELEASE.md``).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# (chemin, motif de capture de la version) — le groupe 1 est la version X.Y.Z.
PYPROJECT = REPO_ROOT / "backend" / "pyproject.toml"
PACKAGE_JSON = REPO_ROOT / "web" / "package.json"
API_MAIN = REPO_ROOT / "backend" / "api" / "main.py"

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

# Chaque entrée : (fichier, regex avec un groupe nommé `v` autour de la version).
# Les regex sont assez précises pour ne capturer que la version du projet.
_FILES: list[tuple[Path, re.Pattern[str]]] = [
    (PYPROJECT, re.compile(r'(?m)^version = "(?P<v>\d+\.\d+\.\d+)"')),
    (PACKAGE_JSON, re.compile(r'(?m)^  "version": "(?P<v>\d+\.\d+\.\d+)",')),
    (API_MAIN, re.compile(r'FastAPI\(title="ODACEA API", version="(?P<v>\d+\.\d+\.\d+)"\)')),
]


def read_versions() -> dict[Path, str]:
    """Renvoie {fichier: version} pour les trois porteurs de version."""
    out: dict[Path, str] = {}
    for path, pattern in _FILES:
        text = path.read_text(encoding="utf-8")
        match = pattern.search(text)
        if match is None:
            raise SystemExit(f"Version introuvable dans {path.relative_to(REPO_ROOT)}")
        out[path] = match.group("v")
    return out


def current_version() -> str:
    """Version courante (exige la concordance des trois fichiers)."""
    versions = read_versions()
    distinct = set(versions.values())
    if len(distinct) != 1:
        details = ", ".join(
            f"{p.relative_to(REPO_ROOT)}={v}" for p, v in versions.items()
        )
        raise SystemExit(f"Versions divergentes : {details}")
    return distinct.pop()


def compute_next(current: str, bump: str) -> str:
    """Calcule la prochaine version (`major`/`minor`/`patch` ou valeur X.Y.Z)."""
    if SEMVER_RE.match(bump):
        return bump
    major, minor, patch = (int(part) for part in current.split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise SystemExit(f"Argument de version invalide : {bump!r} (major|minor|patch|X.Y.Z)")


def write_version(new_version: str) -> None:
    """Réécrit la version dans les trois fichiers (remplacement ciblé)."""
    for path, pattern in _FILES:
        text = path.read_text(encoding="utf-8")
        new_text, count = pattern.subn(
            lambda m: m.group(0).replace(m.group("v"), new_version), text
        )
        if count != 1:
            raise SystemExit(
                f"Remplacement ambigu ou manquant dans {path.relative_to(REPO_ROOT)} "
                f"({count} occurrence(s))"
            )
        path.write_text(new_text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "bump",
        nargs="?",
        help="major | minor | patch | X.Y.Z (omis : affiche la version courante)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="vérifie seulement que les trois fichiers concordent (aucune écriture)",
    )
    args = parser.parse_args(argv)

    if args.check:
        current = current_version()  # lève si divergence
        print(f"OK — version cohérente : {current}")
        return 0

    if args.bump is None:
        print(current_version())
        return 0

    current = current_version()
    new_version = compute_next(current, args.bump)
    write_version(new_version)
    print(f"{current} -> {new_version}")
    print("Pensez à mettre à jour CHANGELOG.md puis à poser le tag (cf. docs/RELEASE.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
