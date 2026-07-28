"""Journal de traitement — traçabilité réglementaire.

Construit, à partir des **métadonnées** d'un traitement (jamais du contenu des
documents), un journal **horodaté exportable** : fichier traité, modèle, versions
de prompt, durée, anomalies, et une **déclaration de confidentialité** explicite.
Destiné aux institutions soumises à des obligations de traçabilité (archives
publiques notamment) qui doivent pouvoir justifier *ce qui a été traité, par quel
modèle, avec quel résultat* — sans jamais exposer le contenu traité.

Moteur **pur, déterministe, sans LLM ni I/O** — consommé par la CLI
(`odacea {audit,classement,run} … --journal FICHIER`) et l'API (`POST /journal`,
prêt pour un export local côté front). Le contenu des documents ne figure jamais
dans le journal : seules les métadonnées et des compteurs y entrent.
"""
from __future__ import annotations

from datetime import datetime

from core.tokens import format_duration, format_usage_line

# Version du *format* du journal (distincte de PROMPT_VERSION) : à incrémenter si
# la structure du document de traçabilité change, pour qu'un journal archivé reste
# interprétable.
JOURNAL_VERSION = "1"

_COMMAND_LABELS = {
    "audit": "Audit (AUD-001)",
    "classement": "Classement (CLA-001)",
    "run": "Pipeline complet (audit + classement)",
    "apply": "Application physique du classement (copie vers l'arborescence cible)",
}

# Origine du plan de classement : plan produit par l'audit LLM ou plan fourni
# par l'archiviste (bypass de l'appel d'audit).
_PLAN_ORIGIN_LABELS = {
    "audit_llm": "plan produit par l'audit LLM (AUD-001)",
    "fourni": "plan fourni par l'archiviste (sans appel LLM d'audit)",
}


def _normalize_plan_origin(origin: str | None) -> str | None:
    """Valeur d'origine normalisée (`audit_llm`/`fourni`) ou None si non renseignée."""
    if origin is None:
        return None
    candidate = str(origin).strip().lower()
    return candidate if candidate in _PLAN_ORIGIN_LABELS else None


def confidentiality_lines(description_sent: bool) -> list[str]:
    """Déclaration de confidentialité du traitement (RGPD de l'outil, cf. H5).

    Le libellé s'adapte au seul vecteur par lequel du contenu *dérivé* peut
    atteindre le modèle : l'option « inclure la description » (Content.Description,
    renseignée localement à l'étape 0 facultative). Hors ce cas, seules les
    métadonnées sont transmises.
    """
    if description_sent:
        first = (
            "Métadonnées (chemins, noms, dates) ET descriptions documentaires "
            "(Content.Description, renseignées localement à l'étape d'enrichissement) "
            "transmises au modèle ; le texte intégral des documents n'a pas été transmis."
        )
    else:
        first = (
            "Seules les métadonnées (chemins, noms, dates) ont été transmises au "
            "modèle ; le contenu des documents n'a jamais quitté le poste."
        )
    return [
        first,
        "Aucune donnée n'est transmise hors du fournisseur de modèle explicitement "
        "choisi ; un modèle local (Ollama, LM Studio) garde l'intégralité du "
        "traitement sur l'infrastructure de l'institution.",
        "ODACEA est sans état côté serveur : aucun document ni aucune métadonnée "
        "n'est conservé après le traitement.",
    ]


def build_journal(
    *,
    command: str,
    input_name: str,
    model: str | None,
    prompt_versions: dict[str, str],
    models: dict[str, str] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    duration_s: float | None = None,
    rows: int | None = None,
    usage: dict | None = None,
    resumed: bool = False,
    ok: bool = True,
    exit_code: int = 0,
    warnings: list[str] | None = None,
    conformity: dict | None = None,
    description_sent: bool = False,
    plan_origin: str | None = None,
    plan_modified: bool = False,
    generated_at: str | None = None,
) -> dict:
    """Construit l'enregistrement structuré (JSON-ready, camelCase) du journal.

    `warnings` alimente les anomalies ; un échec sans anomalie explicite reçoit
    une anomalie de synthèse (le journal ne tait jamais un échec). `conformity`
    (les `stats` du classement) est conservé tel quel quand présent. Aucun champ
    ne porte de contenu documentaire : `input_name` est un **nom de fichier**, pas
    un chemin de source ni des données.

    `models` (optionnel) consigne le modèle **par agent** (`{"AUD-001": …,
    "CLA-001": …}`) — utile quand l'audit et le classement ont été exécutés par des
    modèles différents. Le champ `model` unique reste renseigné (rétro-compat CLI,
    où un `run` n'utilise qu'un seul modèle).

    `plan_origin` trace l'origine du plan de classement : ``"audit_llm"`` (issu
    d'un appel AUD-001) ou ``"fourni"`` (fourni par l'archiviste, bypass de l'audit).
    ``plan_modified`` indique une retouche manuelle. Le journal distingue ainsi sans
    ambiguïté un run avec audit LLM d'un run à plan fourni. ``None`` = origine non
    renseignée (rétro-compat) → ligne omise.
    """
    anomalies = [w for w in (warnings or []) if w and str(w).strip()]
    if not ok and not anomalies:
        anomalies = [f"Traitement terminé en échec (code {exit_code})."]

    return {
        "planOrigin": _normalize_plan_origin(plan_origin),
        "planModified": bool(plan_modified),
        "tool": "ODACEA",
        "journalVersion": JOURNAL_VERSION,
        "generatedAt": generated_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        "command": command,
        "commandLabel": _COMMAND_LABELS.get(command, command),
        "source": {"file": input_name, "rows": rows},
        "model": model,
        "models": dict(models or {}),
        "promptVersions": dict(prompt_versions or {}),
        "timing": {
            "startedAt": started_at,
            "finishedAt": finished_at,
            "durationS": duration_s,
        },
        "usage": usage,
        "resumed": bool(resumed),
        "outcome": {"ok": bool(ok), "exitCode": int(exit_code)},
        "anomalies": anomalies,
        "conformity": conformity,
        "confidentiality": confidentiality_lines(description_sent),
    }


