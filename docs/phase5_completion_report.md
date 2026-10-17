# Phase 5 Implementation Report — Reasoning → Structured Work

> Verification state: **implementation complete in code; real-FalkorDB completion run still required on the local host.**  
> This sandbox cannot honestly claim the Phase 5 success condition because all integration tests skip when the `falkordb` Python client/server is unavailable.

## 1. Repository tree changes

Phase 5 is an in-place extension of the supplied Phase 4 repository. No new repository, alternate canonical database, LangGraph runtime, multi-agent executor, or frontend was introduced.

### Added

```text
backend/app/services/work_planning_service.py
backend/tests/test_phase5_algorithms.py
backend/tests/test_phase5_integration.py
docs/phase5_completion_report.md
docs/phase5_pytest_output.txt
```

### Modified

```text
README.md
backend/app/domain/models.py
backend/app/graph/schema.py
backend/app/main.py
backend/app/services/evidence_acquisition_service.py
backend/app/services/knowledge_gap_service.py
backend/app/services/planning_service.py
docs/capability_status.md
docs/completion_report.md
docs/event_ledger.md
docs/example_queries.md
docs/feature_test_matrix.md
docs/graph_necessity_tests.md
docs/ontology.md
docs/provenance_model.md
docs/relationships.md
docs/repository_tree.txt
docs/temporal_model.md
docs/test_report.md
```

No fixture file was changed.

## 2. Planner algorithm

`WorkPlanningService` is deterministic and graph-first.

For `situation_id + goal` it:

1. loads canonical current/historical graph state from FalkorDB through `GraphSnapshot`;
2. calls the existing `KnowledgeGapService` for explicit graph-backed gaps;
3. converts unresolved Questions into typed `ACQUIRE_EVIDENCE` or `INVESTIGATE` work according to the existing Question→Tool/DataSource route capability;
4. converts unsupported selected Claims into `VERIFY_CLAIM` work;
5. finds explicit `Claim -[:CONTRADICTS]- Claim` pairs and generates `RESOLVE_CONFLICT`;
6. connects conflict work only to relevant evidence/investigation tasks whose graph context intersects the conflicting claims' evidence/subject context;
7. consumes the existing Phase 4 `ConstraintPlanningService` selected Action order rather than rediscovering action constraints independently;
8. emits `PREPARE_ACTION`;
9. traverses governing Policy relationships and emits `VALIDATE_POLICY`;
10. emits `REQUEST_APPROVAL` only when the selected Action actually requires approval and no current approval edge satisfies it;
11. validates optional explicit constraint IDs against canonical, temporally visible FalkorDB entities and persists those constraints as Plan derivation links;
12. optionally includes explicitly selected Hypotheses as `INVESTIGATE`;
13. semantically deduplicates blueprints;
14. topologically validates the generated prerequisite DAG and rejects cycles before persistence;
15. derives a deterministic Plan ID and semantic Task IDs;
16. reuses equivalent active same-situation work when appropriate;
17. persists the Plan/task graph and synchronizes stale planner-owned derivation/prerequisite edges on recompute;
18. ranks candidate workers using the existing Phase 3 responsibility/expertise router and existing Phase 4 tool router;
19. validates the persisted plan and sets Plan status to `READY` or `BLOCKED`.

There is no LLM task generator and no work execution loop.

## 3. Graph model for Plans and Tasks

### Plan

Phase 5 adds one genuinely missing ontology label: `Plan`.

Persisted fields include:

```text
id
tenant_id
situation_id
goal
status
created_at
created_by
generated_by
planner_version
provenance
strategy_summary
as_of
selection_fingerprint
selected_hypotheses_csv
selected_claims_csv
selected_knowledge_gaps_csv
constraint_refs_csv
```

The selection fingerprint prevents two materially different explicit planning scopes from silently overwriting one another while preserving idempotency for an identical request.

