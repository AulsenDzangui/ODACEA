"""Outils de requête **lecture seule** sur un vrac.

Fonctions déterministes, pures et sans LLM, interrogées par l'agent
conversationnel de traitement de vrac (AGT-001, `core.agt_agent`) : le CSV ne
transite jamais dans un prompt, il vit dans un DataFrame que le modèle
questionne via ces outils. Toute réponse quantitative (comptage, liste) vient
d'ici — jamais « de tête » du LLM.

Contrat commun :
  * entrée : le DataFrame canonique (colonnes Archifiltre, cf. `csv_handler`) ;
  * sortie : un dict JSON-sérialisable, clés en français (lisibles par le
    modèle) — jamais d'exception : une entrée invalide renvoie `{"erreur": …}`
    (le modèle peut se corriger) ;
  * les listes sont **paginées** (`PAGE_SIZE` résultats par page) mais les
    totaux (`total`, `pages`) restent **exacts**, calculés sur tout le vrac.

Le **filtre structuré** (`compter`, `echantillonner`) est un dict aux clés
bornées (`FILTER_KEYS`) : mots-clés (ET, insensible casse/accents, sur chemin +
titre), extension, sous-dossier (préfixe de chemin), bornes d'années sur
`Content.StartDate`. Il ne s'applique qu'aux **fichiers** (`Item`) : l'unité de
compte de l'exploration de vrac.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any

import pandas as pd

from core.enrich import FRENCH_STOPWORDS

# Taille de page des listes renvoyées au modèle : assez pour être utile, assez
# peu pour borner les tokens d'un tour (le total exact accompagne chaque page).
PAGE_SIZE = 20

# Nombre maximal de sous-dossiers listés d'un coup (lister_dossier) et de
# valeurs détaillées par stats() — au-delà, agrégat « (autres) ».
MAX_BUCKETS = 20

# Bornes du top-N de mots_frequents : défaut utile pour une vue
# d'ensemble, plafond qui borne les tokens du résultat.
DEFAULT_TERMES = 20
MAX_TERMES = 50

FILTER_KEYS = frozenset({"mots_cles", "extension", "dossier", "annee_min", "annee_max"})

_LEVEL = "Content.DescriptionLevel"
_TITLE = "Content.Title"
_START = "Content.StartDate"


def _fold(s: str) -> str:
    """Normalise pour la recherche : accents retirés, casse repliée."""
    nfd = unicodedata.normalize("NFD", str(s))
    return "".join(c for c in nfd if not unicodedata.combining(c)).lower()


def _extension(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if "." not in name[1:]:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def _year(date: str) -> int | None:
    s = str(date).strip()
    return int(s[:4]) if len(s) >= 4 and s[:4].isdigit() else None


def _parent(path: str) -> str:
    """Chemin du dossier parent (`.` pour un enfant direct de la racine)."""
    return path.rsplit("/", 1)[0] if "/" in path else "."


def _items(df: pd.DataFrame) -> pd.DataFrame:
    return df[df[_LEVEL] == "Item"]


def _folders(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df[_LEVEL] == "RecordGrp") & (df["File"] != ".")]


def _row_payload(row: pd.Series) -> dict:
    """Une ligne de résultat présentée au modèle : métadonnées seules."""
    return {
        "chemin": str(row["File"]),
        "titre": str(row.get(_TITLE, "")),
        "type": "dossier" if row[_LEVEL] == "RecordGrp" else "fichier",
        "date": str(row.get(_START, "") or ""),
    }


def _paginate(rows: list[dict], page: int) -> dict:
    """Découpe `rows` en pages de PAGE_SIZE ; les totaux restent exacts."""
    total = len(rows)
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(0, int(page))
    if page >= pages:
        return {
            "erreur": f"Page {page} inexistante : {total} résultat(s), pages 0 à {pages - 1}.",
            "total": total,
            "pages": pages,
        }
    start = page * PAGE_SIZE
    subset = rows[start : start + PAGE_SIZE]
    return {
        "total": total,
        "page": page,
        "pages": pages,
        "tronque": total > len(subset),
        "resultats": subset,
    }


# ── Filtre structuré ──────────────────────────────────────────────────────────

def filtrer_items(df: pd.DataFrame, filtre: dict | None) -> pd.DataFrame | dict:
    """Applique le filtre structuré aux fichiers (`Item`) du vrac.

    Renvoie le sous-DataFrame filtré, ou un dict `{"erreur": …}` si le filtre
    est invalide (clé inconnue, mauvais type) — le message liste les clés
    admises pour que le modèle se corrige au tour suivant.
    """
    items = _items(df)
    if not filtre:
        return items
    if not isinstance(filtre, dict):
        return {"erreur": "Le filtre doit être un objet (dict)."}
    unknown = set(filtre) - FILTER_KEYS
    if unknown:
        return {
            "erreur": (
                f"Clé(s) de filtre inconnue(s) : {', '.join(sorted(unknown))}. "
                f"Clés admises : {', '.join(sorted(FILTER_KEYS))}."
            )
        }

    paths = items["File"].astype(str)
    titles = items[_TITLE].astype(str) if _TITLE in items.columns else paths
    mask = pd.Series(True, index=items.index)

    mots = filtre.get("mots_cles")
    if mots:
        if isinstance(mots, str):
            mots = [mots]
        if not isinstance(mots, list) or not all(isinstance(m, str) for m in mots):
            return {"erreur": "`mots_cles` doit être une liste de chaînes."}
        haystack = (paths + " " + titles).map(_fold)
        for mot in mots:
            needle = _fold(mot)
            mask &= haystack.str.contains(needle, regex=False)

    ext = filtre.get("extension")
    if ext:
        if not isinstance(ext, str):
            return {"erreur": "`extension` doit être une chaîne (ex. \"pdf\")."}
        wanted = _fold(ext).lstrip(".")
        mask &= paths.map(lambda p: _extension(p) == wanted)

    dossier = filtre.get("dossier")
    if dossier:
        if not isinstance(dossier, str):
            return {"erreur": "`dossier` doit être une chaîne (chemin du sous-dossier)."}
        prefix = _fold(dossier).strip("/")
        if prefix and prefix != ".":
            mask &= paths.map(lambda p: _fold(p).startswith(prefix + "/"))

    for key, op in (("annee_min", "ge"), ("annee_max", "le")):
        bound = filtre.get(key)
        if bound is None:
            continue
        if not isinstance(bound, int) or isinstance(bound, bool):
            return {"erreur": f"`{key}` doit être un entier (année, ex. 2019)."}
        if _START in items.columns:
            years = items[_START].map(_year)
        else:
            years = pd.Series([None] * len(items), index=items.index, dtype=object)
        # Comparaison élément par élément : une ligne sans date est exclue dès
        # qu'une borne d'année est posée (on ne devine jamais une date).
        if op == "ge":
            mask &= years.map(lambda y, b=bound: y is not None and y >= b)
        else:
            mask &= years.map(lambda y, b=bound: y is not None and y <= b)

    return items[mask]


# ── Outils exposés à l'agent ──────────────────────────────────────────────────

def chercher(df: pd.DataFrame, mots_cles: list[str] | str, page: int = 0) -> dict:
    """Recherche par mots-clés (ET, insensible casse/accents) sur le chemin et
    le titre — fichiers **et** dossiers. Paginé, total exact."""
    if isinstance(mots_cles, str):
        mots_cles = [m for m in mots_cles.split() if m]
    if not mots_cles or not all(isinstance(m, str) for m in mots_cles):
        return {"erreur": "`mots_cles` doit être une liste de chaînes non vide."}
    rows = df[df["File"] != "."]
    paths = rows["File"].astype(str)
    titles = rows[_TITLE].astype(str) if _TITLE in rows.columns else paths
    haystack = (paths + " " + titles).map(_fold)
    mask = pd.Series(True, index=rows.index)
    for mot in mots_cles:
        mask &= haystack.str.contains(_fold(mot), regex=False)
    hits = [_row_payload(r) for _, r in rows[mask].iterrows()]
    return _paginate(hits, page)


def lister_dossier(df: pd.DataFrame, chemin: str = ".", page: int = 0) -> dict:
    """Contenu direct d'un dossier : sous-dossiers (avec leur nombre de
    fichiers, sous-arborescence comprise) puis fichiers (paginés)."""
    target = _fold(str(chemin or ".").strip().strip("/") or ".")
    folders = _folders(df)
    folder_paths = {_fold(str(p)): str(p) for p in folders["File"]}
    if target != ".":
        if target not in folder_paths:
            candidates = [
                orig for f, orig in folder_paths.items()
                if target.rsplit("/", 1)[-1] in f
            ][:5]
            out: dict[str, Any] = {"erreur": f"Dossier introuvable : {chemin}."}
            if candidates:
                out["suggestions"] = candidates
            return out
        target_path = folder_paths[target]
    else:
        target_path = "."

    items = _items(df)
    item_paths = items["File"].astype(str)

    sub = folders[folders["File"].astype(str).map(_parent).map(_fold) == _fold(target_path)]
    sous_dossiers = []
    for _, row in sub.head(MAX_BUCKETS).iterrows():
        p = str(row["File"])
        count = int(item_paths.str.startswith(p + "/").sum())
        sous_dossiers.append({"chemin": p, "titre": str(row.get(_TITLE, "")), "fichiers": count})

    direct = items[item_paths.map(_parent).map(_fold) == _fold(target_path)]
    fichiers = [_row_payload(r) for _, r in direct.iterrows()]
    page_out = _paginate(fichiers, page)
    if "erreur" in page_out:
        return {**page_out, "chemin": target_path}
    return {
        "chemin": target_path,
        "sousDossiers": sous_dossiers,
        "totalSousDossiers": int(len(sub)),
        "sousDossiersTronques": len(sub) > len(sous_dossiers),
        "totalFichiers": page_out.get("total", 0),
        "page": page_out.get("page", 0),
        "pages": page_out.get("pages", 1),
        "fichiers": page_out.get("resultats", []),
    }


def compter(df: pd.DataFrame, filtre: dict | None = None) -> dict:
    """Nombre **exact** de fichiers satisfaisant le filtre structuré, avec une
    répartition par extension (5 premières) pour orienter la suite."""
    hits = filtrer_items(df, filtre)
    if isinstance(hits, dict):
        return hits
    by_ext = (
        hits["File"].astype(str).map(lambda p: _extension(p) or "(sans extension)")
        .value_counts()
    )
    return {
        "total": int(len(hits)),
        "filtre": filtre or {},
        "parExtension": {str(k): int(v) for k, v in by_ext.head(5).items()},
    }


def echantillonner(df: pd.DataFrame, filtre: dict | None = None, n: int = 5) -> dict:
    """Échantillon déterministe (indices régulièrement espacés) de fichiers
    satisfaisant le filtre — pour « voir » le vrac sans tout lister."""
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        return {"erreur": "`n` doit être un entier ≥ 1."}
    n = min(n, PAGE_SIZE)
    hits = filtrer_items(df, filtre)
    if isinstance(hits, dict):
        return hits
    total = len(hits)
    if total <= n:
        picked = hits
    else:
        step = total / n
        indices = sorted({int(i * step) for i in range(n)})
        picked = hits.iloc[indices]
    return {
        "total": int(total),
        "n": int(len(picked)),
        "echantillon": [_row_payload(r) for _, r in picked.iterrows()],
    }


def stats(df: pd.DataFrame, par: str = "extension") -> dict:
    """Répartition exacte des fichiers `par` extension, période (année de
    `Content.StartDate`) ou dossier (branche de premier niveau). Les valeurs
    au-delà de MAX_BUCKETS sont agrégées sous « (autres) », le total reste exact."""
    items = _items(df)
    paths = items["File"].astype(str)
    if par == "extension":
        series = paths.map(lambda p: _extension(p) or "(sans extension)")
    elif par in ("periode", "période"):
        if _START not in items.columns:
            return {"erreur": "Aucune colonne de date dans ce vrac."}
        series = items[_START].map(lambda d: str(_year(d)) if _year(d) else "(sans date)")
    elif par == "dossier":
        series = paths.map(lambda p: p.split("/", 1)[0] if "/" in p else "(racine)")
    else:
        return {"erreur": "`par` doit valoir \"extension\", \"periode\" ou \"dossier\"."}
    counts = series.value_counts()
    head = counts.head(MAX_BUCKETS)
    valeurs = {str(k): int(v) for k, v in head.items()}
    rest = int(counts.iloc[MAX_BUCKETS:].sum()) if len(counts) > MAX_BUCKETS else 0
    if rest:
        valeurs["(autres)"] = rest
    return {"par": "periode" if par == "période" else par, "total": int(len(items)), "valeurs": valeurs}


# ── mots_frequents ────────────────────────────────────────────────────────────

# Un terme = une suite de lettres (accents compris) d'au moins 3 caractères —
# les nombres (années, numéros de version) ne sont pas des thèmes ; les
# périodes sont couvertes par stats(par="periode").
_TERM_RE = re.compile(r"[^\W\d_]{3,}")

# Les mots vides sont comparés après le même repli casse/accents que les tokens.
_STOPWORDS_FOLDED = frozenset(_fold(w) for w in FRENCH_STOPWORDS)


def _sans_extension(name: str) -> str:
    return name.rsplit(".", 1)[0] if _extension(name) else name


def _termes_fichier(path: str, title: str) -> set[str]:
    """Termes distincts d'un fichier : chemin (extension du nom retirée —
    les formats sont couverts par `stats(par="extension")`) + titre, repliés
    casse/accents, mots vides écartés. Un `set` par fichier : le titre recopie
    souvent le nom, un terme n'est jamais compté deux fois pour le même fichier."""
    text = _fold(_sans_extension(path)) + " " + _fold(_sans_extension(title))
    return {t for t in _TERM_RE.findall(text) if t not in _STOPWORDS_FOLDED}


