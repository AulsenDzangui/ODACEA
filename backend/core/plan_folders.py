"""Maîtrise du plan de classement par l'archiviste.

Deux voies, **sans aucun appel LLM** :

- **Adopter un plan fourni** : convertir un plan que l'archiviste apporte
  déjà (CSV Resip « dossiers seuls » ou bloc Markdown canonique) en un document de
  plan minimal **parsable par `csv_handler.parse_plan_tree`**, adopté directement
  comme plan validé (bypass de l'audit LLM).
- **Éditer par l'explorateur de fichiers** : *matérialiser* l'arborescence du
  plan en **dossiers vides réels** sur le poste (`materialize_plan`), laisser
  l'archiviste la réorganiser avec ses gestes habituels, puis *re-scanner* le
  répertoire (`scan_folder_tree`) pour reconstruire le plan canonique.

Tout le métier vit ici, côté moteur ; les interfaces (API, CLI, et
via l'API le front) ne transmettent qu'un chemin ou un texte. **Aucun contenu
documentaire n'est lu ni écrit** : la matérialisation crée des dossiers *vides*, le
scan ne lit que des **noms** de dossiers et ignore les fichiers . Rien d'autre
que `pathlib`/`os` standard — aucune dépendance nouvelle.

Format canonique : le bloc « Arborescence technique » du gabarit AUD-001, identique
à celui produit par l'éditeur structuré du front (`web/lib/csv/plan-edit.ts`), donc
directement parsable par `parse_plan_tree`. Les **préfixes numériques** (`1_`,
`1-1_`…) sont **recalculés depuis la position** de chaque nœud à la sérialisation ;
le nom technique « nu » (slug) ne porte pas de préfixe. Cela garantit un round-trip
fidèle : *matérialiser puis re-scanner sans modification restitue un plan
strictement identique* (testé) — les noms de dossiers matérialisés se re-trient
et se re-numérotent à l'identique.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from core.csv_handler import parse_plan_tree

# Nom technique de la racine (placeholder mappé au nœud File="." côté Python) —
# jamais un vrai dossier, donc exclu de l'arbre matérialisé. Identique au front.
ROOT_PLACEHOLDER = "Dossier_racine"

# En-tête du bloc, copié verbatim du gabarit AUD-001 / de l'éditeur front
# (`plan-edit.ts::BLOCK_HEADER`) : la présence de « Arborescence technique » ancre
# `_arborescence_block` du parseur.
BLOCK_HEADER = (
    "**Arborescence technique** *(chaque dossier porte son titre descriptif puis "
    "son nom technique, séparés par « → » ; dossiers uniquement, jamais de fichiers "
    "individuels)* **:**"
)

# Préfixe numérique de position en tête d'un nom technique (« 1_ », « 1-2_ »…).
# Retiré pour obtenir le slug « nu » ; recalculé à la sérialisation. Miroir de
# `plan-edit.ts::NUMERIC_PREFIX_RE`.
_NUMERIC_PREFIX_RE = re.compile(r"^\d+(?:-\d+)*_")


@dataclass
class PlanNode:
    """Un dossier du plan : titre descriptif + slug (nom technique nu, sans préfixe
    numérique) + sous-dossiers. Le préfixe (`1-2`) est recalculé à la position."""

    title: str
    slug: str
    children: list[PlanNode] = field(default_factory=list)


# ── Slugification (miroir de plan-edit.ts::slugify) ──────────────────────────

def slugify(title: str) -> str:
    """Nom technique « nu » dérivé d'un titre : accents retirés, tout caractère hors
    ``[A-Za-z0-9]`` réduit à « _ » (le « - » compris, réservé au préfixe de
    position). Idempotent sur un slug déjà propre → round-trip stable."""
    text = unicodedata.normalize("NFD", title or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "Nouveau_dossier"


def _strip_numeric_prefix(name: str) -> str:
    """Nom technique « nu » : préfixe numérique de position retiré s'il existe."""
    return _NUMERIC_PREFIX_RE.sub("", name.strip())


def _humanize(slug: str) -> str:
    """Titre descriptif de repli dérivé d'un slug (« _ » → espace)."""
    return re.sub(r"_+", " ", slug).strip() or slug


def _safe_title(title: str) -> str:
    """Titre sans flèche : « → » casserait le découpage titre/nom technique."""
    return re.sub(r"\s*(?:→|->)\s*", " - ", title or "").strip()


# ── Sérialisation vers le bloc « Arborescence technique » canonique ──────────
# Miroir déterministe de plan-edit.ts::serializePlanTreeText / serializePlanBlock.

