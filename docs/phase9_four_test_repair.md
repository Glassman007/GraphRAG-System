# Phase 9 four-test integration repair

## Reported live failures

1. `test_phase9_full_resync_is_idempotent`
2. `test_phase9_tombstone_creates_evidence_not_hard_delete`
3. `test_phase9_multiple_sources_for_same_fact_do_not_duplicate_active_relationship`
4. `test_phase9_tenant_scoping_prevents_cross_tenant_source_visibility`

## Repairs

### Full resync idempotency
`IngestionRun` and its run-start audit Event are intentionally new audit objects on every sync, but both carried the generic `source_id` property used by the test to identify source-owned canonical ingestion objects. That made an unchanged full resync look non-idempotent because the source-scoped node-ID set gained volatile audit IDs.

Run nodes now persist the source as `source_ref_id` plus the existing `IngestionRun -[:DERIVED_FROM]-> DataSource` edge. `GET /ingestion/runs` and `GET /ingestion/runs/{id}` continue to expose `source_id`, derived from this provenance. This preserves distinct run audit history while keeping source-record/canonical identity sets idempotent.

### Tombstone lineage
Tombstone impact reconstruction depends on durable `SourceRecord -[:NORMALIZED_TO]-> canonical entity` lineage from older source versions. The pipeline wrote this lineage during resolution, but the graph writer did not enforce it as a write postcondition.

The writer now always upserts a deterministic `NORMALIZED_TO` edge for every resolved entity. The edge uses a stable tenant/source-record/canonical/mapping identity, so it is idempotent across resyncs and remains available for tombstone reconstruction.

### Multi-source provenance on one active fact
The first authoritative ownership assertion was promoted by Phase 7, which created the canonical `OWNS` edge with Phase 7 validation provenance but without Phase 9 `source_record_ids_csv`. A later source then appended only its own SourceRecord, leaving one instead of both.

After successful Phase 7 responsibility promotion, Phase 9 now immediately enriches the promoted canonical edge with the originating SourceRecord. Subsequent equivalent sources merge their SourceRecord IDs into the same active relationship. Existing single `source_record_id` metadata is also folded into the provenance set when present.

### Tenant isolation
Phase 9 generated canonical identity, identity-projection, ExternalIdentity and SourceRecord IDs without tenant namespace. The graph mutations are already tenant-qualified, but generated IDs are now also tenant-qualified as a defense-in-depth invariant for shared FalkorDB graphs.

Explicit canonical hints are unchanged. Cross-source records within the same tenant still resolve to the same canonical identity; equivalent external records in different tenants now have distinct generated IDs.

## Files modified

- `backend/app/ingestion/pipeline.py`
- `backend/app/ingestion/provenance/service.py`
- `backend/app/ingestion/resolution/service.py`
- `backend/app/ingestion/writer/graph_writer.py`
- `backend/tests/test_phase9_algorithms.py`

## Verification in this sandbox

- `pytest backend/tests/test_phase9_algorithms.py -q` -> `64 passed`
- `pytest -m "not integration" -q` -> `225 passed, 193 deselected`
- four targeted real-FalkorDB tests -> skipped because FalkorDB Python client/server are unavailable here

Two deterministic regressions were added for tenant-namespaced SourceRecord IDs and public run source-ID derivation. Total collected tests are now 418.
