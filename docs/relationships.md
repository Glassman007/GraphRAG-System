# Relationship Ontology

> Direction is part of the contract. `RELATED_TO` is intentionally absent.

## OWNS
- **Source node types:** Team|Person
- **Destination node types:** System|Project
- **Direction:** owner -> resource
- **Meaning:** Formal organizational ownership; historical edges are retained.
- **Allowed properties:** edge_id, valid_from, valid_until, source_ref_id, confidence, authoritative
- **Temporal semantics:** valid interval
- **Confidence semantics:** normally 1.0 for system-of-record; lower for imported/unverified
- **Classification:** fact

## RESPONSIBLE_FOR
- **Source node types:** Person|Team
- **Destination node types:** System|Project|Task|Action
- **Direction:** actor -> responsibility
- **Meaning:** Operational accountability distinct from ownership.
- **Allowed properties:** edge_id, valid_from, valid_until, source_ref_id, confidence
- **Temporal semantics:** valid interval
- **Confidence semantics:** 0..1
- **Classification:** fact

## EXPERT_IN
- **Source node types:** Person
- **Destination node types:** System|Change|Project
- **Direction:** person -> domain
- **Meaning:** Evidence-backed expertise/experience.
- **Allowed properties:** edge_id, valid_from, valid_until, source_ref_id, confidence
- **Temporal semantics:** valid interval
- **Confidence semantics:** 0..1 required
- **Classification:** inference/fact

## MEMBER_OF
- **Source node types:** Person
- **Destination node types:** Team
- **Direction:** person -> team
- **Meaning:** Organizational membership.
- **Allowed properties:** edge_id, valid_from, valid_until, source_ref_id, confidence
- **Temporal semantics:** valid interval
- **Confidence semantics:** normally 1.0
- **Classification:** fact

## DEPENDS_ON
- **Source node types:** System|Project|Task
- **Destination node types:** System|Project|Task
- **Direction:** consumer -> prerequisite
- **Meaning:** Runtime/work dependency; direction means source needs target.
- **Allowed properties:** edge_id, dependency_kind, criticality, valid_from, valid_until, source_ref_id, confidence
- **Temporal semantics:** valid interval; old edges retained
- **Confidence semantics:** 0..1
- **Classification:** dependency

## AFFECTS
- **Source node types:** Change|Incident|Action
- **Destination node types:** System|Project|Incident
- **Direction:** cause/intervention -> affected
- **Meaning:** Observed or inferred influence, not necessarily failure.
- **Allowed properties:** edge_id, observed, valid_from, valid_until, source_ref_id, confidence
- **Temporal semantics:** time-bounded when known
- **Confidence semantics:** 0..1 required for inference
- **Classification:** inference/fact

## CHANGED
- **Source node types:** Change
- **Destination node types:** System
- **Direction:** change -> changed resource
- **Meaning:** Concrete technical change applied to a resource.
- **Allowed properties:** edge_id, valid_from, valid_until, source_ref_id, confidence
- **Temporal semantics:** applied interval
- **Confidence semantics:** normally high
- **Classification:** historical event/fact

## SUPPORTS
- **Source node types:** Evidence
- **Destination node types:** Claim|Hypothesis|Decision
- **Direction:** evidence -> assertion
- **Meaning:** Evidence increases support for assertion.
- **Allowed properties:** edge_id, valid_from, source_ref_id, confidence
- **Temporal semantics:** from evidence availability time
- **Confidence semantics:** support strength 0..1
- **Classification:** claim/provenance

## REFUTES
- **Source node types:** Evidence
- **Destination node types:** Claim|Hypothesis
- **Direction:** evidence -> assertion
- **Meaning:** Evidence directly undermines assertion.
- **Allowed properties:** edge_id, valid_from, source_ref_id, confidence
- **Temporal semantics:** from evidence availability time
- **Confidence semantics:** refutation strength 0..1
- **Classification:** claim/provenance

