# Source Control Plane

Phase 13 adds a product-facing source control plane over the existing Phase 9 ingestion system. `ConnectorDefinition` remains code-backed while each tenant-owned source is persisted as a managed `DataSource` (`managed_by=phase13-source-control`). No competing canonical source ontology is introduced.

## Components
- `ConnectorDefinition`: capabilities, auth methods, scopes, fixture/live support.
- `SourceControlService`: lifecycle, test, preview, sync, records, errors, identity review and lineage.
- `CredentialStore`: server-side credential abstraction; graph stores only opaque references.
- Existing Phase 9 `SourceRegistry`, adapters, normalizers, resolution, ArtifactStore and `IngestionPipeline` perform the real work.

## Public API
`/api/v1/connectors`, `/api/v1/sources`, source test/preview/sync/enable/disable, runs, records, errors, identity review, and entity lineage.

Deleting a product configuration does not delete historical Company Brain provenance.
