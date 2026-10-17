# Capability Status — Through Phase 8

> `FOUNDATION EXISTS` means the ontology/fixture can represent the idea. `IMPLEMENTED` means a deterministic service/API plus objective tests exist. FalkorDB remains canonical.

## Track 1 — Agents That Act on Connected Data

### T1.1 — Relational Investigation
- **IMPLEMENTED (Phase 4):** bounded, typed multi-hop incident traversal; incident-linked change candidate selection; evidence/dependency/change path filtering; deterministic path scoring; preserved explanation paths.
- **TESTED:** `INC-001` must expose a connected path containing `MIG-203`, `SYS-PRICING-API`, `SYS-PRICING-DB`, dependency edges and evidence. Removing change edges destroys the causal path.

### T1.2 — Decision Genealogy and Agent Replay
- **IMPLEMENTED (Phase 4):** reconstructs `Decision -[:BASED_ON]-> Claim|Evidence|Policy`, producers, approvals, selected/alternative actions and event-ledger history as of a timezone-aware time. Later outcomes are reported separately and excluded from historical replay.
- **TESTED:** `DEC-INC001-ROLLBACK`; removing `BASED_ON` makes replay incomplete. No private model chain-of-thought is stored.

### T1.3 — Blast-Radius Dependency Search
- **IMPLEMENTED (Phase 4):** cycle-safe upstream/downstream `DEPENDS_ON` traversal with depth/path output and `OBSERVED` versus `POTENTIAL` impact based on incident-linked evidence.
- **TESTED:** `SYS-PRICING-DB`; deleting the Pricing API dependency removes indirect Checkout/Mobile/Legacy reachability while preserving unrelated direct consumers.

### T1.4 — Knowledge-Gap Detection
- **IMPLEMENTED (Phase 4):** detects open/unanswered Questions, explicit expected-evidence gaps, unsupported active claims, missing owner for explicitly relevant systems, and explicit approval-required relation gaps. Absence is flagged only when a defined graph/domain rule expects it.
- **TESTED:** `Q-001..Q-004`; task blockers and tool/source requirements remain explicit.

### T1.5 — Structural Precedent Reasoning
- **IMPLEMENTED (Phase 4):** extracts bounded typed incident motifs, scores structural signatures before semantic metadata, and returns matching evidence plus explanation paths. Keyword overlap contributes only a small secondary component.
- **TESTED:** `INC-074` is a strong structural precedent for `INC-001`; deleting its change topology degrades/removes the match.

### T1.6 — Constraint-Aware Graph Planning
- **IMPLEMENTED (Phase 4):** generates a graph-backed action partial order using `REQUIRES`, policy `GOVERNS/REQUIRES`, `APPROVED_BY`, required evidence/question state, prohibited state rules, and task blockers. Cycles/violations are explicit.
- **TESTED:** rollback -> verify -> restore ordering; an unselected alternative is rejected; removing prerequisite edges removes the proof of ordering.

### T1.7 — Counterfactual Intervention Simulation
- **IMPLEMENTED (Phase 4):** clones a FalkorDB-derived graph snapshot into isolated hypothetical memory; supports dependency removal, change rollback, compatibility-layer insertion and relationship replacement; recomputes blast radius/constraint deltas without database mutation.
- **TESTED:** rolling back `MIG-203` removes its exposure paths in the hypothetical graph while the canonical FalkorDB edge/status remains unchanged.

### T1.8 — Graph Anomaly & Motif-Deviation Detection
- **IMPLEMENTED (Phase 4):** explainable deterministic rules for frontend->database bypass, missing Decision basis, deployed Change without target, and dependency cycles. This is intentionally not advertised as generic ML anomaly detection.
- **TESTED:** exact `SYS-ANALYTICS-UI -[:DEPENDS_ON]-> SYS-PROD-ORDERS-DB` shadow edge is flagged; removing it removes that anomaly.

