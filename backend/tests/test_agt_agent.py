"""Boucle agent — testée sans LLM.

`FakeToolProvider` (conftest) rejoue des séquences scriptées : on vérifie les
deux modes (function calling natif, repli JSON contraint), la dégradation
douce sur sortie invalide, le garde-fou MAX_STEPS, et le critère d'acceptation
central du lot : **le CSV complet n'apparaît jamais dans un prompt** — le
modèle ne voit que le digest et les résultats d'outils.
"""
import json

import pytest

from core.agt_agent import (
    MAX_STEPS,
    _parse_json_action,
    agent_turn,
    resolve_tool_mode,
    run_tool,
)
from core.agt_session import SessionStore
from core.csv_handler import csv_to_string
from tests.conftest import FakeToolProvider


@pytest.fixture
def session(small_df):
    return SessionStore().create(small_df, "Digest du vrac : 6 fichiers.")


def events_of(gen) -> list[dict]:
    return list(gen)


def final_of(events: list[dict]) -> dict:
    assert events[-1]["type"] == "final"
    return events[-1]


# ── resolve_tool_mode ────────────────────────────────────────────────────────

def test_resolve_tool_mode_auto():
    assert resolve_tool_mode("auto", "claude-opus-4-8", None) == "native"
    assert resolve_tool_mode("auto", "gpt-5.1", "") == "native"
    assert resolve_tool_mode("auto", "qwen3:14b", "http://localhost:1234/v1") == "json"
    assert resolve_tool_mode("auto", "ollama/qwen3:14b", None) == "json"


def test_resolve_tool_mode_explicite():
    assert resolve_tool_mode("json", "claude-opus-4-8", None) == "json"
    assert resolve_tool_mode("native", "ollama/qwen3", None) == "native"


# ── run_tool ─────────────────────────────────────────────────────────────────

def test_run_tool_dispatch(session):
    assert run_tool(session, "compter", {})["total"] == 6


def test_run_tool_inconnu(session):
    out = run_tool(session, "supprimer", {})
    assert "erreur" in out
    assert "compter" in out["erreur"]  # les outils disponibles sont listés


def test_run_tool_arguments_invalides(session):
    assert "erreur" in run_tool(session, "stats", {"pear": "extension"})
    assert "erreur" in run_tool(session, "compter", [])  # type: ignore[arg-type]


def test_run_tool_mots_frequents(session):
    """L'outil d'agrégation de termes est dispatché comme les outils."""
    out = run_tool(session, "mots_frequents", {"n": 3})
    assert out["termes"]["eleves"] == 2
    assert list(out["termes"]) == ["cantine", "divers", "eleves"]


def test_outils_exposes_coherents():
    """Les schémas natifs (AGT_001.TOOLS) et le registre d'exécution couvrent
    exactement les mêmes outils — un outil ajouté d'un seul côté est détecté."""
    from core import agt_agent
    from prompts import AGT_001

    declared = {t["function"]["name"] for t in AGT_001.TOOLS}
    executable = set(agt_agent._TOOL_REGISTRY)
    assert declared == executable
    # Le protocole du repli JSON décrit les mêmes outils que le mode natif.
    protocol = AGT_001.build_system_prompt("digest", json_mode=True)
    for name in declared:
        assert f"{name}(" in protocol


# ── Canal optionnel « rapport d'audit » (0.6.0) ──────────────────────────────

def test_rapport_audit_absent_prompt_inchange():
    """Sans rapport (None ou vide), le system prompt est **byte-identique** à
    l'appel historique — canal opt-in, aucune régression pour l'exploration à froid."""
    from prompts import AGT_001

    base = AGT_001.build_system_prompt("mon digest")
    assert AGT_001.build_system_prompt("mon digest", audit_report=None) == base
    assert AGT_001.build_system_prompt("mon digest", audit_report="   ") == base
    # Idem en mode repli JSON.
    base_json = AGT_001.build_system_prompt("mon digest", json_mode=True)
    assert (
        AGT_001.build_system_prompt("mon digest", json_mode=True, audit_report=None)
        == base_json
    )