def _conformity_lines(conformity: dict) -> list[str]:
    """Lignes « Volumétrie et conformité » à partir des `stats` du classement."""
    lines: list[str] = []
    total = conformity.get("itemsTotal")
    classified = conformity.get("itemsClassified")
    if total is not None:
        lines.append(f"- Items classés : {classified if classified is not None else '?'} / {total}")
    if conformity.get("itemsUnclassified"):
        lines.append(f"- Items non classés : {conformity['itemsUnclassified']}")

    if not conformity.get("planParsed"):
        lines.append("- Respect du plan : non mesurable (arborescence du plan illisible)")
    elif conformity.get("planMatches"):
        lines.append("- Respect du plan : arborescence identique au plan d'audit ✓")
    else:
        off = conformity.get("foldersOffPlan", []) or []
        miss = conformity.get("foldersMissing", []) or []
        lines.append(
            f"- Respect du plan : écart(s) — {len(off)} dossier(s) hors plan, "
            f"{len(miss)} dossier(s) du plan non réalisé(s)"
        )
        for f in off:
            lines.append(f"  - hors plan : {f}")
        for f in miss:
            lines.append(f"  - non réalisé : {f}")

    for key, label in (
        ("itemsMalformed", "Items à cible malformée rattachés à la racine"),
        ("extensionsFixed", "Extensions de fichier corrigées (sécurité)"),
        ("targetsUnknown", "Dossiers cibles inconnus du plan"),
        ("pathsNotFound", "Chemins de fichier introuvables"),
        ("refsUnresolved", "Références non résolues (mode Ref)"),
    ):
        if conformity.get(key):
            lines.append(f"- {label} : {conformity[key]}")
    return lines


def format_journal_markdown(journal: dict) -> str:
    """Rend le journal en Markdown lisible — le document de traçabilité exporté.

    Pendant déterministe de `build_journal` : aucune donnée nouvelle, mise en
    forme seule. Destiné à être archivé tel quel par l'institution.
    """
    src = journal.get("source", {})
    timing = journal.get("timing", {})
    outcome = journal.get("outcome", {})
    pv = journal.get("promptVersions", {})

    lines: list[str] = [
        "# Journal de traitement ODACEA",
        "",
        f"*Document de traçabilité — généré le {journal.get('generatedAt', '—')} "
        f"(format v{journal.get('journalVersion', JOURNAL_VERSION)}).*",
        "",
        "## Traitement",
        "",
        f"- Opération : {journal.get('commandLabel', journal.get('command', '—'))}",
    ]

    rows = src.get("rows")
    file_line = f"- Fichier traité : {src.get('file') or '—'}"
    if rows is not None:
        file_line += f" ({rows} lignes)"
    lines.append(file_line)
    models = {k: v for k, v in (journal.get("models") or {}).items() if v}
    if models:
        per_agent = " · ".join(f"{name} : {mdl}" for name, mdl in sorted(models.items()))
        lines.append(f"- Modèle par étape : {per_agent}")
    else:
        lines.append(f"- Modèle : {journal.get('model') or '—'}")

    if pv:
        versions = " · ".join(f"{name} v{ver}" for name, ver in sorted(pv.items()))
        lines.append(f"- Versions de prompt : {versions}")

    origin = journal.get("planOrigin")
    if origin in _PLAN_ORIGIN_LABELS:
        origin_line = f"- Origine du plan : {_PLAN_ORIGIN_LABELS[origin]}"
        if journal.get("planModified"):
            origin_line += " — avec retouches manuelles"
        lines.append(origin_line)

    started, finished = timing.get("startedAt"), timing.get("finishedAt")
    if started:
        lines.append(f"- Début : {started}")
    if finished:
        lines.append(f"- Fin : {finished}")
    duration = timing.get("durationS")
    if duration is not None:
        lines.append(f"- Durée : {format_duration(duration)}")

    if journal.get("resumed"):
        lines.append("- Reprise d'un run interrompu : oui")

    issue = "succès" if outcome.get("ok") else f"échec (code {outcome.get('exitCode', '?')})"
    lines.append(f"- Issue : {issue}")

    usage_line = format_usage_line(journal.get("usage"))
    if usage_line:
        lines += ["", "## Consommation", "", f"- Tokens — {usage_line}"]

    conformity = journal.get("conformity")
    if conformity:
        conf_lines = _conformity_lines(conformity)
        if conf_lines:
            lines += ["", "## Volumétrie et conformité", "", *conf_lines]

    anomalies = journal.get("anomalies", [])
    lines += ["", f"## Anomalies ({len(anomalies)})", ""]
    if anomalies:
        lines += [f"- {a}" for a in anomalies]
    else:
        lines.append("Aucune anomalie signalée.")

    lines += ["", "## Confidentialité des données", ""]
    lines += [f"- {c}" for c in journal.get("confidentiality", [])]
    lines.append("")
    return "\n".join(lines)