## CONTRADICTS
- **Source node types:** Claim|Hypothesis
- **Destination node types:** Claim|Hypothesis
- **Direction:** assertion <-> assertion
- **Meaning:** Explicit semantic incompatibility; store one or both directions as needed.
- **Allowed properties:** edge_id, scope, valid_from, source_ref_id, confidence
- **Temporal semantics:** from detected contradiction time
- **Confidence semantics:** 0..1
- **Classification:** claim

## SUPERSEDES
- **Source node types:** Claim|Decision|Policy|WorkBranch
- **Destination node types:** same type
- **Direction:** new -> old
- **Meaning:** New version replaces current authority while preserving history.
- **Allowed properties:** edge_id, valid_from, source_ref_id, confidence
- **Temporal semantics:** supersession time
- **Confidence semantics:** normally high
- **Classification:** historical event

## DERIVED_FROM
- **Source node types:** Evidence|Claim|Decision|Document|SourceRecord|Checkpoint|WorkBranch
- **Destination node types:** DataSource|Document|Event|Claim|Evidence|WorkBranch
- **Direction:** derived object -> source
- **Meaning:** Traceable derivation/provenance.
- **Allowed properties:** edge_id, method, valid_from, source_ref_id, confidence
- **Temporal semantics:** derivation time
- **Confidence semantics:** 0..1
- **Classification:** provenance

## BASED_ON
- **Source node types:** Decision
- **Destination node types:** Claim|Evidence|Policy|Hypothesis
- **Direction:** decision -> input
- **Meaning:** Decision genealogy input.
- **Allowed properties:** edge_id, valid_from, source_ref_id, confidence
- **Temporal semantics:** decision time
- **Confidence semantics:** 0..1
- **Classification:** provenance

## GOVERNS
- **Source node types:** Policy
- **Destination node types:** System|Project|Change|Action|Team
- **Direction:** policy -> scope
- **Meaning:** Policy applies to target scope.
- **Allowed properties:** edge_id, valid_from, valid_until, authoritative, source_ref_id
- **Temporal semantics:** policy validity
- **Confidence semantics:** normally 1.0
- **Classification:** policy

## REQUIRES
- **Source node types:** Policy|Task|Handoff|Action|Question
- **Destination node types:** Action|Task|Question|Evidence|Tool|DataSource
- **Direction:** requiring object -> prerequisite
- **Meaning:** Hard prerequisite/contract requirement.
- **Allowed properties:** edge_id, required, valid_from, valid_until, source_ref_id, confidence
- **Temporal semantics:** valid while requirement active
- **Confidence semantics:** normally high
- **Classification:** policy/workflow state

## BLOCKED_BY
- **Source node types:** Task
- **Destination node types:** Task|Question|Action|Blocker
- **Direction:** task -> blocker
- **Meaning:** Task cannot progress until the prerequisite work/question/action or explicit Phase 6 Blocker clears.
- **Allowed properties:** edge_id, reason, valid_from, valid_until, confidence
- **Temporal semantics:** active interval
- **Confidence semantics:** normally high
- **Classification:** workflow state

## ASSIGNED_TO
- **Source node types:** Task|Handoff
- **Destination node types:** Agent|Person|Team
- **Direction:** work -> assignee
- **Meaning:** Planned/current work assignment.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** assignment interval
- **Confidence semantics:** normally high
- **Classification:** workflow state

## CLAIMED_BY
- **Source node types:** Task
- **Destination node types:** Agent|Person
- **Direction:** task -> claimant
- **Meaning:** Active claim/lease on a work item.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** active claim interval
- **Confidence semantics:** normally high
- **Classification:** workflow state

## ASSERTED_BY
- **Source node types:** Claim|Hypothesis
- **Destination node types:** Person|Agent
- **Direction:** assertion -> actor
- **Meaning:** Actor responsible for making the assertion; distinct from a work-item claim.
- **Allowed properties:** edge_id, valid_from, source_ref_id, confidence
- **Temporal semantics:** assertion time
- **Confidence semantics:** normally high for attribution
- **Classification:** claim/provenance

