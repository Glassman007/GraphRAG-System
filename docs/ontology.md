# Minimum Ontology

## Design decisions

- Every domain node also has the `Entity` label. Canonical identity is tenant-scoped by `(tenant_id, id)`.
- `System` absorbs service/database/pipeline/worker variants through `system_type`; a separate `Service` label would duplicate identity semantics.
- `Change` is added because the canonical scenario makes `MIG-203` causally central.
- `SourceRecord` is added so entity-resolution candidates are not silently merged into canonical entities.
- `WorkBranch`, `Checkpoint`, and `Handoff` are reused by Phase 6 for branch isolation, resumability/compaction, and contract validation.
- Phase 6 adds `Execution`, `Finding`, `Blocker`, `Lock`, `ActionAttempt`, and `CompactionRecord` because those states cannot be reconstructed safely from Task properties or one giant JSON blackboard.
- Raw logs/documents are not forced into FalkorDB. The graph stores identity, references, provenance, state, and relationships.

## Node types

### Person
- **Purpose:** Human actor with role, responsibility, expertise or authority.
- **Required properties:** id, tenant_id, name
- **Optional properties:** role, status, source_ref_id
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, valid_from, valid_until
- **Provenance requirements:** source_ref_id or source relationship for imported identity
- **Indexes/constraints:** Entity(tenant_id,id) unique; Entity.id index
- **Features depending on it:** T1.2, T2.2, T3.2, T3.3, T3.6, T3.8

### Team
- **Purpose:** Organizational ownership/authority unit.
- **Required properties:** id, tenant_id, name
- **Optional properties:** status, source_ref_id
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, valid_from, valid_until
- **Provenance requirements:** source_ref_id for imported org record
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T3.2, T3.3, T3.6-T3.10

### System
- **Purpose:** Canonical technical resource; replaces a separate Service type to avoid duplicate identity classes.
- **Required properties:** id, tenant_id, name
- **Optional properties:** system_type, status, criticality
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, valid_from, valid_until
- **Provenance requirements:** dependency/ownership edges carry source_ref_id
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T1.1, T1.3, T1.6-T1.8, T3.3, T3.6, T3.10

### Project
- **Purpose:** Organizational initiative/work program.
- **Required properties:** id, tenant_id, name
- **Optional properties:** goal, status
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, valid_from, valid_until
- **Provenance requirements:** source_ref_id when ingested
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T3.7, T3.8

### Incident
- **Purpose:** Bounded operational situation with lifecycle and evidence.
- **Required properties:** id, tenant_id, title, status
- **Optional properties:** severity, started_at, resolved_at
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, started_at, resolved_at
- **Provenance requirements:** Evidence/DataSource and event links
- **Indexes/constraints:** Entity identity; useful status index later
- **Features depending on it:** T1.1-T1.7, T2.1, T3.1-T3.5

### Deployment
- **Purpose:** Concrete rollout/change execution.
- **Required properties:** id, tenant_id, name, status
- **Optional properties:** deployed_at, source_ref_id
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, deployed_at
- **Provenance requirements:** DERIVED_FROM/source_ref_id to deployment system
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T1.1-T1.3, T3.4-T3.5

### Change
- **Purpose:** Explicit schema/code/config migration. Added because MIG-203 is causal and cannot safely live as free text on Deployment.
- **Required properties:** id, tenant_id, name, change_type, status
- **Optional properties:** applied_at, source_ref_id
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, applied_at, valid_from, valid_until
- **Provenance requirements:** source_ref_id/DERIVED_FROM authoritative source
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T1.1, T1.3, T1.5-T1.7, T3.5

### Document
- **Purpose:** Reference to a raw artifact stored externally or lightweight document metadata.
- **Required properties:** id, tenant_id, name
- **Optional properties:** uri, checksum, document_type, source_ref_id
- **Immutable fields:** tenant_id + id; checksum if immutable artifact
- **Temporal fields:** created_at, observed_at, valid_from, valid_until
- **Provenance requirements:** DERIVED_FROM DataSource + checksum
- **Indexes/constraints:** Entity identity; checksum index later
- **Features depending on it:** T1.2, T1.10, T3.1-T3.5

### DataSource
- **Purpose:** Named authoritative/non-authoritative source system.
- **Required properties:** id, tenant_id, name, source_type
- **Optional properties:** authority_scope, authoritative
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, valid_from, valid_until
- **Provenance requirements:** Self-describing; ingestion run later via Event/Document
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T1.10, T3.1-T3.2

