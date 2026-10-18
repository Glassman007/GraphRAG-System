# Phase 7 Learning Loop

Phase 7 closes the loop without creating a second memory store. FalkorDB remains canonical.

```text
Company Brain -> reasoning -> Plan/Task -> coordinated execution -> Action/Outcome
     ^                                                        |
     |                                                        v
     +---- writeback <- validation <- promotion <- learning ---+
```

## Services

- `LearningWritebackService` writes durable Evidence, Claims, Decisions, observed Outcomes and completion history.
- `MemoryPromotionService` evaluates validated Findings/Hypotheses, promotes eligible knowledge, promotes historical incidents, records evidence-backed expertise, and performs verified responsibility changes.
- `KnowledgeInvalidationService` performs bounded dependency-aware staleness propagation, claim supersession, source-authority degradation and revalidation.
- `ClosedLoopLearningService` is the orchestration entry point. It delegates to the three services rather than containing one giant policy function.

## Trust boundary

A Finding or Hypothesis is not organizational truth. Promotion requires validation, confidence, a validator, independent evidence, no unresolved blocker, and no unresolved contradiction. The source artifact remains in the graph after promotion.

## Idempotency

Evidence IDs, promotion Claim IDs and learning-event IDs are deterministic. Reprocessing the same source result reuses the same graph object/edge identity rather than multiplying organizational facts.