## DISCOVERED_BY
- **Source node types:** Evidence|Claim|Hypothesis|Question
- **Destination node types:** Agent|Person
- **Direction:** finding -> discoverer
- **Meaning:** Who found/created a knowledge artifact.
- **Allowed properties:** edge_id, valid_from, source_ref_id, confidence
- **Temporal semantics:** discovery time
- **Confidence semantics:** normally high
- **Classification:** provenance

## APPROVED_BY
- **Source node types:** Deployment|Decision|Action
- **Destination node types:** Person|Team
- **Direction:** subject -> approver
- **Meaning:** Recorded approval; does not itself prove policy sufficiency.
- **Allowed properties:** edge_id, valid_from, source_ref_id, confidence
- **Temporal semantics:** approval time
- **Confidence semantics:** normally 1.0
- **Classification:** workflow state/policy

## PRODUCED
- **Source node types:** Person|Agent|Team
- **Destination node types:** Change|Document|Evidence|Decision|Action
- **Direction:** producer -> artifact
- **Meaning:** Creation authorship.
- **Allowed properties:** edge_id, valid_from, source_ref_id, confidence
- **Temporal semantics:** production time
- **Confidence semantics:** normally high
- **Classification:** provenance

## RESOLVED_BY
- **Source node types:** Incident|Question|Task
- **Destination node types:** Decision|Action|Evidence|Person|Agent
- **Direction:** problem -> resolver/artifact
- **Meaning:** What resolved a problem/unknown.
- **Allowed properties:** edge_id, valid_from, source_ref_id, confidence
- **Temporal semantics:** resolution time
- **Confidence semantics:** 0..1
- **Classification:** historical event

## SIMILAR_TO
- **Source node types:** Incident|Project
- **Destination node types:** same type
- **Direction:** entity -> entity
- **Meaning:** Materialized structural/semantic similarity result; never seeded when it would leak hidden truth.
- **Allowed properties:** edge_id, method, score, valid_from
- **Temporal semantics:** computed time
- **Confidence semantics:** score required
- **Classification:** inference

## COMMITTED_TO
- **Source node types:** Commitment
- **Destination node types:** System|Project|Deployment|Action
- **Direction:** commitment -> subject
- **Meaning:** Scope/object of promise.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** commitment interval
- **Confidence semantics:** normally high
- **Classification:** workflow state

## OWED_TO
- **Source node types:** Commitment
- **Destination node types:** Team|Person
- **Direction:** commitment -> recipient
- **Meaning:** Beneficiary/recipient of obligation.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** commitment interval
- **Confidence semantics:** normally high
- **Classification:** workflow state

## PROMISED_BY
- **Source node types:** Commitment
- **Destination node types:** Team|Person
- **Direction:** commitment -> promisor
- **Meaning:** Actor accountable for obligation.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** commitment interval
- **Confidence semantics:** normally high
- **Classification:** workflow state

## TRIGGERED
- **Source node types:** Event|Action|Incident
- **Destination node types:** Event|Task|Action|Incident
- **Direction:** cause -> triggered object
- **Meaning:** Explicit trigger relation when causally supported.
- **Allowed properties:** edge_id, valid_from, source_ref_id, confidence
- **Temporal semantics:** trigger time
- **Confidence semantics:** 0..1
- **Classification:** historical event/inference

## BEFORE
- **Source node types:** Event
- **Destination node types:** Event
- **Direction:** earlier -> later
- **Meaning:** Explicit ordering when clock order alone is insufficient/important.
- **Allowed properties:** edge_id, valid_from, confidence
- **Temporal semantics:** ordering fact
- **Confidence semantics:** normally high
- **Classification:** historical event

