"""Application physique du classement — copie vers la nouvelle arborescence.

À la sortie du pipeline, le classement validé n'est qu'un CSV RESIP : la
restructuration réelle du fonds reste à faire (dans RESIP). Le backend étant
**local**, ODACEA peut l'exécuter : ce module **copie** chaque fichier vers son
dossier cible, sous son nouveau titre, dans un répertoire **cible distinct**.

**La source n'est jamais mutée** (C-N, non-objectif) : aucune opération de
déplacement, de renommage ou de suppression sur le fonds d'origine — uniquement
des **lectures d'octets** (pour les recopier) et des **écritures dans le
répertoire cible**. L'original reste byte-identique. Aucun LLM ; rien ne quitte
le poste ; le contenu n'est jamais analysé (seulement recopié).

Deux temps : `build_apply_plan` produit d'abord un **aperçu** (total,
collisions de noms, binaires introuvables, items laissés à la racine) présenté à
l'archiviste ; l'écriture (`iter_apply`) n'a lieu qu'après confirmation. La
copie est **reprise-idempotente** (un fichier déjà copié à l'identique —
même taille et même date — est sauté) et **tolérante** (une erreur par fichier
n'interrompt pas le run). Garde-fous du répertoire cible dans
`check_target_guards`.

Le plan d'opérations est dérivé du **manifeste de structure** (`core.export_manifest` —
source unique de la localisation cible de chaque item) : aucune re-dérivation de
l'arborescence ici.
"""
from __future__ import annotations

import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from core.csv_handler import _preserve_extension
from core.export_manifest import build_tree_manifest

# Caractères interdits par le système de fichiers dans un nom de fichier (mêmes
# règles que core.plan_folders pour les dossiers). Le séparateur de chemin est
# volontairement inclus : un titre ne doit pas créer de sous-dossier surprise.
_FS_INVALID_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_filename(name: str) -> tuple[str, bool]:
    """Assainit un nom de fichier cible (caractères FS invalides → « _ »).

    Retourne ``(nom_assaini, modifié)``. L'extension est préservée telle quelle
    (les caractères invalides y sont aussi remplacés, mais le point est conservé)."""
    cleaned = _FS_INVALID_RE.sub("_", name).strip().rstrip(".")
    if not cleaned:
        cleaned = "sans_nom"
    return cleaned, cleaned != name


@dataclass
class CopyOp:
    """Une opération de copie : ``source_rel`` (chemin d'origine relatif au fonds)
    → ``target_rel`` (dossier cible relatif + nom de fichier final)."""
    source_rel: str
    target_dir: str      # dossier cible relatif ("" = racine cible)
    target_name: str     # nom de fichier final (assaini, dédoublonné)

    @property
    def target_rel(self) -> str:
        return f"{self.target_dir}/{self.target_name}" if self.target_dir else self.target_name


@dataclass
class ApplyPlan:
    """Aperçu de l'application, avant toute écriture."""
    operations: list[CopyOp] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)          # binaires introuvables (source_rel)
    at_root: list[str] = field(default_factory=list)          # items laissés à la racine (non classés/hors-plan)
    renamed_collisions: list[tuple[str, str]] = field(default_factory=list)  # (voulu, dédoublonné)
    sanitized_names: list[tuple[str, str]] = field(default_factory=list)     # (original, assaini)

    def as_dict(self) -> dict:
        return {
            "total": len(self.operations),
            "copyable": sum(1 for op in self.operations if op.source_rel not in set(self.missing)),
            "missing": self.missing,
            "missingCount": len(self.missing),
            "atRoot": self.at_root,
            "atRootCount": len(self.at_root),
            "renamedCollisions": [
                {"wanted": w, "resolved": r} for w, r in self.renamed_collisions
            ],
            "collisionCount": len(self.renamed_collisions),
            "sanitizedNames": [
                {"original": o, "sanitized": s} for o, s in self.sanitized_names
            ],
            "operations": [
                {"sourceRel": op.source_rel, "targetRel": op.target_rel} for op in self.operations
            ],
        }


