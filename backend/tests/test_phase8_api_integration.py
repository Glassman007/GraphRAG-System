from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import main as main_module

pytestmark = pytest.mark.integration


@pytest.fixture
def api(integration_client, monkeypatch):
    monkeypatch.setattr(main_module, "_client", lambda: integration_client)
    return TestClient(main_module.app)


def test_phase8_api_process_and_policy_drift(api):
    r = api.get("/incidents/INC-001/process")
    assert r.status_code == 200 and r.json()["steps"]
    d = api.get("/processes/INC-001/policy-drift", params={"policy_id": "POL-DB-04"})
    assert d.status_code == 200
    assert any(x["classification"] == "MISSING_REQUIRED_STEP" for x in d.json()["drift"])


def test_phase8_api_commitment_and_at_risk(api):
    r = api.get("/commitments/COM-017", params={"as_of": "2026-10-16T15:00:00+05:30"})
    assert r.status_code == 200 and r.json()["status"] == "BREACHED"
    all_risk = api.get("/commitments/at-risk", params={"as_of": "2026-10-16T15:00:00+05:30"})
    assert all_risk.status_code == 200
    assert "COM-017" in {x["commitment"]["id"] for x in all_risk.json()}


def test_phase8_api_collision_bus_factor_and_network(api):
    c = api.get("/projects/PROJ-REFUND-A/collisions")
    assert c.status_code == 200
    assert any(x["project_b"]["id"] == "PROJ-REFUND-B" or x["project_a"]["id"] == "PROJ-REFUND-B" for x in c.json()["collisions"])
    b = api.post("/organization/bus-factor/simulate", json={"actor_ids": ["PERSON-ISHA"]})
    assert b.status_code == 200 and b.json()["canonical_graph_mutated"] is False
    n = api.get("/organization/network-analysis", params={"projection": "collaboration"})
    assert n.status_code == 200 and n.json()["articulation_points"]


def test_phase8_api_invalid_ids_and_parameters(api):
    assert api.get("/processes/NOPE/reconstruct").status_code == 404
    assert api.get("/commitments/NOPE").status_code == 404
    assert api.get("/projects/NOPE/collisions").status_code == 404
    assert api.get("/organization/network-analysis", params={"projection": "everything"}).status_code == 422
