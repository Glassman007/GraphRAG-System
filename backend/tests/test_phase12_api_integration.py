from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.app.api_v1.router as v1_router
from backend.app.main import app

pytestmark = pytest.mark.integration
READER={"Authorization":"Bearer test-reader-token","X-Tenant-ID":"northstar"}


@pytest.fixture
def phase12_api(integration_client, monkeypatch):
    monkeypatch.setattr(v1_router, "client_for", lambda principal: integration_client)
    monkeypatch.setattr(v1_router, "_app", lambda principal: v1_router.ExternalApiApplication(integration_client))
    return TestClient(app)


def test_phase12_anomalies_facade_uses_canonical_graph(phase12_api):
    response=phase12_api.get("/api/v1/anomalies",headers=READER)
    assert response.status_code==200
    body=response.json()
    assert body["graph_required"] is True
    assert isinstance(body["anomalies"],list)


def test_phase12_authority_resolution_facade_reuses_phase3_rules(phase12_api):
    response=phase12_api.get("/api/v1/conflicts/INC-001/resolve",headers=READER)
    assert response.status_code==200
    body=response.json()
    assert body["subject_id"]=="INC-001"
    assert "candidates" in body and "rule_set" in body


def test_phase12_company_expertise_facade_is_bounded_and_graph_backed(phase12_api):
    response=phase12_api.get("/api/v1/company-brain/expertise",params={"limit":25},headers=READER)
    assert response.status_code==200
    body=response.json()
    assert body["graph_required"] is True
    assert body["limit"]==25
    assert len(body["items"])<=25
    assert any(item["relationship"] in {"EXPERT_IN","CANDIDATE_EXPERT"} for item in body["items"])
