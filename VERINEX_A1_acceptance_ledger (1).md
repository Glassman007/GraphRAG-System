# VERINEX — A1 Asteria-only acceptance ledger

**Prepared:** 2026-10-22  
**Current verdict:** PARTIAL — live Asteria graph/tools/authorization passed; Workspace legacy unscoped run issue reproduced; narrowly scoped patch checked but not yet applied/verified in the user checkout.  
**Scope:** Only remaining agent workflow, work package A1.  
**Tenant:** `asteria` · **Graph:** `asteria_company_brain_v1` · **Incident:** `INC-AST-ROUTE-OUTAGE`.  
**Input snapshot:** `GraphRAG-System-main (6).zip` (SHA-256 `11bacde771915c9af01f4ba7a4a0f97bbd968f3fe0f72d9a8e2ad3cec351f829`).  
**Live production code changes:** None yet (checked A1 patch provided separately). **Model calls:** None. **Business graph writes:** None.  
**Artifact provided:** Standalone, read-only `VERINEX_A1_asteria_preflight.py` (not part of production runtime).

## Source inspection / actual call path

1. `frontend/src/pages/AgentWorkspacePage.tsx` — selected graph becomes `scopedConfig.graphId`, transmitted as `X-Company-Brain-ID` by `frontend/src/api/client.ts`; POST body also contains `graph_id`, objective and optional source ID.
2. `backend/app/api_v1/security.py` — `authenticate` resolves header through tenant-scoped `GraphRegistry.resolve`; `client_for` gets a client scoped to that registered graph.
3. `backend/app/api_v1/router.py::workspace_start` — requires read/evidence/investigation permissions and consent; rejects body/header graph disagreement; stores graph ID in Workspace record and submits process-local worker.
4. `backend/app/api_v1/router.py::_workspace_worker` — re-creates client under the principal, instantiates `ToolRegistry(lambda: GraphSnapshot.load(client))`, `GraphSupervisorStore`, `AgentMemory`, then calls `Supervisor.run`.
5. `backend/app/agent_runtime/supervisor.py::Supervisor.run` — checks explicit seed existence, opportunistically extracts ID from goal, selects `_incident_plan` only with incident seed, schedules agent profiles, calls `ToolRegistry.execute`, validates cited IDs and stores operational events/results.
6. `backend/app/agent_runtime/tools.py::ToolRegistry.execute` and `backend/app/services/phase4_graph.py::GraphSnapshot.load` — read the selected graph with explicit `tenant_id` filtering. Graph tools are read-only.
7. `backend/app/api_v1/router.py::_workspace_owned`, `workspace_detail`, `workspace_events`, `workspace_replay`, `workspace_control` — check owned Workspace record and graph binding before reading/restoring run state.
8. `backend/app/agent_runtime/workspace.py::WorkspaceStore` — stores owned Workspace metadata/snapshots in the selected graph's `_agent_memory` sidecar, not a separate Company Brain dataset.
9. `backend/app/agent_runtime/incident_skill.py::run_incident_skill` — standalone, opt-in deterministic known-incident read with one synthesis model call; `backend/app/agent_runtime/harness.py` dispatches it, but Supervisor does not.
10. `backend/app/services/coordination_service.py` and `backend/app/services/handoff_service.py` — persisted task/execution/blackboard and formal handoff API implementations exist; Supervisor does not call them automatically.

## Offline verification executed on extracted snapshot

Executed from repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  backend/tests/test_supervisor_component2.py `
  backend/tests/test_agent_workspace_component6.py `
  backend/tests/test_agent_runtime_incident_skill.py `
  backend/tests/test_company_brain_workspace_stage2.py `
  backend/tests/test_coordination_handoff_context.py `
  backend/tests/test_fixture_integrity.py `
  backend/tests/test_agent_runtime_evidence_grounding.py `
  backend/tests/test_agent_runtime_budget_resilience.py `
  backend/tests/test_agent_runtime_duplicate_queries.py `
  backend/tests/test_agent_runtime_provider_resilience.py `
  backend/tests/test_agent_runtime_rate_efficiency.py `
  backend/tests/test_agent_memory_component3.py
```

Two actual invocation batches: **50 passed in 3.07 seconds**, then **42 passed in 3.15 seconds**. Overall: **92 passed / 0 failed**, all offline (fake graph/provider or source-fixture verification); no claim of live FalkorDB/Groq execution.

## A1 check ledger

