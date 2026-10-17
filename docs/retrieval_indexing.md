# Retrieval Indexing

Phase 9 ingestion accepts an optional `RetrievalIndexer`. After a SourceRecord is safely written, the indexer can index the SourceRecord and any externalized Artifacts automatically.

Artifact indexing:
1. read bytes from ArtifactStore;
2. create deterministic chunks;
3. update BM25 index;
4. update vector index;
5. persist lightweight `Chunk` metadata in FalkorDB;
6. connect `Chunk -[:PART_OF]-> Artifact`;
7. emit a deterministic `DOCUMENT_INDEXED` Event.

Unchanged content hashes are not re-embedded. Source updates mark the prior derived index version with `valid_until`; tombstones are not indexed as current content. Historical `as_of` retrieval can still use prior derived versions.

Rebuild command:

```powershell
python scripts/rebuild_retrieval_indexes.py
```

Indexes default under `.graphhacks_retrieval/<tenant>/`. Artifact bytes remain under the Phase 9 ArtifactStore root.

## Rebuild and source lifecycle

A rebuild clears the derived lexical/vector indexes before reconstructing them from FalkorDB SourceRecord/Artifact references and ArtifactStore bytes, so orphaned index entries cannot survive. Source supersession/tombstones close the validity interval of SourceRecord-derived retrieval documents and chunks without deleting historical material. The API rebuild endpoint and standalone script use the same tenant-scoped index directory and ArtifactStore.