### T1.9 — Relational Entity Resolution
- **IMPLEMENTED (Phase 4):** source-record candidate generation/scoring from names/aliases, source ID metadata, organizational context and existing relational match evidence; confirmed `REPRESENTS` mappings are distinct from unresolved `CANDIDATE_MATCH` proposals; no uncertain auto-merge.
- **TESTED:** HR record resolves to `PERSON-RIYA`; CRM record remains an unresolved 0.72 candidate; removing the candidate edge degrades graph evidence/confidence.

### T1.10 — Active Evidence Acquisition & Tool Routing
- **IMPLEMENTED (Phase 4):** explicit `Question -[:REQUIRES]-> Tool|DataSource`, `Tool -[:QUERIES]-> DataSource` routing, authoritative-source ordering, deterministic mock execution, Evidence creation, `DERIVED_FROM`, `ABOUT`, and `Question -[:RESOLVED_BY]-> Evidence` provenance.
- **PHASE-4 BOUNDARY:** external source execution is mocked; no production Slack/Jira/GitHub connector is introduced.
- **TESTED:** `Q-001` routes to deployment/code evidence; `Q-003` routes to deployment/log evidence; deleting routing edges yields `NO_GRAPH_ROUTE`.

## Track 2 — Agent Memory and Coordination

> Phase 6 behavior and real-FalkorDB integration tests are implemented. This sandbox cannot run FalkorDB, so the final local-host integration completion run is still required before claiming the repository-wide Phase 6 success condition.

### T2.1 — Persistent Multi-Agent Blackboard
- **IMPLEMENTED (Phase 6 code; local real-FalkorDB completion run pending):** Task ownership, Execution, Checkpoint, Finding, Blocker, shared Evidence, Handoff, Branch and Action state are persisted as graph-native objects/relationships. New service instances reconstruct state from FalkorDB; there is no canonical in-memory blackboard document.
- **TESTED:** owner/finding/blocker/evidence persistence, reconstruction, cross-agent visibility, and deletion of a Finding->Task `ABOUT` edge removing it from Task shared state.

### T2.2 — Governed Agent Action
- **IMPLEMENTED (Phase 6 code; local real-FalkorDB completion run pending):** deterministic governance evaluates task state/ownership, agent permission/action type, Phase 3 ownership paths, Policy scope/deny, approval edges, Evidence/Question requirements and blockers. Result is `ALLOW`, `DENY`, `REQUIRES_APPROVAL` or `INSUFFICIENT_EVIDENCE`.
- **BOUNDARY:** only a deterministic sandbox/mock executor is connected. No production/destructive action integration exists.
- **TESTED:** allowed action, unauthorized agent, missing approval, explicit policy denial and “agent says execute + policy says deny = no invocation”.

### T2.3 — Resumable Agent Execution
- **IMPLEMENTED (Phase 6 code; local real-FalkorDB completion run pending):** durable Execution/Checkpoint state, latest-step reconstruction, same-agent resume, eligible cross-agent ownership transfer/resume, blocker checks and structured checkpoint state.
- **TESTED:** steps 1/2 survive service reconstruction and resume begins at step 3; ineligible worker cannot resume; prior findings remain.

### T2.4 — Branch-and-Merge Agent Memory
- **IMPLEMENTED (Phase 6 code; local real-FalkorDB completion run pending):** WorkBranch isolates branch-local Findings; validation checks provenance/confidence/evidence; merge promotes validated results as new shared Findings with DERIVED_FROM lineage; rejected branches remain queryable.
- **TESTED:** isolation, validated merge, rejected retention/non-promotion, and missing branch->Execution provenance invalidates merge validation.

### T2.5 — Agent Deadlock & Contention Detection
- **IMPLEMENTED (Phase 6 code; local real-FalkorDB completion run pending):** deterministic Task dependency-cycle detection, multiple active-owner detection, expired lease detection, repeated-ready starvation heuristic, and resource-lease contention prevention/detection.
- **SCOPE:** this is explainable graph/rule detection, not a claim of general distributed deadlock proof.
- **TESTED:** circular wait disappears when an edge is removed; conflicting owners, expired locks, starvation and competing action resource leases.

