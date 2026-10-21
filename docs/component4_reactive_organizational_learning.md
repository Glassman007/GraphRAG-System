# Component 4 — Reactive Organizational Learning (Priority 4)

Component 4 extends Component 3's verified cross-session knowledge and Component 2's dependency-aware supervisor. It **does not train or fine-tune an LLM**. Its job is to detect durable source-graph changes, recheck the source-backed knowledge that depends on them, preserve evidence lineage, and mark the affected supervisor tasks for targeted replay.

## Implementation

- `backend/app/agent_runtime/reactive.py`: material before/after graph diff, event origin checks, conservative source confidence, deterministic source-checkable memory re-verification, memory withdrawal, supervisor DAG impact propagation and legacy Company Brain dependency discovery.
- `backend/app/agent_runtime/reactive_store.py`: FalkorDB private-graph `ReactiveChange` inbox, atomic claim leases, retry/dead-letter states, immutable prior memory/checkpoint revisions, tenant-scoped persisted action outcomes.
- `backend/app/ingestion/pipeline.py`: publishes events **after committed canonical fact writes**; does not publish from dry-runs or no-op resyncs. Eagerly processes bounded batches. Tombstones are `PROBABLE` events requiring review because existing writer preserves canonical records rather than deleting them.
- `backend/app/agent_runtime/supervisor.py`: uses current verified action outcomes as evidence context, resumes a `REPLAN_REQUIRED` checkpoint after new user consent, resets only the explicitly affected tasks and their descendants, and preserves independently completed work.
- `backend/app/services/action_coordination_service.py`: captures real, terminal, canonical action success results with existing ActionAttempt proof. A failure to capture does **not** reverse an already successful external action; the response carries a `learning_warning` and a scoped recovery endpoint exists.
- `scripts/run_reactive_worker.py`: worker that retries after process restarts. It uses FalkorDB as its durable inbox, not a process-local list.
- `frontend/src/demo/ReactiveLearningPanel.tsx`: accessible from Demo & Scenario Explorer, showing event confidence, propagation effects, affected memory and run IDs, and a manual replay control.

## Feature-by-feature matrix

| ID | Scope | Status |
|----|-------|--------|
| 4.1 Change detection | Changes to a bounded set of material node properties and active source-graph edges, including evidence and relationships, after ingestion commits | Implemented, source-ingestion path |
| 4.2 Events | Deterministic idempotency key, tenant, source/checksum, graph delta and provenance | Implemented |
| 4.3 Impact | Verified agent memories, persisted supervisor DAGs, plus structured Claim/Decision/Task/Plan/Investigation dependency impact advice | Implemented within declared dependency relationships |
| 4.4 Invalidation | Unsupported previously-verified agent memories become private RECHECK_REQUIRED; already-supported ones are deterministically reverified | Implemented |
| 4.5 Targeted verification | Recheck only affected claims against fresh canonical nodes and permitted predicates | Implemented, restricted predicates |
| 4.6 Activation | Automatically queue affected supervisor tasks for targeted replan. Additional model calls require user to authorize resume; no unconsented background model calls | Partial for autonomous model execution |
| 4.7 Replanning | Saved dependency DAG recalculates affected tasks and downstream tasks; unrelated completed tasks not rerun | Implemented on authorized resume |
| 4.8 History | Original event source/graph delta and immutable prior AgentMemoryRevision / AgentCheckpointRevision in isolated FalkorDB | Implemented for changed records |
| 4.9 Outcomes | Capture provenance-backed canonical terminal action outcomes, idempotently; provide outcomes to specialist context | Implemented for existing governed action path |
| 4.10 Propagation lineage | Original change event links to memory IDs, checkpoint IDs, affected task IDs, and notifications | Implemented; rare mid-event crash can leave incomplete event summary (see caveat) |
| 4.11 Confidence | CONFIRMED vs PROBABLE source events, REVERIFIED vs STALE memory decisions, CONTRADICTED vs MISSING_EVIDENCE support reasons, UNKNOWN action outcomes as UNRESOLVED | Implemented |
| 4.12 Durability | Per-event FalkorDB inbox, atomic claim token + bounded lease, retries, dead letter and external worker | Implemented for enqueued events; publication atomicity limitation below |
| 4.13 Notifications | Persistent event-side notifications, UI review queue and authorization-based escalation | Implemented as in-app queue; no unsolicited push/email |

The private graph remains `<FALKORDB_GRAPH>_agent_memory`. It is intentionally separate from the canonical graph and thus hidden from ordinary Company Brain queries.

## How to run

Install and configure the project's usual backend dependencies and FalkorDB. Start GraphHacks as usual. For continuous retry after an API crash or restart, run a separate worker under your preferred service supervisor (one per tenant):

```sh
python scripts/run_reactive_worker.py --tenant asteria --poll-seconds 10
```

For a single replay pass:

```sh
python scripts/run_reactive_worker.py --tenant asteria --once
```

An authoritative ingestion that materially changes canonical facts creates an event and triggers immediate deterministic propagation. A separate worker will pick up eligible unacknowledged events; workers from different processes use a short-lived lease token. Non-authoritative updates and tombstones are review events, not forced revisions to organizational truth.

## API (requires tenant-scoped credentials)

