# VERINEX — Codex Engineering Handoff
## Live verification, failure reproduction, conditional fixes, and acceptance evidence

**Date:** 2026-10-21  
**Work type:** Implement and EXECUTE live tests, fix reproducible defects, report verified results.  
**Target:** `GraphRAG-System-main (4)(1).zip` / the user's checked-out VERINEX repository.  
**Prerequisite artifact:** `VERINEX_Agent_Coordination_Fixes.patch` OR `VERINEX_Agent_Coordination_Fix_Pack.zip` (the previously produced offline fix).  
**This document is a specification/handoff, not a claim that any of the live checks passed.**

---

## 1. Your mission (read before making changes)

You are Codex working inside the VERINEX repository. **Do not stop after writing tests, and do not report a test as passed because a mocked adapter succeeded.** Establish live FalkorDB verification of agent-to-agent context transfer. In addition, distinguish the separate capabilities of HTTP orchestration, deterministic specialist execution, and **fully automatic supervisor-driven multi-agent delegation**. Implement narrowly scoped, evidence-backed repairs for anything you reproduce as broken; if a capability does not exist, say `NOT_IMPLEMENTED`, and implement it only where the requirements below explicitly call for it.

**Primary acceptance story:** An Investigator handling a checkout incident produces a finding supported by a specific log. Its handoff is validated and accepted by a different Verifier. The Verifier reads the **recipient task's accepted handoff context** and uses the exact finding/evidence from Agent 1 to issue a recorded verification. No unrelated, unapproved, stale, or unauthorized context may be substituted.

### Correct result classifications

For every test, report one of:

- `PASS_LIVE_DB`: actually executed against a running FalkorDB, with graph reads/writes and assertions.
- `PASS_API`: actually exercised a running API with authentication, connected to live FalkorDB.
- `PASS_AGENT_E2E`: the second *worker* actually consumed delivered context and acted on it; trace proves the data read, not merely that a direct verification function was called with a hard-coded ID.
- `PASS_AUTONOMOUS_E2E`: coordinator/supervisor initiated both workers and the handoff/continuation without manually calling each successive step; optionally model-backed, as explicitly labeled.
- `PASS_OFFLINE_ONLY`: mocks/scripted provider; useful but **does not satisfy a live gate**.
- `FAIL`: assertion failed and evidence saved.
- `NOT_IMPLEMENTED`: needed capability absent; do not substitute a manual chain.
- `BLOCKED_ENVIRONMENT` / `SKIPPED`: services/credentials unavailable or tests skipped; **not a pass**.

Do not silently downgrade missing/live tests to unit tests. Do not invent provider runs, graph query results, screenshots, or test outcomes.

---

## 2. Known evidence and current code baseline

The earlier offline run found seven handoff-contract failures. After applying the previous patch, 14 targeted tests passed; a non-integration backend run reported 498 passed and 299 deselected; four live FalkorDB handoff integration tests were **skipped** because the driver was unavailable in that run. These values are a **historical offline baseline only**, not results to cite as new live verification.

### Confirm these exact files in the checkout

| Real path | Existing responsibility | Why it matters |
|---|---|---|
| `backend/app/services/handoff_service.py` | `create_handoff`, `validate_handoff`, `accept_handoff`, `reject_handoff` | Provenance, required evidence, contract validation, state transition |
| `backend/app/services/coordination_service.py` | `claim_task`, `start_execution`, `add_finding`, `verify_finding`, `get_task_blackboard`, checkpoints and resume | Producer state and recipient's `accepted_handoff_context` |
| `backend/app/services/specialist_agent_service.py` | Bounded deterministic Investigator, Dependency Analyst and Verifier methods | Actual consumer execution, **not** autonomous supervisor |
| `backend/app/services/agent_registry_service.py` | Default agents and task eligibility | Choose correct authorized worker/task type |
| `backend/app/services/event_ledger_service.py` | Records `HANDOFF_CREATED`, `HANDOFF_ACCEPTED`, `HANDOFF_REJECTED` and finding events | Forensic trail and event consistency |
| `backend/app/graph/client.py`, `backend/app/graph/mutations.py`, `backend/app/services/phase4_graph.py` | FalkorDB client, mutations, full graph reads | Live persistence, isolation, atomicity and performance |
| `backend/app/api_v1/router.py`, `backend/app/api_v1/security.py` | `/api/v1/work/contracts`, `/api/v1/tasks/{id}/coordination-state`, auth | HTTP and recipient identity enforcement |
| `backend/app/agent_runtime/harness.py`, `backend/app/agent_runtime/store.py`, `backend/app/agent_runtime/tools.py` | Bounded **single-agent** LLM tool loop and persisted traces | Not inherently linked to Phase 6 handoff supervisor |
| `backend/tests/conftest.py` | `integration_client`, isolated test graph, `seed_all` | Live test setup and cleanup |
| `backend/tests/test_phase6_integration.py`, `backend/tests/test_phase6_api_integration.py` | Existing live Phase 6 checks | Extend rather than duplicate |
| `backend/tests/test_coordination_handoff_context.py` | 14 prior in-memory adapter tests | Preserve as fast regression coverage |
| `docs/agent_runtime_component1.md`, `docs/execution_state_machine.md` | Explicit boundary and state models | Avoid claiming an autonomous scheduler exists |

