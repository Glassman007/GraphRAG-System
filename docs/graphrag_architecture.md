# Phase 10 GraphRAG Architecture

Phase 10 adds retrieval infrastructure without changing FalkorDB's role as the canonical organizational graph.

```text
RetrievalRequest
  -> GraphScopeResolver (FalkorDB first)
  -> RetrievalPlanner
  -> RetrieverRegistry
       -> BM25 lexical
       -> local vector/cosine
       -> direct document lookup
       -> graph metadata
       -> configured database source retrieval
       -> configured internal API source retrieval
  -> deterministic Reciprocal Rank Fusion
  -> graph-distance/source-authority tie-break
  -> RetrievalEvidenceService
  -> FalkorDB Evidence + RetrievalExecution
```

The derived lexical/vector indexes never become organizational truth. Every index entry carries tenant, Artifact, SourceRecord, DataSource, entity, temporal and content-hash metadata. If the derived index is deleted, the canonical graph and artifact provenance remain intact and the index can be rebuilt.

The `GraphScopeResolver` is mandatory. It resolves explicit seed entities first; if the request provides no seed it performs deterministic known-entity lookup over canonical graph properties. It then performs a bounded relationship-aware traversal. Specialized retrieval is restricted to graph-selected candidate material.

Retrieved snippets are stored only as `Evidence(status=UNVERIFIED)`. Phase 7 remains responsible for validation and promotion.
