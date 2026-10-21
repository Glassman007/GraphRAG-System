# Component 6 — Live Agent Workspace

## What ships

**Route:** `/agent-workspace` (first item in the primary navigation).

This component **does not implement a new reasoning agent**. It is an integrated, observable user experience over Components 1–5, including the *actual bounded read-only supervisor* from Component 2, *verified shared memory* from Component 3, *reactive graph changes* from Component 4, and *separately gated external actions* from Component 5.

The user can enter one natural-language objective, optionally select a canonical starting entity, explicitly authorize model-data transmission, and launch a background supervisor run. The browser polls durable events and checkpointed work, and displays execution progress rather than fabricated “thinking” text. Any governed external change must still be separately proposed and approved by an authorized independent principal.

## Feature status

| ID | Feature | Status | Implementation and boundary |
|----|---------|--------|-----------------------------|
| 6.1 | Unified agent command | Implemented | Natural-language objective, starting ID, parallelism, explicit consent |
| 6.2 | Execution dashboard | Implemented | Tenant-and-owner scoped persisted runs and statuses; refresh every 3.5 s |
| 6.3 | Live decisions/tools | Implemented with limits | Poll real operational events (2.5 s); tool names, observation IDs, validated handoffs, assignments and outcomes — **never hidden model reasoning or full raw tool payloads** |
| 6.4 | Multi-agent activity | Implemented | Actual assigned specialist profiles, statuses, dependencies, attempts and task findings |
| 6.5 | Interactive task graph | Implemented | Selectable dependency-stage task DAG; dependency IDs and execution state shown |
| 6.6 | Memory inspector | Implemented with limits | Verified shared-current lookup, record provenance/citations and checkpoint revision; **private branches remain restricted** |
| 6.7 | Execution controls | Implemented, cooperative | Pause/cancel stop *future* task assignment after active read-only model calls finish; resume/retry only from saved tasks, owner and permission enforced |
| 6.8 | Human approval | Integrated | Existing Component 5 governed review, policy preview, named approver gates, execution and authenticated outcome verification |
| 6.9 | Evidence explorer | Implemented | Click cited IDs and inspect the backend's current entity and recorded neighbor relationships inline |
| 6.10 | Change feed | Implemented | Persisted reactive events, confidence, affected memories and affected supervisor runs; probable events clearly remain unconfirmed |
| 6.11 | Before/after comparison | Partial | Compare persisted **workspace execution outcome revisions** after a resume/retry. Full historical graph reconstruction is **not** provided |
| 6.12 | Execution replay | Implemented with limits | Reconstruct persisted operational event order and checkpoint revision; not private chain-of-thought, provider response playback or a historical graph replay |
| 6.13 | Asteria shortcuts | Implemented | Load objective and starting entity from all 24 scenario catalog entries; they are **seeded inputs, not verified live results** |
| 6.14 | Outcome reporting | Implemented with limits | Final synthesis, citations, human escalations, gaps, task states and governed action verification are visible; an incomplete run does not claim success |
| 6.15 | Explicit status | Implemented | Provider readiness, seeded-scenario disclosures, consent, connector boundary, and single-process recovery caveats |

## API additions

All endpoints are under `/api/v1/agent-runtime/workspace` and rely on the existing signed/request-authenticated principal and backend tenant authorization. Read endpoints require `READ_GRAPH` + `READ_EVIDENCE` unless otherwise noted. Operations require `CREATE_INVESTIGATION`, and executing or resuming the model requires explicit `allow_external_model: true`.

```
GET  /capabilities
GET  /runs?limit=30
POST /runs                               {"goal":"...","source_entity_id":"...","max_parallel":3,"allow_external_model":true}
GET  /runs/{run_id}
GET  /runs/{run_id}/events?after=-1
GET  /runs/{run_id}/replay
POST /runs/{run_id}/control              {"operation":"pause|cancel|resume|retry","allow_external_model":true|false}
GET  /changes?limit=30
```

The new workspace **does not** expose a business-action execution endpoint. The governed approval view consumes the existing `/api/v1/agent-runtime/governed/*` routes. The memory inspector consumes `/api/v1/agent-runtime/memory/search`. The graph explorer uses tenant-scoped `/entities/{id}` and `/entities/{id}/neighbors`.

### Execution sequence

1. The frontend sends a launch request with explicit user consent; the server validates authorization and model-provider configuration.
2. `WorkspaceStore` creates the owner-scoped run metadata in a dedicated FalkorDB agent-memory graph.
3. A bounded process-local executor starts the *real* `Supervisor.run` with a predetermined run ID; it uses the existing read-only `ToolRegistry`, persistent supervisor events, verified memory, and task checkpoints.
4. The frontend polls workspace details and reconstructs the task DAG, observed tools and final cited output. It never displays undisclosed model thinking as a “thought stream.”
5. A requested `PAUSE` or `CANCEL` command is persistently recorded and applied at the supervisor scheduling boundary. Existing in-flight calls may finish. No new specialists are assigned after the boundary observes the command.
6. On `PAUSED` or a process interruption, an authorized owner may explicitly resume if a planned checkpoint exists, again supplying consent. Completed tasks remain intact and in-flight interrupted tasks may rerun.
7. On `FAILED`, `PARTIAL` or `NEEDS_REVIEW`, an authorized owner may retry failed/blocked tasks from the checkpoint. Completed tasks are not reset merely to retry a failed descendant. `CANCELLED` is terminal.
8. After a completed/pause/retry transition, an immutable outcome snapshot is saved for comparison; the supervisor's operational events and checkpoint data can be reopened across sessions.

