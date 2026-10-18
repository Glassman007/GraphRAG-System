from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
import backend.app.api_v1.router as routes


class FakeApp:
    def __init__(self, *_):
        self.client = object()
    def get_node(self, entity_id, as_of=None):
        return {"id": entity_id, "_labels": ["System"]} if entity_id == "SYS-1" else None


class FakeAnomaly:
    def __init__(self, *_): pass
    def detect(self):
        return {"anomalies": [{"rule": "R1", "severity": "HIGH"}], "count": 1, "graph_required": True}


class FakeAuthority:
    def __init__(self, *_): pass
    def resolve_subject_conflicts(self, entity_id, *, as_of=None):
        return {"subject_id": entity_id, "as_of": as_of, "status": "RESOLVED", "selected_claim_id": "C1"}


class FakeExpertise:
    def __init__(self, *_): pass
    def list(self, *, as_of=None, limit=200):
        return {"as_of": as_of, "items": [{"actor": {"id": "P1"}, "domain": {"id": "S1"}}], "count": 1, "limit": limit, "graph_required": True}


def headers(token="test-admin-token"):
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": "northstar"}


def test_phase12_session_exposes_permissions():
    response = TestClient(app).get("/api/v1/session", headers=headers())
    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == "northstar"
    assert "READ_GRAPH" in data["permissions"]


def test_phase12_anomalies_facade(monkeypatch):
    monkeypatch.setattr(routes, "GraphAnomalyService", FakeAnomaly)
    monkeypatch.setattr(routes, "client_for", lambda principal: object())
    response = TestClient(app).get("/api/v1/anomalies", headers=headers())
    assert response.status_code == 200
    assert response.json()["anomalies"][0]["rule"] == "R1"


def test_phase12_authority_facade(monkeypatch):
    monkeypatch.setattr(routes, "_app", lambda principal: FakeApp())
    monkeypatch.setattr(routes, "AuthorityResolutionService", FakeAuthority)
    response = TestClient(app).get("/api/v1/conflicts/SYS-1/resolve", headers=headers())
    assert response.status_code == 200
    assert response.json()["selected_claim_id"] == "C1"


def test_phase12_authority_facade_missing_entity(monkeypatch):
    monkeypatch.setattr(routes, "_app", lambda principal: FakeApp())
    response = TestClient(app).get("/api/v1/conflicts/MISSING/resolve", headers=headers())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_phase12_expertise_facade(monkeypatch):
    monkeypatch.setattr(routes, "CompanyBrainExpertiseService", FakeExpertise)
    monkeypatch.setattr(routes, "client_for", lambda principal: object())
    response = TestClient(app).get("/api/v1/company-brain/expertise?limit=20", headers=headers())
    assert response.status_code == 200
    assert response.json()["items"][0]["actor"]["id"] == "P1"


def test_phase12_reader_can_use_read_facades(monkeypatch):
    monkeypatch.setattr(routes, "GraphAnomalyService", FakeAnomaly)
    monkeypatch.setattr(routes, "client_for", lambda principal: object())
    response = TestClient(app).get("/api/v1/anomalies", headers=headers("test-reader-token"))
    assert response.status_code == 200
