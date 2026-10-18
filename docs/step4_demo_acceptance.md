# GraphHacks Step 4 — Demonstration, Observability & Acceptance

## Baseline

This release is additive on **GraphHacks Step 3 (Work + Asteria v1)**. The GraphHacks Read the Rain / Matrix presentation is retained. No existing dataset was reseeded, no graph was modified during packaging, and no permission gates were relaxed. The Northstar fixtures and application routes remain in place. Asteria remains isolated under tenant `asteria` and graph `asteria_company_brain_v1`.

## How the Demo Lab works

- Visit `/demo` in the sidebar. Select among 24 versioned Asteria scenarios divided into Company Brain (9), Agents on Connected Data (7), and Agent Memory & Coordination (8).
- Find scenarios by title, problem or canonical ID, or select a track. Open a scenario; human-friendly titles are shown first, with IDs as secondary references.
- Follow the generated stages. The connected outage scenario walks through organization data, Company Brain, Situations, Knowledge, Investigations, Work, Decisions, governance and non-mutating Simulations. It preselects the incident for plan generation.
- Open a stage in a separate tab and inspect real data. Check **I inspected this stage** only after inspection. These checkmarks are held in browser **session storage** keyed to tenant and scenario; they are NOT automated pass results.
- Select **Collect live trace** to fetch authenticated, bounded GET results from the active backend graph. This cannot create investigations, plans or trigger actions. Trace records are actual API responses, not fabricated demo success events.
- In Live Trace, select a task and governed action by searchable name to see executions, recorded checkpoints/findings, approval gates and attempts. Source evidence and event timelines appear only when recorded and accessible. Any failed or forbidden request is displayed with its error status. The technical view exposes exact payloads for verification.
- The comparison panel contrasts the selected *isolated record* with the same root's backend-returned *connected neighborhood*, reporting actual link and entity counts. The contextual ablation table also shows recorded historical links, evidence, checkpoints, and coordination artifacts when the backend returns them; no AI model without those layers is executed. **It is not an AI accuracy, latency, or benchmark comparison.** To claim a model-performance advantage, measure identical question sets with/without graph context and independently grade results.
- `/demo?view=matrix` displays the scenario acceptance matrix and honest capability register.

## What's verifiably implemented

| Requirement | Verification intent | Limitation |
|---|---|---|
| 33 | Track picker, 24 scenarios, objectives, entry and focus objects, expected observable outputs | Asteria fixture data only; no auto-tenant switching |
| 34 | Contextual walkthrough via existing module routes | User must perform mutating operations deliberately in those modules |
| 35 | Isolated root vs connected neighborhood based on live graph GETs | Not a controlled AI-quality benchmark |
| 36 | Live API trace, events, evidence/provenance, claims, task insight, checkpoints and governance | Only recorded records; no fabricated action or agent execution |
| 37 | Offline contract tests; TS UI unit tests, Playwright demo route tests | Frontend dependency-based tests and browser E2E require local npm/browser |
| 38 | One entry per scenario, with separate offline and live read statuses | Live writes/handoffs require operator-guided acceptance |
| 39 | Implemented/partial/proposed capability register | Claims are code-scope labels, not proof of deployment health |
| 40 | Read-only runner, tenant-bound session, no reseed/migrations | Requires a configured local database for live tests |

## Reproduce on Windows without damaging either graph

1. Extract the complete Step 4 ZIP to a **new folder**. Keep the current Step 3 installation as a rollback option. Do **not** run `scripts/reseed.py`, `scripts/reset_graph.py`, or destructive seed operations.
2. Copy your local config privately. For the Asteria demo, set the *backend process* to `FALKORDB_GRAPH=asteria_company_brain_v1` and `GRAPH_TENANT_ID=asteria`, and start FastAPI at port 8000. Use only local development authentication (`test-asteria-admin-token` when development test auth is enabled). The browser API config must use tenant `asteria` and the corresponding token. Existing Northstar config and graph remain untouched.
3. Run offline checks from the project root:

```powershell
python scripts/validate_asteria_pack.py
python scripts/verify_step4_demo.py --report step4_offline.json
python -m pytest -m "not integration" -q
```

4. Run frontend tests after installing dependencies:

```powershell
cd frontend
npm ci
npm run typecheck
npm test
npm run build
# Requires running FastAPI, FalkorDB, Vite and installed Playwright Chromium:
npx playwright test e2e/step4-demo.spec.ts
```

5. For **read-only live API checks** against a running Asteria graph, configure an environment variable *in your current PowerShell terminal only*:

```powershell
$env:GRAPH_HACKS_TEST_TOKEN='test-asteria-admin-token'
$env:GRAPH_HACKS_TENANT='asteria'
python scripts/verify_step4_demo.py --live --base-url http://127.0.0.1:8000 --report step4_live.json
Remove-Item Env:GRAPH_HACKS_TEST_TOKEN
```

`--live` sends GET requests only. It verifies authorization and root/neighbor availability for all 24 cases and incident context when applicable. `PASS_READS` proves *read availability only*: it does not certify investigation creation, agent autonomy, retrieval accuracy, action approvals, task handoff completion or real execution. The output never includes the bearer token or golden evaluator answers. Treat reports from your deployment as environment-specific.

## Guided live manual acceptance (required for a full demo)

**Company Brain:** Open AST-CB-01 → inspect SYS-AST-ROUTE-DB → Company Brain dependencies. Confirm actual graph relationships, check claim/evidence provenance and historical ownership via an appropriate Company Brain scenario. Check the read-only live trace result.

**Agents on Connected Data:** Open AST-AA-01 → inspect incident `INC-AST-ROUTE-OUTAGE` → explicitly create an investigation → run retrieval and inspect evidence provenance → create plan from the preselected scenario in Work → inspect dependencies → review a proposed action in governance. Do not approve/execute unless your test environment is isolated and the policies allow it. Finally run a supported non-mutating simulation and inspect baseline/hypothetical differences.

**Memory & coordination:** Open AST-AM-01, then Work → Tasks → inspect a task → choose an eligible agent and perform an authorized transition or checkpoint on a separate, newly created test task. Validate a handoff and compare recorded states. In Work → Memory, choose the actual agent and inspect saved checkpoints and evidence provenance. **Seeded memory records are not a live agent run.**

For all tracks capture: scenario ID, dataset version, tenant, backend revision, date, GET results / graph paths, which operations were actually performed, error/request IDs, and independent result status (PASS, FAIL, BLOCKED, NOT TESTED). Do not mark a scenario PASS for autonomous operation simply because graph fixtures or UI screens exist.

## Evidence and acceptance artifacts

- `docs/step4_acceptance_matrix.json` — 24 scenario entries, expected observation and clear criteria. `live_verification` deliberately initializes to `NOT_TESTED`.
- `scripts/verify_step4_demo.py` — per-scenario offline evaluator (reads evaluator-only fixture locally) plus authenticated, read-only live API smoke runner; no automatic writes.
- `backend/tests/test_step4_demo_acceptance.py` — acceptance matrix, module routing, and evaluator-leakage regression assertions.
- `frontend/src/test/step4Demo.test.tsx` — scenario coverage, guide routing, truthful capability flags, API-shaped context comparisons.
- `frontend/e2e/step4-demo.spec.ts` — Demo Lab navigation/progress/matrix browser smoke tests.

## Non-goals and integrity rules

The Demo Lab does not autonomously schedule LLM agents; it exposes Step 3 user-guided coordination. Memory means persistent recorded graph artifacts, not model conversational recall. A generated plan is not an executed plan. Hypothetical simulations don't write to FalkorDB. The readiness banner is not a proxy for successful incident retrieval or agent operation. Full production branch-level ACL review is still outstanding on inherited API surfaces. Test fixtures are synthetic and cannot prove connectors ingest live enterprise data.