| Gate | Status | Basis / expected new evidence |
|---|---|---|
| Latest supplied ZIP inspected before any production edits | PASS | Extracted and audited files, no code changes |
| Workspace→Worker→Supervisor→ToolRegistry exact path traced | PASS (source inspection) | Paths/functions listed above |
| Selected graph/tenant authorization logic exists | IMPLEMENTED + OFFLINE TESTED | Tenant registration, header/body mismatch and owned-run access tests passed |
| DAG, specialist registry, checkpoint and scoped read-only tools | IMPLEMENTED + OFFLINE TESTED | Focused offline suites passed |
| Deterministic `incident_skill` code and one-call architecture | IMPLEMENTED + OFFLINE TESTED | Opt-in standalone `AgentHarness` dispatch; not Supervisor integration |
| Live canonical Asteria Incident + supporting evidence | PENDING | Execute A1 read-only probe against user's live FalkorDB |
| Four direct live Asteria reads (`get_entity`, `graph_neighbors`, `graph_paths`, `incident_context`) | PENDING | Tool statuses and counts from A1 probe |
| Authenticated Asteria Workspace session, run list, detail, events and replay | PENDING | HTTP GET readback; existing owned run required for detail/events/replay |
| Historical Asteria Supervisor run failures and actual tool error summaries | PENDING | Readback of `SRUN-E633E01597404F9EADB12F19F9B3B894`, `SRUN-95541002DA8C4855B7E70BFAC73FF47D` |
| Unregistered graph rejected without reading another real graph | PENDING | Negative API GET with deliberately unregistered graph header |
| No external-model calls or business-side-effect actions | PASS for performed audit | No model, write or execution tools invoked |

## Existing capability/gap diff (do not implement in A1)

| Category | Source-grounded finding | Later package |
|---|---|---|
| Partially implemented | Descriptive goals without a canonical ID depend on a model-planned fallback; target is not guaranteed to resolve. Known incident with `source_entity_id` selects existing `_incident_plan`. | A2 |
| Partially implemented | Four-task incident DAG has dependency, evidence, verification and remediation; no mandatory Investigator skill dispatch. Optimized incident skill only via standalone `AgentHarness`. | A3 |
| Partially implemented | `SPECIALIST_TOOL` events mark `READ_OK`/`ERROR`, but omit sanitized argument IDs and structured error payloads, limiting historical failure diagnosis. | A3 |
| Missing automatic integration | Supervisor predecessor JSON in `validated_handoffs` is not a durable `HandoffService` accept-and-consume contract. Existing graph services must be reused. | A4 |
| Unverified | Explicit evidence auditor, adversarial critic, independent factual/causal gates and complete report synthesis across all intended roles. | A5 |
| Partially implemented | Groq pacing/deadline and process-local checkpoint logic exist, but parallel multi-agent rate safety and restart are not proven live. | A6 |
| Unverified | Real Asteria UI-to-final-report chain. | A7 |

**Historical context from attached handoff requirements, NOT live re-verification:** previous Asteria source-graph inventory was 501 nodes / 893 edges; previous Asteria Supervisor records were `NEEDS_REVIEW`, including reported Groq deadline failures and repeated graph-tool errors. These are not current live observations and should not be used as A1 acceptance.

## Required next local step (no model calls)

1. Place the supplied `VERINEX_A1_asteria_preflight.py` alongside `backend/` in main `G:\graphhacks`.
2. With already-active `.venv` and current directory `G:\graphhacks`, execute:

```powershell
.\.venv\Scripts\python.exe .\VERINEX_A1_asteria_preflight.py
```

If built-in developer auth is disabled, first set `$env:VERINEX_A1_API_TOKEN` to your configured Asteria token **without printing it**. If the local FastAPI server is not listening at `http://127.0.0.1:8000`, set `$env:VERINEX_A1_API_BASE` to the existing reachable base URL. Do not start a new model run in A1. The script uses only graph `asteria_company_brain_v1`, tenant `asteria`, and that graph's agent-memory sidecar; it does not inspect other Company Brains. It writes `VERINEX_A1_asteria_preflight_result.json` locally without changing application code or the graph.

3. Share the console result or generated JSON for A1 review. If it reveals a genuine A1 agent-workflow break, address only that demonstrated issue before revisiting the gate. Do not proceed to A2 without an A1 PASS.

### A1 exit criterion

Current **PARTIAL**. Upgrade to **PASS** only after current main checkout confirms Asteria incident/evidence, direct four-tool graph success, authenticated Workspace binding, no unauthorized graph access, and a reproducible, file-level failure inventory. Live Groq multi-specialist execution is not an A1 requirement and is not claimed.


---

## A1 follow-up evidence, 22 October 2026 (supersedes the initial pending statuses above)

Files supplied by the user after running in the current main checkout:
`VERINEX_A1_asteria_preflight_result.json`, `VERINEX_A1_workspace_scope_diagnostic_result.json`.

