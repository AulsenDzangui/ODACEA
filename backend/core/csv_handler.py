import csv
import io
import re

import pandas as pd

REQUIRED_COLUMNS = [
    "ID",
    "ParentID",
    "File",
    "Content.DescriptionLevel",
    "Content.Title",
    "Content.StartDate",
    "Content.EndDate",
]

VALID_DESCRIPTION_LEVELS = [
    "RecordGrp", "SubGrp", "Series",
    "Subseries", "File", "Item", "OtherLevel",
]


# ── Lecture ────────────────────────────────────────────────────────────────────

def _is_int(s: str) -> bool:
    try:
        int(s)
        return True
    except (ValueError, TypeError):
        return False


def normalize_resip_export(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise un export Resip *natif* vers la forme canonique Archifiltre.

    Resip et Archifiltre exportent tous deux du SEDA, mais Resip diffère sur :
      - les colonnes ID : `Id`/`ParentId` au lieu de `ID`/`ParentID`
      - le chemin physique : colonne `ObjectFiles` (et `File` vide) au lieu de `File`
      - les IDs : texte `Import-1` au lieu d'entiers
      - la racine : `ParentId` vide sans marqueur `File="."`

    Toutes les étapes sont conditionnelles : sur un CSV Archifiltre déjà canonique,
    cette fonction est un no-op. Elle est donc appliquée systématiquement (pas de
    détection de format) et de façon transparente pour l'utilisateur. La sortie de
    l'application reste au format Archifiltre quelle que soit l'origine.
    """
    df = df.copy()

    # 1. Id/ParentId → ID/ParentID (insensible à la casse, seulement si canonique absent)
    lower = {c.lower(): c for c in df.columns}
    rename = {}
    for canon, variant in (("ID", "id"), ("ParentID", "parentid")):
        if canon not in df.columns and variant in lower:
            rename[lower[variant]] = canon
    if rename:
        df = df.rename(columns=rename)

    # 2. ObjectFiles → File (là où File est vide), puis suppression de ObjectFiles
    if "ObjectFiles" in df.columns:
        if "File" not in df.columns:
            df["File"] = ""
        empty = df["File"].fillna("").str.strip() == ""
        df.loc[empty, "File"] = df.loc[empty, "ObjectFiles"].fillna("")
        df = df.drop(columns=["ObjectFiles"])

    # 3. Marqueur racine File="." si aucune ligne ne le porte déjà
    if {"File", "ParentID"} <= set(df.columns):
        if not (df["File"].fillna("").str.strip() == ".").any():
            no_parent = df["ParentID"].fillna("").str.strip() == ""
            df.loc[no_parent, "File"] = "."

    # 4. IDs textuels (Import-N) → entiers séquentiels, ParentID réécrits en cohérence
    if "ID" in df.columns:
        ids = df["ID"].fillna("").astype(str).str.strip()
        present = [i for i in ids if i != ""]
        if present and not all(_is_int(i) for i in present):
            mapping = {old: str(n + 1) for n, old in enumerate(dict.fromkeys(present))}
            df["ID"] = ids.map(lambda x: mapping.get(x, x))
            if "ParentID" in df.columns:
                pid = df["ParentID"].fillna("").astype(str).str.strip()
                df["ParentID"] = pid.map(lambda x: mapping.get(x, x))

    return df


def read_csv(file_obj) -> pd.DataFrame:
    # utf-8-sig gère le BOM éventuel (exports Windows/Archifiltre)
    df = pd.read_csv(file_obj, sep=None, engine="python", encoding="utf-8-sig", dtype=str)
    # Normalise les exports Resip natifs vers la forme canonique Archifiltre
    # (no-op sur un CSV Archifiltre déjà conforme).
    return normalize_resip_export(df)


def csv_to_string(df: pd.DataFrame) -> str:
    return df.to_csv(index=False, sep=";")


def prepare_for_llm(
    df: pd.DataFrame,
    filter_columns: bool = True,
    clean_dates: bool = True,
    sample_items_n: int = 0,
    include_description: bool = True,
) -> pd.DataFrame:
    result = df.copy()
    if filter_columns:
        cols = [c for c in REQUIRED_COLUMNS if c in result.columns]
        # Conserver Content.Description pour l'audit dès que l'option est active
        # et que la colonne existe dans le CSV. On respecte le choix explicite
        # de l'archiviste : la colonne est incluse même si elle est vide partout
        # (le toggle « Inclure la description » fait alors seul autorité).
        # Placée en dernière position, comme dans le CSV RESIP source —
        # l'ordonnancement des colonnes est significatif. Le même toggle
        # gouverne aussi le classement (prepare_for_classement).
        desc_col = "Content.Description"
        if include_description and desc_col in result.columns:
            cols.append(desc_col)
        result = result[cols]
    if clean_dates and "Content.DescriptionLevel" in result.columns:
        is_item = result["Content.DescriptionLevel"] == "Item"
        for col in ("Content.StartDate", "Content.EndDate"):
            if col in result.columns:
                result.loc[is_item, col] = ""
    if sample_items_n > 0 and "Content.DescriptionLevel" in result.columns and "ParentID" in result.columns:
        is_item = result["Content.DescriptionLevel"] == "Item"
        folders = result[~is_item]
        items = result[is_item].copy()
        items["_parent"] = items["ParentID"].fillna("__root__")
        sampled = items.groupby("_parent", group_keys=False).head(sample_items_n).drop(columns=["_parent"])
        result = pd.concat([folders, sampled]).sort_index()
    return result


# ── Validation ─────────────────────────────────────────────────────────────────

def validate_csv(df: pd.DataFrame) -> list[str]:
    """Retourne une liste d'erreurs. Liste vide = CSV valide."""
    errors = []

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        errors.append(f"Colonnes manquantes : {', '.join(missing)}")

    if "Content.DescriptionLevel" in df.columns:
        invalid = df[~df["Content.DescriptionLevel"].isin(VALID_DESCRIPTION_LEVELS)]
        if not invalid.empty:
            errors.append(
                f"{len(invalid)} ligne(s) avec Content.DescriptionLevel invalide "
                f"(valeurs acceptées : {', '.join(VALID_DESCRIPTION_LEVELS)})"
            )

    if "ID" in df.columns:
        duplicates = df[df["ID"].duplicated(keep=False)]
        if not duplicates.empty:
            errors.append(f"{len(duplicates)} ID dupliqué(s) détecté(s)")

    return errors


def _count_date_inversions(df: pd.DataFrame) -> int:
    """Nombre de lignes dont la date de début est postérieure à la date de fin.

    Comparaison lexicographique cohérente avec le reste du module (dates SEDA
    en ISO 8601 ``AAAA-MM-JJ``, l'ordre lexicographique coïncide avec l'ordre
    chronologique). Seules les lignes où les deux bornes sont renseignées sont
    examinées : une borne vide n'est pas une inversion.
    """
    if not {"Content.StartDate", "Content.EndDate"} <= set(df.columns):
        return 0
    start = df["Content.StartDate"].fillna("").astype(str).str.strip()
    end = df["Content.EndDate"].fillna("").astype(str).str.strip()
    both = (start != "") & (end != "")
    return int((both & (start > end)).sum())


def _has_parent_cycle(parents: dict) -> bool:
    """Détecte un cycle dans la chaîne de parenté ``{ID: ParentID}``.

    Un SIP SEDA est un arbre : remonter les ParentID depuis n'importe quel nœud
    doit atteindre la racine sans jamais repasser sur un nœud déjà vu. On marque
    chaque nœud comme « sûr » une fois sa chaîne validée, de sorte que chaque
    nœud n'est visité qu'une fois — détection en une passe linéaire, robuste sur
    de gros versements (une boucle naïve serait quadratique sur une chaîne longue).
    """
    safe: set[str] = set()
    for start in parents:
        if start in safe:
            continue
        seen_in_path: set[str] = set()
        cur = start
        while cur in parents and cur not in safe:
            if cur in seen_in_path:
                return True
            seen_in_path.add(cur)
            cur = parents[cur]
        safe.update(seen_in_path)
    return False


def validate_output_csv(df: pd.DataFrame) -> list[str]:
    """Validation renforcée du CSV produit par CLA-001."""
    errors = validate_csv(df)

    if "ID" in df.columns and "ParentID" in df.columns:
        all_ids = set(df["ID"].dropna())
        parent_col = df["ParentID"].fillna("").astype(str)
        orphans = df[parent_col.notna() & (parent_col != "") & ~parent_col.isin(all_ids)]
        if not orphans.empty:
            errors.append(f"{len(orphans)} Item(s) orphelin(s) — ParentID introuvable")

        roots = df[parent_col.isna() | (parent_col == "")]
        if roots.empty:
            errors.append("Aucun élément racine (aucune ligne avec ParentID vide)")

        parents = {
            str(i).strip(): str(p).strip()
            for i, p in zip(df["ID"].fillna(""), parent_col)
            if str(p).strip() != ""
        }
        if _has_parent_cycle(parents):
            errors.append("Cycle de parenté détecté dans la hiérarchie (ParentID)")

    inversions = _count_date_inversions(df)
    if inversions:
        errors.append(
            f"{inversions} ligne(s) avec une date de début postérieure à la date de fin"
        )

    return errors


# ── Parsing des réponses LLM ───────────────────────────────────────────────────

def strip_structure_markers(text: str) -> str:
    """Supprime les balises internes avant affichage Markdown."""
    text = re.sub(r"<!--\s*PLAN_STRUCTURE_(?:START|END)\s*-->\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\[\d[\d\s–\-]*car\.\]", "", text)
    return text


def _extract_structure_block(section_text: str) -> str:
    """Extrait le contenu entre les balises PLAN_STRUCTURE. Fallback sur le texte complet."""
    match = re.search(
        r"<!--\s*PLAN_STRUCTURE_START\s*-->(.*?)<!--\s*PLAN_STRUCTURE_END\s*-->",
        section_text,
        re.DOTALL | re.IGNORECASE,
    )
    return match.group(1).strip() if match else section_text


def extract_plans(llm_response: str) -> dict:
    """
    Parse la réponse AUD-001 et extrait le plan et les notes.
    Pour le plan, préfère le bloc balisé <!-- PLAN_STRUCTURE_START/END -->
    produit par le LLM ; retombe sur la section complète si absent.

    Les patterns d'amorce consomment toute la ligne d'en-tête (jusqu'au \\n)
    pour éviter qu'un fragment du titre (« L'ARCHIVISTE », « ÉTAT DES LIEUX »…)
    ne se retrouve en tête du contenu capturé.
    """
    plan_start = r"^[ \t]*#+[^\n]*(?:PARTIE\s+2|PLANS?\s+DE\s+CLASSEMENT)[^\n]*\n"
    notes_start = r"^[ \t]*#+[^\n]*(?:PARTIE\s+3|NOTES\s+POUR|RECOMMANDATION)[^\n]*\n"
    end_doc = r"(?:═+\s*FIN|\Z)"

    sections = {
        "plan":  (plan_start,  notes_start),
        "notes": (notes_start, end_doc),
    }
    flags = re.DOTALL | re.IGNORECASE | re.MULTILINE
    result = {}
    for key, (start_pat, end_pat) in sections.items():
        pattern = rf"{start_pat}(.*?)(?={end_pat}|\Z)"
        match = re.search(pattern, llm_response, flags)
        section_text = match.group(1).strip() if match else ""
        if key == "plan":
            section_text = _extract_structure_block(section_text)
        result[key] = section_text
    return result


_EXPECTED_CLASSEMENT_HEADERS = ["Path", "TargetFolder", "NewTitle"]


def _inject_header_if_missing(csv_text: str) -> str:
    """Réinjecte l'en-tête Path;TargetFolder;NewTitle s'il manque.

    Certains modèles (ex. gpt-5.5) produisent les lignes du classement sans la
    ligne d'en-tête. Dans ce cas, la 1re ligne de données serait prise pour
    l'en-tête par pandas. On détecte l'absence d'en-tête (1re ligne = 3 champs,
    dont aucun ne correspond aux en-têtes attendus) et on l'injecte.
    """
    first_line = csv_text.lstrip("﻿").split("\n", 1)[0]
    if not first_line.strip():
        return csv_text

    delim = ";" if ";" in first_line else ","
    fields = [f.strip().strip('"') for f in first_line.split(delim)]
    if len(fields) != len(_EXPECTED_CLASSEMENT_HEADERS):
        return csv_text

    lowered = [f.lower() for f in fields]
    has_header = any(h.lower() in lowered for h in _EXPECTED_CLASSEMENT_HEADERS)
    if has_header:
        return csv_text

    return delim.join(_EXPECTED_CLASSEMENT_HEADERS) + "\n" + csv_text


def _salvage_classement_csv(csv_text: str) -> pd.DataFrame:
    """Parse tolérant pour la sortie CLA-001 quand pandas échoue sur des lignes
    au nombre de champs irrégulier.

    Le format est strictement 3 colonnes par design (`Path;TargetFolder;NewTitle`).
    Un modèle peut produire ponctuellement une ligne à 4 champs — un « ; »
    parasite dans `NewTitle`, ou un champ surnuméraire. Plutôt que de jeter toute
    la réponse (appel API déjà consommé), on ramène chaque ligne à exactement
    3 champs : on tronque les champs en trop, on complète les manquants. Les
    lignes réellement cassées (Path tronqué, TargetFolder absent) seront de toute
    façon signalées en aval par `convert_classement_to_resip`.
    """
    first = next((ln for ln in csv_text.splitlines() if ln.strip()), "")
    sep = ";" if first.count(";") >= first.count(",") else ","

    records: list[list[str]] = []
    for fields in csv.reader(io.StringIO(csv_text), delimiter=sep):
        if not fields or all(f.strip() == "" for f in fields):
            continue
        # Marqueur de livraison (ex. "[FIN DE LA PARTIE X/N]") → ignorer
        if re.match(r"^\[.*\]$", fields[0].strip()):
            continue
        if len(fields) > 3:
            fields = fields[:3]
        elif len(fields) < 3:
            fields = fields + [""] * (3 - len(fields))
        records.append([f.strip() for f in fields])

    if not records:
        raise ValueError("Aucune ligne exploitable dans la réponse du LLM.")

    header = [h.lstrip("﻿").lower() for h in records[0]]
    expected = {h.lower() for h in _EXPECTED_CLASSEMENT_HEADERS}
    data = records[1:] if expected & set(header) else records

    return pd.DataFrame(data, columns=list(_EXPECTED_CLASSEMENT_HEADERS), dtype=str)


def extract_csv_from_response(llm_response: str) -> pd.DataFrame:
    """
    Extrait le bloc CSV de la réponse CLA-001.
    Stratégies par ordre de priorité :
    1. Bloc ```csv ... ``` ou ``` ... ```
    2. Ligne d'en-tête SEDA (commence par ID; ou "ID";)
    3. Réponse complète en dernier recours
    """
    # Stratégie 1 : bloc markdown — prendre le dernier bloc (certains modèles produisent
    # des CSV intermédiaires par phase avant le résultat final)
    pattern = r"```(?:csv)?\s*\n(.*?)```"
    matches = re.findall(pattern, llm_response, re.DOTALL)
    if matches:
        csv_text = matches[-1].strip()
    else:
        # Stratégie 2 : trouver la ligne d'en-tête SEDA
        header_match = re.search(
            r'^("?ID"?[;,].+Content\.DescriptionLevel.+)$',
            llm_response,
            re.MULTILINE | re.IGNORECASE,
        )
        if header_match:
            start = header_match.start()
            csv_text = llm_response[start:].strip()
        else:
            csv_text = llm_response.strip()

    csv_text = _inject_header_if_missing(csv_text)

    # Auto-détection du séparateur : certains modèles (notamment de raisonnement)
    # ignorent l'instruction « séparateur ; » et produisent un CSV avec virgule
    # ou tabulation. On tente d'abord la détection automatique ; si elle ne
    # produit pas de colonnes exploitables, on retombe sur ";".
    # En cas de lignes au nombre de champs irrégulier (un « ; » parasite produit
    # par le LLM), pandas lèverait ParserError et toute la réponse
    # serait perdue : on bascule alors sur un parse tolérant à 3 colonnes.
    try:
        df = pd.read_csv(
            io.StringIO(csv_text),
            sep=None,
            engine="python",
            encoding="utf-8-sig",
            dtype=str,
        )
        if len(df.columns) <= 1:
            df = pd.read_csv(
                io.StringIO(csv_text),
                sep=";",
                engine="python",
                encoding="utf-8-sig",
                dtype=str,
            )
    except pd.errors.ParserError:
        return _salvage_classement_csv(csv_text)
    # Supprimer les colonnes d'index parasites produites par le LLM
    # (colonne vide "", colonne "Unnamed: X", ou colonne purement numérique)
    clean_cols = [
        c for c in df.columns
        if c.strip().lstrip("﻿") != ""
        and not c.startswith("Unnamed")
        and not c.strip().lstrip("﻿").isdigit()
    ]
    df = df[clean_cols]
    df.columns = [c.strip().lstrip("﻿") for c in df.columns]

    # Supprimer les lignes de marqueurs de livraison (ex: "[FIN DE LA PARTIE X/N]")
    if "ID" in df.columns:
        df = df[~df["ID"].astype(str).str.match(r"^\[.*\]$", na=False)]

    return df


# ── Classement simplifié (format LLM → RESIP) ──────────────────────────────────

def prepare_for_classement(df: pd.DataFrame, include_description: bool = True) -> pd.DataFrame:
    """Produit le CSV envoyé au LLM de classement.

    Colonnes de base : Path;CurrentTitle;Date, plus une colonne `Description`
    (la colonne `Content.Description` du CSV source, renommée sous un nom
    lisible) dès que `include_description` est actif et que la colonne est
    présente — même vide partout : on respecte le choix explicite de
    l'archiviste. On ne transmet que cette métadonnée descriptive — et non
    toute colonne supplémentaire — pour éviter le bruit et garder le prompt
    ciblé. Si l'option est désactivée, ou si Content.Description est absente du
    CSV, elle n'est pas envoyée. Le même toggle gouverne aussi l'audit
    (prepare_for_llm).
    """
    items = df[df["Content.DescriptionLevel"] == "Item"].copy()

    out = pd.DataFrame({
        "Path": items["File"].values,
        "CurrentTitle": items["Content.Title"].values,
        "Date": items["Content.StartDate"].values
        if "Content.StartDate" in items.columns else [""] * len(items),
    })

    desc_col = "Content.Description"
    if include_description and desc_col in items.columns:
        out["Description"] = items[desc_col].fillna("").astype(str).values

    return out


def _folder_title(folder_name: str) -> str:
    """Dérive un titre lisible depuis un nom technique : '1-1_Letres_de_motivation' → 'Letres de motivation'."""
    return re.sub(r"^\d+(-\d+)*_", "", folder_name).replace("_", " ")


def _preserve_extension(path: str, new_title: str) -> str:
    """Force l'extension de NewTitle à correspondre à celle du Path d'origine.

    Le LLM modifie parfois l'extension à tort (ex. .docx → .pdf). Cette
    correction déterministe garantit qu'on ne renomme jamais un fichier dans
    un format qui n'est pas le sien. La casse de l'extension d'origine est
    préservée.
    """
    if not path or not new_title:
        return new_title
    path_basename = path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    if "." not in path_basename:
        return new_title
    path_ext = "." + path_basename.rsplit(".", 1)[-1]
    if "." in new_title:
        title_stem, title_ext_raw = new_title.rsplit(".", 1)
        title_ext = "." + title_ext_raw
        if title_ext.lower() == path_ext.lower():
            return title_stem + path_ext  # aligne la casse même si le stem est OK
        return title_stem + path_ext
    return new_title + path_ext


def _looks_like_file(name: str) -> bool:
    """True si `name` ressemble à un nom de fichier (extension finale) plutôt qu'à
    un dossier du plan.

    Sert de filet déterministe pour intercepter les sorties LLM où un nom de
    fichier atterrit dans la colonne TargetFolder (ex. `kermesse_2022_002.jpg`) :
    les dossiers techniques du plan n'ont jamais d'extension. Même esprit que
    `_preserve_extension` — on ne fait pas confiance au LLM sur ce qui est
    mécaniquement vérifiable.
    """
    return bool(re.search(r"\.[A-Za-z0-9]{1,6}$", name.strip()))


# Séparateur « titre descriptif → nom technique » sur une ligne d'arborescence.
# Le LLM écrit « → » (gabarit) mais retombe parfois sur l'ASCII « -> ».
_PLAN_ARROW_RE = re.compile(r"\s*(?:→|->)\s*")

# Nom technique de dossier : se termine par « / ». Recherché APRÈS la flèche
# (cf. _technical_segment) pour ne jamais confondre un mot du titre descriptif
# avec un nom de dossier.
_FOLDER_RE = re.compile(r"([\w][\w\-]*)/")


def _technical_segment(line: str) -> str:
    """Partie d'une ligne d'arborescence portant le nom technique.

    Format fusionné « titre → nom_technique/ » : on ne garde que ce qui suit la
    dernière flèche. Ancien format (nom technique seul) : pas de flèche, on rend
    la ligne entière — d'où la rétro-compatibilité.
    """
    return _PLAN_ARROW_RE.split(line)[-1]


def parse_plan_tree(plan_valide: str) -> dict:
    """
    Parse l'arborescence technique du plan validé.
    Retourne {folder_name: parent_folder_name | None}.
    None = parent est la racine (File=".").
    """
    # Localise l'en-tête de l'arborescence technique. Le LLM place tantôt l'arbre
    # dans un bloc ```text``` qui suit l'en-tête, tantôt l'en-tête lui-même DANS le
    # bloc (en-tête + arbre dans le même fence) — auquel cas il n'y a pas de fence
    # juste après l'en-tête. On ne dépend donc plus d'un fence : on capture tout ce
    # qui suit l'en-tête jusqu'à la section suivante (Préconisations) ou la fin, et
    # on en extrait les lignes de dossier (les fences ```` éventuels sont ignorés
    # par _FOLDER_RE puisqu'ils ne se terminent pas par « / »).
    header = re.search(r"[Aa]rborescence\s+technique", plan_valide)
    if not header:
        return {}

    block = plan_valide[header.end():]
    stop = re.search(r"[Pp]r[ée]conisation", block)
    if stop:
        block = block[: stop.start()]

    folders = []
    for line in block.split("\n"):
        m = _FOLDER_RE.search(_technical_segment(line))
        if m:
            name = m.group(1)
            if name and "_" in name and name != "Dossier_racine":
                folders.append(name)

    result = {}
    for folder in folders:
        prefix = folder.split("_")[0]
        parts = prefix.split("-")
        if len(parts) == 1:
            result[folder] = None
        else:
            parent_prefix = "-".join(parts[:-1])
            parent = next(
                (f for f in folders if f.split("_")[0] == parent_prefix),
                None,
            )
            result[folder] = parent

    # Si une racine non-numérique avec un préfixe de plus d'un caractère existe
    # (ex. "Mairie_..."), reparenter toutes les autres racines sous elle. Les
    # dossiers à préfixe d'une seule lettre (ex. "A_trier") sont traités comme
    # des enfants, pas comme des racines organisationnelles candidates.
    roots = [f for f, parent in result.items() if parent is None]
    main_root = next(
        (
            f for f in roots
            if not f.split("_")[0][:1].isdigit() and len(f.split("_")[0]) > 1
        ),
        None,
    )
    if main_root and len(roots) > 1:
        for f in roots:
            if f != main_root:
                result[f] = main_root

    return result


# Numérotation de tête d'un titre descriptif : « 1. », « 1.1. », « 2.3 »…
_PLAN_NUMBERING_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s*")
_TREE_PREFIX_RE = re.compile(r"^[│├└─\s]+")


def parse_plan_titles(plan_valide: str) -> dict:
    """Extrait {nom_technique: titre_descriptif} de l'arborescence fusionnée.

    Sur chaque ligne « titre → nom_technique/ », associe le nom technique à son
    titre descriptif (numérotation et caractères d'arbre retirés). Retourne un
    dict vide pour un plan à l'ancien format (sans flèche) : l'appelant retombe
    alors sur ``_folder_title`` (titre dérivé du nom technique).
    """
    header = re.search(r"[Aa]rborescence\s+technique", plan_valide)
    if not header:
        return {}

    block = plan_valide[header.end():]
    stop = re.search(r"[Pp]r[ée]conisation", block)
    if stop:
        block = block[: stop.start()]

    titles = {}
    for line in block.split("\n"):
        parts = _PLAN_ARROW_RE.split(line)
        if len(parts) < 2:
            continue  # pas de flèche → aucun titre associable
        m = _FOLDER_RE.search(parts[-1])
        if not m:
            continue
        name = m.group(1)
        if "_" not in name or name == "Dossier_racine":
            continue
        title = _TREE_PREFIX_RE.sub("", parts[0])
        title = _PLAN_NUMBERING_RE.sub("", title).strip()
        if title:
            titles[name] = title
    return titles


def _ancestors_inclusive(name: str, folder_tree: dict, cache: dict | None = None) -> list:
    """Retourne ``[name]`` suivi de tous ses dossiers ancêtres (vers la racine).

    Réciproque de la notion de descendance : un item rangé dans ``name`` entre dans
    la plage de dates de ``name`` *et* de chacun de ses ancêtres. Parcourir la chaîne
    d'ancêtres de chaque item (plutôt que les descendants de chaque dossier) permet
    d'agréger les dates en une seule passe linéaire sur les items. Mémoïsé via
    ``cache`` et protégé contre un éventuel cycle dans ``folder_tree``.
    """
    if cache is not None and name in cache:
        return cache[name]
    result = [name]
    seen = {name}
    parent = folder_tree.get(name)
    while parent is not None and parent not in seen:
        result.append(parent)
        seen.add(parent)
        parent = folder_tree.get(parent)
    if cache is not None:
        cache[name] = result
    return result


def _slug_created(name: str) -> str:
    """Nom technique assaini (FS/SEDA) d'un sous-dossier créé : ponctuation et
    espaces → « _ », répétitions écrasées, accents conservés (``\\w`` unicode,
    cohérent avec ``_FOLDER_RE``). Vide si rien d'exploitable."""
    return re.sub(r"[^\w]+", "_", (name or "").strip(), flags=re.UNICODE).strip("_")


def _resolve_targets(
    targets: pd.Series, folder_tree: dict, allowed_parents: set[str]
) -> tuple[pd.Series, dict[str, str], list[str]]:
    """Résout chaque ``TargetFolder`` brut en nom canonique.

    Cas courant : on ne garde que le **nom de feuille** — le LLM produit parfois un
    chemin ``parent/enfant`` où l'enfant est un vrai dossier du plan.

    Cas création autorisée : quand la feuille n'est **pas** un dossier du plan mais
    que le segment parent l'est **et** figure dans ``allowed_parents``, la feuille
    est une **création légitime** sous ce parent. On lui attribue un nom technique
    canonique ``{préfixe_parent}-{k}_{slug}`` (collision-proof, déterministe) et on
    la rattache au parent. ``allowed_parents`` vide ⇒ aucune création reconnue →
    comportement **byte-identique** à l'existant.

    Retourne ``(cibles_résolues, created_folders {canonique: parent}, warnings)``.
    """
    def _segments(raw: object) -> list[str]:
        parts = re.split(r"[/\\]", str(raw).strip())
        return [p.strip() for p in parts if p.strip()]

    # 1er passage — collecter les demandes de création (parent, slug), dédupliquées.
    creation_reqs: set[tuple[str, str]] = set()
    if allowed_parents:
        for raw in targets:
            segs = _segments(raw)
            if len(segs) < 2:
                continue
            leaf, parent = segs[-1], segs[-2]
            if leaf in folder_tree:
                continue  # dossier réel du plan désigné par son chemin — inchangé
            slug = _slug_created(leaf)
            # La garde « ressemble à un fichier » porte sur la feuille **brute** :
            # l'assainissement écrase le point de l'extension (`facture.pdf` →
            # `facture_pdf`), ce qui la rendrait invisible après slug.
            if (
                parent in folder_tree
                and parent in allowed_parents
                and slug
                and not _looks_like_file(leaf)
            ):
                creation_reqs.add((parent, slug))

    # Attribution des noms canoniques (déterministe, sans collision avec le plan
    # ni entre créations). Numérotation de **position** séquentielle par parent —
    # les frères créés reçoivent des indices distincts (`1-6-1_`, `1-6-2_`…),
    # reprenant après le plus grand enfant direct déjà numéroté dans le plan : les
    # sous-dossiers créés sont ainsi de vrais dossiers du plan, réintégrables tels
    # quels (`parse_plan_tree` déduit le parent du préfixe).
    used = set(folder_tree)
    next_idx: dict[str, int] = {}
    for parent, _slug in creation_reqs:
        if parent in next_idx:
            continue
        prefix = parent.split("_")[0]
        child_re = re.compile(rf"{re.escape(prefix)}-(\d+)_")
        existing = [int(m.group(1)) for f in folder_tree if (m := child_re.match(f))]
        next_idx[parent] = (max(existing) + 1) if existing else 1

    created_folders: dict[str, str] = {}
    canon_by_req: dict[tuple[str, str], str] = {}
    for parent, slug in sorted(creation_reqs):
        prefix = parent.split("_")[0]
        idx = next_idx[parent]
        while f"{prefix}-{idx}_{slug}" in used:
            idx += 1
        canon = f"{prefix}-{idx}_{slug}"
        next_idx[parent] = idx + 1
        used.add(canon)
        created_folders[canon] = parent
        canon_by_req[(parent, slug)] = canon

    # 2e passage — résoudre chaque valeur brute en nom canonique.
    def _resolve(raw: object) -> str:
        segs = _segments(raw)
        if not segs:
            return str(raw)
        leaf = segs[-1]
        if leaf in folder_tree:
            return leaf
        if len(segs) >= 2:
            canon = canon_by_req.get((segs[-2], _slug_created(leaf)))
            if canon is not None:
                return canon
        return leaf  # feuille brute : hors plan / malformée, traitée comme avant

    resolved = targets.astype(str).map(_resolve)
    warnings = [
        f"Sous-dossier créé (autorisé) : '{canon}' sous '{parent}'."
        for canon, parent in created_folders.items()
    ]
    return resolved, created_folders, warnings


def convert_classement_to_resip(
    df_llm: pd.DataFrame,
    df_original: pd.DataFrame,
    plan_valide: str,
    *,
    allowed_parents: set[str] | None = None,
) -> tuple:
    """
    Convertit la sortie LLM (Path;TargetFolder;NewTitle) en CSV RESIP complet.
    Retourne (df_resip, warnings: list[str], stats: dict) où `stats` porte la
    conformité au plan calculée à la source : l'arborescence produite par le
    classement est-elle identique à celle du plan validé (`planMatches`), et sinon
    quels dossiers diffèrent (`foldersOffPlan`, `foldersMissing`).

    `allowed_parents` : ensemble des dossiers du plan sous lesquels le classement
    est autorisé à **créer des sous-dossiers** (dérivé des consignes de l'archiviste
    par `core.cla_directives.allowed_parents`). Un `TargetFolder` de la forme
    `parent_autorisé/Nouveau_sous_dossier` est alors traité comme une **création
    légitime** — sous-dossier créé et rattaché au parent, jamais à la racine, compté
    à part (`foldersCreatedAuthorized`) et **exclu** de `foldersOffPlan`. Vide ⇒
    conversion inchangée (un dossier inventé reste un hors-plan).
    """
    warnings_out = []

    expected_cols = {"Path", "TargetFolder", "NewTitle"}
    missing = expected_cols - set(df_llm.columns)
    if missing:
        raise ValueError(
            "Le CSV produit par le LLM ne contient pas les colonnes attendues "
            f"(manquantes : {', '.join(sorted(missing))}). "
            f"Colonnes reçues : {', '.join(df_llm.columns.tolist())}. "
            "Le modèle n'a pas respecté le format Path;TargetFolder;NewTitle."
        )

    df_llm = df_llm.copy()

    # Garde-fou déterministe : forcer l'extension du NewTitle à correspondre à
    # celle du Path. Le LLM convertit parfois .docx en .pdf, .xlsx en .csv, etc.
    fixed_details: list[str] = []
    new_titles = []
    for path, title in zip(df_llm["Path"].astype(str), df_llm["NewTitle"].astype(str)):
        corrected = _preserve_extension(path, title)
        if corrected != title:
            fixed_details.append(f"`{path}` : `{title}` → `{corrected}`")
        new_titles.append(corrected)
    df_llm["NewTitle"] = new_titles
    if fixed_details:
        details_str = "; ".join(fixed_details)
        warnings_out.append(
            f"{len(fixed_details)} NewTitle(s) corrigé(s) : extension réalignée sur celle du Path d'origine. "
            f"Détails : {details_str}"
        )

    # 1. Parser le plan
    folder_tree = parse_plan_tree(plan_valide)
    # Titres descriptifs portés par l'arborescence fusionnée (titre → nom
    # technique). Vide si plan à l'ancien format : on retombe sur _folder_title.
    folder_titles = parse_plan_titles(plan_valide)
    if not folder_tree:
        warnings_out.append("Arborescence technique non trouvée dans le plan — vérifier le format.")

    # Résoudre TargetFolder : cas courant, on ne garde que le nom de feuille (le
    # LLM produit parfois "1_Parent/1-1_Enfant" alors qu'on n'a besoin que de la
    # feuille pour le lookup). Cas création autorisée : "parent/Nouveau" sous un
    # parent de `allowed_parents` → sous-dossier créé, rattaché au parent.
    allowed = {a for a in (allowed_parents or set()) if a in folder_tree}
    df_llm["TargetFolder"], created_folders, creation_warnings = _resolve_targets(
        df_llm["TargetFolder"], folder_tree, allowed
    )
    # Arbre effectif = plan + sous-dossiers créés (parent réel connu). Sert au
    # rattachement, à l'expansion des ancêtres et au calcul des dates ; la
    # conformité, elle, reste mesurée contre le plan seul (`folder_tree`).
    folder_tree_eff = {**folder_tree, **created_folders}

    # 2. Racine originale
    root_mask = (df_original["File"].fillna("") == ".") & (df_original["ParentID"].fillna("") == "")
    root_rows = df_original[root_mask]
    if root_rows.empty:
        root_orig = {}
        root_id = "1"
    else:
        root_orig = root_rows.iloc[0].to_dict()
        root_id = str(root_orig["ID"])

    # 3. Dossiers nécessaires (référencés + leurs ancêtres)
    # Garde-fou : si le LLM met un nom de fichier (extension) dans TargetFolder au
    # lieu d'un dossier du plan, on ne crée PAS de dossier-poubelle. Ces cibles
    # malformées sont écartées ici (donc aucun RecordGrp) ; leurs items seront
    # rattachés à la racine et signalés dans la boucle ci-dessous. Les vrais
    # dossiers hors plan (sans extension) restent créés et comptés comme écart.
    # Note : les sous-dossiers créés sous autorisation sont dans `folder_tree_eff`
    # (pas dans `folder_tree`) mais ne ressemblent jamais à un fichier → ils passent
    # le filtre comme des dossiers normaux.
    needed = {
        t
        for t in df_llm["TargetFolder"].dropna().astype(str).unique()
        if t and not (t not in folder_tree_eff and _looks_like_file(t))
    }
    for folder in list(needed):
        parent = folder_tree_eff.get(folder)
        while parent is not None:
            needed.add(parent)
            parent = folder_tree_eff.get(parent)

    # 4. Assigner des IDs aux dossiers
    try:
        max_id = int(df_original["ID"].dropna().astype(int).max())
    except (ValueError, TypeError):
        max_id = 100
    folder_ids = {f: str(max_id + i + 1) for i, f in enumerate(sorted(needed))}

    # 5. Colonnes extra du CSV original à préserver
    extra_cols = [c for c in df_original.columns if c not in REQUIRED_COLUMNS]

    # 6. Lignes RecordGrp
    rg_rows = []
    for folder in sorted(needed):
        parent = folder_tree_eff.get(folder)
        parent_id = folder_ids[parent] if parent and parent in folder_ids else root_id
        row = {
            "ID": folder_ids[folder],
            "ParentID": parent_id,
            "File": folder,
            "Content.DescriptionLevel": "RecordGrp",
            "Content.Title": folder_titles.get(folder) or _folder_title(folder),
            "Content.StartDate": "",
            "Content.EndDate": "",
        }
        for col in extra_cols:
            row[col] = ""
        rg_rows.append(row)

    # 7. Lignes Item
    orig_items = df_original[df_original["Content.DescriptionLevel"] == "Item"]
    orig_by_path = orig_items.set_index("File")

    # Vérifier les fichiers manquants dans la sortie LLM
    llm_paths = set(df_llm["Path"].astype(str))
    for missing_path in sorted(set(orig_by_path.index) - llm_paths):
        warnings_out.append(f"Fichier non classé (absent de la sortie LLM) : '{missing_path}'")

    item_rows = []
    n_malformed = 0
    for _, llm_row in df_llm.iterrows():
        path = str(llm_row.get("Path", ""))
        target = str(llm_row.get("TargetFolder", ""))
        new_title = str(llm_row.get("NewTitle", path))

        # Cible malformée : nom de fichier (extension) au lieu d'un dossier du plan.
        # Écartée de `needed` plus haut → pas dans `folder_ids`. On ne perd pas le
        # fichier : il est rattaché à la racine et signalé distinctement. Un
        # sous-dossier créé sous autorisation est dans `folder_tree_eff` et sans
        # extension — jamais concerné.
        malformed = bool(target) and target not in folder_tree_eff and _looks_like_file(target)

        if not target or (target not in folder_ids and not malformed):
            warnings_out.append(f"TargetFolder inconnu : '{target}' pour '{path}'")
            continue
        if path not in orig_by_path.index:
            warnings_out.append(f"Path introuvable dans l'original : '{path}'")
            continue

        orig = orig_by_path.loc[path]
        if isinstance(orig, pd.DataFrame):
            orig = orig.iloc[0]
        row = orig.to_dict()
        if malformed:
            n_malformed += 1
            row["ParentID"] = root_id
            warnings_out.append(
                f"Sortie LLM malformée : TargetFolder '{target}' ressemble à un fichier, "
                f"pas à un dossier du plan ; '{path}' rattaché à la racine."
            )
        else:
            row["ParentID"] = folder_ids[target]
        row["Content.Title"] = new_title
        row["File"] = path  # préservation garantie
        item_rows.append(row)

    # 8. Calculer les dates des RecordGrp.
    # La plage d'un RecordGrp couvre ses items directs *et* ceux de tous ses
    # sous-dossiers. Plutôt que de rebalayer l'ensemble des items pour chaque
    # dossier (coût dossiers × items — quadratique, pénalisant sur gros volumes),
    # on remonte la chaîne d'ancêtres de chaque item une seule fois et on agrège
    # min(start)/max(end) chemin faisant (coût items × profondeur).
    orig_dates = {
        str(r["File"]): (
            str(r.get("Content.StartDate", "")),
            str(r.get("Content.EndDate", "")),
        )
        for _, r in orig_items.iterrows()
    }
    llm_target_map = dict(zip(df_llm["Path"].astype(str), df_llm["TargetFolder"].astype(str)))

    folder_starts: dict[str, str] = {}
    folder_ends: dict[str, str] = {}
    anc_cache: dict[str, list] = {}
    for path, target in llm_target_map.items():
        dates = orig_dates.get(path)
        if dates is None:
            continue
        start, end = dates
        for folder in _ancestors_inclusive(target, folder_tree_eff, anc_cache):
            if start not in ("", "nan"):
                cur = folder_starts.get(folder)
                if cur is None or start < cur:
                    folder_starts[folder] = start
            if end not in ("", "nan"):
                cur = folder_ends.get(folder)
                if cur is None or end > cur:
                    folder_ends[folder] = end

    for rg_row in rg_rows:
        folder = rg_row["File"]
        rg_row["Content.StartDate"] = folder_starts.get(folder, "")
        rg_row["Content.EndDate"] = folder_ends.get(folder, "")

    # 9. Racine avec dates recalculées
    all_starts = [orig_dates[p][0] for p in llm_target_map if p in orig_dates and orig_dates[p][0] not in ("", "nan")]
    all_ends = [orig_dates[p][1] for p in llm_target_map if p in orig_dates and orig_dates[p][1] not in ("", "nan")]
    if root_orig:
        root_orig["Content.StartDate"] = min(all_starts) if all_starts else ""
        root_orig["Content.EndDate"] = max(all_ends) if all_ends else ""

    # 10. Assembler et ordonner les colonnes
    all_rows = ([root_orig] if root_orig else []) + rg_rows + item_rows
    df_result = pd.DataFrame(all_rows)
    ordered_cols = REQUIRED_COLUMNS + [c for c in extra_cols if c in df_result.columns]
    ordered_cols = [c for c in ordered_cols if c in df_result.columns]

    # ── Conformité au plan : l'arborescence produite par le classement doit être
    # identique à celle du plan validé à l'audit (égalité stricte, au niveau
    # dossier — indépendante du classement fichier par fichier). Deux types
    # d'écart, tous deux signalés à l'archiviste :
    #   • dossier inventé   : créé par le classement, absent du plan ;
    #   • dossier manquant  : présent au plan, resté sans contenu.
    # Référence = `folder_tree` (le plan), jamais `folder_ids` (dérivé des cibles du
    # LLM, donc circulaire — un dossier inventé y figurerait aussi). Les dossiers
    # produits sont exactement les RecordGrp construits ci-dessus.
    #
    # Un **sous-dossier créé sous autorisation** (`created_folders`) n'est ni un
    # hors-plan (l'archiviste l'a explicitement permis) ni une non-conformité : il
    # est retiré de `folders_off_plan` et compté à part
    # (`foldersCreatedAuthorized`), `planMatches` reste signifiant.
    plan_folders = set(folder_tree)
    output_folders = {str(r["File"]) for r in rg_rows}
    created_materialized = sorted(output_folders & set(created_folders))
    folders_off_plan = sorted(output_folders - plan_folders - set(created_folders))
    folders_missing = sorted(plan_folders - output_folders)
    # Avertissements de création (autorisés) placés d'abord — information, non alerte.
    for w in creation_warnings:
        if w.split("'")[1] in created_materialized:
            warnings_out.append(w)
    for f in folders_off_plan:
        warnings_out.append(f"Dossier hors plan : '{f}' créé par le classement, absent du plan validé.")
    for f in folders_missing:
        warnings_out.append(f"Dossier du plan non réalisé : '{f}' (aucun contenu classé dedans).")

    # Stats construites à la source — le front se contente de les afficher.
    # `planMatches` : True ssi le plan a pu être lu ET aucun écart dans les deux sens.
    stats = {
        "planParsed": bool(folder_tree),
        "planFolders": len(plan_folders),
        "outputFolders": len(output_folders),
        "foldersOffPlan": folders_off_plan,
        "foldersMissing": folders_missing,
        "itemsMalformed": int(n_malformed),
        "planMatches": bool(folder_tree) and not folders_off_plan and not folders_missing,
        # Sous-dossiers créés sous autorisation d'une consigne : liste + rattachement.
        "foldersCreatedAuthorized": created_materialized,
        "foldersCreatedParents": {f: created_folders[f] for f in created_materialized},
    }

    return df_result[ordered_cols], warnings_out, stats
