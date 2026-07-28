"""Durcissement démo au niveau HTTP.

Deux protections du déploiement public :
  * un **plafond de taille du corps** de requête, appliqué en amont d'après
    `Content-Length` (borne mémoire/CPU par appel) ;
  * `/parse` n'analyse que le **CSV embarqué** en démo — jamais un CSV fourni par
    le client (comme /audit et /classement).

Les quotas par IP / tokens sont vérifiés sous charge dans `test_demo_limits.py`.
"""
import pandas as pd
from fastapi.testclient import TestClient

import api.main as main
from api.main import app
from config import settings

client = TestClient(app)

_COLS = [
    "ID", "ParentID", "File", "Content.DescriptionLevel",
    "Content.Title", "Content.StartDate", "Content.EndDate",
]


def _csv(rows: list[dict]) -> str:
    return pd.DataFrame(rows, columns=_COLS).to_csv(index=False, sep=";")


def test_demo_body_guard_rejects_oversized_payload(monkeypatch):
    monkeypatch.setattr(main, "DEMO_MODE", True)
    monkeypatch.setattr(main, "DEMO_MAX_BODY_BYTES", 1024)  # 1 Kio pour le test
    monkeypatch.setattr(main, "DEMO_MAX_BODY_MB", 1024 / (1024 * 1024))
    resp = client.post("/parse", json={"csv": "x" * 5000})
    assert resp.status_code == 413
    assert resp.json()["code"] == "demo_payload_too_large"


def test_demo_body_guard_allows_small_payload(monkeypatch):
    monkeypatch.setattr(main, "DEMO_MODE", True)
    # Plafond généreux : la requête légitime passe la garde (le forçage du CSV de
    # démo prend ensuite le relais — cf. test suivant).
    resp = client.post("/parse", json={"csv": "ID;ParentID;File\n"})
    assert resp.status_code == 200


def test_body_guard_inactive_outside_demo(monkeypatch):
    """Hors démo, aucune garde de corps : seule la limite (20 Mo) s'applique."""
    monkeypatch.setattr(main, "DEMO_MODE", False)
    monkeypatch.setattr(main, "DEMO_MAX_BODY_BYTES", 1)  # ignoré hors démo
    resp = client.post("/parse", json={"csv": "x" * 5000})
    assert resp.status_code != 413


def test_parse_forces_demo_csv(monkeypatch):
    """En démo, /parse ignore le CSV client et n'analyse que le CSV embarqué."""
    monkeypatch.setattr(settings, "DEMO_MODE", True)  # lu par engine._force_demo
    monkeypatch.setattr(main, "DEMO_MODE", True)
    sentinel = _csv([
        {"ID": "1", "ParentID": "", "File": ".",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "racine"},
        {"ID": "2", "ParentID": "1", "File": "secret.pdf",
         "Content.DescriptionLevel": "Item", "Content.Title": "SENTINEL_CLIENT_DATA"},
    ])
    resp = client.post("/parse", json={"csv": sentinel})
    assert resp.status_code == 200
    body = resp.json()
    # Le CSV client est remplacé : le sentinel n'apparaît nulle part dans la réponse.
    assert "SENTINEL_CLIENT_DATA" not in resp.text
    # Le CSV de démo embarqué a bien été analysé.
    assert body["stats"]["itemCount"] > 0


def test_parse_keeps_client_csv_outside_demo(monkeypatch):
    """Hors démo, /parse analyse bien le CSV fourni par le client."""
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    monkeypatch.setattr(main, "DEMO_MODE", False)
    client_csv = _csv([
        {"ID": "1", "ParentID": "", "File": ".",
         "Content.DescriptionLevel": "RecordGrp", "Content.Title": "racine"},
        {"ID": "2", "ParentID": "1", "File": "doc.pdf",
         "Content.DescriptionLevel": "Item", "Content.Title": "SENTINEL_CLIENT_DATA"},
    ])
    resp = client.post("/parse", json={"csv": client_csv})
    assert resp.status_code == 200
    assert "SENTINEL_CLIENT_DATA" in resp.text
