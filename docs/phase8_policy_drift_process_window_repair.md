# Phase 8 Policy Drift — Process-Window Temporal Repair

## Root cause

`PolicyDriftService` previously reduced the observed process to the earliest Event timestamp and queried `GOVERNS` relationships at that single point. A process is an interval, so a policy-scope relationship becoming valid later in the same process was incorrectly omitted. When `GOVERNS` disappeared, approval discovery had no governed target or containing Deployment and emitted a false `MISSING_APPROVAL`.

## Repair

The service now derives `process_start` and `process_end` from reconstructed Event timestamps and evaluates policy-scope relationships by interval overlap:

```text
valid_from <= process_end
AND
(valid_until is null OR valid_until > process_start)
```

Comparisons use `to_epoch_us`; no lexical ISO timestamp comparison is used.

For each governed target, approval discovery checks direct `APPROVED_BY` edges and active `CONTAINS` containers. Approval is evaluated at the governed operation time using observed deployment/change timestamps, process Events, containment activation, and finally policy-scope activation. A pre-operation approval is valid; an approval that first appears after operation start is not retroactive.

Historical `as_of` behavior is preserved because process reconstruction excludes future Events and the resulting process window bounds relationship overlap.

## Regression coverage

Added deterministic tests for:

1. approval between process start and governed operation;
2. missing approval;
3. approval only after operation execution;
4. `GOVERNS` completely outside process interval;
5. partial `GOVERNS` overlap;
6. historical `as_of` before approval;
7. historical `as_of` after approval and governed action;
8. real-FalkorDB process-window approval path integration.

The pre-existing canonical and genuinely-unapproved tests remain unchanged.
