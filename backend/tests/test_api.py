"""Tests d'intégration du backend HTTP FastAPI (`api/`) — B2 (+ garde).

TestClient + provider LLM mocké (FakeProvider, cf. conftest) : on vérifie les
contrats JSON, le format des événements SSE (reasoning/text/progress/done/
error), la taxonomie d'erreurs, les limites et la garde d'annulation
B8 (fermeture du générateur → arrêt de l'itération LiteLLM, remboursement de
la réservation démo).
"""
import json

import pytest
from fastapi.testclient import TestClient

from api import demo_limits, engine
from api.main import app
from api.schemas import AuditRequest, ClassementBatchRequest
from config import settings
from tests.conftest import FakeProvider

client = TestClient(app)


def sse_events(body: str) -> list[dict]:
    """Décode un flux SSE complet en liste d'événements JSON."""
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


@pytest.fixture
def fake_provider(monkeypatch, golden_aud):
    """Provider AUD-001 par défaut ; les tests classement écrasent `response`."""
    provider = FakeProvider(response=golden_aud, reasoning="Je réfléchis…")
    monkeypatch.setattr(engine, "get_provider", lambda **kw: provider)
    return provider


# ── Endpoints simples ────────────────────────────────────────────────────────

def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_models_shape():
    data = client.get("/models").json()
    assert {"default", "models", "localEndpoints", "demoMode"} <= set(data)
    assert isinstance(data["models"], list)


# ── /parse ───────────────────────────────────────────────────────────────────

def test_parse_valid_csv(small_csv_text):
    resp = client.post("/parse", json={"csv": small_csv_text})
    assert resp.status_code == 200
    data = resp.json()
    assert data["validationErrors"] == []
    assert data["stats"] == {"rowCount": 10, "itemCount": 6, "recordGrpCount": 4}
    assert data["prepared"]["columnCount"] == 7
    est = data["tokenEstimate"]
    assert est["totalTokens"] == est["auditTokens"] + est["classementTotalTokens"]


def test_parse_budget_recommendation(small_csv_text):
    """/parse joint une recommandation de budget d'entrée AUD-001 au
    tokenEstimate, indépendante du modèle. Petit vrac (6 Item) → palier « petit »,
    échantillon recommandé « tous » (sampleN=0). Le réglage par défaut (sample
    n=5) ne correspond pas → tokens recommandés chiffrés et delta exploitable."""
    resp = client.post("/parse", json={"csv": small_csv_text})
    budget = resp.json()["tokenEstimate"]["budgetRecommendation"]
    assert budget["itemCount"] == 6
    assert budget["tier"] == "petit"
    assert budget["recommendedSampleN"] == 0
    assert budget["currentSampleN"] == 5  # défaut PrepOptions
    assert budget["matchesRecommendation"] is False
    assert budget["estimatedAuditTokensAtRecommended"] > 0
    assert budget["tableDate"]


def test_parse_budget_matches_when_aligned(small_csv_text):
    """Quand les options courantes coïncident avec la recommandation (petit vrac
    → aucun échantillonnage), matchesRecommendation est vrai et les tokens
    recommandés égalent l'estimation d'audit courante."""
    resp = client.post("/parse", json={
        "csv": small_csv_text,
        "prep": {"sampleItems": False, "cleanDates": True},
    })
    est = resp.json()["tokenEstimate"]
    budget = est["budgetRecommendation"]
    assert budget["currentSampleN"] == 0
    assert budget["matchesRecommendation"] is True
    assert budget["estimatedAuditTokensAtRecommended"] == est["auditTokens"]


def test_parse_no_cost_without_model(small_csv_text):
    """Sans modèle dans la requête, aucun coût n'est joint à l'estimation."""
    resp = client.post("/parse", json={"csv": small_csv_text})
    assert "costEstimate" not in resp.json()["tokenEstimate"]


def test_parse_cost_for_known_cloud_model(small_csv_text):
    """Avec un modèle cloud connu, le coût d'entrée € est joint au tokenEstimate."""
    resp = client.post("/parse", json={"csv": small_csv_text, "model": "claude-opus-4-8"})
    cost = resp.json()["tokenEstimate"]["costEstimate"]
    assert cost["totalEur"] > 0 and cost["label"] == "Claude Opus"
    assert cost["priceDate"]


def test_parse_no_cost_for_local_model(small_csv_text):
    """Rien pour les locaux : un base_url renseigné → coût None."""
    resp = client.post("/parse", json={
        "csv": small_csv_text, "model": "claude-opus-4-8",
        "baseUrl": "http://localhost:1234",
    })
    assert resp.json()["tokenEstimate"]["costEstimate"] is None


