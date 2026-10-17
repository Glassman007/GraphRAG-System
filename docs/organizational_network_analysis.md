# Phase 8 — Organizational Bottleneck & Bridge Analysis

## Named projections

The service never computes centrality across every heterogeneous Company Brain relationship. It constructs one of four bounded projections from FalkorDB:

1. `system_dependency`: System ↔ System from `DEPENDS_ON`.
2. `ownership`: Person/Team/Agent ↔ System/Project from ownership/responsibility semantics.
3. `approval`: Actor ↔ governed object from `APPROVED_BY`.
4. `collaboration`: Person/Team connections from `MEMBER_OF`, `COLLABORATES_WITH`, and explainable shared Project participation.

Maximum projection size is 300 nodes / 1,500 undirected projected edges.

## Algorithms

- normalized degree centrality;
- normalized unweighted Brandes betweenness centrality;
- Tarjan DFS low-link articulation points;
- Tarjan DFS low-link bridge edges;
- bridge-separated connected components as a conservative community-boundary signal.

The community result is explicitly evidence for review, **not** a claim that a cluster is an organizational silo.

## Overload

A node is labeled overloaded only when:

- normalized betweenness >= 0.25, **and**
- operational load score >= 3.

Load signals are active Tasks, approval obligations, critical owned Systems, and active Commitments. High centrality by itself is not enough.

## Single-path risk

Bridge edges are returned as single-path risks together with the FalkorDB relationship paths that produced each projected edge.

## Canonical fixture

The collaboration projection contains `PERSON-DEV` as a bridge between the Security and Platform sides of the release-gate work. Adding a direct redundant `TEAM-SECURITY -[:COLLABORATES_WITH]-> TEAM-PLATFORM` route removes that unique articulation risk in the integration test.