def serialize_plan_tree_text(
    nodes: list[PlanNode], root_title: str, *, root_slug: str = ROOT_PLACEHOLDER
) -> str:
    """Contenu du fence ```text``` : l'arbre dessiné, préfixes recalculés depuis la
    position. Parsable à l'identique par `parse_plan_tree`."""
    lines: list[str] = [
        f"Fonds — {_safe_title(root_title) or '[Nom du fonds]'} → {root_slug}/"
    ]

    def render(node: PlanNode, number_parts: list[int], indent: str, is_last: bool) -> None:
        number = ".".join(str(n) for n in number_parts) + "."
        tech = "-".join(str(n) for n in number_parts) + "_" + node.slug
        connector = "└──" if is_last else "├──"
        lines.append(f"{indent}{connector} {number} {_safe_title(node.title)} → {tech}/")
        child_indent = indent + ("      " if is_last else "│     ")
        for i, child in enumerate(node.children):
            render(child, number_parts + [i + 1], child_indent, i == len(node.children) - 1)

    for i, node in enumerate(nodes):
        lines.append("  │")  # séparateur visuel entre groupes de premier niveau
        render(node, [i + 1], "  ", i == len(nodes) - 1)

    return "\n".join(lines)


def serialize_plan_block(
    nodes: list[PlanNode], root_title: str, *, root_slug: str = ROOT_PLACEHOLDER
) -> str:
    """Bloc complet : en-tête du gabarit + fence ```text```. C'est le document de
    plan minimal adopté comme plan validé ou reconstruit par scan."""
    body = serialize_plan_tree_text(nodes, root_title, root_slug=root_slug)
    return f"{BLOCK_HEADER}\n\n```text\n{body}\n```"


def _flatten_slugs(nodes: list[PlanNode]) -> int:
    return sum(1 + _flatten_slugs(n.children) for n in nodes)


# ── adopter un plan « dossiers seuls » (CSV Resip) ──────────────────────

def _sort_id_key(value: str):
    """Tri stable des enfants par ID : numérique si possible, lexical en repli."""
    s = str(value).strip()
    if s.lstrip("-").isdigit():
        return (0, int(s), "")
    return (1, 0, s)


def plan_nodes_from_folders_df(
    df: pd.DataFrame,
) -> tuple[list[PlanNode], str, list[str], dict]:
    """Convertit un CSV Resip « dossiers seuls » en arbre `PlanNode` **renuméroté**
    canoniquement (contrairement à `build_reference_tree_from_folders`, qui
    conserve les noms verbatim comme *contexte-guide* d'audit non reparsé).

    - Ne retient que les ``RecordGrp`` ; les ``Item`` sont **ignorés** (warning).
    - Le slug d'un dossier vient de son nom de dossier (colonne ``File``), préfixe
      numérique retiré ; le titre descriptif vient de ``Content.Title`` (repli sur
      le slug humanisé). La hiérarchie vient des ``ParentID``.

    Retourne ``(nodes, root_title, warnings, stats)``. Lève ``ValueError`` si aucun
    dossier (``RecordGrp``).
    """
    level = df.get("Content.DescriptionLevel")
    warnings: list[str] = []
    item_count = int((level == "Item").sum()) if level is not None else 0
    if item_count:
        warnings.append(
            f"{item_count} ligne(s) fichier (Item) ignorée(s) — "
            "seuls les dossiers sont retenus pour le plan."
        )

    folders = (
        df[df["Content.DescriptionLevel"] == "RecordGrp"].copy()
        if level is not None
        else df.iloc[0:0].copy()
    )
    if folders.empty:
        raise ValueError(
            "Aucun dossier (RecordGrp) trouvé : ce CSV ne décrit pas d'arborescence."
        )

    ids = folders["ID"].fillna("").astype(str).str.strip()
    parent_ids = folders["ParentID"].fillna("").astype(str).str.strip()
    files = folders["File"].fillna("").astype(str)
    titles = folders["Content.Title"].fillna("").astype(str)

    id_set = set(ids)
    root_mask = (files.str.strip() == ".") & (parent_ids == "")

    node_title: dict[str, str] = {}
    node_slug: dict[str, str] = {}
    children: dict[str, list[str]] = {}
    top_ids: list[str] = []
    explicit_root: str | None = None
    root_title = "Plan de classement"

    for idx, node_id in ids.items():
        title = titles[idx].strip()
        if root_mask[idx]:
            explicit_root = node_id
            root_title = title or root_title
            continue
        base = files[idx].rsplit("/", 1)[-1].strip()
        slug = slugify(_strip_numeric_prefix(base) or title)
        node_slug[node_id] = slug
        node_title[node_id] = title or _humanize(slug)
        parent = parent_ids[idx]
        # Enfant d'un vrai dossier de plan ; un dossier parenté sous la racine
        # explicite (File=".") — ou orphelin — devient un dossier de premier niveau.
        if parent and parent in id_set and parent != explicit_root:
            children.setdefault(parent, []).append(node_id)
        else:
            top_ids.append(node_id)

    for kids in children.values():
        kids.sort(key=_sort_id_key)
    top_ids.sort(key=_sort_id_key)

    def build(node_id: str) -> PlanNode:
        return PlanNode(
            title=node_title[node_id],
            slug=node_slug[node_id],
            children=[build(k) for k in children.get(node_id, [])],
        )

    nodes = [build(i) for i in top_ids]
    stats = {"folderCount": _flatten_slugs(nodes), "ignoredItemCount": item_count}
    return nodes, root_title, warnings, stats