Explicit `constraints` are IDs of canonical graph entities, not arbitrary text. Unknown or temporally inactive references are rejected, and accepted references are persisted as `Plan -[:ADDRESSES]-> Entity` so they remain traversable and explainable.

### Task

The existing `Task` label is reused and extended through persisted properties:

```text
id
tenant_id
name/title
objective
task_type
status
priority
created_at
expected_output_type
completion_condition
semantic_key
semantic_signature
situation_id
assignee_requirement
planner_version
derivation_reason
provenance
```

Traversal-critical semantics are represented by edges, not only by those fields.

## 4. Relationships added / reused

### New Phase 5 relationships

| Relationship | Direction | Meaning |
|---|---|---|
| `PLAN_HAS_TASK` | `Plan -> Task` | durable plan membership |
| `ADDRESSES` | `Plan|Task -> reasoning/target Entity` | why the plan/task exists |
| `CANDIDATE_FOR` | `Person|Team|Agent|Tool -> Task` | ranked recommendation, **not assignment** |

### Existing relationships reused

| Relationship | Phase 5 use |
|---|---|
| `REQUIRES` | Task prerequisite or required Tool/DataSource |
| `BLOCKED_BY` | readiness blocker |
| `ABOUT` | Task target/situation context |
| `OWNS` | formal authority input |
| `RESPONSIBLE_FOR` | operational responsibility input |
| `EXPERT_IN` | technical expertise input |
| `MEMBER_OF` | fallback organizational context |
| `APPROVED_BY` | existing approval / approval-authority evidence |
| `GOVERNS` | policy applicability |
| `PERFORMED_BY` | planner provenance on creation Events |

No vague `RELATED_TO` edge was introduced.

### EvidenceRequirement decision

Phase 5 does **not** add a duplicate `EvidenceRequirement` label. The existing graph already represents the needed contract explicitly as `Task -[:ADDRESSES]-> Question|Claim`, `Task -[:REQUIRES]-> Tool|DataSource`, `Question -[:REQUIRES]-> Tool|DataSource`, and eventual `Question -[:RESOLVED_BY]-> Evidence`. `expected_output_type=EVIDENCE` and the deterministic completion validator complete that contract without hiding traversal-critical state in prose or inventing a second requirement object for the same unresolved Question.

## 5. Task readiness algorithm

`get_ready_tasks(plan_id)` evaluates each persisted Task against FalkorDB:

1. terminal/cancelled/superseded Tasks are not ready;
2. every `Task -[:REQUIRES]-> Task` predecessor must have a completed terminal-success state;
3. required Tool/DataSource nodes must not be inactive/disabled/decommissioned;
4. other required entities must be in a satisfied state when used as starting prerequisites;
5. active `BLOCKED_BY` targets keep the Task blocked.

The method only reports ready/blocked state. It does not claim or execute work.

Removing a real `REQUIRES` prerequisite edge changes readiness, which is covered by an integration test.

## 6. Plan validation algorithm

`validate_plan(plan_id)` returns structured errors/warnings rather than a Boolean.

Checks include:

- Plan contains Tasks;
- Plan is graph-connected to its Situation;
- Task `REQUIRES` graph is acyclic;
- every Task has a supported typed purpose;
- every Task has an expected output type;
- every Task has a completion condition;
- Task prerequisites do not point outside the Plan;
- each Task remains connected to the Plan Situation;
- acquisition work has an explicit Tool/DataSource requirement;
- Question-oriented work addresses an actual Question;
- candidate-assignee requirements resolve to one or more `CANDIDATE_FOR` edges;
- an Action requiring approval either already has approval or has explicit approval work;
- malformed/dangling task structures are reported with machine-readable codes.

## 7. Candidate-assignee algorithm

Phase 5 does **not** create a second ownership/expertise engine.

It calls:

```text
ResponsibilityRoutingService.rank_candidate_responders(...)
```

and then applies task-purpose weighting while preserving the Phase 3 role semantics.

