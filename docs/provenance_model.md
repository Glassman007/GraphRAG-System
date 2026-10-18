# Provenance Model

## Rule

Every important assertion must be traceable without parsing an opaque JSON blob. Phase 2 uses two complementary mechanisms:

1. **Node-level provenance edges** for knowledge artifacts: `Evidence/Claim/Document/SourceRecord -[:DERIVED_FROM]-> DataSource|Document|Event`.
2. **Relationship provenance properties** for direct structural facts such as `OWNS` and `DEPENDS_ON`: `source_ref_id`, `confidence`, `valid_from`, `valid_until`, `authoritative`. `source_ref_id` is a canonical Entity ID and can be resolved back to a `DataSource`/`Document` node.

This keeps high-frequency graph traversals direct while retaining traceability. If later audit requirements need evidence to attach to individual edge assertions as first-class nodes, introduce a narrowly scoped reified assertion model then; do not duplicate every edge pre-emptively.

## Required provenance fields

- **source system:** `DataSource` node and/or `source_ref_id`.
- **source document:** `Document` node connected by `DERIVED_FROM` where applicable.
- **creator:** `PRODUCED`, `ASSERTED_BY`, `DISCOVERED_BY`, or `PERFORMED_BY`.
- **human vs agent assertion:** `Claim.assertion_kind` plus `ASSERTED_BY` actor label (`Person` or `Agent`).
- **timestamp:** `created_at`, `observed_at`, `occurred_at`, plus temporal edge fields.
- **confidence:** explicit numeric `0..1` on uncertain Claims/Evidence/edges.
- **supporting evidence:** `Evidence -[:SUPPORTS|REFUTES]-> Claim/Hypothesis/Decision`.
- **extraction method:** `DERIVED_FROM.method` or source record metadata when ingestion arrives.
- **ingestion run:** represented later as an `Event`/Document-linked ingestion event; Phase 2 synthetic seeds are deterministic and do not pretend to be ingested production data.
- **authoritative source:** `DataSource.authoritative` + `authority_scope`; authority is contextual, not global.

## What is deliberately not done

- Raw logs and large documents are not copied wholesale into graph properties.
- A Claim is not converted to a Fact merely because it has high confidence.
- Conflicting claims are not overwritten.
- `source_ref_id` never contains an unstructured JSON provenance object.


## Phase 5 plan/task derivation provenance

Phase 5 planning adds durable **derived work**, not new organizational truth.

- `Plan -[:ADDRESSES]-> Situation|Incident` records what the plan is for.
- `Plan -[:PLAN_HAS_TASK]-> Task` records membership.
- `Task -[:ADDRESSES]-> Question|Claim|Policy|Action|...` records the graph facts that caused the task to exist.
- `Task -[:ABOUT]-> Incident|System|Change|...` records the work target/context.
- `Task -[:REQUIRES]-> Task|Tool|DataSource` records explicit prerequisites and source/tool requirements.
- `Person|Team|Agent|Tool -[:CANDIDATE_FOR]-> Task` records a ranked recommendation with score, role/reason summaries and graph-path explanation. It is deliberately **not** an assignment.
- deterministic `PLAN_CREATED` and `TASK_CREATED` Events are linked with `ABOUT` and `PERFORMED_BY` so later replay can distinguish planner creation from future execution.

`Plan.provenance`, `Task.provenance`, `Task.derivation_reason`, and `planner_version` are descriptive audit metadata. Traversal-critical derivation is still represented by graph edges; callers must not rely on the prose fields as a substitute for those relationships.

Phase 5 does not store private model chain-of-thought. The planner is deterministic and stores only structured graph inputs, outputs, reason codes/path summaries, and creation events.

## Phase 7 learning provenance

Phase 7 promoted knowledge must retain explicit lineage:

- `Finding|Hypothesis -[:PROMOTED_TO]-> Claim`;
- promoted `Claim -[:DERIVED_FROM]-> Finding|Hypothesis`;
- `Evidence -[:SUPPORTS]-> Claim`;
- `Claim -[:VALIDATED_BY]-> validator`;
- Agent/Task/Execution `-[:PRODUCED]-> Evidence` for learned evidence;
- Action `-[:HAS_OUTCOME]-> Outcome` for observed organizational effects;
- `ExpertiseEvidence -[:DERIVED_FROM]-> Task|Finding` and `-[:VALIDATED_BY]-> verifier`;
- promoted `OWNS` / `RESPONSIBLE_FOR` relationships carry `source_ref_id`, validity interval and authoritative/confidence metadata.

Promotion/invalidation events are deterministic and linked with `ABOUT`, allowing future queries to explain why an object was promoted, superseded, invalidated or revalidated without storing model chain-of-thought.

# Phase 9 external-source provenance

Every external mutation is traceable through the chain:

`DataSource <-DERIVED_FROM- IngestionRun -INGESTED-> SourceRecord -NORMALIZED_TO-> canonical graph fact`

External identity lineage additionally uses:

`SourceRecord -REFERENCES-> ExternalIdentity -RESOLVES_TO-> canonical Entity`.

Large artifacts use:

`SourceRecord -REFERENCES-> Artifact` and, where semantically applicable, `Evidence -DERIVED_FROM-> Artifact`.

Relationships created from ingestion retain `source_ref_id`, `source_record_id`, `source_record_ids_csv`, `ingestion_run_id`, `observed_at`, `valid_from`, `confidence`, `authority`, `mapping_rule`, and `mapping_version`. Multiple sources supporting the same canonical structural edge are accumulated in provenance rather than creating duplicate active edges.

A SourceRecord change is versioned by checksum and linked with `SUPERSEDES`; source deletion creates tombstone Evidence and never hard-deletes canonical organizational entities.

## Phase 10 retrieval provenance

Retrieval provenance extends Phase 9 source provenance rather than replacing it. Each result retains retrieval method/rank, query, canonical source IDs, graph scope, content hash/model/index version and observation/retrieval times. When selected, the Evidence lineage is materialized through `RetrievalExecution`, `DERIVED_FROM`, `USED_SOURCE`, `FOR_TASK`, `HAS_RETRIEVAL`, and `ABOUT` relationships.