def test_rapport_audit_injecte_apres_digest_avant_protocole():
    """Fourni, le rapport apparaît après le digest et avant le protocole JSON,
    encadré comme contexte (pas comme suspect)."""
    from prompts import AGT_001

    prompt = AGT_001.build_system_prompt(
        "DIGEST-XYZ", json_mode=True, audit_report="RAPPORT-ABC"
    )
    assert "RAPPORT-ABC" in prompt
    assert "Rapport d'audit du projet" in prompt
    # Ordre : digest < rapport < protocole des outils.
    assert prompt.index("DIGEST-XYZ") < prompt.index("RAPPORT-ABC")
    assert prompt.index("RAPPORT-ABC") < prompt.index("Format de réponse")


# ── _parse_json_action ───────────────────────────────────────────────────────

def test_parse_json_action_tolerant():
    assert _parse_json_action('{"reponse": "ok"}') == {"reponse": "ok"}
    fenced = 'Voici :\n```json\n{"outil": "stats", "arguments": {"par": "extension"}}\n```'
    assert _parse_json_action(fenced)["outil"] == "stats"
    nested = '{"outil": "compter", "arguments": {"filtre": {"mots_cles": ["a b"]}}}'
    assert _parse_json_action(nested)["arguments"]["filtre"]["mots_cles"] == ["a b"]
    assert _parse_json_action("aucun JSON ici") is None
    assert _parse_json_action('{"cassé": ') is None


# ── Mode natif (function calling) ────────────────────────────────────────────

def test_turn_native_outil_puis_reponse(session):
    provider = FakeToolProvider([
        [("compter", '{"filtre": {"extension": "pdf"}}')],
        "Il y a 1 fichier PDF dans ce vrac.",
    ])
    events = events_of(agent_turn(session, "Combien de PDF ?", provider, "native"))

    tool = next(e for e in events if e["type"] == "tool")
    assert tool["name"] == "compter"
    result = next(e for e in events if e["type"] == "toolResult")
    assert result["result"]["total"] == 1  # chiffre exact, calculé par Pandas
    assert final_of(events)["answer"] == "Il y a 1 fichier PDF dans ce vrac."
    assert final_of(events)["steps"] == 2

    # Protocole OpenAI rejoué : assistant(tool_calls) puis tool(result).
    second_call = provider.calls[1]["messages"]
    assert second_call[-2]["role"] == "assistant"
    assert second_call[-1]["role"] == "tool"
    assert json.loads(second_call[-1]["content"])["total"] == 1


def test_turn_native_historique_et_usage(session):
    provider = FakeToolProvider(["Réponse directe."])
    events_of(agent_turn(session, "Bonjour ?", provider, "native"))
    assert session.history == [
        {"role": "user", "content": "Bonjour ?"},
        {"role": "assistant", "content": "Réponse directe."},
    ]
    assert session.usage_total["total_tokens"] == 120  # cumul par session

    provider2 = FakeToolProvider(["Encore."])
    events_of(agent_turn(session, "Suite ?", provider2, "native"))
    # Le tour suivant reçoit l'historique compact.
    msgs = provider2.calls[0]["messages"]
    assert {"role": "user", "content": "Bonjour ?"} in msgs
    assert session.usage_total["total_tokens"] == 240


def test_turn_native_arguments_json_invalides(session):
    """Des arguments non parsables ne cassent pas le tour : l'erreur est
    renvoyée au modèle, qui peut se corriger."""
    provider = FakeToolProvider([
        [("compter", '{"filtre": ')],
        "Je n'ai pas pu compter.",
    ])
    events = events_of(agent_turn(session, "Combien ?", provider, "native"))
    result = next(e for e in events if e["type"] == "toolResult")
    assert "erreur" in result["result"]
    assert final_of(events)["answer"] == "Je n'ai pas pu compter."