## ABOUT
- **Source node types:** Evidence|Claim|Hypothesis|Question|Task|Action|Event|Handoff
- **Destination node types:** Entity
- **Direction:** knowledge/work artifact -> subject
- **Meaning:** Typed subject link; intentionally narrower than vague RELATED_TO.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** artifact relevance interval
- **Confidence semantics:** 0..1
- **Classification:** fact/workflow/provenance

## CONTAINS
- **Source node types:** Deployment|Document|WorkBranch
- **Destination node types:** Change|Document|Claim|Hypothesis|Finding
- **Direction:** container -> member
- **Meaning:** Structural containment/version boundary.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** container interval
- **Confidence semantics:** normally high
- **Classification:** fact/workflow

## PERFORMED_BY
- **Source node types:** Event|Action
- **Destination node types:** Person|Agent|Team
- **Direction:** event/action -> actor
- **Meaning:** Execution actor for replay/audit.
- **Allowed properties:** edge_id, valid_from, source_ref_id, confidence
- **Temporal semantics:** execution time
- **Confidence semantics:** normally 1.0
- **Classification:** historical event/provenance

## PART_OF
- **Source node types:** Task|Checkpoint|WorkBranch|Action
- **Destination node types:** Incident|Project|Task|WorkBranch|Execution
- **Direction:** child -> parent
- **Meaning:** Lifecycle/work grouping.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** membership interval
- **Confidence semantics:** normally high
- **Classification:** workflow state

## ROOT_CAUSE
- **Source node types:** Incident
- **Destination node types:** Claim
- **Direction:** incident -> validated claim
- **Meaning:** Only created after validation; never used for initial hidden fixture truth.
- **Allowed properties:** edge_id, valid_from, source_ref_id, confidence
- **Temporal semantics:** validation time
- **Confidence semantics:** high threshold
- **Classification:** inference/decision

## REPRESENTS
- **Source node types:** SourceRecord
- **Destination node types:** Entity
- **Direction:** source record -> canonical entity
- **Meaning:** Accepted identity mapping.
- **Allowed properties:** edge_id, valid_from, valid_until, source_ref_id, confidence
- **Temporal semantics:** mapping validity
- **Confidence semantics:** high threshold
- **Classification:** fact/inference

## CANDIDATE_MATCH
- **Source node types:** SourceRecord
- **Destination node types:** Entity
- **Direction:** source record -> candidate entity
- **Meaning:** Unresolved entity-resolution hypothesis.
- **Allowed properties:** edge_id, status, valid_from, source_ref_id, confidence
- **Temporal semantics:** candidate interval
- **Confidence semantics:** required 0..1
- **Classification:** inference

## QUERIES
- **Source node types:** Tool
- **Destination node types:** DataSource
- **Direction:** tool -> source
- **Meaning:** Tool can retrieve/act on source.
- **Allowed properties:** edge_id, capability, risk_level, valid_from, valid_until
- **Temporal semantics:** tool config validity
- **Confidence semantics:** normally 1.0
- **Classification:** fact

## HANDOFF_FOR
- **Source node types:** Handoff
- **Destination node types:** Task
- **Direction:** handoff -> task
- **Meaning:** Work item whose responsibility/context is transferred.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** handoff interval
- **Confidence semantics:** normally high
- **Classification:** workflow state


# Phase 5 Planning Relationships

## PLAN_HAS_TASK
- **Source node types:** Plan
- **Destination node types:** Task
- **Direction:** plan -> task
- **Meaning:** Durable plan membership. A Task may be reused by a recomputed plan through the same deterministic identity; membership is not task execution.
- **Allowed properties:** edge_id, confidence
- **Temporal semantics:** membership reflects the current persisted version of the deterministic plan; stale membership is removed on recompute and planner-generated stale tasks are marked SUPERSEDED only when no other Plan still references them.
- **Confidence semantics:** normally 1.0
- **Classification:** workflow/planning structure
- **Why needed:** task membership must be traversable in FalkorDB rather than hidden in a Plan JSON property.

