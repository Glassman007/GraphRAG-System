# Component 5 — Governed Tool Execution (Priority 5)

**Safety invariant:** No graph claim, model completion, past memory, or agent recommendation is an authorization. `GovernedActions` is a separate trust boundary; the existing Component 1–4 read-only tools cannot call a business-side-effect connector. This implementation is **safe-by-default but not live-deployment-certified**.

## Modules and integration

- `backend/app/agent_runtime/governed.py`: strict Pydantic tool arguments and proposal schema, fixed allowlist, graph/evidence/policy preconditions, authorization rules, risk classification, read-only counterfactual preview, separate human approval, dispatch, readback, escalation, and verified action-outcome learning.
- `backend/app/agent_runtime/governed_store.py`: `GovernedAction` and immutable `GovernedActionAudit` records in tenant-isolated FalkorDB; guarded revision/status comparisons before execution; audit written atomically with each state transition.
- `backend/app/api_v1/router.py`: scoped API endpoints under `/api/v1/agent-runtime/governed/`.
- `backend/app/api_v1/security.py`: adds `APPROVE_ACTION` to permission vocabulary. The built-in development operator token **does not** have that permission, while development admin does. Neither a model nor an originating agent may self-approve.
- `frontend/src/demo/GovernedToolPanel.tsx`: create, validate, inspect, simulate, request independent review, approve/reject, conditionally execute, verify, escalate, and inspect audit events in the Demo & Scenario Explorer.
- `backend/tests/test_governed_tool_execution_component5.py`: adversarial, isolated, deterministic acceptance tests (no actual rollback).
- `backend/app/agent_runtime/reactive_store.py` (unchanged): existing `VerifiedActionOutcome` sink used after trusted connector readback, so future specialists may use actual confirmed action outcomes as evidence.

**Two explicitly registered action tools:** `deployment_rollback` (HIGH_IMPACT; target graph label `Change`) and `incident_notification` (REVERSIBLE operational notification; target graph label `Incident`). Every action has an immutable schema and a fixed server-operator-controlled HTTPS receiver. Neither tool is configured by default. Shell execution, generic HTTP URLs, arbitrary Cypher, and agent-selected connectors are not exposed. `READ_ONLY` risk does not require write execution; `IRREVERSIBLE` operations are explicitly unavailable.

## Required trust boundary

- `PROPOSE_ACTION` only proposes. If a completed supervisor run is supplied, the current authenticated principal must own it, and it must have completed, unconflicted verification and a matching remediation specialist. Citations must be backed by the verifier and the target must be related to the run's source. If no run is supplied, the proposal is a **manual_operator** proposal, not a falsely attributed AI proposal.
- Cited nodes must be current `Evidence`, not invalidated/draft/unverified, carry a source reference (or `DERIVED_FROM`), and be connected by a declared graph evidence/incident path to the target.
- The target must have the correct current graph type. An active, **authoritative**, applicable graph `Policy` with an explicit `ALLOW`/`PERMIT` effect is required. An explicit `DENY` takes precedence. When policies specify `required_approver` or `required_approver_role`, those constraints are checked against the authenticated decision-maker. Policies with revoked/draft/invalidated status do not authorize actions. No valid policy means **deny**, not default permit.
- Snapshot fingerprints cover target operational properties, evidence content, policy content/versions and relevant relationships. Approval requires the current fingerprint to match the preapproval gate, and execution checks again both before and after its durable claim. Changing policy/evidence causes a `STALE_PRECONDITION` stop.
- Human approval requires the separate authenticated principal permission `APPROVE_ACTION`. It is bound to an action, an independent approver identity and role constraints (when governed policy declares them), the graph fingerprint, a reason, and a **30-minute expiry**. The initiating subject and originating agent cannot approve their own action.
- Dispatch requires `EXECUTE_ACTION`, explicit confirmation, currently configured tool connector, and a current approval. The server builds a payload from allowlisted schema and never follows user-provided hosts, paths or arbitrary commands.
- Transition `APPROVED → EXECUTING` is an atomic FalkorDB compare-and-set, written **before** the connector call. A competing worker cannot claim an already claimed operation. After a process restart, `EXECUTING` / `OUTCOME_UNKNOWN` must be resolved by authenticated **readback**; neither state is silently retried. The receiver must also enforce the supplied `Idempotency-Key` for defense in depth.
- HTTPS POST acknowledgment produces `AWAITING_VERIFICATION`, **not** `COMPLETED`. An authenticated, operation-key-bound GET readback must return `SUCCEEDED` or `FAILED` with a receipt ID. Only then does `COMPLETED` / `FAILED` become eligible for verified outcome learning. A remote timeout is `OUTCOME_UNKNOWN` because it does not prove success or failure.
- Human escalation records a separate immutable audit event while keeping the uncertain/failed state available for future readback. A brand-new attempt needs a **new proposal, authorization, and idempotency key**, not an automatic replay. Compensation is a new governed proposal, not an implicit rollback of another action.

## Lifecycle and safety controls

