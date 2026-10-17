# Phase 6 Handoff Contracts

A handoff is a graph object, not a prose message.

## Persisted contract

`Handoff` records source/destination Task, sending/receiving Agent, contract type/version, required artifact kinds, confidence threshold and contradictory-evidence disclosure. Graph edges preserve task, receiver and artifact provenance:

```text
Handoff -[:HANDOFF_FOR]-> Task
Handoff -[:ASSIGNED_TO]-> Agent
Handoff -[:REQUIRES]-> Finding|Evidence
Handoff -[:DERIVED_FROM]-> Finding|Evidence
```

## Investigator -> Verifier

The deterministic contract requires:

- at least one Finding;
- at least one Evidence artifact;
- every transferred Finding at or above the threshold;
- contradictory evidence disclosure;
- no unresolved blocker on the source task.

Other worker-to-worker transfers require at least a Finding unless a stricter contract is defined.

## Validator output

`validate_handoff()` returns structured state:

```text
valid
errors
warnings
missing_fields
missing_evidence
unresolved_blockers
confidence_failures
```

A missing `Handoff -[:REQUIRES]-> Evidence` edge makes an Investigator->Verifier handoff invalid. That graph-necessity behavior is tested against FalkorDB.
