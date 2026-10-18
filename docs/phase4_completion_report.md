# Phase 4 Completion Report — Track 1: Agents That Act on Connected Data

## Scope

Phase 4 was implemented directly on the supplied Phase 1–3 repository. FalkorDB remains the canonical database. Working Phase 3 Company Brain services were not redesigned. No alternate canonical database, vector store, GraphRAG layer, LangGraph runtime, autonomous multi-agent runtime, production external integration, or frontend was added.

Phase 4 first implements deterministic graph capability engines. The only external-source execution is an intentional mock behind a real graph-backed Tool/DataSource routing and Evidence provenance write path.

## Repository tree changes

```text
backend/app/
├─ main.py                                      MODIFIED: Phase 4 APIs
└─ services/
   ├─ phase4_graph.py                           ADDED: FalkorDB-derived graph snapshot + bounded graph primitives
   ├─ entity_resolution_service.py              ADDED
   ├─ investigation_service.py                  ADDED
   ├─ blast_radius_service.py                   ADDED
   ├─ knowledge_gap_service.py                  ADDED
   ├─ evidence_acquisition_service.py           ADDED
   ├─ decision_genealogy_service.py             ADDED
   ├─ precedent_service.py                      ADDED
   ├─ planning_service.py                       ADDED
   ├─ simulation_service.py                     ADDED
   └─ anomaly_service.py                        ADDED

backend/tests/
├─ test_phase4_algorithms.py                    ADDED: deterministic/unit contracts
└─ test_phase4_integration.py                   ADDED: real FalkorDB acceptance + necessity tests

fixtures/scenarios/
└─ scn-phase4-001.json                          ADDED: Tool routes, decision ledger, remediation constraints

docs/
├─ capability_status.md                         MODIFIED
├─ completion_report.md                         MODIFIED
├─ phase4_completion_report.md                  ADDED: Phase 4 completion snapshot
├─ example_queries.md                           MODIFIED
├─ graph_necessity_tests.md                     MODIFIED
├─ ontology.md                                  MODIFIED: narrow Question acquisition provenance clarification
├─ relationships.md                             MODIFIED: REQUIRES source contract aligned with Phase 1 matrix
├─ repository_tree.txt                          MODIFIED
└─ test_report.md                               MODIFIED

README.md                                       MODIFIED
scripts/example_queries.py                      MODIFIED
```

## Files added

- `backend/app/services/phase4_graph.py`
- `backend/app/services/entity_resolution_service.py`
- `backend/app/services/investigation_service.py`
- `backend/app/services/blast_radius_service.py`
- `backend/app/services/knowledge_gap_service.py`
- `backend/app/services/evidence_acquisition_service.py`
- `backend/app/services/decision_genealogy_service.py`
- `backend/app/services/precedent_service.py`
- `backend/app/services/planning_service.py`
- `backend/app/services/simulation_service.py`
- `backend/app/services/anomaly_service.py`
- `backend/tests/test_phase4_algorithms.py`
- `backend/tests/test_phase4_integration.py`
- `fixtures/scenarios/scn-phase4-001.json`
- `docs/phase4_completion_report.md`

## Files modified

- `backend/app/main.py`
- `README.md`
- `docs/capability_status.md`
- `docs/completion_report.md`
- `docs/example_queries.md`
- `docs/graph_necessity_tests.md`
- `docs/ontology.md`
- `docs/relationships.md`
- `docs/repository_tree.txt`
- `docs/test_report.md`
- `scripts/example_queries.py`

The Phase 3 service implementations, canonical incident fixture, temporal representation, graph client, mutations, query safety and existing tests were otherwise left intact.

## Narrow relationship-contract correction

The Phase 1 acceptance matrix for T1.10 explicitly requires:

```text
Question -[:REQUIRES]-> Tool|DataSource
Tool -[:QUERIES]-> DataSource
```

`docs/relationships.md` previously omitted `Question` from the allowed source types for `REQUIRES`, even though the relationship type already existed in the schema and the acceptance contract required it. Phase 4 corrects only that documentation contract and adds the corresponding graph edges. This is a demonstrated inconsistency fix, not a relationship-direction redesign.

---

# Algorithms implemented

## 1. Relational Entity Resolution

Service: `EntityResolutionService`

Algorithm:

1. Load SourceRecord and canonical entities from FalkorDB.
2. If `REPRESENTS` exists, return confirmed mapping.
3. Generate candidate Person entities from name/alias similarity and existing relational candidates.
4. Score deterministic factors:
   - name/alias similarity;
   - source-specific ID metadata when available;
   - organizational context (`MEMBER_OF`, `RESPONSIBLE_FOR`, `EXPERT_IN`) when the source record supplies expected context;
   - existing `CANDIDATE_MATCH.confidence`.
