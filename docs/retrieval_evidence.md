# Retrieval Evidence and Provenance

A selected retrieval result becomes graph-linked Evidence only when `writeback=true`.

`RetrievalExecution` stores query, requesting context, graph-scope hash, `as_of`, retrievers used, status and result count. Relationships include:

```text
RetrievalExecution -[:REQUESTED_BY]-> Agent
RetrievalExecution -[:FOR_TASK]-> Task
Investigation/Question -[:HAS_RETRIEVAL]-> RetrievalExecution
RetrievalExecution -[:USED_SOURCE]-> DataSource
RetrievalExecution -[:RETURNED]-> Evidence
Agent -[:PRODUCED {production_mode: "retrieval"}]-> Evidence
Evidence -[:DERIVED_FROM]-> Chunk / Artifact / SourceRecord / DataSource
Evidence -[:ABOUT]-> Task / Investigation / matched canonical entities
```

Evidence IDs are deterministic over retrieval execution + origin + observation time. Re-running the same query context over the same source material reuses the same `RetrievalExecution`/Evidence IDs.

Retrieved Evidence is always `UNVERIFIED`. Retrieval score is stored separately and never treated as factual confidence. Claim validation/promotion remains a Phase 7 concern.

## Idempotent provenance

Retrieval writeback assigns deterministic IDs to execution/evidence relationships. An identical query plan reuses one RetrievalExecution and does not append duplicate provenance edges. Different lexical/vector/hybrid plans remain separate RetrievalExecutions, while a shared source observation may reuse the same Evidence node and be linked from each execution. Per-execution retrieval method/rank/score live on the `RETURNED` edge.
