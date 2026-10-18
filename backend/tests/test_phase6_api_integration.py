from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

import backend.app.main as main_module
from backend.app.graph.mutations import upsert_node
from backend.app.services.phase6_utils import now_iso


pytestmark = pytest.mark.integration

REMEDIATION = "AGENT-P6-REMEDIATION"
VERIFIER = "AGENT-P6-VERIFIER"


def _task(client, task_type="PREPARE_ACTION"):
    task_id = f"TASK-P6-API-{uuid.uuid4().hex[:12]}"
    upsert_node(
        client,
        "Task",
        task_id,
        {
            "name": "Phase 6 API flow",
            "title": "Phase 6 API flow",
            "task_type": task_type,
            "objective": "Exercise persistent coordination through FastAPI",
            "status": "OPEN",
            "priority": "P1",
            "created_at": now_iso(),
            "expected_output_type": "ACTION_PROPOSAL" if task_type == "PREPARE_ACTION" else "INVESTIGATION_RESULT",
            "completion_condition": "Persisted API coordination flow succeeds",
        },
    )
    return task_id


def _api(monkeypatch, integration_client):
    monkeypatch.setattr(main_module, "_client", lambda: integration_client)
    return TestClient(main_module.app)


def test_phase6_fastapi_success_flow_persists_claim_checkpoint_transfer_action_and_outcome(monkeypatch, integration_client):
    api = _api(monkeypatch, integration_client)
    assert api.post("/agents/ensure-defaults").status_code == 200
    task_id = _task(integration_client)

    claimed = api.post(f"/tasks/{task_id}/claim", json={"agent_id": REMEDIATION})
    assert claimed.status_code == 200 and claimed.json()["status"] == "CLAIMED"

    started = api.post(f"/tasks/{task_id}/start", json={"agent_id": REMEDIATION})
    assert started.status_code == 200
    execution_id = started.json()["execution"]["id"]

    checkpoint = api.post(
        f"/tasks/{task_id}/checkpoint",
        json={
            "agent_id": REMEDIATION,
            "execution_id": execution_id,
            "step_index": 1,
            "current_step": "prepare sandbox remediation",
            "completed_steps": ["inspect task"],
            "pending_steps": ["propose action"],
            "state_summary": "Preparation checkpoint",
        },
    )
    assert checkpoint.status_code == 200

    resumed = api.post(f"/tasks/{task_id}/resume", json={"agent_id": REMEDIATION, "execution_id": execution_id})
    assert resumed.status_code == 200 and resumed.json()["resume_from_step"] == 2

    finding = api.post(
        f"/tasks/{task_id}/findings",
        json={"agent_id": REMEDIATION, "statement": "Rollback is prepared for sandbox execution", "confidence": 0.95},
    )
    assert finding.status_code == 200
    finding_id = finding.json()["finding"]["id"]

    transfer = api.post(
        "/transfers",
        json={
            "source_task_id": task_id,
            "from_agent_id": REMEDIATION,
            "to_agent_id": VERIFIER,
            "artifact_ids": [finding_id],
            "confidence_threshold": 0.8,
        },
    )
    assert transfer.status_code == 200
    transfer_id = transfer.json()["handoff"]["id"]
    validation = api.get(f"/transfers/{transfer_id}/validate")
    assert validation.status_code == 200 and validation.json()["valid"] is True
    accepted = api.post(f"/transfers/{transfer_id}/accept", json={"agent_id": VERIFIER})
    assert accepted.status_code == 200 and accepted.json()["handoff"]["status"] == "ACCEPTED"

    key = f"api-idem-{uuid.uuid4().hex}"
    proposed = api.post(
        "/actions",
        json={
            "task_id": task_id,
            "agent_id": REMEDIATION,
            "name": "API sandbox rollback",
            "action_type": "rollback",
            "target_ids": ["SYS-PRICING-DB"],
            "idempotency_key": key,
            "approval_required": False,
        },
    )
    assert proposed.status_code == 200
    action_id = proposed.json()["action"]["id"]

    governance = api.get(f"/actions/{action_id}/governance", params={"agent_id": REMEDIATION})
    assert governance.status_code == 200 and governance.json()["decision"] == "ALLOW"
    executed = api.post(f"/actions/{action_id}/execute", json={"agent_id": REMEDIATION})
    assert executed.status_code == 200 and executed.json()["status"] == "SUCCEEDED"

    action_state = api.get(f"/actions/{action_id}/coordination")
    assert action_state.status_code == 200
    assert action_state.json()["action"]["status"] == "SUCCEEDED"
    assert action_state.json()["attempt"]["execution_state"] == "SUCCEEDED"

    persisted = api.get(f"/tasks/{task_id}/coordination-state")
    assert persisted.status_code == 200
    body = persisted.json()
    assert body["owner_state"]["owner"]["id"] == REMEDIATION
    assert any(cp["step_index"] == 1 for cp in body["checkpoints"])
    assert any(item["id"] == finding_id for item in body["findings"])
    assert any(item["id"] == transfer_id for item in body["handoffs"])
    assert any(item["id"] == action_id for item in body["proposed_actions"])


def test_phase6_fastapi_rejects_ineligible_claim(monkeypatch, integration_client):
    api = _api(monkeypatch, integration_client)
    api.post("/agents/ensure-defaults")
    task_id = _task(integration_client, "PREPARE_ACTION")
    response = api.post(f"/tasks/{task_id}/claim", json={"agent_id": VERIFIER})
    assert response.status_code == 400
    assert "TASK_TYPE_NOT_SUPPORTED:PREPARE_ACTION" in response.json()["detail"]


def test_phase6_fastapi_handoff_accept_fails_when_contract_is_invalid(monkeypatch, integration_client):
    api = _api(monkeypatch, integration_client)
    api.post("/agents/ensure-defaults")
    task_id = _task(integration_client, "INVESTIGATE")
    investigator = "AGENT-P6-INVESTIGATOR"
    assert api.post(f"/tasks/{task_id}/claim", json={"agent_id": investigator}).status_code == 200
    finding = api.post(
        f"/tasks/{task_id}/findings",
        json={"agent_id": investigator, "statement": "Evidence is still missing", "confidence": 0.9},
    )
    finding_id = finding.json()["finding"]["id"]
    transfer = api.post(
        "/transfers",
        json={"source_task_id": task_id, "from_agent_id": investigator, "to_agent_id": VERIFIER, "artifact_ids": [finding_id]},
    )
    transfer_id = transfer.json()["handoff"]["id"]
    validation = api.get(f"/transfers/{transfer_id}/validate")
    assert validation.status_code == 200 and validation.json()["valid"] is False
    accepted = api.post(f"/transfers/{transfer_id}/accept", json={"agent_id": VERIFIER})
    assert accepted.status_code == 409
    assert "cannot be accepted" in accepted.json()["detail"].lower()
