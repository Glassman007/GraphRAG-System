# Phase 6 Governed / Idempotent Action Coordination

## Boundary

Phase 6 executes only a deterministic sandbox/mock sink. It does not connect destructive infrastructure or claim universal exactly-once semantics for arbitrary external services.

## Governance

An Agent may propose an Action, but `GovernanceService` decides whether it may execute. Evaluation uses existing graph state:

- Task ownership and execution state;
- Agent permissions and allowed action types;
- organizational owner paths from the Phase 3 routing service;
- applicable Policy `GOVERNS` edges;
- required `APPROVED_BY` relationships;
- Evidence/Question prerequisites;
- unresolved Task blockers.

Result is one of:

```text
ALLOW
DENY
REQUIRES_APPROVAL
INSUFFICIENT_EVIDENCE
```

The result includes policies, ownership/authority paths, approvals, permissions and missing requirements. An agent request to execute cannot override `DENY`.

## Practical exactly-once coordination

Logical Action identity uses an immutable idempotency key. Its deterministic `ActionAttempt` identity is derived from that key.

Attempt acquisition is performed in one FalkorDB mutation:

1. match Action and Agent;
2. `MERGE` the deterministic ActionAttempt;
3. initialize only `ON CREATE`;
4. grant executor state only when Attempt is `PENDING` or `FAILED`;
5. persist `HAS_ATTEMPT` and `PERFORMED_BY` in the same query.

This prevents a duplicate caller from overwriting an already-running attempt back to `PENDING`.

## Resource leases

Different logical Actions can still target the same System/Deployment/Change. Phase 6 therefore uses deterministic per-resource `Lock` nodes. Locks are acquired in sorted resource order with a conditional FalkorDB mutation. This:

- prevents two active leases for one resource;
- avoids lock-order inversion between multi-resource actions;
- exposes expiry for abandoned-lock detection.

FalkorDB is not treated here as a general distributed transaction manager across an arbitrary set of resources. If acquisition of a later resource fails, already-acquired Phase 6 resource leases are explicitly released and the action attempt fails. This limitation is documented rather than hidden.

## Crash windows

- **Before external call:** Attempt can return to `PENDING` after lease expiry and is safe to retry.
- **During/after possible external call:** Attempt becomes `UNKNOWN` unless the destination's idempotency/reconciliation facility can prove the outcome.
- **After confirmed idempotent sink result:** reconciliation may set `SUCCEEDED` without invoking the external side effect again.

The mock sink records invocation count and is thread-safe. Duplicate and concurrent tests require one invocation per idempotency key.