```text
PROPOSED --valid evidence + authoritative allow--> PENDING_APPROVAL
PENDING_APPROVAL --different authenticated approver--> APPROVED / REJECTED
APPROVED --fresh guard + configured adapter + explicit execute--> EXECUTING
EXECUTING --verified safe ACK--> AWAITING_VERIFICATION
EXECUTING --uncertain response--> OUTCOME_UNKNOWN (no automatic retry)
AWAITING_VERIFICATION / OUTCOME_UNKNOWN / EXECUTING --trusted GET readback--> COMPLETED / FAILED
APPROVED / EXECUTING --changed evidence/policy before side effect--> STALE_PRECONDITION
OUTCOME_UNKNOWN / FAILED / STALE_PRECONDITION --authorized escalation--> human review record
```

All state revisions and audit events persist across process restarts; no in-process dictionary is used for production action history. `PROPOSED` is not itself approved, even when simulation predicts improvements.

## Configure a real adapter (not enabled automatically)

The receiver is **not implemented in this project**; deployment teams must provide their own authorized, idempotent internal webhook service and approve its use. In `.env`:

```bash
GRAPH_HACKS_GOVERNED_DEPLOYMENT_ROLLBACK_URL=https://deployment-control.example.org/actions/rollback
GRAPH_HACKS_GOVERNED_DEPLOYMENT_ROLLBACK_TOKEN=<server-side-secret>
GRAPH_HACKS_GOVERNED_DEPLOYMENT_ROLLBACK_STATUS_URL=https://deployment-control.example.org/actions/status
```

These URL values are **configuration format illustrations**, not a deployed or tested endpoint. The token never belongs in a frontend bundle. The same three environment variable suffixes apply to `INCIDENT_NOTIFICATION`. The webhook is a fixed HTTPS target; user/agent action arguments contain only validated entity IDs and text. The backend refuses direct private IP ranges and disallows redirects and cross-origin status URLs. Deployment hardening should also use trusted egress rules, narrow receiver authorization and identity, secret rotation and observable audit logs.

The receiver must implement:

1. `POST <ACTION_URL>` with `Authorization: Bearer ...`, `Idempotency-Key: <SHA256>`, JSON body containing `action_id`, `tenant_id`, `tool_id`, `target_id`, `arguments`, and `approval`. Must persist the idempotency key atomically with its actual external operation. Return JSON `{"operation_id":"...","receipt_id":"...","status":"ACCEPTED"}` after an accepted dispatch. A 200/202 or generic success text alone is insufficient.
2. `GET <STATUS_URL>/<SHA256 key>` using the configured bearer secret; must return JSON `{"operation_key":"<same key>","status":"SUCCEEDED","receipt_id":"..."}` or `FAILED` with an equivalent receipt. Until the receiver can prove an outcome, return a pending state. Do **not** fabricate outcomes to unblock the demo.
3. Verify the calling service identity, action schema, explicit approval provenance and actual deployment permissions **again at the receiver**. Graph approval cannot replace operational RBAC at the recipient.

The app does not infer success from a webhook ACK; if `STATUS_URL` is absent, readback returns pending and `COMPLETED` will not be set. If a POST times out after a side effect, verify its operation key rather than generating another POST.

## API

All endpoints require a correctly scoped API principal and tenant. The server enforces access; UI button visibility alone is insufficient.

| Method | Endpoint after `/api/v1/agent-runtime/governed` | Main permission | Meaning |
|---|---|---|---|
| GET | `/tools` | `READ_GRAPH` | List schemas, risks, configured connector status |
| GET | `/actions` | `READ_GRAPH` | List tenant-scoped action proposals |
| POST | `/actions` | `PROPOSE_ACTION`, `READ_GRAPH`, `READ_EVIDENCE` | Create an evidence-backed `PROPOSED` action; idempotency key required in body |
| GET | `/actions/{id}` | `READ_GRAPH` | Action, state, complete immutable audit trail |
| GET | `/actions/{id}/preview` | `READ_GRAPH`, `READ_ORG_ANALYTICS` | Rerun graph guard and read-only blast radius |
| POST | `/actions/{id}/request-approval` | `PROPOSE_ACTION` | Owner requests review after rechecking policy/evidence |
| POST | `/actions/{id}/approve` or `/reject` | `APPROVE_ACTION` | Independent signed-in user decision with required reason |
| POST | `/actions/{id}/execute` | `EXECUTE_ACTION` | Explicit confirmation and fresh guard, then one bounded connector dispatch |
| POST | `/actions/{id}/verify` | `EXECUTE_ACTION` | Authenticated remote result readback without retry |
| POST | `/actions/{id}/escalate` | `EXECUTE_ACTION` | Preserve human-review requirement for failed/unknown/stale action |
| POST | `/actions/{id}/learn-outcome` | `EXECUTE_ACTION` | Idempotently recover Component 4 outcome persistence after verified readback |

Example proposal schema (requires appropriate actual graph evidence and an authoritative allow policy):

