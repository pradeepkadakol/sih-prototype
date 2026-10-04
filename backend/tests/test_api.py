import base64
import hashlib

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.logic import select_inspector
from app.storage import StorageError


class FakeStore:
    def __init__(self):
        self.objects = {}
        self.fail_upload = False

    def upload(self, key, content, mime_type):
        if self.fail_upload:
            raise StorageError("Upload failed")
        self.objects[key] = (content, mime_type)

    def delete(self, key):
        self.objects.pop(key, None)


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def client(tmp_path, store):
    app = create_app(f"sqlite:///{(tmp_path / 'demo.db').as_posix()}", evidence_store=store, initialize=True)
    with TestClient(app) as test_client:
        yield test_client


def auth(client, username, password="demo1234"):
    token = client.post("/api/login", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_assignment_history_reveal_and_role_checks(client):
    reviewer = auth(client, "reviewer")
    inspector = auth(client, "inspector.arya")
    case_id = next(case["id"] for case in client.get("/api/inspections", headers=reviewer).json() if case["status"] == "pending")
    assert client.post(f"/api/inspections/{case_id}/assign", headers=inspector).status_code == 403
    assigned = client.post(f"/api/inspections/{case_id}/assign", headers=reviewer, json={}).json()
    assert assigned["commitment"] and "seed" not in assigned
    assert client.post(f"/api/inspections/{case_id}/assign", headers=reviewer, json={}).status_code == 409
    second = client.post(f"/api/inspections/{case_id}/assign", headers=reviewer, json={"reason": "Demo reassignment"}).json()
    assert second["event_number"] == 2
    history = client.get(f"/api/inspections/{case_id}/assignment-history", headers=reviewer).json()
    assert len(history) == 2
    revealed = client.post(f"/api/assignments/{assigned['id']}/reveal-seed", headers=reviewer).json()
    assert hashlib.sha256(bytes.fromhex(revealed["seed"])).hexdigest() == assigned["commitment"]
    assert select_inspector(bytes.fromhex(revealed["seed"]), revealed["case_id"], revealed["eligible"], revealed["event_number"]) == revealed["selected_inspector_id"]


def test_inspector_submission_evidence_review_followup(client, store):
    reviewer = auth(client, "reviewer")
    cases = client.get("/api/inspections", headers=reviewer).json()
    case_id = next(case["id"] for case in cases if case["status"] == "assigned")
    detail = client.get(f"/api/inspections/{case_id}", headers=reviewer).json()
    inspector_name = detail["assigned_inspector"]["username"]
    inspector = auth(client, inspector_name)
    assert client.post(f"/api/inspections/{case_id}/submit", headers=inspector).status_code == 409
    assert client.post(f"/api/inspections/{case_id}/check-in", headers=inspector, json={"demo_override": True}).status_code == 200
    assert client.post(f"/api/inspections/{case_id}/submit", headers=inspector).status_code == 409
    answers = [{"item_key": item["key"], "answer": "pass", "note": "Observed"} for item in detail["template"] if item["required"]]
    assert client.put(f"/api/inspections/{case_id}/checklist", headers=inspector, json={"responses": answers}).status_code == 200
    finding = client.post(f"/api/inspections/{case_id}/findings", headers=inspector, json={"severity": "high", "category": "Safety", "description": "Guard rail is loose", "recommended_action": "Repair guard rail"}).json()
    raw = b"\x89PNG\r\n\x1a\n" + b"demo-image"
    evidence = client.post(f"/api/inspections/{case_id}/evidence", headers=inspector, json={"filename": "site.png", "mime_type": "image/png", "data_base64": base64.b64encode(raw).decode()}).json()
    assert evidence["sha256"] == hashlib.sha256(raw).hexdigest()
    assert evidence["server_received_at"]
    assert list(store.objects.values()) == [(raw, "image/png")]
    assert client.post(f"/api/inspections/{case_id}/submit", headers=inspector).status_code == 200
    assert client.post(f"/api/findings/{finding['id']}/review", headers=inspector, json={"status": "accepted", "note": "Looks valid"}).status_code == 403
    assert client.post(f"/api/findings/{finding['id']}/review", headers=reviewer, json={"status": "accepted", "note": "Repair needed"}).status_code == 200
    followup = client.post(f"/api/findings/{finding['id']}/follow-ups", headers=reviewer, json={"owner": "Maintenance cell", "due_date": "2027-02-01", "status": "open"}).json()
    assert followup["owner"] == "Maintenance cell"
    assert followup["history"][0]["status"] == "open"
    assert client.get("/api/dashboard/summary", headers=reviewer).json()["total"] >= 1


def test_upload_rejects_wrong_mime_and_bad_bytes(client):
    reviewer = auth(client, "reviewer")
    case = next(case for case in client.get("/api/inspections", headers=reviewer).json() if case["status"] == "assigned")
    inspector_name = client.get(f"/api/inspections/{case['id']}", headers=reviewer).json()["assigned_inspector"]["username"]
    inspector = auth(client, inspector_name)
    client.post(f"/api/inspections/{case['id']}/check-in", headers=inspector, json={"demo_override": True})
    response = client.post(f"/api/inspections/{case['id']}/evidence", headers=inspector, json={"filename": "x.html", "mime_type": "text/html", "data_base64": base64.b64encode(b"<script>").decode()})
    assert response.status_code == 422


def test_upload_rejects_image_that_would_exceed_vercel_request_limit(client, store):
    reviewer = auth(client, "reviewer")
    case = next(case for case in client.get("/api/inspections", headers=reviewer).json() if case["status"] == "assigned")
    detail = client.get(f"/api/inspections/{case['id']}", headers=reviewer).json()
    inspector = auth(client, detail["assigned_inspector"]["username"])
    client.post(f"/api/inspections/{case['id']}/check-in", headers=inspector, json={"demo_override": True})
    raw = b"\x89PNG\r\n\x1a\n" + b"x" * (3_000_001 - 8)
    response = client.post(
        f"/api/inspections/{case['id']}/evidence",
        headers=inspector,
        json={"filename": "large.png", "mime_type": "image/png", "data_base64": base64.b64encode(raw).decode()},
    )
    assert response.status_code == 413
    assert store.objects == {}


def test_cors_accepts_comma_separated_origins_with_spaces(tmp_path, store, monkeypatch):
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://127.0.0.1:5173, https://example.vercel.app")
    app = create_app(f"sqlite:///{(tmp_path / 'cors.db').as_posix()}", evidence_store=store)
    with TestClient(app) as test_client:
        response = test_client.options(
            "/api/login",
            headers={"Origin": "https://example.vercel.app", "Access-Control-Request-Method": "POST"},
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://example.vercel.app"


def test_storage_failure_does_not_create_evidence_row(client, store):
    reviewer = auth(client, "reviewer")
    case = next(case for case in client.get("/api/inspections", headers=reviewer).json() if case["status"] == "assigned")
    detail = client.get(f"/api/inspections/{case['id']}", headers=reviewer).json()
    inspector = auth(client, detail["assigned_inspector"]["username"])
    client.post(f"/api/inspections/{case['id']}/check-in", headers=inspector, json={"demo_override": True})
    store.fail_upload = True
    raw = b"\x89PNG\r\n\x1a\n" + b"demo-image"
    response = client.post(f"/api/inspections/{case['id']}/evidence", headers=inspector, json={"filename": "site.png", "mime_type": "image/png", "data_base64": base64.b64encode(raw).decode()})
    assert response.status_code == 503
    assert client.get(f"/api/inspections/{case['id']}", headers=inspector).json()["evidence"] == []
    assert store.objects == {}


def test_new_case_cannot_use_seeded_demo_geofence_override(client):
    reviewer = auth(client, "reviewer")
    site_id = client.get("/api/sites", headers=reviewer).json()[0]["id"]
    created = client.post("/api/inspections", headers=reviewer, json={"site_id": site_id}).json()
    assigned = client.post(f"/api/inspections/{created['id']}/assign", headers=reviewer, json={}).json()
    inspector = auth(client, assigned["selected_inspector"]["username"])
    assert client.post(f"/api/inspections/{created['id']}/check-in", headers=inspector, json={"demo_override": True}).status_code == 403
