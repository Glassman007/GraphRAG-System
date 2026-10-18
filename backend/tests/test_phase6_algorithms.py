from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.graph.schema import NODE_LABELS, RELATIONSHIP_TYPES
from backend.app.main import app
from backend.app.services.action_coordination_service import MockActionExecutor
from backend.app.services.agent_registry_service import AgentRegistryService, DEFAULT_AGENT_SPECS
from backend.app.services.branch_service import BranchMemoryService
from backend.app.services.coordination_risk_service import CoordinationRiskService
from backend.app.services.coordination_service import CoordinationService
from backend.app.services.governance_service import GovernanceService
from backend.app.services.handoff_service import HandoffService
from backend.app.services.memory_compaction_service import MemoryCompactionService
from backend.app.services.phase4_graph import GraphEdge, GraphSnapshot


def node(entity_id: str, label: str, **props):
    return {"id": entity_id, "tenant_id": "northstar", "_labels": ["Entity", label], **props}


def edge(source: str, rel: str, target: str, **props):
    return GraphEdge(source, rel, target, props)


def dummy_client():
    return SimpleNamespace(settings=SimpleNamespace(tenant_id="northstar"))


def test_phase6_schema_additions_are_minimal_and_explicit():
    assert {"Execution", "Finding", "Blocker", "Lock", "ActionAttempt", "CompactionRecord"} <= NODE_LABELS
    assert {
        "HAS_EXECUTION", "HAS_CHECKPOINT", "HAS_BRANCH", "LOCKS", "LOCKED_BY",
        "HAS_ATTEMPT", "HAS_COMPACTION", "PROPOSED_ACTION", "VALIDATED_BY",
    } <= RELATIONSHIP_TYPES


def test_phase6_defines_exactly_four_default_specialist_types():
    types = {spec["agent_type"] for spec in DEFAULT_AGENT_SPECS.values()}
    assert types == {"INVESTIGATOR", "VERIFIER", "DEPENDENCY_ANALYST", "REMEDIATION_WORKER"}


def test_investigator_accepts_investigation_work():
    agent = {"status": "ACTIVE", "availability": "AVAILABLE", "supported_task_types": "ACQUIRE_EVIDENCE,INVESTIGATE", "permissions": "READ_GRAPH,WRITE_FINDING"}
    result = AgentRegistryService._eligibility(agent, {"task_type": "INVESTIGATE"})
    assert result["eligible"] is True


def test_investigator_rejects_remediation_work():
    agent = {"status": "ACTIVE", "availability": "AVAILABLE", "supported_task_types": "ACQUIRE_EVIDENCE,INVESTIGATE", "permissions": "READ_GRAPH"}
    result = AgentRegistryService._eligibility(agent, {"task_type": "PREPARE_ACTION"})
    assert result["eligible"] is False
    assert "TASK_TYPE_NOT_SUPPORTED:PREPARE_ACTION" in result["reason_codes"]


def test_unavailable_agent_is_ineligible_even_with_capability():
    agent = {"status": "ACTIVE", "availability": "BUSY", "supported_task_types": "INVESTIGATE", "permissions": "READ_GRAPH"}
    result = AgentRegistryService._eligibility(agent, {"task_type": "INVESTIGATE"})
    assert result["eligible"] is False
    assert "AGENT_NOT_AVAILABLE" in result["reason_codes"]


def test_agent_without_graph_read_permission_is_ineligible():
    agent = {"status": "ACTIVE", "availability": "AVAILABLE", "supported_task_types": "INVESTIGATE", "permissions": "WRITE_FINDING"}
    result = AgentRegistryService._eligibility(agent, {"task_type": "INVESTIGATE"})
    assert "READ_GRAPH_PERMISSION_REQUIRED" in result["reason_codes"]


def test_active_claims_ignore_expired_claim_edges():
    snap = GraphSnapshot(
        {
            "T": node("T", "Task"),
            "A": node("A", "Agent"),
            "B": node("B", "Agent"),
        },
        [
            edge("T", "CLAIMED_BY", "A", valid_from="2026-10-16T10:00:00+05:30", valid_until="2026-10-16T11:00:00+05:30"),
            edge("T", "CLAIMED_BY", "B", valid_from="2026-10-16T11:00:00+05:30"),
        ],
    )
    claims = CoordinationService._active_claims(snap, "T", as_of="2026-10-16T12:00:00+05:30")
    assert [c["agent"]["id"] for c in claims] == ["B"]