def mots_frequents(df: pd.DataFrame, filtre: dict | None = None, n: int = DEFAULT_TERMES) -> dict:
    """Fréquence **exacte** des termes des chemins et titres — tout le vrac ou
    le sous-ensemble filtré.

    Répond à « principaux mots-clés / thématiques du vrac ? » par un comptage
    déterministe, au lieu d'une déduction depuis un échantillon (biais
    d'échantillon) enchaînée de `compter` terme à terme (budget d'étapes
    épuisé). L'occurrence d'un terme est le **nombre de fichiers** dont le
    chemin ou le titre le porte. Top-N borné (`MAX_TERMES`), tri déterministe
    (fréquence décroissante puis ordre alphabétique), totaux exacts.
    """
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        return {"erreur": "`n` doit être un entier ≥ 1."}
    n = min(n, MAX_TERMES)
    hits = filtrer_items(df, filtre)
    if isinstance(hits, dict):
        return hits
    paths = hits["File"].astype(str)
    titles = hits[_TITLE].astype(str) if _TITLE in hits.columns else paths
    counts: Counter[str] = Counter()
    for path, title in zip(paths, titles, strict=True):
        counts.update(_termes_fichier(path, title))
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top = ordered[:n]
    return {
        "total": int(len(hits)),
        "filtre": filtre or {},
        "termesDistincts": len(counts),
        "n": len(top),
        "tronque": len(ordered) > len(top),
        "termes": {t: int(c) for t, c in top},
    }
