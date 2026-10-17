from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from typing import Any, Iterable

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import delete_relationship, upsert_node, upsert_relationship
from backend.app.graph.temporal import to_epoch_us
from backend.app.services.authority_resolution_service import AuthorityResolutionService
from backend.app.services.evidence_acquisition_service import EvidenceAcquisitionService
from backend.app.services.knowledge_gap_service import KnowledgeGapService
from backend.app.services.phase3_utils import now_iso
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.planning_service import ConstraintPlanningService
from backend.app.services.routing_service import ResponsibilityRoutingService


PLANNER_ID = "AGENT-DETERMINISTIC-PLANNER"
PLANNER_VERSION = "phase5-deterministic-v1"
ACTIVE_TASK_STATUSES = {"OPEN", "READY", "BLOCKED", "IN_PROGRESS", "DRAFT"}
DONE_TASK_STATUSES = {"COMPLETED", "DONE", "RESOLVED", "CLOSED"}
TERMINAL_TASK_STATUSES = DONE_TASK_STATUSES | {"CANCELLED", "SUPERSEDED", "FAILED"}
TASK_TYPES = {
    "INVESTIGATE",
    "ACQUIRE_EVIDENCE",
    "VERIFY_CLAIM",
    "RESOLVE_CONFLICT",
    "PREPARE_ACTION",
    "VALIDATE_POLICY",
    "REQUEST_APPROVAL",
    "VALIDATE_OUTCOME",
}


def _norm_goal(goal: str) -> str:
    return " ".join(goal.strip().lower().split())


def _stable_id(prefix: str, *parts: str, length: int = 12) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:length].upper()
    return f"{prefix}{digest}"


def _node_visible(node: dict[str, Any] | None, as_of: str | None) -> bool:
    if not node:
        return False
    # Without an explicit historical cutoff the canonical graph represents current truth.
    if as_of is None:
        return True
    point = to_epoch_us(as_of)
    for field in ("created_at", "observed_at", "occurred_at", "valid_from"):
        value = node.get(field)
        if value is not None and to_epoch_us(value) > point:
            return False
    valid_until = node.get("valid_until")
    if valid_until is not None and to_epoch_us(valid_until) <= point:
        return False
    return True


def _priority_rank(priority: str | None) -> int:
    return {"P0": 0, "HIGH": 0, "P1": 1, "MEDIUM": 1, "P2": 2, "LOW": 2, "P3": 3}.get(
        str(priority or "P2").upper(), 2
    )


