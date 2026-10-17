from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.main import app
from backend.app.services.work_planning_service import WorkPlanningService


class _Result:
    def __init__(self, rows):
        self.result_set = rows


class FixtureGraphClient:
    def __init__(self, root: Path):
        self.settings = SimpleNamespace(tenant_id="northstar")
        self.nodes = {}
        self.edges = []
        paths = [root / "fixtures" / "canonical_incident.json", *sorted((root / "fixtures" / "scenarios").glob("*.json"))]
        for path in paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data.get("nodes", []):
                node = dict(item["properties"])
                node["id"] = item["id"]
                node["_labels"] = ["Entity", item["label"]]
                self.nodes[item["id"]] = node
            self.edges.extend(data.get("edges", []))

    def read(self, cypher, params=None):
        if "RETURN n ORDER BY n.id" in cypher:
            return _Result([[self.nodes[k]] for k in sorted(self.nodes)])
        if "RETURN a.id, type(r), r, b.id" in cypher:
            rows = []
            for edge in sorted(self.edges, key=lambda x: (x["source"], x["type"], x["target"])):
                if edge["source"] in self.nodes and edge["target"] in self.nodes:
                    rows.append([edge["source"], edge["type"], dict(edge.get("properties") or {}), edge["target"]])
            return _Result(rows)
        raise AssertionError(f"Unexpected read query in fixture test: {cypher}")


def _service(project_root: Path) -> WorkPlanningService:
    return WorkPlanningService(FixtureGraphClient(project_root))


def _derive(project_root: Path, **kwargs):
    return _service(project_root).derive_plan(
        "INC-001",
        "Resolve INC-001 safely with enough evidence to select remediation.",
        **kwargs,
    )


def test_phase5_planner_derives_typed_work_from_existing_reasoning(project_root):
    result = _derive(project_root)
    assert result is not None
    assert result["plan_id"].startswith("PLAN-P5-")
    types = {task["task_type"] for task in result["tasks"]}
    assert {"ACQUIRE_EVIDENCE", "INVESTIGATE", "RESOLVE_CONFLICT", "PREPARE_ACTION", "VALIDATE_POLICY"} <= types
    assert all(task["expected_output_type"] for task in result["tasks"])
    assert all(task["completion_condition"] for task in result["tasks"])


def test_phase5_knowledge_gaps_generate_q001_through_q004_work(project_root):
    result = _derive(project_root)
    addressed = {
        entity_id
        for task in result["tasks"]
        if task["task_type"] in {"ACQUIRE_EVIDENCE", "INVESTIGATE"}
        for entity_id in task["addresses"]
    }
    assert {"Q-001", "Q-002", "Q-003", "Q-004"} <= addressed


def test_phase5_question_task_type_comes_from_graph_tool_capability(project_root):
    result = _derive(project_root)
    by_question = {
        task["addresses"][0]: task
        for task in result["tasks"]
        if task["task_type"] in {"ACQUIRE_EVIDENCE", "INVESTIGATE"} and task["addresses"]
    }
    assert by_question["Q-001"]["task_type"] == "ACQUIRE_EVIDENCE"
    assert by_question["Q-002"]["task_type"] == "INVESTIGATE"
    assert "TOOL-DEPLOY-LOOKUP" in by_question["Q-001"]["requires_entities"]
    assert "TOOL-CATALOG-LOOKUP" in by_question["Q-002"]["requires_entities"]


def test_phase5_conflict_resolution_depends_on_relevant_evidence_tasks(project_root):
    result = _derive(project_root)
    conflict = next(task for task in result["tasks"] if task["task_type"] == "RESOLVE_CONFLICT")
    assert set(conflict["addresses"]) == {"C-001", "C-002"}
    assert "question:Q-001:ACQUIRE_EVIDENCE" in conflict["prerequisite_keys"]
    assert "question:Q-002:INVESTIGATE" in conflict["prerequisite_keys"]
    assert "question:Q-003:ACQUIRE_EVIDENCE" in conflict["prerequisite_keys"]
    assert "question:Q-004:INVESTIGATE" not in conflict["prerequisite_keys"]


