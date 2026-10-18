from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.graph.temporal import to_epoch_us
from backend.app.services.agent_registry_service import AgentRegistryService
from backend.app.services.event_ledger_service import EventLedgerService
from backend.app.services.phase3_utils import node_dict
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase6_utils import csv, csv_list, now_iso, stable_id
from backend.app.services.work_planning_service import WorkPlanningService


ACTIVE_CLAIM_TASK_STATUSES = {"OPEN", "READY"}
ACTIVE_EXECUTION_STATUSES = {"RUNNING", "PAUSED", "BLOCKED"}
TERMINAL_EXECUTION_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
TERMINAL_FINDING_STATUSES = {"VERIFIED", "REJECTED"}


class CoordinationService:
    """Persistent FalkorDB-backed coordination and blackboard primitives for Phase 6."""

    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self.registry = AgentRegistryService(client)
        self.events = EventLedgerService(client)

    @staticmethod
    def _active_claims(snapshot: GraphSnapshot, task_id: str, *, as_of: str | None = None) -> list[dict[str, Any]]:
        as_of = as_of or now_iso()
        claims = []
        for edge in snapshot.edges_from(task_id, {"CLAIMED_BY"}, as_of=as_of):
            owner = snapshot.node(edge.target)
            if owner and has_label(owner, "Agent"):
                claims.append({"agent": owner, "relationship": edge.properties, "path": f"{task_id}-[:CLAIMED_BY]->{edge.target}"})
        return claims

    def get_task_owner(self, task_id: str, *, as_of: str | None = None) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        task = snapshot.node(task_id)
        if not task or not has_label(task, "Task"):
            return None
        claims = self._active_claims(snapshot, task_id, as_of=as_of)
        return {
            "task": task,
            "owner": claims[0]["agent"] if len(claims) == 1 else None,
            "active_claims": claims,
            "conflict": len(claims) > 1,
        }

    def _mark_ready_if_computable(self, task_id: str, *, timestamp: str) -> dict[str, Any]:
        readiness = WorkPlanningService(self.client).get_task_readiness(task_id)
        if readiness is None:
            raise ValueError(f"Task not found: {task_id}")
        if not readiness["ready"]:
            raise ValueError(f"Task is not ready: {', '.join(readiness['reason_codes'])}")
        task = readiness["task"]
        if str(task.get("status") or "OPEN").upper() == "OPEN":
            upsert_node(self.client, "Task", task_id, {"status": "READY", "ready_since": task.get("ready_since") or timestamp})
        return readiness

    def claim_task(self, task_id: str, agent_id: str, *, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        self.registry.ensure_default_agents(timestamp=timestamp)
        readiness = self._mark_ready_if_computable(task_id, timestamp=timestamp)
        eligibility = self.registry.check_task_eligibility(task_id, agent_id)
        if not eligibility["eligible"]:
            raise ValueError(f"Agent is not eligible: {', '.join(eligibility['reason_codes'])}")

        # Active ownership is acquired in one FalkorDB mutation. This is stronger than a
        # process-local read/then-write sequence; postcondition checks still detect any
        # server-level race if an installation does not serialize conflicting writes.
        edge_id = f"{task_id}|CLAIMED_BY|{agent_id}|{timestamp}"
        result = self.client.query(
            """
            MATCH (t:Entity:Task {tenant_id:$tenant_id, id:$task_id})
            MATCH (a:Entity:Agent {tenant_id:$tenant_id, id:$agent_id})
            OPTIONAL MATCH (t)-[existing:CLAIMED_BY]->(other:Entity:Agent)
            WHERE existing.valid_until IS NULL
            WITH t, a, collect(other) AS active_owners
            WHERE size(active_owners) = 0 AND t.status IN ['OPEN','READY']
            SET t.status = 'CLAIMED', t.claimed_at = $timestamp,
                t.claim_attempts = coalesce(t.claim_attempts, 0) + 1
            CREATE (t)-[r:CLAIMED_BY {edge_id:$edge_id, valid_from:$timestamp, confidence:1.0}]->(a)
            RETURN t, a, r
            """,
            {
                "tenant_id": self.client.settings.tenant_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "timestamp": timestamp,
                "edge_id": edge_id,
            },
        )
        if not result.result_set:
            owner_state = self.get_task_owner(task_id) or {}
            active = owner_state.get("active_claims") or []
            if len(active) == 1 and str((active[0].get("agent") or {}).get("id")) == agent_id:
                return {"status": "ALREADY_CLAIMED", "task_id": task_id, "agent_id": agent_id, "owner": active[0]["agent"]}
            # Count losing claim attempts with an in-database increment so concurrent losers
            # cannot overwrite one another's starvation/contention diagnostic state.
            self.client.query(
                """
                MATCH (t:Entity:Task {tenant_id:$tenant_id, id:$task_id})
                SET t.claim_attempts = coalesce(t.claim_attempts, 0) + 1
                RETURN t.claim_attempts
                """,
                {"tenant_id": self.client.settings.tenant_id, "task_id": task_id},
            )
            raise ValueError("Task claim failed because another active owner or incompatible task state won the race")

        post = self.get_task_owner(task_id) or {}
        if post.get("conflict"):
            self.events.record(
                "CONTENTION_DETECTED",
                about_ids=[task_id],
                actor_id=agent_id,
                summary=f"Conflicting active claims detected after claim of {task_id}",
            )
            raise RuntimeError("Conflicting task ownership detected after conditional claim")
        self.events.record(
            "TASK_CLAIMED",
            about_ids=[task_id],
            actor_id=agent_id,
            summary=f"{agent_id} claimed {task_id}",
            occurred_at=timestamp,
        )
        return {
            "status": "CLAIMED",
            "task_id": task_id,
            "agent_id": agent_id,
            "eligibility": eligibility,
            "owner": (post.get("owner") or eligibility.get("agent")),
        }

    def transfer_claim(self, task_id: str, from_agent_id: str, to_agent_id: str, *, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        eligibility = self.registry.check_task_eligibility(task_id, to_agent_id)
        if not eligibility["eligible"]:
            raise ValueError(f"Destination agent is not eligible: {', '.join(eligibility['reason_codes'])}")
        edge_id = f"{task_id}|CLAIMED_BY|{to_agent_id}|{timestamp}"
        result = self.client.query(
            """
            MATCH (t:Entity:Task {tenant_id:$tenant_id, id:$task_id})
            MATCH (from:Entity:Agent {tenant_id:$tenant_id, id:$from_agent_id})
            MATCH (to:Entity:Agent {tenant_id:$tenant_id, id:$to_agent_id})
            MATCH (t)-[old:CLAIMED_BY]->(from)
            WHERE old.valid_until IS NULL
            SET old.valid_until = $timestamp
            CREATE (t)-[new:CLAIMED_BY {edge_id:$edge_id, valid_from:$timestamp, confidence:1.0}]->(to)
            SET t.claimed_at = $timestamp, t.status = 'CLAIMED'
            RETURN t, to, new
            """,
            {
                "tenant_id": self.client.settings.tenant_id,
                "task_id": task_id,
                "from_agent_id": from_agent_id,
                "to_agent_id": to_agent_id,
                "timestamp": timestamp,
                "edge_id": edge_id,
            },
        )
        if not result.result_set:
            raise ValueError("Claim transfer requires the source agent to be the current active owner")
        self.events.record(
            "TASK_CLAIMED",
            about_ids=[task_id],
            actor_id=to_agent_id,
            summary=f"Ownership transferred from {from_agent_id} to {to_agent_id}",
            occurred_at=timestamp,
            properties={"transferred_from": from_agent_id},
        )
        return {"status": "TRANSFERRED", "task_id": task_id, "from_agent_id": from_agent_id, "to_agent_id": to_agent_id}

    def start_execution(self, task_id: str, agent_id: str, *, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        owner = self.get_task_owner(task_id)
        if not owner or not owner.get("owner") or str(owner["owner"].get("id")) != agent_id:
            raise ValueError("Only the active task owner may start execution")
        snapshot = GraphSnapshot.load(self.client)
        existing = [
            snapshot.node(edge.target)
            for edge in snapshot.edges_from(task_id, {"HAS_EXECUTION"})
            if snapshot.node(edge.target) and str(snapshot.node(edge.target).get("status") or "").upper() in ACTIVE_EXECUTION_STATUSES
        ]
        if existing:
            return {"status": "ALREADY_STARTED", "execution": existing[0]}
        execution_id = stable_id("EXEC-P6-", task_id)
        prior = snapshot.node(execution_id)
        attempt = int((prior or {}).get("attempt") or 0) + 1
        upsert_node(
            self.client,
            "Execution",
            execution_id,
            {
                "name": f"Execution for {task_id}",
                "task_id": task_id,
                "status": "RUNNING",
                "created_at": (prior or {}).get("created_at") or timestamp,
                "started_at": timestamp,
                "current_step_index": int((prior or {}).get("current_step_index") or 0),
                "attempt": attempt,
                "last_error": None,
                "owner_agent_id": agent_id,
            },
        )
        upsert_relationship(self.client, task_id, "HAS_EXECUTION", execution_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_node(self.client, "Task", task_id, {"status": "IN_PROGRESS", "started_at": timestamp})
        self.events.record("TASK_STARTED", about_ids=[task_id, execution_id], actor_id=agent_id, summary=f"Started {execution_id}", occurred_at=timestamp)
        return self.get_execution_state(execution_id) or {"execution_id": execution_id}

    def complete_execution(self, execution_id: str, agent_id: str, *, timestamp: str | None = None) -> dict[str, Any]:
        """Complete persisted work only when Phase 5's graph-backed completion contract is satisfied."""
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        execution = snapshot.node(execution_id)
        if not execution or not has_label(execution, "Execution"):
            raise ValueError(f"Execution not found: {execution_id}")
        task_id = str(execution.get("task_id") or "")
        owner_state = self.get_task_owner(task_id)
        owner = (owner_state or {}).get("owner")
        if not owner or str(owner.get("id")) != agent_id:
            raise ValueError("Only the active task owner may complete execution")
        blockers = self.get_unresolved_blockers(task_id)
        if blockers:
            raise ValueError("Task has unresolved blockers")
        completion = WorkPlanningService(self.client).is_task_completion_satisfied(task_id)
        if not completion or not completion.get("satisfied"):
            reason = (completion or {}).get("reason") or "Task completion condition is not satisfied"
            raise ValueError(f"Task completion condition is not satisfied: {reason}")

        self.client.query(
            """
            MATCH (e:Entity:Execution {tenant_id:$tenant_id, id:$execution_id})
            MATCH (t:Entity:Task {tenant_id:$tenant_id, id:$task_id})
            SET e.status='COMPLETED', e.completed_at=$timestamp,
                t.status='COMPLETED', t.completed_at=$timestamp
            WITH e, t
            OPTIONAL MATCH (t)-[claim:CLAIMED_BY]->(:Entity:Agent {tenant_id:$tenant_id, id:$agent_id})
            WHERE claim.valid_until IS NULL
            SET claim.valid_until=$timestamp
            RETURN e, t
            """,
            {
                "tenant_id": self.client.settings.tenant_id,
                "execution_id": execution_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "timestamp": timestamp,
            },
        )
        self.events.record(
            "TASK_COMPLETED",
            about_ids=[task_id, execution_id],
            actor_id=agent_id,
            summary=f"Completed {task_id}",
            occurred_at=timestamp,
            properties={"completion_reason": str(completion.get("reason") or "")},
        )
        return {
            "status": "COMPLETED",
            "task_id": task_id,
            "execution_id": execution_id,
            "agent_id": agent_id,
            "completion": completion,
        }

    def save_checkpoint(
        self,
        execution_id: str,
        agent_id: str,
        *,
        step_index: int,
        current_step: str,
        completed_steps: list[str] | None = None,
        pending_steps: list[str] | None = None,
        state_summary: str = "",
        last_error: str | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        if step_index < 0:
            raise ValueError("step_index must be >= 0")
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        execution = snapshot.node(execution_id)
        if not execution or not has_label(execution, "Execution"):
            raise ValueError(f"Execution not found: {execution_id}")
        task_id = str(execution.get("task_id"))
        owner = self.get_task_owner(task_id)
        if not owner or not owner.get("owner") or str(owner["owner"].get("id")) != agent_id:
            raise ValueError("Only the current task owner may save a checkpoint")
        checkpoint_id = stable_id("CHK-P6-", execution_id, str(step_index), str(execution.get("attempt") or 1))
        upsert_node(
            self.client,
            "Checkpoint",
            checkpoint_id,
            {
                "name": f"Checkpoint {step_index} for {execution_id}",
                "execution_id": execution_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "step_index": step_index,
                "current_step": current_step,
                "completed_steps": csv(completed_steps),
                "pending_steps": csv(pending_steps),
                "state_summary": state_summary,
                "status": "ACTIVE",
                "created_at": timestamp,
                "attempt": int(execution.get("attempt") or 1),
                "last_error": last_error,
            },
        )
        upsert_relationship(self.client, execution_id, "HAS_CHECKPOINT", checkpoint_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_relationship(self.client, task_id, "HAS_CHECKPOINT", checkpoint_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_node(
            self.client,
            "Execution",
            execution_id,
            {"current_step_index": step_index, "current_step": current_step, "last_checkpoint_at": timestamp, "last_error": last_error},
        )
        upsert_node(self.client, "Agent", agent_id, {"last_checkpoint": checkpoint_id})
        self.events.record("CHECKPOINT_SAVED", about_ids=[task_id, execution_id, checkpoint_id], actor_id=agent_id, summary=f"Saved checkpoint {checkpoint_id}", occurred_at=timestamp)
        return {"checkpoint": GraphSnapshot.load(self.client).node(checkpoint_id), "execution_id": execution_id}

    @staticmethod
    def _latest_checkpoint(snapshot: GraphSnapshot, execution_id: str, *, include_archived: bool = False) -> dict[str, Any] | None:
        checkpoints = []
        for edge in snapshot.edges_from(execution_id, {"HAS_CHECKPOINT"}):
            node = snapshot.node(edge.target)
            if not node or not has_label(node, "Checkpoint"):
                continue
            if not include_archived and str(node.get("status") or "ACTIVE").upper() == "ARCHIVED":
                continue
            checkpoints.append(node)
        checkpoints.sort(
            key=lambda n: (int(n.get("step_index") or 0), to_epoch_us(str(n.get("created_at"))) if n.get("created_at") else 0),
            reverse=True,
        )
        return checkpoints[0] if checkpoints else None

    def get_execution_state(self, execution_id: str, *, include_archived: bool = False) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        execution = snapshot.node(execution_id)
        if not execution or not has_label(execution, "Execution"):
            return None
        task_id = str(execution.get("task_id"))
        checkpoints = []
        for edge in snapshot.edges_from(execution_id, {"HAS_CHECKPOINT"}):
            cp = snapshot.node(edge.target)
            if not cp:
                continue
            if not include_archived and str(cp.get("status") or "ACTIVE").upper() == "ARCHIVED":
                continue
            checkpoints.append(cp)
        checkpoints.sort(key=lambda n: (int(n.get("step_index") or 0), str(n.get("created_at") or "")))
        latest = self._latest_checkpoint(snapshot, execution_id, include_archived=include_archived)
        return {
            "execution": execution,
            "task": snapshot.node(task_id),
            "owner": (self.get_task_owner(task_id) or {}).get("owner"),
            "checkpoints": checkpoints,
            "latest_checkpoint": latest,
            "resume_from_step": int((latest or {}).get("step_index") or -1) + 1,
        }

    def pause_execution(self, execution_id: str, agent_id: str, *, timestamp: str | None = None) -> dict[str, Any]:
        """Conditional pause: only the currently claiming agent can pause a RUNNING execution."""
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        execution = snapshot.node(execution_id)
        if not execution or not has_label(execution, "Execution"):
            raise ValueError("Execution not found")
        task_id = str(execution.get("task_id") or "")
        owner = (self.get_task_owner(task_id) or {}).get("owner")
        if not owner or str(owner.get("id")) != agent_id:
            raise ValueError("Only the active task owner may pause execution")
        result = self.client.query(
            """
            MATCH (e:Entity:Execution {tenant_id:$tenant_id,id:$execution_id})
            MATCH (t:Entity:Task {tenant_id:$tenant_id,id:$task_id})
            MATCH (t)-[claim:CLAIMED_BY]->(:Entity:Agent {tenant_id:$tenant_id,id:$agent_id})
            WHERE claim.valid_until IS NULL AND e.status='RUNNING' AND t.status='IN_PROGRESS'
            SET e.status='PAUSED', e.paused_at=$timestamp, t.status='PAUSED'
            RETURN e.id
            """,
            {"tenant_id":self.client.settings.tenant_id,"execution_id":execution_id,"task_id":task_id,"agent_id":agent_id,"timestamp":timestamp},
        )
        if not result.result_set:
            raise ValueError("Only a running task can be paused")
        self.events.record("EXECUTION_PAUSED", about_ids=[task_id, execution_id], actor_id=agent_id,
                           summary=f"Paused execution {execution_id}", occurred_at=timestamp)
        return {"status":"PAUSED","task_id":task_id,"execution_id":execution_id,"agent_id":agent_id}

    def resume_execution(self, execution_id: str, agent_id: str, *, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        state = self.get_execution_state(execution_id, include_archived=True)
        if state is None:
            raise ValueError(f"Execution not found: {execution_id}")
        execution = state["execution"]
        if str(execution.get("status") or "").upper() not in {"PAUSED", "BLOCKED", "FAILED"}:
            raise ValueError("Resume requires a PAUSED, BLOCKED or FAILED execution")
        task_id = str(execution.get("task_id"))
        eligibility = self.registry.check_task_eligibility(task_id, agent_id)
        if not eligibility["eligible"]:
            raise ValueError(f"Agent cannot resume this task: {', '.join(eligibility['reason_codes'])}")
        blockers = self.get_unresolved_blockers(task_id)
        if blockers:
            raise ValueError("Execution cannot resume while unresolved blockers remain")
        owner = (self.get_task_owner(task_id) or {}).get("owner")
        if owner and str(owner.get("id")) != agent_id:
            self.transfer_claim(task_id, str(owner.get("id")), agent_id, timestamp=timestamp)
        elif not owner:
            self.claim_task(task_id, agent_id, timestamp=timestamp)
        latest = self._latest_checkpoint(GraphSnapshot.load(self.client), execution_id, include_archived=True)
        next_step = int((latest or {}).get("step_index") or -1) + 1
        attempt = int(execution.get("attempt") or 1) + 1
        upsert_node(
            self.client,
            "Execution",
            execution_id,
            {"status": "RUNNING", "attempt": attempt, "owner_agent_id": agent_id, "resumed_at": timestamp, "current_step_index": next_step},
        )
        upsert_node(self.client, "Task", task_id, {"status": "IN_PROGRESS"})
        self.events.record("EXECUTION_RESUMED", about_ids=[task_id, execution_id], actor_id=agent_id, summary=f"Resumed at step {next_step}", occurred_at=timestamp, properties={"resume_from_step": next_step})
        result = self.get_execution_state(execution_id, include_archived=True) or {}
        result["resume_from_step"] = next_step
        return result

    def transfer_execution(self, execution_id: str, to_agent_id: str, *, timestamp: str | None = None) -> dict[str, Any]:
        state = self.get_execution_state(execution_id, include_archived=True)
        if state is None:
            raise ValueError(f"Execution not found: {execution_id}")
        task_id = str(state["execution"].get("task_id"))
        owner = state.get("owner")
        if not owner:
            raise ValueError("Execution has no active task owner to transfer")
        self.transfer_claim(task_id, str(owner.get("id")), to_agent_id, timestamp=timestamp)
        upsert_node(self.client, "Execution", execution_id, {"owner_agent_id": to_agent_id, "status": "PAUSED"})
        return self.resume_execution(execution_id, to_agent_id, timestamp=timestamp)

    def add_finding(
        self,
        task_id: str,
        agent_id: str,
        *,
        statement: str,
        confidence: float,
        kind: str = "GENERAL",
        evidence_ids: list[str] | None = None,
        claim_ids: list[str] | None = None,
        branch_id: str | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        if not statement.strip():
            raise ValueError("Finding statement must not be empty")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        if not has_label(snapshot.node(task_id), "Task"):
            raise ValueError(f"Task not found: {task_id}")
        if not has_label(snapshot.node(agent_id), "Agent"):
            raise ValueError(f"Agent not found: {agent_id}")
        if branch_id and not has_label(snapshot.node(branch_id), "WorkBranch"):
            raise ValueError(f"Branch not found: {branch_id}")
        scope = "BRANCH" if branch_id else "SHARED"
        finding_id = stable_id("FIND-P6-", task_id, agent_id, kind, statement, branch_id or "SHARED")
        upsert_node(
            self.client,
            "Finding",
            finding_id,
            {
                "name": statement[:120],
                "statement": statement,
                "finding_kind": kind,
                "status": "OPEN",
                "confidence": confidence,
                "scope": scope,
                "task_id": task_id,
                "branch_id": branch_id,
                "created_at": timestamp,
                "created_by": agent_id,
            },
        )
        upsert_relationship(self.client, agent_id, "PRODUCED", finding_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_relationship(self.client, finding_id, "ABOUT", task_id, {"valid_from": timestamp, "confidence": 1.0})
        if branch_id:
            upsert_relationship(self.client, branch_id, "CONTAINS", finding_id, {"valid_from": timestamp, "confidence": 1.0})
        for eid in evidence_ids or []:
            if has_label(snapshot.node(eid), "Evidence"):
                upsert_relationship(self.client, finding_id, "DERIVED_FROM", eid, {"valid_from": timestamp, "confidence": 1.0})
        for cid in claim_ids or []:
            if has_label(snapshot.node(cid), "Claim"):
                upsert_relationship(self.client, finding_id, "ABOUT", cid, {"valid_from": timestamp, "confidence": 1.0})
        self.events.record("FINDING_CREATED", about_ids=[task_id, finding_id], actor_id=agent_id, summary=statement[:500], occurred_at=timestamp)
        return {"finding": GraphSnapshot.load(self.client).node(finding_id), "scope": scope}

    def verify_finding(self, finding_id: str, verifier_agent_id: str, *, result: str, rationale: str = "", timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        result = result.upper()
        if result not in {"VERIFIED", "REJECTED", "INCONCLUSIVE"}:
            raise ValueError("result must be VERIFIED, REJECTED or INCONCLUSIVE")
        agent = self.registry.get_agent(verifier_agent_id)
        if not agent or str(agent.get("agent_type")) != "VERIFIER":
            raise ValueError("Only a VERIFIER agent may validate findings")
        snapshot = GraphSnapshot.load(self.client)
        finding = snapshot.node(finding_id)
        if not finding or not has_label(finding, "Finding"):
            raise ValueError(f"Finding not found: {finding_id}")
        upsert_node(self.client, "Finding", finding_id, {"status": result, "verified_at": timestamp, "verified_by": verifier_agent_id, "validation_rationale": rationale})
        upsert_relationship(self.client, finding_id, "VALIDATED_BY", verifier_agent_id, {"valid_from": timestamp, "confidence": 1.0})
        event_type = "FINDING_VERIFIED" if result == "VERIFIED" else "FINDING_REJECTED" if result == "REJECTED" else "FINDING_VALIDATED"
        task_id = str(finding.get("task_id") or "")
        self.events.record(event_type, about_ids=[finding_id, *( [task_id] if task_id else [])], actor_id=verifier_agent_id, summary=f"{result}: {rationale}"[:500], occurred_at=timestamp)
        return {"finding": GraphSnapshot.load(self.client).node(finding_id), "result": result}

    def add_blocker(self, task_id: str, agent_id: str, *, reason: str, severity: str = "MEDIUM", timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        blocker_id = stable_id("BLOCK-P6-", task_id, reason)
        upsert_node(self.client, "Blocker", blocker_id, {"name": reason[:120], "reason": reason, "severity": severity.upper(), "status": "OPEN", "created_at": timestamp, "created_by": agent_id, "task_id": task_id})
        upsert_relationship(self.client, task_id, "BLOCKED_BY", blocker_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_relationship(self.client, blocker_id, "DISCOVERED_BY", agent_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_node(self.client, "Task", task_id, {"status": "BLOCKED"})
        self.events.record("TASK_BLOCKED", about_ids=[task_id, blocker_id], actor_id=agent_id, summary=reason, occurred_at=timestamp)
        return {"blocker": GraphSnapshot.load(self.client).node(blocker_id)}

    def resolve_blocker(self, blocker_id: str, agent_id: str, *, resolution: str, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        blocker = snapshot.node(blocker_id)
        if not blocker or not has_label(blocker, "Blocker"):
            raise ValueError(f"Blocker not found: {blocker_id}")
        upsert_node(self.client, "Blocker", blocker_id, {"status": "RESOLVED", "resolved_at": timestamp, "resolution": resolution, "resolved_by": agent_id})
        task_id = str(blocker.get("task_id") or "")
        if task_id:
            remaining = [x for x in self.get_unresolved_blockers(task_id) if str(x.get("id")) != blocker_id]
            if not remaining:
                owner = (self.get_task_owner(task_id) or {}).get("owner")
                upsert_node(self.client, "Task", task_id, {"status": "IN_PROGRESS" if owner else "READY"})
        return {"blocker": GraphSnapshot.load(self.client).node(blocker_id)}

    def add_shared_evidence(self, task_id: str, agent_id: str, evidence_id: str, *, timestamp: str | None = None) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        evidence = snapshot.node(evidence_id)
        if not evidence or not has_label(evidence, "Evidence"):
            raise ValueError(f"Evidence not found: {evidence_id}")
        upsert_relationship(self.client, evidence_id, "ABOUT", task_id, {"valid_from": timestamp, "confidence": 1.0})
        # PRODUCED is only added when the agent is actually the evidence producer; linking alone keeps provenance intact.
        self.events.record("EVIDENCE_FOUND", about_ids=[task_id, evidence_id], actor_id=agent_id, summary=f"Linked existing evidence {evidence_id} to shared task state", occurred_at=timestamp)
        return {"task_id": task_id, "evidence": evidence, "shared": True}

    def get_unresolved_blockers(self, task_id: str) -> list[dict[str, Any]]:
        snapshot = GraphSnapshot.load(self.client)
        blockers = []
        for edge in snapshot.edges_from(task_id, {"BLOCKED_BY"}):
            node = snapshot.node(edge.target)
            if node and has_label(node, "Blocker") and str(node.get("status") or "OPEN").upper() not in {"RESOLVED", "CLOSED"}:
                blockers.append(node)
        return blockers

    def get_recent_findings(self, task_id: str, *, limit: int = 20, include_branch: bool = False) -> list[dict[str, Any]]:
        snapshot = GraphSnapshot.load(self.client)
        findings = []
        for edge in snapshot.edges_to(task_id, {"ABOUT"}):
            node = snapshot.node(edge.source)
            if not node or not has_label(node, "Finding"):
                continue
            if not include_branch and str(node.get("scope") or "SHARED").upper() == "BRANCH":
                continue
            findings.append(node)
        findings.sort(key=lambda n: to_epoch_us(str(n.get("created_at"))) if n.get("created_at") else 0, reverse=True)
        return findings[:limit]

    def get_task_blackboard(self, task_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        task = snapshot.node(task_id)
        if not task or not has_label(task, "Task"):
            return None
        plan_ids = sorted(edge.source for edge in snapshot.edges_to(task_id, {"PLAN_HAS_TASK"}) if has_label(snapshot.node(edge.source), "Plan"))
        executions = [snapshot.node(edge.target) for edge in snapshot.edges_from(task_id, {"HAS_EXECUTION"}) if snapshot.node(edge.target)]
        checkpoints = [snapshot.node(edge.target) for edge in snapshot.edges_from(task_id, {"HAS_CHECKPOINT"}) if snapshot.node(edge.target) and str(snapshot.node(edge.target).get("status") or "ACTIVE").upper() != "ARCHIVED"]
        evidence = [snapshot.node(edge.source) for edge in snapshot.edges_to(task_id, {"ABOUT"}) if has_label(snapshot.node(edge.source), "Evidence")]
        handoffs = [snapshot.node(edge.source) for edge in snapshot.edges_to(task_id, {"HANDOFF_FOR"}) if has_label(snapshot.node(edge.source), "Handoff")]
        branches = [snapshot.node(edge.target) for edge in snapshot.edges_from(task_id, {"HAS_BRANCH"}) if has_label(snapshot.node(edge.target), "WorkBranch")]
        actions = [snapshot.node(edge.target) for edge in snapshot.edges_from(task_id, {"PROPOSED_ACTION"}) if has_label(snapshot.node(edge.target), "Action")]
        return {
            "task": task,
            "plan_ids": plan_ids,
            "owner_state": self.get_task_owner(task_id),
            "executions": [x for x in executions if x],
            "checkpoints": [x for x in checkpoints if x],
            "findings": self.get_recent_findings(task_id),
            "blockers": self.get_unresolved_blockers(task_id),
            "shared_evidence": [x for x in evidence if x],
            "handoffs": [x for x in handoffs if x],
            "branches": [x for x in branches if x],
            "proposed_actions": [x for x in actions if x],
            "graph_required": True,
        }

    def get_plan_blackboard(self, plan_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        plan = snapshot.node(plan_id)
        if not plan or not has_label(plan, "Plan"):
            return None
        task_ids = sorted(edge.target for edge in snapshot.edges_from(plan_id, {"PLAN_HAS_TASK"}) if has_label(snapshot.node(edge.target), "Task"))
        return {"plan": plan, "tasks": [self.get_task_blackboard(tid) for tid in task_ids], "graph_required": True}

    def get_agent_work(self, agent_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        agent = snapshot.node(agent_id)
        if not agent or not has_label(agent, "Agent"):
            return None
        owned = []
        for edge in snapshot.edges_to(agent_id, {"CLAIMED_BY"}):
            if edge.properties.get("valid_until") is None and has_label(snapshot.node(edge.source), "Task"):
                owned.append(snapshot.node(edge.source))
        produced = [snapshot.node(edge.target) for edge in snapshot.edges_from(agent_id, {"PRODUCED"}) if snapshot.node(edge.target)]
        return {"agent": agent, "owned_tasks": owned, "produced_artifacts": produced}
