# Component 2 — Supervisor & Task Scheduler (Priority 2)

**Scope:** autonomously coordinate bounded, read-only specialist investigations. Internal supervisor task/event persistence is permitted; business action execution, approval granting, changes to organizational tasks, or external system mutations are **not**.

## Architecture and execution

- `backend/app/agent_runtime/supervisor.py` — supervisor planner, DAG validator, specialist registry, capability-based selector, concurrent dependency scheduler, read-only specialist tool loops, evidence-checked handoffs, retry bounds, contradiction detection, escalation, final synthesis.
- `backend/app/agent_runtime/supervisor_store.py` — tenant-scoped FalkorDB persistence of `SupervisorRun`, `SupervisorTask`, and `SupervisorEvent` nodes connected to the run. Stored output is bounded, typed specialist summaries and canonical citations, not secrets or unrestricted raw graph documents.
- `frontend/src/demo/SupervisorPanel.tsx` — run form, specialist directory, task DAG, handoff evidence, reasons for escalation, complete persisted execution events, and run reopening.
- `backend/tests/test_supervisor_component2.py` — deterministic tests using the production tools and orchestrator, with a stub provider instead of a remote paid model.

### Scheduling logic

A recognized canonical `Incident` entity automatically generates four tasks:

```text
analyze_dependencies ─┐
                      ├──> verify_findings ──> propose_remediation
retrieve_evidence ───┘
```

The first two tasks may execute concurrently when `max_parallel >= 2`. The verifier is only scheduled when both are completed, and the remediation-proposal agent is scheduled only after verification. When the source is not an `Incident`, the configured model proposes a task DAG under a strict schema; the supervisor validates required capabilities, duplicate IDs, missing prerequisites, task bounds, and cycles before dispatch.

**Specialists:** `incident_investigator`, `dependency_analyst`, `evidence_retriever`, `policy_verifier`, `independent_verifier`, and `remediation_specialist`. This is an internal executable agent registry, not a discovery mechanism for real employees or arbitrary external agents. The selector checks capability, tool allowlist, authenticated permissions, and concurrent capacity. All specialists invoke the existing allowlisted `ToolRegistry` functions, never arbitrary Cypher or write tools. Only the supervisor schedules tasks; specialists cannot self-assign or start unauthorized tasks.

**Agent messages and handoffs:** prerequisite outputs are passed as structured objects containing task ID, worker ID, summary, citations, confidence, gaps, assertions, flags, and risk. A worker may cite a source only when it appears in its own tenant-visible observations, the starting entity context, or a previously validated prerequisite handoff. Assertions' subjects must be among these observed entity IDs. An invalid tool, source citation, or reference fails that specialist and blocks downstream tasks; a model's summary is not independently proven true by this check.

**Retries and recovery:** default one retry (maximum two configured retries) for timeouts and transient provider HTTP 429/500/502/503/504. Other provider failures including HTTP 404 are terminal. A different qualified worker is preferred when possible; otherwise a bounded retry can reuse the original worker. The outer request enforces deadline, task count, iteration count, parallelism and token budgets; no unbounded autonomous retry loop.

**Deadlock and conflicts:** upfront DAG cycle and duplicate ownership checks; runtime detection of blocked prerequisites or no runnable owner; comparisons of normalized structured claims for a matching `(subject_id, predicate)` with different values; explicit model-reported conflicts. The latter are structured conflict reports and **not** a guarantee of semantic contradiction detection.

**Human escalation:** blocked/failed tasks, source insufficiency, asserted contradiction, critical/high risk, or a requested review produce a `NEEDS_REVIEW` run and a persisted list of reasons. The operator can inspect them in the demo view. There is **no automatic action approval, outbound alert, human queue, ticket creation, or remediation execution** in this component; those require a separate authorized governance integration.

## API

Requires configured model provider, `READ_GRAPH`, `READ_EVIDENCE`, `CREATE_INVESTIGATION` to run. Explicit `allow_external_model: true` is required.

- `GET /api/v1/agent-runtime/supervisor/registry` — specialist IDs, supported capabilities and allowlisted tools, restricted to accessible agents.
- `POST /api/v1/agent-runtime/supervisor/runs` — synchronous, bounded multi-agent run; accepts `goal`, optional `source_entity_id`, consent, `max_tasks` (2–8), `max_parallel` (1–4), `max_steps_per_task` (1–10), `max_seconds` (20–240), `max_tokens_per_task` (500–12000), `max_retries` (0–2).
- `GET /api/v1/agent-runtime/supervisor/runs/{SRUN-...}` — reload persisted DAG, specialist findings, source references, events and escalations. Reads are tenant-scoped.

Example with an existing Asteria incident (use your own tenant's real canonical incident ID):

```powershell
$headers = @{ Authorization = 'Bearer test-asteria-admin-token'; 'X-Tenant-ID' = 'asteria' }
$body = @{
  goal = 'Investigate the dispatch outage, affected systems, evidence and safe next steps'
  source_entity_id = 'INC-AST-ROUTE-OUTAGE'
  allow_external_model = $true
  max_parallel = 3
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/v1/agent-runtime/supervisor/runs' -Headers $headers -ContentType 'application/json' -Body $body
```

The development token and incident in this example must exist in the configured environment; the example is **not** a promise of availability in another tenant. No model results are hard-coded as evidence.

## Acceptance and limitations

`pytest -q backend/tests/test_supervisor_component2.py` exercises multi-agent execution, parallel workers, verified handoffs, dependency ordering, authorization/consent, both model and incident decompositions, cycle rejection, incompatible claims, high-risk escalation, transient retry and nonretryable 404 handling. The tests use an in-memory store and a scripted model. Full FalkorDB end-to-end persistence, UI build, and live remote provider behavior need environment-level verification. A model provider still returning HTTP 404 cannot run this component; check the provider's actual model name, authorization and endpoint independently before live demos.

To run the whole backend unit suite: `pytest -q backend/tests`. Integration tests needing an active FalkorDB instance are skipped when it is unavailable.

**Feature coverage (2.1–2.13):** supervisor objective owner; incident template plus model task decomposition; executable specialist registry; capability/permission/load selection; dependency DAG; parallel execution; structured handoffs; validated predecessor contracts; persisted shared state; cycle/duplicate assignment/assertion conflicts; bounded retries and reassignment; source-checked aggregated answer; persisted human-escalation reasons. Dynamic registry updates, push notifications, general semantic contradiction proof, durable queue workers, and authorized action execution are outside this component.