def test_latest_checkpoint_uses_step_index_not_insertion_order():
    snap = GraphSnapshot(
        {
            "E": node("E", "Execution"),
            "C1": node("C1", "Checkpoint", step_index=1, status="ACTIVE", created_at="2026-10-16T10:00:00+05:30"),
            "C2": node("C2", "Checkpoint", step_index=2, status="ACTIVE", created_at="2026-10-16T09:00:00+05:30"),
        },
        [edge("E", "HAS_CHECKPOINT", "C1"), edge("E", "HAS_CHECKPOINT", "C2")],
    )
    assert CoordinationService._latest_checkpoint(snap, "E")["id"] == "C2"


def test_latest_checkpoint_skips_archived_by_default():
    snap = GraphSnapshot(
        {
            "E": node("E", "Execution"),
            "C1": node("C1", "Checkpoint", step_index=1, status="ACTIVE", created_at="2026-10-16T10:00:00+05:30"),
            "C2": node("C2", "Checkpoint", step_index=2, status="ARCHIVED", created_at="2026-10-16T11:00:00+05:30"),
        },
        [edge("E", "HAS_CHECKPOINT", "C1"), edge("E", "HAS_CHECKPOINT", "C2")],
    )
    assert CoordinationService._latest_checkpoint(snap, "E")["id"] == "C1"
    assert CoordinationService._latest_checkpoint(snap, "E", include_archived=True)["id"] == "C2"


def test_deadlock_cycle_detection_finds_two_task_cycle():
    cycles = CoordinationRiskService._cycles({"T1": {"T2"}, "T2": {"T1"}})
    assert cycles == [["T1", "T2", "T1"]]


def test_deadlock_cycle_disappears_when_one_wait_edge_removed():
    assert CoordinationRiskService._cycles({"T1": {"T2"}, "T2": set()}) == []


def test_deadlock_cycle_detection_deduplicates_rotations():
    cycles = CoordinationRiskService._cycles({"A": {"B"}, "B": {"C"}, "C": {"A"}})
    assert len(cycles) == 1
    assert cycles[0][0] == cycles[0][-1]


def test_mock_executor_is_idempotent_by_key():
    executor = MockActionExecutor()
    first = executor.invoke("k1", {"x": 1})
    second = executor.invoke("k1", {"x": 2})
    assert first == second
    assert executor.invocation_count("k1") == 1


def test_mock_executor_executes_distinct_keys_separately():
    executor = MockActionExecutor()
    executor.invoke("k1", {})
    executor.invoke("k2", {})
    assert executor.invocation_count() == 2


def test_handoff_validation_rejects_missing_evidence(monkeypatch):
    service = HandoffService(dummy_client())
    monkeypatch.setattr(service, "get_handoff", lambda _id: {
        "handoff": {
            "id": _id,
            "source_task_id": "T1",
            "from_agent_id": "A",
            "to_agent_id": "B",
            "contract_type": "INVESTIGATOR_TO_VERIFIER",
            "contract_version": "phase6-v1",
            "required_artifacts": "EVIDENCE,FINDING",
            "confidence_threshold": 0.6,
            "contradictory_evidence_disclosed": True,
        },
        "tasks": [{"task": node("T1", "Task"), "role": "SOURCE"}],
        "receiver": node("B", "Agent"),
        "artifacts": [node("F1", "Finding", confidence=0.9)],
    })
    monkeypatch.setattr(service.coordination, "get_unresolved_blockers", lambda _tid: [])
    result = service.validate_handoff("H")
    assert result["valid"] is False
    assert result["missing_evidence"] == ["EVIDENCE"]


def test_handoff_validation_rejects_low_confidence(monkeypatch):
    service = HandoffService(dummy_client())
    monkeypatch.setattr(service, "get_handoff", lambda _id: {
        "handoff": {
            "id": _id,
            "source_task_id": "T1",
            "from_agent_id": "A",
            "to_agent_id": "B",
            "contract_type": "INVESTIGATOR_TO_VERIFIER",
            "contract_version": "phase6-v1",
            "required_artifacts": "EVIDENCE,FINDING",
            "confidence_threshold": 0.8,
            "contradictory_evidence_disclosed": True,
        },
        "tasks": [],
        "receiver": node("B", "Agent"),
        "artifacts": [node("F1", "Finding", confidence=0.5), node("E1", "Evidence")],
    })
    monkeypatch.setattr(service.coordination, "get_unresolved_blockers", lambda _tid: [])
    result = service.validate_handoff("H")
    assert result["valid"] is False
    assert result["confidence_failures"][0]["finding_id"] == "F1"


