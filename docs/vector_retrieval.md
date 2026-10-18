# Vector Retrieval

`LocalVectorIndex` provides a rebuildable retrieval-only vector index. It depends on the `EmbeddingProvider` interface.

The default provider is `HashingEmbeddingProvider` (`phase10-hash-semantic-v1`). It is a deterministic, dependency-free local embedding intended for tests/offline development. It normalizes a small set of semantic concepts and uses feature hashing over tokens/bigrams. It is not presented as a production-quality language model embedding. A sentence-transformers/FastEmbed/provider implementation can replace it without changing graph-first routing.

Cosine similarity is computed only over candidates passing tenant, graph-source/artifact/entity and temporal filters. The implementation never searches the full vector index and then treats out-of-scope results as valid candidates.

The index stores only derived vectors plus canonical IDs. It is rebuildable from FalkorDB + ArtifactStore via `scripts/rebuild_retrieval_indexes.py`.