### SourceRecord
- **Purpose:** Source-specific identity record kept separate from canonical entity until resolved.
- **Required properties:** id, tenant_id, source_entity_id, source_kind
- **Optional properties:** name, normalized fields, status
- **Immutable fields:** tenant_id + id; source_kind+source_entity_id semantically immutable
- **Temporal fields:** created_at, observed_at, valid_from, valid_until
- **Provenance requirements:** DERIVED_FROM DataSource; candidate/accepted mapping edges
- **Indexes/constraints:** source_entity_id index
- **Features depending on it:** T1.9

### Evidence
- **Purpose:** Observed artifact/measurement used to support/refute a claim.
- **Required properties:** id, tenant_id, name, evidence_type
- **Optional properties:** confidence, source_ref_id
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, observed_at, valid_from, valid_until
- **Provenance requirements:** DERIVED_FROM DataSource/Document; DISCOVERED_BY actor/agent
- **Indexes/constraints:** observed_at index
- **Features depending on it:** T1.1-T1.5, T1.10, T2.1, T3.1-T3.5

### Claim
- **Purpose:** Asserted proposition; never silently promoted to fact.
- **Required properties:** id, tenant_id, statement, status, confidence
- **Optional properties:** assertion_kind, source_ref_id
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, valid_from, valid_until
- **Provenance requirements:** ASSERTED_BY actor + SUPPORTS/REFUTES evidence + DERIVED_FROM source
- **Indexes/constraints:** status index
- **Features depending on it:** T1.1-T1.5, T2.1, T2.4, T3.1-T3.2

### Hypothesis
- **Purpose:** Explicit speculative explanation kept distinct from claims/facts.
- **Required properties:** id, tenant_id, statement, status, confidence
- **Optional properties:** branch_id
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, valid_from, valid_until
- **Provenance requirements:** DISCOVERED_BY/DERIVED_FROM and branch membership
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T1.1, T2.4

### Question
- **Purpose:** First-class knowledge gap that can block work.
- **Required properties:** id, tenant_id, text, status
- **Optional properties:** priority
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, resolved_at
- **Provenance requirements:** ABOUT subject; REQUIRES Tool/DataSource when an explicit acquisition route is known; RESOLVED_BY evidence/decision later
- **Indexes/constraints:** Entity identity; status index later
- **Features depending on it:** T1.4, T1.10, T2.1, T2.6

### Decision
- **Purpose:** Selected course/conclusion with reconstructable basis.
- **Required properties:** id, tenant_id, statement, status
- **Optional properties:** decision_type, rationale_summary
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, valid_from, valid_until
- **Provenance requirements:** BASED_ON evidence/claims/policy; APPROVED_BY; Event ledger
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T1.2, T3.2, T3.4

### Plan
- **Purpose:** Durable Phase 5 container for graph-backed work derived from a Situation/Incident and existing reasoning state.
- **Required properties:** id, tenant_id, situation_id, goal, status, created_at, generated_by, planner_version
- **Optional properties:** created_by, provenance, strategy_summary, as_of, selection_fingerprint, selected_hypotheses_csv, selected_claims_csv, selected_knowledge_gaps_csv, constraint_refs_csv
- **Immutable fields:** tenant_id + id; deterministic identity is derived from tenant + situation + normalized goal + historical cutoff + explicit planning-selection fingerprint
- **Temporal fields:** created_at; `as_of` is an optional historical planning cutoff and is not compared as a raw string
- **Provenance requirements:** ADDRESSES Situation/Incident; PLAN_HAS_TASK Task; PLAN_CREATED Event
- **Indexes/constraints:** global Entity(tenant_id,id) identity constraint is sufficient for Phase 5
- **Features depending on it:** Phase 5 Tasks 27-29; later Track 2 execution will consume but not redefine it