def test_turn_native_max_steps(session):
    """Au-delà de MAX_STEPS appels d'outils, un dernier appel SANS outils force
    la conclusion avec les résultats déjà obtenus."""
    provider = FakeToolProvider(
        [[("compter", "{}")]] * MAX_STEPS + ["Conclusion forcée."]
    )
    events = events_of(agent_turn(session, "Explore tout.", provider, "native"))
    assert final_of(events)["answer"] == "Conclusion forcée."
    assert final_of(events)["steps"] == MAX_STEPS + 1
    assert provider.calls[-1]["tools"] is None  # plus d'outils au tour de conclusion
    assert "meilleure réponse" in provider.calls[-1]["messages"][-1]["content"]


def test_csv_jamais_dans_le_prompt(session, small_df):
    """Critère d'acceptation : le CSV ne transite pas dans les prompts —
    seuls le digest (system) et les résultats d'outils paginés y figurent."""
    csv_text = csv_to_string(small_df)
    provider = FakeToolProvider([
        [("lister_dossier", '{"chemin": "."}')],
        "Voilà.",
    ])
    events_of(agent_turn(session, "Que contient la racine ?", provider, "native"))
    for call in provider.calls:
        for message in call["messages"]:
            content = message.get("content") or ""
            assert csv_text not in str(content)
            # Borne de tokens d'entrée par message : un résultat d'outil paginé
            # reste petit, très loin d'un CSV complet sérialisé.
            assert len(str(content)) < 6000


# ── Mode repli JSON (petits modèles locaux) ──────────────────────────────────

def test_turn_json_outil_puis_reponse(session):
    provider = FakeToolProvider([
        '{"outil": "stats", "arguments": {"par": "extension"}}',
        '{"reponse": "Le vrac compte 6 fichiers, surtout des xlsx."}',
    ])
    events = events_of(agent_turn(session, "Quels formats ?", provider, "json"))
    tool = next(e for e in events if e["type"] == "tool")
    assert tool["name"] == "stats"
    result = next(e for e in events if e["type"] == "toolResult")
    assert result["result"]["total"] == 6
    assert final_of(events)["answer"].startswith("Le vrac compte 6 fichiers")

    # Le protocole JSON est annoncé dans le system prompt, et le résultat
    # d'outil revient en message user (pas de rôle `tool` en repli).
    assert "un seul objet JSON" in provider.calls[0]["messages"][0]["content"]
    assert provider.calls[0]["tools"] is None
    assert "Résultat de l'outil stats" in provider.calls[1]["messages"][-1]["content"]


def test_turn_json_sortie_invalide_relancee_puis_degradee(session):
    """Première sortie non-JSON → relance corrective ; deuxième échec → la
    sortie brute devient la réponse (dégradation douce, jamais de 500)."""
    provider = FakeToolProvider([
        "Je pense que…",
        '{"reponse": "6 fichiers."}',
    ])
    events = events_of(agent_turn(session, "Combien ?", provider, "json"))
    assert final_of(events)["answer"] == "6 fichiers."
    assert "Réponse invalide" in provider.calls[1]["messages"][-1]["content"]

    session.history.clear()
    provider2 = FakeToolProvider(["Blabla un.", "Blabla deux."])
    events2 = events_of(agent_turn(session, "Combien ?", provider2, "json"))
    assert final_of(events2)["answer"] == "Blabla deux."


def test_turn_json_fence_markdown_toleree(session):
    provider = FakeToolProvider([
        '```json\n{"outil": "compter", "arguments": {}}\n```',
        '{"reponse": "6."}',
    ])
    events = events_of(agent_turn(session, "Total ?", provider, "json"))
    assert next(e for e in events if e["type"] == "toolResult")["result"]["total"] == 6


def test_turn_json_max_steps(session):
    provider = FakeToolProvider(
        ['{"outil": "compter", "arguments": {}}'] * MAX_STEPS
        + ['{"reponse": "Conclusion."}']
    )
    events = events_of(agent_turn(session, "Explore.", provider, "json"))
    assert final_of(events)["answer"] == "Conclusion."
    assert final_of(events)["steps"] == MAX_STEPS + 1