## Permission and truth boundaries

- **Tenant and ownership:** Workspace records have tenant ID plus requesting principal subject. Every workspace read/control checks ownership *before* loading supervisor details, checkpoints or replay. The full underlying action approval system retains its own permissions and separation of duties.
- **Model execution is not permission to act:** All model tool declarations remain graph/evidence READ ONLY. The supervisor can propose remediation; the governed action engine alone handles explicit allowed connectors and human approvals.
- **Event meaning:** `ASSIGN`, `SPECIALIST_TOOL`, `MEMORY_RETRIEVED`, `HANDOFF_VALIDATED`, `TASK_COMPLETED`, etc. are persisted execution events; summaries identify observed canonical evidence IDs, not unsupported “model thoughts.”
- **Private memory:** The UI searches only shared, verified and currently valid knowledge through the existing access-controlled memory service. Private working branches and unverified assertions are not exposed.
- **Change confidence:** `PROBABLE` / `NEEDS_REVIEW` change records cannot silently override confirmed knowledge. User reviews the recorded source change and its affected work.
- **External business operations:** Never auto-dispatched from the workspace. Users must independently create and authorize proposals through the Governed Tool Execution interface.

## Deployment and recovery limitations

1. **Single FastAPI worker only.** `WorkspaceRunner` uses two in-process background execution threads. It is **not** a distributed durable job queue. Running multiple `uvicorn --workers` instances or multiple replicas is unsupported for accurate live-worker detection, control or concurrency guarantees. **For production:** introduce a distributed lease, transactional queue/outbox, worker heartbeats and owner-checked atomic transitions.
2. **Process interruption:** The graph-persisted run may be displayed as `INTERRUPTED` if its process-local worker is gone; resuming requires the last checkpoint with planned tasks. If a process died *before* the first plan checkpoint, safe recovery requires launching a new run. The system must not claim exactly-once model calls.
3. **Cooperative pause:** Already-running read-only model calls (up to the provider timeout) may finish and be saved before the run becomes `PAUSED` or `CANCELLED`. This is not instantaneous termination.
4. **Graph integration:** Requires a reachable FalkorDB, compatible Python dependencies and populated graph; unit tests cannot substitute for live database, connector or browser certification.
5. **Frontend:** `npm ci && npm run build` is the required local build check; this execution environment lacked the cached npm dependencies, so only TypeScript syntax was checked here.
6. **Replay and comparisons:** Outcomes are archived, but canonical graph history is not reconstructed here. The replay timeline is based on supervisor operational metadata, not transcript or private reasoning recovery.
7. **Change publication:** Component 4 retains its transactional-outbox limitation across graph commit and event publication; this UI cannot remove that underlying failure window.

## Manual acceptance (with a running backend and configured environment)

- Visit `http://localhost:5174/agent-workspace`, authenticate, and confirm the provider readiness badge.
- Select `AST-AA-01` and confirm the fixture supplies `INC-AST-ROUTE-OUTAGE` but **does not auto-run**; verify Asteria is selected and ingested.
- Check explicit model-data consent, start. Confirm a real `SRUN-...` ID and stage-by-stage specialist statuses. Observe actual tool names and canonical observation IDs in the activity trace; confirm no external connector action was dispatched.
- Select a specialist to inspect validated citations; open the embedded evidence graph and verify relationship endpoints link to current canonical entities.
- Pause while specialists are active. Confirm the state transitions only after running calls finish, and pending downstream tasks stay pending. Resume and verify existing completed tasks are not rerun.
- Open Memory and search the starting incident; confirm no private/unverified memory becomes visible. Check checkpoint metadata and provenance.
- Open Replay and compare two run outcome snapshots after an allowed resume/retry. Ensure older results are preserved.
- In a separate authenticated approval principal, review any proposed Governed Tool action. Verify proposing and approving principals are distinct, policy preview and connector config are mandatory, and completion requires external readback.
- Trigger a source-confirmed change through the normal ingestion path, process the reactive queue, and verify that the Change feed links to affected run IDs and flags targeted re-verification rather than executing fresh model calls without consent.

## Tests executed here

Run `pytest -q backend/tests/test_agent_workspace_component6.py` for control/replay/auth behavior, then `pytest -q` for the full backend regression suite. FalkorDB-backed integration tests require the live database and installed client. A frontend compilation/build is still required in a configured local environment.