# ── adopter un plan Markdown (bloc canonique déjà écrit) ────────────────

def adopt_markdown_plan(text: str) -> tuple[str, list[str]]:
    """Adopte un plan Markdown fourni (typiquement exporté d'un projet ODACEA
    antérieur). Le texte est conservé tel quel s'il contient une arborescence
    technique **exploitable** ; sinon une ``ValueError`` explicite est levée.

    Retourne ``(plan_valide, warnings)``."""
    tree = parse_plan_tree(text)
    if not tree:
        raise ValueError(
            "Aucune arborescence technique exploitable dans ce fichier : le plan "
            "doit contenir des lignes « titre → nom_technique/ » (bloc « Arborescence "
            "technique »)."
        )
    warnings: list[str] = []
    return text.strip(), warnings


def looks_like_csv(name: str, content: str) -> bool:
    """Heuristique de routage d'un plan importé : CSV Resip « dossiers seuls »
    (extension ``.csv`` ou première ligne à séparateur « ; ») vs bloc Markdown."""
    if (name or "").lower().endswith(".csv"):
        return True
    if (name or "").lower().endswith((".md", ".markdown", ".txt")):
        return False
    first = content.splitlines()[0] if content.strip() else ""
    return ";" in first and "→" not in content and "->" not in content


# ── matérialiser le plan en dossiers vides réels ────────────────────────

# Caractères interdits par le système de fichiers Windows dans un nom de dossier.
_FS_INVALID_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_FS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def _folder_full_parts(folder: str, tree: dict) -> list[str]:
    """Chaîne de noms techniques de la racine jusqu'à ``folder`` (inclus)."""
    parts: list[str] = []
    seen: set[str] = set()
    cur: str | None = folder
    while cur is not None and cur not in seen:
        parts.append(cur)
        seen.add(cur)
        cur = tree.get(cur)
    return list(reversed(parts))


def materialize_plan(plan_valide: str, root: Path, *, clear: bool = False) -> dict:
    """Écrit l'arborescence technique du plan en **dossiers vides** sous ``root``.

    Chaque dossier porte son **nom technique verbatim** (`1-1_Inscriptions_effectifs`)
    — le tri alphabétique de l'Explorateur restitue l'ordre du plan grâce aux
    préfixes. Aucun fichier n'est créé . ``clear=True`` **vide d'abord** le
    répertoire de travail (uniquement son contenu — jamais ``root`` lui-même ni quoi
    que ce soit au-dehors) : réservé à une action explicite et confirmée par
    l'archiviste (garde-fou appliqué par l'appelant).

    Lève ``ValueError`` si le plan n'a pas d'arborescence exploitable.
    """
    tree = parse_plan_tree(plan_valide)
    if not tree:
        raise ValueError(
            "Le plan ne contient aucune arborescence technique exploitable à "
            "matérialiser."
        )

    root = root.expanduser()
    root.mkdir(parents=True, exist_ok=True)
    if clear:
        _clear_directory(root)

    created = 0
    for folder in tree:
        target = root.joinpath(*_folder_full_parts(folder, tree))
        # Garde-fou : ne jamais écrire hors de root (un nom technique validé ne
        # contient ni « / » ni « .. », mais on vérifie par principe).
        target.mkdir(parents=True, exist_ok=True)
        created += 1

    return {"folderCount": created, "root": str(root)}