### T2.6 — Handoff Contract Validation
- **IMPLEMENTED (Phase 6 code; local real-FalkorDB completion run pending):** persistent Handoff contracts validate required fields/artifact kinds, confidence, blocker disclosure, contradictory-evidence disclosure and receiver identity. Validator returns structured errors/warnings/missing fields/evidence/blockers/confidence failures.
- **TESTED:** accepted complete Investigator->Verifier transfer and negative missing-evidence/blocker/low-confidence cases; removing a required artifact relationship invalidates the transfer.

### T2.7 — Exactly-Once Action Coordination
- **IMPLEMENTED FOR PHASE-6 SANDBOX / IDEMPOTENT DESTINATION SEMANTICS (local real-FalkorDB completion run pending):** deterministic idempotency key/attempt ID, single-query attempt CAS, deterministic per-resource leases, durable attempt state, duplicate detection and crash recovery.
- **NOT CLAIMED:** universal exactly-once side effects for arbitrary external systems. After an uncertain non-reconcilable external call, state becomes `UNKNOWN` and is not blindly retried.
- **TESTED:** duplicate logical action invokes mock sink once, completed duplicate returns `ALREADY_COMPLETED`, concurrent duplicate workers invoke once, crash-before-call safely retries, uncertain result becomes `UNKNOWN`, idempotent reconciliation can recover success.

### T2.8 — Dependency-Preserving Memory Compaction
- **IMPLEMENTED (Phase 6 code; local real-FalkorDB completion run pending):** old Checkpoints are marked `ARCHIVED`, not deleted; CompactionRecord preserves retained/archived manifests and Findings/Evidence/Decision/Handoff/Branch/Action/Attempt/Blocker lineage.
- **TESTED:** checkpoint reduction, evidence/decision/branch/action outcome preservation, and broken evidence lineage invalidates compaction.

### Phase 6 Task 31 — Four Specialist Agents
- **IMPLEMENTED (bounded deterministic workers):** INVESTIGATOR, VERIFIER, DEPENDENCY_ANALYST and REMEDIATION_WORKER capability records persist in FalkorDB. Workers reuse Phase 4 investigation/blast-radius and Phase 6 verification/governance primitives rather than running free-form LLM loops.
- **ROUTING:** Phase 5 remains responsible for candidate worker ranking. Phase 6 performs actual claim/ownership only after eligibility/readiness checks.

## Track 3 — Company Brain

### T3.1 — Conflict-Aware Organizational Memory
- **IMPLEMENTED (Phase 3):** preserved unchanged except shared temporal infrastructure.

### T3.2 — Graph-Based Authority / Contradiction Resolution
- **IMPLEMENTED (Phase 3):** preserved unchanged.

### T3.3 — Responsibility and Expertise Routing
- **IMPLEMENTED (Phase 3):** preserved unchanged.

### T3.4 — Organizational Process Reconstruction
- **IMPLEMENTED (Phase 8 code; real-FalkorDB completion run pending in this sandbox):** bounded event-scope reconstruction with actors, tasks/artifacts, explicit `BEFORE`, explicit `TRIGGERED`, task/action dependencies, ambiguity reporting and validated causal edges only. Chronology alone never becomes causation.

### T3.5 — Policy-vs-Practice Drift Detection
- **IMPLEMENTED (Phase 8 code; real-FalkorDB completion run pending):** structured policy requirements are compared to reconstructed observed process state. Detects missing required steps/evidence/approval, order violations, unauthorized actors, bypassed controls, unexpected steps, optional variation and historical policy-version selection.

### T3.6 — Organizational Bus-Factor Analysis
- **IMPLEMENTED (Phase 8 code; real-FalkorDB completion run pending):** per-resource ownership/responsibility/expertise/approval coverage, concentration risk and non-mutating actor-loss simulation. No company-wide single-number fiction and no employee performance scoring.

