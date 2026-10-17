# Phase 8 — Policy-vs-Practice Drift

## Purpose

`PolicyDriftService` compares a policy-derived expected process graph with the observed process reconstructed from FalkorDB. It does not infer compliance from prose alone and does not hardcode `INC-001` or `POL-DB-04`.

## Expected graph

Expected requirements are read from active policy relationships/properties, primarily `REQUIRES`, `GOVERNS`, structured approval requirements, ordering requirements, evidence requirements, and allowed/prohibited actions.

Historical analysis selects the policy version whose validity interval contains the process start. A later policy is not applied retrospectively.

Policy **scope relationships** are process-window aware rather than evaluated only at the first event. The observed process derives `process_start` and `process_end` from reconstructed Events, and a relationship such as `GOVERNS` is relevant when its half-open validity interval overlaps that process window:

```text
valid_from <= process_end
AND
(valid_until is null OR valid_until > process_start)
```

All comparisons use timezone-aware epoch microseconds via the repository temporal utilities; ISO strings are not compared lexically. Historical `as_of` reconstruction still bounds the process window, so future relationships cannot leak backward.

## Observed graph

Observed state comes from Events, Tasks, Actions, approvals, evidence, handoffs, Outcomes, and the process reconstruction service.

## Deterministic drift classes

- `MISSING_REQUIRED_STEP`
- `ORDER_VIOLATION`
- `MISSING_APPROVAL`
- `MISSING_EVIDENCE`
- `UNAUTHORIZED_ACTOR`
- `UNEXPECTED_STEP`
- `BYPASSED_CONTROL`
- `OUTDATED_POLICY_USAGE`
- `OPTIONAL_VARIATION`

Each result distinguishes `VIOLATION`, `DEVIATION`, `PERMITTED_VARIATION`, or `UNKNOWN` and returns expected/observed graph paths.

## POL-DB-04

`POL-DB-04 -[:REQUIRES]-> ACT-COMPAT-TEST` and `ACT-DOWNSTREAM-VERIFY` are evaluated against the actual observed state. In the canonical fixture these actions are `SKIPPED` / `NOT_RECORDED`, so the missing-control findings are derived from the graph. Owner approval is not falsely reported missing because `POL-DB-04 -[:GOVERNS]-> MIG-203`, `DPL-882 -[:CONTAINS]-> MIG-203`, and `DPL-882 -[:APPROVED_BY]-> PERSON-ARJUN` form the applicable approval path. Approval is evaluated at the governed operation time: it may predate the deployment/change, but an approval first becoming valid after the operation begins cannot retroactively satisfy the requirement.

## Graph necessity

If the policy `REQUIRES` edge is removed, the corresponding expected requirement disappears and the detector can no longer derive that specific violation. This is exercised by a real-FalkorDB integration test.