class WorkPlanningService:
    """Phase 5 deterministic planner that turns existing graph reasoning into durable work.

    FalkorDB is the canonical plan/task store. The service deliberately does not execute tasks,
    claim work, coordinate agents, or call external systems.
    """

    def __init__(self, client: FalkorGraphClient):
        self.client = client

    # ---------- deterministic derivation ----------
    def _plan_id(
        self,
        situation_id: str,
        goal: str,
        as_of: str | None = None,
        *,
        selection_fingerprint: str = "DEFAULT",
    ) -> str:
        # Historical cutoffs and explicit planning selections define distinct deterministic views.
        # Repeating the same request against unchanged graph state reuses this identity.
        return _stable_id(
            "PLAN-P5-",
            self.client.settings.tenant_id,
            situation_id,
            _norm_goal(goal),
            str(as_of or "CURRENT"),
            selection_fingerprint,
        )

    @staticmethod
    def _selection_fingerprint(
        selected_hypotheses: list[str] | None,
        selected_claims: list[str] | None,
        knowledge_gaps: list[str] | None,
        constraints: list[str] | None,
    ) -> str:
        groups = (
            ("hypotheses", selected_hypotheses or []),
            ("claims", selected_claims or []),
            ("gaps", knowledge_gaps or []),
            ("constraints", constraints or []),
        )
        normalized = [
            f"{name}={','.join(sorted({str(value) for value in values if str(value).strip()}))}"
            for name, values in groups
        ]
        if all(item.endswith("=") for item in normalized):
            return "DEFAULT"
        return hashlib.sha256("|".join(normalized).encode("utf-8")).hexdigest()[:16].upper()

    @staticmethod
    def _csv(values: list[str] | None) -> str:
        return ",".join(sorted({str(value) for value in (values or []) if str(value).strip()}))

    @staticmethod
    def _from_csv(value: Any) -> list[str]:
        return [item for item in str(value or "").split(",") if item]

    @staticmethod
    def _blueprint_signature(blueprint: dict[str, Any]) -> str:
        """Structural identity used only to decide whether work is genuinely reusable."""
        parts = [
            str(blueprint.get("task_type") or ""),
            _norm_goal(str(blueprint.get("objective") or "")),
            str(blueprint.get("expected_output_type") or ""),
            str(blueprint.get("assignee_requirement") or ""),
            ",".join(sorted(str(x) for x in (blueprint.get("addresses") or []))),
            ",".join(sorted(str(x) for x in (blueprint.get("about") or []))),
            ",".join(sorted(str(x) for x in (blueprint.get("requires_entities") or []))),
            ",".join(sorted(str(x) for x in (blueprint.get("prerequisite_keys") or []))),
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20].upper()

    @staticmethod
    def _task_id(plan_id: str, semantic_key: str) -> str:
        return _stable_id("TASK-P5-", plan_id, semantic_key)

    @staticmethod
    def _question_specific_targets(snapshot: GraphSnapshot, question_id: str, *, as_of: str | None) -> list[str]:
        targets = []
        for edge in snapshot.edges_from(question_id, {"ABOUT"}, as_of=as_of):
            node = snapshot.node(edge.target)
            if node and not has_label(node, "Incident"):
                targets.append(edge.target)
        return sorted(set(targets))

    @staticmethod
    def _claim_context_targets(snapshot: GraphSnapshot, claim_ids: Iterable[str], *, as_of: str | None) -> set[str]:
        targets: set[str] = set()
        claim_ids = set(claim_ids)
        for claim_id in claim_ids:
            for about in snapshot.edges_from(claim_id, {"ABOUT"}, as_of=as_of):
                if not has_label(snapshot.node(about.target), "Incident"):
                    targets.add(about.target)
            for evidence_edge in snapshot.edges_to(claim_id, {"SUPPORTS", "REFUTES"}, as_of=as_of):
                if not has_label(snapshot.node(evidence_edge.source), "Evidence"):
                    continue
                for about in snapshot.edges_from(evidence_edge.source, {"ABOUT"}, as_of=as_of):
                    if not has_label(snapshot.node(about.target), "Incident"):
                        targets.add(about.target)
        return targets

    def _question_task_type(self, question_id: str, *, as_of: str | None = None) -> tuple[str, str, str]:
        routing = EvidenceAcquisitionService(self.client).route_question(question_id, as_of=as_of)
        route_capabilities = " ".join(
            str(route.get("capability") or "") for route in (routing or {}).get("routes", [])
        ).lower()
        if any(token in route_capabilities for token in ("dependency", "ownership", "catalog")):
            return "INVESTIGATE", "INVESTIGATION_RESULT", "EXPERTISE"
        return "ACQUIRE_EVIDENCE", "EVIDENCE", "TOOL_ACCESS"

    def _question_blueprints(
        self,
        snapshot: GraphSnapshot,
        situation_id: str,
        knowledge: dict[str, Any],
        *,
        as_of: str | None,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for gap in knowledge.get("gaps", []):
            if gap.get("kind") != "QUESTION_GAP":
                continue
            question = gap.get("question") or {}
            qid = str(question.get("id") or "")
            if not qid or not _node_visible(question, as_of):
                continue
            task_type, output_type, requirement = self._question_task_type(qid, as_of=as_of)
            targets = self._question_specific_targets(snapshot, qid, as_of=as_of)
            route = EvidenceAcquisitionService(self.client).route_question(qid, as_of=as_of) or {}
            tool_requirements = sorted(
                {
                    str((item.get("tool") or item.get("data_source") or {}).get("id"))
                    for item in route.get("routes", [])
                    if (item.get("tool") or item.get("data_source") or {}).get("id")
                }
            )
            semantic_key = f"question:{qid}:{task_type}"
            result.append(
                {
                    "semantic_key": semantic_key,
                    "task_type": task_type,
                    "title": (
                        f"Acquire evidence for {qid}"
                        if task_type == "ACQUIRE_EVIDENCE"
                        else f"Investigate {qid}"
                    ),
                    "objective": str(question.get("text") or f"Resolve {qid}"),
                    "priority": "P0" if str(question.get("priority") or "").upper() == "HIGH" else "P1",
                    "expected_output_type": output_type,
                    "completion_condition": (
                        f"Question {qid} has authoritative Evidence linked by RESOLVED_BY"
                        if task_type == "ACQUIRE_EVIDENCE"
                        else f"Question {qid} has a graph-backed investigation result or resolving evidence"
                    ),
                    "addresses": [qid],
                    "about": [situation_id, *targets],
                    "requires_entities": tool_requirements,
                    "prerequisite_keys": [],
                    "assignee_requirement": requirement,
                    "routing_targets": targets,
                    "reason": f"{qid} is unresolved: {', '.join(gap.get('reason_codes') or [])}",
                    "derived_from": [qid, *targets],
                    "graph_paths": [
                        f"{qid}-[:ABOUT]->{target}" for target in targets
                    ] + [
                        step
                        for route_item in route.get("routes", [])
                        for step in route_item.get("path", [])
                    ],
                }
            )
        return result


    @staticmethod
    def _claim_available(snapshot: GraphSnapshot, claim_id: str, *, as_of: str | None) -> bool:
        claim = snapshot.node(claim_id)
        if not claim or not _node_visible(claim, as_of):
            return False
        status = str(claim.get("status") or "OPEN").upper()
        if status == "REJECTED":
            return False
        if snapshot.edges_to(claim_id, {"SUPERSEDES"}, as_of=as_of):
            return False
        if as_of is None and status == "SUPERSEDED":
            return False
        return True

    def _claim_verification_blueprints(
        self,
        snapshot: GraphSnapshot,
        situation_id: str,
        knowledge: dict[str, Any],
        *,
        as_of: str | None,
        selected_claims: set[str] | None,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for gap in knowledge.get("gaps", []):
            if gap.get("kind") != "UNSUPPORTED_CLAIM":
                continue
            claim = gap.get("claim") or {}
            claim_id = str(claim.get("id") or "")
            if not claim_id or not self._claim_available(snapshot, claim_id, as_of=as_of):
                continue
            if selected_claims and claim_id not in selected_claims:
                continue
            targets = sorted(self._claim_context_targets(snapshot, [claim_id], as_of=as_of))
            result.append(
                {
                    "semantic_key": f"verify-claim:{claim_id}",
                    "task_type": "VERIFY_CLAIM",
                    "title": f"Verify claim {claim_id}",
                    "objective": str(claim.get("statement") or f"Verify {claim_id}"),
                    "priority": "P1",
                    "expected_output_type": "CLAIM_STATUS",
                    "completion_condition": f"{claim_id} has supporting or refuting Evidence with provenance.",
                    "addresses": [claim_id],
                    "about": [situation_id, *targets],
                    "requires_entities": [],
                    "prerequisite_keys": [],
                    "assignee_requirement": "EXPERTISE",
                    "routing_targets": targets,
                    "reason": f"{claim_id} is active but lacks expected supporting evidence.",
                    "derived_from": [claim_id],
                    "graph_paths": [f"{claim_id}-[:ABOUT]->{situation_id}"],
                }
            )
        return result

    def _conflict_blueprints(
        self,
        snapshot: GraphSnapshot,
        situation_id: str,
        question_tasks: list[dict[str, Any]],
        *,
        as_of: str | None,
        selected_claims: set[str] | None,
    ) -> list[dict[str, Any]]:
        claims = {
            edge.source
            for edge in snapshot.edges_to(situation_id, {"ABOUT"}, as_of=as_of)
            if has_label(snapshot.node(edge.source), "Claim") and self._claim_available(snapshot, edge.source, as_of=as_of)
        }
        if selected_claims:
            claims &= selected_claims
        pairs: set[tuple[str, str]] = set()
        for cid in sorted(claims):
            for edge in snapshot.edges_from(cid, {"CONTRADICTS"}, as_of=as_of):
                if edge.target in claims:
                    pairs.add(tuple(sorted((cid, edge.target))))
            for edge in snapshot.edges_to(cid, {"CONTRADICTS"}, as_of=as_of):
                if edge.source in claims:
                    pairs.add(tuple(sorted((cid, edge.source))))

        result = []
        for left, right in sorted(pairs):
            context = self._claim_context_targets(snapshot, (left, right), as_of=as_of)
            prereqs = []
            for task in question_tasks:
                targets = set(task.get("routing_targets") or [])
                if context & targets:
                    prereqs.append(task["semantic_key"])
            result.append(
                {
                    "semantic_key": f"conflict:{left}:{right}",
                    "task_type": "RESOLVE_CONFLICT",
                    "title": f"Resolve contradiction {left} vs {right}",
                    "objective": f"Resolve the explicit contradiction between {left} and {right} using authority, evidence and temporal rules.",
                    "priority": "P0",
                    "expected_output_type": "CLAIM_STATUS",
                    "completion_condition": "Authority resolver returns RESOLVED, or an explicit UNRESOLVED result documents remaining evidence gaps.",
                    "addresses": [left, right],
                    "about": [situation_id, *sorted(context)],
                    "requires_entities": [],
                    "prerequisite_keys": sorted(set(prereqs)),
                    "assignee_requirement": "EXPERTISE",
                    "routing_targets": sorted(context),
                    "reason": f"{left} and {right} are connected by CONTRADICTS.",
                    "derived_from": [left, right],
                    "graph_paths": [f"{left}-[:CONTRADICTS]->{right}"],
                }
            )
        return result

    def _selected_actions(
        self, snapshot: GraphSnapshot, situation_id: str, *, as_of: str | None
    ) -> tuple[list[str], dict[str, Any]]:
        plan = ConstraintPlanningService(self.client).plan_for_incident(situation_id, as_of=as_of) or {}
        actions = []
        for step in plan.get("steps", []):
            action = step.get("action") or {}
            aid = str(action.get("id") or "")
            if aid and _node_visible(action, as_of):
                actions.append(aid)
        return actions, plan

    @staticmethod
    def _specific_action_targets(snapshot: GraphSnapshot, action_id: str, *, as_of: str | None) -> list[str]:
        targets: set[str] = set()
        for edge in snapshot.edges_from(action_id, {"ABOUT"}, as_of=as_of):
            node = snapshot.node(edge.target)
            if node and not has_label(node, "Incident") and not has_label(node, "Decision"):
                targets.add(edge.target)
                if has_label(node, "Change"):
                    for changed in snapshot.edges_from(edge.target, {"CHANGED", "AFFECTS"}, as_of=as_of):
                        if has_label(snapshot.node(changed.target), "System"):
                            targets.add(changed.target)
        return sorted(targets)

    def _action_and_policy_blueprints(
        self,
        snapshot: GraphSnapshot,
        situation_id: str,
        prior_tasks: list[dict[str, Any]],
        *,
        as_of: str | None,
    ) -> list[dict[str, Any]]:
        action_ids, phase4_plan = self._selected_actions(snapshot, situation_id, as_of=as_of)
        if not action_ids:
            return []
        conflict_keys = [t["semantic_key"] for t in prior_tasks if t["task_type"] == "RESOLVE_CONFLICT"]
        question_keys = [t["semantic_key"] for t in prior_tasks if t["task_type"] in {"ACQUIRE_EVIDENCE", "INVESTIGATE"}]
        prepare_key = "prepare:selected-remediation"
        routing_targets = sorted(
            {
                target
                for aid in action_ids
                for target in self._specific_action_targets(snapshot, aid, as_of=as_of)
            }
        )
        tasks = [
            {
                "semantic_key": prepare_key,
                "task_type": "PREPARE_ACTION",
                "title": "Prepare graph-backed remediation proposal",
                "objective": "Turn the selected Phase 4 action sequence into an implementation-ready remediation proposal without executing it.",
                "priority": "P0",
                "expected_output_type": "ACTION_PROPOSAL",
                "completion_condition": "A selected Action proposal exists with its prerequisites, constraints and target entities represented.",
                "addresses": action_ids,
                "about": [situation_id, *routing_targets],
                "requires_entities": [],
                "prerequisite_keys": sorted(set(conflict_keys or question_keys)),
                "assignee_requirement": "AUTHORITY",
                "routing_targets": routing_targets,
                "reason": "Phase 4 produced selected remediation Actions that must be converted into structured work.",
                "derived_from": action_ids,
                "graph_paths": list(phase4_plan.get("constraint_paths") or []),
            }
        ]

        policies: set[str] = set()
        governed_targets = set(action_ids) | set(routing_targets)
        for target in governed_targets:
            for edge in snapshot.edges_to(target, {"GOVERNS"}, as_of=as_of):
                if has_label(snapshot.node(edge.source), "Policy") and _node_visible(snapshot.node(edge.source), as_of):
                    policies.add(edge.source)
        for policy_id in sorted(policies):
            policy_targets = [
                edge.target for edge in snapshot.edges_from(policy_id, {"GOVERNS"}, as_of=as_of)
                if edge.target in governed_targets
            ]
            tasks.append(
                {
                    "semantic_key": f"policy:{policy_id}",
                    "task_type": "VALIDATE_POLICY",
                    "title": f"Validate {policy_id} requirements",
                    "objective": f"Verify the remediation proposal satisfies authoritative policy {policy_id}.",
                    "priority": "P0",
                    "expected_output_type": "VALIDATION_RESULT",
                    "completion_condition": f"All active REQUIRES constraints of {policy_id} relevant to the remediation are represented and evaluated.",
                    "addresses": [policy_id],
                    "about": [situation_id, *policy_targets],
                    "requires_entities": [],
                    "prerequisite_keys": [prepare_key],
                    "assignee_requirement": "AUTHORITY",
                    "routing_targets": routing_targets or policy_targets,
                    "reason": f"{policy_id} governs a selected action or its target.",
                    "derived_from": [policy_id, *policy_targets],
                    "graph_paths": [f"{policy_id}-[:GOVERNS]->{target}" for target in policy_targets],
                }
            )

        approval_keys = [t["semantic_key"] for t in tasks if t["task_type"] == "VALIDATE_POLICY"] or [prepare_key]
        for action_id in action_ids:
            action = snapshot.node(action_id) or {}
            if not action.get("approval_required"):
                continue
            approvals = snapshot.edges_from(action_id, {"APPROVED_BY"}, as_of=as_of)
            if approvals:
                continue
            action_targets = self._specific_action_targets(snapshot, action_id, as_of=as_of)
            tasks.append(
                {
                    "semantic_key": f"approval:{action_id}",
                    "task_type": "REQUEST_APPROVAL",
                    "title": f"Request approval for {action_id}",
                    "objective": f"Obtain the approval required before {action_id} may be executed.",
                    "priority": "P0",
                    "expected_output_type": "APPROVAL",
                    "completion_condition": f"{action_id} has a current APPROVED_BY relationship from an authorized actor.",
                    "addresses": [action_id],
                    "about": [situation_id, *action_targets],
                    "requires_entities": [],
                    "prerequisite_keys": list(approval_keys),
                    "assignee_requirement": "APPROVAL",
                    "routing_targets": action_targets,
                    "reason": f"{action_id} has approval_required=true and no current APPROVED_BY relationship.",
                    "derived_from": [action_id],
                    "graph_paths": [f"{action_id}.approval_required=true"],
                }
            )
        return tasks

    @staticmethod
    def _dedupe_blueprints(blueprints: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key: dict[str, dict[str, Any]] = {}
        for item in blueprints:
            if item["task_type"] not in TASK_TYPES:
                raise ValueError(f"Unsupported task type: {item['task_type']}")
            prior = by_key.get(item["semantic_key"])
            if prior is None:
                by_key[item["semantic_key"]] = item
                continue
            # Same semantic work merges derivation facts instead of creating a duplicate task.
            for field in ("addresses", "about", "requires_entities", "prerequisite_keys", "routing_targets", "derived_from", "graph_paths"):
                prior[field] = sorted(set(prior.get(field, [])) | set(item.get(field, [])))
        return sorted(by_key.values(), key=lambda t: (_priority_rank(t.get("priority")), t["task_type"], t["semantic_key"]))

    @staticmethod
    def _topological_order(blueprints: list[dict[str, Any]]) -> list[str]:
        keys = {item["semantic_key"] for item in blueprints}
        indegree = {key: 0 for key in keys}
        outgoing: dict[str, list[str]] = defaultdict(list)
        for item in blueprints:
            dependent = item["semantic_key"]
            for prereq in item.get("prerequisite_keys", []):
                if prereq not in keys:
                    raise ValueError(f"Task {dependent} references missing prerequisite {prereq}")
                outgoing[prereq].append(dependent)
                indegree[dependent] += 1
        queue = deque(sorted(k for k, degree in indegree.items() if degree == 0))
        order: list[str] = []
        while queue:
            key = queue.popleft()
            order.append(key)
            for nxt in sorted(outgoing.get(key, [])):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
        if len(order) != len(keys):
            raise ValueError("Generated task graph contains a cycle")
        return order

    def derive_plan(
        self,
        situation_id: str,
        goal: str,
        *,
        selected_hypotheses: list[str] | None = None,
        selected_claims: list[str] | None = None,
        knowledge_gaps: list[str] | None = None,
        constraints: list[str] | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        situation = snapshot.node(situation_id)
        if situation is None or not has_label(situation, "Incident") or not _node_visible(situation, as_of):
            return None
        if not goal.strip():
            raise ValueError("goal must not be empty")

        knowledge = KnowledgeGapService(self.client).detect_for_incident(situation_id, as_of=as_of) or {"gaps": []}
        if knowledge_gaps:
            selected_gap_ids = set(knowledge_gaps)
            knowledge = {
                **knowledge,
                "gaps": [
                    gap for gap in knowledge.get("gaps", [])
                    if str((gap.get("question") or gap.get("claim") or gap.get("entity") or {}).get("id")) in selected_gap_ids
                ],
            }

        selected_claim_set = set(selected_claims or []) or None
        question_tasks = self._question_blueprints(snapshot, situation_id, knowledge, as_of=as_of)
        claim_tasks = self._claim_verification_blueprints(
            snapshot, situation_id, knowledge, as_of=as_of, selected_claims=selected_claim_set
        )
        conflict_tasks = self._conflict_blueprints(
            snapshot,
            situation_id,
            question_tasks,
            as_of=as_of,
            selected_claims=selected_claim_set,
        )
        # Explicit verification work for a conflicting claim is also a prerequisite for resolving that conflict.
        claim_task_by_id = {
            task["addresses"][0]: task["semantic_key"]
            for task in claim_tasks
            if task.get("addresses")
        }
        for task in conflict_tasks:
            for claim_id in task.get("addresses", []):
                if claim_id in claim_task_by_id:
                    task["prerequisite_keys"].append(claim_task_by_id[claim_id])
            task["prerequisite_keys"] = sorted(set(task["prerequisite_keys"]))
        base = question_tasks + claim_tasks + conflict_tasks
        action_tasks = self._action_and_policy_blueprints(snapshot, situation_id, base, as_of=as_of)
        blueprints = self._dedupe_blueprints(base + action_tasks)

        # Optional explicit hypotheses become investigation tasks only when the caller selected them.
        for hypothesis_id in selected_hypotheses or []:
            node = snapshot.node(hypothesis_id)
            if not node or not has_label(node, "Hypothesis") or not _node_visible(node, as_of):
                continue
            blueprints.append(
                {
                    "semantic_key": f"hypothesis:{hypothesis_id}",
                    "task_type": "INVESTIGATE",
                    "title": f"Investigate {hypothesis_id}",
                    "objective": str(node.get("statement") or f"Investigate {hypothesis_id}"),
                    "priority": "P1",
                    "expected_output_type": "INVESTIGATION_RESULT",
                    "completion_condition": f"{hypothesis_id} is supported, rejected, or superseded by graph-backed evidence.",
                    "addresses": [hypothesis_id],
                    "about": [situation_id],
                    "requires_entities": [],
                    "prerequisite_keys": [],
                    "assignee_requirement": "EXPERTISE",
                    "routing_targets": [],
                    "reason": "Caller selected this active hypothesis for planning.",
                    "derived_from": [hypothesis_id],
                    "graph_paths": [f"selected_hypothesis:{hypothesis_id}"],
                }
            )
        blueprints = self._dedupe_blueprints(blueprints)
        order = self._topological_order(blueprints)
        by_key = {item["semantic_key"]: item for item in blueprints}
        ordered = [by_key[key] for key in order]

        explicit_constraints = list(dict.fromkeys(str(x) for x in (constraints or []) if str(x).strip()))
        for constraint_id in explicit_constraints:
            constraint = snapshot.node(constraint_id)
            if constraint is None or not _node_visible(constraint, as_of):
                raise ValueError(
                    f"Unknown or temporally inactive constraint reference: {constraint_id}. "
                    "Phase 5 constraint inputs must reference canonical FalkorDB entities."
                )

        selection_fingerprint = self._selection_fingerprint(
            selected_hypotheses,
            selected_claims,
            knowledge_gaps,
            constraints,
        )
        return {
            "plan_id": self._plan_id(
                situation_id,
                goal,
                as_of,
                selection_fingerprint=selection_fingerprint,
            ),
            "situation": situation,
            "situation_id": situation_id,
            "goal": goal.strip(),
            "as_of": as_of,
            "planner_version": PLANNER_VERSION,
            "selection_fingerprint": selection_fingerprint,
            "selected_hypotheses": selected_hypotheses or [],
            "selected_claims": selected_claims or [],
            "selected_knowledge_gaps": knowledge_gaps or [],
            "tasks": ordered,
            "explicit_constraint_refs": explicit_constraints,
            "reasoning_inputs": {
                "knowledge_gap_count": len(knowledge.get("gaps", [])),
                "selected_claims": selected_claims or [],
                "selected_hypotheses": selected_hypotheses or [],
            },
            "graph_required": True,
        }

    # ---------- candidate workers ----------
    @staticmethod
    def _task_specific_score(candidate: dict[str, Any], requirement: str) -> float:
        roles = set(candidate.get("roles") or [])
        existing = min(float(candidate.get("score") or 0.0), 100.0)
        weights = {
            "EXPERTISE": {
                "DOMAIN_EXPERT": 100.0,
                "RESPONSIBLE_ACTOR": 72.0,
                "FORMAL_OWNER": 65.0,
                "OWNER_TEAM_MEMBER": 50.0,
                "HISTORICAL_EXPERT": 35.0,
                "HISTORICAL_EXPERIENCE": 25.0,
                "BACKUP_CANDIDATE": 15.0,
                "APPROVER": 10.0,
            },
            "AUTHORITY": {
                "FORMAL_OWNER": 100.0,
                "RESPONSIBLE_ACTOR": 95.0,
                "APPROVER": 80.0,
                "DOMAIN_EXPERT": 45.0,
                "OWNER_TEAM_MEMBER": 40.0,
                "BACKUP_CANDIDATE": 20.0,
            },
            "APPROVAL": {
                "APPROVER": 100.0,
                "RESPONSIBLE_ACTOR": 85.0,
                "FORMAL_OWNER": 80.0,
                "DOMAIN_EXPERT": 35.0,
            },
            "TOOL_ACCESS": {
                "RESPONSIBLE_ACTOR": 50.0,
                "FORMAL_OWNER": 45.0,
                "DOMAIN_EXPERT": 40.0,
                "OWNER_TEAM_MEMBER": 25.0,
            },
        }
        table = weights.get(requirement, {})
        role_score = max((table.get(role, 0.0) for role in roles), default=0.0)
        if not table:
            role_score = existing
        return round(min(100.0, role_score + existing * 0.05), 4)

    def _expand_routing_targets(self, snapshot: GraphSnapshot, ids: Iterable[str], *, as_of: str | None) -> list[str]:
        systems: set[str] = set()
        queue = deque(ids)
        seen: set[str] = set()
        while queue:
            item = str(queue.popleft())
            if item in seen:
                continue
            seen.add(item)
            node = snapshot.node(item)
            if not node:
                continue
            if has_label(node, "System"):
                systems.add(item)
                continue
            if has_label(node, "Change"):
                queue.extend(edge.target for edge in snapshot.edges_from(item, {"CHANGED", "AFFECTS"}, as_of=as_of))
            elif has_label(node, "Deployment"):
                queue.extend(edge.target for edge in snapshot.edges_from(item, {"CONTAINS"}, as_of=as_of))
            elif has_label(node, "Action") or has_label(node, "Policy"):
                rels = {"ABOUT"} if has_label(node, "Action") else {"GOVERNS"}
                queue.extend(edge.target for edge in snapshot.edges_from(item, rels, as_of=as_of))
        return sorted(systems)

    def _candidate_assignees_for_blueprint(
        self, snapshot: GraphSnapshot, blueprint: dict[str, Any], *, as_of: str | None
    ) -> list[dict[str, Any]]:
        requirement = str(blueprint.get("assignee_requirement") or "GENERAL")
        candidates: dict[str, dict[str, Any]] = {}

        # Tool access comes from the existing Phase 4 graph routing service, not a new registry.
        for addressed in blueprint.get("addresses", []):
            node = snapshot.node(addressed)
            if not has_label(node, "Question"):
                continue
            routing = EvidenceAcquisitionService(self.client).route_question(addressed, as_of=as_of) or {}
            for route in routing.get("routes", []):
                tool = route.get("tool")
                if not tool:
                    continue
                tid = str(tool.get("id"))
                entry = candidates.setdefault(
                    tid,
                    {
                        "actor": tool,
                        "score": 0.0,
                        "roles": ["TOOL_ACCESS"],
                        "reasons": [],
                        "graph_paths": [],
                        "source": "EVIDENCE_ROUTING",
                    },
                )
                score = 100.0 if route.get("authoritative") else 80.0
                entry["score"] = max(entry["score"], score)
                entry["reasons"].append("Tool/DataSource route can obtain the required evidence")
                entry["graph_paths"].extend(route.get("path") or [])

        systems = self._expand_routing_targets(snapshot, blueprint.get("routing_targets") or [], as_of=as_of)
        for system_id in systems:
            routing = ResponsibilityRoutingService(self.client).rank_candidate_responders(system_id, as_of=as_of)
            for candidate in routing.get("ranked_candidates", []):
                actor = candidate.get("actor") or {}
                actor_id = str(actor.get("id") or "")
                if not actor_id:
                    continue
                score = self._task_specific_score(candidate, requirement)
                if score <= 0:
                    continue
                entry = candidates.setdefault(
                    actor_id,
                    {
                        "actor": actor,
                        "score": 0.0,
                        "roles": [],
                        "reasons": [],
                        "graph_paths": [],
                        "source": "RESPONSIBILITY_ROUTING",
                    },
                )
                entry["score"] = max(float(entry["score"]), score)
                entry["roles"] = sorted(set(entry["roles"]) | set(candidate.get("roles") or []))
                entry["reasons"].extend(candidate.get("basis") or [])
                entry["reasons"].append(f"task requires {requirement.lower()} for {system_id}")
                entry["graph_paths"].extend(candidate.get("paths") or [])

        ranked = list(candidates.values())
        for item in ranked:
            item["score"] = round(float(item["score"]), 4)
            item["reasons"] = list(dict.fromkeys(str(x) for x in item["reasons"]))
            normalized_paths = []
            for path in item["graph_paths"]:
                normalized_paths.append(path if isinstance(path, str) else " -> ".join(str(x) for x in path))
            item["graph_paths"] = list(dict.fromkeys(normalized_paths))
        ranked.sort(key=lambda x: (-x["score"], str((x.get("actor") or {}).get("id"))))
        return ranked

    # ---------- persistence ----------
    def _ensure_planner_identity(self, timestamp: str) -> None:
        upsert_node(
            self.client,
            "Agent",
            PLANNER_ID,
            {
                "name": "Deterministic Phase 5 Planner",
                "agent_type": "DETERMINISTIC_PLANNER",
                "status": "ACTIVE",
                "created_at": timestamp,
                "planner_version": PLANNER_VERSION,
            },
        )

    def _write_creation_event(
        self, *, event_id: str, event_type: str, timestamp: str, summary: str, about_ids: list[str]
    ) -> None:
        upsert_node(
            self.client,
            "Event",
            event_id,
            {
                "event_type": event_type,
                "occurred_at": timestamp,
                "created_at": timestamp,
                "summary": summary,
                "generator_id": PLANNER_ID,
                "planner_version": PLANNER_VERSION,
            },
        )
        for entity_id in about_ids:
            upsert_relationship(self.client, event_id, "ABOUT", entity_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_relationship(self.client, event_id, "PERFORMED_BY", PLANNER_ID, {"valid_from": timestamp, "confidence": 1.0})

    def generate_plan(self, situation_id: str, goal: str, **kwargs: Any) -> dict[str, Any] | None:
        derived = self.derive_plan(situation_id, goal, **kwargs)
        if derived is None:
            return None
        as_of = kwargs.get("as_of")
        before = GraphSnapshot.load(self.client)
        plan_id = derived["plan_id"]
        existing_plan = before.node(plan_id)
        timestamp = str((existing_plan or {}).get("created_at") or now_iso())
        self._ensure_planner_identity(timestamp)

        plan_props = {
            "situation_id": situation_id,
            "goal": derived["goal"],
            "status": str((existing_plan or {}).get("status") or "DRAFT"),
            "created_at": timestamp,
            "created_by": PLANNER_ID,
            "generated_by": PLANNER_ID,
            "planner_version": PLANNER_VERSION,
            "provenance": "derived from FalkorDB reasoning state",
            "strategy_summary": "knowledge gaps -> conflicts -> remediation proposal -> policy/approval checks",
            "as_of": as_of,
            "selection_fingerprint": derived["selection_fingerprint"],
            "selected_hypotheses_csv": self._csv(derived.get("selected_hypotheses")),
            "selected_claims_csv": self._csv(derived.get("selected_claims")),
            "selected_knowledge_gaps_csv": self._csv(derived.get("selected_knowledge_gaps")),
            "constraint_refs_csv": self._csv(derived.get("explicit_constraint_refs")),
        }
        upsert_node(self.client, "Plan", plan_id, plan_props)
        upsert_relationship(self.client, plan_id, "ADDRESSES", situation_id, {"confidence": 1.0})
        for constraint_id in derived.get("explicit_constraint_refs") or []:
            upsert_relationship(
                self.client,
                plan_id,
                "ADDRESSES",
                constraint_id,
                {"confidence": 1.0},
            )

        if existing_plan is None:
            self._write_creation_event(
                event_id=f"EVT-{plan_id}-CREATED",
                event_type="PLAN_CREATED",
                timestamp=timestamp,
                summary=f"Created plan {plan_id} for {situation_id}",
                about_ids=[plan_id, situation_id],
            )

        generated_task_ids: set[str] = set()
        semantic_to_id: dict[str, str] = {}
        existing_by_signature: dict[tuple[str, str], str] = {}
        for node in before.nodes.values():
            if (
                has_label(node, "Task")
                and str(node.get("status") or "OPEN").upper() in ACTIVE_TASK_STATUSES
                and str(node.get("situation_id") or "") == situation_id
                and node.get("semantic_key")
                and node.get("semantic_signature")
            ):
                existing_by_signature.setdefault(
                    (str(node.get("semantic_key")), str(node.get("semantic_signature"))),
                    str(node.get("id")),
                )

        for bp in derived["tasks"]:
            signature = self._blueprint_signature(bp)
            reusable_id = existing_by_signature.get((bp["semantic_key"], signature))
            fallback_id = self._task_id(plan_id, bp["semantic_key"])
            task_id = reusable_id or fallback_id

            fallback_node = before.node(task_id)
            if (
                reusable_id is None
                and fallback_node
                and str(fallback_node.get("semantic_signature") or "") not in {"", signature}
            ):
                other_plan_refs = [
                    edge
                    for edge in before.edges_to(task_id, {"PLAN_HAS_TASK"})
                    if edge.source != plan_id
                ]
                if other_plan_refs:
                    # The original deterministic Task is shared by another Plan and must not
                    # be structurally rewritten. Use a stable plan+signature version instead.
                    task_id = _stable_id("TASK-P5-", plan_id, bp["semantic_key"], signature)

            semantic_to_id[bp["semantic_key"]] = task_id
            generated_task_ids.add(task_id)
            existing_task = before.node(task_id)
            task_created_at = str((existing_task or {}).get("created_at") or timestamp)
            previous_status = str((existing_task or {}).get("status") or "OPEN").upper()
            # A deterministic task can disappear from one recomputation and become relevant
            # again later. SUPERSEDED is planner lifecycle state, not permanent cancellation.
            task_status = "OPEN" if previous_status == "SUPERSEDED" else previous_status
            upsert_node(
                self.client,
                "Task",
                task_id,
                {
                    "name": bp["title"],
                    "title": bp["title"],
                    "objective": bp["objective"],
                    "task_type": bp["task_type"],
                    "status": task_status,
                    "priority": bp["priority"],
                    "created_at": task_created_at,
                    "expected_output_type": bp["expected_output_type"],
                    "completion_condition": bp["completion_condition"],
                    "semantic_key": bp["semantic_key"],
                    "semantic_signature": signature,
                    "situation_id": situation_id,
                    "assignee_requirement": bp["assignee_requirement"],
                    "planner_version": PLANNER_VERSION,
                    "derivation_reason": bp["reason"],
                    "provenance": "derived from FalkorDB reasoning state",
                },
            )
            upsert_relationship(self.client, plan_id, "PLAN_HAS_TASK", task_id, {"confidence": 1.0})
            for entity_id in sorted(set(bp.get("addresses") or [])):
                if before.node(entity_id):
                    upsert_relationship(self.client, task_id, "ADDRESSES", entity_id, {"confidence": 1.0})
            for entity_id in sorted(set(bp.get("about") or [])):
                if entity_id == task_id:
                    continue
                upsert_relationship(self.client, task_id, "ABOUT", entity_id, {"confidence": 1.0})
            for entity_id in sorted(set(bp.get("requires_entities") or [])):
                upsert_relationship(self.client, task_id, "REQUIRES", entity_id, {"required": True, "confidence": 1.0})
            if existing_task is None:
                self._write_creation_event(
                    event_id=f"EVT-{task_id}-CREATED",
                    event_type="TASK_CREATED",
                    timestamp=task_created_at,
                    summary=f"Created task {task_id}: {bp['title']}",
                    about_ids=[task_id, plan_id, situation_id],
                )

        # Persist task prerequisites only after all deterministic task IDs are known.
        by_semantic = {item["semantic_key"]: item for item in derived["tasks"]}
        for semantic_key, task_id in semantic_to_id.items():
            for prereq_key in by_semantic[semantic_key].get("prerequisite_keys", []):
                upsert_relationship(
                    self.client,
                    task_id,
                    "REQUIRES",
                    semantic_to_id[prereq_key],
                    {"required": True, "confidence": 1.0},
                )

        # Recompute is a synchronization operation for planner-owned task semantics.
        # Remove stale derivation/prerequisite edges before they can affect readiness or validation.
        desired_edges: dict[str, dict[str, set[str]]] = {}
        for bp in derived["tasks"]:
            task_id = semantic_to_id[bp["semantic_key"]]
            desired_edges[task_id] = {
                "ADDRESSES": set(bp.get("addresses") or []),
                "ABOUT": set(bp.get("about") or []),
                "REQUIRES": set(bp.get("requires_entities") or [])
                | {semantic_to_id[key] for key in bp.get("prerequisite_keys", [])},
            }

        for task_id, desired_by_type in desired_edges.items():
            existing_task = before.node(task_id) or {}
            if not str(existing_task.get("planner_version") or "").startswith("phase5"):
                continue
            for relationship_type, desired_targets in desired_by_type.items():
                for edge in before.edges_from(task_id, {relationship_type}):
                    if edge.target not in desired_targets:
                        delete_relationship(self.client, task_id, relationship_type, edge.target)

        # Remove stale Plan membership on recompute and explicitly supersede planner-generated orphan work.
        for edge in before.edges_from(plan_id, {"PLAN_HAS_TASK"}):
            if edge.target in generated_task_ids:
                continue
            delete_relationship(self.client, plan_id, "PLAN_HAS_TASK", edge.target)
            stale = before.node(edge.target) or {}
            other_plan_refs = [
                ref for ref in before.edges_to(edge.target, {"PLAN_HAS_TASK"})
                if ref.source != plan_id
            ]
            if (
                not other_plan_refs
                and str(stale.get("planner_version") or "").startswith("phase5")
                and str(stale.get("status") or "").upper() not in TERMINAL_TASK_STATUSES
            ):
                upsert_node(self.client, "Task", edge.target, {"status": "SUPERSEDED"})

        # Candidate workers are graph-derived and refreshed on every generation/recompute.
        after_tasks = GraphSnapshot.load(self.client)
        for bp in derived["tasks"]:
            task_id = semantic_to_id[bp["semantic_key"]]
            ranked = self._candidate_assignees_for_blueprint(after_tasks, bp, as_of=as_of)
            keep_ids = {str((candidate.get("actor") or {}).get("id")) for candidate in ranked}
            for edge in after_tasks.edges_to(task_id, {"CANDIDATE_FOR"}):
                if edge.source not in keep_ids:
                    delete_relationship(self.client, edge.source, "CANDIDATE_FOR", task_id)
            for candidate in ranked:
                actor = candidate.get("actor") or {}
                actor_id = str(actor.get("id") or "")
                if not actor_id:
                    continue
                upsert_relationship(
                    self.client,
                    actor_id,
                    "CANDIDATE_FOR",
                    task_id,
                    {
                        "score": candidate["score"],
                        "requirement": bp["assignee_requirement"],
                        "roles": ",".join(candidate.get("roles") or []),
                        "reason_summary": " | ".join(candidate.get("reasons") or [])[:1000],
                        "path_summary": " | ".join(candidate.get("graph_paths") or [])[:2000],
                        "confidence": min(1.0, float(candidate["score"]) / 100.0),
                    },
                )

        validation = self.validate_plan(plan_id)
        status = "READY" if validation["valid"] else "BLOCKED"
        upsert_node(self.client, "Plan", plan_id, {"status": status})
        return self.get_plan(plan_id)

    def recompute_plan(self, plan_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        plan = snapshot.node(plan_id)
        if plan is None or not has_label(plan, "Plan"):
            return None
        return self.generate_plan(
            str(plan.get("situation_id")),
            str(plan.get("goal") or ""),
            selected_hypotheses=self._from_csv(plan.get("selected_hypotheses_csv")),
            selected_claims=self._from_csv(plan.get("selected_claims_csv")),
            knowledge_gaps=self._from_csv(plan.get("selected_knowledge_gaps_csv")),
            constraints=self._from_csv(plan.get("constraint_refs_csv")),
            as_of=plan.get("as_of"),
        )

    # ---------- reads / explanations ----------
    def _plan_task_ids(self, snapshot: GraphSnapshot, plan_id: str) -> list[str]:
        return sorted(
            edge.target
            for edge in snapshot.edges_from(plan_id, {"PLAN_HAS_TASK"})
            if has_label(snapshot.node(edge.target), "Task")
        )

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        plan = snapshot.node(plan_id)
        if plan is None or not has_label(plan, "Plan"):
            return None
        task_ids = self._plan_task_ids(snapshot, plan_id)
        tasks = [self._task_detail(snapshot, task_id) for task_id in task_ids]
        tasks.sort(key=lambda item: (_priority_rank(item["task"].get("priority")), item["task"].get("task_type", ""), item["task"].get("id", "")))
        return {
            "plan": plan,
            "situation": snapshot.node(str(plan.get("situation_id"))),
            "tasks": tasks,
            "task_count": len(tasks),
            "ready_tasks": self._ready_tasks_from_snapshot(snapshot, plan_id),
            "validation": self._validate_plan_snapshot(snapshot, plan_id),
            "graph_required": True,
        }

    def get_plan_tasks(self, plan_id: str) -> dict[str, Any] | None:
        plan = self.get_plan(plan_id)
        if plan is None:
            return None
        return {"plan_id": plan_id, "tasks": plan["tasks"], "task_count": plan["task_count"]}

    def _task_detail(self, snapshot: GraphSnapshot, task_id: str) -> dict[str, Any]:
        task = snapshot.node(task_id) or {}
        prereqs = []
        required_entities = []
        addresses = []
        about = []
        for edge in snapshot.edges_from(task_id):
            target = snapshot.node(edge.target)
            if edge.type == "REQUIRES":
                item = {"entity": target, "path": f"{task_id}-[:REQUIRES]->{edge.target}"}
                if has_label(target, "Task"):
                    prereqs.append(item)
                else:
                    required_entities.append(item)
            elif edge.type == "ADDRESSES":
                addresses.append({"entity": target, "path": f"{task_id}-[:ADDRESSES]->{edge.target}"})
            elif edge.type == "ABOUT":
                about.append({"entity": target, "path": f"{task_id}-[:ABOUT]->{edge.target}"})
        candidates = []
        for edge in snapshot.edges_to(task_id, {"CANDIDATE_FOR"}):
            candidates.append(
                {
                    "actor": snapshot.node(edge.source),
                    "score": float(edge.properties.get("score") or 0.0),
                    "requirement": edge.properties.get("requirement"),
                    "roles": [x for x in str(edge.properties.get("roles") or "").split(",") if x],
                    "reasons": [x.strip() for x in str(edge.properties.get("reason_summary") or "").split("|") if x.strip()],
                    "graph_paths": [x.strip() for x in str(edge.properties.get("path_summary") or "").split("|") if x.strip()],
                    "path": f"{edge.source}-[:CANDIDATE_FOR]->{task_id}",
                }
            )
        candidates.sort(key=lambda x: (-x["score"], str((x.get("actor") or {}).get("id"))))
        return {
            "task": task,
            "prerequisites": prereqs,
            "required_entities": required_entities,
            "addresses": addresses,
            "about": about,
            "candidate_assignees": candidates,
            "explanation": {
                "reason": task.get("derivation_reason"),
                "graph_paths": [x["path"] for x in prereqs + required_entities + addresses + about],
            },
        }

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        node = snapshot.node(task_id)
        if node is None or not has_label(node, "Task"):
            return None
        return self._task_detail(snapshot, task_id)

    def get_candidate_assignees(self, task_id: str) -> dict[str, Any] | None:
        detail = self.get_task(task_id)
        if detail is None:
            return None
        return {
            "task_id": task_id,
            "assignee_requirement": detail["task"].get("assignee_requirement"),
            "candidate_assignees": detail["candidate_assignees"],
            "actual_assignee": None,
            "assignment_performed": False,
        }

    def get_prerequisites(self, task_id: str) -> dict[str, Any] | None:
        detail = self.get_task(task_id)
        if detail is None:
            return None
        return {
            "task_id": task_id,
            "prerequisites": detail["prerequisites"],
            "required_entities": detail["required_entities"],
        }

    # ---------- readiness / validation ----------
    @staticmethod
    def _is_blocker_cleared(node: dict[str, Any] | None) -> bool:
        if not node:
            return False
        if has_label(node, "Tool") or has_label(node, "DataSource") or has_label(node, "Evidence"):
            return True
        return str(node.get("status") or "").upper() in DONE_TASK_STATUSES | {"RESOLVED", "APPROVED", "ACTIVE"}

    def _task_readiness(self, snapshot: GraphSnapshot, task_id: str) -> dict[str, Any]:
        task = snapshot.node(task_id) or {}
        status = str(task.get("status") or "OPEN").upper()
        reasons = []
        if status in TERMINAL_TASK_STATUSES:
            return {"task": task, "ready": False, "reason_codes": ["TERMINAL_TASK"]}
        for edge in snapshot.edges_from(task_id, {"REQUIRES"}):
            target = snapshot.node(edge.target)
            if has_label(target, "Task"):
                if str((target or {}).get("status") or "").upper() not in DONE_TASK_STATUSES:
                    reasons.append(f"PREREQUISITE_TASK_NOT_COMPLETED:{edge.target}")
            elif has_label(target, "Tool") or has_label(target, "DataSource"):
                if str((target or {}).get("status") or "ACTIVE").upper() in {"INACTIVE", "DISABLED", "DECOMMISSIONED"}:
                    reasons.append(f"REQUIRED_SOURCE_UNAVAILABLE:{edge.target}")
            elif not self._is_blocker_cleared(target):
                reasons.append(f"REQUIRED_ENTITY_UNSATISFIED:{edge.target}")
        for edge in snapshot.edges_from(task_id, {"BLOCKED_BY"}):
            if not self._is_blocker_cleared(snapshot.node(edge.target)):
                reasons.append(f"ACTIVE_BLOCKER:{edge.target}")
        return {"task": task, "ready": not reasons, "reason_codes": reasons}

    def _ready_tasks_from_snapshot(self, snapshot: GraphSnapshot, plan_id: str) -> list[dict[str, Any]]:
        ready = []
        for task_id in self._plan_task_ids(snapshot, plan_id):
            state = self._task_readiness(snapshot, task_id)
            if state["ready"]:
                ready.append(state)
        ready.sort(key=lambda item: (_priority_rank(item["task"].get("priority")), str(item["task"].get("id"))))
        return ready

    def get_task_readiness(self, task_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        task = snapshot.node(task_id)
        if task is None or not has_label(task, "Task"):
            return None
        return self._task_readiness(snapshot, task_id)

    def get_ready_tasks(self, plan_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        plan = snapshot.node(plan_id)
        if plan is None or not has_label(plan, "Plan"):
            return None
        states = [self._task_readiness(snapshot, task_id) for task_id in self._plan_task_ids(snapshot, plan_id)]
        return {
            "plan_id": plan_id,
            "ready_tasks": [x for x in states if x["ready"]],
            "blocked_tasks": [x for x in states if not x["ready"]],
        }

    @staticmethod
    def _cycle_info(snapshot: GraphSnapshot, task_ids: set[str]) -> tuple[bool, list[str]]:
        indegree = {task_id: 0 for task_id in task_ids}
        outgoing: dict[str, list[str]] = defaultdict(list)
        for source in task_ids:
            for edge in snapshot.edges_from(source, {"REQUIRES"}):
                if edge.target not in task_ids or not has_label(snapshot.node(edge.target), "Task"):
                    continue
                # source requires target => target precedes source
                outgoing[edge.target].append(source)
                indegree[source] += 1
        queue = deque(sorted(k for k, degree in indegree.items() if degree == 0))
        visited = []
        while queue:
            current = queue.popleft()
            visited.append(current)
            for nxt in outgoing.get(current, []):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
        cycle_nodes = sorted(k for k, degree in indegree.items() if degree > 0)
        return bool(cycle_nodes), cycle_nodes

    def _validate_plan_snapshot(self, snapshot: GraphSnapshot, plan_id: str) -> dict[str, Any]:
        plan = snapshot.node(plan_id)
        task_ids = set(self._plan_task_ids(snapshot, plan_id)) if plan else set()
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        if not task_ids:
            errors.append({"code": "NO_TASKS", "detail": "Plan has no PLAN_HAS_TASK relationships."})
        situation_id = str((plan or {}).get("situation_id") or "")
        if situation_id and not any(
            edge.target == situation_id for edge in snapshot.edges_from(plan_id, {"ADDRESSES"})
        ):
            errors.append({
                "code": "PLAN_NOT_CONNECTED_TO_SITUATION",
                "detail": "Plan must ADDRESSES its situation so goal provenance is traversable.",
                "situation_id": situation_id,
            })
        has_cycle, cycle_nodes = self._cycle_info(snapshot, task_ids)
        if has_cycle:
            errors.append({"code": "TASK_CYCLE", "detail": "Task REQUIRES graph is cyclic.", "task_ids": cycle_nodes})

        for task_id in sorted(task_ids):
            task = snapshot.node(task_id) or {}
            if not task.get("task_type") or task.get("task_type") not in TASK_TYPES:
                errors.append({"code": "UNTYPED_TASK", "task_id": task_id})
            if not task.get("completion_condition"):
                errors.append({"code": "MISSING_COMPLETION_CONDITION", "task_id": task_id})
            if not task.get("expected_output_type"):
                errors.append({"code": "MISSING_EXPECTED_OUTPUT", "task_id": task_id})
            for edge in snapshot.edges_from(task_id, {"REQUIRES"}):
                if has_label(snapshot.node(edge.target), "Task") and edge.target not in task_ids:
                    errors.append({"code": "DANGLING_TASK_PREREQUISITE", "task_id": task_id, "target_id": edge.target})
            addresses = [snapshot.node(edge.target) for edge in snapshot.edges_from(task_id, {"ADDRESSES"})]
            about_edges = snapshot.edges_from(task_id, {"ABOUT"})
            if situation_id and not any(edge.target == situation_id for edge in about_edges):
                errors.append({
                    "code": "TASK_NOT_CONNECTED_TO_SITUATION",
                    "task_id": task_id,
                    "situation_id": situation_id,
                })
            if task.get("task_type") in {"ACQUIRE_EVIDENCE", "INVESTIGATE"} and not any(has_label(node, "Question") for node in addresses):
                warnings.append({"code": "NO_QUESTION_ADDRESS", "task_id": task_id})
            if task.get("task_type") == "ACQUIRE_EVIDENCE":
                non_task_requirements = [
                    snapshot.node(edge.target)
                    for edge in snapshot.edges_from(task_id, {"REQUIRES"})
                    if not has_label(snapshot.node(edge.target), "Task")
                ]
                if not any(
                    has_label(node, "Tool") or has_label(node, "DataSource")
                    for node in non_task_requirements
                ):
                    errors.append({"code": "MISSING_EVIDENCE_REQUIREMENT", "task_id": task_id})
            candidates = snapshot.edges_to(task_id, {"CANDIDATE_FOR"})
            if task.get("assignee_requirement") and not candidates:
                errors.append({"code": "UNRESOLVABLE_ASSIGNEE_REQUIREMENT", "task_id": task_id})

        # Required approval must either already exist or be represented by a plan task.
        plan_actions = {
            edge.target
            for task_id in task_ids
            for edge in snapshot.edges_from(task_id, {"ADDRESSES"})
            if has_label(snapshot.node(edge.target), "Action")
        }
        approval_task_actions = {
            edge.target
            for task_id in task_ids
            if str((snapshot.node(task_id) or {}).get("task_type")) == "REQUEST_APPROVAL"
            for edge in snapshot.edges_from(task_id, {"ADDRESSES"})
            if has_label(snapshot.node(edge.target), "Action")
        }
        for action_id in sorted(plan_actions):
            action = snapshot.node(action_id) or {}
            if action.get("approval_required") and not snapshot.edges_from(action_id, {"APPROVED_BY"}) and action_id not in approval_task_actions:
                errors.append({"code": "MISSING_APPROVAL_WORK", "action_id": action_id})

        return {
            "plan_id": plan_id,
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "task_count": len(task_ids),
            "graph_required": True,
        }

    def validate_plan(self, plan_id: str) -> dict[str, Any]:
        return self._validate_plan_snapshot(GraphSnapshot.load(self.client), plan_id)

    # ---------- deterministic completion checks ----------
    def is_task_completion_satisfied(self, task_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        task = snapshot.node(task_id)
        if task is None or not has_label(task, "Task"):
            return None
        status = str(task.get("status") or "OPEN").upper()
        if status in DONE_TASK_STATUSES:
            return {"task_id": task_id, "satisfied": True, "reason": "Task status is terminal-complete."}
        task_type = str(task.get("task_type") or "")
        addressed = [snapshot.node(edge.target) for edge in snapshot.edges_from(task_id, {"ADDRESSES"})]
        if task_type in {"ACQUIRE_EVIDENCE", "INVESTIGATE"}:
            questions = [node for node in addressed if has_label(node, "Question")]
            if questions:
                missing = []
                for question in questions:
                    qid = str(question.get("id"))
                    resolved = str(question.get("status") or "").upper() in {"RESOLVED", "CLOSED"}
                    evidence = [
                        edge for edge in snapshot.edges_from(qid, {"RESOLVED_BY"})
                        if has_label(snapshot.node(edge.target), "Evidence")
                    ]
                    if not (resolved and evidence):
                        missing.append(qid)
                return {
                    "task_id": task_id,
                    "satisfied": not missing,
                    "reason": "All addressed questions have resolving Evidence." if not missing else "Some addressed questions remain unresolved.",
                    "missing_question_ids": missing,
                }
        if task_type == "PREPARE_ACTION":
            actions = [node for node in addressed if has_label(node, "Action")]
            satisfied = bool(actions) and all(str(a.get("status") or "").upper() not in {"REJECTED", "CANCELLED"} for a in actions)
            return {"task_id": task_id, "satisfied": satisfied, "reason": "Selected Action proposal is present." if satisfied else "Action proposal is absent or rejected."}
        if task_type == "REQUEST_APPROVAL":
            action_ids = [str(node.get("id")) for node in addressed if has_label(node, "Action")]
            missing = [action_id for action_id in action_ids if not snapshot.edges_from(action_id, {"APPROVED_BY"})]
            return {"task_id": task_id, "satisfied": bool(action_ids) and not missing, "reason": "Required approval exists." if not missing else "Approval is still missing.", "missing_action_ids": missing}
        if task_type == "RESOLVE_CONFLICT":
            plan_edges = snapshot.edges_to(task_id, {"PLAN_HAS_TASK"})
            situation_id = None
            if plan_edges:
                plan = snapshot.node(plan_edges[0].source) or {}
                situation_id = plan.get("situation_id")
            if situation_id:
                result = AuthorityResolutionService(self.client).resolve_subject_conflicts(str(situation_id))
                return {"task_id": task_id, "satisfied": result.get("status") == "RESOLVED", "reason": result.get("reason"), "resolution": result}
        return {"task_id": task_id, "satisfied": False, "reason": "Completion requires an explicit later work-state transition."}