### T3.7 — Duplicate-Work / Initiative Collision Detection
- **IMPLEMENTED (Phase 8 code; real-FalkorDB completion run pending):** bounded candidate-pair generation from shared graph neighborhoods followed by explicit weighted overlap across goals, systems, datasets, stakeholders, requirements and dependencies. Collaboration relationships suppress false duplicate-work classification.

### T3.8 — Organizational Bottleneck & Bridge Detection
- **IMPLEMENTED (Phase 8 code; real-FalkorDB completion run pending):** explicit collaboration/system-dependency/ownership/approval projections with deterministic degree/betweenness centrality, Tarjan articulation points/bridges, bridge-separated communities, single-path risk and overload only when structural centrality is combined with operational load evidence.

### T3.9 — Commitment and Obligation Tracking
- **IMPLEMENTED (Phase 8 code; real-FalkorDB completion run pending):** reconstructs promisor, promisee, subject, due date, fulfillment/breach evidence, provenance, historical status and downstream consequences. Passing a deadline without evidence yields `OVERDUE`, not a fabricated breach.

### T3.10 — Ownership-Gap / Orphaned-Resource Detection
- **IMPLEMENTED (Phase 3):** preserved unchanged.

### Track 3 completion gate
All ten Track 3 capabilities now have implemented deterministic code and objective tests. **Track 3 is not marked fully COMPLETE in this sandbox until the real-FalkorDB integration suite runs locally without skips/failures.**


## Phase 5 — Convert Reasoning Into Work

### Task 27 — Deterministic Planner
- **IMPLEMENTED (Phase 5; real-FalkorDB verification test present, local sandbox execution unavailable):** `WorkPlanningService` consumes Phase 4 knowledge gaps/tool routing/constraint planning plus explicit contradiction topology and produces a typed DAG-like task structure. It does not independently rediscover the incident through an LLM.
- **BEHAVIOR:** unresolved Questions create evidence/investigation work; explicit Claim contradictions create `RESOLVE_CONFLICT`; selected Phase 4 Actions create `PREPARE_ACTION`; governing Policies create `VALIDATE_POLICY`; missing required approval creates `REQUEST_APPROVAL`. Cyclic generated dependencies are rejected.
- **IDEMPOTENCY:** Plan IDs are deterministic by tenant+situation+normalized goal+historical cutoff+explicit planning-selection fingerprint; Task IDs/semantic keys are deterministic, equivalent active same-situation work may be referenced, and recompute synchronizes stale planner-owned edges instead of duplicating work.
- **TEMPORAL:** explicit `as_of` uses the numeric temporal model to exclude future Questions, Evidence routes, Actions and relationship state. Claim supersession is evaluated from temporal `SUPERSEDES` edges so current materialized state cannot erase earlier truth. Historical and current plans receive different deterministic IDs.

### Task 28 — Graph-backed Plan / Task Model
- **IMPLEMENTED (Phase 5; real-FalkorDB verification test present, local sandbox execution unavailable):** adds the `Plan` label and persists Plan/Task structure with `PLAN_HAS_TASK`, Task `REQUIRES` prerequisites, `ADDRESSES` derivation links, `ABOUT` targets, and structured task properties (`task_type`, objective, output type, completion condition, semantic key, assignee requirement).
- **READINESS:** `get_ready_tasks` traverses Task `REQUIRES` and `BLOCKED_BY`; completed/cancelled/superseded tasks are excluded from readiness.
- **VALIDATION:** checks non-empty plan, Plan/Task connection to the Situation, typed tasks, cycle freedom, dangling task prerequisites, acquisition-source requirements, expected output, completion condition, candidate resolvability and approval-work representation. Explicit caller constraints must resolve to canonical, temporally visible graph entities and are persisted through `ADDRESSES`.
- **EVENT LEDGER:** deterministic `PLAN_CREATED` / `TASK_CREATED` Events point back to Plan/Task/Situation and `AGENT-DETERMINISTIC-PLANNER`. No execution event is emitted.