## ADDRESSES
- **Source node types:** Plan|Task
- **Destination node types:** Incident|Question|Claim|Hypothesis|Policy|Action|Decision|System|Change|Deployment
- **Direction:** plan/task -> reasoning or target entity
- **Meaning:** Explicitly records which graph entity caused the plan/task to exist, which governed work item it resolves, or which canonical caller-selected constraint scopes the Plan. It is narrower than a generic RELATED_TO edge.
- **Allowed properties:** edge_id, confidence
- **Temporal semantics:** current derivation link; historical planning is represented by the Plan `as_of` cutoff and source entities' temporal model.
- **Confidence semantics:** normally 1.0 for deterministic planner derivation
- **Classification:** planning/provenance
- **Why needed:** duplicate detection, explanations and graph-necessity tests require first-class derivation links to Questions, Claims, Policies and Actions.

## CANDIDATE_FOR
- **Source node types:** Person|Team|Agent|Tool
- **Destination node types:** Task
- **Direction:** candidate actor/tool -> task
- **Meaning:** Ranked Phase 5 candidate worker derived from existing responsibility/expertise routing or Tool/DataSource routing. This is not ASSIGNED_TO and does not claim/execute work.
- **Allowed properties:** edge_id, score, requirement, roles, reason_summary, path_summary, confidence
- **Temporal semantics:** refreshed on plan generation/recompute from current or explicit `as_of` graph state; obsolete candidate edges are removed.
- **Confidence semantics:** normalized from deterministic candidate score for convenience; `score` remains the primary ranking value.
- **Classification:** derived planning/routing state
- **Why needed:** candidate rankings and their requirement semantics must remain inspectable without converting a recommendation into a real assignment.


# Phase 6 Coordination Relationships

## HAS_EXECUTION
- **Source node types:** Task
- **Destination node types:** Execution
- **Direction:** task -> execution
- **Meaning:** Durable execution state belonging to a Task.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** execution membership/history; old executions remain queryable.
- **Confidence semantics:** 1.0
- **Classification:** coordination state
- **Why needed:** restart reconstruction must discover execution from the Task graph.

## HAS_CHECKPOINT
- **Source node types:** Task|Execution
- **Destination node types:** Checkpoint
- **Direction:** task/execution -> checkpoint
- **Meaning:** Persisted resumability anchor. Execution is the authoritative resume path; Task link supports blackboard inspection.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** append-oriented checkpoint membership; archived checkpoints remain linked.
- **Confidence semantics:** 1.0
- **Classification:** execution/provenance

## HAS_BRANCH
- **Source node types:** Task
- **Destination node types:** WorkBranch
- **Direction:** task -> branch
- **Meaning:** Speculative branch associated with a Task.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** branch history is retained after merge/rejection.
- **Confidence semantics:** 1.0
- **Classification:** isolated execution memory

## PROPOSED_ACTION
- **Source node types:** Task
- **Destination node types:** Action
- **Direction:** task -> action
- **Meaning:** Action proposed as work product of the Task; does not itself authorize execution.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** proposal interval/history.
- **Confidence semantics:** 1.0
- **Classification:** governed action provenance

## HAS_ATTEMPT
- **Source node types:** Action
- **Destination node types:** ActionAttempt
- **Direction:** action -> attempt
- **Meaning:** Durable idempotency/crash-recovery record for the logical Action.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** attempts remain historical even after success/failure/unknown.
- **Confidence semantics:** 1.0
- **Classification:** action coordination

## LOCKS
- **Source node types:** Lock
- **Destination node types:** Action|System|Deployment|Change
- **Direction:** lock -> exclusive resource
- **Meaning:** Resource protected by a Phase 6 lease.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** current exclusivity is determined by Lock.status + lease_until, not merely edge existence.
- **Confidence semantics:** 1.0
- **Classification:** coordination/lease

## LOCKED_BY
- **Source node types:** Lock
- **Destination node types:** Agent
- **Direction:** lock -> agent
- **Meaning:** Worker that acquired the current/historical lock lease.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** Lock node status/lease is authoritative for current ownership; relationship preserves provenance.
- **Confidence semantics:** 1.0
- **Classification:** coordination/provenance

