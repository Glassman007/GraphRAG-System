# GraphHacks Step 3 — Work, Agent Coordination & Persistent Memory

## Baseline and design

This release extends **Step 2** and retains the Asteria v1 and Northstar fixtures, FalkorDB as the canonical graph, FastAPI/tenant-scoped authorization, and the merged Matrix / Read the Rain frontend. It does **not** reseed or reset either graph. Existing Plans, Tasks and Agents tabs remain; Work now also includes Memory and Action Governance.

## Implemented capabilities

| Request | Implemented behavior | Boundary |
|---|---|---|
| 22 | Existing plans/tasks/agents operations preserved and reorganized | Same backend auth and task state machine |
| 23 | Rich task objective, priority, output, owner, prerequisites, evidence, assigned candidates, checkpoints, events and outcomes | Only fields recorded in graph are shown |
| 24 | Plan DAG graph, parallel execution waves, blocked tasks, cycle detection, potential exact-objective duplicates, longest dependency chain | Longest chain is **not** duration-based critical path (durations unknown) |
| 25 | Agent task-type eligibility, capabilities, permissions, tools, current assigned work, and selected agent assignment through existing claim/start API | No automatic assignment or permission bypass |
| 26 | Generate plan from scenario incident; coordinate specialist task claims and branch findings, verify/merge results | User-guided; **not** a fully autonomous multi-agent scheduler |
| 27 | Graph-persisted checkpoint/artifact memory with provenance, timestamps, status, validity and declared sharing scope | Not LLM conversation memory; branch-private findings withheld from new read endpoints; tenant-wide READ_GRAPH is not per-agent ACL |
| 28 | Pause, resume, retry FAILED execution, checkpoint inspection, formal handoff validation/accept/reject | Retry resumes graph execution state; **does not rerun external actions** |
| 29 | Explicit CONTRADICTS edges, conflicting active claims, unresolved blockers, cycle/duplicate detection, verifier outcomes and blocker resolution | No speculative semantic contradiction detector |
| 30 | Work action list, governance results, attempts; optional user-confirmed governed execution | Reuses existing backend governance, locks, idempotency and mock executor; no auto-approval |
| 31 | Historical execution timeline (recorded events), checkpoint history, planned vs actual outputs and attempts | No estimated duration projection |
| 32 | Select Asteria scenarios containing Incident entries; create a graph-derived plan; canonical ID remains editable | Scenario starting system-only cases require manual situation selection |

## New APIs (under /api/v1)

**Read only — READ_GRAPH**
- `GET /work/plans/{plan_id}/topology` – ordered waves, recorded prerequisite edges, blocked tasks, exact duplicate suggestions, event history, longest dependency chain; `cycle_detected` and a **false** `longest_dependency_chain_is_duration_critical_path` marker.
- `GET /work/tasks/{task_id}/insights` – task owner, evidence, candidate agents, executions, checkpoints, findings, handoffs, branches, blockers, explicit conflicts, ledger timeline and expected vs actual outputs.
- `GET /work/tasks/{task_id}/agent-matches` – eligible agents, reason codes; never claims a task.
- `GET /work/agents/{agent_id}/memory` – persisted produced artifacts/checkpoints and lineage. Branch-private findings not exposed here.
- `GET /work/contracts/{contract_id}/validation` – validates formal handoff requirements.

**Mutating — require CALLER permission and existing backend service state**
- `POST /tasks/{task_id}/pause` (CLAIM_TASK) – conditional pause for a current owner with RUNNING execution.
- `POST /tasks/{task_id}/retry` (CLAIM_TASK) – only FAILED executions; retries graph execution state.
- `POST /tasks/{task_id}/transfer` (CLAIM_TASK) – transfers and resumes recorded execution with destination agent eligibility checking. It is **not** a formal handoff acceptance.
- `POST /tasks/{task_id}/complete` (CLAIM_TASK) – checks completion contract.
- `POST /work/tasks/{task_id}/findings` (WRITE_FINDING) – current owner only; source evidence optional.
- `POST /work/findings/{finding_id}/verify` (WRITE_FINDING) – existing VERIFIER agent gate.
- `POST /work/blockers/{blocker_id}/resolve` (WRITE_FINDING) – current task owner only.
- `POST /work/contracts` (CLAIM_TASK) – prepare formal handoff with artifacts and designated receiver; current owner only.
- `POST /work/contracts/{contract_id}/accept`, `POST .../reject` (CLAIM_TASK) – receiver validation, no automatic task claim.
- `POST /work/executions/{execution_id}/branches` (WRITE_FINDING) – current task owner creates isolated branch.
- `POST /work/branches/{branch_id}/findings` (WRITE_FINDING) – current task owner adds branch finding.
- `POST /work/branches/{branch_id}/validate` (WRITE_FINDING) – graph-backed branch contract validation.
- `POST /work/branches/{branch_id}/merge` (WRITE_FINDING) – current owner promotes valid branch into shared graph.