### Important distinction already established by code inspection

The endpoint `GET /api/v1/agent-runtime/status` currently returns `supports_autonomous_multi_agent_coordination: false`. `SpecialistAgentService` describes itself as bounded deterministic behavior, not an LLM supervisor. `docs/execution_state_machine.md` explicitly says there is **no autonomous scheduler**. Consequently, *a passing handoff contract or manually sequenced pair of worker calls is not proof of automatic multi-agent coordination.* Inspect the current checkout before changing this statement; never flip the capability flag unless a running coordinator and its tests justify it.

Another inspection-derived concern: accepting/rejecting a handoff checks status and then performs an independent `upsert_node`, rather than an atomic conditional state transition; a race is plausible but **has not yet been reproduced live**. `contradictory_evidence_disclosed` is a boolean, not an inventory of counter-evidence. Blackboard reads currently take a task ID, not a receiving-agent identity. These require tests before claims of correctness.

---

## 3. Preconditions, safety, and environment setup

1. Work on a fresh branch; do not force-push, reseed the user's main graph, or run the tests against production. Capture `git status`, commit hash and Python/Docker/FalkorDB versions. Keep changes isolated.
2. Confirm whether the prior four-file fix is already present: `backend/tests/test_coordination_handoff_context.py` exists AND destination task blackboard emits `accepted_handoff_context`. If missing, apply **one** prior patch/copy method and run offline tests before continuing. Never blindly overwrite newer user changes; resolve conflicts explicitly.
3. Use `docker compose up -d falkordb` (service name from `docker-compose.yml`). Confirm the server is healthy and driver is installed from `requirements.txt` (`FalkorDB==1.8.0` pinned in this snapshot). Record the resolved Docker image version; `docker-compose.yml` currently uses `falkordb/falkordb:latest`, so pin to a proven compatible version/digest in any reproducibility fix.
4. Set `FALKORDB_HOST=localhost`, `FALKORDB_PORT=6379`. **Use a disposable test graph**; `backend/tests/conftest.py` already uses a unique `company_brain_test_<uuid>` graph and deletes it in teardown. Assert the name starts with a dedicated test prefix before any deletion. Never delete `company_brain`, an Asteria demo graph, or another persistent user graph.
5. Keep secrets in local environment variables. Redact `GROQ_API_KEY`, `OPENAI_API_KEY`, tokens, raw private records and model payloads in reports. Real external-model testing is opt-in and must use synthetic, non-sensitive fixture data.
6. Existing API v1 routes are under `/api/v1` and require a principal. Legacy root routes also exist; do not confuse them. Local built-in demo tokens are development-only. API verification must use `/api/v1` and distinguish authentication of an HTTP principal from the `agent_id` supplied in the JSON body.

### Windows / PowerShell entry commands

Run from repo root (if Python/venv already configured, retain the working interpreter):

```powershell
# A) Record reproducibility metadata
git status --short
git rev-parse HEAD
python --version
docker compose version

# B) Apply the previous patch ONLY if it is not already applied
# git apply --check .\VERINEX_Agent_Coordination_Fixes.patch
# git apply .\VERINEX_Agent_Coordination_Fixes.patch

# C) Dependencies and graph
python -m pip install -r requirements.txt
docker compose up -d falkordb
docker compose ps
python scripts/apply_schema.py

# D) Offline baseline (should not depend on the live graph)
python -m pytest -q backend/tests/test_coordination_handoff_context.py
python -m pytest -q -m "not integration"

# E) EXISTING live integration (SKIPS ARE NOT A PASS)
python -m pytest -q backend/tests/test_phase6_integration.py -k handoff -rs --tb=short
python -m pytest -q backend/tests/test_phase6_api_integration.py -k handoff -rs --tb=short
```

