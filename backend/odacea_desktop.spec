# -*- mode: python ; coding: utf-8 -*-
# Empaquette le mode tout-en-un (docs/I3_MODE_TOUT_EN_UN.md) en exécutable
# unique par OS. Construit depuis `backend/` :
#
#   pip install -e ".[desktop]"
#   pyinstaller odacea_desktop.spec
#
# Suppose que le front a déjà été exporté en statique à côté
# (`cd web && npm run build:desktop` → `web/out/`) — c'est le job CI qui
# orchestre les deux dans le bon ordre (cf. le workflow, dépôt public
# uniquement). `console=True` : les logs uvicorn/erreurs de démarrage restent
# visibles au double-clic (cohérent avec la décision I3 « pas de fenêtre
# native » — l'app s'ouvre dans le navigateur par défaut).
#
# Première version : litellm en particulier embarque des données (table de
# prix, etc.) et des imports dynamiques par fournisseur — `collect_all` vise
# large. Le smoke-test CI (lancer l'exécutable, GET /health) est ce qui
# révélera un hidden-import manquant, pas une relecture de ce fichier.
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

for pkg in ("litellm",):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

hiddenimports += [
    # Enrichissement mécanique (core/enrich.py) — imports paresseux par format,
    # invisibles à l'analyse statique de PyInstaller.
    "pypdf",
    "docx",
    "openpyxl",
    "pptx",
    # uvicorn charge certains modules dynamiquement (workers, protocoles HTTP).
    "uvicorn.workers",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    # litellm compte les tokens via tiktoken, dont l'encodage cl100k_base est
    # enregistré par un plugin découvert au runtime via pkgutil.iter_modules()
    # sur le paquet-espace-de-noms `tiktoken_ext` — invisible à l'analyse
    # statique de PyInstaller (confirmé par un smoke-test réel : sans cette
    # ligne, l'exécutable démarre puis plante avec
    # `ValueError: Unknown encoding cl100k_base`).
    "tiktoken_ext.openai_public",
]

# Front exporté (`web/out`) → servi sous "static" par `desktop.py`
# (resolve_static_dir : sys._MEIPASS/static en exécutable onefile).
front_out = "../web/out"
datas.append((front_out, "static"))
datas.append(("demo_assets/demo.csv", "demo_assets"))

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ODACEA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    onefile=True,
)