### Task
- **Purpose:** Durable typed work item generated/reused by a Plan; Phase 5 computes work and readiness but does not execute it.
- **Required properties:** id, tenant_id, name, status
- **Optional properties:** title, objective, task_type, priority, expected_output_type, completion_condition, semantic_key, semantic_signature, situation_id, assignee_requirement, planner_version, derivation_reason, provenance, result_summary
- **Immutable fields:** tenant_id + id; planner-generated semantic identity is deterministic
- **Temporal fields:** created_at, started_at, completed_at
- **Provenance requirements:** PLAN_HAS_TASK; ADDRESSES; ABOUT; REQUIRES/BLOCKED_BY; CANDIDATE_FOR; Events. Actual ASSIGNED_TO remains a later coordination decision.
- **Indexes/constraints:** status index
- **Features depending on it:** T1.4, T1.6, Phase 5 Tasks 27-29, T2.1-T2.6, T2.8

### Agent
- **Purpose:** Persisted identity/capability record for one of the four bounded Phase 6 worker types.
- **Required properties:** id, tenant_id, name, agent_type
- **Optional properties:** status, availability, capabilities, supported_task_types, permissions, supported_tools, evidence_types, actions_may_propose, actions_may_execute, last_checkpoint, registry_version
- **Immutable fields:** tenant_id + id, agent_type for the built-in registry identity
- **Temporal fields:** created_at, valid_from, valid_until
- **Provenance requirements:** CLAIMED_BY Tasks, PRODUCED findings/actions, PERFORMED_BY Events, checkpoint ownership
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T2.1-T2.7

### Action
- **Purpose:** Proposed or sandbox-executed side effect/verification operation governed by organizational graph state.
- **Required properties:** id, tenant_id, name, action_type, status
- **Optional properties:** idempotency_key, risk_level, approval_required, proposed_at, executed_at
- **Immutable fields:** tenant_id + id; idempotency_key immutable once execution starts
- **Temporal fields:** created_at, proposed_at, executed_at
- **Provenance requirements:** Task PROPOSED_ACTION; ABOUT target; APPROVED_BY; HAS_ATTEMPT; Event ledger; policy links
- **Indexes/constraints:** idempotency_key index
- **Features depending on it:** T1.6-T1.7, T2.2, T2.7, T3.4-T3.5

### Policy
- **Purpose:** Authoritative rule defining constraints/required process.
- **Required properties:** id, tenant_id, name, status, version
- **Optional properties:** scope, authoritative
- **Immutable fields:** tenant_id + id; version immutable
- **Temporal fields:** created_at, valid_from, valid_until
- **Provenance requirements:** source document/system + approval provenance
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T1.6-T1.7, T2.2, T3.2, T3.5

### Commitment
- **Purpose:** Explicit promise/obligation between organizational actors.
- **Required properties:** id, tenant_id, statement, status
- **Optional properties:** name, due_at
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, due_at, fulfilled_at, violated_at
- **Provenance requirements:** PROMISED_BY/OWED_TO/COMMITTED_TO + outcome evidence/event
- **Indexes/constraints:** due_at index
- **Features depending on it:** T3.9

### Event
- **Purpose:** Append-oriented ledger fact about work/state transition.
- **Required properties:** id, tenant_id, event_type, occurred_at
- **Optional properties:** summary, source_ref_id
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, occurred_at
- **Provenance requirements:** ABOUT targets; PERFORMED_BY; DERIVED_FROM source where imported
- **Indexes/constraints:** occurred_at index
- **Features depending on it:** T1.2, T2.1-T2.3, T2.7-T2.8, T3.4-T3.5, T3.9

### Tool
- **Purpose:** Callable retrieval/action capability metadata; no MCP/orchestration yet.
- **Required properties:** id, tenant_id, name
- **Optional properties:** tool_type, risk_level, capability
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, valid_from, valid_until
- **Provenance requirements:** QUERIES DataSource; source/config provenance
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T1.10, T2.2

### WorkBranch
- **Purpose:** Isolation boundary for speculative agent memory; branch-local Findings do not become canonical shared findings until validated merge.
- **Required properties:** id, tenant_id, name, status
- **Optional properties:** purpose, branch_kind, parent_execution, task_id, created_by, rejection_reason
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, validated_at, merged_at, closed_at
- **Provenance requirements:** Task HAS_BRANCH; PART_OF Execution; CONTAINS branch-local Finding; merge creates DERIVED_FROM links
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T2.4

### Checkpoint
- **Purpose:** Structured durable resumability/compaction anchor; never a private chain-of-thought trace.
- **Required properties:** id, tenant_id, name, execution_id, task_id, agent_id, step_index, status
- **Optional properties:** current_step, completed_steps, pending_steps, state_summary, attempt, last_error, compaction_id
- **Immutable fields:** tenant_id + id for an execution/step/attempt checkpoint identity
- **Temporal fields:** created_at, archived_at
- **Provenance requirements:** Execution HAS_CHECKPOINT; Task HAS_CHECKPOINT; checkpoint agent identity
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T2.3, T2.8