def test_handoff_validation_reports_unresolved_blocker(monkeypatch):
    service = HandoffService(dummy_client())
    monkeypatch.setattr(service, "get_handoff", lambda _id: {
        "handoff": {
            "id": _id, "source_task_id": "T1", "from_agent_id": "A", "to_agent_id": "B",
            "contract_type": "INVESTIGATOR_TO_VERIFIER", "contract_version": "phase6-v1",
            "required_artifacts": "EVIDENCE,FINDING", "confidence_threshold": 0.5,
            "contradictory_evidence_disclosed": True,
        },
        "tasks": [], "receiver": node("B", "Agent"),
        "artifacts": [node("F1", "Finding", confidence=0.9), node("E1", "Evidence")],
    })
    monkeypatch.setattr(service.coordination, "get_unresolved_blockers", lambda _tid: [node("BL", "Blocker", status="OPEN")])
    result = service.validate_handoff("H")
    assert "UNRESOLVED_BLOCKERS" in result["errors"]


def test_handoff_validation_accepts_complete_contract(monkeypatch):
    service = HandoffService(dummy_client())
    monkeypatch.setattr(service, "get_handoff", lambda _id: {
        "handoff": {
            "id": _id, "source_task_id": "T1", "from_agent_id": "A", "to_agent_id": "B",
            "contract_type": "INVESTIGATOR_TO_VERIFIER", "contract_version": "phase6-v1",
            "required_artifacts": "EVIDENCE,FINDING", "confidence_threshold": 0.5,
            "contradictory_evidence_disclosed": True,
        },
        "tasks": [], "receiver": node("B", "Agent"),
        "artifacts": [node("F1", "Finding", confidence=0.9), node("E1", "Evidence")],
    })
    monkeypatch.setattr(service.coordination, "get_unresolved_blockers", lambda _tid: [])
    assert service.validate_handoff("H")["valid"] is True


def governance_snapshot(*, approval=True, deny=False, permission=True, task_status="IN_PROGRESS"):
    nodes = {
        "ACT": node("ACT", "Action", action_type="rollback", status="PROPOSED", approval_required=True, idempotency_key="k"),
        "TASK": node("TASK", "Task", task_type="PREPARE_ACTION", status=task_status),
        "AG": node("AG", "Agent", agent_type="REMEDIATION_WORKER", permissions="EXECUTE_SANDBOX_ACTION,READ_GRAPH" if permission else "READ_GRAPH", actions_may_execute="rollback"),
        "SYS": node("SYS", "System", status="ACTIVE"),
        "POL": node("POL", "Policy", status="ACTIVE", authoritative=True, effect="DENY" if deny else "ALLOW"),
        "OWNER": node("OWNER", "Team", status="ACTIVE"),
    }
    edges = [edge("TASK", "PROPOSED_ACTION", "ACT"), edge("ACT", "ABOUT", "SYS"), edge("POL", "GOVERNS", "ACT", authoritative=True)]
    if approval:
        nodes["APP"] = node("APP", "Person", status="ACTIVE")
        edges.append(edge("ACT", "APPROVED_BY", "APP"))
    return GraphSnapshot(nodes, edges)


def patch_governance(monkeypatch, service, snap):
    monkeypatch.setattr("backend.app.services.governance_service.GraphSnapshot.load", lambda _client: snap)
    monkeypatch.setattr(service.coordination, "get_task_owner", lambda _tid, as_of=None: {"owner": snap.node("AG")})
    monkeypatch.setattr(service.coordination, "get_unresolved_blockers", lambda _tid: [])
    monkeypatch.setattr(
        "backend.app.services.governance_service.ResponsibilityRoutingService.find_owner",
        lambda _self, entity_id, as_of=None: {"owners": [{"actor": snap.node("OWNER"), "path": ["OWNER", "OWNS", entity_id]}]},
    )


def test_governance_allows_authorized_approved_action(monkeypatch):
    snap = governance_snapshot()
    service = GovernanceService(dummy_client())
    patch_governance(monkeypatch, service, snap)
    assert service.evaluate_action("ACT", agent_id="AG")["decision"] == "ALLOW"


