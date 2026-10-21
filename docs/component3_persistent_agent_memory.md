# Component 3: Persistent Agent Memory (Priority 3)

Component 3 builds on Component 2's bounded read-only specialist scheduler. It is NOT a chat-history store, and it does NOT treat all prior LLM statements as reliable source truth.

## Architecture

- Canonical company graph: `$FALKORDB_GRAPH` (the existing `falkordb_graph` setting). Contains source entities and relationships. Existing business graph tools remain read-only.
- Persistent memory graph: `<falkordb_graph>_agent_memory`, selected automatically through the configured FalkorDB connection. This separate FalkorDB graph prevents unrelated Company Brain graph-query endpoints from accidentally surfacing PRIVATE working branches or checkpoints.
- `AgentKnowledge`: tenant-scoped private draft / shared verified claims, provenance, original task/run/agent identity, model-recorded tool names and citation IDs, verification actor/time, review state, optional valid-until, derived memory IDs. Provenance links use stable IDs; no transcript copying is involved.
- `AgentWorkflowCheckpoint`: owner- and tenant-scoped DAG state, successful task results, task progress/attempts, bounded events and the original settings; saved on scheduling and execution transitions.
- `backend/app/agent_runtime/memory.py`: checks provenance, source validity, controlled claim predicates, independent corroboration, conflict quarantine, staleness, tenant and branch ACLs, and one-hop graph/context search.
- `backend/app/agent_runtime/memory_store.py`: FalkorDB adapter for both knowledge and checkpoint persistence.

## Coverage of features 3.1-3.13

| ID | Behavior and important boundary |
|---|---|
| 3.1 | Verified shared knowledge is retrieved in later run instances (and after a restart when FalkorDB survives). |
| 3.2 | The supervisor checkpoints goals, DAG, task ownership, completed results, failures and bounded events. |
| 3.3 | Long-term `AgentKnowledge` lives in a dedicated FalkorDB graph. |
| 3.4 | Authorized graph/evidence-reading specialists can reuse independently verified shared claims. |
| 3.5 | Unverified statements are PRIVATE and keyed by tenant + owner + run + task + agent branch. |
| 3.6 | Automatic supervisor retrieval by source IDs, one-hop graph neighbors and contextual terms, filtered by expiry and live source evidence. |
| 3.7 | Checkpoints are persisted after progress changes. |
| 3.8 | Resume reuses completed task outputs; incomplete in-flight RUNNING tasks are requeued. Read-only tool calls inside an interrupted RUNNING task can be repeated. |
| 3.9 | Each claim records origin run/task/agent, citations, source tools, verifier, timestamp, and derivation from earlier memories if applicable. |
| 3.10 | A new value conflicting with an existing verified `(tenant, subject, predicate)` is quarantined as `CONFLICT`; existing knowledge is never silently replaced. |
| 3.11 | 30-day verification freshness limit; explicit expiry; graph entity/relationship validity checks; explicit `INVALIDATED`, `SUPERSEDED`, `RECHECK_REQUIRED` reviews. |
| 3.12 | Only current, source-supported, independently reaffirmed, graph-checkable structured assertions are consolidated from private task branches. |
| 3.13 | Tenant scoped graph + permission checks; private run/branch/owner/agent checks; shared records readable only with graph and evidence permissions. |

## Verifier and source-truth requirements

1. A specialist observes canonical graph entities through allowed tools (or current, already-verified memory) and returns a structured `assertions` entry and valid `citations`.
2. That assertion is staged as PRIVATE; only the originating agent's run/branch may access it before sharing.
3. A separate policy or independent verifier completes a dependent task, issues `supported` confidence, cites the same source evidence, and **repeats the matching proposition** in its own assertions. A generic verifier summary cannot promote the claim.
4. The memory manager checks the proposed proposition against the current canonical graph. Supported auto-verifiable predicates in this release: `depends_on`/`dependency_on`/`dependency` edges, `status`, `name`, `severity`, `criticality`, `owner_id`, `source_type` properties. Other or semantically ambiguous claims remain private. This restriction is intentional.
5. If no pre-existing VERIFIED record for the same tenant/subject/predicate contradicts it, the claim becomes `SHARED / VERIFIED`; otherwise it is `CONFLICT` and requires human reconciliation.
6. Later agents search for current verified memory. References and provenance are included in specialist model context. If complete, the model may directly answer the corresponding subtask without repeating the same read-only graph queries. **There is no blanket skip of investigations**: missing evidence still requires tools.

