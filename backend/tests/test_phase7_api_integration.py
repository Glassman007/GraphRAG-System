from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app import main as main_module
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.services.phase6_utils import now_iso

pytestmark = pytest.mark.integration


def uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture
def api(integration_client, monkeypatch):
    monkeypatch.setattr(main_module, "_client", lambda: integration_client)
    return TestClient(main_module.app)


def test_phase7_api_writeback_then_invalidate_and_revalidate(api, integration_client):
    agent, task, execution, claim = uid("AG"), uid("T"), uid("EX"), uid("C")
    upsert_node(integration_client, "Agent", agent, {"status": "ACTIVE", "agent_type": "INVESTIGATOR"})
    upsert_node(integration_client, "Task", task, {"status": "COMPLETED", "completion_condition": "x"})
    upsert_node(integration_client, "Execution", execution, {"status": "COMPLETED", "task_id": task})
    upsert_node(integration_client, "Claim", claim, {"status": "VALIDATED", "statement": "x", "created_at": now_iso()})
    body = {"source_ref":"src:1","content":"new grounded evidence","evidence_type":"LOG","agent_id":agent,"task_id":task,"execution_id":execution,"supports_claim_ids":[claim],"confidence":0.9}
    r = api.post("/learning/evidence", json=body)
    assert r.status_code == 200
    eid = r.json()["entity"]["id"]
    r = api.post(f"/memory/evidence/{eid}/invalidate", json={"reason":"source corrected"})
    assert r.status_code == 200
    # replacement evidence
    body["source_ref"] = "src:2"
    body["content"] = "replacement grounded evidence"
    r2 = api.post("/learning/evidence", json=body)
    eid2 = r2.json()["entity"]["id"]
    rr = api.post(f"/memory/claims/{claim}/revalidate", json={"evidence_id":eid2})
    assert rr.status_code == 200
    assert rr.json()["status"] == "VALIDATED"


def test_phase7_api_promotion_rejects_unverified_artifact(api, integration_client):
    fid = uid("F")
    upsert_node(integration_client, "Finding", fid, {"status":"OPEN","confidence":0.9,"statement":"x"})
    r = api.post(f"/memory/findings/{fid}/promote", json={"subject_ids":["INC-001"]})
    assert r.status_code == 409


def test_phase7_api_lineage_returns_relationships(api, integration_client):
    eid = uid("E")
    upsert_node(integration_client, "Evidence", eid, {"status":"VALIDATED","observed_at":now_iso()})
    upsert_relationship(integration_client, eid, "ABOUT", "INC-001", {"valid_from":now_iso()})
    r = api.get(f"/memory/{eid}/lineage")
    assert r.status_code == 200
    assert any(edge["type"] == "ABOUT" for edge in r.json()["outgoing"])


def test_phase7_api_process_requires_completed_execution(api, integration_client):
    ex = uid("EX")
    upsert_node(integration_client, "Execution", ex, {"status":"RUNNING","task_id":uid("T")})
    r = api.post(f"/learning/executions/{ex}/process")
    assert r.status_code == 200
    assert r.json()["status"] == "NOT_READY"