def _clear_directory(root: Path) -> None:
    """Supprime **le contenu** de ``root`` (dossiers vides du plan précédent), jamais
    ``root`` lui-même ni rien au-dehors. Refuse de supprimer un dossier non vide de
    fichiers pour ne pas détruire de contenu documentaire ."""
    import shutil

    for entry in root.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()


# ── re-scanner le répertoire → plan canonique reconstruit ───────────────

def _scan_sort_key(name: str):
    """Ordre des dossiers frères au scan : par préfixe numérique quand présent
    (tri *naturel*, donc `10_…` après `2_…`), puis les noms libres, alphabétique.
    Reproduit l'ordre du plan pour un round-trip fidèle, et reste sensé pour des
    dossiers créés à la main sans préfixe."""
    prefix = name.split("_", 1)[0]
    parts = prefix.split("-")
    if all(p.isdigit() for p in parts) and parts != [""]:
        return (0, [int(p) for p in parts], name.lower())
    return (1, [], name.lower())


def scan_folder_tree(root: Path) -> tuple[list[PlanNode], str, list[str], dict]:
    """Re-scanne un répertoire de travail et reconstruit l'arbre `PlanNode`
    canonique : slugification des noms libres, préfixes recalculés depuis le tri
    (`scan_folder_tree` ne pose pas les préfixes — la sérialisation le fait depuis
    la position). Les **fichiers présents sont ignorés et signalés** .

    Retourne ``(nodes, root_title, warnings, stats)``. Lève ``ValueError`` si
    ``root`` n'est pas un répertoire."""
    root = root.expanduser()
    if not root.is_dir():
        raise ValueError(f"Répertoire introuvable : {root}")

    warnings: list[str] = []
    ignored_files = 0
    invalid_names: list[str] = []

    def walk(dir_path: Path) -> list[PlanNode]:
        nonlocal ignored_files
        try:
            entries = list(os.scandir(dir_path))
        except OSError as e:  # dossier illisible : signalé, non bloquant
            warnings.append(f"Dossier illisible ignoré : {dir_path.name} ({e})")
            return []
        subdirs = [e for e in entries if e.is_dir()]
        ignored_files += sum(1 for e in entries if e.is_file())
        subdirs.sort(key=lambda e: _scan_sort_key(e.name))

        nodes: list[PlanNode] = []
        for entry in subdirs:
            bare = _strip_numeric_prefix(entry.name)
            slug = slugify(bare)
            if _FS_INVALID_RE.search(entry.name) or bare.lower() in _FS_RESERVED:
                invalid_names.append(entry.name)
            nodes.append(
                PlanNode(title=_humanize(slug), slug=slug, children=walk(Path(entry.path)))
            )
        return nodes

    nodes = walk(root)
    root_title = _humanize(slugify(root.name)) or "Plan de classement"

    if ignored_files:
        warnings.append(
            f"{ignored_files} fichier(s) présent(s) dans le répertoire de travail "
            "ignoré(s) — seuls les dossiers structurent le plan."
        )
    if invalid_names:
        warnings.append(
            "Nom(s) de dossier normalisé(s) (caractères invalides FS/SEDA) : "
            + ", ".join(sorted(set(invalid_names))[:10])
        )
    if not nodes:
        warnings.append(
            "Aucun dossier trouvé dans le répertoire — le plan reconstruit est vide."
        )

    stats = {"folderCount": _flatten_slugs(nodes), "ignoredFileCount": ignored_files}
    return nodes, root_title, warnings, stats


# ── Aperçu des changements : plan courant ↔ plan re-scanné ──────────────

