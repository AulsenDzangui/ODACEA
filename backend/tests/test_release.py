"""Versionnage et releases (tags semver, CHANGELOG, artefacts).

On verrouille le *contrat* de release sans construire d'artefact (déterministe,
hors ligne — ni registre Docker ni GitHub requis) :
- `CHANGELOG.md` existe, suit Keep a Changelog / semver, porte une section
  « Non publié » et les versions publiées ;
- `docs/RELEASE.md` documente la politique semver et les artefacts (wheel + Docker) ;
- `.github/workflows/release.yml` se déclenche sur un tag `v*`, vérifie la
  cohérence de version, et build le wheel (`python -m build`) + les images Docker ;
- la version du dépôt est **cohérente** entre les trois fichiers porteurs ;
- `scripts/bump_version.py` lit/calcule/synchronise la version ;
- l'outil de build (`build`) est déclaré côté dev (wheel reproductible en local).

La publication *réelle* (push ghcr.io, GitHub Release) relève de l'exécution du
workflow sur GitHub Actions — comme le `docker up`, hors périmètre du bac
à sable.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
RELEASE_DOC = REPO_ROOT / "docs" / "RELEASE.md"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
BUMP_SCRIPT = REPO_ROOT / "scripts" / "bump_version.py"
PYPROJECT = BACKEND / "pyproject.toml"
PACKAGE_JSON = REPO_ROOT / "web" / "package.json"
API_MAIN = BACKEND / "api" / "main.py"

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _load_bump():
    """Charge `scripts/bump_version.py` comme module (hors `sys.path`)."""
    spec = importlib.util.spec_from_file_location("bump_version", BUMP_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- CHANGELOG -------------------------------------------------------------


def test_changelog_present():
    assert CHANGELOG.is_file()


def test_changelog_follows_keep_a_changelog_and_semver():
    text = CHANGELOG.read_text(encoding="utf-8")
    assert "Keep a Changelog" in text
    assert "semver" in text.lower() or "sémantique" in text.lower()


def test_changelog_has_unreleased_and_released_sections():
    text = CHANGELOG.read_text(encoding="utf-8")
    # Section de travail en cours.
    assert "## [Non publié]" in text
    # Au moins une version publiée référencée.
    assert "## [0.1.0]" in text


# --- Documentation de release ----------------------------------------------


def test_release_doc_present_and_covers_artifacts():
    text = RELEASE_DOC.read_text(encoding="utf-8")
    assert "semver" in text.lower() or "sémantique" in text.lower()
    # Les deux artefacts exigés par la release.
    assert "wheel" in text.lower()
    assert "Docker" in text
    # La source de vérité de version est documentée (les 3 fichiers).
    assert "pyproject.toml" in text
    assert "package.json" in text


# --- Workflow de release ----------------------------------------------------


def test_release_workflow_present_and_tag_triggered():
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    # Déclenché par la pose d'un tag semver.
    assert "tags:" in text
    assert "v*.*.*" in text


def test_release_workflow_builds_wheel_and_images():
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    # Artefact wheel CLI.
    assert "python -m build" in text
    # Artefacts images Docker (backend + web) + registre.
    assert "ghcr.io" in text
    assert "build-push-action" in text


def test_release_workflow_verifies_version_consistency():
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    # Garde-fou : tag vs fichiers de version (via le script).
    assert "bump_version.py --check" in text


# --- Cohérence de version (les 3 fichiers concordent) ----------------------


def _version_in(path: Path, pattern: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"version introuvable dans {path}"
    return match.group(1)


def test_project_version_is_consistent_across_files():
    py = _version_in(PYPROJECT, r'^version = "(\d+\.\d+\.\d+)"')
    web = _version_in(PACKAGE_JSON, r'^  "version": "(\d+\.\d+\.\d+)",')
    api = _version_in(
        API_MAIN, r'FastAPI\(title="ODACEA API", version="(\d+\.\d+\.\d+)"\)'
    )
    assert py == web == api, f"versions divergentes : pyproject={py} web={web} api={api}"
    assert SEMVER_RE.match(py)


# --- Script de bump ---------------------------------------------------------


def test_bump_script_present():
    assert BUMP_SCRIPT.is_file()


def test_bump_current_version_matches_files():
    bump = _load_bump()
    current = bump.current_version()
    assert SEMVER_RE.match(current)
    # Concorde avec le fichier de packaging.
    py = _version_in(PYPROJECT, r'^version = "(\d+\.\d+\.\d+)"')
    assert current == py


def test_bump_compute_next():
    bump = _load_bump()
    assert bump.compute_next("0.1.0", "patch") == "0.1.1"
    assert bump.compute_next("0.1.0", "minor") == "0.2.0"
    assert bump.compute_next("0.1.9", "major") == "1.0.0"
    assert bump.compute_next("0.1.0", "0.3.0") == "0.3.0"


def test_bump_check_passes_on_consistent_repo():
    bump = _load_bump()
    # --check : code 0 quand les trois fichiers concordent (cas du dépôt sain).
    assert bump.main(["--check"]) == 0


def test_bump_rewrites_all_three_files(tmp_path, monkeypatch):
    """`write_version` réécrit les trois fichiers de façon ciblée (copie isolée)."""
    bump = _load_bump()
    # Copies de travail isolées (on ne touche pas le dépôt réel).
    py = tmp_path / "pyproject.toml"
    pkg = tmp_path / "package.json"
    api = tmp_path / "main.py"
    py.write_text('name = "odacea"\nversion = "0.1.0"\n', encoding="utf-8")
    pkg.write_text('{\n  "name": "odacea",\n  "version": "0.1.0",\n}\n', encoding="utf-8")
    api.write_text('app = FastAPI(title="ODACEA API", version="0.1.0")\n', encoding="utf-8")
    monkeypatch.setattr(
        bump,
        "_FILES",
        [
            (py, re.compile(r'(?m)^version = "(?P<v>\d+\.\d+\.\d+)"')),
            (pkg, re.compile(r'(?m)^  "version": "(?P<v>\d+\.\d+\.\d+)",')),
            (api, re.compile(r'FastAPI\(title="ODACEA API", version="(?P<v>\d+\.\d+\.\d+)"\)')),
        ],
    )
    bump.write_version("0.2.0")
    assert 'version = "0.2.0"' in py.read_text(encoding="utf-8")
    assert '"version": "0.2.0",' in pkg.read_text(encoding="utf-8")
    assert 'version="0.2.0"' in api.read_text(encoding="utf-8")


# --- Outillage de build -----------------------------------------------------


def test_build_tool_declared_for_dev():
    reqs = (BACKEND / "requirements-dev.txt").read_text(encoding="utf-8")
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    assert re.search(r"(?m)^build>=", reqs)
    assert '"build>=' in pyproject
