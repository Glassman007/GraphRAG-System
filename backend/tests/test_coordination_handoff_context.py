"""Offline contract tests for VERINEX multi-agent Investigator -> Verifier handoffs.

Executes production services/mutation functions against an intentionally narrow,
in-memory Cypher graph adapter. This is not a substitute for a FalkorDB/live LLM E2E.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.services.agent_registry_service import AgentRegistryService
from backend.app.services.coordination_service import CoordinationService
from backend.app.services.handoff_service import HandoffService

INVESTIGATOR = "AGENT-P6-INVESTIGATOR"
VERIFIER = "AGENT-P6-VERIFIER"
OTHER = "AGENT-P6-DEPENDENCY"


class GraphNode:
    def __init__(self, props):
        self.properties = {k: v for k, v in props.items() if k != "_labels"}
        self.labels = props.get("_labels", [])


class Result:
    def __init__(self, result_set):
        self.result_set = result_set


class MemoryGraphClient:
    """Fake persistence only: services, validation, traversal and mutation code are real."""

    def __init__(self):
        self.settings = SimpleNamespace(tenant_id="coordination-test")
        self.nodes = {}
        self.edges = {}

    def query(self, cypher, params=None):
        params = params or {}
        if "MERGE (n:Entity:" in cypher:
            label = re.search(r"MERGE \(n:Entity:(\w+)", cypher).group(1)
            identity = params["id"]
            current = self.nodes.setdefault(identity, {"id": identity, "_labels": ["Entity", label]})
            if label not in current["_labels"]:
                current["_labels"].append(label)
            current.update(params["props"])
            return Result([[GraphNode(current)]])
        if "MERGE (a)-[r:" in cypher:
            label = re.search(r"MERGE \(a\)-\[r:(\w+)", cypher).group(1)
            source, target = params["source_id"], params["target_id"]
            if source not in self.nodes or target not in self.nodes:
                return Result([])
            edge_id = params["edge_id"]
            edge = self.edges.setdefault((source, label, target, edge_id), {})
            edge.update(params["props"])
            return Result([[SimpleNamespace(properties=edge)]])
        raise NotImplementedError(f"Offline fake does not support Cypher: {cypher[:140]}")

    def read(self, cypher, params=None):
        if "RETURN n ORDER BY n.id" in cypher:
            return Result([[GraphNode(v)] for _, v in sorted(self.nodes.items())])
        if "RETURN a.id, type(r), r, b.id" in cypher:
            return Result([
                [a, rel, SimpleNamespace(properties=properties), b]
                for (a, rel, b, _), properties in sorted(self.edges.items())
            ])
        raise NotImplementedError(f"Offline fake does not support read: {cypher[:140]}")


@pytest.fixture
def scenario():
    db = MemoryGraphClient()
    AgentRegistryService(db).ensure_default_agents()
    for task_id in ("TASK-INCIDENT-42", "TASK-VERIFY-42", "TASK-OTHER-99"):
        upsert_node(db, "Task", task_id, {"title": task_id, "task_type": "INVESTIGATE", "status": "IN_PROGRESS"})
    upsert_relationship(db, "TASK-INCIDENT-42", "CLAIMED_BY", INVESTIGATOR, {"valid_from": "2026-10-21T09:00:00+05:30"})
    upsert_node(db, "Evidence", "E-INCIDENT-LOG", {
        "name": "Checkout incident logs 09:17 UTC", "source_ref_id": "incident-42:log-901",
        "observed_at": "2026-10-21T09:20:00+05:30", "status": "ACTIVE",
    })
    upsert_node(db, "Evidence", "E-UNRELATED", {"name": "Other incident evidence", "source_ref_id": "incident-99:log-321"})
    coord = CoordinationService(db)
    own = coord.add_finding(
        "TASK-INCIDENT-42", INVESTIGATOR,
        statement="Checkout failures started after deployment dep-42 at 09:15 UTC",
        confidence=0.91, evidence_ids=["E-INCIDENT-LOG"],
    )["finding"]["id"]
    other = coord.add_finding(
        "TASK-OTHER-99", OTHER,
        statement="Unrelated price sync issue", confidence=0.95, evidence_ids=["E-UNRELATED"],
    )["finding"]["id"]
    return db, own, other


def make_handoff(scenario, *, artifact_ids=None, from_agent_id=INVESTIGATOR):
    db, own, other = scenario
    details = HandoffService(db).create_handoff(
        "TASK-INCIDENT-42", from_agent_id, VERIFIER,
        artifact_ids=artifact_ids if artifact_ids is not None else [own, "E-INCIDENT-LOG"],
        destination_task_id="TASK-VERIFY-42", confidence_threshold=0.8,
    )
    return HandoffService(db), details["handoff"]["id"]


def test_valid_multi_agent_handoff_retains_exact_context_across_service_instances(scenario):
    db, own, _ = scenario
    service, hid = make_handoff(scenario)
    assert service.validate_handoff(hid)["valid"] is True
    service.accept_handoff(hid, VERIFIER)
    receiver = HandoffService(db).get_handoff(hid)
    assert receiver["handoff"]["status"] == "ACCEPTED"
    assert {x["id"] for x in receiver["artifacts"]} == {own, "E-INCIDENT-LOG"}
    assert any(x["statement"] == "Checkout failures started after deployment dep-42 at 09:15 UTC" for x in receiver["artifacts"] if "Finding" in x["_labels"])
    assert any(x.get("source_ref_id") == "incident-42:log-901" for x in receiver["artifacts"])
    # The destination agent's task workspace should expose accepted handoff CONTEXT,
    # not just the opaque handoff ID: agents must be able to continue investigation.
    board = CoordinationService(db).get_task_blackboard("TASK-VERIFY-42")
    assert any(
        item["handoff"]["id"] == hid and {a["id"] for a in item["artifacts"]} == {own, "E-INCIDENT-LOG"}
        and item["source_agent"]["id"] == INVESTIGATOR
        and item["receiver"]["id"] == VERIFIER
        and {tuple(link[k] for k in ("finding_id", "evidence_id", "relationship")) for link in item["evidence_links"]}
            == {(own, "E-INCIDENT-LOG", "DERIVED_FROM")}
        for item in board["accepted_handoff_context"]
    )


def test_wrong_task_finding_cannot_be_laundered_into_a_valid_handoff(scenario):
    _, own, other = scenario
    service, hid = make_handoff(scenario, artifact_ids=[other, "E-INCIDENT-LOG"])
    validation = service.validate_handoff(hid)
    assert not validation["valid"]
    assert "FINDING_NOT_FROM_SOURCE_TASK" in validation["errors"]
    with pytest.raises(ValueError):
        service.accept_handoff(hid, VERIFIER)


def test_unrelated_evidence_cannot_validate_a_correct_finding(scenario):
    _, own, other = scenario
    service, hid = make_handoff(scenario, artifact_ids=[own, "E-UNRELATED"])
    validation = service.validate_handoff(hid)
    assert not validation["valid"]
    assert "EVIDENCE_NOT_LINKED_TO_FINDING" in validation["errors"]


def test_sender_cannot_impersonate_source_task_owner(scenario):
    db, own, other = scenario
    with pytest.raises(ValueError, match="owner"):
        make_handoff(scenario, from_agent_id=OTHER)


def test_rejected_handoff_cannot_be_later_accepted(scenario):
    service, hid = make_handoff(scenario)
    service.reject_handoff(hid, VERIFIER, reason="Detected a conflicting deployment record")
    with pytest.raises(ValueError, match="PENDING"):
        service.accept_handoff(hid, VERIFIER)


def test_accepted_handoff_cannot_be_rejected(scenario):
    service, hid = make_handoff(scenario)
    service.accept_handoff(hid, VERIFIER)
    with pytest.raises(ValueError, match="PENDING"):
        service.reject_handoff(hid, VERIFIER, reason="Late rejection")


def test_pending_handoff_not_exposed_as_accepted_context(scenario):
    db, own, other = scenario
    make_handoff(scenario)
    board = CoordinationService(db).get_task_blackboard("TASK-VERIFY-42")
    assert board["accepted_handoff_context"] == []


def test_verifier_can_consume_handoff_and_record_verification(scenario):
    from backend.app.services.specialist_agent_service import SpecialistAgentService

    db, own, other = scenario
    service, hid = make_handoff(scenario)
    service.accept_handoff(hid, VERIFIER)
    # The second agent reads the first agent's statement from its OWN task blackboard.
    context = CoordinationService(db).get_task_blackboard("TASK-VERIFY-42")["accepted_handoff_context"]
    passed_finding = next(a for a in context[0]["artifacts"] if "Finding" in a["_labels"])
    assert passed_finding["id"] == own
    result = SpecialistAgentService(db).verify_finding(
        passed_finding["id"], VERIFIER, result="VERIFIED",
        rationale="Incident log corroborates the deployment timestamp",
    )
    assert result["finding"]["status"] == "VERIFIED"
    assert CoordinationService(db).get_recent_findings("TASK-INCIDENT-42")[0]["status"] == "VERIFIED"


def test_sender_must_be_actual_finding_producer(scenario):
    db, own, other = scenario
    fabricated = CoordinationService(db).add_finding(
        "TASK-INCIDENT-42", OTHER, statement="Claim inserted by a different worker",
        confidence=0.96, evidence_ids=["E-INCIDENT-LOG"],
    )["finding"]["id"]
    service, hid = make_handoff(scenario, artifact_ids=[fabricated, "E-INCIDENT-LOG"])
    assert "FINDING_NOT_PRODUCED_BY_SENDER" in service.validate_handoff(hid)["errors"]


def test_unmerged_branch_finding_not_shared_as_verifier_context(scenario):
    db, own, other = scenario
    upsert_node(db, "WorkBranch", "BRANCH-UNMERGED", {"name": "Unmerged hypothesis"})
    branch_finding = CoordinationService(db).add_finding(
        "TASK-INCIDENT-42", INVESTIGATOR, statement="Unmerged alternate cause",
        confidence=0.99, evidence_ids=["E-INCIDENT-LOG"], branch_id="BRANCH-UNMERGED",
    )["finding"]["id"]
    service, hid = make_handoff(scenario, artifact_ids=[branch_finding, "E-INCIDENT-LOG"])
    assert "UNMERGED_BRANCH_FINDING" in service.validate_handoff(hid)["errors"]


def test_wrong_agent_cannot_accept_valid_context(scenario):
    service, hid = make_handoff(scenario)
    with pytest.raises(ValueError, match="designated receiver"):
        service.accept_handoff(hid, OTHER)


def test_finalized_handoff_cannot_be_reopened_through_deterministic_id(scenario):
    service, hid = make_handoff(scenario)
    service.reject_handoff(hid, VERIFIER, reason="Supporting evidence is stale")
    with pytest.raises(ValueError, match="finalized"):
        make_handoff(scenario)


def test_accepted_context_does_not_appear_in_unrelated_task_workspace(scenario):
    db, own, other = scenario
    service, hid = make_handoff(scenario)
    service.accept_handoff(hid, VERIFIER)
    unrelated = CoordinationService(db).get_task_blackboard("TASK-OTHER-99")
    assert unrelated["accepted_handoff_context"] == []


def test_unrelated_extra_evidence_cannot_be_smuggled_with_valid_pair(scenario):
    db, own, other = scenario
    service, hid = make_handoff(scenario, artifact_ids=[own, "E-INCIDENT-LOG", "E-UNRELATED"])
    assert "EVIDENCE_NOT_LINKED_TO_FINDING" in service.validate_handoff(hid)["errors"]