def test_governance_denies_agent_without_permission(monkeypatch):
    snap = governance_snapshot(permission=False)
    service = GovernanceService(dummy_client())
    patch_governance(monkeypatch, service, snap)
    result = service.evaluate_action("ACT", agent_id="AG")
    assert result["decision"] == "DENY"
    assert "AGENT_EXECUTION_PERMISSION_MISSING" in result["missing_requirements"]


def test_governance_requires_missing_approval(monkeypatch):
    snap = governance_snapshot(approval=False)
    service = GovernanceService(dummy_client())
    patch_governance(monkeypatch, service, snap)
    result = service.evaluate_action("ACT", agent_id="AG")
    assert result["decision"] == "REQUIRES_APPROVAL"


def test_policy_deny_overrides_agent_permission(monkeypatch):
    snap = governance_snapshot(deny=True)
    service = GovernanceService(dummy_client())
    patch_governance(monkeypatch, service, snap)
    result = service.evaluate_action("ACT", agent_id="AG")
    assert result["decision"] == "DENY"
    assert "AUTHORITATIVE_POLICY_DENY" in result["missing_requirements"]


def test_blocked_task_is_denied_by_governance(monkeypatch):
    snap = governance_snapshot(task_status="BLOCKED")
    service = GovernanceService(dummy_client())
    patch_governance(monkeypatch, service, snap)
    result = service.evaluate_action("ACT", agent_id="AG")
    assert result["decision"] == "DENY"
    assert "TASK_NOT_IN_EXECUTION_STATE" in result["missing_requirements"]


def test_compaction_validation_detects_broken_evidence_lineage(monkeypatch):
    nodes = {
        "C": node("C", "CompactionRecord", execution_id="EX"),
        "EX": node("EX", "Execution", task_id="T"),
        "T": node("T", "Task"),
        "E": node("E", "Evidence"),
    }
    snap = GraphSnapshot(nodes, [edge("T", "HAS_EXECUTION", "EX")])
    service = MemoryCompactionService(dummy_client())
    monkeypatch.setattr("backend.app.services.memory_compaction_service.GraphSnapshot.load", lambda _client: snap)
    monkeypatch.setattr(service, "_execution_context", lambda _snap, _exec: {"execution": nodes["EX"], "task": nodes["T"], "task_id": "T", "checkpoints": [], "retained": {"E": nodes["E"]}})
    result = service.validate_compaction("C")
    assert result["valid"] is False
    assert "ARTIFACT_TASK_LINEAGE_BROKEN:E" in result["errors"]


def test_compaction_validation_accepts_preserved_evidence_lineage(monkeypatch):
    nodes = {
        "C": node("C", "CompactionRecord", execution_id="EX"),
        "EX": node("EX", "Execution", task_id="T"),
        "T": node("T", "Task"),
        "E": node("E", "Evidence"),
    }
    snap = GraphSnapshot(nodes, [edge("T", "HAS_EXECUTION", "EX"), edge("E", "ABOUT", "T")])
    service = MemoryCompactionService(dummy_client())
    monkeypatch.setattr("backend.app.services.memory_compaction_service.GraphSnapshot.load", lambda _client: snap)
    monkeypatch.setattr(service, "_execution_context", lambda _snap, _exec: {"execution": nodes["EX"], "task": nodes["T"], "task_id": "T", "checkpoints": [], "retained": {"E": nodes["E"]}})
    assert service.validate_compaction("C")["valid"] is True


def test_phase6_api_routes_are_registered_without_raw_cypher():
    paths = {route.path for route in app.routes}
    required = {
        "/tasks/{task_id}/claim",
        "/tasks/{task_id}/start",
        "/tasks/{task_id}/checkpoint",
        "/tasks/{task_id}/resume",
        "/plans/{plan_id}/coordination-state",
        "/tasks/{task_id}/findings",
        "/transfers",
        "/branches",
        "/coordination/contention",
        "/coordination/deadlocks",
        "/actions/{action_id}/governance",
        "/actions/{action_id}/execute",
        "/executions/{execution_id}/compact",
    }
    assert required <= paths
    assert not any("cypher" in path.lower() for path in paths)


def test_phase5_forbidden_route_name_contract_remains_true():
    paths = {route.path for route in app.routes}
    forbidden_tokens = {"claim-task", "execute-task", "handoff", "blackboard", "langgraph"}
    assert not any(any(token in path.lower() for token in forbidden_tokens) for path in paths)
