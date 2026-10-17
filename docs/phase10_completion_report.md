# GraphHacks Phase 10 Completion Report

## Status

Phase 10 Graph RAG + supporting retrieval is implemented on top of the repaired Phase 9 repository. FalkorDB remains canonical and mandatory. Retrieval indexes are derived/rebuildable infrastructure. The implementation is deterministic/fixture-verified in this sandbox; real FalkorDB integration/browser verification remains pending because the FalkorDB Python client/server is unavailable here.

## 1. Baseline tests

- Phase 9 baseline collected: **418**
- Available sandbox baseline: **225 passed / 193 FalkorDB tests skipped / 0 failed**
- The Phase 10 work started from the latest Phase 9 repairs, including the `apply_schema.py` field correction, ingestion idempotency/tombstone/provenance/tenant repairs, and Python `True` tombstone fixture correction.

## 2. Final tests

- New Phase 10 tests: **110**
  - deterministic/unit: 74
  - FalkorDB integration: 27
  - FastAPI + FalkorDB: 9
- Final collected: **528**
- Sandbox result: **299 passed / 229 skipped / 0 failed**
- Skip reason: FalkorDB Python client/server unavailable in this sandbox.
- Local target: **528 passed / 0 failed / 0 skipped**.

## 3. Files added

### Retrieval package
- `backend/app/retrieval/__init__.py`
- `backend/app/retrieval/models.py`
- `backend/app/retrieval/utils.py`
- `backend/app/retrieval/lexical.py`
- `backend/app/retrieval/vector.py`
- `backend/app/retrieval/chunking.py`
- `backend/app/retrieval/graph_scope.py`
- `backend/app/retrieval/planner.py`
- `backend/app/retrieval/registry.py`
- `backend/app/retrieval/retrievers.py`
- `backend/app/retrieval/document.py`
- `backend/app/retrieval/fusion.py`
- `backend/app/retrieval/rerank.py`
- `backend/app/retrieval/evidence.py`
- `backend/app/retrieval/indexing.py`
- `backend/app/retrieval/service.py`

### Tests
- `backend/tests/test_phase10_algorithms.py`
- `backend/tests/test_phase10_integration.py`
- `backend/tests/test_phase10_api_integration.py`

### Scripts
- `scripts/rebuild_retrieval_indexes.py`
- `scripts/verify_phase10_browser.py`

### Documentation
- `docs/graphrag_architecture.md`
- `docs/graph_first_retrieval.md`
- `docs/lexical_retrieval.md`
- `docs/vector_retrieval.md`
- `docs/document_chunking.md`
- `docs/retrieval_routing.md`
- `docs/retrieval_evidence.md`
- `docs/retrieval_indexing.md`
- `docs/phase10_manual_acceptance.md`
- `docs/phase10_completion_report.md`
- `docs/phase10_algorithms_pytest_output.txt`
- `docs/phase10_pytest_output.txt`
- `docs/phase10_acceptance_sandbox_output.txt`

## 4. Files modified

- `README.md`
- `backend/app/main.py`
- `backend/app/domain/models.py`
- `backend/app/graph/schema.py`
- `backend/app/ingestion/pipeline.py`
- `backend/app/services/evidence_acquisition_service.py`
- `docs/ontology.md`
- `docs/relationships.md`
- `docs/provenance_model.md`
- `docs/capability_status.md`
- `docs/graph_necessity_tests.md`

## 5. GraphRAG architecture

```text
Question / Investigation
        ↓
FalkorDB GraphScopeResolver
        ↓
entities + paths + DataSources + SourceRecords + Artifacts + temporal scope
        ↓
RetrievalPlanner
        ↓
RetrieverRegistry
        ├─ BM25 lexical
        ├─ local vector/cosine
        ├─ direct Artifact/document
        ├─ graph metadata
        ├─ configured database source
        └─ configured internal API source
        ↓
RRF + deterministic graph/authority tie-break
        ↓
RetrievedEvidence
        ↓
RetrievalEvidenceService
        ↓
FalkorDB Evidence(status=UNVERIFIED)
```

The graph is the router. Vector/lexical systems cannot independently define organizational scope.

## 6. Graph-scope algorithm

`GraphScopeResolver`:
1. validates tenant;
2. uses supplied canonical seed IDs, or deterministic canonical property lookup only when no seed was supplied;
3. traverses an allowlisted set of organizational/provenance relationships;
4. applies `as_of` to edge/node temporal visibility;
5. excludes current tombstoned/superseded SourceRecords;
6. bounds graph hops to 1..6 and entity count;
7. returns explainable paths plus selected DataSources/SourceRecords/Artifacts/Documents/Chunks.

