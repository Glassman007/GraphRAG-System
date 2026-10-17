# Entity Resolution During Ingestion

Phase 9 wraps the existing Phase 4 Relational Entity Resolution service instead of implementing a second matcher.

For identity-bearing normalized entities the pipeline creates a source identity projection, asks the existing resolver for graph-context candidates, and applies conservative ingestion thresholds. Verified email, reviewed source identity or other independent relational signals are required for automatic Person matching; name equality alone is insufficient.

Outcomes:

- `MATCHED`: ExternalIdentity is connected to an existing canonical entity with `RESOLVES_TO`.
- `CREATED`: strong stable identity evidence permits a new canonical entity.
- `POSSIBLE_MATCH` / `UNRESOLVED`: an `IngestionQuarantineRecord` preserves candidates, scores/reasons and proposed normalized meaning.

Manual quarantine resolution confirms the existing Phase 4 match rather than duplicating canonical nodes.
