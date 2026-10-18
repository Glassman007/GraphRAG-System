# Requirements Audit — Phase 1 + Phase 2

## Requirements preserved

- One architecture targets all three tracks; no separate product/agent per track.
- FalkorDB remains the canonical structured state layer and is required for graph-native behavior.
- Canonical Northstar Commerce scenario is preserved rather than replaced.
- All 28 capabilities receive objective acceptance contracts.
- Claims, hypotheses, evidence, decisions and facts remain distinct.
- Contradictions and temporal history are preserved.
- No autonomous agents, LangGraph, vector store, Slack/Jira/GitHub ingestion or frontend are introduced in Phase 2.

## Corrections to the initial candidate ontology

1. **Add `Change`:** `MIG-203` is the causal object in the canonical scenario. Hiding it inside Deployment text would break causal traversal and provenance.
2. **Do not keep both `System` and `Service`:** use `System.system_type` for service/database/pipeline/worker variants to avoid duplicate canonical identities.
3. **Add `SourceRecord`:** relational entity resolution needs unresolved source-specific identities before canonical merge.
4. **Add `WorkBranch`, `Checkpoint`, `Handoff`:** these are minimal future primitives required by Track 2's branch isolation, resumability/compaction and handoff validation.
5. **Add narrowly defined `ABOUT`, `CONTAINS`, `PERFORMED_BY`, `REPRESENTS`, `CANDIDATE_MATCH`, `PROMISED_BY`, `HANDOFF_FOR`:** the candidate relationship list otherwise cannot express core scenario/track semantics without overloading vague edges.

## Important constraint/assumption notes

- A graph schema/index does **not** mean a capability is implemented. Status is reported separately as `FOUNDATION EXISTS` vs `CAPABILITY NOT YET IMPLEMENTED`.
- `Action.idempotency_key` is indexed now, but exactly-once coordination still needs a later concurrency/lease/transaction strategy; an index alone is insufficient.
- Phase 2 provenance keeps direct structural edges fast and traceable via `source_ref_id`; high-assurance reified edge assertions can be added later only if audit needs justify their cost.
- Counterfactual simulation should operate on an isolated projection/branch; never mutate canonical history merely to ask “what if?”.
- Current synthetic fixture ground truth is deliberately stored in JSON test metadata and not seeded as `ROOT_CAUSE`/`SIMILAR_TO`, preventing hidden answer leakage.
- AI coding assistance is allowed by the supplied rules but must be disclosed in the final submission, and the participant remains responsible for correctness and understanding.

## Environment limitation during generation

The generation sandbox cannot reach the user's Windows `localhost:6379`; connection attempt returned `ConnectionRefusedError`. Therefore the repository is created and locally statically/unit tested here, while database integration/seed commands are provided for the already-running `falkordb-dev` container on the user's machine.
