#!/usr/bin/env python3
"""Fabrique un fichier de corrections à partir d'un run de référence.

L'expérience few-shot (/ expérience (a) du harnais d'éval) compare CLA-001
**avec** et **sans** un bloc d'exemples de corrections validées
(`Path;TargetFolder;NewTitle`). Pour disposer d'exemples réalistes sans
intervention humaine, ce script **dérive** un fichier de corrections des
**classements propres** produits par un run de référence (`odacea run --out-dir`) :
on ne garde que les lignes dont le `TargetFolder` appartient bien au plan validé
(exemplaires sur-plan, ni cible inventée ni nom de fichier égaré), puis on
sélectionne un sous-ensemble couvrant le plus de dossiers cibles distincts.

C'est un **proxy d'évaluation** : de vraies corrections viennent de l'archiviste
. Ici, les bonnes classifications du run servent d'exemplaires pour mesurer
si les re-présenter en few-shot rend un re-run plus régulier
(`itemsMalformed`/`extensionsFixed`/`foldersMissing` ↓). **Métadonnées seules**
(chemin → dossier cible + nom) — jamais de contenu.

Pur et déterministe (aucun appel LLM, aucun réseau).

Usage::

    python scripts/make_corrections_from_run.py OUT_DIR [--out corrections.csv] [--max N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Le moteur vit dans backend/ — on l'ajoute au chemin d'import.
BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pandas as pd  # noqa: E402

from core.corrections import (  # noqa: E402
    CORRECTION_COLUMNS,
    normalize_corrections,
    select_examples,
)
from core.csv_handler import extract_csv_from_response, parse_plan_tree  # noqa: E402


def _read_raw_classement(out_dir: Path) -> str:
    """Concatène les réponses brutes de classement (`raw/*.txt`) d'un run."""
    raw_dir = out_dir / "raw"
    parts: list[str] = []
    if raw_dir.is_dir():
        for raw in sorted(raw_dir.glob("*.txt")):
            parts.append(raw.read_text(encoding="utf-8"))
    return "\n".join(parts)


def build_corrections_df(out_dir: Path, *, max_rows: int = 12) -> pd.DataFrame:
    """Dérive les corrections d'un run de référence : lignes de classement dont
    le `TargetFolder` est **dans le plan validé**, dédoublonnées par chemin,
    diversifiées par dossier cible (au plus `max_rows`). Renvoie un DataFrame
    `Path;TargetFolder;NewTitle` (vide si rien d'exploitable)."""
    plan_path = out_dir / "plan.md"
    if not plan_path.is_file():
        raise SystemExit(f"Plan introuvable : {plan_path} (lancer d'abord `odacea run --out-dir`).")
    plan_tree = parse_plan_tree(plan_path.read_text(encoding="utf-8"))
    raw = _read_raw_classement(out_dir)
    if not raw.strip():
        raise SystemExit(f"Aucune réponse de classement dans {out_dir / 'raw'}.")

    df = extract_csv_from_response(raw, id_col="Path")
    df = normalize_corrections(df)  # restreint aux 3 colonnes + nettoie
    # Exemplaires « propres » : la cible doit être un dossier réel du plan
    # (élimine cibles inventées, noms de fichiers égarés, hallucinations).
    on_plan = df[df["TargetFolder"].isin(plan_tree.keys())].copy()
    on_plan = on_plan.drop_duplicates(subset=["Path"]).reset_index(drop=True)
    # Sélection déterministe, diversifiée par dossier cible (même règle que la réinjection).
    selected = select_examples(on_plan, max_examples=max_rows)
    return pd.DataFrame(selected, columns=list(CORRECTION_COLUMNS))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir", help="Répertoire d'un run (odacea run --out-dir)")
    parser.add_argument("--out", default=None, help="Fichier corrections (défaut : OUT_DIR/corrections.csv)")
    parser.add_argument("--max", type=int, default=12, help="Nombre max d'exemples (défaut 12)")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    df = build_corrections_df(out_dir, max_rows=args.max)
    if df.empty:
        print("Aucun exemplaire sur-plan exploitable — corrections vides.", file=sys.stderr)
        return 1
    dest = Path(args.out) if args.out else out_dir / "corrections.csv"
    df.to_csv(dest, sep=";", index=False)
    print(f"{len(df)} correction(s) écrite(s) → {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