def _slug_paths(nodes: list[PlanNode], prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Ensemble des « chemins de slugs » (racine→feuille) d'un arbre — clé
    d'identité indépendante des préfixes numériques."""
    paths: list[tuple[str, ...]] = []
    for node in nodes:
        here = prefix + (node.slug,)
        paths.append(here)
        paths.extend(_slug_paths(node.children, here))
    return paths


def plan_nodes_from_plan_text(plan_valide: str) -> list[PlanNode]:
    """Reconstruit un arbre `PlanNode` (slugs nus, titres humanisés) depuis le texte
    d'un plan validé — pour comparer un plan courant au plan re-scanné."""
    from core.csv_handler import parse_plan_titles

    tree = parse_plan_tree(plan_valide)
    titles = parse_plan_titles(plan_valide)
    made: dict[str, PlanNode] = {}
    for name in tree:
        slug = _strip_numeric_prefix(name)
        made[name] = PlanNode(title=titles.get(name) or _humanize(slug), slug=slug)
    roots: list[PlanNode] = []
    for name, node in made.items():
        parent = tree[name]
        if parent is not None and parent in made:
            made[parent].children.append(node)
        else:
            roots.append(node)
    return roots


def diff_plans(current_nodes: list[PlanNode], scanned_nodes: list[PlanNode]) -> dict:
    """Aperçu **best-effort** des changements entre deux arbres de plan,
    exprimé en chemins de slugs (« Rubrique/Sous-rubrique ») :

    - ``renamed`` : même parent, dossier renommé (sous-arbre inchangé) ;
    - ``moved`` : même nom, parent différent (sous-arbre inchangé) ;
    - ``added`` / ``removed`` : le reste.

    Un dossier renommé/déplacé **absorbe son sous-arbre** : ses descendants ne sont
    pas re-signalés (on apparie les nœuds les plus hauts d'abord, en exigeant une
    signature de sous-arbre identique). Diff structurel indicatif — suffisant pour
    un aperçu avant adoption, pas un calcul d'édition minimal."""
    old = {tuple(p) for p in _slug_paths(current_nodes)}
    new = {tuple(p) for p in _slug_paths(scanned_nodes)}
    removed = old - new
    added = new - old

    def fmt(path: tuple[str, ...]) -> str:
        return "/".join(path)

    def subtree_sig(paths: set[tuple[str, ...]], p: tuple[str, ...]) -> frozenset:
        """Signature d'un sous-arbre : chemins de slugs des descendants, relatifs à
        ``p`` — inchangée par un renommage/déplacement de ``p`` lui-même."""
        n = len(p)
        return frozenset(q[n:] for q in paths if len(q) > n and q[:n] == p)

    matched_rem: set[tuple[str, ...]] = set()
    matched_add: set[tuple[str, ...]] = set()

    def absorb(r: tuple[str, ...], a: tuple[str, ...]) -> None:
        for q in removed:
            if q[: len(r)] == r:
                matched_rem.add(q)
        for q in added:
            if q[: len(a)] == a:
                matched_add.add(q)

    renamed: list[dict] = []
    moved: list[dict] = []

    def order(path: tuple[str, ...]) -> tuple:
        """Ordre de parcours : les nœuds les plus hauts d'abord, puis
        alphabétique. Le second critère est indispensable — trier sur la seule
        profondeur laisse les ex æquo dans l'ordre d'itération d'un `set`, qui
        varie d'une exécution à l'autre : l'aperçu ne serait pas reproductible."""
        return (len(path), path)

    def closest(ref: str, candidates: list[tuple[str, ...]], part) -> tuple | None:
        """Parmi les candidats équivalents (même signature de sous-arbre), celui
        dont le nom **ressemble le plus** à `ref`. Sans ce départage, deux nœuds
        interchangeables s'apparient dans l'ordre de parcours et l'aperçu annonce
        un renommage que l'archiviste n'a pas fait. `part` extrait du candidat le
        fragment comparé (son nom pour un renommage, son parent pour un
        déplacement — où le nom, lui, est identique par construction)."""
        if not candidates:
            return None
        return max(candidates, key=lambda a: SequenceMatcher(None, ref, part(a)).ratio())

    # Nœuds les plus hauts d'abord : apparier un parent absorbe ses descendants.
    for r in sorted(removed, key=order):
        if r in matched_rem:
            continue
        r_sig = subtree_sig(old, r)
        a = closest(r[-1], [
            a for a in sorted(added, key=order)
            if a not in matched_add
            and r[:-1] == a[:-1] and r[-1] != a[-1]
            and subtree_sig(new, a) == r_sig
        ], lambda a: a[-1])
        if a is not None:
            renamed.append({"from": fmt(r), "to": fmt(a)})
            absorb(r, a)

    for r in sorted(removed, key=order):
        if r in matched_rem:
            continue
        r_sig = subtree_sig(old, r)
        # Un déplacement conserve le nom : le départage porte sur le parent.
        a = closest(fmt(r[:-1]), [
            a for a in sorted(added, key=order)
            if a not in matched_add
            and r[-1] == a[-1] and r[:-1] != a[:-1]
            and subtree_sig(new, a) == r_sig
        ], lambda a: fmt(a[:-1]))
        if a is not None:
            moved.append({"from": fmt(r), "to": fmt(a)})
            absorb(r, a)

    final_added = sorted(fmt(a) for a in added - matched_add)
    final_removed = sorted(fmt(r) for r in removed - matched_rem)
    return {
        "added": final_added,
        "removed": final_removed,
        "renamed": renamed,
        "moved": moved,
        "unchanged": len(old & new),
        "identical": not (added or removed),
    }
