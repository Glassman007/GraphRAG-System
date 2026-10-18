# Phase 6 — Three-Test Repair

## Reported failures

1. `test_phase6_fastapi_handoff_accept_fails_when_contract_is_invalid`
2. `test_phase6_missing_required_approval_prevents_execution`
3. `test_phase6_graph_necessity_compaction_validation_fails_when_evidence_lineage_removed`

## Repairs

### Handoff acceptance error contract

`HandoffService.accept_handoff()` still rejects an invalid contract exactly as before, but the error now states that the handoff **cannot be accepted** because the contract is invalid. This preserves the 409 API behavior and matches the acceptance-test message contract.

### Governance / mock executor isolation

Governance already returned `REQUIRES_APPROVAL` for an action with `approval_required=true` and no active `APPROVED_BY` edge. The failing `assert 1 == 0` came from the process-global mock sink retaining an invocation from an earlier integration test.

The shared mock sink remains shared for idempotent lookup/reconciliation semantics, but each default `ActionCoordinationService` now receives a scoped observation view. `service.executor.invocation_count()` therefore reports side effects generated during that service instance rather than unrelated historical test traffic.

Explicitly supplied `MockActionExecutor` instances are unchanged.

### Compaction lineage validation

`validate_compaction()` previously recomputed retained artifacts through current graph links. Removing `E-003 -[:ABOUT]-> Task` therefore caused E-003 to disappear from the set being validated, masking the broken lineage.

Validation now uses the `CompactionRecord.retained_entities` manifest persisted when compaction occurred. Every retained artifact in that manifest must still satisfy its required lineage. Removing the Evidence→Task relationship now produces `ARTIFACT_TASK_LINEAGE_BROKEN:E-003` and invalidates the compaction.

For compatibility with old/unit-created `CompactionRecord` objects without `retained_entities`, validation falls back to the reconstructed retained context.

## Files modified

- `backend/app/services/handoff_service.py`
- `backend/app/services/action_coordination_service.py`
- `backend/app/services/memory_compaction_service.py`

No test was weakened or removed. No reseed or schema migration is required for these repairs.

## Verification in this sandbox

- `python -m compileall -q backend scripts` — PASS
- `python scripts/validate_fixtures.py` — PASS
- `pytest -m "not integration" -q` — 78 passed
- `pytest -q` — 78 passed, 112 skipped, 0 failed

The 112 integration tests skip because the sandbox does not have the FalkorDB client/server. Run the three reported tests against the local FalkorDB instance, followed by the full suite.