An explicit invalid seed does not silently trigger global entity discovery.

## 7. Lexical engine

`BM25LexicalIndex` implements standard deterministic BM25 with k1=1.5, b=0.75 and a small exact-phrase bonus. Graph-derived tenant/source/artifact/entity filters are applied before scoring. It is optionally JSON-persistent and fully rebuildable.

## 8. Vector engine

`LocalVectorIndex` stores retrieval-only vectors and canonical IDs. Cosine search applies tenant/graph/temporal filters before candidate scoring.

## 9. Embedding provider

Default: `HashingEmbeddingProvider` (`phase10-hash-semantic-v1`). It is a dependency-free deterministic offline provider using semantic concept normalization plus hashed token/bigram features. It is explicitly documented as a test/offline embedding, not as a production language embedding model. The provider interface allows FastEmbed/sentence-transformers/other providers without changing graph-first logic.

## 10. Chunking strategy

`DocumentChunker` uses Markdown headings, paragraph boundaries and top-level JSON structure where possible. Fallback is 1200-character chunks with 120-character overlap. Chunk IDs depend on parent, sequence, content hash and chunker version.

## 11. Chunk storage model

FalkorDB stores `Chunk` metadata only. `Chunk -[:PART_OF]-> Artifact`. The large body remains in ArtifactStore/derived lexical/vector indexes.

## 12. Index rebuild strategy

```powershell
python scripts/rebuild_retrieval_indexes.py
```

Rebuild source of truth: FalkorDB SourceRecord/Artifact references + Phase 9 ArtifactStore. Indexes are not canonical. The FastAPI rebuild endpoint and the standalone rebuild script both use the same tenant-scoped index directory and ArtifactStore; an integration regression test verifies that an externalized Phase 9 artifact is readable and indexed during rebuild.

## 13. Retrieval planner

Deterministic routing:
- exact identifiers/errors/policy wording -> LEXICAL;
- similarity/causal/historical/paraphrased request -> VECTOR;
- graph-selected Artifact -> DOCUMENT;
- source/time/status metadata -> METADATA;
- graph-selected configured database -> SQL mode;
- graph-selected configured internal API -> API mode.

For SQL/API modes, the default path uses already-ingested graph-linked SourceRecords. When `metadata_filters.refresh_external=true`, the retriever may call only the server-configured Phase 9 adapter selected by FalkorDB. Database retrieval therefore uses the configured read-only query template; API retrieval uses the configured host/path. Requests cannot supply SQL, URLs, or credentials. Every used retriever returns a reason.

## 14. Retriever registry

`RetrieverRegistry` maps `RetrievalMode` to replaceable implementations and only executes registered retrievers whose `can_handle` accepts the graph scope.

## 15. Hybrid ranking

Multiple retriever lists use Reciprocal Rank Fusion with k=60. Results are deduplicated by Chunk/Document/Artifact/SourceRecord identity. A tiny deterministic post-fusion tie-break uses graph distance and source trust class; it cannot erase lower-authority contradictory evidence.

## 16. Temporal filtering

All derived retrieval documents carry `observed_at`, `valid_from`, `valid_until`. Filtering uses the existing epoch-based temporal utilities. Regression tests enforce:
- E-003-era material at 14:08:14 is visible at 14:09;
- E-004-era material at 14:12 is invisible at 14:09.

No lexical timestamp comparison is used.

## 17. Tenant isolation

Graph scope uses tenant-filtered FalkorDB snapshots; lexical/vector indexes require exact tenant match. A request tenant differing from the graph client tenant is rejected.

## 18. Source authority

Trust class is a deterministic tie-break signal only. It never grants truth and never removes relevant contradictory lower-authority evidence.

## 19. Evidence writeback

`RetrievalEvidenceService` persists deterministic `RetrievalExecution` and `Evidence` nodes. Evidence links to Task/Investigation/matched entities and derives from Chunk/Artifact/SourceRecord/DataSource. The requesting Agent also has a direct `PRODUCED` edge to retrieved Evidence with `production_mode=retrieval`. `USED_SOURCE`, `RETURNED`, `REQUESTED_BY`, `FOR_TASK`, and `HAS_RETRIEVAL` preserve execution provenance.

Retrieved Evidence status is always `UNVERIFIED`. Writeback relationships use deterministic edge IDs, so rerunning an identical retrieval does not append duplicate `RETURNED`, `ABOUT`, `DERIVED_FROM`, or `HAS_RETRIEVAL` edges. Different retrieval plans receive distinct RetrievalExecution IDs while the same source observation can reuse one Evidence node through multiple `RETURNED` edges.

