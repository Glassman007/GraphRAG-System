# Entity Identity Semantics

## Canonical identity

Every canonical node has both `:Entity` and one domain label. Identity is `(tenant_id, id)`. The schema creates a composite range index and unique constraint on `:Entity(tenant_id, id)`.

IDs are stable opaque domain identifiers (`SYS-PRICING-API`, `PERSON-RIYA`, `INC-001`). Names are mutable display attributes and never identity keys.

## Aliases

Human aliases may live as an array/property on the canonical node only when they are simple display variants. Source-system identity must not be collapsed into that array.

## Source-specific IDs

Use `SourceRecord` nodes with `source_kind` and `source_entity_id`. This preserves source identity independently of the canonical node.

- accepted mapping: `SourceRecord -[:REPRESENTS {confidence:...}]-> Entity`
- uncertain mapping: `SourceRecord -[:CANDIDATE_MATCH {confidence,status:'UNRESOLVED'}]-> Entity`

## Duplicate prevention

1. Composite `Entity(tenant_id,id)` uniqueness is the hard canonical constraint.
2. Seed/import code uses `MERGE` on that identity.
3. Source records are resolved before creating a new canonical entity when a plausible mapping exists.
4. `CANDIDATE_MATCH` never automatically upgrades to `REPRESENTS` below a later configured confidence/evidence threshold.
5. A merge must preserve losing source IDs and provenance rather than deleting them.

The supporting identity fixture intentionally keeps `SRCREC-CRM-42 -> PERSON-RIYA` unresolved at confidence `0.72`.