5. Preserve unresolved candidates. No uncertain candidate is auto-merged.
6. Explicit review can promote a mapping through `REPRESENTS`.

Canonical acceptance:

- `SRCREC-HR-991 -> REPRESENTS -> PERSON-RIYA` = confirmed.
- `SRCREC-CRM-42 -> CANDIDATE_MATCH -> PERSON-RIYA {confidence:0.72}` = unresolved.

## 2. Relational Investigation

Service: `RelationalInvestigationService`

Algorithm:

1. Discover Evidence structurally about the incident.
2. Discover candidate Change nodes that share that incident Evidence.
3. Run bounded simple-path traversal over whitelisted semantic relations:
   - `ABOUT`
   - `DEPENDS_ON`
   - `CHANGED`
   - `AFFECTS`
   - `SUPPORTS`
   - `REFUTES`
   - `DERIVED_FROM`
   - `CONTAINS`
4. Reject paths that do not contain:
   - Evidence;
   - at least one dependency hop;
   - a `CHANGED` or `AFFECTS` relation.
5. Score paths deterministically from relationship importance, Evidence/Change presence and path length.
6. Return nodes, edges, Evidence, Systems, Changes and human-readable explanation path.

Canonical result can reconstruct:

```text
INC-001
<-[:ABOUT]- Evidence
-[:ABOUT]-> SYS-CHECKOUT / SYS-PRICING-API
-[:DEPENDS_ON]-> SYS-PRICING-DB
<-[:CHANGED]- MIG-203
```

## 3. Blast-Radius Dependency Search

Service: `BlastRadiusService`

Algorithm:

- System input: reverse bounded `DEPENDS_ON` traversal for downstream consumers plus forward traversal for upstream dependencies.
- Change input: `CHANGED/AFFECTS` targets become blast-radius roots.
- Uses simple-path visited-node cycle protection.
- Every returned consumer includes depth and explicit dependency path.
- Reachability is `POTENTIAL` unless incident-linked Evidence exists about that System, in which case it is `OBSERVED`.

For `SYS-PRICING-DB`, the potential set includes Checkout, Mobile Offers, Legacy Promotion Adapter and Pricing Analytics; observed status is assigned only where Evidence supports it.

## 4. Knowledge-Gap Detection

Service: `KnowledgeGapService`

Only rule-governed absence is flagged.

Implemented rules:

- open Question ABOUT incident => unanswered knowledge gap;
- Question with explicit `REQUIRES Tool|DataSource` but no `RESOLVED_BY` => expected Evidence missing;
- Task `REQUIRES/BLOCKED_BY` Question => blocker/value path retained;
- active Claim with no supporting Evidence => unsupported claim;
- explicitly relevant active System with no current owner => missing owner;
- entity with `approval_required=true` but no `APPROVED_BY` => required relation absent.

It does not infer that an arbitrary absent edge is false.

## 5. Active Evidence Acquisition & Tool Routing

Service: `EvidenceAcquisitionService`

Routing:

```text
Question -[:REQUIRES]-> Tool -[:QUERIES]-> DataSource
```

Routes are ordered deterministically with authoritative DataSources first. Phase 4 mock execution accepts an externally supplied/mock result and writes:

```text
Question -[:RESOLVED_BY]-> Evidence
Evidence -[:DERIVED_FROM]-> DataSource
Evidence -[:ABOUT]-> Question/relevant graph subjects
```

The Question is marked resolved. Production Slack/Jira/GitHub calls are intentionally not included.

## 6. Decision Genealogy and Agent Replay

Service: `DecisionGenealogyService`

Reconstruction uses:

```text
Decision -[:BASED_ON]-> Claim|Evidence|Policy
Actor -[:PRODUCED]-> Decision
Decision -[:APPROVED_BY]-> Actor
Action -[:ABOUT]-> Decision
Event -[:ABOUT]-> Decision|Action
Event -[:PERFORMED_BY]-> Actor
```

All replayed Claim/Evidence/Event inputs must be temporally available at `as_of`. Later ledger events/outcomes are returned separately and are never inserted into the historical replay packet.

No private model chain-of-thought is stored. Only structured graph facts and event-ledger records are used.

## 7. Structural Precedent Reasoning

Service: `StructuralPrecedentService`

Algorithm extracts incident motifs through shared Evidence/Change structure and local dependency topology. Structural matching compares abstract typed motifs such as:

```text
Evidence bridges Incident -> Change
Change -[:CHANGED]-> System
Change -[:AFFECTS]-> System
dependent System -[:DEPENDS_ON]-> changed System
```

Final score:

- 75% structural topology;
- 25% semantic metadata.

Within semantic metadata, title token overlap is only 15%, so keyword overlap can contribute at most 3.75% of the final score. `INC-074` is therefore found from structural similarity, not vocabulary.

