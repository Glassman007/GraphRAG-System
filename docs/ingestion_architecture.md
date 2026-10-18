# Phase 9 Ingestion Architecture

## Boundary

External sources never mutate canonical organizational state directly.

```text
SourceAdapter
  -> SourceRecord
  -> Normalizer
  -> Relational Entity Resolution
  -> Provenance + Trust Classification
  -> Safe Graph Writer
  -> FalkorDB
```

Large bytes follow `SourceRecord -> ArtifactStore`, while FalkorDB receives only `Artifact` metadata/reference nodes.

## Orchestration

`IngestionPipeline` selects a registered adapter, fetches a bounded page, persists an `IngestionRun`, writes immutable/versioned SourceRecords, normalizes each record, resolves identities, quarantines ambiguity, externalizes configured artifacts, applies trust rules, performs safe graph writes, records events, and advances the source cursor only through safely committed records.

`dry_run=true` fetches, normalizes, resolves in read-only preview mode, and reports proposed mutations without creating DataSource, IngestionRun, SourceRecord, Artifact, identity or canonical graph state.

## Consistency

GraphHacks does not claim one ACID transaction across a remote provider, local ArtifactStore and FalkorDB. Safety comes from stable source identities/checksums, content-addressed artifacts, idempotent upserts, immutable SourceRecord versions, a cursor advanced only after commit, explicit PARTIAL/FAILED run state, and safe retry.

## Bounds

- request `max_records`: 1–10,000;
- batch size: 1–500;
- fixture/live adapters support source-specific cursors/pages;
- public APIs do not accept arbitrary external URLs or SQL.