### Handoff
- **Purpose:** Explicit validated transfer contract between bounded workers.
- **Required properties:** id, tenant_id, name, status, contract_type, contract_version, source_task_id, from_agent_id, to_agent_id
- **Optional properties:** destination_task_id, required_artifacts, confidence_threshold, contradictory_evidence_disclosed, rejection_reason
- **Immutable fields:** tenant_id + id; source/receiver contract identity
- **Temporal fields:** created_at, completed_at
- **Provenance requirements:** HANDOFF_FOR Task; ASSIGNED_TO receiver; REQUIRES/DERIVED_FROM Finding|Evidence
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T2.6

### Execution
- **Purpose:** Durable resumable execution state for a Task.
- **Required properties:** id, tenant_id, task_id, status, attempt, owner_agent_id
- **Optional properties:** current_step_index, current_step, last_checkpoint_at, last_error, started_at, resumed_at
- **Immutable fields:** tenant_id + id; task_id
- **Temporal fields:** created_at, started_at, resumed_at
- **Provenance requirements:** Task HAS_EXECUTION; HAS_CHECKPOINT; Branch PART_OF Execution; Events
- **Indexes/constraints:** status index plus Entity identity
- **Features depending on it:** T2.1, T2.3, T2.4, T2.8

### Finding
- **Purpose:** Structured worker result shared across agents or isolated inside a WorkBranch.
- **Required properties:** id, tenant_id, statement, status, confidence, scope, task_id, created_by
- **Optional properties:** finding_kind, branch_id, verified_by, validation_rationale, merged_from_branch
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, verified_at
- **Provenance requirements:** Agent PRODUCED; ABOUT Task/Claim; DERIVED_FROM Evidence/branch source; optional VALIDATED_BY verifier
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T2.1, T2.4, T2.6, T2.8

### Blocker
- **Purpose:** Explicit unresolved reason a Task/Execution cannot progress.
- **Required properties:** id, tenant_id, reason, severity, status, task_id
- **Optional properties:** created_by, resolution, resolved_by
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at, resolved_at
- **Provenance requirements:** Task BLOCKED_BY Blocker; Blocker DISCOVERED_BY Agent
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T2.1, T2.3, T2.5, T2.6

### Lock
- **Purpose:** Lease-bearing coordination record for exclusive graph resources.
- **Required properties:** id, tenant_id, status, resource_id
- **Optional properties:** action_id, owner_agent_id, heartbeat_at, lease_until, lease_until_us, acquired_at, released_at
- **Immutable fields:** tenant_id + id; Phase 6 resource locks use deterministic identity derived from resource
- **Temporal fields:** created_at, acquired_at, heartbeat_at, lease_until, released_at
- **Provenance requirements:** LOCKS resource; LOCKED_BY Agent; Events
- **Indexes/constraints:** lease_until index plus Entity identity
- **Features depending on it:** T2.5, T2.7

### ActionAttempt
- **Purpose:** Durable idempotency/crash-recovery state for one logical Action side-effect attempt.
- **Required properties:** id, tenant_id, action_id, idempotency_key, task_id, agent_id, execution_state
- **Optional properties:** started_at, finished_at, lease_until, lease_until_us, result_reference, external_request_id, external_started, error, lock_id, lock_ids
- **Immutable fields:** tenant_id + id; id derived from idempotency key
- **Temporal fields:** created_at, started_at, finished_at, lease_until
- **Provenance requirements:** Action HAS_ATTEMPT; PERFORMED_BY Agent; resource locks/events
- **Indexes/constraints:** idempotency_key index plus Entity identity
- **Features depending on it:** T2.7, T2.8

### CompactionRecord
- **Purpose:** Auditable manifest of archived low-value Checkpoints and retained durable dependencies.
- **Required properties:** id, tenant_id, execution_id, task_id, status, dependency_manifest
- **Optional properties:** summary, retained_entities, archived_entities
- **Immutable fields:** tenant_id + id
- **Temporal fields:** created_at
- **Provenance requirements:** Execution HAS_COMPACTION; ABOUT Execution; DERIVED_FROM archived/retained entities
- **Indexes/constraints:** Entity identity indexes
- **Features depending on it:** T2.8