Examples:

- `EXPERTISE`: explicit `DOMAIN_EXPERT` is favored over formal ownership.
- `AUTHORITY`: `FORMAL_OWNER` / `RESPONSIBLE_ACTOR` are favored over technical expertise.
- `APPROVAL`: existing approver/authority paths are favored.
- `TOOL_ACCESS`: Question→Tool/DataSource routes are included directly.

The score is a deterministic 0–100 ranking value. Each persisted `CANDIDATE_FOR` edge also stores:

```text
score
requirement
roles
reason_summary
path_summary
confidence
```

The planner does **not** persist `ASSIGNED_TO`.

### Canonical Pricing Database explanation

For a technical `SYS-PRICING-DB` investigation:

```text
PERSON-RIYA -[:EXPERT_IN]-> SYS-PRICING-DB
```

provides explicit `DOMAIN_EXPERT` evidence.

```text
TEAM-PRICING -[:OWNS]-> SYS-PRICING-DB
```

provides formal ownership, but formal ownership is not treated as technical expertise.

The integration contract asserts that Riya outranks the formal owner for the technical diagnosis task. Removing Riya's `EXPERT_IN` edge changes that ranking.

For authority-oriented Pricing work, the weighting reverses appropriately: ownership/responsibility paths are stronger than expertise alone.

## 8. APIs added / extended

`POST /plans` remains backward compatible:

- legacy body containing only `incident_id` uses the existing Phase 4 action-constraint planner;
- Phase 5 body containing `situation_id` + `goal` creates/reuses the durable Work Plan.

Phase 5 endpoints:

```text
POST /plans
GET  /plans/{plan_id}
GET  /plans/{plan_id}/tasks
GET  /plans/{plan_id}/ready-tasks
GET  /plans/{plan_id}/validate
POST /plans/{plan_id}/recompute

GET  /tasks/{task_id}
GET  /tasks/{task_id}/candidate-assignees
GET  /tasks/{task_id}/prerequisites
GET  /tasks/{task_id}/completion-status
```

No arbitrary Cypher, task-claim, execute, handoff, blackboard or LangGraph route was added.

## 9. Event types

Added to the event model:

```text
PLAN_CREATED
```

Phase 5 also reuses the existing:

```text
TASK_CREATED
```

Creation Events are deterministic:

```text
EVT-{plan_id}-CREATED
EVT-{task_id}-CREATED
```

They are linked with `ABOUT` and `PERFORMED_BY` to `AGENT-DETERMINISTIC-PLANNER`.

No execution, claiming, handoff or autonomous-action event is emitted by Phase 5.

## 10. Temporal behavior

Historical planning uses the corrected temporal model.

An explicit timezone-aware `as_of`:

- is converted through `to_epoch_us`;
- excludes nodes whose created/observed/occurred/valid-from instant is after the cutoff;
- respects relationship validity intervals numerically;
- does not compare ISO timestamps lexicographically;
- produces a distinct deterministic Plan identity from the current plan.

The historical test at `2026-10-16T14:09:00+05:30` has no Phase 5 work because the canonical Questions, conflict, and Phase 4 remediation work did not yet exist. A second cutoff at `2026-10-16T14:15:59+05:30` proves that current Questions/conflicts remain visible while remediation Actions and policy relationships beginning at 14:16 do not leak into the historical Plan. To enforce this, the existing Phase 4 `ConstraintPlanningService` now accepts an optional `as_of` and applies it to all Action/Policy/approval/prerequisite traversals; its default current-state behavior is unchanged.

Historical Question/Tool routing and knowledge-gap membership also use the cutoff. A current materialized Claim status of `SUPERSEDED` does not erase historical truth: the planner checks when the incoming `SUPERSEDES` relationship became active. This prevents future tool routes, later resolution state, and later claim supersession from leaking backward in time while preserving current-state defaults when `as_of` is omitted.

## 11. Idempotency / recomputation

For the same:

```text
tenant
situation
normalized goal
historical cutoff
explicit planning selections
```

the Plan ID is deterministic.

Task IDs are deterministic from the Plan + semantic task key unless an equivalent active same-situation Task is already reusable. Cross-Plan reuse additionally requires an identical deterministic `semantic_signature` covering task type, objective, targets, source requirements and prerequisite semantic keys.

Recomputation:

- does not create duplicate Plan/task graphs;
- removes stale `PLAN_HAS_TASK` membership;
- removes stale planner-owned `ADDRESSES`, `ABOUT`, and `REQUIRES` edges;
- marks unreferenced stale planner Tasks `SUPERSEDED`;
- does **not** supersede a Task still referenced by another Plan;
- reactivates the same deterministic Task if its graph justification disappears and later becomes valid again;
- refreshes candidate edges;
- preserves explicit selected Claims/Hypotheses/knowledge gaps/constraint references.

## 12. Tests added

Baseline supplied by the user:

```text
74 passed
0 failed
```

New Phase 5 tests:

```text
25 deterministic/unit/API tests
18 real-FalkorDB integration tests
43 new tests total
117 total repository tests
```

See `docs/test_report.md` for exact coverage.

## 13. Test output in this environment

The complete raw `pytest -v` output is preserved in `docs/phase5_pytest_output.txt`.

Executable checks:

```text
python -m compileall -q backend scripts
PASS

pytest -m "not integration" -q
51 passed, 66 deselected

pytest -m integration -q
66 skipped, 51 deselected
```

All 66 integration skips are environmental:

```text
FalkorDB Python client is not installed
localhost:6379 integration instance unavailable
```

Breakdown:

```text
48 inherited integration tests skipped
18 Phase 5 integration tests skipped
```

Therefore this report **does not claim Phase 5's final success condition**. The local FalkorDB completion run must produce:

```text
117 passed
0 failed
0 skipped
```

## 14. FalkorDB necessity tests

Phase 5 includes explicit real-database necessity tests.

### Knowledge-gap membership

Delete:

```text
Q-001 -[:ABOUT]-> INC-001
```

Expected:

- Q-001 acquisition Task disappears on recompute;
- the conflict Task no longer requires that stale Task;
- restoring the relationship reactivates the same deterministic Task and prerequisite edge.

### Expertise

Delete:

```text
PERSON-RIYA -[:EXPERT_IN]-> SYS-PRICING-DB
```

Expected:

- Riya no longer ranks as the strongest technical candidate.

### Policy scope

Delete:

```text
POL-RECOVERY-01 -[:GOVERNS]-> ACT-ROLLBACK-MIG203
```

Expected:

- the corresponding policy-validation Task disappears.

### Task prerequisite

Delete a persisted:

```text
VALIDATE_POLICY_TASK -[:REQUIRES]-> PREPARE_ACTION_TASK
```

Expected:

- readiness/order changes.

### Cycles

Add the inverse of an existing Task prerequisite.

Expected:

- `validate_plan` returns `TASK_CYCLE`.

### Explicit caller constraint

Generate a Plan with `constraints=["POL-DB-04"]`.

Expected:

- the Plan identity differs from the unconstrained request;
- FalkorDB contains `Plan -[:ADDRESSES]-> POL-DB-04`;
- an unknown/temporally inactive constraint is rejected rather than stored as opaque text.

### Temporal claim supersession

Create `C-P5-SUPERSEDER -[:SUPERSEDES {valid_from: 14:20}]-> C-001` and materialize C-001 as `SUPERSEDED`.

Expected:

- a current Plan does not treat C-001 as an active conflict participant;
- a historical Plan at 14:15:59 still reconstructs the C-001/C-002 conflict because the supersession edge was not yet active.

These tests depend on real FalkorDB relationships, not hidden fixture JSON fallback.

## 15. Example INC-001 generated plan

For a fresh Phase 4 graph and exact goal:

```text
Resolve INC-001 safely with enough evidence to select remediation.
```

the deterministic derivation currently produces:

```text
PLAN-P5-731E447522D1

TASK-P5-F2A5F875BCA4
  ACQUIRE_EVIDENCE
  addresses Q-001
  requires TOOL-DEPLOY-LOOKUP, TOOL-GIT-LOOKUP

TASK-P5-B0C86915F2E9
  INVESTIGATE
  addresses Q-002 / Pricing DB
  requires TOOL-CATALOG-LOOKUP

TASK-P5-C71BDD2FC1B5
  ACQUIRE_EVIDENCE
  addresses Q-003 / Pricing API
  requires TOOL-DEPLOY-LOOKUP, TOOL-LOG-LOOKUP

TASK-P5-70C97D7DA0EF
  INVESTIGATE
  addresses Q-004 / Legacy Promotion

TASK-P5-007DE9129009
  RESOLVE_CONFLICT
  addresses C-001, C-002
  REQUIRES Q-001 task
  REQUIRES Q-002 task
  REQUIRES Q-003 task

TASK-P5-F69AAA32CC73
  PREPARE_ACTION
  addresses ACT-ROLLBACK-MIG203, ACT-VERIFY-ROLLBACK, ACT-RESTORE-CHECKOUT
  REQUIRES conflict-resolution task

TASK-P5-B5F354BB28D1
  VALIDATE_POLICY
  addresses POL-DB-04
  REQUIRES remediation-preparation task

TASK-P5-32C673D66793
  VALIDATE_POLICY
  addresses POL-RECOVERY-01
  REQUIRES remediation-preparation task
```

`Q-004` remains independent because its Legacy Promotion context is not falsely treated as a prerequisite of the C-001/C-002 root-cause conflict.

No `REQUEST_APPROVAL` Task is generated in the canonical current graph because the selected rollback already has valid approval evidence. If that approval relationship is genuinely absent while the Action requires approval, the planner derives approval work.

## 16. Exact FalkorDB Browser verification queries

After creating a Plan, substitute its ID as `$plan_id`.

### Plan → Tasks

```cypher
MATCH (p:Entity:Plan {tenant_id:'northstar', id:$plan_id})-[:PLAN_HAS_TASK]->(t:Entity:Task)
RETURN p.id, p.status, t.id, t.task_type, t.status, t.expected_output_type
ORDER BY t.priority, t.task_type, t.id;
```

### Task prerequisites

```cypher
MATCH (p:Entity:Plan {tenant_id:'northstar', id:$plan_id})-[:PLAN_HAS_TASK]->(t:Entity:Task)
OPTIONAL MATCH (t)-[:REQUIRES]->(pre:Entity:Task)
RETURN t.id, t.task_type, pre.id
ORDER BY t.id, pre.id;
```

### Derivation / target links

```cypher
MATCH (p:Entity:Plan {tenant_id:'northstar', id:$plan_id})-[:PLAN_HAS_TASK]->(t:Entity:Task)
OPTIONAL MATCH (t)-[:ADDRESSES]->(source:Entity)
OPTIONAL MATCH (t)-[:ABOUT]->(target:Entity)
RETURN t.id, t.task_type, t.derivation_reason,
       collect(DISTINCT source.id),
       collect(DISTINCT target.id)
ORDER BY t.id;
```

### Candidate workers

```cypher
MATCH (candidate:Entity)-[r:CANDIDATE_FOR]->(t:Entity:Task)
MATCH (:Entity:Plan {tenant_id:'northstar', id:$plan_id})-[:PLAN_HAS_TASK]->(t)
RETURN t.id, candidate.id, labels(candidate),
       r.score, r.requirement, r.roles, r.reason_summary
ORDER BY t.id, r.score DESC, candidate.id;
```

### Creation ledger