## VALIDATED_BY
- **Source node types:** Finding
- **Destination node types:** Agent
- **Direction:** finding -> verifier
- **Meaning:** Verifier responsible for a persisted Finding validation decision.
- **Allowed properties:** edge_id, valid_from, valid_until, confidence
- **Temporal semantics:** validation history.
- **Confidence semantics:** 1.0
- **Classification:** verification provenance

## HAS_COMPACTION
- **Source node types:** Execution
- **Destination node types:** CompactionRecord
- **Direction:** execution -> compaction record
- **Meaning:** Auditable record of which checkpoint traces were archived and which durable dependencies were retained.
- **Allowed properties:** edge_id, valid_from, confidence
- **Temporal semantics:** append-oriented compaction history.
- **Confidence semantics:** 1.0
- **Classification:** memory/provenance

## Phase 6 reuse of existing relationships

- `CLAIMED_BY`: `Task -> Agent` is now actual active ownership, with `valid_from`/`valid_until`; it is distinct from Phase 5 `CANDIDATE_FOR`.
- `PRODUCED`: `Agent -> Finding|Action` records worker output.
- `ABOUT`: `Finding|Evidence -> Task` makes shared blackboard artifacts discoverable.
- `BLOCKED_BY`: `Task -> Blocker|Task` drives execution blocking and deadlock detection.
- `HANDOFF_FOR`: `Handoff -> Task` identifies source/destination work.
- `ASSIGNED_TO`: `Handoff -> Agent` designates the receiver; task ownership still uses `CLAIMED_BY`.
- `REQUIRES`: `Handoff -> Finding|Evidence` is a contract requirement; Task prerequisites retain Phase 5 semantics.
- `DERIVED_FROM`: branch merges, handoff provenance and compaction manifests preserve lineage.
- `PART_OF`: `WorkBranch -> Execution` identifies the parent execution.

No generic `RELATED_TO` relationship is introduced.

# Phase 7 learning relationships

## PROMOTED_TO
- Source: `Finding|Hypothesis`
- Target: `Claim`
- Direction: temporary/validated work -> promoted organizational Claim
- Meaning: explicit promotion lineage; source artifact remains queryable.

## HAS_OUTCOME
- Source: `Action`
- Target: `Outcome`
- Meaning: observed organizational result, distinct from ActionAttempt/executor success.

## CANDIDATE_EXPERT
- Source: `Person|Agent`
- Target: domain `System|Project`
- Meaning: evidence-backed expertise candidate. This is deliberately weaker than canonical `EXPERT_IN`.
- Provenance: relationship `source_ref_id` points to `ExpertiseEvidence`.

Existing `DERIVED_FROM`, `SUPPORTS`, `VALIDATED_BY`, `BASED_ON`, `ROOT_CAUSE`, `OWNS`, `RESPONSIBLE_FOR`, `PLAN_HAS_TASK`, `ADDRESSES`, `GOVERNS` remain the load-bearing Phase 7 traversal semantics.

# Phase 8 relationship additions and analytic interpretation

| Relationship | Source -> Target | Meaning |
|---|---|---|
| `CAUSE` | validated causal artifact/entity -> affected artifact/entity | Explicit causal assertion backed by validation/evidence. Never inferred from `BEFORE` alone. |
| `SATISFIED_BY` | Commitment -> Evidence/Event/Outcome | Evidence that the obligation was fulfilled. |
| `BREACHED_BY` | Commitment -> Evidence/Event/Outcome | Evidence that the obligation was violated. |
| `MADE_BY` | Commitment -> Person/Team | Optional promisor synonym; existing `PROMISED_BY` remains canonical for Northstar fixtures. |
| `COLLABORATES_WITH` | Project/Team/Person -> Project/Team/Person | Explicit intentional collaboration, used to avoid misclassifying overlap as waste. |

