"""Application physique du classement (core/apply_classement.py) : aperçu avant
écriture, copie SSE (source jamais mutée), garde-fous cible et reprise idempotente."""
import json

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def sse_events(body: str) -> list[dict]:
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


def _make_source(root):
    (root / "vieux").mkdir(parents=True)
    (root / "vieux" / "contrat.pdf").write_text("CONTRAT", encoding="utf-8")
    (root / "note.docx").write_text("NOTE", encoding="utf-8")


def _resip_rows():
    def row(i, p, f, lvl, title=""):
        return {"ID": i, "ParentID": p, "File": f, "Content.DescriptionLevel": lvl,
                "Content.Title": title, "Content.StartDate": "", "Content.EndDate": ""}
    return [
        row("1", "", ".", "RecordGrp", "Fonds"),
        row("2", "1", "1_Administration", "RecordGrp", "Administration"),
        row("3", "2", "vieux/contrat.pdf", "Item", "2020-01-01_contrat.pdf"),
        row("4", "2", "note.docx", "Item", "2021-03-02_note.docx"),
    ]


def test_apply_preview_reports_plan(tmp_path):
    src = tmp_path / "src"
    _make_source(src)
    resp = client.post("/apply/preview", json={
        "rows": _resip_rows(), "sourceRoot": str(src),
        "targetRoot": str(tmp_path / "out"),
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["missingCount"] == 0
    assert data["targetGuard"] is None


def test_apply_preview_target_guard(tmp_path):
    src = tmp_path / "src"
    _make_source(src)
    # Cible sous la source → garde-fou signalé dès l'aperçu.
    resp = client.post("/apply/preview", json={
        "rows": _resip_rows(), "sourceRoot": str(src),
        "targetRoot": str(src / "sortie"),
    })
    guard = resp.json()["targetGuard"]
    assert guard is not None and guard["code"] == "apply_target_in_source"


def test_apply_copies_and_source_intact(tmp_path):
    src = tmp_path / "src"
    tgt = tmp_path / "out"
    _make_source(src)
    before = {str(p.relative_to(src)): p.stat().st_size for p in src.rglob("*") if p.is_file()}

    resp = client.post("/apply", json={
        "rows": _resip_rows(), "sourceRoot": str(src),
        "targetRoot": str(tgt), "confirm": True,
    })
    assert resp.status_code == 200
    events = sse_events(resp.text)
    done = events[-1]
    assert done["type"] == "done"
    assert done["stats"]["copied"] == 2
    assert (tgt / "1_Administration" / "2021-03-02_note.docx").is_file()
    # Source strictement identique avant/après (copie seule).
    after = {str(p.relative_to(src)): p.stat().st_size for p in src.rglob("*") if p.is_file()}
    assert before == after


def test_apply_requires_confirm(tmp_path):
    src = tmp_path / "src"
    _make_source(src)
    resp = client.post("/apply", json={
        "rows": _resip_rows(), "sourceRoot": str(src),
        "targetRoot": str(tmp_path / "out"), "confirm": False,
    })
    events = sse_events(resp.text)
    assert events[-1]["type"] == "error"
    assert "confirm" in events[-1]["message"].lower()


def test_apply_resume_is_idempotent(tmp_path):
    src = tmp_path / "src"
    tgt = tmp_path / "out"
    _make_source(src)
    payload = {"rows": _resip_rows(), "sourceRoot": str(src), "targetRoot": str(tgt)}
    client.post("/apply", json={**payload, "confirm": True})
    # Deuxième passe : tout est déjà copié à l'identique → sauté, aucune recopie.
    resp = client.post("/apply", json={**payload, "confirm": True, "resume": True})
    done = sse_events(resp.text)[-1]
    assert done["type"] == "done"
    assert done["stats"]["copied"] == 0
    assert done["stats"]["skipped"] == 2