## 8. Constraint-Aware Graph Planning

Service: `ConstraintPlanningService`

Implemented constraints:

- Action `REQUIRES` Action/Question/Evidence/Tool/DataSource;
- policy `GOVERNS` Action;
- policy `REQUIRES` Action;
- `approval_required` + `APPROVED_BY`;
- prohibited action/subject state;
- task `BLOCKED_BY` relation;
- topological ordering and cycle detection.

Output is a structured graph-backed partial order with steps, prerequisites, approvals, blockers, violations, rejected alternatives and exact constraint paths.

Canonical remediation order:

```text
ACT-ROLLBACK-MIG203
    -> ACT-VERIFY-ROLLBACK
        -> ACT-RESTORE-CHECKOUT
```

`ACT-KEEP-ROLLING` is retained as an alternative but is not silently inserted into the selected plan.

## 9. Counterfactual Intervention Simulation

Service: `CounterfactualSimulationService`

The service reads canonical FalkorDB graph state once and clones the snapshot in memory. Supported hypothetical operations:

- `remove_dependency`;
- `rollback_change`;
- `add_compatibility_layer`;
- `replace_relationship`.

It recomputes blast-radius reachability and supported constraint summaries on the clone and returns canonical-vs-counterfactual deltas. It never writes hypothetical edges back to FalkorDB.

Canonical integration contract explicitly reloads FalkorDB after simulation and verifies `MIG-203 -[:CHANGED]-> SYS-PRICING-DB` and `MIG-203.status=DEPLOYED` are unchanged.

## 10. Graph Anomaly & Motif-Deviation Detection

Service: `GraphAnomalyService`

This is deterministic motif/rule analysis, not ML anomaly detection.

Supported rules:

- `FRONTEND_DIRECT_DATABASE`: frontend directly depends on database while normal service/API mediation exists;
- `DECISION_REQUIRES_BASIS`: non-draft Decision lacks `BASED_ON`;
- `CHANGE_REQUIRES_TARGET`: deployed/rolled-back Change lacks `CHANGED|AFFECTS` target;
- `DEPENDENCY_CYCLE`: unusual dependency cycle.

Canonical SCN-ANOM result flags only the exact UI -> production DB bypass pattern while retaining the normal UI -> API -> DB path.

---

# FalkorDB reads / graph algorithms

Phase 4's shared `GraphSnapshot` reads canonical tenant state through two parameterized FalkorDB queries:

```cypher
MATCH (n:Entity {tenant_id:$tenant_id})
RETURN n
ORDER BY n.id
```

```cypher
MATCH (a:Entity {tenant_id:$tenant_id})-[r]->(b:Entity {tenant_id:$tenant_id})
RETURN a.id, type(r), r, b.id
ORDER BY a.id, type(r), b.id
```

All Phase 4 algorithms then operate on that FalkorDB-derived typed graph. This keeps graph traversal deterministic while avoiding dynamic arbitrary-Cypher APIs. Bounded traversal depth is limited to 8.

Important graph algorithms include:

- bounded BFS/simple paths;
- reverse dependency reachability;
- forward dependency reachability;
- cycle protection through node-simple paths;
- topological sort of Action prerequisite DAG;
- Counter/Jaccard typed-motif comparison;
- isolated snapshot cloning and edge/state intervention;
- explicit motif/rule checks.

Runtime services never read fixture JSON.

---

# APIs added

- `GET /source-records/{source_record_id}/resolution`
- `POST /source-records/{source_record_id}/resolution/{entity_id}/confirm`
- `GET /incidents/{incident_id}/investigation`
- `GET /entities/{entity_id}/blast-radius`
- `GET /incidents/{incident_id}/knowledge-gaps`
- `GET /questions/{question_id}/tool-routing`
- `POST /questions/{question_id}/acquire-evidence`
- `GET /decisions/{decision_id}/genealogy`
- `GET /incidents/{incident_id}/precedents`
- `POST /plans`
- `POST /simulations`
- `GET /anomalies`

No raw arbitrary Cypher endpoint was introduced.

---

# Fixtures used

Existing:

- `fixtures/canonical_incident.json` — `INC-001`, `INC-074`, `MIG-203`, dependencies, claims/evidence/questions/policy/events.
- `fixtures/scenarios/scn-identity-001.json` — confirmed HR identity plus unresolved CRM candidate.
- `fixtures/scenarios/scn-anom-001.json` — API-mediated dependency plus exact UI->DB shadow dependency.

Added:

- `fixtures/scenarios/scn-phase4-001.json`
  - authoritative Service Catalog DataSource;
  - four read-only Tool nodes;
  - Q-001..Q-004 Tool/source routing and explicit relevant-entity ABOUT edges;
  - `DEC-INC001-ROLLBACK` decision genealogy;
  - selected/alternative actions;
  - recovery policy/constraint graph;
  - decision/action/outcome Event ledger entries.