### Task 29 — Candidate Workers via Existing Responsibility / Expertise Routing
- **IMPLEMENTED (Phase 5; real-FalkorDB verification test present, local sandbox execution unavailable):** reuses `ResponsibilityRoutingService` and `EvidenceAcquisitionService`; it does not implement a second organizational traversal algorithm.
- **ROLE PRESERVATION:** task requirement changes ranking semantics: technical tasks prefer explicit `EXPERT_IN`; authority tasks prefer `OWNS`/`RESPONSIBLE_FOR`; approval tasks prefer approver evidence; evidence acquisition can rank graph-routed `Tool` nodes.
- **PERSISTENCE:** candidates are represented as `Person|Team|Agent|Tool -[:CANDIDATE_FOR]-> Task` with score/requirement/explanation metadata. This is intentionally distinct from `ASSIGNED_TO`; Phase 5 does not make or claim actual assignments.
- **GRAPH NECESSITY:** removing `PERSON-RIYA -[:EXPERT_IN]-> SYS-PRICING-DB` and recomputing lowers/removes Riya's technical ranking; removing Question/Policy/prerequisite edges changes generated work/readiness.

### Historical Phase 5 boundary (superseded by Phase 6 where noted)
Phase 5 deliberately stopped before execution. Phase 6 now implements the FalkorDB-backed blackboard, claiming, resumability, handoff, branch/merge, contention/deadlock detection, governed sandbox actions, practical idempotent action coordination, and memory compaction described in Track 2 above. The following boundaries still remain:

- LangGraph orchestration — **NOT IMPLEMENTED**
- production Slack/Jira/GitHub or destructive infrastructure integrations — **NOT IMPLEMENTED**
- unrestricted autonomous tool use / browser-computer control — **NOT IMPLEMENTED**
- universal exactly-once guarantees for arbitrary non-idempotent external systems — **NOT IMPLEMENTED / NOT CLAIMED**
- frontend — **IMPLEMENTED IN PHASE 12; live Playwright verification pending in this sandbox**


## Phase 7 — Closed-Loop Organizational Learning

> Phase 7 deterministic code, unit tests, and real-FalkorDB integration/API tests exist. This sandbox cannot run FalkorDB, so the local full-suite completion run remains required before claiming the repository-wide Phase 7 success condition.

### P7.39 — Meaningful Result Writeback
- **IMPLEMENTED (code; real-FalkorDB completion run pending):** centralized `LearningWritebackService` persists durable Evidence, Claim genealogy, Decision genealogy, Task completion history and observed Outcome objects. Agent/Task/Execution provenance is graph-native and deterministic writeback IDs prevent duplicate organizational facts.
- **BOUNDARY:** transport/executor success is not automatically treated as an observed business/operational Outcome.

### P7.40 — Validated Memory Promotion
- **IMPLEMENTED (code; real-FalkorDB completion run pending):** deterministic promotion validates status, confidence, validator, independent Evidence, blockers and contradictions before creating a new Claim with `PROMOTED_TO`/`DERIVED_FROM` lineage. Source Finding/Hypothesis remains queryable.
- **INCIDENT LEARNING:** closed incidents require validated root cause, decision genealogy, remediation and observed outcome before becoming historical precedents. Existing Phase 4 precedent reasoning consumes the learned graph directly.
- **RESPONSIBILITY:** verified `OWNS`/`RESPONSIBLE_FOR` promotion closes old temporal intervals and changes current routing while preserving historical ownership.
- **EXPERTISE:** successful validated work creates `ExpertiseEvidence`/`CANDIDATE_EXPERT`, not automatic canonical `EXPERT_IN`.

