# Phase 10 Manual Acceptance

## Upgrade existing Phase 9 graph

No destructive reseed is required.

```powershell
python scripts/apply_schema.py
python scripts/rebuild_retrieval_indexes.py
pytest -v
```

`apply_schema.py` adds the Phase 10 index foundations. `rebuild_retrieval_indexes.py` rebuilds derived lexical/vector/chunk indexes from FalkorDB references + the Phase 9 ArtifactStore.

## Isolated canonical browser runner

```powershell
python scripts/verify_phase10_browser.py
```

The runner creates `phase10_accept_<random>` and does **not** modify `company_brain`. It keeps the graph for FalkorDB Browser inspection and writes:

```text
phase10_acceptance_report_<graph>.json
phase10_browser_queries_<graph>.cypher
```

It verifies Phase 9 auto-indexing, graph scope, exact lexical error retrieval, semantic historical retrieval, hybrid retrieval, Evidence writeback/idempotency, 14:09 temporal filtering, and a graph-necessity edge removal.

## Swagger demo

Start the API:

```powershell
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs`.

### A. Inspect graph scope first

`POST /retrieval/graph-scope`

```json
{
  "query": "Why did Checkout fail during DPL-882?",
  "seed_entity_ids": ["INC-001"],
  "max_graph_hops": 6,
  "max_results": 10,
  "writeback": false
}
```

Confirm the response exposes graph entities/paths and only graph-selected DataSources/SourceRecords/Artifacts.

### B. Graph-first search

`POST /retrieval/search`

```json
{
  "query": "Why did Checkout fail during DPL-882?",
  "seed_entity_ids": ["INC-001"],
  "investigation_id": "INC-001",
  "retrieval_modes": ["LEXICAL", "VECTOR"],
  "max_graph_hops": 6,
  "max_results": 10,
  "writeback": true
}
```

Confirm:
- `graph_required=true`;
- retriever reasons are returned;
- every result exposes Artifact/SourceRecord/DataSource provenance where available;
- `execution_id` exists;
- `evidence_ids` exist;
- Evidence remains `UNVERIFIED`.

### C. Exact error

`POST /retrieval/lexical`

```json
{
  "query": "region_scope cannot be null",
  "seed_entity_ids": ["INC-001"],
  "max_graph_hops": 6,
  "writeback": false
}
```

The relevant pricing log/chunk should outrank within scope. An unrelated exact-keyword artifact outside the graph scope must not appear.

### D. Semantic historical case

`POST /retrieval/vector`

```json
{
  "query": "schema compatibility during mixed rollout",
  "seed_entity_ids": ["INC-074"],
  "max_graph_hops": 6,
  "writeback": false
}
```

The local default semantic provider should retrieve the historical wording around an old/legacy worker being rejected after a database/schema constraint migration when that artifact is inside graph scope.

### E. Temporal regression

```json
{
  "query": "region_scope cannot be null",
  "seed_entity_ids": ["INC-001"],
  "retrieval_modes": ["LEXICAL"],
  "as_of": "2026-10-16T14:09:00+05:30",
  "max_graph_hops": 6,
  "writeback": false
}
```

Evidence/source material observed at 14:08:14 may be returned. Material first observed at 14:12 must not be returned.

## FalkorDB Browser queries

Use the isolated graph from `verify_phase10_browser.py` or adapt the tenant/IDs to `company_brain`.

### 1. Retrieval executions

```cypher
MATCH (r:RetrievalExecution {tenant_id:'northstar'})
RETURN r
ORDER BY r.completed_at DESC;
```

### 2. Retrieval execution -> Evidence

```cypher
MATCH (r:RetrievalExecution {tenant_id:'northstar'})-[:RETURNED]->(e:Evidence)
RETURN r.id, r.query, e.id, e.retrieval_method, e.status, e.retrieval_score;
```

### 3. Selected DataSources

```cypher
MATCH (r:RetrievalExecution {tenant_id:'northstar'})-[:USED_SOURCE]->(ds:DataSource)
RETURN r.id, ds.id, ds.name, ds.source_type, ds.trust_class;
```

### 4. Document -> Chunk -> Artifact

```cypher
MATCH (c:Chunk {tenant_id:'northstar'})-[:PART_OF]->(a:Artifact)
RETURN c.id, c.heading, c.sequence, c.content_hash, a.id, a.uri;
```

### 5. Evidence -> Chunk/Artifact/SourceRecord

```cypher
MATCH (e:Evidence {tenant_id:'northstar'})-[:DERIVED_FROM]->(x)
WHERE e.evidence_type='RETRIEVED'
RETURN e.id, labels(x), x.id, x.name;
```

### 6. Evidence -> Task

```cypher
MATCH (e:Evidence {tenant_id:'northstar'})-[:ABOUT]->(t:Task)
WHERE e.evidence_type='RETRIEVED'
RETURN e.id, t.id, t.name;
```

### 7. Investigation -> RetrievalExecution

```cypher
MATCH (i:Entity {tenant_id:'northstar'})-[:HAS_RETRIEVAL]->(r:RetrievalExecution)
RETURN i.id, labels(i), r.id, r.query;
```

### 8. Complete provenance path

```cypher
MATCH p=(i:Entity {tenant_id:'northstar'})-[:HAS_RETRIEVAL]->(r:RetrievalExecution)-[:RETURNED]->(e:Evidence)-[:DERIVED_FROM]->(c:Chunk)-[:PART_OF]->(a:Artifact)
RETURN p;
```

### 9. Artifact -> SourceRecord -> DataSource

```cypher
MATCH (sr:SourceRecord {tenant_id:'northstar'})-[:REFERENCES]->(a:Artifact)
MATCH (sr)-[:DERIVED_FROM]->(ds:DataSource)
RETURN a.id, sr.id, sr.observed_at, ds.id, ds.source_type;
```

### 10. Temporal source material around 14:09

```cypher
MATCH (sr:SourceRecord {tenant_id:'northstar'})-[:REFERENCES]->(a:Artifact)
WHERE sr.observed_at IS NOT NULL
RETURN sr.id, sr.observed_at, a.id
ORDER BY sr.observed_at;
```

The retrieval API, not a lexical timestamp comparison in Cypher, applies the repository's epoch temporal utilities.

## Graph necessity demonstration

In the isolated graph, identify the SourceRecord→Artifact edge for the exact error artifact. Delete it temporarily:

```cypher
MATCH (sr:SourceRecord {tenant_id:'northstar'})-[r:REFERENCES]->(a:Artifact)
WHERE sr.source_entity_id='p10-e003'
DELETE r;
```

Repeat `POST /retrieval/graph-scope` / `POST /retrieval/lexical`. That Artifact must leave the selected scope/result set. Restore from the generated `.cypher`/acceptance graph by rerunning the isolated runner if desired.
