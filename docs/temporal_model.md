# Temporal / Version Semantics

## Time meanings

- `created_at`: when this graph object was created/recorded.
- `observed_at`: when evidence/source data says an observation occurred.
- `occurred_at`: event time in the append-oriented event ledger.
- `valid_from`: when a relationship/policy/ownership assertion became valid.
- `valid_until`: exclusive end of validity. Missing means still current unless superseded by domain rules.

These timestamps are **not interchangeable**. Ingestion later may occur after the event it records.

## Storage and comparison representation

The public/provenance timestamp fields above remain timezone-aware ISO-8601 strings. They are retained exactly as domain data so existing API payloads and fixture semantics do not change.

Chronological filtering and ordering **must not compare those strings directly**. Different timezone offsets can represent the same instant, and string relational operators are not the temporal contract of the application.

Every node/relationship mutation derives an internal integer Unix epoch value in **microseconds**:

- `created_at` -> `_ts_created_at_us`
- `observed_at` -> `_ts_observed_at_us`
- `occurred_at` -> `_ts_occurred_at_us`
- `valid_from` -> `_ts_valid_from_us`
- `valid_until` -> `_ts_valid_until_us`

All `as_of` inputs are parsed as timezone-aware ISO-8601 timestamps and converted to epoch microseconds before a FalkorDB query is executed. `Z` and explicit numeric offsets are supported. Naive timestamps are rejected because silently assigning a timezone would make historical reconstruction ambiguous.

The `_ts_*_us` fields are implementation properties. Service/API serializers strip them from returned graph objects.

## Seeding and mutation rule

`backend/app/graph/mutations.py` is the canonical write path and derives the internal epoch values for all temporal fields. `scripts/seed_lib.py` uses the same conversion while loading fixtures, so seeded data and API-created data have identical temporal semantics.

Existing graphs seeded before this representation was introduced do not contain the `_ts_*_us` properties. They must be reseeded (or equivalently migrated/backfilled) before running temporal queries. For the local canonical graph, use `python scripts/reseed.py`.

## Ownership and dependency history

Never replace an old `OWNS` or `DEPENDS_ON` edge with a new edge and discard the past. Close the old edge with `valid_until`, then create the new edge with a later `valid_from`. Current-state queries filter to `valid_until IS NULL`; historical queries compare the requested epoch timestamp against `_ts_valid_from_us` / `_ts_valid_until_us`.

The canonical fixture demonstrates this with `TEAM-GROWTH -[:OWNS]-> SYS-LEGACY-PROMO` ending on `2026-07-01`. A current owner query returns none; a June 2026 query returns Growth Integrations. `valid_until` is exclusive, so the relationship is not active at exactly `2026-07-01T00:00:00+05:30`.

## Supersession

Use `SUPERSEDES` when a new Claim/Decision/Policy version replaces the currently preferred version but the old node must remain auditable. Supersession does not delete the predecessor.

## Event ordering

Primary ordering uses `_ts_occurred_at_us`, while `Event.occurred_at` remains the public timestamp. `BEFORE` is stored when ordering is semantically important, clocks may be ambiguous, or a causal/process sequence must be explicit.

## Decision-time reconstruction

For an `as_of` timestamp:

1. parse the timezone-aware input and convert it to epoch microseconds;
2. include only Claims with `_ts_created_at_us <= as_of_us`;
3. include only Evidence with `_ts_observed_at_us <= as_of_us`;
4. include only Events with `_ts_occurred_at_us <= as_of_us`;
5. include ownership/dependency/policy edges where `_ts_valid_from_us <= as_of_us < _ts_valid_until_us`, allowing either boundary to be open when absent;
6. follow `BASED_ON`, `APPROVED_BY`, `DERIVED_FROM`, and actor edges to preserve provenance.

This supports questions such as “what was believed at 14:09?” without cloning the entire graph for every timestamp, and produces the same result when the same instant is supplied using another timezone offset.

## Branches and counterfactuals

Hypothetical states must not mutate canonical temporal truth. Later phases should use `WorkBranch` or an isolated temporary projection for speculative/counterfactual computation and explicitly promote validated results.


## Phase 5 historical planning

`WorkPlanningService` accepts an optional timezone-aware `as_of`. Historical planning uses the same corrected epoch-microsecond temporal contract as replay:

- graph nodes created/observed/occurred after `as_of` are not eligible planner inputs;
- graph relationships are traversed only when their numeric validity interval contains `as_of`;
- future Questions/Claims/Events/ownership relationships are not allowed to leak into the historical plan;
- the deterministic Plan ID includes the historical cutoff, so a historical projection does not overwrite the current plan for the same situation and goal.

The service converts `as_of` with `to_epoch_us`; it does not reintroduce ISO-string ordering. Current plans (`as_of` omitted) consume canonical current graph truth.

The Phase 5 planner also passes the same `as_of` into the existing Phase 4 `ConstraintPlanningService`. That service applies the cutoff to Action `ABOUT`, `REQUIRES`, `BLOCKED_BY`, Policy `GOVERNS`, and `APPROVED_BY` traversals. This prevents future remediation or policy structure from leaking into a historical Plan while leaving the Phase 4 default current-state API unchanged.

The same cutoff is propagated into knowledge-gap membership and Question→Tool/DataSource routing. Historical Claim eligibility is based on whether an incoming `SUPERSEDES` relationship is active at the cutoff; a current materialized `status=SUPERSEDED` does not by itself erase the Claim from an earlier historical view. Similarly, a Question currently marked resolved is considered unresolved at an earlier cutoff when no `RESOLVED_BY` Evidence is yet visible at that time.

Plan/Task creation itself is current write-time state. Historical planning therefore means “derive a plan from graph knowledge visible at that cutoff,” not backdate the creation event.

## Phase 7 learning time

Phase 7 continues the epoch-microsecond comparison contract. New public timestamps include `promoted_at`, `invalidated_at`, `stale_since`, `revalidated_at`, `completed_at` and Outcome `observed_at` where semantically appropriate.

Responsibility promotion closes old `OWNS`/`RESPONSIBLE_FOR` relationships at the exact effective instant and creates the new relationship at the same instant. Because `valid_until` is exclusive, a historical query before the change returns the old owner while a current query at/after the change returns the new owner.

Claims are never physically deleted on supersession/invalidation. `SUPERSEDES`, status changes and event-ledger timestamps preserve historical truth.

# Phase 9 source-time semantics

Phase 9 keeps five source/canonical times distinct:

1. **source event / observed time** — when the organizational event was observed to happen;
2. **source_updated_at** — when the provider says its record changed;
3. **fetched_at** — when the adapter fetched the record;
4. **ingested_at / IngestionRun time** — when GraphHacks committed the source record;
5. **canonical validity (`valid_from` / `valid_until`)** — when an organizational fact is considered applicable.

Canonical event time is never replaced by fetch/ingestion time. All canonical temporal relationship comparisons continue to use the repository's timezone-aware epoch-microsecond utilities; no lexical ISO timestamp ordering is introduced.

Incremental cursor movement occurs only after records through that cursor are safely committed. Partial failure leaves the cursor at the last committed record, making retry idempotent.