Do not proceed to editing source just because an environment dependency is broken: diagnose graph connectivity, permissions, client incompatibility, test fixture setup and skip reasons separately. A blocked live test should be stated plainly.

---

## 4. Exact end-to-end fixture: `INCIDENT-42` (must remain deterministic)

Use a fresh unique suffix per test run for all graph IDs. Keep human-readable canonical *logical* values constant below. Create graph nodes through the existing mutation helpers in an isolated FalkorDB graph; do **not** rely on missing production data.

| Object | Required fixture value |
|---|---|
| Source task | `TASK-INCIDENT-42-{run}`; `Task.task_type = INVESTIGATE`; active owner `AGENT-P6-INVESTIGATOR` |
| Destination task | `TASK-VERIFY-42-{run}`; `Task.task_type = VERIFY_CLAIM`; verify eligibility and assign/claim to `AGENT-P6-VERIFIER` as appropriate |
| Third, unrelated task | `TASK-OTHER-99-{run}` used to test leakage |
| Evidence E1 | `E-INCIDENT-LOG-{run}`, `Evidence`, `source_ref_id = incident-42:log-901`, timestamped checkout failure logs at 09:17 UTC |
| Evidence E2 | `E-UNRELATED-{run}`, `Evidence`, `source_ref_id = incident-99:log-321`, unrelated incident |
| Finding F1 | Exact statement: `Checkout failures started after deployment dep-42 at 09:15 UTC`; confidence `0.91`; `task_id` source task; `created_by` Investigator; graph links `Investigator-[:PRODUCED]->F1`, `F1-[:ABOUT]->source task`, `F1-[:DERIVED_FROM]->E1` |
| Valid handoff | From `AGENT-P6-INVESTIGATOR` to `AGENT-P6-VERIFIER`, from source task to destination task, `artifact_ids=[F1,E1]`, `confidence_threshold=0.8`, pending until accepted |
| Verifier outcome | `VERIFIED` with rationale `incident-42:log-901 corroborates the post-deployment checkout failure timing`; preserves exact evidence provenance |

**Important:** The fixture is *synthetic*, so it validates graph/data plumbing—not the historical truth of a real checkout incident. Also: verifying that failures start after deployment does **not** prove the deployment caused them; the Verifier must not fabricate causality. For the alternate `INCONCLUSIVE` test, provide an explicit contradictory deployment/time observation and ensure it is surfaced rather than silently omitted.

### Required happy-path operations

1. `AgentRegistryService.ensure_default_agents()`; create two tasks and E1/E2 through `upsert_node`, then claim source task and start its execution.
2. `CoordinationService.add_finding(... evidence_ids=[E1])` for F1. Verify the `PRODUCED`, `ABOUT` and `DERIVED_FROM` edges from **live** graph query results.
3. `HandoffService.create_handoff(... destination_task_id=destination, artifact_ids=[F1,E1])`.
4. Assert `validate_handoff(id).valid == true`. Before acceptance: destination blackboard's `accepted_handoff_context` is empty.
5. Accept as designated Verifier (not Investigator, not Dependency Analyst). Fetch recipient task blackboard through a *new* `FalkorGraphClient`/service instance and, in a second run, through a separately started API process.
6. Inspect the actual recipient context. Assert: same F1 ID, **exact** statement, `0.91` confidence, E1 ID, exact E1 `source_ref_id`, source task ID, sender/receiver IDs, and explicit `F1-[:DERIVED_FROM]->E1` lineage; unrelated E2 must not appear.
7. The Verifier must choose F1 from the **delivered recipient blackboard**, not from a manually pre-supplied F1 parameter. Verify the finding through `SpecialistAgentService.verify_finding`, then re-read the original finding, `VALIDATED_BY` edge, and event ledger from a newly constructed client. Assert the originating task sees the persisted verified result.
8. Restart API / reopen database client and assert results remain present. Do not recreate or reseed the graph as part of this persistence assertion.

