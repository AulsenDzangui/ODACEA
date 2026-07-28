"""Endpoints /agt/* — TestClient, provider mocké.

Cycle complet : création de session, dialogue SSE avec appels d'outils
transparents (agent **lecture seule**), statut, expiration → code
stable `agt_session_expired`, suppression, refus en démo.
"""
import json

import pytest
from fastapi.testclient import TestClient

from api import engine
from api.main import app
from core.agt_session import STORE
from prompts import AGT_001
from tests.conftest import FakeToolProvider

client = TestClient(app)


def sse_events(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


@pytest.fixture(autouse=True)
def _sessions_propres():
    """Le magasin est global au process : chaque test part d'un état vide."""
    STORE._sessions.clear()
    yield
    STORE._sessions.clear()


def _tool_provider(monkeypatch, script) -> FakeToolProvider:
    provider = FakeToolProvider(script)
    monkeypatch.setattr(engine, "get_provider", lambda **kw: provider)
    return provider


def _create_session(small_csv_text) -> str:
    resp = client.post("/agt/session", json={"csv": small_csv_text})
    assert resp.status_code == 200
    return resp.json()["sessionId"]


# ── /agt/session ────────────────────────────────────────────────────────────

def test_session_create(small_csv_text):
    resp = client.post("/agt/session", json={"csv": small_csv_text})
    assert resp.status_code == 200
    data = resp.json()
    assert data["sessionId"]
    assert data["stats"] == {"rowCount": 10, "itemCount": 6, "recordGrpCount": 4}
    assert data["digest"]  # résumé compact (audit_scan) — seul contexte du modèle
    assert data["ttlS"] > 0


def test_session_create_csv_invalide():
    resp = client.post("/agt/session", json={"csv": "a;b\n1;2\n"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "csv_invalid"


def test_session_create_sans_rapport_audit(small_csv_text):
    """Par défaut (aucun rapport), la session n'en retient pas (0.6.0)."""
    resp = client.post("/agt/session", json={"csv": small_csv_text})
    data = resp.json()
    assert data["auditReportUsed"] is False
    assert STORE.get(data["sessionId"]).audit_report is None


def test_session_create_avec_rapport_audit(small_csv_text):
    """Le rapport d'audit fourni est retenu et signalé (auditReportUsed)."""
    resp = client.post(
        "/agt/session",
        json={"csv": small_csv_text, "auditReport": "# Audit\nConstat notable."},
    )
    data = resp.json()
    assert data["auditReportUsed"] is True
    assert "Constat notable." in STORE.get(data["sessionId"]).audit_report


def test_session_create_rapport_vide_ignore(small_csv_text):
    """Un rapport composé d'espaces est traité comme absent (prompt inchangé)."""
    resp = client.post(
        "/agt/session", json={"csv": small_csv_text, "auditReport": "   \n  "}
    )
    data = resp.json()
    assert data["auditReportUsed"] is False
    assert STORE.get(data["sessionId"]).audit_report is None


def test_chat_utilise_le_rapport_audit_en_contexte(monkeypatch, small_csv_text):
    """Le rapport injecté à la création se retrouve dans le system prompt du tour."""
    provider = _tool_provider(monkeypatch, ["Réponse."])
    resp = client.post(
        "/agt/session",
        json={"csv": small_csv_text, "auditReport": "SENTINELLE-RAPPORT-42"},
    )
    sid = resp.json()["sessionId"]
    client.post("/agt/chat", json={
        "sessionId": sid, "message": "Bonjour", "model": "gpt-test",
    })
    system = provider.calls[0]["messages"][0]["content"]
    assert "SENTINELLE-RAPPORT-42" in system
    assert "Rapport d'audit du projet" in system


def test_session_status_et_delete(small_csv_text):
    sid = _create_session(small_csv_text)
    status = client.get(f"/agt/session/{sid}")
    assert status.status_code == 200
    assert status.json()["rows"] == 10

    assert client.delete(f"/agt/session/{sid}").json() == {"deleted": True}
    assert client.delete(f"/agt/session/{sid}").json() == {"deleted": False}
    assert client.get(f"/agt/session/{sid}").status_code == 404
    assert client.get(f"/agt/session/{sid}").json()["code"] == "agt_session_expired"


# ── /agt/chat ───────────────────────────────────────────────────────────────

def test_chat_tour_complet(monkeypatch, small_csv_text):
    provider = _tool_provider(monkeypatch, [
        [("compter", '{"filtre": {"extension": "xlsx"}}')],
        "Il y a 2 fichiers xlsx.",
    ])
    sid = _create_session(small_csv_text)
    resp = client.post("/agt/chat", json={
        "sessionId": sid, "message": "Combien de xlsx ?", "model": "gpt-test",
    })
    assert resp.status_code == 200
    events = sse_events(resp.text)
    types = [e["type"] for e in events]
    assert types == ["tool", "toolResult", "text", "done"]

    tool = events[0]
    assert tool["name"] == "compter"
    assert tool["arguments"] == {"filtre": {"extension": "xlsx"}}
    assert events[1]["result"]["total"] == 2 # chiffre exact (critère)

    done = events[-1]
    assert done["answer"] == "Il y a 2 fichiers xlsx."
    assert done["steps"] == 2
    assert done["toolMode"] == "native"
    assert done["promptVersion"] == AGT_001.PROMPT_VERSION
    assert done["model"] == "gpt-test"
    assert done["usage"]["total_tokens"] == 240
    assert done["usageSession"]["total_tokens"] == 240  # cumul par session

    # Le system prompt du tour = AGT-001 + digest, jamais le CSV.
    system = provider.calls[0]["messages"][0]["content"]
    assert "assistant archiviste" in system
    assert small_csv_text not in system


def test_chat_mode_json_pour_serveur_local(monkeypatch, small_csv_text):
    """`toolMode=auto` + base_url ⇒ repli JSON : pas de déclaration
    d'outils, protocole JSON dans le system prompt."""
    provider = _tool_provider(monkeypatch, ['{"reponse": "Bonjour."}'])
    sid = _create_session(small_csv_text)
    resp = client.post("/agt/chat", json={
        "sessionId": sid, "message": "Salut", "model": "qwen3:14b",
        "baseUrl": "http://localhost:1234/v1",
    })
    done = sse_events(resp.text)[-1]
    assert done["toolMode"] == "json"
    assert provider.calls[0]["tools"] is None


def test_chat_session_expiree(monkeypatch, small_csv_text):
    """Le code stable `agt_session_expired` déclenche la recréation côté
    front depuis le projet client (l'état serveur n'est qu'un cache)."""
    _tool_provider(monkeypatch, [])
    resp = client.post("/agt/chat", json={
        "sessionId": "disparue", "message": "Combien ?", "model": "gpt-test",
    })
    events = sse_events(resp.text)
    assert events == [{"type": "error", "message": "Session inconnue ou expirée.",
                       "code": "agt_session_expired", "hint": events[0]["hint"]}]
    assert "recréez-la" in events[0]["hint"]


def test_chat_message_vide(monkeypatch, small_csv_text):
    _tool_provider(monkeypatch, [])
    sid = _create_session(small_csv_text)
    resp = client.post("/agt/chat", json={
        "sessionId": sid, "message": "   ", "model": "gpt-test",
    })
    assert sse_events(resp.text)[0]["code"] == "agt_message_empty"


def test_chat_erreur_llm(monkeypatch, small_csv_text):
    """Une exception LLM devient un événement `error` de la taxonomie."""
    class ExplodingProvider(FakeToolProvider):
        def complete_with_tools(self, messages, tools=None):
            raise RuntimeError("boom")

    monkeypatch.setattr(engine, "get_provider", lambda **kw: ExplodingProvider([]))
    sid = _create_session(small_csv_text)
    resp = client.post("/agt/chat", json={
        "sessionId": sid, "message": "Combien ?", "model": "gpt-test",
    })
    events = sse_events(resp.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "llm_unknown"


def test_chat_historique_entre_tours(monkeypatch, small_csv_text):
    """L'état de session porte le dialogue : le second tour voit le premier."""
    sid = _create_session(small_csv_text)
    _tool_provider(monkeypatch, ["Première réponse."])
    client.post("/agt/chat", json={
        "sessionId": sid, "message": "Premier tour", "model": "gpt-test",
    })
    provider2 = _tool_provider(monkeypatch, ["Seconde réponse."])
    client.post("/agt/chat", json={
        "sessionId": sid, "message": "Second tour", "model": "gpt-test",
    })
    msgs = provider2.calls[0]["messages"]
    assert {"role": "user", "content": "Premier tour"} in msgs
    assert {"role": "assistant", "content": "Première réponse."} in msgs


def test_conversation_reset(monkeypatch, small_csv_text):
    """DELETE …/history vide le dialogue **sans détruire la session** —
    l'agent repart sans mémoire."""
    sid = _create_session(small_csv_text)
    _tool_provider(monkeypatch, ["Première réponse."])
    client.post("/agt/chat", json={
        "sessionId": sid, "message": "Premier tour", "model": "gpt-test",
    })
    assert client.get(f"/agt/session/{sid}").json()["turns"] == 1

    reset = client.delete(f"/agt/session/{sid}/history")
    assert reset.status_code == 200
    assert reset.json() == {"sessionId": sid, "reset": True, "turns": 0}

    # La session vit encore : historique vidé.
    status = client.get(f"/agt/session/{sid}").json()
    assert status["turns"] == 0

    # Le tour suivant ne voit plus les échanges précédents dans son prompt.
    provider = _tool_provider(monkeypatch, ["Nouveau départ."])
    client.post("/agt/chat", json={
        "sessionId": sid, "message": "On reprend", "model": "gpt-test",
    })
    msgs = provider.calls[0]["messages"]
    assert not any(m.get("content") == "Premier tour" for m in msgs)


def test_conversation_reset_session_expiree():
    resp = client.delete("/agt/session/disparue/history")
    assert resp.status_code == 404
    assert resp.json()["code"] == "agt_session_expired"


# ── Coût € cumulé par session ────────────────────────────────────────────────

def test_chat_cout_eur_cumule_modele_cloud(monkeypatch, small_csv_text):
    """Chaque tour est valorisé à la grille locale (core.pricing) et le
    cumul de session est renvoyé dans le done{} et le statut."""
    sid = _create_session(small_csv_text)
    _tool_provider(monkeypatch, ["Premier tour."])
    done = sse_events(client.post("/agt/chat", json={
        "sessionId": sid, "message": "Bonjour", "model": "claude-opus-4-8",
    }).text)[-1]
    # 100 tokens in × 13,8 €/M + 20 tokens out × 69 €/M = 0,00276 €.
    assert done["costSessionEur"] == pytest.approx(0.0028, abs=0.0001)

    _tool_provider(monkeypatch, ["Second tour."])
    done2 = sse_events(client.post("/agt/chat", json={
        "sessionId": sid, "message": "Encore", "model": "claude-opus-4-8",
    }).text)[-1]
    assert done2["costSessionEur"] == pytest.approx(0.0055, abs=0.0001)
    assert client.get(f"/agt/session/{sid}").json()["costEur"] == pytest.approx(
        0.0055, abs=0.0001
    )


def test_chat_cout_eur_absent_modele_local(monkeypatch, small_csv_text):
    """Modèle local (base_url) ⇒ pas de tarif : rien à afficher."""
    sid = _create_session(small_csv_text)
    _tool_provider(monkeypatch, ['{"reponse": "Bonjour."}'])
    done = sse_events(client.post("/agt/chat", json={
        "sessionId": sid, "message": "Salut", "model": "qwen3:14b",
        "baseUrl": "http://localhost:1234/v1",
    }).text)[-1]
    assert done["costSessionEur"] is None
    assert client.get(f"/agt/session/{sid}").json()["costEur"] is None


# ── Mode démonstration ───────────────────────────────────────────────────────

def test_agt_refuse_en_demo(monkeypatch, small_csv_text):
    """L'agent introduit de l'état serveur et des appels LLM multi-tours :
    refusé sur le déploiement public (comme /enrich)."""
    import api.main as main_mod

    monkeypatch.setattr(main_mod, "DEMO_MODE", True)
    for resp in (
        client.post("/agt/session", json={"csv": small_csv_text}),
        client.get("/agt/session/x"),
        client.delete("/agt/session/x"),
        client.post("/agt/chat", json={"sessionId": "x", "message": "y", "model": "m"}),
        client.delete("/agt/session/x/history"),
    ):
        assert resp.status_code == 403
        assert resp.json()["code"] == "agt_disabled"
