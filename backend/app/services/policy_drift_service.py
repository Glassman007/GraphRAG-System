from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.temporal import to_epoch_us
from backend.app.services.phase4_graph import GraphEdge, GraphSnapshot, has_label
from backend.app.services.phase8_utils import node_timestamp_us, node_visible, path_text
from backend.app.services.process_reconstruction_service import OrganizationalProcessReconstructionService


DONE_STATES = {"DONE", "COMPLETED", "SUCCEEDED", "EXECUTED", "VERIFIED", "VALIDATED", "FULFILLED", "APPROVED"}
MISSING_STATES = {"NOT_RECORDED", "MISSING", "SKIPPED", "CANCELLED"}


class PolicyDriftService:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    @staticmethod
    def _policy_active(node: dict[str, Any], as_of: str | None) -> bool:
        return node_visible(node, as_of)

    @staticmethod
    def _select_policy(snapshot: GraphSnapshot, policy_id: str, process_time: str | None) -> tuple[dict[str, Any] | None, str | None]:
        requested = snapshot.node(policy_id)
        if requested is None or not has_label(requested, "Policy"):
            return None, "POLICY_NOT_FOUND"
        if PolicyDriftService._policy_active(requested, process_time):
            return requested, None
        family = requested.get("policy_family") or requested.get("name")
        candidates = [
            node for node in snapshot.nodes.values()
            if has_label(node, "Policy") and (node.get("policy_family") or node.get("name")) == family and PolicyDriftService._policy_active(node, process_time)
        ]
        candidates.sort(key=lambda n: (to_epoch_us(str(n.get("valid_from"))) if n.get("valid_from") else 0, str(n.get("id"))), reverse=True)
        if candidates:
            return candidates[0], "HISTORICAL_VERSION_SELECTED"
        return None, "NO_POLICY_VERSION_VALID_AT_PROCESS_TIME"

    @staticmethod
    def _process_window(process: dict[str, Any], snapshot: GraphSnapshot, scope_id: str, as_of: str | None) -> tuple[int | None, int | None, str | None, str | None]:
        """Return the observed process interval in epoch microseconds and public ISO values.

        The interval is derived from reconstructed process Events.  A historical ``as_of``
        query is already enforced by process reconstruction; the end is additionally capped
        defensively so future relationships cannot leak into a historical analysis.
        """
        timed_steps: list[tuple[int, str]] = []
        for step in process.get("steps", []):
            event = step.get("event") or {}
            ts = node_timestamp_us(event, "occurred_at", "created_at")
            raw = event.get("occurred_at") or event.get("created_at")
            if ts is not None and raw:
                timed_steps.append((ts, str(raw)))
        if timed_steps:
            timed_steps.sort(key=lambda item: item[0])
            start_us, start_iso = timed_steps[0]
            end_us, end_iso = timed_steps[-1]
        else:
            scope = snapshot.node(scope_id) or {}
            raw = scope.get("started_at") or scope.get("created_at") or as_of
            start_us = end_us = to_epoch_us(str(raw)) if raw else None
            start_iso = end_iso = str(raw) if raw else None
        if as_of and end_us is not None:
            cutoff = to_epoch_us(as_of)
            if end_us > cutoff:
                end_us, end_iso = cutoff, as_of
        return start_us, end_us, start_iso, end_iso

    @staticmethod
    def _edge_overlaps_window(edge: GraphEdge, process_start_us: int | None, process_end_us: int | None) -> bool:
        """Half-open relationship interval overlaps the closed observed process window."""
        if process_start_us is None or process_end_us is None:
            return edge.properties.get("valid_until") is None
        valid_from = edge.properties.get("valid_from")
        valid_until = edge.properties.get("valid_until")
        valid_from_us = to_epoch_us(str(valid_from)) if valid_from is not None else None
        valid_until_us = to_epoch_us(str(valid_until)) if valid_until is not None else None
        return (valid_from_us is None or valid_from_us <= process_end_us) and (valid_until_us is None or valid_until_us > process_start_us)

    @staticmethod
    def _relationship_active_at_us(edge: GraphEdge, point_us: int) -> bool:
        valid_from = edge.properties.get("valid_from")
        valid_until = edge.properties.get("valid_until")
        if valid_from is not None and to_epoch_us(str(valid_from)) > point_us:
            return False
        if valid_until is not None and to_epoch_us(str(valid_until)) <= point_us:
            return False
        return True

    @staticmethod
    def _operation_time_us(
        snapshot: GraphSnapshot,
        governed_edge: GraphEdge,
        governed: dict[str, Any],
        container_edges: list[GraphEdge],
        process: dict[str, Any],
        process_start_us: int | None,
        process_end_us: int | None,
    ) -> int | None:
        """Best deterministic timestamp for when the governed operation began.

        Prefer actual operation/deployment timestamps and observed process Events.  Relationship
        ``valid_from`` is only a fallback because a long-lived policy-scope relationship can
        predate the concrete operation by months.
        """
        candidates: list[int] = []

        def add_value(value: Any) -> None:
            if not value:
                return
            ts = to_epoch_us(str(value))
            if process_start_us is not None and ts < process_start_us:
                return
            if process_end_us is not None and ts > process_end_us:
                return
            candidates.append(ts)

        for field in ("applied_at", "deployed_at", "executed_at", "started_at", "occurred_at", "completed_at"):
            add_value(governed.get(field))

        container_ids = {edge.source for edge in container_edges}
        for container_id in container_ids:
            container = snapshot.node(container_id) or {}
            for field in ("deployed_at", "executed_at", "started_at", "occurred_at", "completed_at"):
                add_value(container.get(field))

        governed_id = str(governed.get("id"))
        for step in process.get("steps", []):
            about_ids = set(step.get("about_ids") or [])
            if governed_id in about_ids or container_ids.intersection(about_ids):
                event = step.get("event") or {}
                add_value(event.get("occurred_at") or event.get("created_at"))

        # A containment edge commonly marks the concrete deployment/change start.
        for edge in container_edges:
            add_value(edge.properties.get("valid_from"))
        add_value(governed_edge.properties.get("valid_from"))

        if candidates:
            return min(candidates)
        return process_end_us

    @staticmethod
    def analyze_from_snapshot(snapshot: GraphSnapshot, scope_id: str, policy_id: str, *, as_of: str | None = None) -> dict[str, Any] | None:
        process = OrganizationalProcessReconstructionService.reconstruct_from_snapshot(snapshot, scope_id, as_of=as_of)
        if process is None:
            return None
        process_start_us, process_end_us, process_start, process_end = PolicyDriftService._process_window(process, snapshot, scope_id, as_of)
        # Policy-version selection retains the established historical rule: select the version
        # valid when the observed process began.  Process-scoped relationships below use the
        # full process interval instead of this point-in-time value.
        process_time = process_start
        policy, selection_note = PolicyDriftService._select_policy(snapshot, policy_id, process_time)
        if policy is None:
            return {"scope_id": scope_id, "policy_id": policy_id, "process": process, "status": "UNKNOWN", "reason": selection_note, "drift": []}
        pid = str(policy["id"])
        requirements = []
        for edge in snapshot.edges_from(pid, {"REQUIRES"}, as_of=process_time or as_of):
            target = snapshot.node(edge.target)
            if not target:
                continue
            requirements.append({"edge": edge, "target": target, "optional": bool(edge.properties.get("optional", False) or edge.properties.get("required") is False)})

        # Process-level policy scope is interval-based.  A GOVERNS edge that becomes valid
        # after an early process event is still relevant when it overlaps the observed process.
        governed_edges = [
            edge for edge in snapshot.outgoing.get(pid, [])
            if edge.type == "GOVERNS" and PolicyDriftService._edge_overlaps_window(edge, process_start_us, process_end_us)
        ]
        governed_targets = [snapshot.node(edge.target) for edge in governed_edges if snapshot.node(edge.target)]
        drift = []
        approval_observations: list[dict[str, Any]] = []
        for req in requirements:
            edge, target, optional = req["edge"], req["target"], req["optional"]
            target_id = str(target.get("id"))
            status = str(target.get("status") or "UNKNOWN").upper()
            event_evidence = []
            for event_edge in snapshot.edges_to(target_id, {"ABOUT"}, as_of=as_of):
                ev = snapshot.node(event_edge.source)
                if ev and has_label(ev, "Event"):
                    event_evidence.append(ev)
            observed = status in DONE_STATES or any(str(ev.get("event_type") or "").upper() in {"ACTION_EXECUTED", "ACTION_SUCCEEDED", "OUTCOME_OBSERVED"} for ev in event_evidence)
            if observed:
                authorized = edge.properties.get("authorized_actor_ids") or []
                if authorized:
                    observed_actors = set()
                    for ev in event_evidence:
                        eid = str(ev.get("id"))
                        observed_actors.update(e.target for e in snapshot.edges_from(eid, {"PERFORMED_BY"}, as_of=as_of))
                    if observed_actors and not (set(authorized) & observed_actors):
                        drift.append({
                            "policy_id": pid,
                            "expected_requirement": target,
                            "observed_behavior": {"status": status, "actors": sorted(observed_actors)},
                            "classification": "UNAUTHORIZED_ACTOR",
                            "status": "VIOLATION",
                            "severity": str(edge.properties.get("severity") or "HIGH"),
                            "expected_path": path_text(edge),
                            "observed_path": [f"{ev.get('id')}-[:PERFORMED_BY]->{actor}" for ev in event_evidence for actor in observed_actors],
                            "evidence": [ev.get("id") for ev in event_evidence],
                            "affected_process_step": target_id,
                            "suggestion": "review actor authorization",
                        })
                continue
            if optional:
                classification = "OPTIONAL_VARIATION"
                result_status = "PERMITTED_VARIATION"
            elif has_label(target, "Evidence"):
                classification = "MISSING_EVIDENCE"
                result_status = "VIOLATION" if status in MISSING_STATES else "UNKNOWN"
            else:
                classification = "MISSING_REQUIRED_STEP"
                result_status = "VIOLATION" if status in MISSING_STATES else "UNKNOWN"
            severity = str(edge.properties.get("severity") or ("LOW" if optional else "HIGH"))
            drift.append({
                "policy_id": pid,
                "expected_requirement": target,
                "observed_behavior": {"status": status, "events": event_evidence},
                "classification": classification,
                "status": result_status,
                "severity": severity,
                "expected_path": path_text(edge),
                "observed_path": [f"{ev.get('id')}-[:ABOUT]->{target_id}" for ev in event_evidence],
                "evidence": [ev.get("id") for ev in event_evidence],
                "affected_process_step": target_id,
                "suggestion": "review required policy step" if not optional else "document permitted variation",
            })

        # Optional structured approval expectation on Policy.  Approval is evaluated against
        # each governed operation, not against process start.  It may validly precede the
        # operation, but an approval first appearing after execution cannot satisfy it retroactively.
        if bool(policy.get("requires_owner_approval") or policy.get("requires_approval")):
            approved: list[GraphEdge] = []
            late_or_inapplicable: list[GraphEdge] = []
            missing_approval_targets: list[str] = []
            for governed_edge in governed_edges:
                governed = snapshot.node(governed_edge.target)
                if not governed:
                    continue
                gid = str(governed.get("id"))
                container_edges = [
                    edge for edge in snapshot.incoming.get(gid, [])
                    if edge.type == "CONTAINS" and PolicyDriftService._edge_overlaps_window(edge, process_start_us, process_end_us)
                ]
                operation_time_us = PolicyDriftService._operation_time_us(
                    snapshot, governed_edge, governed, container_edges, process, process_start_us, process_end_us
                )
                candidate_approvals = [edge for edge in snapshot.outgoing.get(gid, []) if edge.type == "APPROVED_BY"]
                for container_edge in container_edges:
                    candidate_approvals.extend(edge for edge in snapshot.outgoing.get(container_edge.source, []) if edge.type == "APPROVED_BY")
                accepted_for_target: list[GraphEdge] = []
                rejected_for_target: list[GraphEdge] = []
                for approval in candidate_approvals:
                    if operation_time_us is not None and PolicyDriftService._relationship_active_at_us(approval, operation_time_us):
                        accepted_for_target.append(approval)
                    else:
                        rejected_for_target.append(approval)
                approved.extend(accepted_for_target)
                late_or_inapplicable.extend(rejected_for_target)
                if not accepted_for_target:
                    missing_approval_targets.append(gid)
                approval_observations.append({
                    "governed_target_id": gid,
                    "operation_time_us": operation_time_us,
                    "approvals": [path_text(edge) for edge in accepted_for_target],
                    "late_or_inapplicable_approvals": [path_text(edge) for edge in rejected_for_target],
                })
            if missing_approval_targets:
                drift.append({
                    "policy_id": pid,
                    "expected_requirement": {"type": "APPROVAL", "scope": sorted(missing_approval_targets)},
                    "observed_behavior": {
                        "approvals": [],
                        "late_or_inapplicable_approvals": [path_text(edge) for edge in late_or_inapplicable],
                    },
                    "classification": "MISSING_APPROVAL",
                    "status": "VIOLATION",
                    "severity": "HIGH",
                    "expected_path": f"{pid}.requires_approval=true",
                    "observed_path": [],
                    "evidence": [],
                    "affected_process_step": scope_id,
                    "suggestion": "obtain required authority approval",
                })

        # Explicit prohibited governed targets. GOVERNS{allowed:false} is treated as a structured control.
        observed_action_ids = set()
        for step in process["steps"]:
            for about_id in step.get("about_ids", []):
                node = snapshot.node(about_id)
                if node and has_label(node, "Action"):
                    observed_action_ids.add(about_id)
        for edge in governed_edges:
            if edge.properties.get("allowed") is False and edge.target in observed_action_ids:
                drift.append({
                    "policy_id": pid,
                    "expected_requirement": {"prohibited": edge.target},
                    "observed_behavior": {"action_id": edge.target},
                    "classification": "BYPASSED_CONTROL",
                    "status": "VIOLATION",
                    "severity": str(edge.properties.get("severity") or "HIGH"),
                    "expected_path": path_text(edge),
                    "observed_path": [f"Event-[:ABOUT]->{edge.target}"],
                    "evidence": [],
                    "affected_process_step": edge.target,
                    "suggestion": "review prohibited transition/control bypass",
                })

        allowed_action_ids = set(policy.get("allowed_action_ids") or [])
        required_action_ids = {str(r["target"].get("id")) for r in requirements if has_label(r["target"], "Action")}
        if allowed_action_ids:
            for action_id in sorted(observed_action_ids - allowed_action_ids - required_action_ids):
                drift.append({
                    "policy_id": pid,
                    "expected_requirement": {"allowed_action_ids": sorted(allowed_action_ids)},
                    "observed_behavior": {"unexpected_action_id": action_id},
                    "classification": "UNEXPECTED_STEP",
                    "status": "DEVIATION",
                    "severity": "MEDIUM",
                    "expected_path": f"{pid}.allowed_action_ids",
                    "observed_path": [f"Event-[:ABOUT]->{action_id}"],
                    "evidence": [],
                    "affected_process_step": action_id,
                    "suggestion": "review unexpected process variation",
                })

        # Decisions may explicitly cite a policy version. Flag a version that was not valid for the process time.
        process_about = {about for step in process["steps"] for about in step.get("about_ids", [])}
        for decision_id in sorted(x for x in process_about if has_label(snapshot.node(x), "Decision")):
            for edge in snapshot.edges_from(decision_id, {"BASED_ON"}, as_of=as_of):
                used = snapshot.node(edge.target)
                if not used or not has_label(used, "Policy") or edge.target == pid:
                    continue
                same_family = (used.get("policy_family") or used.get("name")) == (policy.get("policy_family") or policy.get("name"))
                if same_family and not PolicyDriftService._policy_active(used, process_time):
                    drift.append({
                        "policy_id": pid,
                        "expected_requirement": {"active_policy_id": pid},
                        "observed_behavior": {"used_policy_id": edge.target},
                        "classification": "OUTDATED_POLICY_USAGE",
                        "status": "VIOLATION",
                        "severity": "HIGH",
                        "expected_path": f"active policy at {process_time}: {pid}",
                        "observed_path": [path_text(edge)],
                        "evidence": [],
                        "affected_process_step": decision_id,
                        "suggestion": "review decision against policy version valid at decision time",
                    })

        # Ordering constraints are graph semantics, never inferred from prose.
        expected_ids = {str(r["target"].get("id")) for r in requirements}
        expected_order = []
        for edge in snapshot.edges:
            if edge.type not in {"BEFORE", "REQUIRES"} or not snapshot._edge_active(edge, process_time or as_of):
                continue
            if edge.source in expected_ids and edge.target in expected_ids:
                # REQUIRES direction: source requires target, therefore target must occur first.
                first, second = (edge.target, edge.source) if edge.type == "REQUIRES" else (edge.source, edge.target)
                expected_order.append((first, second, edge))
        for first, second, edge in expected_order:
            n1, n2 = snapshot.node(first) or {}, snapshot.node(second) or {}
            t1, t2 = node_timestamp_us(n1, "completed_at", "occurred_at", "created_at"), node_timestamp_us(n2, "completed_at", "occurred_at", "created_at")
            if t1 is not None and t2 is not None and t2 < t1:
                drift.append({
                    "policy_id": pid,
                    "expected_requirement": {"before": first, "after": second},
                    "observed_behavior": {"before_time": n1.get("completed_at") or n1.get("created_at"), "after_time": n2.get("completed_at") or n2.get("created_at")},
                    "classification": "ORDER_VIOLATION",
                    "status": "VIOLATION",
                    "severity": "HIGH",
                    "expected_path": path_text(edge),
                    "observed_path": [],
                    "evidence": [],
                    "affected_process_step": second,
                    "suggestion": "restore required ordering",
                })
        return {
            "scope_id": scope_id,
            "policy": policy,
            "policy_selection": selection_note or "REQUESTED_VERSION_ACTIVE",
            "process_time": process_time,
            "process_start": process_start,
            "process_end": process_end,
            "expected_process": {
                "requirements": [{"entity": x["target"], "path": path_text(x["edge"]), "optional": x["optional"]} for x in requirements],
                "governed_targets": governed_targets,
                "approval_observations": approval_observations,
            },
            "observed_process": process,
            "drift": drift,
            "summary": {
                "violations": sum(1 for x in drift if x["status"] == "VIOLATION"),
                "deviations": sum(1 for x in drift if x["status"] == "DEVIATION"),
                "permitted_variations": sum(1 for x in drift if x["status"] == "PERMITTED_VARIATION"),
                "unknown": sum(1 for x in drift if x["status"] == "UNKNOWN"),
            },
            "graph_required": True,
        }

    def analyze(self, scope_id: str, policy_id: str, *, as_of: str | None = None) -> dict[str, Any] | None:
        return self.analyze_from_snapshot(GraphSnapshot.load(self.client), scope_id, policy_id, as_of=as_of)