**The key nontrivial gate:** Log and assert exactly how Agent B obtains F1 from Agent A's handoff context. Invoking `verify_finding(F1)` directly without that read is NOT enough.

---

## 5. Mandatory live verification matrix

Implement under `backend/tests/test_live_agent_coordination.py` (or split into focused files), marked `@pytest.mark.integration`, using a dedicated isolated live graph fixture and actual database connections. Do not override the graph client with the in-memory fake used by `test_coordination_handoff_context.py`. Add API tests under `backend/tests/test_live_agent_coordination_api.py`, and concurrency tests under `backend/tests/test_live_agent_coordination_races.py`. Reuse `integration_client` if safe; tests must not mutate a shared graph across parallel processes without unique IDs.

| ID | What to execute on live system | Required assertion / expected result |
|---|---|---|
| **LIVE-01** | Complete Incident-42 Investigator → Verifier handoff | Correct F1/E1 source IDs and `DERIVED_FROM`, status `ACCEPTED`, recipient context retrievable after new connection |
| **LIVE-02** | API version of same flow: `/api/v1/work/contracts`, `/validation`, `/accept`, `/api/v1/tasks/{id}/coordination-state` | Authenticated HTTP responses match persisted graph, not mocked API client |
| **LIVE-03** | Verifier worker reads recipient blackboard, verifies F1 and records rationale | `VALIDATED_BY` + event present, original task sees `VERIFIED`; trace shows F1 selected from context |
| **LIVE-04** | Pending, rejected and already-finalized contracts | Pending/rejected excluded from `accepted_handoff_context`; reject→accept, accept→reject, duplicate finalized transition blocked without state/event damage |
| **LIVE-05** | Sender or finding from another task, forged producer, wrong receiver/self-handoff | Failed validation or safe rejection; no unauthorized accepted context |
| **LIVE-06** | Valid F1 with wrong E2, or E1 + additional E2 | Fails `EVIDENCE_NOT_LINKED_TO_FINDING`; unrelated evidence never crosses boundary |
| **LIVE-07** | Source has blocker, finding below threshold, branch-only unmerged finding | Validation fails with clear reason; merged/promoted finding may be tested separately |
| **LIVE-08** | Two tenant principals, forbidden reader and forged agent ID in authenticated requests | Cross-tenant and unauthorized access denied; if role permits pretending to be another agent, record `FAIL` and implement authorization binding |
| **LIVE-09** | Concurrent accept vs reject, simultaneous accept vs accept, across independent clients/processes, >=50 repetitions each with fresh contract | Exactly one legal terminal transition; no status flip; at most one corresponding terminal event; losing request conflict/defined idempotent response |
| **LIVE-10** | Concurrent duplicate create calls and retries after response loss, including reused deterministic handoff ID with different threshold/policy | No overwrite/reopening, no duplicated event; mismatched payload must be rejected, not silently reusing an earlier weaker contract |
| **LIVE-11** | Accepted handoff followed by source Evidence/Finding mutation or deletion of lineage link | Receiver can reconstruct original **as-accepted** provenance OR explicitly reports that versioning is not supported; test must reveal silent drift |
| **LIVE-12** | Finding with contradictory/refuting evidence in graph, only positive E1 in handoff, `contradictory_evidence_disclosed=true` | No false claim of complete contradiction disclosure; require explicit checks/IDs to be considered verified |
| **LIVE-13** | After acceptance invalidate E1 with `KnowledgeInvalidationService` | Receiver sees handoff/finding as stale/revalidation-needed, cannot unknowingly rely on outdated evidence |
| **LIVE-14** | Source task owner changes or original finding becomes branch-only *between validation and acceptance* | Acceptance rechecks relevant conditions; either rejects or records a clearly version-pinned consented historical state |
| **LIVE-15** | Restart during PENDING and after ACCEPTED; simulate graph timeout between transition and event record | State recoverable; no duplicate transitions/events on retries; failures classified correctly |
| **LIVE-16** | Agent execution checkpoint→pause→resume with another eligible worker and accepted handoff | Latest checkpoint/artifacts persist; no lost or wrongly replayed steps; preserve existing Phase 6 ownership constraints |
| **LIVE-17** | Recipient task access by other same-tenant agent with only `READ_GRAPH` or unintended receiver | No unauthorized disclosure of accepted artifacts in multi-agent mode; demonstrate service and API boundaries separately |
| **LIVE-18** | Evidence sets of 1/10/100, tens of concurrent handoffs on an isolated graph | Capture throughput, query count, p50/p95 latency, snapshot growth; set explicit regressions after measuring baseline, do not invent limits |
| **LIVE-19** | Genuine coordinator initiated Investigator→Verifier workflow WITHOUT test code calling each subsequent worker directly | If unsupported, report `NOT_IMPLEMENTED` and proceed to supervisor implementation described below; never call manual sequence autonomous |
| **LIVE-20** | Live provider run using configured Groq/OpenAI-compatible model, synthetic graph evidence, explicit external-model consent | Only mark `PASS_AUTONOMOUS_E2E` if the model-backed supervisor actually delegates and passes context; standalone `/agent-runtime/runs` earns at most single-agent verification |