# Phase 7 ontology additions

## Outcome
Observed organizational effect of a governed Action. This is distinct from ActionAttempt transport/execution status. Important fields: `observed_effect`, `expected_effect`, `result`, `observed_at`, `status`.

## ExpertiseEvidence
Evidence that a Person/Agent may possess domain expertise based on completed work plus verifier validation. It does not itself grant `EXPERT_IN`. Important fields: `actor_id`, `domain_id`, `task_id`, `finding_id`, `verifier_id`, `confidence`, `created_at`.

Phase 7 reuses existing Claim, Hypothesis, Finding, Decision, Action, Incident, Task, Plan, Evidence, Event, Person, Team, System and Policy labels rather than duplicating organizational memory.

# Phase 8 analytics semantics

Phase 8 intentionally adds no parallel analytics database. Existing `Event`, `Policy`, `Commitment`, `Project`, `Person`, `Team`, `System`, `Task`, `Decision`, `Action`, `Outcome`, Claim/Evidence and temporal relationship objects remain canonical in FalkorDB.

New relationship vocabulary is minimal and explicit:

- `CAUSE`: explicit validated causal relationship. `BEFORE` must never be converted into `CAUSE` merely because of chronology.
- `MADE_BY`: optional alias for a commitment promisor when a future source uses that wording; canonical Northstar fixtures continue to use `PROMISED_BY`.
- `SATISFIED_BY`: Commitment -> Evidence/Event/Outcome proving fulfillment.
- `BREACHED_BY`: Commitment -> Evidence/Event/Outcome proving breach.
- `COLLABORATES_WITH`: explicit Project/Team/Person collaboration used to distinguish intentional overlap from duplicate-work collision.

Analytics outputs (centrality, bus-factor risk, collision scores, drift findings) are derived results and are not automatically promoted into canonical organizational truth.

# Phase 9 ingestion ontology additions

Phase 9 does not create source-specific canonical people, teams, projects or systems. Provider identities remain separate from canonical organizational entities.

## DataSource
Configured external organizational source. Phase 9 adds/uses `source_type`, `source_instance`, `trust_class`, `authoritative_domains`, `enabled`, `sync_mode`, `last_successful_cursor`, `last_sync_at`, `adapter_version`, `mapping_version`, and sanitized configuration metadata. Credentials are never persisted.

## SourceRecord
Immutable/versioned record of what one external source reported. Important fields include `source_id`, `source_type`, `source_instance`, `external_id`, `source_key`, `record_type`, `observed_at`, `fetched_at`, `source_updated_at`, `version`, `etag`, `checksum`, `deleted`, `adapter_version`, `mapping_version`, and trust metadata. A changed checksum creates a new SourceRecord linked with `SUPERSEDES`; history is not overwritten.

## ExternalIdentity
Durable source-system identity such as GitHub username, Jira account, or Slack user ID. It stores source identity metadata and connects to one canonical organizational entity through `RESOLVES_TO` only after entity resolution succeeds.

## IngestionRun
Auditable source synchronization run with status, start/completion time, input/output cursor, fetched/normalized/written/quarantined/failed/artifact counts, and adapter version.

## Artifact
Lightweight graph reference to bytes stored outside FalkorDB. Fields: `id`, `uri`, `sha256`, `size_bytes`, `mime_type`, `artifact_type`, `source_type`, `source_record_id`, `created_at`. Binary content is not stored on the node.

## IngestionQuarantineRecord
Reviewable unresolved normalized mutation/identity record. It records source record, proposed entity, candidate entities/scores, reason, status, and eventual manual resolution. Ambiguity is retained rather than silently dropped or auto-merged.

## Phase 10 retrieval nodes

- `Chunk`: lightweight chunk metadata; body remains in retrieval/artifact storage.
- `RetrievalExecution`: one deterministic graph-scoped retrieval execution.
- Retrieval-produced `Evidence` remains `UNVERIFIED` until existing verification/promotion rules act on it.


### Investigation (Phase 11 external resource)

`Investigation` is the durable external resource that scopes a question/goal to an existing Situation/Incident and exposes structured Findings, Evidence, graph-first RetrievalExecutions, and status without exposing model chain-of-thought. It does not replace Incident or Phase 4 reasoning artifacts.