### P7.41 — Stale Knowledge Invalidation / Revalidation
- **IMPLEMENTED (code; real-FalkorDB completion run pending):** bounded graph propagation supports Evidence invalidation, Claim supersession, Policy supersession, source-authority degradation, ownership/responsibility replacement, dependency changes, identity-resolution changes, and explicitly contradictory observed Outcomes. Dependent Claims/Decisions/Tasks/Plans receive `REQUIRES_REVALIDATION`, `INVALIDATED`, `REQUIRES_REVIEW`, `STALE_INPUT`, or `REPLAN_REQUIRED` as appropriate.
- **REVALIDATION:** replacement active Evidence linked through `SUPPORTS` may restore Claim status to `VALIDATED`; earlier invalidation Events remain in history.
- **GRAPH NECESSITY:** removing `SUPPORTS`, `BASED_ON`, task derivation or `PLAN_HAS_TASK` edges removes the corresponding downstream propagation in tests.

### Closed-loop orchestration
- **IMPLEMENTED (code; real-FalkorDB completion run pending):** `ClosedLoopLearningService.process_completed_execution()` gathers completed execution artifacts and delegates promotion/writeback/invalidation concerns to dedicated services. `close_situation()` evaluates/persists historical precedent eligibility.
- **NO SILENT SELF-LEARNING:** agents cannot directly promote their own conclusions; independent grounding and validation are required.

## Phase 9 — Organizational Data Foundation

Phase 9 does not change the implementation status of Phase 3–8 reasoning. It adds a controlled acquisition/normalization/provenance boundary feeding those capabilities.

| Capability / adapter | Implementation | Verification |
|---|---|---|
| Common SourceAdapter + registry | **IMPLEMENTED** | FIXTURE_VERIFIED; real FalkorDB integration run pending in this sandbox |
| GitHub adapter | **IMPLEMENTED** | FIXTURE_VERIFIED; LIVE_NOT_VERIFIED |
| Jira adapter | **IMPLEMENTED** | FIXTURE_VERIFIED; LIVE_NOT_VERIFIED |
| Slack adapter | **IMPLEMENTED** | FIXTURE_VERIFIED; LIVE_NOT_VERIFIED |
| Teams adapter boundary | **IMPLEMENTED (contract)** | FIXTURE_VERIFIED; LIVE_NOT_VERIFIED |
| Document adapter | **IMPLEMENTED** | FIXTURE_VERIFIED; LIVE_NOT_VERIFIED |
| Telemetry adapter | **IMPLEMENTED** | FIXTURE_VERIFIED; LIVE_NOT_VERIFIED |
| Database adapter | **IMPLEMENTED** | FIXTURE_VERIFIED; optional PostgreSQL backend NOT_LIVE_VERIFIED |
| Internal JSON/REST API adapter | **IMPLEMENTED** | FIXTURE_VERIFIED; LIVE_NOT_VERIFIED |
| Source-to-ontology normalization | **IMPLEMENTED** | deterministic tests pass |
| Relational entity resolution during ingestion | **IMPLEMENTED** | reuses Phase 4 resolver; real FalkorDB integration verification pending here |
| Unresolved-ingestion quarantine | **IMPLEMENTED** | service/API tests exist; real FalkorDB run pending here |
| External provenance / SourceRecord versioning | **IMPLEMENTED** | real FalkorDB integration verification pending here |
| Source trust / Phase 7 promotion boundary | **IMPLEMENTED** | deterministic trust tests + integration tests exist |
| Local content-addressed ArtifactStore | **IMPLEMENTED** | FIXTURE_VERIFIED |
| Incremental cursor + crash-safe retry | **IMPLEMENTED** | integration tests exist; real FalkorDB run pending here |
| Phase 3–8 consumption of imported facts | **IMPLEMENTED IN CODE** | cross-phase integration tests exist; real FalkorDB run pending here |

No provider is marked `LIVE_VERIFIED` because no real GitHub/Jira/Slack/Teams/document/telemetry/database/internal-API credentialed connection was exercised in this environment.

