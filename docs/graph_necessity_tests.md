# FalkorDB Necessity Tests — Through Phase 5

These tests are designed to prove FalkorDB is load-bearing. Phase 4–5 services read canonical nodes/relationships from FalkorDB and then run deterministic bounded algorithms over that graph state. There is no production fallback to fixture JSON, vector search, or document-only similarity.

## Phase 3 — still required

- [x] Conflict memory requires `Claim -[:CONTRADICTS]- Claim`, evidence links, provenance links, and actor attribution.
- [x] Authority resolution loses authority/evidence factors when `RESPONSIBLE_FOR`, `OWNS`, `EXPERT_IN`, `APPROVED_BY`, `GOVERNS`, `SUPPORTS/REFUTES`, or `DERIVED_FROM` paths are removed.
- [x] Responsibility/expertise routing removes a role when its typed graph edge is removed; team membership alone is not silently substituted.
- [x] Ownership-gap detection requires temporal `OWNS` plus dependency structure to distinguish currently orphaned, historically owned, ambiguous, and risky resources.

## Phase 4 — implemented graph-necessity contracts

### T1.9 Relational Entity Resolution
Required traversal:

```text
SourceRecord -[:REPRESENTS|CANDIDATE_MATCH]-> canonical Entity
canonical Entity <-[:MEMBER_OF|RESPONSIBLE_FOR|EXPERT_IN]- organizational context
```

The integration test deletes `SRCREC-CRM-42 -[:CANDIDATE_MATCH]-> PERSON-RIYA`. The candidate may still be proposed from a weak name signal, but its graph evidence disappears and its confidence drops below the seeded 0.72 reviewable match. This is the intended degradation: graph-backed resolution becomes weaker rather than silently merging on a string.

### T1.1 Relational Investigation
Required traversal:

```text
INC-001 <-[:ABOUT]- Evidence -[:ABOUT]-> System
System -[:DEPENDS_ON]-> System
MIG-203 -[:CHANGED|AFFECTS]-> System
```

The service only accepts candidate causal paths containing Evidence, at least one dependency hop, and a Change edge. Deleting both `MIG-203` change/effect edges makes the incident's causal path disappear even though node text remains.

### T1.3 Blast Radius
Required traversal:

```text
changed System <-[:DEPENDS_ON*]- downstream consumers
Evidence -[:ABOUT]-> reachable System
```

Removing `SYS-PRICING-API -[:DEPENDS_ON]-> SYS-PRICING-DB` removes Checkout/Mobile/Legacy from the Pricing DB blast radius while direct Pricing Analytics remains reachable. This proves indirect impact comes from graph reachability, not naming.

### T1.4 Knowledge Gaps
Required traversal:

```text
Question -[:ABOUT]-> Incident/relevant entity
Task -[:REQUIRES|BLOCKED_BY]-> Question
Question -[:REQUIRES]-> Tool|DataSource
Question -[:RESOLVED_BY]-> Evidence
Owner -[:OWNS]-> explicitly relevant System
```

Without the Question/requirement/blocker structure, the service cannot prove what fact is expected, what work it blocks, or which missing relationship is a governed absence. It intentionally does not treat every missing edge as false.

### T1.10 Active Evidence Acquisition & Tool Routing
Required traversal:

```text
Question -[:REQUIRES]-> Tool -[:QUERIES]-> DataSource
Question -[:RESOLVED_BY]-> Evidence -[:DERIVED_FROM]-> DataSource
```

Deleting Q-001's `REQUIRES` routes produces `NO_GRAPH_ROUTE` even though tools still exist. Mock acquisition writes new Evidence and provenance back to FalkorDB; Phase 4 does not add production external integrations.

### T1.2 Decision Genealogy and Replay
Required traversal:

```text
Decision -[:BASED_ON]-> Claim|Evidence|Policy
Person|Agent|Team -[:PRODUCED]-> Decision
Decision -[:APPROVED_BY]-> Actor
Event -[:ABOUT]-> Decision|Action
Event -[:PERFORMED_BY]-> Actor
Event -[:BEFORE]-> Event
```

Deleting the Decision's `BASED_ON` edges leaves the final decision statement but makes the replay packet incomplete. Historical replay also filters future Evidence/Events by numeric temporal representation.

### T1.5 Structural Precedent
Required traversal:

```text
Evidence -[:ABOUT]-> Incident
Evidence -[:ABOUT]-> Change
Change -[:CHANGED|AFFECTS]-> System
System -[:DEPENDS_ON]-> System
```

INC-074 is matched to INC-001 from abstract typed motifs before semantic metadata. Removing INC-074's change topology degrades/removes the match even though both incident titles still contain schema/migration-like language.

### T1.6 Constraint Planning
Required traversal:

```text
Action -[:REQUIRES]-> prerequisite
Policy -[:GOVERNS]-> Action
Policy -[:REQUIRES]-> Action
Action -[:APPROVED_BY]-> Actor
Task -[:BLOCKED_BY]-> Question|Task|Action
```

The planner topologically orders Action prerequisites and reports approval/evidence/question blockers. Removing prerequisite edges removes the graph proof that rollback must precede verification and verification must precede restore.

### T1.7 Counterfactual Simulation
Required traversal:

```text
Change -[:CHANGED|AFFECTS]-> System
System <-[:DEPENDS_ON*]- dependents
```

The simulator starts from a FalkorDB-derived snapshot, clones it, applies hypothetical edits only to the clone, and recomputes reachability/constraint deltas. When the canonical change edges are absent, the baseline and rollback counterfactual become indistinguishable.

### T1.8 Graph Anomaly / Motif Deviation
Required traversal:

```text
frontend -[:DEPENDS_ON]-> service -[:DEPENDS_ON]-> database
frontend -[:DEPENDS_ON]-> database   # abnormal bypass
```

Deleting `SYS-ANALYTICS-UI -[:DEPENDS_ON]-> SYS-PROD-ORDERS-DB` removes the exact anomaly while leaving the normal API-mediated path intact. No text/property-only anomaly detector can reproduce that result without recreating the typed topology elsewhere.

## Final challenge

Stop FalkorDB and call the Phase 4 APIs. They must fail materially because the services cannot construct their graph snapshot/traversals. Static fixture files are seed inputs only and are never read by runtime capability services.

# Phase 5 — Planning Graph Necessity

Phase 5 does not copy planning truth into an in-memory canonical task list. Derivation may use a temporary FalkorDB-derived snapshot for deterministic algorithms, but Plans, Tasks, prerequisites, derivation links, candidate workers and creation events are persisted back into FalkorDB.

## Knowledge gap -> task generation

Required traversal:

```text
Question -[:ABOUT]-> Incident
Question -[:REQUIRES]-> Tool|DataSource
Task -[:ADDRESSES]-> Question
Task -[:REQUIRES]-> Tool|DataSource
```

Integration contract: delete `Q-001 -[:ABOUT]-> INC-001`, recompute the plan, and the Q-001 evidence task disappears from current `PLAN_HAS_TASK` membership. Restoring the edge restores the work. The planner does not hard-code `Q-001`.

## Claim conflict -> prerequisite work

Required traversal:

```text
Claim -[:CONTRADICTS]- Claim
Evidence -[:SUPPORTS|REFUTES]-> Claim
Evidence -[:ABOUT]-> Change|System
Question -[:ABOUT]-> same Change|System
Task(RESOLVE_CONFLICT) -[:REQUIRES]-> evidence/investigation Task
```

The C-001/C-002 resolution task depends only on gap tasks whose specific graph context intersects the conflicting claims' evidence context; Q-004's orphan-ownership gap is intentionally not made a root-cause prerequisite.

## Task ordering / readiness

Required traversal:

```text
Plan -[:PLAN_HAS_TASK]-> Task
Task(dependent) -[:REQUIRES]-> Task(prerequisite)
```

Readiness traverses the persisted `REQUIRES` DAG. Removing a required Task edge changes readiness/order; adding the inverse edge to an existing dependency produces a detectable cycle and invalidates the Plan.

## Candidate worker routing

Required traversal:

```text
Person -[:EXPERT_IN]-> System
Person -[:RESPONSIBLE_FOR]-> System
Team   -[:OWNS]-> System
Person -[:MEMBER_OF]-> Team
subject -[:APPROVED_BY]-> Person|Team
Tool -[:QUERIES]-> DataSource
Candidate -[:CANDIDATE_FOR]-> Task
```

