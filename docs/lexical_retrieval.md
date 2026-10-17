# Lexical Retrieval

The default lexical implementation is deterministic BM25 (`BM25LexicalIndex`). It is local, dependency-free and optionally persisted as a JSON derived index.

Indexed records retain:
- canonical document/chunk ID;
- tenant;
- Artifact ID;
- SourceRecord ID;
- DataSource ID;
- relevant canonical entity IDs;
- document type;
- `observed_at`, `valid_from`, `valid_until`;
- content hash and metadata.

Search applies graph-derived document/source/artifact/entity filters **before scoring**. Exact phrases get a small deterministic phrase bonus after BM25. Tenant and temporal filters are mandatory.

A keyword-heavy unrelated document is explicitly tested to ensure it cannot outrank or appear beside the graph-scoped relevant result.