## Phase 10 — Graph RAG + supporting retrieval

- Graph-first scope resolution — **IMPLEMENTED / deterministic tests passing / FalkorDB integration pending in this sandbox**.
- BM25 lexical retrieval — **IMPLEMENTED**.
- Local vector retrieval abstraction — **IMPLEMENTED** using deterministic offline `HashingEmbeddingProvider`; production semantic model provider remains replaceable.
- Document/chunk retrieval — **IMPLEMENTED**.
- Retrieval planner/registry + hybrid RRF — **IMPLEMENTED**.
- SQL/API routing — **IMPLEMENTED for configured Phase 9 sources; no arbitrary SQL/URL support**.
- Retrieval Evidence writeback — **IMPLEMENTED**.
- Phase 9 automatic indexing hook — **IMPLEMENTED**.
- Live provider/database retrieval — **NOT LIVE VERIFIED**.


## Phase 11 — Stable External Application Boundary

- Versioned `/api/v1` facade — **IMPLEMENTED**. Legacy/internal routes remain for compatibility.
- Bearer/API-key Principal authentication — **IMPLEMENTED**. Test credentials are development-only and automatically disabled in production mode.
- Tenant isolation — **IMPLEMENTED** by tenant-bound FalkorGraphClient construction and cross-tenant request rejection.
- Permission gates — **IMPLEMENTED** for graph/evidence/analytics reads and governed mutations. Phase 6/7 governance remains authoritative underneath HTTP.
- Common errors + request correlation — **IMPLEMENTED**. V1 errors use stable codes and every response carries `X-Request-ID`.
- Cursor pagination and query bounds — **IMPLEMENTED**. Page size and graph/retrieval/simulation limits are externally enforced.
- Situations / Investigations / Entities / Paths / Blast Radius — **IMPLEMENTED** by delegation to existing graph/reasoning/retrieval services.
- Claims / Evidence / Plans / Tasks / Agents / Decisions / Actions — **IMPLEMENTED** with existing Phase 5–7 lifecycle semantics preserved.
- Simulations / History / Processes / Risks — **IMPLEMENTED** over Phase 4/7/8 services; simulations remain noncanonical.
- Phase 10 graph-first retrieval facade — **IMPLEMENTED** and uses configured Phase 9 ArtifactStore/retrieval indexes.
- OpenAPI/Swagger grouping — **IMPLEMENTED**.
- Isolated API acceptance runner — **IMPLEMENTED**; real FalkorDB execution is pending in this sandbox.


## Phase 12 — Functional Frontend

- React/TypeScript/Vite application shell — **IMPLEMENTED**.
- Phase 11-only browser boundary — **IMPLEMENTED**; no frontend FalkorDB/Cypher/SQL/internal-service access.
- Situation Dashboard — **IMPLEMENTED**.
- Investigation graph + GraphRAG scope/results/Evidence — **IMPLEMENTED**.
- Plans / Task DAG / coordination blackboard / Agent capabilities — **IMPLEMENTED**.
- Claim/Evidence explorer + authority resolution — **IMPLEMENTED**.
- Decision genealogy/replay + Action governance — **IMPLEMENTED**.
- Entity / Blast Radius / path explanation — **IMPLEMENTED**.
- Counterfactual + bus-factor simulation UI — **IMPLEMENTED**.
- Company Brain process/policy/commitment/ownership/expertise/bus-factor/bottleneck/bridge/collision views — **IMPLEMENTED**.
- Anomaly motif view — **IMPLEMENTED**.
- Thin v1 facades for anomalies, conflict authority, company-wide expertise and session permissions — **IMPLEMENTED**.
- Vitest/RTL test suites + Playwright acceptance harness — **IMPLEMENTED IN CODE**.
- Frontend build + live Playwright against FalkorDB — **NOT VERIFIED IN THIS SANDBOX** because npm registry resolution/node_modules and FalkorDB are unavailable.