Phase 5 calls the existing Phase 3 `ResponsibilityRoutingService` and Phase 4 evidence-routing service. It only applies task-purpose weighting to their role-preserving result. Removing `PERSON-RIYA -[:EXPERT_IN]-> SYS-PRICING-DB` and recomputing lowers/removes Riya from the strongest Pricing DB technical candidate position; team ownership is not silently relabeled as expertise.

## Policy work

Required traversal:

```text
Policy -[:GOVERNS]-> Action|Change|System
Policy -[:REQUIRES]-> prerequisite
Plan -[:PLAN_HAS_TASK]-> Task(VALIDATE_POLICY)
Task -[:ADDRESSES]-> Policy
```

Removing `POL-RECOVERY-01 -[:GOVERNS]-> ACT-ROLLBACK-MIG203` and recomputing removes that policy-validation task. The policy task is therefore caused by the graph scope edge, not by fixture-specific code.

## Idempotency and event provenance

Required traversal:

```text
Plan -[:PLAN_HAS_TASK]-> Task
Event(PLAN_CREATED) -[:ABOUT]-> Plan
Event(TASK_CREATED) -[:ABOUT]-> Task
Event -[:PERFORMED_BY]-> AGENT-DETERMINISTIC-PLANNER
```

Plan and Task identities are deterministic. Recomputing the same situation+goal+historical cutoff+explicit planning-selection scope reuses the same nodes and creation-event IDs rather than appending duplicate task graphs. Recompute also removes stale planner-owned prerequisite/derivation edges instead of letting obsolete graph structure affect readiness.

## Failure if FalkorDB is unavailable

The Phase 5 API cannot derive or retrieve Plans if FalkorDB is unavailable because `GraphSnapshot.load`, knowledge-gap detection, constraint planning, routing, persistence, readiness and validation all depend on FalkorDB reads/writes. There is no runtime JSON or vector-store fallback.

# Phase 6 — Coordination Graph Necessity

Phase 6 coordination is deliberately load-bearing on FalkorDB. Production services do not reconstruct canonical owner/checkpoint/handoff/branch/action state from fixtures or process-local dictionaries.

## T2.1 Persistent blackboard

Required traversal:

```text
Task <-[:ABOUT]- Finding
Task <-[:ABOUT]- Evidence
Task -[:CLAIMED_BY]-> Agent
Task -[:HAS_EXECUTION]-> Execution
```

Integration test: remove `Finding -[:ABOUT]-> Task`; the Finding disappears from `get_task_blackboard()` even though the Finding node still exists. Shared state therefore depends on the graph link, not a hidden list.

## T2.3 Resumability

Required traversal:

```text
Task -[:HAS_EXECUTION]-> Execution -[:HAS_CHECKPOINT]-> Checkpoint
Task -[:CLAIMED_BY]-> Agent
```

Restart reconstruction reads the latest checkpoint and computes `resume_from_step = latest.step_index + 1`. Integration tests persist steps 1/2, create a new service instance and resume at step 3. Archived checkpoints can be intentionally excluded from active resume state.

## T2.6 Handoff validation

Required traversal:

```text
Handoff -[:HANDOFF_FOR]-> Task
Handoff -[:ASSIGNED_TO]-> Agent
Handoff -[:REQUIRES]-> Finding|Evidence
```

Integration test: delete the handoff's required Evidence relationship; an Investigator->Verifier contract changes from valid to invalid. Artifact identity cannot be recovered from a prose handoff string.

## T2.4 Branch / merge

Required traversal:

```text
Task -[:HAS_BRANCH]-> WorkBranch -[:PART_OF]-> Execution
WorkBranch -[:CONTAINS]-> Finding
Merged Finding -[:DERIVED_FROM]-> WorkBranch|branch Finding|Evidence
```

Integration test: deleting `WorkBranch -[:PART_OF]-> Execution` produces `MISSING_BRANCH_PROVENANCE` and blocks validated merge. Rejected branch nodes/findings remain in FalkorDB.

## T2.5 Deadlock / contention

Required traversal:

```text
Task -[:REQUIRES|BLOCKED_BY]-> Task
Task -[:CLAIMED_BY]-> Agent
Lock -[:LOCKS]-> Resource
```

Integration tests construct a two-Task circular wait; removing one blocking edge removes the detected cycle. Active multiple owners, expired Lock leases and repeated READY/no-owner state are also detected from graph state.

Resource mutation coordination additionally uses deterministic per-resource Lock nodes. A second different Action cannot acquire the same unexpired resource lease.