def test_phase5_action_work_consumes_phase4_constraint_plan(project_root):
    result = _derive(project_root)
    prepare = next(task for task in result["tasks"] if task["task_type"] == "PREPARE_ACTION")
    assert {"ACT-ROLLBACK-MIG203", "ACT-VERIFY-ROLLBACK", "ACT-RESTORE-CHECKOUT"} <= set(prepare["addresses"])
    assert any("REQUIRES" in path for path in prepare["graph_paths"])
    policies = {task["addresses"][0] for task in result["tasks"] if task["task_type"] == "VALIDATE_POLICY"}
    assert {"POL-DB-04", "POL-RECOVERY-01"} <= policies
    # The selected rollback already has approval in Phase 4 truth, so duplicate approval work is not generated.
    assert not any(task["task_type"] == "REQUEST_APPROVAL" for task in result["tasks"])


def test_phase5_plan_and_task_ids_are_deterministic(project_root):
    first = _derive(project_root)
    second = _derive(project_root)
    service = _service(project_root)
    assert first["plan_id"] == second["plan_id"]
    first_ids = [service._task_id(first["plan_id"], task["semantic_key"]) for task in first["tasks"]]
    second_ids = [service._task_id(second["plan_id"], task["semantic_key"]) for task in second["tasks"]]
    assert first_ids == second_ids
    assert len(first_ids) == len(set(first_ids))


def test_phase5_task_graph_is_acyclic(project_root):
    result = _derive(project_root)
    order = WorkPlanningService._topological_order(result["tasks"])
    assert len(order) == len(result["tasks"])
    positions = {key: index for index, key in enumerate(order)}
    for task in result["tasks"]:
        for prerequisite in task["prerequisite_keys"]:
            assert positions[prerequisite] < positions[task["semantic_key"]]


def test_phase5_cycle_is_rejected_without_weakening_dependency_semantics():
    tasks = [
        {"semantic_key": "a", "prerequisite_keys": ["b"]},
        {"semantic_key": "b", "prerequisite_keys": ["a"]},
    ]
    with pytest.raises(ValueError, match="cycle"):
        WorkPlanningService._topological_order(tasks)


def test_phase5_dedup_merges_same_semantic_work():
    base = {
        "semantic_key": "question:Q-001:ACQUIRE_EVIDENCE",
        "task_type": "ACQUIRE_EVIDENCE",
        "priority": "P0",
        "addresses": ["Q-001"],
        "about": ["INC-001"],
        "requires_entities": [],
        "prerequisite_keys": [],
        "routing_targets": [],
        "derived_from": ["Q-001"],
        "graph_paths": [],
    }
    other = {**base, "about": ["MIG-203"], "graph_paths": ["Q-001-[:ABOUT]->MIG-203"]}
    result = WorkPlanningService._dedupe_blueprints([dict(base), dict(other)])
    assert len(result) == 1
    assert set(result[0]["about"]) == {"INC-001", "MIG-203"}


def test_phase5_expertise_requirement_prefers_explicit_expert_role():
    expert = {"roles": ["DOMAIN_EXPERT"], "score": 78.4}
    owner = {"roles": ["FORMAL_OWNER"], "score": 95.0}
    assert WorkPlanningService._task_specific_score(expert, "EXPERTISE") > WorkPlanningService._task_specific_score(owner, "EXPERTISE")


def test_phase5_authority_requirement_preserves_owner_vs_expert_distinction():
    expert = {"roles": ["DOMAIN_EXPERT"], "score": 78.4}
    owner = {"roles": ["FORMAL_OWNER"], "score": 95.0}
    assert WorkPlanningService._task_specific_score(owner, "AUTHORITY") > WorkPlanningService._task_specific_score(expert, "AUTHORITY")


def test_phase5_selected_claim_filter_does_not_invent_conflict(project_root):
    result = _derive(project_root, selected_claims=["C-001"])
    assert not any(task["task_type"] == "RESOLVE_CONFLICT" for task in result["tasks"])


def test_phase5_historical_planning_excludes_future_questions_claims_and_actions(project_root):
    result = _derive(project_root, as_of="2026-10-16T14:09:00+05:30")
    # At 14:09 the Q-001..Q-004 gaps, C-001/C-002 conflict and Phase 4 remediation actions did not yet exist.
    assert result["tasks"] == []


