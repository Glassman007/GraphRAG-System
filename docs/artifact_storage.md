# Phase 9 Artifact Storage

`LocalArtifactStore` is the deterministic Phase 9 implementation of the ArtifactStore abstraction.

Bytes are content-addressed under a tenant/source/hash path. `sha256` is both an integrity check and the physical deduplication key. Reingesting identical content reuses the existing payload rather than writing another physical object.

Always-externalized artifact classes include PDF, image, log, trace, source file, archive and document payloads. Generic structured content is externalized only when it exceeds `GRAPH_HACKS_ARTIFACT_THRESHOLD_BYTES` (default 16 KiB).

FalkorDB stores only lightweight `Artifact` metadata (`id`, URI, hash, MIME type, size, source, created time) and provenance relationships. Evidence and SourceRecords can therefore trace back to bytes without placing large blobs in graph properties.