## 20. RetrievalExecution model

Properties include query, graph-scope hash, `as_of`, start/end time, status, retrievers used, and result count. Stable identity includes tenant/query/task/investigation/as_of/scope hash, enabling idempotent repeated writeback.

## 21. Phase 9 indexing integration

`IngestionPipeline` accepts a `RetrievalIndexer`. The production FastAPI ingestion helper now constructs the indexer by default, so safe Phase 9 ingestion automatically indexes SourceRecords/Artifacts after canonical graph writes. Tests can still construct a Phase 9 pipeline without an indexer, preserving Phase 9 semantics.

Source update/tombstone behavior updates derived validity instead of deleting historical retrieval material. Current graph scope suppresses Artifacts whose only SourceRecord provenance has been superseded/tombstoned, while historical `as_of` uses source observation/update time so old content remains retrievable in its valid interval.

## 22. Knowledge-Gap integration

A Phase 4 Question detected as a knowledge gap can pass through the existing `EvidenceAcquisitionService.retrieve_question()` bridge. Phase 4 still determines what evidence/source route is required; Phase 10 performs graph-scoped specialized retrieval.

## 23. Active Evidence Acquisition integration

`EvidenceAcquisitionService` was extended rather than replaced. It can use an injected retrieval service for tests/provider configuration and returns Phase 4 routing plus Phase 10 retrieval/evidence output.

## 24. APIs added

- `POST /retrieval/graph-scope`
- `POST /retrieval/search`
- `POST /retrieval/lexical`
- `POST /retrieval/vector`
- `POST /retrieval/document`
- `GET /retrieval/executions/{id}`
- `GET /retrieval/evidence/{id}`
- `POST /retrieval/index/rebuild`

No arbitrary Cypher, SQL, URL or filesystem query endpoint was added.

## 25. Tests added

110 tests cover BM25 behavior, semantic vector retrieval, chunking, graph scope, routing, hybrid fusion, temporal/tenant isolation, schema, actual FalkorDB scope/evidence/indexing, Graph Necessity, Phase 4/7 integration and FastAPI behavior.

## 26. Full test result

Sandbox:

```text
528 collected
299 passed
229 skipped
0 failed
```

The 229 skips are FalkorDB-backed tests because the FalkorDB Python package/server is absent here. This includes the inherited 193 integration tests plus the 36 Phase 10 integration/API tests.

## 27. Graph Necessity results

Implemented tests prove:
- deleting Incident→System changes/removes source/artifact scope;
- deleting SourceRecord→Artifact removes Artifact scope;
- unrelated keyword-heavy documents cannot bypass graph scope;
- unrelated semantic distractors cannot bypass graph scope;
- deleting retrieval Evidence→Artifact provenance removes that explanation path;
- temporal filter removal would expose future E-004 material.

The retrieval service has no fallback global-vector path when graph scope is absent.

## 28. Exact browser acceptance command

```powershell
python scripts/verify_phase10_browser.py
```

It creates and keeps an isolated `phase10_accept_<random>` graph; `company_brain` is not modified.

## 29. Browser queries

Exact queries are in `docs/phase10_manual_acceptance.md`. The isolated runner also generates `phase10_browser_queries_<graph>.cypher`.

## 30. Limitations / unimplemented providers

- Default local embedding is intentionally lightweight; production semantic model provider is not bundled.
- Live SQL query-template callbacks are not exercised in this sandbox; SQL mode is constrained to graph-selected configured Phase 9 database sources.
- Live internal API fetch-on-query is not exercised; API mode is constrained to graph-selected configured Phase 9 internal API sources.
- No arbitrary external URL, SQL, filesystem, web search or LLM-generated Cypher retrieval exists.
- No final conversational answer-generation layer or front-end was added.
- PDF OCR is not required/implemented by Phase 10.

## Migration / reseed

No destructive reseed is required. Run:

```powershell
python scripts/apply_schema.py
python scripts/rebuild_retrieval_indexes.py
```

Existing Phase 9 graph truth stays intact. Phase 10 derived indexes can be recreated at any time.

## Completion gate

Implementation is complete and deterministic tests are green. Do not mark environment verification complete until local FalkorDB returns:

```text
528 passed
0 failed
0 skipped
```

and:

```powershell
python scripts/verify_phase10_browser.py
```

prints `PHASE 10 ACCEPTANCE: PASS`.