## T2.2 Governance

Required traversal:

```text
Task -[:PROPOSED_ACTION]-> Action -[:ABOUT]-> System
Team|Person -[:OWNS|RESPONSIBLE_FOR]-> System
Policy -[:GOVERNS]-> Action|System
Action -[:APPROVED_BY]-> Actor
Action -[:REQUIRES]-> Evidence|Question
Task -[:CLAIMED_BY]-> Agent
```

Integration test: remove the required `APPROVED_BY` edge and the governance decision changes from `ALLOW` to `REQUIRES_APPROVAL`. An authoritative DENY policy prevents the mock executor from being invoked even when the worker requests execution.

## T2.7 Practical exactly-once coordination

Required graph state:

```text
Action -[:HAS_ATTEMPT]-> ActionAttempt
ActionAttempt -[:PERFORMED_BY]-> Agent
Lock -[:LOCKS]-> Action|System|Deployment|Change
Lock -[:LOCKED_BY]-> Agent
```

The deterministic ActionAttempt is created/acquired with one FalkorDB `MERGE ... ON CREATE ... WHERE execution_state ... SET` mutation. Duplicate callers cannot reset an `EXECUTING`/`SUCCEEDED` attempt to `PENDING`. Per-resource Lock acquisition is also a conditional graph mutation.

Tests verify one mock invocation for duplicate/sequential and concurrent callers, safe retry only before the external call, and `UNKNOWN` instead of blind retry after an uncertain external side effect.

The graph proves coordination state; it does **not** create a universal external exactly-once guarantee. Destination idempotency/reconciliation is still required for uncertain external outcomes.

## T2.8 Dependency-preserving compaction

Required traversal:

```text
Execution -[:HAS_CHECKPOINT]-> Checkpoint
Execution -[:HAS_COMPACTION]-> CompactionRecord
CompactionRecord -[:DERIVED_FROM]-> retained/archive entities
Evidence|Finding -[:ABOUT]-> Task
WorkBranch -[:PART_OF]-> Execution
Action -[:HAS_ATTEMPT]-> ActionAttempt
```

Integration test: remove preserved `Evidence -[:ABOUT]-> Task`; `validate_compaction()` fails with an artifact-lineage error. Compaction therefore cannot pass merely because a text summary exists.

## Stop-FalkorDB challenge

With FalkorDB unavailable, Phase 6 cannot determine the current owner, resume position, shared findings, transfer validity, branch provenance, deadlock cycle, governance inputs, action-attempt state or compaction lineage. No runtime JSON fallback reproduces these capabilities.


# Phase 7 graph-necessity tests

- **Promotion lineage:** a validated artifact without independent Evidence lineage cannot promote; self-produced/self-derived Evidence is rejected.
- **Stale Claim:** remove `Evidence -[:SUPPORTS]-> Claim`; Evidence invalidation no longer affects that Claim.
- **Decision impact:** remove `Decision -[:BASED_ON]-> Claim`; Claim/Evidence change no longer marks that Decision affected.
- **Task impact:** remove `Task -[:ADDRESSES|DERIVED_FROM]-> Claim|Decision`; the Task is no longer propagated as stale.
- **Plan impact:** remove `Plan -[:PLAN_HAS_TASK]-> Task`; the Plan is no longer marked for recompute through that Task.
- **Precedent learning:** precedent eligibility requires `ROOT_CAUSE`, Decision genealogy, remediation Action and `HAS_OUTCOME`; existing Phase 4 precedent reasoning uses the resulting graph rather than a learned-case list.
- **Responsibility:** verified relationship promotion requires validator/verification graph state; current routing changes because the temporal `OWNS`/`RESPONSIBLE_FOR` edges change.

# Phase 8 — Company Brain analytics graph necessity