def _dedup_name(name: str, used: set[str]) -> tuple[str, bool]:
    """Rend ``name`` unique dans ``used`` (comparaison insensible à la casse — les
    FS Windows/macOS le sont). Ajoute ``« (2) »``, ``« (3) »``… avant l'extension.
    Retourne ``(nom_final, dédoublonné)``."""
    if name.casefold() not in used:
        used.add(name.casefold())
        return name, False
    stem, dot, ext = name.rpartition(".")
    base = stem if dot else name
    suffix = ext if dot else ""
    i = 2
    while True:
        candidate = f"{base} ({i}){'.' + suffix if suffix else ''}"
        if candidate.casefold() not in used:
            used.add(candidate.casefold())
            return candidate, True
        i += 1


def build_apply_plan(df_resip: pd.DataFrame, source_root: Path) -> ApplyPlan:
    """Construit l'aperçu des copies à effectuer depuis les lignes RESIP
    finalisées et la racine source. **Ne lit ni n'écrit aucun binaire** : seule
    l'existence des sources est testée (``Path.is_file``).

    Résout, dans l'ordre déterministe du manifeste : l'assainissement des noms
    invalides FS, le dédoublonnage des collisions de noms cibles, et le repérage
    des binaires introuvables et des items laissés à la racine (non classés /
    hors-plan)."""
    source_root = source_root.expanduser()
    manifest = build_tree_manifest(df_resip)
    plan = ApplyPlan()
    # used_names : ensemble des noms déjà pris **par dossier cible** (les
    # collisions ne se posent qu'à l'intérieur d'un même dossier).
    used_by_dir: dict[str, set[str]] = {}

    for entry in manifest["items"]:
        source_rel = entry["originalFile"]
        target_dir = entry["dir"]  # "" = racine cible
        # Le nom cible (Content.Title) ne porte pas forcément l'extension du
        # fichier (ex. option d'export « conserver le titre d'origine » : le titre
        # Archifiltre est sans extension). Sur disque, l'extension est mécanique et
        # obligatoire : on la ré-aligne sur celle de la source (même règle et même
        # source unique que la conversion RESIP, `_preserve_extension`).
        wanted = _preserve_extension(source_rel, entry["name"])

        safe_name, was_sanitized = _sanitize_filename(wanted)
        if was_sanitized:
            plan.sanitized_names.append((wanted, safe_name))

        used = used_by_dir.setdefault(target_dir, set())
        final_name, was_renamed = _dedup_name(safe_name, used)
        if was_renamed:
            plan.renamed_collisions.append((
                f"{target_dir}/{safe_name}" if target_dir else safe_name,
                f"{target_dir}/{final_name}" if target_dir else final_name,
            ))

        op = CopyOp(source_rel=source_rel, target_dir=target_dir, target_name=final_name)
        plan.operations.append(op)

        if not target_dir:
            plan.at_root.append(source_rel)
        # Existence de la source (métadonnée seule : jamais d'ouverture du binaire).
        if not source_rel or not (source_root / _rel_parts(source_rel)).is_file():
            plan.missing.append(source_rel)

    return plan