```cypher
MATCH (e:Entity:Event {tenant_id:'northstar'})
WHERE e.event_type IN ['PLAN_CREATED','TASK_CREATED']
MATCH (e)-[:ABOUT]->(artifact:Entity)
OPTIONAL MATCH (e)-[:PERFORMED_BY]->(generator:Entity)
RETURN e.id, e.event_type, e.occurred_at, artifact.id, generator.id
ORDER BY e.occurred_at, e.id;
```

### Cycle check

```cypher
MATCH (:Entity:Plan {tenant_id:'northstar', id:$plan_id})-[:PLAN_HAS_TASK]->(t:Entity:Task)
MATCH path=(t)-[:REQUIRES*1..]->(t)
RETURN path;
```

Expected for a valid Plan: no rows.

More Browser queries are in `docs/example_queries.md`.

## 17. Migration / reseed requirement

Starting from the successful supplied Phase 4 repository:

```text
database migration required: NO
fixture reseed required for Phase 5: NO
```

Reason:

- Phase 5 adds no seed fixture;
- the global `Entity(tenant_id,id)` identity constraint already covers new Plan nodes;
- Plan/Task/candidate/event data are created on demand;
- relationship whitelisting is application code.

Restart the API with the Phase 5 code before generating Plans.

For integration tests, the test fixture creates and seeds a temporary FalkorDB graph automatically.

If a developer is **not** actually starting from the corrected Phase 4 graph (for example, an older graph lacks the temporal epoch properties or Phase 4 scenario), that older graph must first be migrated/reseeded according to the earlier phase documentation. That is not a new Phase 5 migration.

## 18. Capability status

### IMPLEMENTED IN CODE + REAL-FALKORDB TEST CONTRACTS PRESENT

- Phase 5 Task 27 — deterministic work planner
- Phase 5 Task 28 — durable Plan/Task graph representation
- Phase 5 Task 29 — ranked candidate workers via existing responsibility/expertise/tool routing
- Plan/task readiness
- plan validation
- deterministic idempotency/recompute
- creation-event provenance
- historical `as_of` planning

These are **not declared fully verified in this sandbox** because the real FalkorDB test suite cannot run here.

### FOUNDATION EXISTS

The existing ontology still provides future primitives such as:

- `Agent`
- `Checkpoint`
- `WorkBranch`
- `Handoff`
- Task lifecycle fields
- Event ledger
- `ASSIGNED_TO`, `CLAIMED_BY`, `HANDOFF_FOR` relationship vocabulary

Their presence does not mean the later coordination capabilities are implemented.

### NOT IMPLEMENTED

- multi-agent blackboard execution;
- autonomous worker loop;
- automatic task claiming;
- locks/leases;
- resumable worker execution;
- handoff execution/validation;
- deadlock/contention detection;
- exactly-once external actions;
- branch/merge execution;
- memory compaction;
- LangGraph orchestration;
- production Slack/Jira/GitHub actions;
- frontend.

## 19. Prerequisites for Phase 6

Phase 6 can now consume, but should not redefine, the persisted Phase 5 task graph.

The next layer needs:

1. explicit worker identity/capability registry for software Agents;
2. durable task claim/lease semantics;
3. governed action permissions before side effects;
4. checkpoint/resume state tied to Task and Event;
5. handoff contracts with required artifacts;
6. contention/deadlock rules;
7. idempotency keys and exactly-once external-action records;
8. branch isolation/merge policy where speculative execution is allowed;
9. event-ledger transitions for claiming, execution, failure and completion;
10. tests proving execution uses, rather than bypasses, Phase 5 prerequisites/readiness.

LangGraph or another orchestration framework should only be considered after those state semantics are defined and tested.

## 20. Required local command before claiming Phase 5 complete

With the existing FalkorDB instance running:

```powershell
cd <phase5-repository>
pip install -r requirements.txt
pytest -v
```

Required result:

```text
117 passed
0 failed
0 skipped
```

Only after that result should the project status be described as **Phase 5 complete**.