- `GET /api/v1/agent-runtime/reactive/events?limit=30`: inspect recent change events and dependent impacts. Needs `READ_GRAPH + READ_EVIDENCE`.
- `POST /api/v1/agent-runtime/reactive/process?limit=12`: recover eligible queued events. Needs `READ_GRAPH + READ_EVIDENCE + CREATE_INVESTIGATION`.
- `GET /api/v1/agent-runtime/reactive/runs/{run_id}/impact`: **run owner only**; tells which tasks and events require replan.
- `POST /api/v1/agent-runtime/reactive/outcomes/{action_id}/learn`: idempotently reconcile a canonical action outcome, rejected unless proven by ActionAttempt. Needs read/evidence/create-investigation permissions.
- `POST /api/v1/agent-runtime/supervisor/runs/{run_id}/resume?allow_external_model=true`: reruns affected tasks **only after the authenticated owner explicitly authorizes another external model call**. Even if the original supervisor run was completed, the saved reactive replan can be resumed.

## Concrete Route Database demonstration

1. In a tenant with fixture graph `SYS-AST-DISPATCH -[:DEPENDS_ON]-> SYS-AST-DB`, start a supervisor incident analysis that independently corroborates and publishes this dependency to shared memory.
2. Ingest a different **authoritative, validated** source record that actually changes this canonical edge (not merely a textual suggestion of an alternative).
3. The pipeline computes its material before/after change and queues a `RCHANGE-*` event with the source record ID, checksum and changed entities.
4. Deterministic worker checks the old memory against current canonical graph. If the dependency no longer exists, the record moves from `SHARED / VERIFIED` to `PRIVATE / RECHECK_REQUIRED`; its original version is archived. If the fact still holds, the worker records a new source recheck without removing it.
5. A previously completed run that cited the affected entities gets `REPLAN_REQUIRED`; the exact impacted task and its descendants are marked for resumption. An unrelated completed branch remains completed.
6. A user with the original run ownership and permission can consent to execute only the queued agent work; newly run agents cannot retrieve the stale memory as a verified premise.
7. The Demo's **Reactive Organizational Learning** panel shows the event, memory effect, downstream task IDs, and the reason for review.

### Do not confuse these cases

- A new log says “Route DB might not be the cause”: source confidence is **not** enough to overwrite existing memory. Without a confirmed canonical graph change, queue a review, not automatic invalidation.
- An authoritative source record is tombstoned but canonical graph relationships remain: this triggers an **unresolved / review** event, not a fictional deletion.
- A change to unrelated metadata, e.g. `last_ingested_at`, is ignored in material diff.
- A success reported by an LLM is not an action outcome. The persisted canonical `Action` and successful `ActionAttempt` must corroborate it.

## Test commands

```sh
python -m pytest -q backend/tests/test_reactive_learning_component4.py
python -m pytest -q backend/tests
cd frontend && npm ci && npm run typecheck && npm run build
```

Tests exercise deterministic source deltas, confirmed/probable trust boundaries, no-op deduplication, fresh cross-session verification, staleness, prior-revision archives, impacted task descendants, isolated tenants, bounded retries, action-outcome proof and targeted supervisor resume. Live FalkorDB-dependent tests were skipped here because a working FalkorDB installation was unavailable. TypeScript syntax was checked with a local compiler; the complete frontend dependency/typecheck/build remains unverified.

## Operational limits — do not claim broader guarantees

1. **No implicit new LLM calls:** Source-update processing is autonomous; model-based investigation needs fresh authorization and must not reuse credentials from a prior request. The event queue automatically flags and preserves work; the authenticated original owner resumes it. Business action execution still uses existing governance.
2. **Atomicity:** Canonical graph writes and the reactive inbox live in different graph namespaces, so the ingestion callback cannot commit them in one transaction. An unexpected process death *between* graph commit and event enqueue can lose a change event. Production should add a canonical-graph transactional outbox and periodic reconciliation/backfill before claiming guaranteed capture.
3. **Multi-worker concurrency:** Event claims use graph-level lease updates and are at-least-once, not exactly-once. The write-side revision checks prevent silent overwrites; under overlapping in-flight supervisor workers, distributed run-level cancellation/locking is still required.
4. **Large tenants:** Impact scans intentionally fail closed beyond 10,000 records until indexed impact edges and pagination are added. Do not infer “no dependencies” from a truncated scan.
5. **Full graph versioning:** The component archives the previous memory/checkpoint and per-event graph property/edge delta. It is not a full transactional bitemporal snapshot of every graph write or every historical claim.
6. **Legacy Claim/Plan/Investigation flows:** The existing Phase 7 dependency rules discover affected records. A confirmed explicit Evidence INVALIDATED transition uses existing Phase 7 invalidation. Other changes generate traceable review targets rather than silently changing every older object's business state.
7. **External integrations:** Source changes not routed through the verified Phase 9 ingestion pipeline (including direct administrative Cypher and legacy write endpoints) do **not** automatically publish component-4 events yet. Additional source adapters/hooks are needed for coverage of every mutation path.
8. **Notifications:** Notifications are persisted in events and shown in the UI; there is no Slack/email/push delivery, and the UI polls rather than receiving a websocket stream.

These limits are intentional: the system should maintain **verified knowledge**, not assert unsupported continuous intelligence.
