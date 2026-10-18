# Phase 8 — Organizational Process Reconstruction

## Purpose

`OrganizationalProcessReconstructionService` reconstructs an observed workflow from FalkorDB state. It is read-only analytics: the service loads a bounded `GraphSnapshot` from the canonical FalkorDB graph and returns structured process steps and relationship classes with graph IDs and provenance paths.

## Semantic contract

The engine never treats these relationships as synonyms:

| Semantic | Meaning | Allowed derivation |
|---|---|---|
| `BEFORE` | temporal ordering only | explicit edge or timestamp ordering reported as temporal order |
| `TRIGGERED` | A explicitly initiated B | explicit `TRIGGERED` edge only |
| dependency | B required A / depends on A | `REQUIRES`, `BLOCKED_BY`, `DEPENDS_ON` |
| cause | A is supported as causally responsible for B | explicit validated `CAUSE`, or validated root-cause Claim with Evidence lineage |

`A BEFORE B` alone never produces a causal edge.

## Algorithm

1. Resolve the requested scope (`Incident`, `Plan`, `Task`, or another graph entity).
2. Traverse only the configured process-link relationships to a maximum depth of 4.
3. Collect at most 250 Events in the scoped subgraph.
4. Order steps by corrected numeric temporal representation (`occurred_at`/`created_at`) for display.
5. Preserve equal/incomplete timestamps as ambiguous rather than inventing causal order.
6. Separately emit explicit temporal, trigger, dependency, and causal relationships.
7. Include actors, ABOUT entities, producing artifacts, and graph paths for explanation.

## Bounds and complexity

The scope traversal is bounded by depth 4 and event count 250. Work is proportional to the bounded scoped subgraph, not the whole enterprise graph.

## Canonical acceptance

For `INC-001`, the support fixture adds the explicit graph edge:

`EVT-INC-001 -[:TRIGGERED]-> EVT-TASK-INV`

so reconstruction can distinguish the incident-triggered investigation from events that merely occurred later.
