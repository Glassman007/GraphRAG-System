# Document and Chunk Retrieval

`DocumentChunker` uses deterministic content-aware boundaries:
- Markdown headings;
- paragraph boundaries;
- top-level JSON keys;
- fixed-size fallback windows with configured overlap.

Default fallback configuration is 1200 characters with 120-character overlap. Chunk IDs are deterministic over parent document ID, sequence, content hash and chunking version (`phase10-chunk-v1`).

FalkorDB stores lightweight `Chunk` nodes and `Chunk -[:PART_OF]-> Artifact` relationships. Large text remains in ArtifactStore/derived indexes. Chunk metadata includes sequence, heading, character range, content hash and chunking version.

Direct document retrieval is allowed only when FalkorDB scope identifies an Artifact/Document candidate. It does not scan arbitrary filesystem paths.
