# Phase 8 — Organizational Bus-Factor Analysis

## Model

Bus factor is resource/capability-specific, not a single company-wide degree count. For each resource the service measures independent coverage for:

- ownership (`OWNS`);
- responsibility (`RESPONSIBLE_FOR`);
- expertise (`EXPERT_IN`);
- approval authority (`APPROVED_BY` on the resource or bounded related operational objects).

The reported bus factor is the minimum non-zero independent coverage count across represented dimensions. Risk also considers resource criticality; graph degree alone is never used as bus factor.

## Loss simulation

`simulate_loss` excludes selected actors from the analysis projection without deleting or changing canonical FalkorDB data. It compares before/after coverage and reports newly missing ownership, expertise, responsibility or approvals, plus Tasks whose entire candidate set is unavailable.

## Temporal behavior

All coverage edges respect `valid_from` / `valid_until` through `as_of`. This allows historical concentration questions without future owners/experts leaking into the result.

## Canonical fixture

`SYS-LEDGER-EXPORT` is HIGH criticality and has `PERSON-ISHA` as its only modeled expert. The fixture therefore derives a single-expert concentration risk. Adding a second valid `EXPERT_IN` edge reduces that concentration in the integration test.

## Bounds

The organizational summary is bounded to 300 resources/actors and an explicit caller limit.
