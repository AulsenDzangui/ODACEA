"""Métriques d'évaluation des prompts.

Fonctions **pures et déterministes** : elles mesurent des artefacts déjà produits
(rapport AUD-001, stats de conversion CLA-001) sans aucun appel LLM — le harnais
`cli.py eval` les orchestre sur un corpus de fixtures et historise les résultats
(`evals/results/*.json`). Tout est donc testable hors réseau, et les chiffres
sont comparables d'un run à l'autre (à `PROMPT_VERSION` consignée).

Deux familles :

* `audit_metrics(report, scan, brief)` — qualité **structurelle** d'une réponse
  AUD-001 : plan extrait, bloc `PLAN_STRUCTURE` présent, arborescence
  parsable et sa forme (profondeur/largeur), respect du gabarit (sections
  1.1–1.5), réutilisation des chiffres du digest déterministe (volumétrie),
  et — respect de l'ordre originel — verdict « Ordre existant » rendu +
  **conservation** (part des dossiers sources non vides retrouvés parmi les
  rubriques du plan, créations comptées). On ne juge pas la *pertinence
  archivistique* du plan — ça reste à l'humain ; on mesure ce qui est
  mécaniquement vérifiable.
* `classement_metrics(stats)` — agrégation des compteurs CLA-001 déjà
  calculés à la source par `convert_classement_to_resip` : conformité au plan,
  items classés/non classés, cibles malformées, extensions corrigées,
  identifiants non résolus (mode Ref).

* `agent_case_metrics(events, attendu, df)` / `agent_run_metrics(cases)` —
  **exactitude des tool-calls et des filtres émis** par l'agent AGT-001
 : chaque cas du corpus golden (question en langage naturel → outil et
  filtre attendus, opération de classement attendue) est mesuré sur les
  événements d'un tour d'agent. L'équivalence de filtres est **sémantique**
  (mêmes fichiers sélectionnés sur le vrac évalué), jamais une comparaison de
  forme.

`format_eval_tables(runs)` met en forme le « tableau lisible » du rapport d'éval
(critère d'acceptation) — une table AUD-001, une table CLA-001 et une table
AGT-001, une ligne par run de la matrice corpus × modèle × mode.
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

from core.agt_tools import compter, filtrer_items
from core.csv_handler import extract_plans, parse_plan_tree
from core.tokens import format_duration

_PLAN_PREFIX_RE = re.compile(r"^\d+(?:-\d+)*_")


def semantic_label(folder_name: str) -> str:
    """Libellé comparable d'un dossier technique : préfixe numérique (`1_`,
    `1-1_`…) retiré, underscores remplacés par des espaces, casse repliée.

    `2-3_Marchés_publics` et `1-1_marchés_publics` rendent tous deux
    `marchés publics` — un même dossier numéroté différemment d'une variante à
    l'autre est reconnu identique. Source unique, réexportée par
    `core.plan_compare` qui l'utilise pour croiser les variantes de plan.
    """
    stripped = _PLAN_PREFIX_RE.sub("", folder_name)
    return stripped.replace("_", " ").strip().casefold()


# Préfixe ordinal de dossier source : `1. `, `1.2. `, `3) `. Exige un
# séparateur `.`/`)` puis une espace — un dossier-année (`2024 factures`,
# `2024`) n'est jamais tronqué.
_ORDINAL_PREFIX_RE = re.compile(r"^\d+(?:[.-]\d+)*[.)]\s+")


def conservation_label(name: str) -> str:
    """Libellé de rapprochement **source ⇄ plan** : `semantic_label` élargi aux
    préfixes ordinaux des dossiers sources (`1. Compta`), accents repliés
    (décomposition NFKD, diacritiques retirés), puis **sac de mots trié**
    (séparateurs non alphanumériques repliés, mots d'une lettre — élisions
    françaises `d'`, `l'` — écartés, doublons fusionnés).

    Nécessaire à la métrique de conservation : un dossier source conservé
    ressort du plan sous un nom technique translittéré (`Marchés publics` →
    `1_Marches_publics`), retiretisé (`Inscriptions 2022-2023` →
    `Inscriptions_2022_2023`), désélidé (`Conseils d'ecole` → `Conseils_ecole`)
    ou réordonné (`ATSEM - Personnel` → `Personnel_ATSEM`) — mesuré sur le
    corpus démo (2026-07-09) : sans ces replis, ces conservations réelles
    comptaient comme créations. Réservé au rapprochement (jamais à
    l'affichage)."""
    folded = unicodedata.normalize(
        "NFKD", semantic_label(_ORDINAL_PREFIX_RE.sub("", name))
    )
    ascii_label = "".join(c for c in folded if not unicodedata.combining(c))
    words = [
        w for w in re.split(r"[^a-z0-9]+", ascii_label)
        if len(w) > 1 or w.isdigit()  # « Tome 2 » garde son 2 ; `d'`/`l'` écartés
    ]
    return " ".join(sorted(set(words)))

# Sections du gabarit AUD-001 (Partie 1) — cf. prompts/AUD_001.py. Le mode
# brief n'en produit aucune (plan seul) : le respect du gabarit n'y est pas
# mesurable.
GABARIT_SECTIONS = ("1.1", "1.2", "1.3", "1.4", "1.5")

# Ligne de volumétrie du gabarit (§1.1) : « Items : N | RecordGrp : N |
# Profondeur : N niveaux ». C'est la forme imposée par le prompt — on ne tente
# pas de deviner des chiffres en prose libre : un rapport hors gabarit rend la
# réutilisation du digest « non mesurable » (None), ce qui est en soi un signal.
_VOLUMETRY_RE = re.compile(
    r"Items?\s*:\s*(\d+)\s*\|\s*RecordGrps?\s*:\s*(\d+)\s*\|\s*Profondeur\s*:\s*(\d+)"
)

# Verdict « Ordre existant » du gabarit AUD-001 ≥ 1.1.0 (Partie 2, avant le bloc
# plan) : STRUCTURÉ | PARTIELLEMENT STRUCTURÉ | ABSENT. Recherché sur le rapport
# accents/casse repliés (un modèle local écrit parfois « Structure ») ; les
# formes canoniques sont restituées. Absent (rapport ancien format ou modèle
# hors gabarit) → None, non mesurable — signal en soi.
_ORDER_VERDICTS = ("PARTIELLEMENT STRUCTURÉ", "STRUCTURÉ", "ABSENT")
_ORDER_RE = re.compile(
    r"ORDRE EXISTANT\s*:?\**\s*(PARTIELLEMENT STRUCTURE|STRUCTURE|ABSENT)"
)


def _fold_upper(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.upper())
    return "".join(c for c in folded if not unicodedata.combining(c))


def _order_verdict(report: str) -> str | None:
    m = _ORDER_RE.search(_fold_upper(report))
    if not m:
        return None
    return {v: canon for v, canon in zip(
        ("PARTIELLEMENT STRUCTURE", "STRUCTURE", "ABSENT"), _ORDER_VERDICTS, strict=True
    )}[m.group(1)]


def _plan_rubric_labels(tree: dict) -> set[str]:
    """Libellés de rapprochement des **rubriques** d'un plan — la racine du
    fonds (unique dossier sans parent, portant des enfants) est exclue : elle
    correspond au nœud racine du CSV, pas à un dossier source."""
    roots = [f for f, p in tree.items() if p is None]
    exclude: set[str] = set()
    if len(roots) == 1 and any(p == roots[0] for p in tree.values()):
        exclude = {roots[0]}
    return {
        label for f in tree if f not in exclude and (label := conservation_label(f))
    }


def plan_shape(tree: dict) -> dict:
    """Forme de l'arborescence d'un plan : nombre de dossiers, profondeur
    (niveaux), largeur max (enfants directs d'un même parent), feuilles.

    ``tree`` est le dict `{dossier: parent | None}` de `parse_plan_tree`.
    """
    if not tree:
        return {"folders": 0, "depth": 0, "maxWidth": 0, "leaves": 0}

    children_count: dict[str | None, int] = {}
    for parent in tree.values():
        children_count[parent] = children_count.get(parent, 0) + 1

    depth = 0
    for folder in tree:
        level, seen = 1, {folder}
        parent = tree.get(folder)
        while parent is not None and parent not in seen:
            level += 1
            seen.add(parent)
            parent = tree.get(parent)
        depth = max(depth, level)

    leaves = sum(1 for folder in tree if folder not in children_count)
    return {
        "folders": len(tree),
        "depth": depth,
        "maxWidth": max(children_count.values()),
        "leaves": leaves,
    }


def audit_metrics(report: str, scan: dict | None = None, brief: bool = False) -> dict:
    """Métriques structurelles d'une réponse AUD-001.

    ``scan`` est le résultat de `scan_metadata(df)` sur le vrac source : il
    fournit les valeurs déterministes auxquelles comparer la volumétrie écrite
    par le modèle (réutilisation du digest). ``brief`` neutralise les métriques
    de gabarit (le mode plan seul ne produit pas la Partie 1).
    """
    sections = extract_plans(report)
    plan = sections.get("plan", "")
    tree = parse_plan_tree(plan)
    shape = plan_shape(tree)

    metrics: dict = {
        "responseChars": len(report),
        "planExtracted": bool(plan.strip()),
        "planStructureBlock": "PLAN_STRUCTURE_START" in report,
        "planTreeParsed": bool(tree),
        "planFolders": shape["folders"],
        "planDepth": shape["depth"],
        "planMaxWidth": shape["maxWidth"],
        "planLeaves": shape["leaves"],
    }

    if brief:
        metrics["gabaritSectionsPresent"] = None
        metrics["gabaritComplete"] = None
    else:
        present = [
            s for s in GABARIT_SECTIONS
            if re.search(rf"###\s*{re.escape(s)}\b", report)
        ]
        metrics["gabaritSectionsPresent"] = present
        metrics["gabaritComplete"] = len(present) == len(GABARIT_SECTIONS)

    reported = None
    m = _VOLUMETRY_RE.search(report)
    if m:
        reported = {
            "items": int(m.group(1)),
            "recordGrps": int(m.group(2)),
            "maxDepth": int(m.group(3)),
        }
    metrics["volumetryReported"] = reported
    if reported is None or scan is None:
        metrics["volumetryMatches"] = None
    else:
        expected = scan["volumetry"]
        metrics["volumetryMatches"] = all(
            reported[k] == expected[k] for k in ("items", "recordGrps", "maxDepth")
        )

    # Verdict « Ordre existant » (gabarit ≥ 1.1.0) + conservation de l'ordre
    # existant : part des dossiers sources **non vides** retrouvés parmi les
    # rubriques du plan (rapprochement par `conservation_label`). Limite
    # documentée : une rubrique *renommée* (libellé différent) compte comme non
    # retrouvée côté source et comme création côté plan — la métrique mesure la
    # conservation littérale, pas la déclaration d'écarts du modèle.
    metrics["ordreExistant"] = _order_verdict(report)
    source = (scan or {}).get("sourceFolders")
    if source is None or not tree:
        metrics["sourceFoldersTotal"] = None
        metrics["sourceFoldersRetained"] = None
        metrics["sourceRetainedPct"] = None
        metrics["planFoldersCreated"] = None
    else:
        src_labels = {
            label for t in source["titles"] if (label := conservation_label(t))
        }
        plan_labels = _plan_rubric_labels(tree)
        retained = src_labels & plan_labels
        metrics["sourceFoldersTotal"] = len(src_labels)
        metrics["sourceFoldersRetained"] = len(retained)
        metrics["sourceRetainedPct"] = (
            round(100 * len(retained) / len(src_labels), 1) if src_labels else None
        )
        metrics["planFoldersCreated"] = len(plan_labels - src_labels)
    return metrics


def classement_metrics(stats: dict) -> dict:
    """Agrège les compteurs CLA-001 renvoyés par `convert_classement_to_resip`.

    Passe-plat volontaire (les compteurs sont calculés à la source, jamais
    re-dérivés des messages d'avertissement) + taux dérivés.
    """
    total = int(stats.get("itemsTotal") or 0)
    classified = int(stats.get("itemsClassified") or 0)
    return {
        "planParsed": bool(stats.get("planParsed")),
        "planMatches": bool(stats.get("planMatches")),
        "foldersOffPlan": len(stats.get("foldersOffPlan") or []),
        "foldersMissing": len(stats.get("foldersMissing") or []),
        "planFolders": int(stats.get("planFolders") or 0),
        "itemsTotal": total,
        "itemsClassified": classified,
        "itemsUnclassified": int(stats.get("itemsUnclassified") or 0),
        "classifiedPct": round(100 * classified / total, 1) if total else None,
        "itemsMalformed": int(stats.get("itemsMalformed") or 0),
        "extensionsFixed": int(stats.get("extensionsFixed") or 0),
        "targetsUnknown": int(stats.get("targetsUnknown") or 0),
        "pathsNotFound": int(stats.get("pathsNotFound") or 0),
        "refsUnresolved": int(stats.get("refsUnresolved") or 0),
        # Sous-dossiers créés sous autorisation. Sert aussi de garde de
        # non-régression (doit valoir 0 pour un run sans consigne d'autorisation).
        "foldersCreated": len(stats.get("foldersCreatedAuthorized") or []),
    }


def _resip_ancestry(rows: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """Depuis des lignes RESIP, renvoie (chemin_item → nom du dossier parent,
    nom de dossier → nom du dossier parent). Utilitaire des métriques."""
    id_to_file = {
        str(r.get("ID")): str(r.get("File"))
        for r in rows
        if r.get("Content.DescriptionLevel") == "RecordGrp"
    }
    item_folder: dict[str, str] = {}
    folder_parent: dict[str, str] = {}
    for r in rows:
        level = r.get("Content.DescriptionLevel")
        parent_file = id_to_file.get(str(r.get("ParentID")), "")
        if level == "Item":
            item_folder[str(r.get("File"))] = parent_file
        elif level == "RecordGrp":
            folder_parent[str(r.get("File"))] = parent_file
    return item_folder, folder_parent


def directives_followed(rows: list[dict], cases: list[dict]) -> dict:
    """Métrique — les consignes de classement sont-elles suivies ?

    `rows` = lignes RESIP produites (`resip.rows` de finalize). `cases` = attentes
    golden, chacune ``{path, expectedFolder}`` (le fichier doit atterrir **dans ce
    dossier exact**) ou ``{path, expectedUnder}`` (le fichier doit atterrir dans ce
    dossier **ou un de ses sous-dossiers** — pour les créations autorisées, dont le
    nom exact du sous-dossier n'est pas prévisible). **Déterministe, sans LLM.**

    Retourne ``{total, followed, followedPct, misses:[{path, landedIn, expected}]}``.
    """
    item_folder, folder_parent = _resip_ancestry(rows)
    total = 0
    followed = 0
    misses: list[dict] = []
    for c in cases:
        path = str(c.get("path", ""))
        total += 1
        landed = item_folder.get(path)
        ok = False
        expected = c.get("expectedFolder", c.get("expectedUnder", ""))
        if landed is not None:
            if "expectedFolder" in c:
                ok = landed == str(c["expectedFolder"])
            elif "expectedUnder" in c:
                target = str(c["expectedUnder"])
                cur: str | None = landed
                seen: set[str] = set()
                while cur is not None and cur not in seen:
                    if cur == target:
                        ok = True
                        break
                    seen.add(cur)
                    cur = folder_parent.get(cur)
        if ok:
            followed += 1
        else:
            misses.append({"path": path, "landedIn": landed or "", "expected": str(expected)})
    return {
        "total": total,
        "followed": followed,
        "followedPct": round(100 * followed / total, 1) if total else None,
        "misses": misses,
    }


# ── Agent AGT-001 : exactitude des tool-calls et des filtres ─────────────────

def _filter_paths(df: pd.DataFrame, filtre: dict | None) -> frozenset[str] | None:
    """Ensemble des chemins de fichiers sélectionnés par un filtre structuré
    None si le filtre est invalide (l'équivalence n'est pas établie)."""
    hits = filtrer_items(df, filtre or None)
    if isinstance(hits, dict):
        return None
    return frozenset(hits["File"].astype(str))


def _emitted_filter(name: str, arguments: dict) -> dict | None:
    """Filtre structuré équivalent à un appel d'outil de l'agent — l'argument
    `filtre` pour les outils qui en portent un, une traduction pour les outils
    à arguments propres. None quand l'outil n'exprime pas de sélection
    (`stats`).

    NB : `lister_dossier` montre le contenu **direct** d'un dossier là où le
    filtre `dossier` couvre la sous-arborescence — approximation assumée,
    suffisante pour juger que l'agent a visé le bon périmètre."""
    if name in ("compter", "echantillonner", "mots_frequents"):
        filtre = arguments.get("filtre")
        return filtre if isinstance(filtre, dict) else {}
    if name == "chercher":
        mots = arguments.get("mots_cles")
        if isinstance(mots, str):
            mots = [m for m in mots.split() if m]
        return {"mots_cles": mots} if mots else None
    if name == "lister_dossier":
        chemin = str(arguments.get("chemin") or ".").strip()
        return {"dossier": chemin} if chemin not in (".", "") else {}
    return None


def _paired_tool_calls(events: list[dict]) -> list[dict]:
    """Appaire les événements `tool`/`toolResult` d'un tour d'agent en une
    liste `{name, arguments, result}` (un `toolResult` orphelin — arguments
    JSON illisibles en mode natif — est ignoré : aucun outil n'a tourné)."""
    calls: list[dict] = []
    pending: dict | None = None
    for event in events:
        if event.get("type") == "tool":
            pending = event
        elif event.get("type") == "toolResult":
            if pending is not None and pending.get("name") == event.get("name"):
                calls.append({
                    "name": str(event.get("name", "")),
                    "arguments": pending.get("arguments") or {},
                    "result": event.get("result") or {},
                })
            pending = None
    return calls


def agent_case_metrics(events: list[dict], attendu: dict, df: pd.DataFrame) -> dict:
    """Mesure un cas du corpus sur les événements d'un tour d'agent
    (`core.agt_agent.agent_turn`) — pur, sans LLM.

    ``attendu`` (le golden du cas, `type: "requete"`) : `outils` (noms admis,
    au moins un doit être appelé), `filtre` (facultatif : un appel admis doit
    émettre un filtre **sémantiquement équivalent** — même sélection de
    fichiers sur ``df``), `verifierTotal` (facultatif : le total exact Pandas
    du filtre golden doit figurer dans la réponse finale).

    Chaque vérification vaut True/False, ou None quand le golden ne la demande
    pas ; `reussi` = toutes les vérifications demandées passent.
    """
    calls = _paired_tool_calls(events)
    final = events[-1] if events and events[-1].get("type") == "final" else {}
    answer = str(final.get("answer") or "")
    checks: dict[str, bool | None] = {
        "outilAttendu": None,
        "filtreEquivalent": None,
        "reponseExacte": None,
    }
    filtre_golden = attendu.get("filtre")
    score_filtre = filtre_golden is not None
    expected_paths = _filter_paths(df, filtre_golden) if score_filtre else None

    wanted = attendu.get("outils") or []
    matching = [c for c in calls if c["name"] in wanted]
    if wanted:
        checks["outilAttendu"] = bool(matching)
    if score_filtre:
        candidates = matching if wanted else calls
        checks["filtreEquivalent"] = any(
            (emis := _emitted_filter(c["name"], c["arguments"])) is not None
            and _filter_paths(df, emis) == expected_paths
            for c in candidates
        )
    if attendu.get("verifierTotal"):
        total = compter(df, filtre_golden or None).get("total")
        checks["reponseExacte"] = (
            bool(re.search(rf"\b{int(total)}\b", answer))
            if total is not None else None
        )

    demanded = [v for v in checks.values() if v is not None]
    return {
        "reussi": bool(demanded) and all(demanded),
        **checks,
        "steps": final.get("steps"),
        "toolCalls": [{"name": c["name"], "arguments": c["arguments"]} for c in calls],
        "reponse": answer[:300],
    }


def _dim_str(dim: dict) -> str:
    return f"{dim['ok']}/{dim['mesures']}" if dim.get("mesures") else "—"


def agent_run_metrics(case_results: list[dict]) -> dict:
    """Agrège les cas d'un run AGT-001 : l'**exactitude** (part de cas réussis)
    est la métrique de seuil du critère d'acceptation ; les dimensions
    (outil, filtre, réponse) localisent ce qui échoue."""
    total = len(case_results)
    ok = sum(1 for c in case_results if c.get("reussi"))

    def dim(key: str) -> dict:
        measured = [c.get(key) for c in case_results if c.get(key) is not None]
        return {"ok": sum(1 for v in measured if v), "mesures": len(measured)}

    steps = [c["steps"] for c in case_results if isinstance(c.get("steps"), int)]
    return {
        "cases": total,
        "reussis": ok,
        "exactitudePct": round(100 * ok / total, 1) if total else None,
        "outilAttendu": dim("outilAttendu"),
        "filtreEquivalent": dim("filtreEquivalent"),
        "reponseExacte": dim("reponseExacte"),
        "stepsMoyen": round(sum(steps) / len(steps), 1) if steps else None,
        "erreurs": sum(1 for c in case_results if c.get("error")),
    }


# ── Tableau lisible (critère d'acceptation) ───────────────────────────────────

def _check(value: object) -> str:
    """✓ / ✗ / — (non mesurable)."""
    if value is None:
        return "—"
    return "✓" if value else "✗"


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Table texte alignée (stdout). Sans dépendance, lisible dans un terminal."""
    widths = [
        max(len(headers[i]), *(len(r[i]) for r in rows)) if rows else len(headers[i])
        for i in range(len(headers))
    ]

    def fmt(cells: list[str]) -> str:
        return "  ".join(c.ljust(widths[i]) for i, c in enumerate(cells)).rstrip()

    lines = [fmt(headers), fmt(["-" * w for w in widths])]
    lines.extend(fmt(r) for r in rows)
    return "\n".join(lines)


def _usage_str(usage: dict | None) -> str:
    if not usage or not usage.get("total_tokens"):
        return "—"
    return str(usage["total_tokens"])


def _prep_label(prep: dict | None) -> str:
    """Suffixe compact de la variante de préparation d'entrée (sweep) accolé au
    modèle : `[n=5]`, `[n=tous]`, `[n=3,dates=off]` (nettoyage de dates désactivé).
    Vide quand le run ne porte pas de variante (rétrocompatible)."""
    if not prep:
        return ""
    n = prep.get("sampleN")
    n_str = "tous" if n == 0 else str(n)
    label = f" [n={n_str}"
    if prep.get("cleanDates") is False:
        label += ",dates=off"
    return label + "]"


def format_eval_tables(runs: list[dict]) -> str:
    """Met en forme les runs d'une éval en tables lisibles (AUD puis CLA).

    Chaque run : `{dataset, model, agent, mode?, brief?, durationS, usage,
    metrics, error?}` — cf. `cli.py cmd_eval`. Un run en erreur est affiché
    avec son message (la matrice continue malgré un modèle injoignable).
    """
    blocks: list[str] = []

    aud_runs = [r for r in runs if r["agent"] == "AUD-001"]
    if aud_runs:
        rows = []
        for r in aud_runs:
            m = r.get("metrics")
            if m is None:
                rows.append([r["dataset"], r["model"], "ERREUR : " + str(r.get("error", "?"))]
                            + ["—"] * 9)
                continue
            gabarit = m["gabaritComplete"]
            gabarit_str = (
                "—" if gabarit is None
                else "✓" if gabarit
                else f"{len(m['gabaritSectionsPresent'])}/{len(GABARIT_SECTIONS)}"
            )
            # Rétrocompatible : un rapport d'éval historisé avant la métrique de
            # conservation n'a pas ces clés → non mesurable.
            ordre = m.get("ordreExistant")
            ordre_str = {
                "STRUCTURÉ": "structuré", "PARTIELLEMENT STRUCTURÉ": "partiel",
                "ABSENT": "absent",
            }.get(ordre, "—")
            retained = m.get("sourceFoldersRetained")
            if retained is None:
                conserv_str = "—"
            else:
                conserv_str = f"{retained}/{m['sourceFoldersTotal']}"
                if m.get("sourceRetainedPct") is not None:
                    conserv_str += f" ({m['sourceRetainedPct']}%)"
            rows.append([
                r["dataset"],
                r["model"] + _prep_label(r.get("prep")) + (" (brief)" if r.get("brief") else ""),
                _check(m["planExtracted"]),
                _check(m["planStructureBlock"]),
                _check(m["planTreeParsed"]),
                f"{m['planFolders']} ({m['planDepth']} niv. ×{m['planMaxWidth']})",
                ordre_str,
                conserv_str,
                gabarit_str,
                _check(m["volumetryMatches"]),
                format_duration(r.get("durationS") or 0),
                _usage_str(r.get("usage")),
            ])
        blocks.append(
            "AUD-001 — audit\n"
            + format_table(
                ["jeu", "modèle", "plan", "bloc", "arbre", "dossiers",
                 "ordre", "conserv.", "gabarit", "volum.", "durée", "tokens"],
                rows,
            )
        )

    cla_runs = [r for r in runs if r["agent"] == "CLA-001"]
    if cla_runs:
        rows = []
        for r in cla_runs:
            m = r.get("metrics")
            if m is None:
                rows.append([r["dataset"], r["model"], r.get("mode") or "—",
                             "ERREUR : " + str(r.get("error", "?"))] + ["—"] * 7)
                continue
            rows.append([
                r["dataset"],
                r["model"],
                r.get("mode") or "—",
                f"{m['itemsClassified']}/{m['itemsTotal']}",
                _check(m["planMatches"]),
                f"{m['foldersOffPlan']}/{m['foldersMissing']}",
                str(m["itemsMalformed"]),
                str(m["extensionsFixed"]),
                str(m["refsUnresolved"]),
                format_duration(r.get("durationS") or 0),
                _usage_str(r.get("usage")),
            ])
        blocks.append(
            "CLA-001 — classement\n"
            + format_table(
                ["jeu", "modèle", "mode", "classés", "plan",
                 "hors/manq.", "malf.", "ext.corr.", "refs✗", "durée", "tokens"],
                rows,
            )
        )

    agt_runs = [r for r in runs if r["agent"] == "AGT-001"]
    if agt_runs:
        rows = []
        for r in agt_runs:
            m = r.get("metrics")
            if m is None:
                rows.append([r["dataset"], r["model"], r.get("mode") or "—",
                             "ERREUR : " + str(r.get("error", "?"))] + ["—"] * 6)
                continue
            exactitude = f"{m['reussis']}/{m['cases']}"
            if m["exactitudePct"] is not None:
                exactitude += f" ({m['exactitudePct']}%)"
            rows.append([
                r["dataset"],
                r["model"],
                r.get("mode") or "—",
                exactitude,
                _dim_str(m["outilAttendu"]),
                _dim_str(m["filtreEquivalent"]),
                _dim_str(m["reponseExacte"]),
                str(m["stepsMoyen"]) if m["stepsMoyen"] is not None else "—",
                format_duration(r.get("durationS") or 0),
                _usage_str(r.get("usage")),
            ])
        blocks.append(
            "AGT-001 — agent (exactitude des requêtes)\n"
            + format_table(
                ["jeu", "modèle", "mode", "exactitude", "outil", "filtre",
                 "réponse", "étapes", "durée", "tokens"],
                rows,
            )
        )

    return "\n\n".join(blocks) if blocks else "(aucun run)"