Where a feature is not currently implemented (versions, contradiction inventory, agent binding, supervisor), write a **red test or explicit `NOT_IMPLEMENTED` record first**; then implement the narrowest correction below and rerun. Do not force unrelated semantics into the current code simply to make tests green.

---

## 6. Additional possible fixes — conditional implementation requirements

These are **hypotheses / hardening needs**, not previously live-proven defects. For each: reproduce failure, write regression test, patch, retest. Document a rejected fix if analysis shows the original behavior intentional.

### FIX-A — Atomic handoff transitions and durable events

**Why:** `handoff_service.py` currently reads `PENDING` through snapshot then separately calls `upsert_node` for ACCEPTED/REJECTED. Two workers can both see PENDING before either write completes. The subsequent event writer is also a separate operation.

**Files:** `backend/app/services/handoff_service.py`, `backend/app/services/event_ledger_service.py`; possibly `backend/app/graph/client.py`, `backend/app/graph/mutations.py` and tests.

**Implement:** Use a **single conditional server-side graph mutation** matching the exact tenant/contract and `status='PENDING'`, setting terminal state and returning the affected contract. Do not assume the graph driver/server guarantees transactionality across multiple `query()` calls. Precisely document FalkorDB behavior/version tested. Event consistency must be solved via a supported single-transaction/atomic pattern or a durable outbox/reconciliation mechanism; `HANDOFF_ACCEPTED` and `HANDOFF_REJECTED` cannot both exist for one handoff. Idempotency must use stable event keys and not use wall-clock timestamp alone. Test with separate database clients **and** separate processes, not just threads sharing one client.

**Acceptance:** 0 double-winners across >=50 rounds for accept/reject and accept/accept; exactly one effective terminal event; retry-safe crash recovery. A winning request must not be turned into a failure merely because the event write was interrupted.

### FIX-B — Frozen handoff context, revisions, and historical fidelity

**Why:** `accepted_handoff_context` currently dereferences the *current* Finding/Evidence nodes when read. If they are edited or invalidated, the receiver can see different content than was approved at acceptance.

**Files:** `handoff_service.py`, `coordination_service.py`, graph schema/mutations if required; add focused integration tests.

**Implement:** A revisioned or immutable acceptance bundle storing normalized artifact IDs, timestamps, essential content/version hashes, source-reference IDs, producer ID, evidence edges, and acceptance-time policy. Prefer compact immutable graph nodes (`HandoffBundle` / `HandoffArtifactVersion`) or equivalent artifact version objects with digest verification. Preserve readable current state **and** immutable accepted state, explicitly labeled. Do not copy secrets/binary bodies into the graph. Do not make an in-memory dict the only source of truth.

**Acceptance:** mutation of F1/E1 after acceptance cannot silently rewrite the historical bundle; re-reading after restart reproduces accepted values or returns an explicit digest violation. Optional follow-up marks current context stale.

### FIX-C — Contradiction disclosure validated from graph

**Why:** boolean `contradictory_evidence_disclosed=true` is not proof of actual disclosure.

**Files:** `handoff_service.py`, `coordination_service.py`, schema if necessary.

**Implement:** Derive a deterministic set of relevant active `CONTRADICTS` / `REFUTES` relationships (including direction and Claim vs Finding type as supported by ontology), represent disclosed counter-evidence IDs in the contract and compare expected-to-supplied evidence at validation/acceptance. Unknown completeness must be `NOT_ASSESSED`, not `FULLY_DISCLOSED`. Distinguish contradiction of *a causal hypothesis* from mere contrary timestamps; don't invent evidence.

