# Phase 3 Temporal Repair Report

## Status

The temporal repair is implemented, but **44/44 is not claimed from this execution environment**. The sandbox does not have the `FalkorDB` Python package and has no FalkorDB server listening on `localhost:6379`, so integration tests skip before executing graph queries.

Verified here:

- `python -m compileall -q backend scripts` — passed
- `python scripts/validate_fixtures.py` — all fixtures passed validation
- `pytest -m "not integration" -v` — 15 passed
- `pytest backend/tests/test_integration_graph.py::test_temporal_history_lookup -vv -s` — skipped because FalkorDB client/server are unavailable
- `pytest -v` — 15 passed, 29 skipped for the same environment reason

The repository still contains exactly 44 collected tests; temporal regression coverage was added inside the existing `test_temporal_history_lookup` test so the expected final count remains 44.

## Root cause

The graph stored `created_at`, `observed_at`, `occurred_at`, `valid_from`, and `valid_until` as ISO-8601 strings and temporal queries compared those properties directly with relational operators such as `e.observed_at <= $as_of`.

That makes the database perform a string/general-value comparison rather than an application-defined chronological comparison. The reported failure — `E-004` at 14:12 being returned for an `as_of` of 14:09 — demonstrates that the representation/comparison contract is invalid for temporal reconstruction. It also cannot safely handle equivalent instants written with different timezone offsets.

## Representation chosen

Public timestamps remain timezone-aware ISO-8601 strings so API and provenance payloads are unchanged.

Every write also derives internal signed integer Unix epoch microseconds:

- `_ts_created_at_us`
- `_ts_observed_at_us`
- `_ts_occurred_at_us`
- `_ts_valid_from_us`
- `_ts_valid_until_us`

All chronological filtering and ordering uses those numeric properties. `as_of` values are parsed as timezone-aware timestamps and converted to the same unit before query execution.

Node range indexes used for temporal read paths now target `_ts_created_at_us`, `_ts_observed_at_us`, `_ts_occurred_at_us`, and policy `_ts_valid_from_us` rather than the public string properties.

## Files changed

Added:

- `backend/app/graph/temporal.py`
- `docs/temporal_repair_report.md`

Modified:

- `backend/app/graph/mutations.py`
- `backend/app/graph/queries.py`
- `backend/app/graph/phase3_queries.py`
- `backend/app/graph/schema.py`
- `backend/app/services/temporal_service.py`
- `backend/app/services/graph_service.py`
- `backend/app/services/provenance_service.py`
- `backend/app/services/phase3_utils.py`
- `backend/app/services/authority_resolution_service.py`
- `backend/app/services/claim_memory_service.py`
- `backend/app/services/ownership_gap_service.py`
- `scripts/seed_lib.py`
- `backend/tests/test_integration_graph.py`
- `docs/temporal_model.md`

No fixture timestamp values or ontology relationship semantics were changed.

## Regression coverage

The existing integration temporal test now checks:

- E-003 (before `as_of`) is included;
- E-004 (after `as_of`) is excluded;
- an event before `as_of` is included;
- an event after `as_of` is excluded;
- C-001 is included while later C-002 is excluded at an intermediate time;
- `valid_until` is exclusive for the historical `TEAM-GROWTH -> SYS-LEGACY-PROMO` ownership edge;
- `2026-10-16T14:09:00+05:30` and `2026-10-16T08:39:00Z` reconstruct the same state.

## Reseed / migration requirement

Yes. Graphs seeded before this repair do not have the `_ts_*_us` properties and must be reseeded or backfilled.

For the canonical local development graph:

```powershell
python scripts/reseed.py
```

The integration fixture creates a fresh test graph and calls `seed_all`, so running the integration suite after installing dependencies automatically tests a reseeded graph.

## Required real-FalkorDB verification

Run on the machine where FalkorDB is already available at `localhost:6379`:

```powershell
pip install -r requirements.txt
python scripts/reseed.py
pytest backend/tests/test_integration_graph.py::test_temporal_history_lookup -vv -s
pytest -v
```

The repair should only be marked complete after the final command reports `44 passed`.