The inherited endpoints remain for listing, claim/start/resume/checkpoint, plan generation, agent capabilities, actions and audit trails. No raw Cypher endpoint or ungoverned direct database write was added.

## Important scope and security limits

- Test tokens select Northstar or Asteria only when development authentication is enabled. Never deploy test credentials to production. `READ_GRAPH` is tenant-scoped, **not** a branch-level ACL. This release excludes branch-private findings from the *new* memory and task-insight read endpoints, but existing legacy graph read endpoints may still expose branch records to authorized tenant readers. Full branch-level privacy needs an architectural ACL review of *all* read surfaces.
- API bodies accept agent IDs to simulate specialist activity. Permissions authorize the **human/API principal**; they do not cryptographically prove identity of an autonomous worker. Proper agent credential issuance and attribution are separate work.
- Asteria seed records include historical agent coordination **examples**, not automatically executed demonstrations. Test creation and operation of new tasks/checkpoints/handoffs to establish live behavior.
- Formal handoff acceptance records acceptance. An authorized operator separately transfers active task ownership when appropriate.
- Governance still has the existing mock sink unless a separately configured executor changes it. Do not claim real infrastructure actions happened when mock responses are returned.
- The task DAG's longest edge-count chain is not a critical-path schedule: estimates, task durations, and resource contention are unmodeled.

## Windows acceptance (non-destructive)

1. Back up your Step 2 folder and extract the Step 3 ZIP to **a separate directory**. Copy local `.env` configuration without uploading secrets. Use Step 1 Asteria seed graph only if already seeded. **Do not run `reseed.py`**.
2. Start existing Docker FalkorDB, FastAPI on `127.0.0.1:8000`, and Vite on its configured port. Verify `/api/v1/session` with your tenant-appropriate token and `X-Tenant-ID` header.
3. Backend tests: `python -m pytest -m "not integration" -q`. Dataset integrity: `python scripts/validate_asteria_pack.py`. For full live tests, run `python -m pytest -m integration -v` against your **intended isolated testing graph**, not production.
4. Frontend: `cd frontend; npm ci; npm run typecheck; npm test; npm run build; npm run dev`. **These npm-dependent tests have not been verified in the creation environment**, so fix any local failures before deploying.
5. Set API config to `asteria` and its development token if testing the new Asteria pack, with your backend `FALKORDB_GRAPH=asteria_company_brain_v1` and matching tenant settings. Existing browser-local API config can override `.env`.
6. Work → Plans → pick a scenario whose starting entry is an `INC-*` incident → create plan → open generated plan → verify recorded task nodes, waves, cycle state and longest dependency chain. Select a task and open its workbench.
7. Work → Tasks → choose task → verify owner, evidence, prerequisites, execution and event records. Select an eligible agent; only use Claim/Start on eligible work. Pause/Resume must preserve and update status, and saving a checkpoint must create a real record. Retry must reject non-FAILED tasks. Submit findings, verify using a VERIFIER agent, and test contract-gated completion.
8. Create a branch on an owned task execution, add a finding with real evidence IDs, validate and merge; verify shared findings only after merging. Create a formal handoff with the required artifacts and test validation, acceptance/rejection, and separate transfer of task execution.
9. Work → Memory → choose agent and verify persisted checkpoints, status, provenance, validity and source evidence. Work → Action Governance → inspect action status, governance, attempts; **do not execute real actions merely to test the page**.
10. Test with a READ_GRAPH-only principal and wrong-tenant token: reading must follow tenant permission; mutation attempts must be denied. Verify a branch-private finding is not shown by Step 3 memory/insight APIs.

## Verification in build environment

- Python compile: passed.
- New work logic/API tests: 8 passed, included in regression.
- All non-integration backend tests: **437 passed**, **299 integration-marked deselected**.
- Asteria fixture validator: passed.
- New TSX and API module transpilation/parser check: passed.
- Frontend TypeScript typechecking, Vitest, production bundling and live FalkorDB/browser tests: **not run / not certified** (frontend npm dependencies unavailable).