**Acceptance:** deliberately withheld counter-evidence blocks acceptance or produces an explicit policy-governed exception with a recorded rationale, never a false complete flag.

### FIX-D — Agent identity, recipient authorization, and tenant isolation

**Why:** API routes authorize the principal's broad permission (`CLAIM_TASK`/`READ_GRAPH`) but take `agent_id` from the request body; the service cannot equate a caller with that agent. Task blackboard access is not scoped to the accepting receiver at the service signature.

**Files:** `backend/app/api_v1/security.py`, `backend/app/api_v1/router.py`, `coordination_service.py`, `specialist_agent_service.py`, `handoff_service.py` where needed.

**Implement:** Define authenticated principal→agent delegation/impersonation rules; enforce them on create/accept/reject/verify, including workers with service credentials. Add tenant and recipient-scoped context retrieval with non-agent admin/human workflows preserved explicitly. Restrict raw artifact disclosure to authorized receivers; handle revoked agent permissions. Keep existing backward-compatible public task blackboard fields only if authorization permits, otherwise introduce a scoped endpoint rather than quietly leaking data.

**Acceptance:** mismatched `agent_id`, cross-tenant IDs and wrong receiver fail with 403/409 as appropriate and do not mutate graph. A legitimate verifier and authorized human reviewer can still access necessary context.

### FIX-E — Evidence validity, stale inputs and revalidation hooks

**Why:** `validate_handoff()` checks evidence label/lineage, not every evidence lifecycle/status/validity epoch. `KnowledgeInvalidationService` can invalidate evidence after handoff.

**Files:** `handoff_service.py`, `coordination_service.py`, `knowledge_invalidation_service.py`, and related provenance models.

**Implement:** Validate active evidence and relationship effective intervals at acceptance. After invalidation/supersession, mark affected accepted handoffs as `STALE_INPUT`/`REVALIDATION_REQUIRED` (prefer a separate current-health status so immutable acceptance history stays intact), notify workflow/supervisor and require deliberate revalidation before action. Do not silently revert `ACCEPTED` to `PENDING`.

**Acceptance:** recipient can distinguish original accepted facts from current invalidated facts and cannot issue an unqualified verification relying on E1 after invalidation.

### FIX-F — Deterministic handoff identity and duplicate conflict semantics

**Why:** `stable_id` for handoff currently uses source/destination/agent/artifact identities, *not* threshold or disclosure policy. A second request with a stricter/different policy can return the older PENDING contract unchanged.

**Files:** `handoff_service.py` and API tests.

**Implement:** Explicit immutable request fingerprint including relevant policy/version fields; if same ID and identical fingerprint, return prior PENDING as idempotent response; if different fingerprint, return conflict or create a versioned new contract ID per documented rules. Never modify an accepted/rejected contract through replay.

**Acceptance:** tests distinguish identical request replay vs changed confidence threshold / disclosure flag; no downgrade or ambiguous reuse.

### FIX-G — First-class supervisor / automatic Agent 1 → Agent 2 dispatch

**Why:** Current `AgentHarness` is a bounded single-agent model/tool loop; `SpecialistAgentService` offers deterministic, manually invoked operations. Automatic supervisor/delegation is explicitly reported as unsupported.

**Status:** Treat as **new functionality**, not a regression bug. Do not claim it has been verified until built.

**Possible location:** New `backend/app/services/agent_supervisor_service.py` and a run/dispatch layer, with minimal changes to `agent_registry_service.py`, `coordination_service.py`, `handoff_service.py`, `agent_runtime/harness.py` and `/api/v1/router.py`. Reuse existing graph-backed task/execution/checkpoint/event infrastructure instead of creating a parallel in-memory source of truth.

**Required behavior:**

