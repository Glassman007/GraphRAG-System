# Phase 7 Memory Promotion

## Artifact promotion state machine

```text
Finding/Hypothesis OPEN
  -> VERIFIED/VALIDATED
  -> PROMOTED

or

OPEN -> REJECTED
```

Promotion creates a new Claim. It never relabels the source object into a Claim.

```text
Finding|Hypothesis -[:PROMOTED_TO]-> Claim
Claim -[:DERIVED_FROM]-> Finding|Hypothesis
Evidence -[:SUPPORTS]-> Claim
Claim -[:VALIDATED_BY]-> Agent|Person
```

The promoted Claim records `promoted_at`, `promotion_rule`, confidence and temporal validity.

## Deterministic promotion rule

`phase7-validated-artifact-v1` requires:

1. source status VERIFIED/VALIDATED/PROMOTED;
2. confidence >= 0.65;
3. at least one validator;
4. at least one Evidence artifact;
5. at least one independent grounding Evidence path;
6. no unresolved Blocker;
7. no unresolved explicit contradiction.

Self-reinforcement is rejected: evidence produced by the source artifact or derived back from the source cannot be the sole grounding basis.

## Incident precedent

A closed Incident is precedent-eligible only when the graph contains:

- validated `Incident -[:ROOT_CAUSE]-> Claim`;
- a Decision `BASED_ON` the root cause;
- remediation Action reachable from an Incident Task;
- observed Outcome attached to the Action.

Promotion changes the Incident to `HISTORICAL` and `precedent_eligible=true`; no separate hardcoded precedent list exists. Existing Phase 4 structural precedent reasoning reads the learned graph naturally.

## Responsibility promotion

Verified ownership/responsibility change closes currently active competing intervals by setting `valid_until` and creates the new relationship with `valid_from`. Old edges are retained. Candidate work derived from the old actor is marked `STALE_INPUT`; parent Plans become `REPLAN_REQUIRED`.

## Expertise learning

One successful Task does not create `EXPERT_IN`. A completed Task + verified Finding + linked verifier creates an `ExpertiseEvidence` node and `Person|Agent -[:CANDIDATE_EXPERT]-> domain` with source provenance. Canonical expertise requires a later governed promotion rule.
