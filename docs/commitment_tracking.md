# Phase 8 — Commitment and Obligation Tracking

## Model

Commitments remain durable FalkorDB `Commitment` nodes. The service reconstructs:

- promisor via `PROMISED_BY` / `MADE_BY`;
- promisee via `OWED_TO`;
- subject via `COMMITTED_TO` / `ABOUT`;
- dependencies via `DEPENDS_ON` / `REQUIRES`;
- fulfillment via `SATISFIED_BY`;
- breach via `BREACHED_BY`;
- downstream consequences through incoming `DEPENDS_ON` / `REQUIRES` and outgoing `AFFECTS`.

## Status algorithm

Status precedence is:

1. explicit `BREACHED_BY` evidence → `BREACHED`;
2. explicit `SATISFIED_BY` evidence → `FULFILLED`;
3. explicit terminal lifecycle state;
4. `due_at` passed without fulfillment/breach evidence → `OVERDUE`;
5. due within configured risk window → `AT_RISK`;
6. otherwise `OPEN`.

An elapsed deadline alone is **not** treated as proof of breach. All date comparisons use the corrected timezone-aware epoch representation.

## Canonical cases

`COM-017` reconstructs Pricing Platform as promisor, Payments as promisee, Pricing API compatibility as subject, `E-003` as explicit breach evidence, and `DPL-882` as dependent work.

`COM-099` provides an overdue-but-not-proven-breached deadline case.

## Temporal queries

`as_of` filters nodes, relationships, and evidence. Historical queries therefore cannot use fulfillment or breach evidence that became valid later.