| Capability | Load-bearing FalkorDB relationships | Necessity test | Expected failure/degradation |
|---|---|---|---|
| Process reconstruction | `ABOUT`, `BEFORE`, `TRIGGERED`, `REQUIRES`/`BLOCKED_BY`/`DEPENDS_ON`, validated `ROOT_CAUSE`/`CAUSE` | remove `EVT-INC-001 -[:TRIGGERED]-> EVT-TASK-INV` | chronology remains but trigger semantics disappear; the service does not invent the trigger from timestamps |
| Policy drift | `Policy -[:REQUIRES]-> step/evidence`, `GOVERNS`, `APPROVED_BY`, ordering edges | remove `POL-DB-04 -[:REQUIRES]-> ACT-COMPAT-TEST` | the corresponding missing-compatibility violation can no longer be derived |
| Commitment tracking | `PROMISED_BY`, `OWED_TO`, `COMMITTED_TO`, `SATISFIED_BY`/`BREACHED_BY`, dependency edges | remove `COM-017 -[:OWED_TO]-> TEAM-PAYMENTS` | promisee becomes unreconstructable; remove dependency and downstream consequence disappears |
| Initiative collision | Project structural relations to Systems/DataSources/requirements/stakeholders | remove shared DataSource/requirement edges | collision score decreases because structural overlap dimensions disappear |
| Bus factor | `OWNS`, `RESPONSIBLE_FOR`, `EXPERT_IN`, `APPROVED_BY`, task-candidate edges | remove sole `EXPERT_IN`; add a second expert | expertise coverage/risk changes in both directions; no fixture-ID override exists |
| Bottleneck / bridge | named projection relationships (`MEMBER_OF`, project participation, `DEPENDS_ON`, ownership/responsibility) | add a redundant collaboration edge | former articulation/bridge risk disappears because connectivity genuinely changes |

The analysis services never read fixture JSON at runtime. They require a FalkorDB-derived `GraphSnapshot`; stopping/removing FalkorDB materially prevents these capabilities from reconstructing their projections.

# Phase 9 graph-necessity audit

| Capability | Load-bearing graph structure | Removal test | Expected degradation |
|---|---|---|---|
| ingestion entity resolution | `ExternalIdentity -[:RESOLVES_TO]-> Entity` plus SourceRecord identity evidence | remove `RESOLVES_TO` | source identity can no longer reconstruct canonical entity |
| provenance | `SourceRecord -[:NORMALIZED_TO]-> canonical fact`, `IngestionRun -[:INGESTED]-> SourceRecord` | remove NORMALIZED_TO | origin validation becomes incomplete |
| source disagreement | source-derived Claim `CONTRADICTS` Claim plus Evidence support | remove conflict/assertion relation | conflict set loses source disagreement |
| imported dependency | `System -[:DEPENDS_ON]-> System` | remove imported edge | existing Phase 4 blast radius changes |
| imported ownership | `Team/Person -[:OWNS]-> System` | remove imported edge | existing Phase 3 current-owner routing changes |
| imported policy | `Policy -[:REQUIRES]-> requirement` | remove imported requirement | Phase 8 drift no longer derives that missing control |
| artifact lineage | `Evidence -[:DERIVED_FROM]-> Artifact` | remove edge | original large evidence bytes can no longer be traced from Evidence |

These tests operate on isolated/test records and do not rely on fixture-ID conditionals inside algorithms.

## Phase 10 — Graph-first retrieval necessity

Phase 10 fails closed when graph scope disappears. Tests explicitly remove Incident→System and SourceRecord→Artifact relationships and assert selected source/artifact candidates disappear. Keyword-heavy and semantically similar distractors outside the selected graph neighborhood are excluded before BM25/cosine ranking. Removing an Evidence→Artifact provenance edge removes that explanation path. Temporal tests preserve the corrected E-003/E-004 behavior at 14:09.


## Phase 11 — External API graph necessity

The v1 layer deliberately delegates to graph-backed services; it does not reconstruct canonical answers in route code. Real-FalkorDB HTTP tests remove load-bearing relationships and require externally observable degradation:

| External API capability | Removed relationship | Required API change |
|---|---|---|
| Blast radius | `System -[:DEPENDS_ON]-> System` | downstream result/path disappears |
| Claim Evidence | `Evidence -[:SUPPORTS]-> Claim` | Claim evidence response loses that support |
| Decision genealogy | `Decision -[:BASED_ON]-> Claim` | genealogy becomes incomplete |
| Ownership-gap risk | `Team/Person -[:OWNS]-> System` | risk/ownership response changes |
| Investigation retrieval provenance | `RetrievalExecution -[:RETURNED]-> Evidence` | Evidence can no longer report the retrieval execution that returned it |
| Process reconstruction | `Event -[:BEFORE]-> Event` | temporal process edge disappears; chronology is not recreated as CAUSE |

These tests prove the external API remains an application boundary over FalkorDB-backed semantics rather than a fixture-aware result generator.