def test_phase5_blueprints_explain_why_each_task_exists(project_root):
    result = _derive(project_root)
    assert all(task["reason"] for task in result["tasks"])
    assert all(task["derived_from"] for task in result["tasks"])
    assert all(isinstance(task["graph_paths"], list) for task in result["tasks"])


def test_phase5_api_routes_exist_and_no_execution_routes_are_added():
    paths = {route.path for route in app.routes}
    required = {
        "/plans",
        "/plans/{plan_id}",
        "/plans/{plan_id}/tasks",
        "/plans/{plan_id}/ready-tasks",
        "/plans/{plan_id}/validate",
        "/plans/{plan_id}/recompute",
        "/tasks/{task_id}",
        "/tasks/{task_id}/candidate-assignees",
        "/tasks/{task_id}/prerequisites",
        "/tasks/{task_id}/completion-status",
    }
    assert required <= paths
    forbidden_tokens = {"claim-task", "execute-task", "handoff", "blackboard", "langgraph"}
    assert not any(any(token in path.lower() for token in forbidden_tokens) for path in paths)
    assert all("cypher" not in path.lower() for path in paths)


def test_phase5_ready_task_requires_completed_task_predecessor(project_root):
    from backend.app.services.phase4_graph import GraphEdge, GraphSnapshot

    service = _service(project_root)
    nodes = {
        "PLAN-X": {"id": "PLAN-X", "_labels": ["Entity", "Plan"], "status": "READY"},
        "T-A": {"id": "T-A", "_labels": ["Entity", "Task"], "status": "OPEN", "priority": "P0"},
        "T-B": {"id": "T-B", "_labels": ["Entity", "Task"], "status": "OPEN", "priority": "P0"},
    }
    edges = [
        GraphEdge("PLAN-X", "PLAN_HAS_TASK", "T-A", {}),
        GraphEdge("PLAN-X", "PLAN_HAS_TASK", "T-B", {}),
        GraphEdge("T-B", "REQUIRES", "T-A", {"required": True}),
    ]
    snapshot = GraphSnapshot(nodes, edges)
    states = {x["task"]["id"]: x for x in [service._task_readiness(snapshot, "T-A"), service._task_readiness(snapshot, "T-B")]}
    assert states["T-A"]["ready"] is True
    assert states["T-B"]["ready"] is False
    nodes["T-A"]["status"] = "COMPLETED"
    snapshot = GraphSnapshot(nodes, edges)
    assert service._task_readiness(snapshot, "T-B")["ready"] is True


def test_phase5_validation_detects_malformed_task(project_root):
    from backend.app.services.phase4_graph import GraphEdge, GraphSnapshot

    service = _service(project_root)
    nodes = {
        "PLAN-X": {"id": "PLAN-X", "_labels": ["Entity", "Plan"], "status": "DRAFT"},
        "T-X": {
            "id": "T-X",
            "_labels": ["Entity", "Task"],
            "status": "OPEN",
            "task_type": "INVESTIGATE",
            "expected_output_type": "INVESTIGATION_RESULT",
            "assignee_requirement": "EXPERTISE",
        },
    }
    snapshot = GraphSnapshot(nodes, [GraphEdge("PLAN-X", "PLAN_HAS_TASK", "T-X", {})])
    result = service._validate_plan_snapshot(snapshot, "PLAN-X")
    codes = {item["code"] for item in result["errors"]}
    assert "MISSING_COMPLETION_CONDITION" in codes
    assert "UNRESOLVABLE_ASSIGNEE_REQUIREMENT" in codes
    assert result["valid"] is False


def test_phase5_historical_cutoff_changes_plan_identity(project_root):
    service = _service(project_root)
    current = service.derive_plan("INC-001", "Resolve safely")
    historical = service.derive_plan("INC-001", "Resolve safely", as_of="2026-10-16T14:09:00+05:30")
    assert current["plan_id"] != historical["plan_id"]


def test_phase5_explicit_selection_changes_plan_identity(project_root):
    service = _service(project_root)
    default = service.derive_plan("INC-001", "Resolve safely")
    scoped = service.derive_plan("INC-001", "Resolve safely", selected_claims=["C-001"])
    same_scoped = service.derive_plan("INC-001", "Resolve safely", selected_claims=["C-001"])
    assert default["plan_id"] != scoped["plan_id"]
    assert scoped["plan_id"] == same_scoped["plan_id"]


