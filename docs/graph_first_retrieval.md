# Graph-First Retrieval

Graph-first retrieval answers **where to look** before any lexical or vector search occurs.

Default traversal relationships include `AFFECTS`, `DEPENDS_ON`, `CONTAINS`, `CHANGED`, `ABOUT`, `SUPPORTS`, `REFUTES`, `CONTRADICTS`, `PRODUCED`, `DERIVED_FROM`, `REFERENCES`, `NORMALIZED_TO`, `GOVERNS`, `DOCUMENTED_BY`, `HAS_ARTIFACT`, `PART_OF`, `ROOT_CAUSE`, `HAS_OUTCOME`, `PLAN_HAS_TASK`, `ADDRESSES`, `TRIGGERED`, `BASED_ON`, `SUPERSEDES`, `INGESTED`, `RESOLVES_TO`, `OWNS`, and `RESPONSIBLE_FOR`.

Traversal is bounded by request `max_graph_hops` (1..6) and an internal entity ceiling. Tenant scope is enforced by `GraphSnapshot.load`. `as_of` is applied to edges and temporal source records; tombstoned/superseded current SourceRecords are not selected for current retrieval.

A graph-scope result exposes seeds, entities, relationships, DataSources, SourceRecords, Artifacts, Documents, Chunks, paths, source types and temporal scope. The retrieval planner consumes this object.

Graph necessity is tested by deleting the Incident→System or SourceRecord→Artifact relationship and asserting that the corresponding source/artifact leaves retrieval scope. Out-of-scope lexical/vector distractors are filtered before retrieval ranking.

## Source-observation temporal semantics

Phase 9 may persist provenance edges at ingestion time after the source event occurred. For retrieval-specific provenance (`NORMALIZED_TO`, `REFERENCES`, source `DERIVED_FROM`, and Chunk `PART_OF`), historical graph scope uses the represented SourceRecord/Evidence/Chunk observation time rather than unsafe lexical timestamp comparison or the later ingestion timestamp. Supersession uses the newer source record's source-update/observation time. This keeps `as_of` retrieval historically meaningful without reseeding older Phase 9 graphs.
