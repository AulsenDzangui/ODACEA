"""Packaging — point d'entrée console `odacea` (`pip install -e .`).

On vérifie le contrat de packaging sans dépendre de l'état d'installation :
- `pyproject.toml` déclare bien le script `odacea = "cli:main"` ;
- la cible (`cli.main`) existe et est appelable ;
- les paquets du moteur sont déclarés explicitement (ni tests ni données).

Si le paquet est effectivement installé (CI fait `pip install -e .`), on
vérifie en plus que le point d'entrée résout vers la bonne cible.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

try:
    import tomllib  # Python ≥ 3.11
except ModuleNotFoundError:  # pragma: no cover - repli pour Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

import cli

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_console_script_declared(pyproject):
    scripts = pyproject["project"]["scripts"]
    assert scripts["odacea"] == "cli:main"


def test_entry_point_target_callable():
    # La cible du script doit exister et accepter argv (renvoie un code EXIT_*).
    assert callable(cli.main)


def test_packages_explicit_no_tests(pyproject):
    packages = pyproject["tool"]["setuptools"]["packages"]
    # Le moteur est déclaré ; ni les tests ni les répertoires de données
    # (evals/, demo_assets/) ne doivent être embarqués comme paquets.
    assert set(packages) == {"api", "config", "core", "llm", "prompts"}
    assert "tests" not in packages
    assert pyproject["tool"]["setuptools"]["py-modules"] == ["cli"]


def test_runtime_deps_cover_cli(pyproject):
    # `pip install -e .` doit suffire à faire tourner le CLI : les imports de
    # tête de cli.py (pandas, dotenv) doivent figurer dans les dépendances.
    deps = " ".join(pyproject["project"]["dependencies"]).lower()
    assert "pandas" in deps
    assert "python-dotenv" in deps
    assert "litellm" in deps


def test_installed_entry_point_resolves():
    # N'a de sens que si le paquet est installé (cas de la CI : pip install -e .).
    from importlib.metadata import entry_points

    try:
        scripts = entry_points(group="console_scripts")
    except Exception:  # pragma: no cover - API ancienne
        pytest.skip("entry_points indisponible")
    match = [ep for ep in scripts if ep.name == "odacea"]
    if not match:
        pytest.skip("paquet non installé (pip install -e . non exécuté)")
    assert match[0].value.replace(" ", "") == "cli:main"
    loaded = match[0].load()
    assert loaded is cli.main or loaded.__name__ == "main"


def test_help_uses_invoked_program_name(capsys):
    # prog implicite : le nom affiché suit sys.argv[0] (odacea / cli.py),
    # il n'est plus codé en dur sur « cli.py ».
    parser = cli.build_parser()
    assert parser.prog == Path(sys.argv[0]).name