Phase 8 also gives existing relationships stricter analytic roles:

- `BEFORE` = temporal ordering only.
- `TRIGGERED` = explicit workflow initiation.
- `REQUIRES`, `BLOCKED_BY`, `DEPENDS_ON` = dependency/prerequisite semantics.
- `GOVERNS`, `REQUIRES`, `APPROVED_BY` = expected-process/policy controls.
- `PROMISED_BY`, `OWED_TO`, `COMMITTED_TO` = commitment identity and scope.
- `OWNS`, `RESPONSIBLE_FOR`, `EXPERT_IN`, `APPROVED_BY` = coverage dimensions for bus-factor analysis.

# Phase 9 ingestion relationships

## INGESTED
- **Source -> destination:** `IngestionRun -> SourceRecord`
- **Meaning:** this run fetched and safely recorded this immutable external source version.
- **Temporal/provenance:** append-oriented; `valid_from` is ingestion time.

## NORMALIZED_TO
- **Source -> destination:** `SourceRecord -> canonical Entity|Claim|Evidence|Task|Project|System|Policy|Event|Document|Change`
- **Meaning:** deterministic normalization/writeback lineage from exact external record to graph meaning.
- **Important properties:** mapping rule/version, fact source/target/relation where relationship meaning is represented.

## RESOLVES_TO
- **Source -> destination:** `ExternalIdentity -> Person|Team|System|Project`
- **Meaning:** reviewed/high-confidence canonical identity resolution. Removing it must make source identity provenance unable to reconstruct the canonical entity.

## REFERENCES
- **Source -> destination:** `SourceRecord -> ExternalIdentity|Artifact|SourceRecord` and other explicit lightweight source references where documented.
- **Meaning:** source record references a source identity/artifact without asserting canonical truth.

## Phase 9 reuse of existing relationships
- `DERIVED_FROM`: SourceRecord/Artifact/Evidence/DataSource provenance.
- `SUPERSEDES`: newer immutable SourceRecord version -> previous version.
- `SUPPORTS` / `REFUTES`: imported Evidence -> Claim; source evidence never becomes truth by itself.
- `CONTRADICTS`: conflicting structural source Claims asserting the same predicate/target with different actors.
- `OWNS`, `RESPONSIBLE_FOR`, `DEPENDS_ON`: written only through configured trust rules; relationship properties retain source record/run/mapping provenance.
- `VALIDATED_BY`: authoritative DataSource may validate source Evidence when the source registry explicitly permits that domain.

No generic provider-specific canonical relationship types are introduced.

## Phase 10 retrieval relationships

- `Chunk -[:PART_OF]-> Artifact`
- `RetrievalExecution -[:REQUESTED_BY]-> Agent`
- `RetrievalExecution -[:FOR_TASK]-> Task`
- `RetrievalExecution -[:USED_SOURCE]-> DataSource`
- `RetrievalExecution -[:RETURNED]-> Evidence`
- `Agent -[:PRODUCED {production_mode: "retrieval"}]-> Evidence`
- `Investigation/Question -[:HAS_RETRIEVAL]-> RetrievalExecution`
- `Evidence -[:DERIVED_FROM]-> Chunk/Artifact/SourceRecord`
- existing `DOCUMENTED_BY` / `HAS_ARTIFACT` may scope direct document retrieval.


## Phase 11 external-resource relationships

Phase 11 reuses existing relationships for most resources. The external Investigation resource uses graph-native lineage such as:

```text
Investigation -[:ABOUT]-> Incident/Situation
Investigation -[:HAS_RETRIEVAL]-> RetrievalExecution
RetrievalExecution -[:RETURNED]-> Evidence
Evidence -[:ABOUT]-> Investigation|Task|canonical entity
Evidence -[:DERIVED_FROM]-> Chunk|Artifact|SourceRecord|DataSource
```

These relationships make retrieval provenance externally explainable without copying service results into a second store.