def test_phase5_task_reuse_signature_changes_when_prerequisite_structure_changes():
    base = {
        "task_type": "RESOLVE_CONFLICT",
        "objective": "Resolve conflict",
        "expected_output_type": "CLAIM_STATUS",
        "assignee_requirement": "EXPERTISE",
        "addresses": ["C-001", "C-002"],
        "about": ["INC-001"],
        "requires_entities": [],
        "prerequisite_keys": ["question:Q-001:ACQUIRE_EVIDENCE"],
    }
    changed = {**base, "prerequisite_keys": ["question:Q-001:ACQUIRE_EVIDENCE", "question:Q-003:ACQUIRE_EVIDENCE"]}
    assert WorkPlanningService._blueprint_signature(base) != WorkPlanningService._blueprint_signature(changed)


def test_phase5_historical_planning_excludes_future_action_and_policy_edges(project_root):
    result = _derive(project_root, as_of="2026-10-16T14:15:59+05:30")
    types = {task["task_type"] for task in result["tasks"]}
    assert "RESOLVE_CONFLICT" in types
    assert "PREPARE_ACTION" not in types
    assert "VALIDATE_POLICY" not in types
    assert "REQUEST_APPROVAL" not in types


def test_phase5_explicit_constraint_reference_is_graph_backed_and_changes_plan_identity(project_root):
    unconstrained = _derive(project_root)
    constrained = _derive(project_root, constraints=["POL-DB-04"])
    assert constrained["explicit_constraint_refs"] == ["POL-DB-04"]
    assert constrained["plan_id"] != unconstrained["plan_id"]
    assert constrained["selection_fingerprint"] != unconstrained["selection_fingerprint"]


def test_phase5_unknown_explicit_constraint_reference_is_rejected(project_root):
    with pytest.raises(ValueError, match="Unknown or temporally inactive constraint reference"):
        _derive(project_root, constraints=["POL-DOES-NOT-EXIST"])


def test_phase5_historical_planning_does_not_use_future_tool_routes(project_root):
    client = FixtureGraphClient(project_root)
    for edge in client.edges:
        if edge["source"] == "Q-001" and edge["type"] == "REQUIRES":
            edge.setdefault("properties", {})["valid_from"] = "2026-10-16T14:20:00+05:30"
    result = WorkPlanningService(client).derive_plan(
        "INC-001",
        "Resolve INC-001 from the 14:15:59 knowledge state.",
        as_of="2026-10-16T14:15:59+05:30",
    )
    q1 = next(task for task in result["tasks"] if "Q-001" in task.get("addresses", []))
    assert q1["task_type"] == "ACQUIRE_EVIDENCE"
    assert "TOOL-DEPLOY-LOOKUP" not in q1["requires_entities"]
    assert "TOOL-GIT-LOOKUP" not in q1["requires_entities"]


def test_phase5_historical_claim_supersession_uses_edge_time_not_current_materialized_status(project_root):
    client = FixtureGraphClient(project_root)
    client.nodes["C-001"]["status"] = "SUPERSEDED"
    client.nodes["C-P5-SUPERSEDER"] = {
        "id": "C-P5-SUPERSEDER",
        "tenant_id": "northstar",
        "statement": "Replacement root-cause claim",
        "status": "OPEN",
        "created_at": "2026-10-16T14:20:00+05:30",
        "_labels": ["Entity", "Claim"],
    }
    client.edges.append({
        "source": "C-P5-SUPERSEDER",
        "type": "SUPERSEDES",
        "target": "C-001",
        "properties": {"valid_from": "2026-10-16T14:20:00+05:30", "confidence": 1.0},
    })
    service = WorkPlanningService(client)
    current = service.derive_plan("INC-001", "Resolve current INC-001 safely.")
    historical = service.derive_plan(
        "INC-001",
        "Resolve historical INC-001 safely.",
        as_of="2026-10-16T14:15:59+05:30",
    )
    assert not any(task["task_type"] == "RESOLVE_CONFLICT" for task in current["tasks"])
    assert any(set(task["addresses"]) == {"C-001", "C-002"} for task in historical["tasks"] if task["task_type"] == "RESOLVE_CONFLICT")
