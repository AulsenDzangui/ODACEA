"""Tests du journal de traitement — moteur `core.journal`.

Pur et déterministe (aucun LLM, aucune I/O) : on vérifie la structure du journal
(métadonnées seules, jamais de contenu), l'adaptation de la déclaration de
confidentialité, la synthèse d'anomalie sur échec, et le rendu Markdown.
"""
from core.journal import (
    JOURNAL_VERSION,
    build_journal,
    confidentiality_lines,
    format_journal_markdown,
)

_FIXED_TS = "2026-06-15T10:00:00+02:00"


def _journal(**overrides):
    base = dict(
        command="run",
        input_name="vrac.csv",
        model="claude-opus-4-8",
        prompt_versions={"AUD-001": "3", "CLA-001": "5"},
        duration_s=42.0,
        rows=112,
        generated_at=_FIXED_TS,
    )
    base.update(overrides)
    return build_journal(**base)


def test_build_journal_core_fields():
    j = _journal()
    assert j["tool"] == "ODACEA"
    assert j["journalVersion"] == JOURNAL_VERSION
    assert j["generatedAt"] == _FIXED_TS
    assert j["command"] == "run"
    assert j["commandLabel"].startswith("Pipeline complet")
    assert j["source"] == {"file": "vrac.csv", "rows": 112}
    assert j["model"] == "claude-opus-4-8"
    assert j["promptVersions"] == {"AUD-001": "3", "CLA-001": "5"}
    assert j["timing"]["durationS"] == 42.0
    assert j["outcome"] == {"ok": True, "exitCode": 0}
    assert j["anomalies"] == []


def test_journal_carries_no_document_content():
    """Garde-fou : seules des métadonnées (nom de fichier, compteurs) — le
    journal ne doit transporter ni chemin de source ni contenu."""
    j = _journal(input_name="vrac.csv")
    # `source.file` est un nom de fichier, pas un chemin absolu/relatif de source.
    assert "/" not in j["source"]["file"] and "\\" not in j["source"]["file"]


def test_confidentiality_metadata_only():
    lines = confidentiality_lines(description_sent=False)
    assert any("métadonnées" in line and "jamais quitté le poste" in line for line in lines)
    j = _journal(description_sent=False)
    assert j["confidentiality"] == lines


def test_confidentiality_adapts_when_description_sent():
    lines = confidentiality_lines(description_sent=True)
    assert any("descriptions documentaires" in line for line in lines)
    assert any("texte intégral des documents n'a pas été transmis" in line for line in lines)


def test_warnings_become_anomalies():
    j = _journal(warnings=["3 NewTitle(s) corrigé(s)", "", "  ", "1 dossier hors plan"])
    # Les chaînes vides/blanches sont filtrées.
    assert j["anomalies"] == ["3 NewTitle(s) corrigé(s)", "1 dossier hors plan"]


def test_failure_without_warning_gets_synthetic_anomaly():
    j = _journal(ok=False, exit_code=3, warnings=[])
    assert j["anomalies"] == ["Traitement terminé en échec (code 3)."]
    assert j["outcome"] == {"ok": False, "exitCode": 3}


def test_failure_with_warnings_keeps_them():
    j = _journal(ok=False, exit_code=3, warnings=["plan illisible"])
    assert j["anomalies"] == ["plan illisible"]


def test_markdown_render_contains_key_sections():
    j = _journal(
        usage={"input_tokens": 12000, "output_tokens": 3000, "total_tokens": 15000},
        conformity={
            "planParsed": True, "planMatches": False,
            "foldersOffPlan": ["A_trier"], "foldersMissing": [],
            "itemsTotal": 80, "itemsClassified": 79, "itemsUnclassified": 1,
            "itemsMalformed": 2,
        },
        warnings=["2 cible(s) malformée(s)"],
    )
    md = format_journal_markdown(j)
    assert md.startswith("# Journal de traitement ODACEA")
    assert "## Traitement" in md
    assert "vrac.csv (112 lignes)" in md
    assert "AUD-001 v3 · CLA-001 v5" in md
    assert "## Consommation" in md and "entrée : 12,0 k" in md
    assert "## Volumétrie et conformité" in md
    assert "Items classés : 79 / 80" in md
    assert "hors plan : A_trier" in md
    assert "Items à cible malformée rattachés à la racine : 2" in md
    assert "## Anomalies (1)" in md
    assert "## Confidentialité des données" in md


def test_models_per_agent_stored_and_rendered():
    """Modèle figé par agent : la carte `models` est conservée et rendue par
    étape (audit et classement peuvent avoir tourné sur des modèles distincts)."""
    j = _journal(models={"AUD-001": "claude-opus-4-8", "CLA-001": "ollama/llama3"})
    assert j["models"] == {"AUD-001": "claude-opus-4-8", "CLA-001": "ollama/llama3"}
    md = format_journal_markdown(j)
    assert "Modèle par étape :" in md
    assert "AUD-001 : claude-opus-4-8" in md
    assert "CLA-001 : ollama/llama3" in md
    # La ligne mono-modèle n'est pas émise quand la carte par agent est présente.
    assert "- Modèle : " not in md


def test_markdown_falls_back_to_single_model_without_models_map():
    """Sans carte `models` (cas CLI mono-modèle), le champ `model` unique est rendu."""
    j = _journal(model="claude-opus-4-8")
    assert j["models"] == {}
    md = format_journal_markdown(j)
    assert "- Modèle : claude-opus-4-8" in md
    assert "Modèle par étape :" not in md


def test_markdown_no_anomaly_renders_neutral_line():
    md = format_journal_markdown(_journal())
    assert "## Anomalies (0)" in md
    assert "Aucune anomalie signalée." in md


def test_markdown_conformity_not_measurable():
    j = _journal(conformity={"planParsed": False})
    md = format_journal_markdown(j)
    assert "Respect du plan : non mesurable" in md


def test_generated_at_defaults_when_absent():
    j = build_journal(
        command="audit", input_name="x.csv", model="m",
        prompt_versions={"AUD-001": "3"},
    )
    # ISO 8601 avec fuseau (……+hh:mm ou ……Z) — non vide, déterminé à l'appel.
    assert j["generatedAt"] and "T" in j["generatedAt"]