def test_parse_unreadable_csv_taxonomy():
    resp = client.post("/parse", json={"csv": '"a;b\n"1'})
    assert resp.status_code == 400
    data = resp.json()
    assert data["code"] == "csv_unreadable"
    assert "Archifiltre" in data["hint"]


def test_parse_row_limit_guard(small_csv_text, monkeypatch):
    monkeypatch.setattr(settings, "MAX_CSV_ROWS", 5)
    resp = client.post("/parse", json={"csv": small_csv_text})
    assert resp.status_code == 413
    data = resp.json()
    assert data["code"] == "csv_too_large"
    assert "10 lignes" in data["error"]
    assert "Découpez" in data["hint"] or "découpé" in data["hint"]


def test_parse_byte_limit_guard(small_csv_text, monkeypatch):
    monkeypatch.setattr(settings, "MAX_CSV_BYTES", 100)
    resp = client.post("/parse", json={"csv": small_csv_text})
    assert resp.status_code == 413
    assert resp.json()["code"] == "csv_too_large"


# ── /audit (SSE) ─────────────────────────────────────────────────────────────

def test_audit_sse_full_flow(small_csv_text, fake_provider):
    resp = client.post("/audit", json={"csv": small_csv_text, "model": "test-model"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = sse_events(resp.text)

    types = [e["type"] for e in events]
    assert types[0] == "reasoning"
    assert "text" in types
    assert types[-1] == "done"

    done = events[-1]
    assert "AFFAIRES_SCOLAIRES" in done["report"]
    assert "Arborescence technique" in done["plan"]
    assert done["planTree"]["1_Inscriptions"] == "AFFAIRES_SCOLAIRES"
    assert done["usage"]["total_tokens"] == 1200
    assert isinstance(done["durationMs"], int)
    # Version du prompt consignée dans le done{}.
    from prompts import AUD_001

    assert done["promptVersion"] == AUD_001.PROMPT_VERSION
    # Modèle ayant exécuté l'étape, renvoyé pour la traçabilité (figé côté front).
    assert done["model"] == "test-model"
    # Le texte streamé reconstitue la réponse complète.
    streamed = "".join(e["delta"] for e in events if e["type"] == "text")
    assert streamed == fake_provider.response


def test_audit_invalid_csv_yields_error_event(fake_provider, small_csv_text):
    bad = small_csv_text.replace('"3";"2"', '"1";"2"')  # ID dupliqué
    events = sse_events(client.post("/audit", json={"csv": bad, "model": "m"}).text)
    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert events[0]["code"] == "csv_invalid"
    assert events[0]["hint"]


def test_audit_llm_failure_taxonomy(monkeypatch, small_csv_text):
    class AuthError(Exception):
        status_code = 401

    provider = FakeProvider()
    provider.failures = [AuthError("bad key")]
    monkeypatch.setattr(engine, "get_provider", lambda **kw: provider)
    events = sse_events(client.post("/audit", json={"csv": small_csv_text, "model": "m"}).text)
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "llm_auth"
    assert "réglages" in events[-1]["hint"]


def test_audit_brief_uses_brief_prompt(small_csv_text, fake_provider):
    client.post("/audit", json={"csv": small_csv_text, "model": "m", "brief": True})
    system_prompt = fake_provider.calls[-1][0]
    from prompts import AUD_001

    assert system_prompt == AUD_001.SYSTEM_PROMPT_BRIEF


# ── /classement (prepare / batch / finalize) ─────────────────────────────────

def test_classement_prepare_counts_items(small_csv_text):
    data = client.post("/classement/prepare", json={"csv": small_csv_text}).json()
    assert data["total"] == 6
    assert data["columns"] == ["Ref", "Path", "CurrentTitle", "Date"]


def test_classement_batch_sse_flow(monkeypatch, small_csv_text, golden_cla_path, plan_valide):
    provider = FakeProvider(response=golden_cla_path, chunk_size=40)
    monkeypatch.setattr(engine, "get_provider", lambda **kw: provider)
    resp = client.post("/classement/batch", json={
        "csv": small_csv_text, "planValide": plan_valide, "model": "m",
    })
    events = sse_events(resp.text)
    done = events[-1]
    assert done["type"] == "done"
    assert len(done["llmRows"]) == 6
    assert done["llmRows"][0]["TargetFolder"] == "1_Inscriptions"
    assert done["rawText"] == golden_cla_path
    # Version du prompt consignée dans le done{}.
    from prompts import CLA_001

    assert done["promptVersion"] == CLA_001.PROMPT_VERSION
    # Modèle ayant exécuté l'étape, renvoyé pour la traçabilité.
    assert done["model"] == "m"
    # Progression live : des événements progress avec compteur croissant.
    progress = [e["itemsDone"] for e in events if e["type"] == "progress"]
    assert progress and progress[-1] >= 6  # marqueur [FIN…] compté en live, recalé au done


def test_classement_batch_corrections_inject_fewshot(monkeypatch, small_csv_text,
                                                    golden_cla_path, plan_valide):
    """Des corrections passées à /classement/batch ouvrent le canal
    d'exemples (système) et insèrent le bloc dans le user message."""
    provider = FakeProvider(response=golden_cla_path)
    monkeypatch.setattr(engine, "get_provider", lambda **kw: provider)
    client.post("/classement/batch", json={
        "csv": small_csv_text, "planValide": plan_valide, "model": "m",
        "corrections": [
            {"path": "inscriptions/liste_eleves_2022.xlsx",
             "targetFolder": "1-1_Inscriptions", "newTitle": "2022_liste.xlsx"},
        ],
    })
    system_prompt, user_msg = provider.calls[-1]
    assert "# Exemples de classements validés" in system_prompt
    assert "appliquez la même logique" in user_msg
    assert "`inscriptions/liste_eleves_2022.xlsx`" in user_msg


def test_classement_batch_no_corrections_prompt_unchanged(monkeypatch, small_csv_text,
                                                        golden_cla_path, plan_valide):
    provider = FakeProvider(response=golden_cla_path)
    monkeypatch.setattr(engine, "get_provider", lambda **kw: provider)
    client.post("/classement/batch", json={
        "csv": small_csv_text, "planValide": plan_valide, "model": "m",
    })
    system_prompt, user_msg = provider.calls[-1]
    assert "# Exemples de classements validés" not in system_prompt
    assert "appliquez la même logique" not in user_msg
    assert "# Notes de connaissance du fonds" not in system_prompt


def test_classement_batch_slices_server_side(monkeypatch, small_csv_text, golden_cla_ref, plan_valide):
    provider = FakeProvider(response=golden_cla_ref)
    monkeypatch.setattr(engine, "get_provider", lambda **kw: provider)
    client.post("/classement/batch", json={
        "csv": small_csv_text, "planValide": plan_valide, "model": "m",
        "batchIndex": 1, "batchSize": 2,
        "prep": {"classementRef": True},
    })
    user_msg = provider.calls[-1][1]
    # La tranche 1 (items 3 et 4) est re-dérivée côté serveur.
    assert "menus_janvier" in user_msg and "facture_traiteur" in user_msg
    assert "liste_eleves_2022" not in user_msg
    assert "photo_kermesse" not in user_msg


def test_classement_batch_extract_failure_taxonomy(monkeypatch, small_csv_text, plan_valide):
    provider = FakeProvider(response="Aucune donnée tabulaire ici.")
    monkeypatch.setattr(engine, "get_provider", lambda **kw: provider)
    events = sse_events(client.post("/classement/batch", json={
        "csv": small_csv_text, "planValide": plan_valide, "model": "m",
    }).text)
    # extract_csv_from_response retombe sur la réponse brute → df sans les
    # colonnes attendues : l'erreur se manifeste à la finalisation, ou ici si
    # l'extraction lève. Selon le chemin, on tolère done (lignes inexploitables)
    # — le contrat testé : jamais d'exception non formatée.
    assert events[-1]["type"] in ("done", "error")
    if events[-1]["type"] == "error":
        assert events[-1]["code"] == "extract_failed"


def test_classement_finalize_full(small_csv_text, plan_valide, golden_cla_path):
    from core.csv_handler import extract_csv_from_response

    rows = extract_csv_from_response(golden_cla_path).to_dict(orient="records")
    data = client.post("/classement/finalize", json={
        "csv": small_csv_text, "planValide": plan_valide, "llmRows": rows,
    }).json()
    resip = data["resip"]
    assert resip["stats"]["planMatches"] is True
    assert resip["columns"][:3] == ["ID", "ParentID", "File"]
    items = [r for r in resip["rows"] if r["Content.DescriptionLevel"] == "Item"]
    assert len(items) == 6
    # Contrôle d'intégrité passé : aucun warning préfixé.
    assert not [w for w in resip["warnings"] if w.startswith("Contrôle d'intégrité")]
    # Anomalies typées jointes — catégorisées côté moteur, une par warning
    # (la ligne-fleuve des extensions exceptée). Toute catégorie est connue.
    assert "anomalies" in resip
    known = {
        "nonClasse", "cibleInconnue", "pathIntrouvable", "cibleMalformee",
        "horsPlan", "nonRealise", "sousDossierCree", "extension", "autre",
    }
    assert all(a["category"] in known for a in resip["anomalies"])


def test_classement_batch_directives_inject_channel(monkeypatch, small_csv_text,
                                                   golden_cla_path, plan_valide):
    """Des consignes passées à /classement/batch ouvrent le canal
    (système) et insèrent le bloc dans le user message (préfixe caché)."""
    provider = FakeProvider(response=golden_cla_path)
    monkeypatch.setattr(engine, "get_provider", lambda **kw: provider)
    client.post("/classement/batch", json={
        "csv": small_csv_text, "planValide": plan_valide, "model": "m",
        "directives": [
            {"folder": "2_Cantine", "text": "un sous-dossier par prestataire",
             "allowCreation": True},
        ],
    })
    system_prompt, user_msg = provider.calls[-1]
    assert "# Consignes de classement de l'archiviste" in system_prompt
    assert "un sous-dossier par prestataire" in user_msg
    assert "`2_Cantine`" in user_msg


def test_classement_batch_no_directives_prompt_unchanged(monkeypatch, small_csv_text,
                                                       golden_cla_path, plan_valide):
    provider = FakeProvider(response=golden_cla_path)
    monkeypatch.setattr(engine, "get_provider", lambda **kw: provider)
    client.post("/classement/batch", json={
        "csv": small_csv_text, "planValide": plan_valide, "model": "m",
    })
    system_prompt, user_msg = provider.calls[-1]
    assert "# Consignes de classement de l'archiviste" not in system_prompt


def test_classement_finalize_creates_authorized_subfolder(small_csv_text, plan_valide):
    """ bout-en-bout via l'API : une consigne autorisant la création +
    des TargetFolder en chemin `2_Cantine/…` produisent des sous-dossiers
    rattachés au bon parent, comptés à part, planMatches non cassé par eux."""
    import io

    from core.csv_handler import prepare_for_classement, read_csv

    df = read_csv(io.StringIO(small_csv_text))
    items = prepare_for_classement(df)
    # Ranger tous les items sous des sous-dossiers créés de 2_Cantine.
    rows = [
        {"Path": p, "TargetFolder": "2_Cantine/Prestataire A", "NewTitle": "x.pdf"}
        for p in items["Path"]
    ]
    data = client.post("/classement/finalize", json={
        "csv": small_csv_text, "planValide": plan_valide, "llmRows": rows,
        "directives": [
            {"folder": "2_Cantine", "text": "un sous-dossier par prestataire",
             "allowCreation": True},
        ],
    }).json()
    stats = data["resip"]["stats"]
    # 2-1_Menus / 2-2_Factures existent déjà → la création reçoit 2-3.
    assert stats["foldersCreatedAuthorized"] == ["2-3_Prestataire_A"]
    # Le sous-dossier créé n'est pas compté comme hors-plan.
    assert stats["foldersOffPlan"] == []
    # Rattaché sous 2_Cantine, jamais à la racine.
    rg = {r["File"]: r for r in data["resip"]["rows"]
          if r["Content.DescriptionLevel"] == "RecordGrp"}
    assert rg["2-3_Prestataire_A"]["ParentID"] == rg["2_Cantine"]["ID"]


def test_classement_finalize_no_rows_taxonomy(small_csv_text, plan_valide):
    data = client.post("/classement/finalize", json={
        "csv": small_csv_text, "planValide": plan_valide, "llmRows": [],
    }).json()
    assert data["code"] == "no_llm_rows"


def test_classement_finalize_conversion_error_taxonomy(small_csv_text, plan_valide):
    data = client.post("/classement/finalize", json={
        "csv": small_csv_text, "planValide": plan_valide,
        "llmRows": [{"Quoi": "x"}],
    }).json()
    assert data["code"] == "conversion_failed"
    assert "plan validé" in data["hint"]


# ── /extract-plans ───────────────────────────────────────────────────────────

def test_extract_plans_endpoint(golden_aud):
    data = client.post("/extract-plans", json={"report": golden_aud}).json()
    assert "AFFAIRES_SCOLAIRES/" in data["plan"]
    assert data["planTree"]["2-1_Menus"] == "2_Cantine"
    assert "RGPD" in data["notes"]


# ── /journal ──────────────────────────────────────────────────────────────────

def test_journal_endpoint_renders_markdown_and_record():
    """/journal rend le document de traçabilité (markdown + objet) à partir
    des métadonnées renvoyées par le front (jamais de contenu documentaire)."""
    data = client.post("/journal", json={
        "command": "run",
        "inputName": "vrac.csv",
        "model": "claude-opus-4-8",
        "promptVersions": {"AUD-001": "3", "CLA-001": "5"},
        "durationS": 42.0,
        "rows": 112,
        "warnings": ["2 cible(s) malformée(s)"],
        "conformity": {"planParsed": True, "planMatches": True,
                       "itemsTotal": 80, "itemsClassified": 80},
    }).json()
    assert data["journal"]["tool"] == "ODACEA"
    assert data["journal"]["source"] == {"file": "vrac.csv", "rows": 112}
    assert data["journal"]["anomalies"] == ["2 cible(s) malformée(s)"]
    assert data["markdown"].startswith("# Journal de traitement ODACEA")
    assert "Confidentialité des données" in data["markdown"]


def test_journal_endpoint_models_per_agent():
    """La carte `models` (modèle par agent) est consignée et rendue par étape,
    pour distinguer audit et classement exécutés sur des modèles différents."""
    data = client.post("/journal", json={
        "command": "run",
        "inputName": "vrac.csv",
        "models": {"AUD-001": "claude-opus-4-8", "CLA-001": "ollama/llama3"},
        "promptVersions": {"AUD-001": "3", "CLA-001": "5"},
    }).json()
    assert data["journal"]["models"] == {
        "AUD-001": "claude-opus-4-8", "CLA-001": "ollama/llama3",
    }
    assert "AUD-001 : claude-opus-4-8" in data["markdown"]
    assert "CLA-001 : ollama/llama3" in data["markdown"]


def test_journal_endpoint_confidentiality_adapts_to_description():
    data = client.post("/journal", json={
        "command": "audit", "inputName": "x.csv",
        "promptVersions": {"AUD-001": "3"}, "descriptionSent": True,
    }).json()
    assert any("descriptions documentaires" in c
               for c in data["journal"]["confidentiality"])


# ── /manifest ─────────────────────────────────────────────────────────────────

def test_manifest_endpoint_derives_tree_from_resip_rows(small_csv_text, plan_valide,
                                                        golden_cla_path):
    """/manifest dérive l'arborescence de répertoires modèle des lignes RESIP
    produites (mêmes `rows` que `resip.rows` de finalize) — métadonnées seules."""
    from core.csv_handler import extract_csv_from_response

    rows = extract_csv_from_response(golden_cla_path).to_dict(orient="records")
    resip = client.post("/classement/finalize", json={
        "csv": small_csv_text, "planValide": plan_valide, "llmRows": rows,
    }).json()["resip"]

    data = client.post("/manifest", json={"rows": resip["rows"]}).json()
    assert data["manifest"]["tool"] == "ODACEA"
    assert data["manifest"]["summary"]["items"] == 6
    assert data["manifest"]["directories"]
    assert data["markdown"].startswith("# Arborescence de répertoires modèle ODACEA")
    assert "métadonnées seules" in data["markdown"].lower()


# ── /plan-compare ─────────────────────────────────────────────────────────────

def _plan_block(*folders: str) -> str:
    body = "\n".join(f"{f}/" for f in folders)
    return f"Arborescence technique\n{body}\n"


def test_plan_compare_endpoint_reports_common_and_unique():
    """/plan-compare compare les variantes de plan renvoyées par le front
    (textes du bloc « Arborescence technique ») de façon déterministe, sans LLM."""
    a = _plan_block("1_Inscriptions", "2_Cantine")
    # Variante b : même dossier commun numéroté autrement + un dossier propre.
    b = _plan_block("1_Cantine", "2_Vie_scolaire")
    data = client.post("/plan-compare", json={"plans": [a, b]}).json()

    assert data["comparison"]["variantCount"] == 2
    assert data["comparison"]["identical"] is False
    assert "cantine" in data["comparison"]["commonFolders"]
    assert data["variants"][0]["uniqueFolders"] == ["inscriptions"]
    assert data["variants"][1]["uniqueFolders"] == ["vie scolaire"]
    # Le rendu lisible (source unique côté moteur) est joint pour l'affichage.
    assert "Variante" in data["markdown"] and "#1" in data["markdown"]


# ── /validate-connection ─────────────────────────────────────────────────────

def test_validate_connection_ok(monkeypatch):
    import api.main as main_mod

    monkeypatch.setattr(main_mod, "get_provider", lambda **kw: FakeProvider(response="OK"))
    data = client.post("/validate-connection", json={"model": "m"}).json()
    assert data == {"ok": True}


# ── annulation — fermeture du générateur SSE ─────────────────────────────────

class _EndlessProvider(FakeProvider):
    """Stream infini : simule un LLM en cours de génération. `closed` passe à
    True quand l'itération est interrompue (GeneratorExit propagé)."""

    def __init__(self):
        super().__init__()
        self.closed = False

    def stream_with_reasoning(self, system_prompt, user_message, *, cache_user_boundary=None):
        try:
            while True:
                yield False, "chunk "
        finally:
            self.closed = True


def test_audit_generator_close_stops_llm_iteration(monkeypatch, small_csv_text):
    """Déconnexion client (bouton « Arrêter ») : Starlette ferme le générateur ;
    la boucle sur le stream LiteLLM doit cesser immédiatement (garde)."""
    provider = _EndlessProvider()
    monkeypatch.setattr(engine, "get_provider", lambda **kw: provider)
    gen = engine.audit_stream(AuditRequest(csv=small_csv_text, model="m"))
    assert next(gen).startswith("data: ")
    next(gen)
    gen.close()  # ce que fait Starlette à la déconnexion
    assert provider.closed is True


def test_classement_generator_close_rolls_back_demo_reservation(
    monkeypatch, small_csv_text, plan_valide
):
    """Interruption en mode démo : l'essai provisionné est remboursé (finally)."""
    provider = _EndlessProvider()
    monkeypatch.setattr(engine, "get_provider", lambda **kw: provider)
    rolled = []
    monkeypatch.setattr(demo_limits, "rollback", rolled.append)
    reservation = object()
    gen = engine.classement_batch_stream(
        ClassementBatchRequest(csv=small_csv_text, plan_valide=plan_valide, model="m"),
        reservation=reservation,
    )
    next(gen)
    gen.close()
    assert provider.closed is True
    assert rolled == [reservation]


# ── heartbeat SSE (`: ping`) ─────────────────────────────────────────────────

import threading  # noqa: E402
import time  # noqa: E402

from api import sse  # noqa: E402


def test_with_heartbeat_disabled_is_passthrough():
    """interval <= 0 : passe-plat strict, aucun heartbeat, ordre conservé."""
    def source():
        yield "a"
        yield "b"

    assert list(sse.with_heartbeat(source(), interval=0)) == ["a", "b"]


def test_with_heartbeat_relays_items_in_order_without_ping():
    """Quand les événements arrivent vite (< interval), aucun ping n'est inséré."""
    def source():
        for i in range(5):
            yield f"item{i}"

    out = list(sse.with_heartbeat(source(), interval=5))
    assert out == [f"item{i}" for i in range(5)]


def test_with_heartbeat_emits_ping_during_silence():
    """Source silencieuse plus longue que l'intervalle → un `: ping` est émis
    avant l'arrivée du vrai événement (cas « longue réflexion »)."""
    released = threading.Event()

    def source():
        released.wait(2.0)  # bloque le flux, comme un modèle qui réfléchit
        yield sse.text("hello")

    gen = sse.with_heartbeat(source(), interval=0.05)
    assert next(gen) == sse.HEARTBEAT
    released.set()
    rest = list(gen)
    assert any('"hello"' in chunk for chunk in rest)


def test_with_heartbeat_propagates_source_exception():
    """Une exception levée par la source est remontée au consommateur."""
    def source():
        yield "a"
        raise ValueError("boom")

    gen = sse.with_heartbeat(source(), interval=5)
    assert next(gen) == "a"
    with pytest.raises(ValueError, match="boom"):
        next(gen)


def test_with_heartbeat_close_closes_source():
    """Fermer le générateur enrobant ferme la source (son `finally` s'exécute) —
    c'est ce qui rembourse la réservation démo et stoppe LiteLLM."""
    closed = threading.Event()

    def source():
        try:
            while True:
                yield "chunk"
                time.sleep(0.01)
        finally:
            closed.set()

    gen = sse.with_heartbeat(source(), interval=5)
    assert next(gen) == "chunk"
    gen.close()
    assert closed.wait(2.0)