1. Accept a bounded goal rooted in an incident/task. Resolve eligible workers using registry and graph-backed task eligibility; assign Investigator explicitly.
2. Investigator executes (deterministic path first; optional consenting LLM provider path), emits an evidence-backed Finding and a formal Handoff. The orchestrator must not invent evidence to fill requirements.
3. Supervisor validates handoff, records the acceptance decision or awaits explicit receiver policy, resolves/claims a `VERIFY_CLAIM` task, **passes only accepted context** to Verifier, and starts that worker without caller manually invoking stage 2.
4. Verifier reads `accepted_handoff_context` in its own task context, confirms provenance and records `VERIFIED`, `REJECTED`, or `INCONCLUSIVE` with citations; optionally requests missing evidence instead of hallucinating.
5. Supervisor persists `SupervisorRun`, stage/agent IDs, handoff ID, input/output artifact IDs, transitions, correlation ID, checkpoints, failure/retry state and provenance-linked events. Restarting worker/API resumes safely without duplicate handoffs or verifications.
6. Apply bounded steps/time/tool budget and cancellation; no external side effects without existing `GovernanceService` permission. Isolate tenant data. Human approval policy for acceptance and governed remediation must remain explicit.
7. Expose honest capability/status: don't switch `supports_autonomous_multi_agent_coordination` to `true` before automatic workflow and associated live tests run. Document `DETERMINISTIC_SUPERVISOR` vs `MODEL_BACKED_SUPERVISOR` independently.

**Acceptance:** launch **one** supervisor run, let it finish, then prove from persisted trace that both worker executions and the handoff occurred without test code explicitly calling the Verifier stage. Include a controlled failure mid-handoff and verify restart/resume. Scripted provider may validate orchestration mechanics (`PASS_OFFLINE_ONLY`/`PASS_AGENT_E2E` with live DB), but label real model-backed test separately.

### FIX-H — Performance, observability and operability

**Why:** `GraphSnapshot.load()` reads a broad tenant graph and is repeatedly called during `validate`, `get_handoff`, `get_task_blackboard` and event recording. Latency and cost may rise with organizational graph size.

**Files:** `phase4_graph.py`, graph queries, service methods and instrumented tests.

**Implement only after measurement:** Selective tenant+task handoff queries, normalized structured trace (`correlation_id`, `source_task_id`, `dest_task_id`, `agent_id`, `handoff_id`, `artifact_count`, `status`, elapsed ms), duplicate/conflict counters, and safe retries. Choose throughput/performance acceptance thresholds from the baseline measurement, not guesses. Add representative 1/10/100-evidence and concurrency tests.

**Acceptance:** observable traces join Investigator→Handoff→Verifier with no secrets; no loss of context; measured regression thresholds under load.

---

## 7. Test implementation and runtime policy

- **Do not fake database success:** Use real `FalkorGraphClient`; only isolate external network/model calls with explicit fake provider tests. Fake providers can be used to test supervisor control logic, not reported as a live Groq run.
- **Integration fixture:** Create/run inside an isolated test graph; unique suffix per test. Reuse `seed_all` when relying on built-in fixture `E-003`. For Incident-42, construct E1/E2 explicitly and verify all graph mutation operations returned a row/edge. Teardown only the disposable graph created for that test or module.
- **Concurrency:** independent FalkorDB clients per worker, barriers to force overlapping operations, separate-process repetition; record winner, loser status, event count and final contract. Non-deterministic winner is okay; conflicting *terminal states* are not.
- **API authentication:** run against real running API, not only monkeypatched `_client()`. If launching uvicorn subprocess, point its configuration to the ephemeral test graph and guard against touching other graphs. Always check the API process is using the intended graph.
- **Security:** test tenant isolation through configured principals and non-shared tokens; don't put secrets in logs. Test the API even if service-level checks pass because the API takes actor IDs in the body.
- **Failure injection:** before/after state mutation, before/after event record, after accept before receiver reads, and after verifier records before acknowledgment. Simulate a kill/restart or controlled exception; don't corrupt the server's shared data.
- **Replay:** reopen a client and reboot app/worker, read persisted checkpoint, accepted artifacts, event IDs and outcome. A fresh service object in the same Python process is insufficient to establish cross-process durability.
- **Invariants:** same finding/evidence/source IDs, tenant scope, actual accepted-only context, legal state transitions, no fabricated causal inference, append-oriented auditability, bounded run/cost, no unauthorized action.
- **If unavailable:** show the exact failing command, driver/server error and `BLOCKED_ENVIRONMENT` status. Do not mark it `PASS` because older test results existed.

### Suggested run commands for newly implemented suites

