from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.services.agent_registry_service import AgentRegistryService
from backend.app.services.coordination_service import CoordinationService
from backend.app.services.event_ledger_service import EventLedgerService
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase6_utils import csv, csv_list, now_iso, stable_id


class HandoffService:
    """Formal, graph-backed handoff contracts between bounded workers."""

    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self.registry = AgentRegistryService(client)
        self.coordination = CoordinationService(client)
        self.events = EventLedgerService(client)

    def create_handoff(
        self,
        source_task_id: str,
        from_agent_id: str,
        to_agent_id: str,
        *,
        artifact_ids: list[str],
        destination_task_id: str | None = None,
        confidence_threshold: float = 0.6,
        contradictory_evidence_disclosed: bool = True,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        source_task = snapshot.node(source_task_id)
        from_agent = snapshot.node(from_agent_id)
        to_agent = snapshot.node(to_agent_id)
        if not source_task or not has_label(source_task, "Task"):
            raise ValueError(f"Source task not found: {source_task_id}")
        if not from_agent or not has_label(from_agent, "Agent"):
            raise ValueError(f"Source agent not found: {from_agent_id}")
        if not to_agent or not has_label(to_agent, "Agent"):
            raise ValueError(f"Destination agent not found: {to_agent_id}")
        if destination_task_id and not has_label(snapshot.node(destination_task_id), "Task"):
            raise ValueError(f"Destination task not found: {destination_task_id}")
        if from_agent_id == to_agent_id:
            raise ValueError("Handoff sender and receiver must be different agents")
        owner_state = self.coordination.get_task_owner(source_task_id) or {}
        if (owner_state.get("owner") or {}).get("id") != from_agent_id:
            raise ValueError("Handoff sender must be the active source task owner")

        artifact_ids = list(dict.fromkeys(artifact_ids))
        for artifact_id in artifact_ids:
            artifact = snapshot.node(artifact_id)
            if not artifact or not ({"Finding", "Evidence"} & set(artifact.get("_labels") or [])):
                raise ValueError(f"Handoff artifact must be Finding or Evidence: {artifact_id}")

        source_type = str(from_agent.get("agent_type") or "")
        dest_type = str(to_agent.get("agent_type") or "")
        contract_type = f"{source_type}_TO_{dest_type}"
        required_kinds = ["FINDING", "EVIDENCE"] if contract_type == "INVESTIGATOR_TO_VERIFIER" else ["FINDING"]
        handoff_id = stable_id(
            "HANDOFF-P6-",
            source_task_id,
            destination_task_id or source_task_id,
            from_agent_id,
            to_agent_id,
            ",".join(sorted(artifact_ids)),
        )
        prior = snapshot.node(handoff_id)
        if prior and has_label(prior, "Handoff"):
            # Stable identifiers must not reopen a rejected/accepted contract.
            if str(prior.get("status") or "").upper() != "PENDING":
                raise ValueError("A finalized handoff cannot be recreated or reopened")
            return self.get_handoff(handoff_id) or {"handoff_id": handoff_id}
        upsert_node(
            self.client,
            "Handoff",
            handoff_id,
            {
                "name": f"{source_type} to {dest_type} handoff",
                "status": "PENDING",
                "contract_type": contract_type,
                "contract_version": "phase6-v1",
                "source_task_id": source_task_id,
                "destination_task_id": destination_task_id,
                "from_agent_id": from_agent_id,
                "to_agent_id": to_agent_id,
                "required_artifacts": csv(required_kinds),
                "confidence_threshold": confidence_threshold,
                "contradictory_evidence_disclosed": bool(contradictory_evidence_disclosed),
                "created_at": timestamp,
            },
        )
        upsert_relationship(
            self.client,
            handoff_id,
            "HANDOFF_FOR",
            source_task_id,
            {"valid_from": timestamp, "confidence": 1.0, "role": "SOURCE"},
        )
        if destination_task_id and destination_task_id != source_task_id:
            upsert_relationship(
                self.client,
                handoff_id,
                "HANDOFF_FOR",
                destination_task_id,
                {"valid_from": timestamp, "confidence": 1.0, "role": "DESTINATION"},
            )
        upsert_relationship(self.client, handoff_id, "ASSIGNED_TO", to_agent_id, {"valid_from": timestamp, "confidence": 1.0})
        for artifact_id in artifact_ids:
            upsert_relationship(self.client, handoff_id, "REQUIRES", artifact_id, {"valid_from": timestamp, "required": True, "confidence": 1.0})
            upsert_relationship(self.client, handoff_id, "DERIVED_FROM", artifact_id, {"valid_from": timestamp, "confidence": 1.0})
        self.events.record(
            "HANDOFF_CREATED",
            about_ids=[handoff_id, source_task_id, *( [destination_task_id] if destination_task_id else [])],
            actor_id=from_agent_id,
            summary=f"Created {contract_type} handoff",
            occurred_at=timestamp,
        )
        return self.get_handoff(handoff_id) or {"handoff_id": handoff_id}

    def get_handoff(self, handoff_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        handoff = snapshot.node(handoff_id)
        if not handoff or not has_label(handoff, "Handoff"):
            return None
        tasks = []
        receiver = None
        artifacts = []
        for edge in snapshot.edges_from(handoff_id):
            if edge.type == "HANDOFF_FOR":
                tasks.append({"task": snapshot.node(edge.target), "role": edge.properties.get("role")})
            elif edge.type == "ASSIGNED_TO":
                receiver = snapshot.node(edge.target)
            elif edge.type == "REQUIRES":
                artifacts.append(snapshot.node(edge.target))
        return {"handoff": handoff, "tasks": [x for x in tasks if x["task"]], "receiver": receiver, "artifacts": [x for x in artifacts if x]}

    def validate_handoff(self, handoff_id: str) -> dict[str, Any]:
        detail = self.get_handoff(handoff_id)
        if detail is None:
            return {"valid": False, "errors": ["HANDOFF_NOT_FOUND"], "warnings": [], "missing_fields": [], "missing_evidence": [], "unresolved_blockers": [], "confidence_failures": []}
        handoff = detail["handoff"]
        errors: list[str] = []
        warnings: list[str] = []
        missing_fields: list[str] = []
        missing_evidence: list[str] = []
        confidence_failures: list[dict[str, Any]] = []
        unresolved_blockers: list[dict[str, Any]] = []

        for field in ("source_task_id", "from_agent_id", "to_agent_id", "contract_type", "contract_version"):
            if not handoff.get(field):
                missing_fields.append(field)
        source_task_id = str(handoff.get("source_task_id") or "")
        required = set(csv_list(handoff.get("required_artifacts")))
        artifacts = detail["artifacts"]
        kinds = set()
        threshold = float(handoff.get("confidence_threshold") or 0.0)
        snapshot = GraphSnapshot.load(self.client)
        from_agent_id = str(handoff.get("from_agent_id") or "")
        finding_ids: set[str] = set()
        evidence_ids: set[str] = set()
        for artifact in artifacts:
            labels = set(artifact.get("_labels") or [])
            artifact_id = str(artifact.get("id") or "")
            if "Finding" in labels:
                kinds.add("FINDING")
                finding_ids.add(artifact_id)
                source_link = any(e.target == source_task_id for e in snapshot.edges_from(artifact_id, {"ABOUT"}))
                producer_link = any(e.source == from_agent_id for e in snapshot.edges_to(artifact_id, {"PRODUCED"}))
                if str(artifact.get("task_id") or "") != source_task_id or not source_link:
                    errors.append("FINDING_NOT_FROM_SOURCE_TASK")
                if str(artifact.get("created_by") or "") != from_agent_id or not producer_link:
                    errors.append("FINDING_NOT_PRODUCED_BY_SENDER")
                if str(artifact.get("scope") or "SHARED").upper() != "SHARED":
                    errors.append("UNMERGED_BRANCH_FINDING")
                if float(artifact.get("confidence") or 0.0) < threshold:
                    confidence_failures.append({"finding_id": artifact_id, "confidence": artifact.get("confidence"), "threshold": threshold})
            if "Evidence" in labels:
                kinds.add("EVIDENCE")
                evidence_ids.add(artifact_id)
        if finding_ids and evidence_ids:
            supported_evidence = {
                edge.target
                for fid in finding_ids
                for edge in snapshot.edges_from(fid, {"DERIVED_FROM"})
            }
            if not evidence_ids.issubset(supported_evidence):
                errors.append("EVIDENCE_NOT_LINKED_TO_FINDING")
        for expected in sorted(required - kinds):
            missing_evidence.append(expected)
        if str(handoff.get("contract_type")) == "INVESTIGATOR_TO_VERIFIER" and not bool(handoff.get("contradictory_evidence_disclosed")):
            errors.append("CONTRADICTORY_EVIDENCE_NOT_DISCLOSED")
        if source_task_id:
            unresolved_blockers = self.coordination.get_unresolved_blockers(source_task_id)
        if unresolved_blockers:
            errors.append("UNRESOLVED_BLOCKERS")
        if missing_fields:
            errors.append("MISSING_REQUIRED_FIELDS")
        if missing_evidence:
            errors.append("MISSING_REQUIRED_EVIDENCE")
        if confidence_failures:
            errors.append("CONFIDENCE_BELOW_THRESHOLD")
        if not detail.get("receiver"):
            errors.append("DESTINATION_AGENT_NOT_LINKED")
        valid = not errors
        return {
            "handoff_id": handoff_id,
            "valid": valid,
            "errors": list(dict.fromkeys(errors)),
            "warnings": warnings,
            "missing_fields": missing_fields,
            "missing_evidence": missing_evidence,
            "unresolved_blockers": unresolved_blockers,
            "confidence_failures": confidence_failures,
            "graph_paths": [
                f"{handoff_id}-[:HANDOFF_FOR]->{source_task_id}" if source_task_id else None,
                *[f"{handoff_id}-[:REQUIRES]->{artifact.get('id')}" for artifact in artifacts],
            ],
        }

    def accept_handoff(self, handoff_id: str, agent_id: str, *, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        validation = self.validate_handoff(handoff_id)
        if not validation["valid"]:
            raise ValueError(f"Handoff cannot be accepted because its contract is invalid: {', '.join(validation['errors'])}")
        detail = self.get_handoff(handoff_id)
        assert detail is not None
        receiver = detail.get("receiver") or {}
        if str(receiver.get("id")) != agent_id:
            raise ValueError("Only the designated receiver may accept the handoff")
        handoff = detail["handoff"]
        if str(handoff.get("status") or "").upper() != "PENDING":
            raise ValueError("Only a PENDING handoff can be accepted")
        upsert_node(self.client, "Handoff", handoff_id, {"status": "ACCEPTED", "completed_at": timestamp, "accepted_by": agent_id})
        self.events.record("HANDOFF_ACCEPTED", about_ids=[handoff_id, str(handoff.get("source_task_id"))], actor_id=agent_id, summary=f"Accepted {handoff_id}", occurred_at=timestamp)
        return {"handoff": GraphSnapshot.load(self.client).node(handoff_id), "validation": validation}

    def reject_handoff(self, handoff_id: str, agent_id: str, *, reason: str, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        detail = self.get_handoff(handoff_id)
        if detail is None:
            raise ValueError(f"Handoff not found: {handoff_id}")
        receiver = detail.get("receiver") or {}
        if str(receiver.get("id")) != agent_id:
            raise ValueError("Only the designated receiver may reject the handoff")
        if str(detail["handoff"].get("status") or "").upper() != "PENDING":
            raise ValueError("Only a PENDING handoff can be rejected")
        upsert_node(self.client, "Handoff", handoff_id, {"status": "REJECTED", "completed_at": timestamp, "rejection_reason": reason, "rejected_by": agent_id})
        self.events.record("HANDOFF_REJECTED", about_ids=[handoff_id], actor_id=agent_id, summary=reason, occurred_at=timestamp)
        return {"handoff": GraphSnapshot.load(self.client).node(handoff_id)}
