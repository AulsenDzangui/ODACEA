"""Mode tout-en-un : sert le front
(export statique de `web/`) et l'API sur un seul port, en local, et ouvre le
navigateur par défaut. Interface mince au même titre que `cli.py`/`api/` — zéro
logique métier ici, seulement l'orchestration du process.

Point d'entrée de l'exécutable PyInstaller (`odacea_desktop.spec`) et du script
console `odacea-desktop` (`pyproject.toml`). Utilisable aussi directement
depuis les sources, une fois le front exporté :

    cd web && npm run build:desktop
    cd backend && python desktop.py

Garde-fous : écoute **127.0.0.1 uniquement**, aucune connexion sortante
non sollicitée, aucun auto-update.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import pathlib
import socket
import sys
import threading
import webbrowser

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def find_free_port() -> int:
    """Un port libre sur 127.0.0.1, choisi par l'OS (fenêtre TOCTOU minime,
    acceptable pour un lancement local mono-utilisateur)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def resolve_static_dir(explicit: str | pathlib.Path | None = None) -> pathlib.Path | None:
    """Dossier du front exporté à servir, par ordre de priorité :

    1. `explicit` (`--static-dir`) ;
    2. `ODACEA_STATIC_DIR` (déjà positionné dans l'environnement) ;
    3. `<bundle PyInstaller>/static` (exécutable empaqueté, onefile) ;
    4. `<dépôt>/web/out` (développement, après `npm run build:desktop`).

    `None` si rien de tout cela n'existe — l'appelant sert alors l'API seule.
    """
    candidates: list[pathlib.Path] = []
    if explicit:
        candidates.append(pathlib.Path(explicit))
    env_dir = os.environ.get("ODACEA_STATIC_DIR")
    if env_dir:
        candidates.append(pathlib.Path(env_dir))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(pathlib.Path(meipass) / "static")
    candidates.append(REPO_ROOT / "web" / "out")

    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def run(
    *,
    port: int | None = None,
    open_browser: bool = True,
    static_dir: str | pathlib.Path | None = None,
) -> None:
    """Démarre le mode tout-en-un — bloquant jusqu'à interruption (Ctrl+C)."""
    resolved_static = resolve_static_dir(static_dir)
    if resolved_static is not None:
        # Doit être posé AVANT l'import de `api.main` : `config.settings` lit
        # ODACEA_STATIC_DIR à l'import.
        os.environ["ODACEA_STATIC_DIR"] = str(resolved_static)
    else:
        print(
            "[odacea] Front introuvable (aucun export statique sous "
            f"{REPO_ROOT / 'web' / 'out'} ni dans l'exécutable) — API seule "
            "disponible, sans interface.",
            file=sys.stderr,
        )

    import uvicorn

    from api.main import app  # noqa: E402 — après la pose de ODACEA_STATIC_DIR

    chosen_port = port if port is not None else find_free_port()
    url = f"http://127.0.0.1:{chosen_port}/"

    if open_browser and resolved_static is not None:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()

    print(f"[odacea] Mode tout-en-un sur {url} (Ctrl+C pour arrêter)", file=sys.stderr)
    uvicorn.run(app, host="127.0.0.1", port=chosen_port, log_level="info")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odacea-desktop",
        description="Mode tout-en-un ODACEA : API + front local, navigateur ouvert automatiquement.",
    )
    parser.add_argument("--port", type=int, default=None, help="Port d'écoute (défaut : port libre choisi par l'OS)")
    parser.add_argument("--no-browser", action="store_true", help="Ne pas ouvrir le navigateur automatiquement")
    parser.add_argument("--static-dir", default=None, metavar="DOSSIER", help="Dossier du front exporté à servir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with contextlib.suppress(KeyboardInterrupt):
        run(port=args.port, open_browser=not args.no_browser, static_dir=args.static_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