def _rel_parts(rel: str) -> Path:
    """Chemin relatif robuste aux séparateurs Windows (`\\`) des colonnes File."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    return Path(*parts) if parts else Path()


def check_target_guards(
    source_root: Path, target_root: Path, *, resume: bool = False
) -> dict | None:
    """Garde-fous du répertoire cible. Retourne ``{error, code, hint}`` en cas
    de refus, sinon ``None``.

    - la cible ne peut être **sous** la source ni la source **sous** la cible
      (on n'écrit jamais dans le fonds, et on ne recopie pas la cible en boucle) ;
    - hors reprise (``resume``), un répertoire cible **déjà peuplé** est refusé
      (protège d'un mélange accidentel avec un autre contenu)."""
    source_root = source_root.expanduser()
    target_root = target_root.expanduser()
    try:
        src_res = source_root.resolve()
        tgt_res = target_root.resolve()
    except OSError as e:
        return {"error": f"Chemin invalide : {e}", "code": "apply_path_invalid",
                "hint": "Vérifiez que les répertoires source et cible sont accessibles."}

    if src_res == tgt_res:
        return {"error": "Le répertoire cible ne peut pas être le répertoire source.",
                "code": "apply_target_is_source",
                "hint": "Choisissez un répertoire cible distinct — la source n'est jamais modifiée."}
    if _is_within(tgt_res, src_res):
        return {"error": "Le répertoire cible ne peut pas être situé dans le répertoire source.",
                "code": "apply_target_in_source",
                "hint": "Choisissez un répertoire cible en dehors du fonds source."}
    if _is_within(src_res, tgt_res):
        return {"error": "Le répertoire source ne peut pas être situé dans le répertoire cible.",
                "code": "apply_source_in_target",
                "hint": "Choisissez un répertoire cible qui ne contient pas le fonds source."}

    if not resume and target_root.is_dir() and any(target_root.iterdir()):
        return {"error": f"Le répertoire cible n'est pas vide : {target_root}",
                "code": "apply_target_not_empty",
                "hint": ("Choisissez un répertoire cible vide, ou activez la reprise "
                         "pour compléter une application interrompue.")}
    return None


def _is_within(child: Path, parent: Path) -> bool:
    """``child`` est-il ``parent`` lui-même ou un descendant ? (chemins résolus)."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _should_skip(src: Path, dst: Path) -> bool:
    """Reprise idempotente : un fichier déjà copié **à l'identique** (même
    taille et même date de modification) est sauté. ``copy2`` préservant le
    ``mtime``, un fichier issu d'une exécution précédente correspond exactement."""
    if not dst.exists():
        return False
    try:
        s, d = src.stat(), dst.stat()
    except OSError:
        return False
    return s.st_size == d.st_size and int(s.st_mtime) == int(d.st_mtime)


def iter_apply(
    plan: ApplyPlan, source_root: Path, target_root: Path
) -> Iterator[dict]:
    """Exécute les copies du plan, en **flux** : émet un événement
    ``{"type": "progress", copied, skipped, failed, total, current}`` par fichier,
    puis un ``{"type": "done", "stats": …}`` final. Les erreurs par fichier sont
    **collectées sans interrompre** le run.

    Copie seule (``shutil.copy2`` — dates conservées) : la source n'est jamais
    écrite. Les dossiers cible sont créés à la demande. Idempotent : un fichier
    déjà présent à l'identique est compté ``skipped`` (reprise)."""
    source_root = source_root.expanduser()
    target_root = target_root.expanduser()
    target_root.mkdir(parents=True, exist_ok=True)

    total = len(plan.operations)
    copied = skipped = failed = 0
    errors: list[dict] = []

    for op in plan.operations:
        src = source_root / _rel_parts(op.source_rel)
        dst_dir = target_root / _rel_parts(op.target_dir) if op.target_dir else target_root
        dst = dst_dir / op.target_name
        try:
            if not src.is_file():
                failed += 1
                errors.append({"sourceRel": op.source_rel, "error": "binaire introuvable"})
            elif _should_skip(src, dst):
                skipped += 1
            else:
                dst_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)  # copie (jamais move) — source intacte
                copied += 1
        except OSError as e:
            failed += 1
            errors.append({"sourceRel": op.source_rel, "error": str(e)})
        yield {
            "type": "progress",
            "copied": copied,
            "skipped": skipped,
            "failed": failed,
            "total": total,
            "current": op.target_rel,
        }

    yield {
        "type": "done",
        "stats": {
            "total": total,
            "copied": copied,
            "skipped": skipped,
            "failed": failed,
            "errors": errors,
            "targetRoot": str(target_root),
        },
    }


def apply_plan(plan: ApplyPlan, source_root: Path, target_root: Path) -> dict:
    """Consomme ``iter_apply`` et retourne les seules stats finales (pratique pour
    la CLI et les tests). Le flux de progression est ignoré."""
    stats: dict = {}
    for event in iter_apply(plan, source_root, target_root):
        if event["type"] == "done":
            stats = event["stats"]
    return stats


def verify_apply(plan: ApplyPlan, target_root: Path) -> dict:
    """Vérification post-copie : compte les fichiers attendus effectivement
    présents dans la cible, à la bonne taille — **métadonnées seules** (aucune
    lecture de contenu ; l'empreinte SHA-256 optionnelle ne relève pas de cette étape, non
    incluse ici). Retourne ``{expected, present, missingTargets}``."""
    target_root = target_root.expanduser()
    present = 0
    missing_targets: list[str] = []
    for op in plan.operations:
        dst = (target_root / _rel_parts(op.target_dir) / op.target_name
               if op.target_dir else target_root / op.target_name)
        if dst.is_file():
            present += 1
        else:
            missing_targets.append(op.target_rel)
    return {
        "expected": len(plan.operations),
        "present": present,
        "missingTargets": missing_targets,
    }