| Gate | Result | Current evidence |
|---|---|---|
| Asteria graph live and scoped | PASS | tenant `asteria`; graph `asteria_company_brain_v1`; 519 nodes, 908 relationships; `INC-AST-ROUTE-OUTAGE` exists |
| Required evidence available | PASS | EVD-AST-0003, EVD-AST-0004, EVD-AST-0005 all found |
| Four live read-only tools | PASS | get_entity=1, incident_context=18, graph_neighbors=6, graph_paths=15 returned entries |
| Agent-memory graph binding | PASS | `asteria_company_brain_v1_agent_memory`, tenant `asteria` |
| Authenticated selected graph | PASS | `/api/v1/session` returned HTTP 200 |
| Unregistered graph denied | PASS | negative authorization GET returned HTTP 404 without reading any other registered graph |
| Historical failed Supervisor records | INSPECTED | `SRUN-E633E01597404F9EADB12F19F9B3B894` `NEEDS_REVIEW`, empty source ID, repeated failed graph reads; `SRUN-95541002DA8C4855B7E70BFAC73FF47D` `NEEDS_REVIEW`, Groq TPM/deadline failures |
| Provider configuration | INITIALIZED | Groq configured; no live Groq requests attempted during A1 |
| Workspace list | FAIL (before patch) | HTTP 200 with one row lacking `graph_id`; no explicitly scoped Asteria row available for detail/events/replay readback |
| Negative auth Asteria other graph | PASS | unregistered graph ID refused, HTTP 404 |

### A1 scope bug and minimal proposed fix

The current checked snapshot has a fail-open default in `backend/app/api_v1/router.py::_workspace_owned`:
`record.get('graph_id', expected)`. Legacy runs lacking `graph_id` could be mistaken for the currently selected graph. Additionally, `workspace_runs` returns tenant-owned rows without selected graph filtering. `workspace_changes` similarly accepts workflow impacts based only on an owner lookup without verifying the impact's run graph.

`VERINEX_A1_workspace_scope_fix.patch` changes only `backend/app/api_v1/router.py` plus adds three regression tests in `backend/tests/test_company_brain_workspace_stage2.py`. The change explicitly checks that `record.tenant` and `record.graph_id` match the authenticated request, rejects unscoped run details/controls and filters list and change impacts. No legacy runs are modified or deleted, and no new database schema is introduced. Unscoped records become inaccessible until an authorized explicit graph attribution procedure is separately justified; no graph inference or automatic migration is performed.

**Offline patch proof:** `git apply --check` and `git apply` both succeeded against a fresh extraction of the supplied ZIP. The 12 focused original suites plus three new scope regression tests gave **95 passed, 0 failed** in 3.92 seconds. This is not evidence that the patch has yet been applied to the user's local checkout or reloaded by their running API process.

### Next A1 live verification

1. Apply the checked patch only if it passes `git apply --check` on the user's latest main checkout. Do not force it over changed files.
2. Run focused tests in the user's activated environment.
3. After the API has loaded the patched router (restart the existing API process if auto-reload is disabled), run `python .\VERINEX_A1_workspace_scope_diagnostic.py` again. Expected: `SCOPED_LIST_VERIFIED`, zero missing/different scope categories, negative unregistered-graph HTTP 404. A list containing zero Asteria-scoped runs is acceptable for the list-scope gate, but does not prove live detail/events/replay or restart behavior; those remain unverified until an Asteria Workspace run legitimately exists.
4. Reclassify A1 only after reviewing the actual test and live diagnostic outputs; do not move to A2 based solely on this offline patch proof.

---

## A1 follow-up: user-verified local patch and API behavior (22 October 2026)

**User-supplied PowerShell evidence:**

- `python -m pytest -q backend/tests/test_company_brain_workspace_stage2.py backend/tests/test_agent_workspace_component6.py` — **18 passed, 1 unrelated Starlette/AnyIO deprecation warning, 3.69 s**.
- `python .\VERINEX_A1_workspace_scope_diagnostic.py` — **`SCOPED_LIST_VERIFIED`**; list HTTP 200; **0 returned rows**, `categories={}`; unregistered graph HTTP **404**.
- `NO_MATCHING_OWNED_RUN_FOR_READBACK` is **not** a failed access-control check. It means there is no authenticated, graph-bound Workspace run to test `/runs/{id}`, `/events` and `/replay` live. Consequently those readback paths remain **unverified live**. These historical failed Supervisor runs cannot be relabeled as Asteria Workspace records just to satisfy the test.
- The Asteria incident and four read-only graph tools were already confirmed live in earlier A1 output; Groq calls during A1: **0**.

**Current classification:** A1 **PARTIAL**, with the specific list-scope bug fixed and regression-tested. Remaining A1 activity is one bounded authenticated readback probe, not A2 work or a full agent run.

**Prepared next check:** `VERINEX_A1_workspace_readback_probe.py` — inserts one clearly marked synthetic Workspace diagnostic entry **only** into `asteria_company_brain_v1_agent_memory`, tests list/detail/events/replay with the authenticated Asteria principal, tests rejection of an unregistered graph, and removes that exact diagnostic entry. It never calls Groq, starts a Supervisor, or writes business-graph data. Successful empty Supervisor/events/replay responses validate the HTTP readback and scope, **not** specialist execution, durable handoffs, or restart recovery (later packages).

**A1 promotion condition:** pass the targeted Asteria-only readback and cleanup check, with no authorization/tenant/graph discrepancy. Record any failure and stop before A2. Even an A1 PASS does not imply an A7 E2E PASS.
