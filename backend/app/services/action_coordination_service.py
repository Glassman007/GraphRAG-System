from __future__ import annotations

from dataclasses import dataclass
from threading import Lock as ThreadLock
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.graph.temporal import to_epoch_us
from backend.app.services.agent_registry_service import AgentRegistryService
from backend.app.services.coordination_service import CoordinationService
from backend.app.services.event_ledger_service import EventLedgerService
from backend.app.agent_runtime.reactive import ReactiveLearning
from backend.app.agent_runtime.reactive_store import GraphReactiveStore
from backend.app.agent_runtime.memory import AgentMemory
from backend.app.agent_runtime.memory_store import GraphMemoryStore
from backend.app.services.governance_service import GovernanceService
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase6_utils import add_seconds, now_iso, stable_id


@dataclass
class MockInvocation:
    idempotency_key: str
    payload: dict[str, Any]
    result: dict[str, Any]


class MockActionExecutor:
    """Deterministic sandbox sink. It never performs real infrastructure side effects."""

    def __init__(self):
        self.invocations: list[MockInvocation] = []
        self._by_key: dict[str, dict[str, Any]] = {}
        self._lock = ThreadLock()

    def invoke(self, idempotency_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if idempotency_key in self._by_key:
                return self._by_key[idempotency_key]
            result = {"ok": True, "external_request_id": stable_id("MOCK-REQ-", idempotency_key), "message": "sandbox action accepted"}
            self._by_key[idempotency_key] = result
            self.invocations.append(MockInvocation(idempotency_key, dict(payload), dict(result)))
            return result

    def lookup(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._by_key.get(idempotency_key)
            return dict(value) if value else None

    def invocation_count(self, idempotency_key: str | None = None) -> int:
        with self._lock:
            if idempotency_key is None:
                return len(self.invocations)
            return sum(1 for item in self.invocations if item.idempotency_key == idempotency_key)


DEFAULT_MOCK_EXECUTOR = MockActionExecutor()


class ScopedMockActionExecutor:
    """Per-service observation window over the shared deterministic mock sink.

    The underlying sink remains shared so separate API/service instances can reconcile an
    idempotent mock request.  Counts exposed through a service, however, include only
    invocations that happened after that service instance was created.  This prevents
    unrelated integration tests or requests from making a governance-denied action look as
    though it executed a side effect.
    """

    def __init__(self, sink: MockActionExecutor):
        self._sink = sink
        with sink._lock:
            self._start_index = len(sink.invocations)

    def invoke(self, idempotency_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._sink.invoke(idempotency_key, payload)

    def lookup(self, idempotency_key: str) -> dict[str, Any] | None:
        return self._sink.lookup(idempotency_key)

    def invocation_count(self, idempotency_key: str | None = None) -> int:
        with self._sink._lock:
            values = self._sink.invocations[self._start_index:]
            if idempotency_key is None:
                return len(values)
            return sum(1 for item in values if item.idempotency_key == idempotency_key)


class ActionCoordinationService:
    """Governed durable action attempts with practical idempotency coordination."""

    def __init__(self, client: FalkorGraphClient, executor: MockActionExecutor | None = None):
        self.client = client
        self.executor = executor if executor is not None else ScopedMockActionExecutor(DEFAULT_MOCK_EXECUTOR)
        self.registry = AgentRegistryService(client)
        self.coordination = CoordinationService(client)
        self.governance = GovernanceService(client)
        self.events = EventLedgerService(client)

    def _capture_action_learning(self, action_id: str) -> str | None:
        """Best effort after canonical business outcome commit; NEVER redo an action on error.

        The explicit /reactive/outcomes/{id}/learn endpoint can reconcile a failed
        post-commit capture. The caller sees a warning rather than a false failure.
        """
        try:
            memory = AgentMemory(backend=GraphMemoryStore(self.client),
                                 snapshot_factory=lambda: GraphSnapshot.load(self.client),
                                 tenant=self.client.settings.tenant_id)
            reactive = ReactiveLearning(store=GraphReactiveStore(self.client), memory=memory,
                                        snapshot_factory=lambda: GraphSnapshot.load(self.client),
                                        tenant=self.client.settings.tenant_id)
            reactive.learn_action_outcome(action_id=action_id)
            return None
        except Exception as exc:
            return 'Verified outcome capture pending reconciliation: ' + type(exc).__name__

    def propose_action(
        self,
        task_id: str,
        agent_id: str,
        *,
        action_id: str | None = None,
        name: str | None = None,
        action_type: str | None = None,
        target_ids: list[str] | None = None,
        idempotency_key: str | None = None,
        approval_required: bool | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        task = snapshot.node(task_id)
        agent = snapshot.node(agent_id)
        if not task or not has_label(task, "Task"):
            raise ValueError(f"Task not found: {task_id}")
        if not agent or not has_label(agent, "Agent"):
            raise ValueError(f"Agent not found: {agent_id}")
        if "PROPOSE_ACTION" not in str(agent.get("permissions") or "").split(","):
            raise ValueError("Agent lacks PROPOSE_ACTION permission")
        owner = (self.coordination.get_task_owner(task_id) or {}).get("owner")
        if not owner or str(owner.get("id")) != agent_id:
            raise ValueError("Only the active task owner may propose an execution action")

        if action_id:
            action = snapshot.node(action_id)
            if not action or not has_label(action, "Action"):
                raise ValueError(f"Action not found: {action_id}")
            if idempotency_key and idempotency_key != action.get("idempotency_key"):
                raise ValueError("Cannot replace an existing Action idempotency_key")
        else:
            if not name or not action_type or not idempotency_key:
                raise ValueError("name, action_type and idempotency_key are required for a new action")
            action_id = stable_id("ACT-P6-", task_id, idempotency_key)
            upsert_node(
                self.client,
                "Action",
                action_id,
                {
                    "name": name,
                    "action_type": action_type,
                    "status": "PROPOSED",
                    "idempotency_key": idempotency_key,
                    "approval_required": bool(approval_required),
                    "created_at": timestamp,
                    "proposed_at": timestamp,
                },
            )
            for target_id in target_ids or []:
                if snapshot.node(target_id):
                    upsert_relationship(self.client, action_id, "ABOUT", target_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_relationship(self.client, task_id, "PROPOSED_ACTION", action_id, {"valid_from": timestamp, "confidence": 1.0})
        upsert_relationship(self.client, agent_id, "PRODUCED", action_id, {"valid_from": timestamp, "confidence": 1.0})
        self.events.record("ACTION_PROPOSED", about_ids=[task_id, action_id], actor_id=agent_id, summary=f"Proposed {action_id}", occurred_at=timestamp)
        return {"action": GraphSnapshot.load(self.client).node(action_id), "task_id": task_id, "agent_id": agent_id}

    def _attempt_detail(self, action_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        for edge in snapshot.edges_from(action_id, {"HAS_ATTEMPT"}):
            attempt = snapshot.node(edge.target)
            if attempt and has_label(attempt, "ActionAttempt"):
                return attempt
        return None

    def _lock_resources(self, snapshot: GraphSnapshot, action_id: str) -> list[str]:
        resources: set[str] = {action_id}
        for edge in snapshot.edges_from(action_id, {"ABOUT"}):
            target = snapshot.node(edge.target)
            if has_label(target, "System") or has_label(target, "Deployment") or has_label(target, "Change"):
                resources.add(edge.target)
                if has_label(target, "Change"):
                    for changed in snapshot.edges_from(edge.target, {"CHANGED", "AFFECTS"}):
                        if has_label(snapshot.node(changed.target), "System"):
                            resources.add(changed.target)
        return sorted(resources)

    def _acquire_resource_locks(self, action_id: str, agent_id: str, *, timestamp: str, lease_seconds: int) -> dict[str, Any]:
        """Acquire deterministic per-resource leases in stable order.

        A shared lock identity per resource turns resource ownership into a conditional graph
        state transition instead of a process-local read-before-write check. Multi-resource
        acquisition is ordered lexicographically to avoid lock-order inversion. FalkorDB does
        not provide a cross-resource transaction primitive here, so partial acquisition is
        rolled back if a later resource cannot be leased.
        """
        snapshot = GraphSnapshot.load(self.client)
        resources = self._lock_resources(snapshot, action_id)
        lease_until = add_seconds(timestamp, lease_seconds)
        now_us = to_epoch_us(timestamp)
        lease_until_us = to_epoch_us(lease_until)
        acquired: list[str] = []
        try:
            for resource_id in resources:
                lock_id = stable_id("LOCK-P6-RESOURCE-", resource_id)
                result = self.client.query(
                    """
                    MATCH (resource:Entity {tenant_id:$tenant_id, id:$resource_id})
                    MATCH (agent:Entity:Agent {tenant_id:$tenant_id, id:$agent_id})
                    MERGE (l:Entity:Lock {tenant_id:$tenant_id, id:$lock_id})
                    ON CREATE SET l.name=$lock_name, l.created_at=$timestamp,
                                  l.status='AVAILABLE', l.resource_id=$resource_id
                    WITH resource, agent, l
                    WHERE l.status <> 'ACTIVE' OR l.lease_until_us IS NULL
                       OR l.lease_until_us <= $now_us OR l.action_id=$action_id
                    SET l.status='ACTIVE', l.action_id=$action_id,
                        l.owner_agent_id=$agent_id, l.acquired_at=$timestamp,
                        l.heartbeat_at=$timestamp, l.lease_until=$lease_until,
                        l.lease_until_us=$lease_until_us
                    MERGE (l)-[lr:LOCKS {edge_id:$locks_edge_id}]->(resource)
                    ON CREATE SET lr.valid_from=$timestamp, lr.confidence=1.0
                    MERGE (l)-[la:LOCKED_BY {edge_id:$locked_by_edge_id}]->(agent)
                    ON CREATE SET la.valid_from=$timestamp, la.confidence=1.0
                    RETURN l
                    """,
                    {
                        "tenant_id": self.client.settings.tenant_id,
                        "resource_id": resource_id,
                        "agent_id": agent_id,
                        "lock_id": lock_id,
                        "lock_name": f"Resource lock for {resource_id}",
                        "action_id": action_id,
                        "timestamp": timestamp,
                        "now_us": now_us,
                        "lease_until": lease_until,
                        "lease_until_us": lease_until_us,
                        "locks_edge_id": f"{lock_id}|LOCKS|{resource_id}",
                        "locked_by_edge_id": f"{lock_id}|LOCKED_BY|{agent_id}",
                    },
                )
                if not result.result_set:
                    self.events.record(
                        "CONTENTION_DETECTED",
                        about_ids=[action_id, resource_id],
                        actor_id=agent_id,
                        summary=f"Resource {resource_id} is already leased by another action",
                        occurred_at=timestamp,
                    )
                    raise ValueError(f"Resource contention detected: {resource_id}")
                acquired.append(lock_id)
                self.events.record(
                    "LOCK_ACQUIRED",
                    about_ids=[lock_id, action_id, resource_id],
                    actor_id=agent_id,
                    summary=f"Acquired {lock_id} for {resource_id}",
                    occurred_at=timestamp,
                )
        except Exception:
            for lock_id in acquired:
                self._release_lock(lock_id, agent_id, timestamp=timestamp)
            raise
        return {"lock_ids": acquired, "lease_until": lease_until, "resources": resources}

    # Compatibility helper for internal callers/tests that expected a single lock result.
    def _acquire_resource_lock(self, action_id: str, agent_id: str, *, timestamp: str, lease_seconds: int) -> dict[str, Any]:
        result = self._acquire_resource_locks(action_id, agent_id, timestamp=timestamp, lease_seconds=lease_seconds)
        return {**result, "lock_id": result["lock_ids"][0] if result["lock_ids"] else None}

    def _release_lock(self, lock_id: str, agent_id: str, *, timestamp: str) -> None:
        upsert_node(self.client, "Lock", lock_id, {"status": "RELEASED", "released_at": timestamp, "lease_until": timestamp, "lease_until_us": to_epoch_us(timestamp)})
        self.events.record("LOCK_RELEASED", about_ids=[lock_id], actor_id=agent_id, summary=f"Released {lock_id}", occurred_at=timestamp)

    def execute_action(
        self,
        action_id: str,
        agent_id: str,
        *,
        timestamp: str | None = None,
        lease_seconds: int = 60,
        simulate_crash: str | None = None,
    ) -> dict[str, Any]:
        timestamp = timestamp or now_iso()
        governance = self.governance.evaluate_action(action_id, agent_id=agent_id, as_of=timestamp)
        self.events.record(
            "ACTION_GOVERNANCE_ALLOWED" if governance["decision"] == "ALLOW" else "ACTION_GOVERNANCE_DENIED",
            about_ids=[action_id],
            actor_id=agent_id,
            summary=governance["decision"],
            occurred_at=timestamp,
            properties={"decision": governance["decision"]},
        )
        if governance["decision"] != "ALLOW":
            return {"status": "NOT_EXECUTED", "governance": governance}

        action = governance["action"]
        idempotency_key = str(action.get("idempotency_key") or "")
        if not idempotency_key:
            raise ValueError("Action requires an idempotency_key before execution")
        task = governance.get("task") or {}
        task_id = str(task.get("id") or "")
        attempt_id = stable_id("ATTEMPT-P6-", idempotency_key)
        existing = GraphSnapshot.load(self.client).node(attempt_id)
        if existing:
            state = str(existing.get("execution_state") or "").upper()
            if state == "SUCCEEDED":
                return {"status": "ALREADY_COMPLETED", "attempt": existing, "governance": governance}
            if state in {"EXECUTING", "LOCKED"}:
                return {"status": "ALREADY_RUNNING", "attempt": existing, "governance": governance}
            if state == "UNKNOWN":
                return {"status": "UNKNOWN", "attempt": existing, "governance": governance, "message": "External result is uncertain; no blind retry performed."}

        # Attempt creation + compare-and-set acquisition + graph linkage are one FalkorDB
        # mutation. A duplicate caller must never overwrite an already EXECUTING/SUCCEEDED
        # attempt back to PENDING. MERGE ON CREATE preserves the first durable state and the
        # WHERE clause grants the executor role only to PENDING/FAILED attempts.
        lease_until = add_seconds(timestamp, lease_seconds)
        result = self.client.query(
            """
            MATCH (action:Entity:Action {tenant_id:$tenant_id, id:$action_id})
            MATCH (agent:Entity:Agent {tenant_id:$tenant_id, id:$agent_id})
            MERGE (a:Entity:ActionAttempt {tenant_id:$tenant_id, id:$attempt_id})
            ON CREATE SET a.name=$attempt_name, a.action_id=$action_id,
                          a.idempotency_key=$idempotency_key, a.task_id=$task_id,
                          a.agent_id=$agent_id, a.execution_state='PENDING',
                          a.created_at=$timestamp, a.external_started=false
            WITH action, agent, a
            WHERE a.execution_state IN ['PENDING','FAILED']
            SET a.execution_state='EXECUTING', a.started_at=$timestamp,
                a.lease_until=$lease_until, a.lease_until_us=$lease_until_us,
                a.agent_id=$agent_id
            MERGE (action)-[ha:HAS_ATTEMPT {edge_id:$attempt_edge_id}]->(a)
            ON CREATE SET ha.valid_from=$timestamp, ha.confidence=1.0
            MERGE (a)-[pb:PERFORMED_BY {edge_id:$performed_edge_id}]->(agent)
            ON CREATE SET pb.valid_from=$timestamp, pb.confidence=1.0
            RETURN a
            """,
            {
                "tenant_id": self.client.settings.tenant_id,
                "action_id": action_id,
                "agent_id": agent_id,
                "attempt_id": attempt_id,
                "attempt_name": f"Attempt for {action_id}",
                "idempotency_key": idempotency_key,
                "task_id": task_id,
                "timestamp": timestamp,
                "lease_until": lease_until,
                "lease_until_us": to_epoch_us(lease_until),
                "attempt_edge_id": f"{action_id}|HAS_ATTEMPT|{attempt_id}",
                "performed_edge_id": f"{attempt_id}|PERFORMED_BY|{agent_id}",
            },
        )
        if not result.result_set:
            current = GraphSnapshot.load(self.client).node(attempt_id)
            state = str((current or {}).get("execution_state") or "")
            return {"status": "ALREADY_RUNNING" if state == "EXECUTING" else state or "NOT_ACQUIRED", "attempt": current, "governance": governance}

        try:
            lock = self._acquire_resource_locks(action_id, agent_id, timestamp=timestamp, lease_seconds=lease_seconds)
        except Exception:
            upsert_node(self.client, "ActionAttempt", attempt_id, {"execution_state": "FAILED", "finished_at": timestamp, "error": "RESOURCE_CONTENTION"})
            raise
        lock_ids = lock["lock_ids"]
        upsert_node(self.client, "ActionAttempt", attempt_id, {"lock_id": lock_ids[0] if lock_ids else None, "lock_ids": ",".join(lock_ids)})
        upsert_node(self.client, "Action", action_id, {"status": "EXECUTING"})
        self.events.record("ACTION_STARTED", about_ids=[action_id, attempt_id, *lock_ids], actor_id=agent_id, summary=f"Executing {action_id}", occurred_at=timestamp)

        if simulate_crash == "before_external":
            return {"status": "CRASH_SIMULATED_BEFORE_EXTERNAL", "attempt": GraphSnapshot.load(self.client).node(attempt_id), "lock": lock, "governance": governance}

        upsert_node(self.client, "ActionAttempt", attempt_id, {"external_started": True})
        result_payload = self.executor.invoke(idempotency_key, {"action_id": action_id, "task_id": task_id, "agent_id": agent_id})
        upsert_node(self.client, "ActionAttempt", attempt_id, {"external_request_id": result_payload.get("external_request_id")})

        if simulate_crash in {"during_external", "after_external_success"}:
            return {"status": "CRASH_SIMULATED_WITH_UNCERTAIN_EXTERNAL_RESULT", "attempt": GraphSnapshot.load(self.client).node(attempt_id), "mock_result": result_payload, "governance": governance}

        finished = now_iso()
        upsert_node(
            self.client,
            "ActionAttempt",
            attempt_id,
            {
                "execution_state": "SUCCEEDED",
                "finished_at": finished,
                "result_reference": result_payload.get("external_request_id"),
                "error": None,
            },
        )
        upsert_node(self.client, "Action", action_id, {"status": "SUCCEEDED", "executed_at": finished})
        for lock_id in lock_ids:
            self._release_lock(lock_id, agent_id, timestamp=finished)
        self.events.record("ACTION_SUCCEEDED", about_ids=[action_id, attempt_id], actor_id=agent_id, summary=f"Succeeded {action_id}", occurred_at=finished)
        learning_warning = self._capture_action_learning(action_id)
        return {"status": "SUCCEEDED", "attempt": GraphSnapshot.load(self.client).node(attempt_id), "mock_result": result_payload, "governance": governance,
                "learning_warning": learning_warning}

    def recover_action(self, action_id: str, agent_id: str, *, as_of: str | None = None, reconcile_external: bool = False) -> dict[str, Any]:
        as_of = as_of or now_iso()
        snapshot = GraphSnapshot.load(self.client)
        action = snapshot.node(action_id)
        if not action or not has_label(action, "Action"):
            raise ValueError(f"Action not found: {action_id}")
        attempt = self._attempt_detail(action_id)
        if not attempt:
            return {"status": "NO_ATTEMPT"}
        state = str(attempt.get("execution_state") or "").upper()
        if state in {"SUCCEEDED", "UNKNOWN"}:
            return {"status": state, "attempt": attempt}
        lease_until = attempt.get("lease_until")
        if state == "EXECUTING" and lease_until and to_epoch_us(str(lease_until)) > to_epoch_us(as_of):
            return {"status": "ALREADY_RUNNING", "attempt": attempt}
        if state == "EXECUTING":
            if not bool(attempt.get("external_started")):
                upsert_node(self.client, "ActionAttempt", str(attempt.get("id")), {"execution_state": "PENDING", "recovered_at": as_of, "error": "CRASH_BEFORE_EXTERNAL_CALL"})
                return {"status": "SAFE_TO_RETRY", "attempt": GraphSnapshot.load(self.client).node(str(attempt.get("id")))}
            idempotency_key = str(action.get("idempotency_key") or "")
            if reconcile_external:
                external = self.executor.lookup(idempotency_key)
                if external:
                    upsert_node(self.client, "ActionAttempt", str(attempt.get("id")), {"execution_state": "SUCCEEDED", "finished_at": as_of, "result_reference": external.get("external_request_id"), "reconciled": True})
                    upsert_node(self.client, "Action", action_id, {"status": "SUCCEEDED", "executed_at": as_of})
                    learning_warning = self._capture_action_learning(action_id)
                    return {"status": "SUCCEEDED", "attempt": GraphSnapshot.load(self.client).node(str(attempt.get("id"))), "reconciled": True,
                            "learning_warning": learning_warning}
            upsert_node(self.client, "ActionAttempt", str(attempt.get("id")), {"execution_state": "UNKNOWN", "finished_at": as_of, "error": "EXTERNAL_RESULT_UNCERTAIN"})
            upsert_node(self.client, "Action", action_id, {"status": "UNKNOWN"})
            return {"status": "UNKNOWN", "attempt": GraphSnapshot.load(self.client).node(str(attempt.get("id"))), "message": "External call may have occurred; blind retry is prohibited."}
        return {"status": state, "attempt": attempt}

    def get_action(self, action_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        action = snapshot.node(action_id)
        if not action or not has_label(action, "Action"):
            return None
        attempt = self._attempt_detail(action_id)
        locks = []
        if attempt:
            lock_ids = [x for x in str(attempt.get("lock_ids") or attempt.get("lock_id") or "").split(",") if x]
            for lock_id in lock_ids:
                lock = snapshot.node(lock_id)
                if lock:
                    locks.append(lock)
        return {"action": action, "attempt": attempt, "locks": locks, "governance": self.governance.evaluate_action(action_id)}
