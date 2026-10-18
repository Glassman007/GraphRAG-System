# Phase 7 Knowledge Invalidation

Invalidation is bounded and relationship-specific. A random neighboring node is never marked stale merely because it is connected.

## Supported triggers

Implemented deterministic triggers include:

- Evidence invalidation/retraction;
- Claim supersession;
- Policy supersession;
- source-authority degradation;
- verified ownership/responsibility replacement;
- system dependency changes;
- entity-resolution changes where active work depends on the affected identity;
- observed Outcomes that explicitly `REFUTES` a Claim;
- new replacement Evidence revalidation.

Action outcomes do not automatically become causal truth. Outcome invalidation triggers only when the graph explicitly states `Outcome -[:REFUTES]-> Claim`; this preserves the distinction between an execution failure and an observed contradiction of an organizational assumption.

## Evidence propagation

```text
Evidence INVALIDATED
  -[:SUPPORTS]-> Claim REQUIRES_REVALIDATION / INVALIDATED
  <-[:BASED_ON]- Decision REQUIRES_REVIEW
  <-[:ADDRESSES]- Task STALE_INPUT
  <-[:PLAN_HAS_TASK]- Plan REPLAN_REQUIRED
```

If all valid support disappears, the Claim becomes `INVALIDATED`. If other valid support remains, the Claim becomes `REQUIRES_REVALIDATION`.

## Historical truth

Invalidation never deletes the Event, Claim, Decision, Task, old ownership edge, rejected branch or Evidence. Status/time fields and event-ledger entries explain when/why applicability changed.

## Graph necessity

Propagation follows only `SUPPORTS`, `BASED_ON`, `ADDRESSES`, `PLAN_HAS_TASK`, `GOVERNS`, and candidate-routing relationships with defined semantics. Removing one of those edges removes the corresponding downstream impact in tests.