```json
{
  "tool_id": "deployment_rollback",
  "target_id": "CHG-AST-ROLLBACK",
  "evidence_ids": ["EVD-AST-TRACE"],
  "arguments": {"change_id": "CHG-AST-ROLLBACK", "reason": "New trace evidence implicates the deployment"},
  "rationale": "Verified trace evidence links the deployed change with the incident impact.",
  "agent_id": "remediation_specialist",
  "supervisor_run_id": "<actual-completed-owned-supervisor-run-id>",
  "idempotency_key": "rollout-incident-rollback-2026-10-18"
}
```

This example refers to an **isolated test scenario**, not guaranteed records in the Asteria production graph. A user-entered proposal without a verified supervisor run must identify the agent as `manual_operator` and use `supervisor_run_id: null`.

## Example: Verified route-outage rollback investigation

1. The supervisor's dependency/evidence/verifier/remediation DAG investigates an incident and concludes that a specific rollout may be implicated. This is an investigatory *recommendation*; the supervisor's model has only read-only tools.
2. The authenticated owner creates a `deployment_rollback` action proposal referencing a **real, completed supervisor run**, the exact `Change` target, matching evidence IDs, and a fresh idempotency key. The API verifies the run owner, verifier corroboration, and remediation specialist; free-form prose alone is not accepted.
3. Graph checks retrieve current cited evidence, explicit authoritative policy, and relevant relationships. The counterfactual engine previews affected systems on a cloned snapshot. The proposal remains `PROPOSED` until a valid review request.
4. A separate authorized person inspects the preview, citations and impact, then approves with a recorded reason. Self-approval and unauthorized review requests are blocked.
5. An executor explicitly confirms the side effect. The backend checks fingerprint/freshness, atomically claims the execution, checks freshness again and sends one fixed-schema request to the configured receiver.
6. The receiver reports an idempotent receipt; GraphHacks records `AWAITING_VERIFICATION`. An authenticated readback establishes `SUCCEEDED` or `FAILED`, and only then creates the verified action outcome for Component 4 future reasoning. If anything is uncertain, it queues a human review rather than pretending a rollback succeeded.

## Feature accounting

| Feature | Status and exact boundary |
|---|---|
| 5.1 Registry | Implemented: two server-defined tools with strict Pydantic schemas, risks, connector configuration |
| 5.2 Graph-derived proposals | Implemented: verified evidence, bounded relationship check, optional corroborated owned supervisor run. **Not** automated extraction of typed actions from free-form LLM summary |
| 5.3 Policy | Implemented: current authoritative `Policy/GOVERNS`, explicit allow and deny precedence |
| 5.4 Risk | Implemented for `READ_ONLY`, `REVERSIBLE`, `HIGH_IMPACT`, disabled `IRREVERSIBLE` |
| 5.5 Approval | Implemented: distinct authenticated approver, optional authoritative policy named/role approver restrictions, 30-minute expiry, evidence fingerprint, self-approval denial |
| 5.6 Lifecycle | Implemented with additional safe states: `AWAITING_VERIFICATION`, `OUTCOME_UNKNOWN`, `STALE_PRECONDITION` |
| 5.7 Idempotency | Implemented: deterministic proposal ID, durable CAS execution claim, stable receiver idempotency key; sender never auto-retries uncertain effects |
| 5.8 Precondition verification | Implemented: evidence/policy fingerprint at proposal, approval and immediately before dispatch; **not** a single atomic transaction shared with the remote system |
| 5.9 Simulation | Implemented: reuse graph-only blast radius + counterfactual without canonical mutation |
| 5.10 Bounded connectors | Implemented: configured HTTPS action receiver interface, **disabled without explicit operator configuration**; no live receiver included |
| 5.11 Failures | Implemented: unknown-outcome hold, terminal verified failure, explicit human escalation; no unsafe silent replay or implicit compensation |
| 5.12 Verification | Implemented if connector supports authenticated GET readback, otherwise remains pending; not possible to certify an unconfigured external action |
| 5.13 Audit | Implemented: durable immutable event per transition, provenance, policy/evidence decisions, approvals, receipts, verified outcomes |

## Verification and production limits

```bash
python -m pytest -q backend/tests/test_governed_tool_execution_component5.py
python -m pytest -q backend/tests
cd frontend && npm ci && npm run typecheck && npm run build
```

The local backend suite and client-side TypeScript **syntax** checks pass. The actual frontend typecheck/build, FalkorDB Cypher store adapter in a live cluster, and live external receiver were **not verified** here. The separate integration test suite skips without FalkorDB, so do not interpret a passing fake-store test as live transactional or connector certification.

Remaining production hardening: trusted per-tenant egress policy and SSRF/DNS-rebinding protection at infrastructure level, complete end-to-end audit export, durable receiver-side idempotency, action rate/volume caps, approver groups/organizational policy quorum, multi-region transaction conflict tests, and operational compensation workflows. If canonical graph ingestion or policy changes between the last freshness check and the external side effect, there is still a small cross-system time-of-check/time-of-use window. To close it, implement revision preconditions at the receiver and enforce immutable version tokens end to end. No action executor should be granted a powerful real receiver solely because this test suite passes.