```powershell
python -m pytest -q backend/tests/test_live_agent_coordination.py -m integration -rs --tb=short
python -m pytest -q backend/tests/test_live_agent_coordination_api.py -m integration -rs --tb=short
python -m pytest -q backend/tests/test_live_agent_coordination_races.py -m integration -rs --tb=short
python -m pytest -q backend/tests/test_coordination_handoff_context.py
python -m pytest -q -m "not integration"
# After implemented: run any supervisor-specific tests, plus existing Phase 6 integration tests.
python -m pytest -q backend/tests/test_phase6_integration.py backend/tests/test_phase6_api_integration.py -m integration -rs --tb=short
```

Stop with a non-success *live verification verdict* if any mandatory test was skipped or never run; tests can continue for useful diagnostics. Provide command/exit code/summary for each command.

---

## 8. Required deliverables from Codex

Create these in the repository (paths are deliverable requirements, not claims they already exist):

1. `backend/tests/test_live_agent_coordination.py` — live database acceptance/invariant tests.
2. `backend/tests/test_live_agent_coordination_api.py` — real HTTP+DB coordination tests.
3. `backend/tests/test_live_agent_coordination_races.py` — multiprocessing/concurrency, retry/event consistency tests.
4. `backend/tests/test_agent_supervisor_e2e.py` — ONLY if implementing supervisor, using live DB with fake-provider control test plus real-provider opt-in separate test.
5. Source modifications only for verified defects or explicitly requested new supervisor capabilities, with tests demonstrating **red before / green after** or a documented `NOT_IMPLEMENTED → IMPLEMENTED` capability change.
6. `reports/agent_coordination_live/verification_report.md` and `reports/agent_coordination_live/results.json` (machine-readable) recording all LIVE-01...LIVE-20 classifications, exact commands, run IDs and evidence pointers.
7. `reports/agent_coordination_live/graph_evidence.json` — sanitized IDs, paths, before/after state, event counts, lineage, execution traces (no credentials/private payloads).
8. `reports/agent_coordination_live/fix_log.md` — observed failure, root cause, touched files, why design is safe, regression test, remaining concerns. Keep a `NOT_IMPLEMENTED` register separate from true bugs.
9. `docs/agent_coordination_live_setup.md` — repeatable Windows/PowerShell instructions, Docker image + FalkorDB version, provider flags, test graph safeguards, cleanup and limitations.

Suggested machine-readable record format (values shown are **schema examples**, NOT fabricated results):

```json
{
  "test_id": "LIVE-01",
  "environment": "LIVE_FALKORDB",
  "status": "BLOCKED_ENVIRONMENT",
  "assertions": ["recipient_exact_finding", "recipient_exact_evidence_source_ref", "handoff_accepted"],
  "command": "python -m pytest ...",
  "exit_code": null,
  "test_graph": null,
  "correlation_id": null,
  "evidence_files": [],
  "blocker": "Replace with observed information; do not pre-fill PASS"
}
```

### Acceptance checklist / final reply format

Codex final response must state:

- Baseline branch/commit and whether previous patch was present or applied.
- Live graph server/client and API versions/configuration (redacted), exact isolated graph used.
- Counts of `PASS_LIVE_DB`, `PASS_API`, `PASS_AGENT_E2E`, `PASS_AUTONOMOUS_E2E`, `FAIL`, `BLOCKED_ENVIRONMENT`, `NOT_IMPLEMENTED`, `SKIPPED`; do not collapse categories.
- Incident-42 evidence-chain sample: source task → Investigator → F1 → E1; Handoff → destination task → Verifier → `VALIDATED_BY` + event IDs; confirm the receiver actually read F1 from its own workspace.
- For every failing test, the reproduction, patch, files changed and rerun output; list explicitly what remains unverified.
- Whether the system supports **(a)** manually driven handoffs, **(b)** automatic deterministic specialist delegation, **(c)** model-backed multi-agent collaboration; these are three distinct claims.
- A truthful verdict: `LIVE_HANDOFF_VERIFIED`, `LIVE_HANDOFF_FAILED`, or `LIVE_HANDOFF_BLOCKED`; separately `AUTONOMOUS_COORDINATION_VERIFIED`, `NOT_IMPLEMENTED`, `FAILED`, or `BLOCKED`.

**Definition of done:** The happy-path and negative-context checks pass against *real FalkorDB*; the HTTP and second-worker consumption tests pass; race/identity/invalidation checks have results and fixes or explicit blockers; and autonomous coordination is either implemented and verified **or clearly labeled not implemented**. Tests and logs exist in the repo. A green unit suite alone is **not** completion.