---

# Tests added

## Deterministic/unit

`backend/tests/test_phase4_algorithms.py`: **11 tests**

Covers all ten capabilities and API route registration.

## Real FalkorDB integration

`backend/tests/test_phase4_integration.py`: **19 tests**

Covers the ten acceptance capabilities plus Graph Necessity degradation/removal tests for entity resolution, investigation, blast radius, tool routing, replay, precedent, planning, simulation and anomaly detection.

---

# Test result in this execution environment

Before Phase 4:

```text
44 collected
15 passed
29 integration skipped
```

After Phase 4:

```text
python -m compileall -q backend scripts
PASS

python scripts/validate_fixtures.py
PASS — canonical + all scenario fixtures

pytest -m "not integration" -v
26 passed, 48 deselected

pytest -m integration -v
48 skipped, 26 deselected

pytest -v
26 passed, 48 skipped
```

The 48 integration tests skip because this sandbox has no `falkordb` Python package and no server reachable at `localhost:6379`. No integration success is claimed here.

Required real-database run:

```powershell
pip install -r requirements.txt
python scripts/reseed.py
pytest -m "not integration" -v
pytest -m integration -v
pytest -v
```

---

# Graph Necessity summary

- **Entity resolution:** removing `CANDIDATE_MATCH` removes relational match evidence and lowers confidence.
- **Investigation:** removing `CHANGED/AFFECTS` destroys the connected causal path.
- **Blast radius:** removing dependency edges removes indirect consumers.
- **Knowledge gaps:** removing Question/requirement/blocker structure removes proof of expected missing information and what it blocks.
- **Tool routing:** removing Question->Tool routes yields `NO_GRAPH_ROUTE`.
- **Replay:** removing `BASED_ON` leaves final Decision text but destroys reconstructable inputs.
- **Precedent:** removing historical Change topology degrades/removes structural match.
- **Planning:** removing `REQUIRES` removes proof of valid action ordering.
- **Simulation:** without Change/dependency edges canonical and hypothetical outcomes become indistinguishable.
- **Anomaly:** removing the abnormal typed edge removes the motif deviation.

See `docs/graph_necessity_tests.md` for the exact removal contracts.

---

# Capability status

Genuinely **IMPLEMENTED** after Phase 4:

- T1.1 Relational Investigation
- T1.2 Decision Genealogy and Agent Replay
- T1.3 Blast-Radius Dependency Search
- T1.4 Knowledge-Gap Detection
- T1.5 Structural Precedent Reasoning
- T1.6 Constraint-Aware Graph Planning
- T1.7 Counterfactual Intervention Simulation
- T1.8 Graph Anomaly & Motif-Deviation Detection
- T1.9 Relational Entity Resolution
- T1.10 Active Evidence Acquisition & Tool Routing
- T3.1 Conflict-Aware Organizational Memory
- T3.2 Graph-Based Authority / Contradiction Resolution
- T3.3 Responsibility and Expertise Routing
- T3.10 Ownership-Gap / Orphaned-Resource Detection

Still **FOUNDATION EXISTS / NOT IMPLEMENTED**:

- all Track 2 multi-agent coordination/runtime capabilities;
- T3.4 Organizational Process Reconstruction;
- T3.5 Policy-vs-Practice Drift Detection;
- T3.6 Bus-Factor Analysis;
- T3.7 Duplicate-Work Detection;
- T3.8 Bottleneck/Bridge Detection;
- T3.9 Commitment Tracking.

---

# Phase 5 / Phase 6 prerequisites

Before later multi-agent phases, the next work should build on—not replace—these contracts:

1. **Persistent task/blackboard state:** define Agent/Task/Claim/Question write leases and durable state transitions in FalkorDB.
2. **Governed action contract:** connect proposed Action to Policy, approval state, idempotency key and execution Event before any production side effect.
3. **Checkpoint/replay contract:** use `Checkpoint` + append-only Event history for resumability rather than hidden in-process memory.
4. **Branch isolation:** use `WorkBranch` for speculative agent memory before any merge into canonical truth.
5. **Handoff validation:** define required artifacts/questions/evidence on Handoff edges before implementing agent-to-agent transfer.
6. **Exactly-once semantics:** enforce Action identity/idempotency plus one terminal execution Event before production integrations are enabled.
7. **Tool execution adapters:** Phase 4 supplies deterministic routing; later phases may replace mock execution with controlled Slack/Jira/GitHub/etc. adapters while preserving `Question -> Tool -> DataSource -> Evidence` provenance.
8. **Integration verification:** run all 74 current tests against the real local FalkorDB before layering orchestration over the graph engines.

Do not introduce LangGraph or autonomous orchestration until these durable graph-state contracts are verified against real FalkorDB.