### Concrete data scenario

The existing Asteria test fixture contains `SYS-AST-DISPATCH -[:DEPENDS_ON]-> SYS-AST-DB` and incident `INC-AST-ROUTE-OUTAGE`. Agent A inspects `SYS-AST-DISPATCH` and its edges, asserts `SYS-AST-DISPATCH depends_on SYS-AST-DB` with both IDs cited, and the verifier independently corroborates it. The memory record is promoted. On a second run, a different specialist is automatically provided the current verified claim, source citations, tool provenance, and verifier identity. The acceptance test confirms the dependency specialist can complete the repeated relationship question without new graph reads. It does **not** bypass other investigation branches that are not covered by that claim.

## APIs

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/agent-runtime/memory/search` | `{"entity_ids":["SYS-AST-DISPATCH"],"query":"dispatch database dependency","limit":8}`. Returns only active VERIFIED SHARED facts and provenance. `READ_GRAPH` + `READ_EVIDENCE`. |
| POST | `/api/v1/agent-runtime/memory/{memory_id}/validity` | `{"status":"RECHECK_REQUIRED","reason":"The owner confirmed a source change"}`. `CREATE_INVESTIGATION` plus read permissions. No changes to source graph. |
| POST | `/api/v1/agent-runtime/supervisor/runs/{run_id}/resume?allow_external_model=true` | Requires fresh model-data consent, original run owner, full permissions; original persisted plan/settings are authoritative. |
| GET | `/api/v1/agent-runtime/supervisor/runs/{run_id}` | Existing endpoint for persisted run DAG, statuses, results and events. |

The Demo & Scenario Explorer now includes **Component 3 / Persistent Agent Memory**, with contextual search, provenance view and human validity-review controls. The Component 2 panel includes **Resume interrupted tasks** by run ID.

## Running tests

```
python -m pytest -q backend/tests/test_agent_memory_component3.py backend/tests/test_supervisor_component2.py
python -m pytest -q backend/tests
cd frontend && npm ci && npm run typecheck && npm run build
```

**Important testing limits:** Tests verify memory policies, real supervisor orchestration and restart reconstruction with an in-memory *test adapter*, plus that FalkorDB queries are tenant-scoped and target a separate graph. Live FalkorDB persistence/integration, provider behavior, and full frontend build must be exercised against your local stack. These are not yet live-certified. For UI screenshots and API tests, first set up the configured FalkorDB instance and model provider.

## Operational limitations and deliberate safeguards

- The workflow remains **read-only for business operations**. Memory writes are internal agent telemetry/knowledge only.
- No source-proof means no promotion. Only the graph-checkable structured predicates above are auto-promotable; free-text narratives are not.
- Rechecking happens at read time, but stale records do not automatically mutate themselves into a review state. The manual review endpoint records it durably.
- The checkpoint model is task-boundary resumability: interrupted RUNNING tasks are restarted; it does not replay the internal step-by-step LLM context of the interrupted task. Completed task results are reused.
- Concurrent attempts to resume the **same** run or promote **different** memories with the same identity across multiple application worker processes need a distributed lease/transactional compare-and-set for strict exactly-once guarantees. This release's locks are process-local. Do not expose duplicate resume requests concurrently in production until such a mechanism is added.
- Older Component 2 runs created before Component 3 do not have the new memory checkpoints and cannot be retroactively resumed by this endpoint.
- Promotion is conservative: incident-specific specialists may need to emit explicit, verifiable relation assertions to create durable shared memory; generic summaries alone will produce no shared facts.
