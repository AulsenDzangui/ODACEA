"""Audit des dépendances intégré à la CI.

On verrouille le *contrat* sans lancer les audits réseau (déterministe, hors
ligne) :
- `pip-audit` est déclaré comme outil de dev (requirements-dev.txt + extra
  `[dev]` de pyproject) → reproductible en local comme en CI ;
- le workflow CI porte bien un job d'audit invoquant `pip-audit` (Python) et
  `npm audit` au seuil `high` (web).
"""
from __future__ import annotations

from pathlib import Path

try:
    import tomllib  # Python ≥ 3.11
except ModuleNotFoundError:  # pragma: no cover - repli pour Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent
PYPROJECT = BACKEND / "pyproject.toml"
REQUIREMENTS_DEV = BACKEND / "requirements-dev.txt"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_pip_audit_in_requirements_dev():
    deps = REQUIREMENTS_DEV.read_text(encoding="utf-8").lower()
    assert "pip-audit" in deps


def test_pip_audit_in_dev_extra():
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dev_extra = " ".join(pyproject["project"]["optional-dependencies"]["dev"]).lower()
    assert "pip-audit" in dev_extra


def test_ci_workflow_has_dependency_audit_job():
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    # Job dédié à l'audit des dépendances.
    assert "audit:" in workflow
    # Les deux outils du cahier y sont invoqués.
    assert "pip-audit" in workflow
    assert "npm audit" in workflow
    # Le seuil web est explicite (les « moderate » n'écroulent pas la CI).
    assert "--audit-level=high" in workflow
