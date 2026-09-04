"""Mode tout-en-un : `desktop.py` (point
d'entrée) + son câblage CLI (`odacea serve`) + le contrat d'empaquetage
(`pyproject.toml`, `odacea_desktop.spec`). Déterministe — aucun uvicorn réel
n'est démarré ici (pas de port tenu en tâche de fond en CI pytest) ; le
smoke-test qui lance réellement l'exécutable vit dans le workflow du dépôt
public (hors de portée d'un test unitaire local)."""
from __future__ import annotations

import argparse
import socket
from pathlib import Path

import desktop

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent
SPEC_FILE = BACKEND / "odacea_desktop.spec"
PYPROJECT = BACKEND / "pyproject.toml"


# ── find_free_port ────────────────────────────────────────────────────────────

def test_find_free_port_returns_bindable_port():
    port = desktop.find_free_port()
    assert 1 <= port <= 65535
    # Le port rendu est effectivement libre et bindable sur 127.0.0.1.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))


def test_find_free_port_yields_distinct_ports_across_calls():
    # Pas de garantie stricte (TOCTOU documenté), mais deux appels consécutifs
    # ne doivent normalement pas retomber sur le même port fermé entre-temps.
    ports = {desktop.find_free_port() for _ in range(5)}
    assert len(ports) == 5


# ── resolve_static_dir ────────────────────────────────────────────────────────

def test_resolve_static_dir_prefers_explicit_argument(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    monkeypatch.setenv("ODACEA_STATIC_DIR", str(env_dir))
    assert desktop.resolve_static_dir(explicit) == explicit


def test_resolve_static_dir_falls_back_to_env_var(tmp_path, monkeypatch):
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    monkeypatch.setenv("ODACEA_STATIC_DIR", str(env_dir))
    assert desktop.resolve_static_dir() == env_dir


def test_resolve_static_dir_falls_back_to_meipass(tmp_path, monkeypatch):
    monkeypatch.delenv("ODACEA_STATIC_DIR", raising=False)
    meipass = tmp_path / "bundle"
    static = meipass / "static"
    static.mkdir(parents=True)
    monkeypatch.setattr(desktop.sys, "_MEIPASS", str(meipass), raising=False)
    assert desktop.resolve_static_dir() == static


def test_resolve_static_dir_none_when_nothing_exists(tmp_path, monkeypatch):
    monkeypatch.delenv("ODACEA_STATIC_DIR", raising=False)
    monkeypatch.delattr(desktop.sys, "_MEIPASS", raising=False)
    # `<repo>/web/out` n'existe qu'après un `npm run build:desktop` réel — pas
    # garanti présent dans l'environnement de test. On ne l'affirme donc que
    # conditionnellement, mais le cas nominal (rien de tout ça) doit rester None
    # quand ce dossier non plus n'existe pas.
    if not (REPO_ROOT / "web" / "out").is_dir():
        assert desktop.resolve_static_dir() is None


def test_resolve_static_dir_explicit_missing_dir_is_skipped(tmp_path, monkeypatch):
    monkeypatch.delenv("ODACEA_STATIC_DIR", raising=False)
    monkeypatch.delattr(desktop.sys, "_MEIPASS", raising=False)
    missing = tmp_path / "does-not-exist"
    if not (REPO_ROOT / "web" / "out").is_dir():
        assert desktop.resolve_static_dir(missing) is None


# ── câblage CLI (`odacea serve`) ──────────────────────────────────────────────

def test_cli_registers_serve_subcommand():
    import cli

    sub_action = next(
        a for a in cli.build_parser()._actions
        if isinstance(a, argparse._SubParsersAction)
    )
    assert "serve" in sub_action.choices
    options = set(sub_action.choices["serve"]._option_string_actions.keys())
    assert {"--port", "--no-browser", "--static-dir"} <= options


def test_cli_serve_defaults_to_desktop_run(monkeypatch):
    import cli

    calls = {}

    def fake_run(*, port, open_browser, static_dir):
        calls.update(port=port, open_browser=open_browser, static_dir=static_dir)

    monkeypatch.setattr(desktop, "run", fake_run)

    args = cli.build_parser().parse_args(["serve", "--port", "1234", "--no-browser"])
    rc = args.func(args)
    assert rc == cli.EXIT_OK
    assert calls == {"port": 1234, "open_browser": False, "static_dir": None}


# ── contrat d'empaquetage (pyproject.toml / .spec) ────────────────────────────

def test_pyproject_declares_desktop_entry_points():
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    assert 'odacea-desktop = "desktop:main"' in pyproject
    assert '"desktop"' in pyproject  # py-modules
    assert "pyinstaller" in pyproject.lower()


def test_pyinstaller_spec_present_and_targets_desktop_entry():
    assert SPEC_FILE.is_file()
    spec = SPEC_FILE.read_text(encoding="utf-8")
    assert '"desktop.py"' in spec
    assert "collect_all" in spec
    # Bundle le front exporté sous "static" — convention lue par
    # `resolve_static_dir` (sys._MEIPASS/static).
    assert '"static"' in spec
