# Phase 8 — Duplicate Work / Initiative Collision

## Candidate generation

The service does not compare every Project pair blindly. It builds an inverted index from shared FalkorDB neighborhoods (`DEPENDS_ON`, `REQUIRES`, `ABOUT`, `AFFECTS`, ownership/responsibility) and scores only generated candidate pairs.

Bounds: maximum 250 Projects and 2,000 candidate pairs per request.

## Scoring model

Weights are explicit and sum to 1.0:

| Dimension | Weight |
|---|---:|
| lexical goal overlap | 0.35 |
| shared Systems | 0.20 |
| shared DataSources/datasets | 0.15 |
| shared stakeholders | 0.10 |
| shared requirements | 0.10 |
| shared dependencies | 0.10 |

Goal overlap uses deterministic token Jaccard similarity. Structural dimensions use graph-set Jaccard overlap.

Classification:

- explicit `COLLABORATES_WITH` → `INTENTIONAL_COLLABORATION`;
- score >= 0.70 → `HIGH_COLLISION`;
- score >= 0.40 → `POSSIBLE_COLLISION`;
- otherwise → `LOW_OVERLAP`.

A shared system alone therefore cannot create a high-collision result.

## Canonical scenario

`PROJ-REFUND-A` and `PROJ-REFUND-B` share refund goal context, `SYS-REFUND-API`, `DS-REFUND-TELEMETRY`, and `POL-REFUND-AUTO-01`; current fixture score is 0.90 (`HIGH_COLLISION`). `PROJ-REFUND-C` is a shared-system-only negative and scores about 0.3038 against A (`LOW_OVERLAP`).

Removing shared graph relations lowers the score in real-FalkorDB graph-necessity tests.
