# Feature → Problem → Graph Pattern → Expected Behaviour → Acceptance Test Matrix

> Phase 1 acceptance definitions. These are test contracts for later phases; a graph primitive existing in Phase 2 does **not** mean the capability is implemented.

## T1.1 — Relational Investigation

- **Problem class:** Root cause hidden across several connected entities.
- **Minimal graph pattern required:** Incident <-ABOUT- Evidence ->ABOUT Change/System; System DEPENDS_ON System; Evidence SUPPORTS Claim.
- **Input:** INC-001
- **Expected system behaviour:** Traverse incident evidence, causal changes, dependencies and claims rather than keyword-searching one document.
- **Expected FalkorDB traversal/query behaviour:** Multi-hop MATCH paths constrained to semantic edge types; preserve path nodes/edges for explanation.
- **Expected output:** One or more explicit evidence-backed paths from symptom/incident to plausible causes.
- **Pass condition:** Returned path includes MIG-203, SYS-PRICING-API, SYS-PRICING-DB and supporting evidence IDs without reading ground_truth.
- **Failure condition:** No connected path is returned, or result depends only on text similarity.
- **Graph Necessity Test:** Delete the dependency/change/evidence edges; investigation must lose the causal path even though node text remains.

## T1.2 — Decision Genealogy and Agent Replay

- **Problem class:** A past decision/action must be reconstructed from what was known at the time.
- **Minimal graph pattern required:** Decision BASED_ON Claim/Evidence/Policy; Event BEFORE Event; Event ABOUT Decision/Action/Task.
- **Input:** decision_id + as_of time
- **Expected system behaviour:** Reconstruct inputs, actor, approvals, event sequence and later outcome without using future evidence.
- **Expected FalkorDB traversal/query behaviour:** Time-filter Claims/Evidence/Events; traverse BASED_ON/APPROVED_BY/PERFORMED_BY and event ordering.
- **Expected output:** Ordered replay packet with evidence available at decision time and actor/action provenance.
- **Pass condition:** Every replayed item has occurred_at/observed_at <= decision time and all prerequisites are linked.
- **Failure condition:** Replay includes later evidence, loses actor/source, or cannot order events.
- **Graph Necessity Test:** Remove Event/BASED_ON edges; replay must become incomplete even if final decision text still exists.

## T1.3 — Blast-Radius Dependency Search

- **Problem class:** A change can affect indirect consumers that have not yet failed.
- **Minimal graph pattern required:** Changed System <-DEPENDS_ON* downstream Systems; Change CHANGED System.
- **Input:** MIG-203 or SYS-PRICING-DB
- **Expected system behaviour:** Return reachable potential consumers while keeping potential impact distinct from observed impact.
- **Expected FalkorDB traversal/query behaviour:** Reverse variable-length traversal over DEPENDS_ON from changed system, optionally joined to observed Evidence/AFFECTS.
- **Expected output:** Reachable systems with depth/path and observed-vs-potential flag.
- **Pass condition:** Potential set includes Checkout, Mobile Offers, Legacy Promotion Adapter and Pricing Analytics; only observed evidence marks actual failure.
- **Failure condition:** Marks every reachable node as broken or misses indirect dependents.
- **Graph Necessity Test:** Delete DEPENDS_ON edges; blast radius must collapse to directly changed entity.

## T1.4 — Knowledge-Gap Detection

- **Problem class:** Investigation cannot safely continue because evidence/relationships are missing.
- **Minimal graph pattern required:** Question ABOUT Incident; Task REQUIRES Question; optional Evidence RESOLVED_BY/ABOUT Question.
- **Input:** INC-001
- **Expected system behaviour:** Surface unresolved questions required by active tasks/claims and rank them by blocking value.
- **Expected FalkorDB traversal/query behaviour:** Find OPEN Question nodes connected to incident and tasks; test whether resolving evidence exists.
- **Expected output:** List of unresolved question IDs, blockers and what depends on each.
- **Pass condition:** Q-001..Q-004 remain explicit until evidence resolves them; closed questions are excluded.
- **Failure condition:** Unknowns exist only in prose or disappear when a task changes state.
- **Graph Necessity Test:** Remove Question/REQUIRES structure; system can no longer compute which missing fact blocks work.

## T1.5 — Structural Precedent Reasoning

- **Problem class:** Past cases use different words but share the same relationship motif.
- **Minimal graph pattern required:** Incident motifs composed of Change->System, dependency edges, evidence and failure sequence.
- **Input:** INC-001
- **Expected system behaviour:** Compare graph structure against historical incidents without relying on shared vocabulary.
- **Expected FalkorDB traversal/query behaviour:** Extract bounded typed subgraphs/motifs and compare structural signatures before any semantic text rerank.
- **Expected output:** Ranked historical incidents with matched motif edges and structural score.
- **Pass condition:** INC-074 is returned as a high structural match despite different names/terms.
- **Failure condition:** Only keyword overlap drives the result, or INC-074 is missed because names differ.
- **Graph Necessity Test:** Flatten edges to documents; structural match should no longer be computable.

## T1.6 — Constraint-Aware Graph Planning

- **Problem class:** Remediation steps must respect dependencies, policy and approvals.
- **Minimal graph pattern required:** Action/Task REQUIRES prerequisites; BLOCKED_BY dependencies; Policy GOVERNS/REQUIRES Action; System dependency graph.
- **Input:** target state: recover INC-001
- **Expected system behaviour:** Produce an executable partial order, not merely a prose list.
- **Expected FalkorDB traversal/query behaviour:** Traverse prerequisite/dependency/policy edges and topologically order eligible actions.
- **Expected output:** Ordered/partially ordered action plan with blockers and required approvers.
- **Pass condition:** No action appears before its graph prerequisites and policy-required approvals.
- **Failure condition:** Plan proposes an action that violates a REQUIRES/BLOCKED_BY/GOVERNS constraint.
- **Graph Necessity Test:** Remove constraint edges; planner should lose the ability to prove the sequence is valid.

## T1.7 — Counterfactual Intervention Simulation

- **Problem class:** Need to estimate consequences of changing/removing an edge/node before acting.
- **Minimal graph pattern required:** Dependency subgraph + candidate intervention (edge/node state change).
- **Input:** remove MIG-203 effect or rollback dependency
- **Expected system behaviour:** Compute reachability/constraint differences between baseline and hypothetical graph without mutating canonical state.
- **Expected FalkorDB traversal/query behaviour:** Read baseline subgraph, apply intervention in an isolated in-memory representation or temporary graph, recompute affected paths.
- **Expected output:** Delta: paths removed/created, systems no longer exposed, constraints newly satisfied/violated.
- **Pass condition:** Rollback intervention removes the incompatible-change path while preserving unrelated dependencies.
- **Failure condition:** Canonical graph is mutated or result is a language-model guess without graph recomputation.
- **Graph Necessity Test:** Without dependency/change edges, baseline and counterfactual become indistinguishable.

## T1.8 — Graph Anomaly & Motif-Deviation Detection

- **Problem class:** The relationship pattern itself violates normal architecture/process structure.
- **Minimal graph pattern required:** Observed graph motif + reference/expected motif; e.g. UI->API->DB plus unexpected UI->DB.
- **Input:** SCN-ANOM-001
- **Expected system behaviour:** Flag typed-edge deviations with the exact abnormal edge/path.
- **Expected FalkorDB traversal/query behaviour:** Compare local neighborhood/motif frequencies or explicit allowed patterns.
- **Expected output:** Anomaly containing SYS-ANALYTICS-UI -> DEPENDS_ON -> SYS-PROD-ORDERS-DB and rationale.
- **Pass condition:** Exact shadow dependency is flagged; normal API-mediated edges are not.
- **Failure condition:** Only unusual text/properties are flagged or normal edges trigger equally.
- **Graph Necessity Test:** Remove typed edges; motif anomaly disappears because topology is no longer represented.

## T1.9 — Relational Entity Resolution

- **Problem class:** Two source records may represent the same canonical entity but confidence is uncertain.
- **Minimal graph pattern required:** SourceRecord REPRESENTS Entity for accepted mappings; CANDIDATE_MATCH Entity with confidence/status for unresolved ones.
- **Input:** SRCREC-CRM-42 and SRCREC-HR-991
- **Expected system behaviour:** Preserve ambiguous candidates until threshold/evidence supports promotion; never silently merge.
- **Expected FalkorDB traversal/query behaviour:** Traverse source records, neighboring team/system relationships and candidate mappings; compare relational consistency.
- **Expected output:** Accepted mapping for HR record; unresolved 0.72 candidate for CRM record.
- **Pass condition:** HR maps to PERSON-RIYA; CRM candidate remains unresolved rather than auto-merging.
- **Failure condition:** Ambiguous record is merged solely on name similarity or candidate provenance is lost.
- **Graph Necessity Test:** Remove relational context/mapping edges; resolution loses graph evidence and degrades to string matching.

## T1.10 — Active Evidence Acquisition & Tool Routing

- **Problem class:** The graph knows what is missing and where/tool to query next.
- **Minimal graph pattern required:** Question REQUIRES DataSource/Tool; Tool QUERIES DataSource; DataSource owns authoritative scope.
- **Input:** Q-001 or Q-003
- **Expected system behaviour:** Select the source/tool that can resolve the specific missing fact and record acquired evidence back to graph.
- **Expected FalkorDB traversal/query behaviour:** Traverse Question -> required source/tool and source authority scope; later link Evidence DERIVED_FROM DataSource.
- **Expected output:** Chosen tool/source plus expected evidence type and unresolved question ID.
- **Pass condition:** Compatibility-test question routes to deployment/code evidence source, version question routes to logs/deploy data.
- **Failure condition:** Tool is selected without graph relation/authority context.
- **Graph Necessity Test:** Delete Question/source/tool relationships; routing becomes unguided despite available tools.

## T2.1 — Persistent Multi-Agent Blackboard

- **Problem class:** Multiple agents must share durable structured work state.
- **Minimal graph pattern required:** Incident/Project <-ABOUT- Task/Question/Claim; Task ASSIGNED_TO Agent; Evidence SUPPORTS Claim.
- **Input:** INC-001
- **Expected system behaviour:** Read/write the same task, claim, question and evidence graph across sessions.
- **Expected FalkorDB traversal/query behaviour:** Query current Task/Question/Claim state from FalkorDB; mutations create typed nodes/edges and ledger events.
- **Expected output:** Durable blackboard snapshot with active tasks, owners, findings and unresolved questions.
- **Pass condition:** Restarting application does not lose graph work state; two agents see the same persisted entities.
- **Failure condition:** State lives only in process memory/chat transcript.
- **Graph Necessity Test:** Stop FalkorDB; blackboard state becomes unavailable and coordination cannot reconstruct work.

## T2.2 — Governed Agent Action

- **Problem class:** An agent may know an action but lack authority/approval.
- **Minimal graph pattern required:** Action ABOUT resource; Policy GOVERNS resource/action; Policy REQUIRES approval; Action APPROVED_BY actor.
- **Input:** proposed production restart/rollback
- **Expected system behaviour:** Return ALLOWED/BLOCKED/APPROVAL_REQUIRED with path-based justification.
- **Expected FalkorDB traversal/query behaviour:** Traverse action->resource, governing policy, required approver/owner, and approval evidence before execution.
- **Expected output:** Decision with required approver(s), unmet conditions and evidence path.
- **Pass condition:** High-impact action is blocked until required approval edge/event exists.
- **Failure condition:** Action executes despite a missing mandatory approval.
- **Graph Necessity Test:** Delete policy/ownership/approval edges; authorization answer must become indeterminate rather than default-allow.

## T2.3 — Resumable Agent Execution

- **Problem class:** Work must continue after crash/restart without repeating completed steps.
- **Minimal graph pattern required:** Task + Checkpoint PART_OF Task; Event ledger records completed work/evidence/action.
- **Input:** TASK-INVESTIGATE-INC001 after simulated worker restart
- **Expected system behaviour:** Resume from latest valid checkpoint and skip completed event-backed steps.
- **Expected FalkorDB traversal/query behaviour:** Read Task state, newest Checkpoint, prior Events and produced artifacts from FalkorDB.
- **Expected output:** Resume cursor + completed step IDs + remaining work.
- **Pass condition:** Completed steps are not rerun and previously created evidence/claims remain referenced.
- **Failure condition:** Workflow restarts from zero or relies on a process-local checkpoint.
- **Graph Necessity Test:** Remove checkpoint/event relationships; safe continuation point cannot be derived.

## T2.4 — Branch-and-Merge Agent Memory

- **Problem class:** Parallel hypotheses must not contaminate canonical truth before validation.
- **Minimal graph pattern required:** WorkBranch DERIVED_FROM parent; Hypothesis/Claim PART_OF WorkBranch; SUPERSEDES/merge result when promoted.
- **Input:** two competing root-cause branches
- **Expected system behaviour:** Keep branch-local findings isolated, detect conflicts on merge, promote only validated artifacts.
- **Expected FalkorDB traversal/query behaviour:** Query artifacts by branch; compare outgoing claims/evidence; create explicit merge/promotion edges/events.
- **Expected output:** Branch A/B states, conflicts, promoted IDs, rejected-but-preserved IDs.
- **Pass condition:** Rejected branch remains auditable; only validated claims appear in canonical shared view.
- **Failure condition:** Speculative claim appears canonical before merge or rejected evidence is deleted.
- **Graph Necessity Test:** Remove branch membership edges; system cannot distinguish speculative from canonical memory.

## T2.5 — Agent Deadlock & Contention Detection

- **Problem class:** Agents/tasks can form wait cycles or compete for one work item/resource.
- **Minimal graph pattern required:** Task BLOCKED_BY Task; Task ASSIGNED_TO/CLAIMED_BY Agent; optional resource claims.
- **Input:** SCN-AGENT-001
- **Expected system behaviour:** Detect cycles/contention and name the smallest blocking cycle/resource.
- **Expected FalkorDB traversal/query behaviour:** Cycle detection over BLOCKED_BY/REQUIRES; duplicate active claim query over task/resource.
- **Expected output:** Deadlock cycle TASK-A -> TASK-B -> TASK-A and involved agents.
- **Pass condition:** Exact cycle is reported; acyclic blocked chains are not falsely labeled deadlocked.
- **Failure condition:** Cycle exists but system only reports generic blocked state.
- **Graph Necessity Test:** Remove BLOCKED_BY/claim edges; deadlock topology cannot be detected.

## T2.6 — Handoff Contract Validation

- **Problem class:** Receiving agent must get required fields/evidence/context before ownership transfer.
- **Minimal graph pattern required:** Handoff HANDOFF_FOR Task; Handoff REQUIRES artifacts/Questions; ASSIGNED_TO receiver; provenance edges.
- **Input:** HANDOFF-A-B
- **Expected system behaviour:** Validate required artifacts, evidence provenance, unresolved blockers and receiver capability before completion.
- **Expected FalkorDB traversal/query behaviour:** Traverse Handoff requirements, linked outputs/evidence, Task blockers and receiver Agent.
- **Expected output:** VALID/INVALID plus exact missing contract items.
- **Pass condition:** HANDOFF-A-B is INVALID because evidence_ids is missing.
- **Failure condition:** Handoff marked complete when a mandatory artifact is absent.
- **Graph Necessity Test:** Remove Handoff requirement edges/properties; validation loses objective contract state.

## T2.7 — Exactly-Once Action Coordination

- **Problem class:** Retries/concurrent agents must not duplicate one real-world side effect.
- **Minimal graph pattern required:** Action with stable idempotency_key; execution Event ABOUT Action; optional unique constraint/lease later.
- **Input:** restart:SYS-PRICING-API:INC-001
- **Expected system behaviour:** Create/reserve one logical Action and refuse second execution after terminal execution event.
- **Expected FalkorDB traversal/query behaviour:** Lookup Action by idempotency_key before mutation; write execution event atomically/with future lock discipline.
- **Expected output:** first attempt EXECUTE, second attempt ALREADY_EXECUTED/NOOP.
- **Pass condition:** Two concurrent/retried requests produce one terminal action execution record.
- **Failure condition:** Duplicate terminal execution events exist for same idempotency key.
- **Graph Necessity Test:** Remove Action identity/event graph; system cannot determine whether side effect already occurred.

## T2.8 — Dependency-Preserving Memory Compaction

- **Problem class:** Long-running graph memory must shrink without deleting facts needed by downstream work/audit.
- **Minimal graph pattern required:** Checkpoint summary DERIVED_FROM Events/Claims/Evidence/Tasks; live Tasks REQUIRES referenced artifacts.
- **Input:** old completed incident work
- **Expected system behaviour:** Compact only nodes not required by active dependency paths; keep provenance references to summarized material.
- **Expected FalkorDB traversal/query behaviour:** Compute reverse dependency closure from active tasks/open questions/decisions, then compact outside closure with explicit derivation links.
- **Expected output:** Compaction manifest: retained IDs, summarized IDs, protected dependency closure.
- **Pass condition:** Every active task can still reach all prerequisite claims/evidence after compaction.
- **Failure condition:** Compaction deletes an artifact required by an active task or severs provenance.
- **Graph Necessity Test:** Without dependency edges, safe-to-compact set cannot be proven.

## T3.1 — Conflict-Aware Organizational Memory

- **Problem class:** Organization contains multiple competing versions of reality.
- **Minimal graph pattern required:** Claim ABOUT same subject; Claim CONTRADICTS Claim; Evidence SUPPORTS/REFUTES each claim.
- **Input:** INC-001
- **Expected system behaviour:** Store disagreement side-by-side; never overwrite earlier claim merely because another claim arrives.
- **Expected FalkorDB traversal/query behaviour:** Query claims by subject and explicit contradiction/evidence paths.
- **Expected output:** Both C-001 and C-002 with confidence, actors, evidence and contradiction link.
- **Pass condition:** Both claims remain queryable and conflict is explicit.
- **Failure condition:** One claim overwrites/deletes the other.
- **Graph Necessity Test:** Remove Claim/CONTRADICTS edges; organizational disagreement collapses into unstructured text.

## T3.2 — Graph-Based Authority / Contradiction Resolution

- **Problem class:** Conflicting claims require explainable authority/evidence resolution.
- **Minimal graph pattern required:** Claim ASSERTED_BY Person; Person RESPONSIBLE_FOR/Team OWNS subject; Policy GOVERNS scope; Evidence SUPPORTS/REFUTES.
- **Input:** C-001 vs C-002
- **Expected system behaviour:** Score/resolve based on authority scope, recency and evidence while preserving losing claim.
- **Expected FalkorDB traversal/query behaviour:** Traverse actor->ownership/responsibility, policy and evidence paths; compare temporal validity/confidence.
- **Expected output:** Preferred claim + explanation path + unresolved caveats.
- **Pass condition:** Resolution cites specific authority/evidence paths; losing claim remains preserved.
- **Failure condition:** Result is based only on LLM confidence or deletes losing claim.
- **Graph Necessity Test:** Remove ownership/policy/evidence edges; authority resolution must become weaker/indeterminate.

## T3.3 — Responsibility and Expertise Routing

- **Problem class:** Need to identify owner, responsible people and experienced experts for work.
- **Minimal graph pattern required:** Team OWNS System; Person MEMBER_OF Team; Person RESPONSIBLE_FOR/EXPERT_IN System/Change.
- **Input:** SYS-PRICING-DB incident task
- **Expected system behaviour:** Return distinct formal owner, responsible people and ranked experts.
- **Expected FalkorDB traversal/query behaviour:** Traverse OWNS/MEMBER_OF/RESPONSIBLE_FOR/EXPERT_IN with current temporal validity.
- **Expected output:** Pricing Platform owner; Riya as DB expert; relevant responsible people.
- **Pass condition:** Owner/expert roles are not conflated and current edges exclude dissolved ownership.
- **Failure condition:** Returns dissolved Growth ownership as current or treats any team member as expert.
- **Graph Necessity Test:** Remove org edges; routing cannot infer correct people from system identity alone.

## T3.4 — Organizational Process Reconstruction

- **Problem class:** Company must infer how work actually happened from events across systems.
- **Minimal graph pattern required:** Event ABOUT artifacts/tasks/actions; BEFORE ordering; PERFORMED_BY actors.
- **Input:** DPL-882 / INC-001
- **Expected system behaviour:** Reconstruct actual event sequence and actors from recorded events, not from a declared workflow document.
- **Expected FalkorDB traversal/query behaviour:** Collect related events and order by occurred_at/BEFORE; traverse actors/artifacts.
- **Expected output:** Ordered process trace with event IDs, actors and artifacts.
- **Pass condition:** Trace shows deployment before errors/retries/CPU spike and preserves all source events.
- **Failure condition:** Sequence is guessed from final state or timestamps are ignored.
- **Graph Necessity Test:** Remove event history; process reconstruction becomes impossible from current state alone.

## T3.5 — Policy-vs-Practice Drift Detection

- **Problem class:** Actual workflow can skip required policy steps.
- **Minimal graph pattern required:** Policy GOVERNS Change; Policy REQUIRES Action; Event history shows executed/skipped actions.
- **Input:** POL-DB-04 + DPL-882
- **Expected system behaviour:** Compare expected required-step graph to observed event/action graph and report missing/extra/order violations.
- **Expected FalkorDB traversal/query behaviour:** Traverse policy requirements then anti-join against execution events/actions for governed deployment/change.
- **Expected output:** Missing compatibility test and downstream verification; approval present.
- **Pass condition:** Flags the two missing required steps without falsely flagging Arjun approval.
- **Failure condition:** Reports compliant merely because policy document exists.
- **Graph Necessity Test:** Remove policy requirement or event edges; drift cannot be computed as a graph difference.

## T3.6 — Organizational Bus-Factor Analysis

- **Problem class:** Critical capability depends on too few people.
- **Minimal graph pattern required:** Person EXPERT_IN/RESPONSIBLE_FOR critical System; Team OWNS System; backup paths.
- **Input:** SYS-LEDGER-EXPORT
- **Expected system behaviour:** Count independent qualified people/paths and identify single points of knowledge/authority.
- **Expected FalkorDB traversal/query behaviour:** Neighborhood/path analysis over expertise, responsibility and ownership edges.
- **Expected output:** bus_factor=1, only expert PERSON-ISHA, no backup.
- **Pass condition:** Correctly reports 1 for support scenario and does not count unrelated team members.
- **Failure condition:** Counts nominal team size rather than expertise/responsibility relationships.
- **Graph Necessity Test:** Remove expertise/responsibility edges; key-person risk cannot be computed.

## T3.7 — Duplicate-Work / Initiative Collision Detection

- **Problem class:** Different teams unknowingly build overlapping initiatives.
- **Minimal graph pattern required:** Project nodes share goal/system/resource dependencies; owned by different teams.
- **Input:** SCN-DUP-001
- **Expected system behaviour:** Find projects with high structural overlap in goals/dependencies/resources and explain overlap.
- **Expected FalkorDB traversal/query behaviour:** Compare project neighborhoods and dependency intersections; text similarity may only supplement.
- **Expected output:** PROJ-REFUND-A and PROJ-REFUND-B flagged with shared Refund API and same goal.
- **Pass condition:** Exact pair is flagged with graph overlap evidence.
- **Failure condition:** Only title similarity is used or shared dependencies are ignored.
- **Graph Necessity Test:** Remove project dependency/ownership edges; collision evidence becomes materially weaker.

## T3.8 — Organizational Bottleneck & Bridge Detection

- **Problem class:** One person/team connects otherwise weakly connected organizational regions.
- **Minimal graph pattern required:** People/Teams/Projects connected by MEMBER_OF, RESPONSIBLE_FOR, DEPENDS_ON/approval paths.
- **Input:** SCN-BRIDGE-001
- **Expected system behaviour:** Identify articulation-like nodes/bridges whose removal disconnects important workflow paths.
- **Expected FalkorDB traversal/query behaviour:** Compute connectivity before/after candidate removal in scoped org/process graph.
- **Expected output:** PERSON-DEV flagged as bridge with disconnected Platform->Security review path.
- **Pass condition:** Removal test demonstrates the claimed disconnection.
- **Failure condition:** High-degree nodes are labeled bottlenecks without testing connectivity impact.
- **Graph Necessity Test:** Remove relational graph; bridge property is undefined.

## T3.9 — Commitment and Obligation Tracking

- **Problem class:** Promises can become due/violated without an explicit ticket state update.
- **Minimal graph pattern required:** Commitment PROMISED_BY actor, OWED_TO recipient, COMMITTED_TO subject; due_at/status; outcome Events.
- **Input:** COM-017 or COM-099 at a time
- **Expected system behaviour:** Determine active/due/overdue/violated/satisfied state from graph-linked obligation and outcomes.
- **Expected FalkorDB traversal/query behaviour:** Traverse promisor/recipient/subject and compare due time with satisfaction/violation evidence events.
- **Expected output:** Commitment state plus responsible party, recipient, subject and evidence.
- **Pass condition:** COM-099 is overdue with no satisfaction event; COM-017 can be linked to compatibility breach evidence later.
- **Failure condition:** Commitment exists only as text and cannot be tied to owner/recipient/outcome.
- **Graph Necessity Test:** Remove commitment relationship graph; obligation accountability cannot be computed.

## T3.10 — Ownership-Gap / Orphaned-Resource Detection

- **Problem class:** Active resources can outlive their owning team/relationship.
- **Minimal graph pattern required:** Active System with no temporally valid incoming OWNS; historical owner edge retained with valid_until.
- **Input:** SYS-LEGACY-PROMO at 2026-10-16
- **Expected system behaviour:** Report orphan while preserving former owner/history.
- **Expected FalkorDB traversal/query behaviour:** Anti-match current OWNS edge with temporal validity; optionally return expired ownership history.
- **Expected output:** current_owner=null, historical_owner=TEAM-GROWTH, expired=2026-07-01.
- **Pass condition:** Legacy Promotion Adapter is flagged orphaned and historical ownership remains queryable.
- **Failure condition:** Dissolved team is returned as current owner or old ownership edge was deleted.
- **Graph Necessity Test:** Remove OWNS/history edges; system cannot distinguish orphan from unknown metadata.


# Phase 5 — Reasoning → Structured Work Acceptance Matrix

The Phase 5 contracts extend, rather than replace, the Phase 1 Track 1 acceptance matrix. They consume the already-implemented reasoning capabilities and require their outputs to become durable work in FalkorDB.

## P5.27 — Deterministic Work Planner

- **Problem class:** Reasoning identifies gaps, conflicts and constrained remedies but does not turn them into executable work structure.
- **Minimal graph pattern required:** Situation/Incident connected to Questions, Claims, Evidence, explicit contradictions, Actions, Policies and existing reasoning paths.
- **Input:** `INC-001` + a goal.
- **Expected behaviour:** Derive typed tasks (`ACQUIRE_EVIDENCE`, `INVESTIGATE`, `RESOLVE_CONFLICT`, `PREPARE_ACTION`, `VALIDATE_POLICY`, and `REQUEST_APPROVAL` only when an unmet approval actually exists).
- **Pass condition:** Unresolved Q-001..Q-004 create typed work; C-001/C-002 create conflict-resolution work; selected remediation/policy structure creates downstream preparation/validation work.
- **Failure condition:** Planner emits only prose, rediscovers reasoning with unrelated heuristics, hardcodes INC-001 IDs, or creates an approval task despite a valid current approval.
- **Graph necessity:** Removing the graph relation that establishes a gap/conflict/policy requirement changes the generated task graph.

## P5.28 — Persisted Plan / Task Graph

- **Problem class:** A transient Python checklist cannot support readiness, provenance, replay or later coordination.
- **Minimal graph pattern required:** `Plan -[:PLAN_HAS_TASK]-> Task`, task-to-task `REQUIRES`, task `ADDRESSES` / `ABOUT` source entities, task `REQUIRES` source/tool entities, and candidate actors `CANDIDATE_FOR` tasks.
- **Expected behaviour:** Persist deterministic Plan/Task IDs, task purpose/output/completion metadata, explicit prerequisite edges and creation-ledger events.
- **Pass condition:** Repeating the same situation + goal + unchanged graph state reuses the same Plan and semantic tasks; cross-Plan Task reuse occurs only when a deterministic structural signature (targets, requirements and prerequisites included) matches, so one Plan cannot rewrite another Plan’s task structure.
- **Failure condition:** Tasks live only in memory/JSON, prerequisites live only in prose, cycles are accepted, or recomputation retains stale planner-owned prerequisite edges.
- **Graph necessity:** Removing a task `REQUIRES` edge changes readiness/order; a cycle in task `REQUIRES` is rejected.

## P5.29 — Candidate Worker Routing

- **Problem class:** Work needs qualified candidates without conflating technical expertise, formal ownership, responsibility and approval authority.
- **Minimal graph pattern required:** existing Phase 3 `OWNS`, `RESPONSIBLE_FOR`, `EXPERT_IN`, `MEMBER_OF`, `APPROVED_BY` plus task target/purpose.
- **Expected behaviour:** Reuse `ResponsibilityRoutingService`, then apply task-purpose weighting; persist ranked `Person|Team|Agent|Tool -[:CANDIDATE_FOR]-> Task` explanations without permanent assignment.
- **Pass condition:** Pricing Database diagnosis ranks Riya strongly because of `EXPERT_IN`; authority-oriented work prefers owner/responsible paths; Tool candidates come from the existing Question→Tool/DataSource route.
- **Failure condition:** Planner creates a second ownership/expertise algorithm, blindly assigns one worker, or treats team membership as expertise.
- **Graph necessity:** Removing Riya's `EXPERT_IN` edge changes her candidate ranking for Pricing Database technical work.

# Phase 6 implementation verification addendum

The Track 2 acceptance definitions above are now backed by Phase 6 implementation/tests as follows. The original problem definitions are retained unchanged.

| Capability | Phase 6 implementation | Primary real-FalkorDB proof |
|---|---|---|
| T2.1 Persistent Multi-Agent Blackboard | `CoordinationService`, persisted Agent/Execution/Checkpoint/Finding/Blocker/Handoff/WorkBranch/Action state | restart reconstruction; shared Finding/Evidence; removing Finding->Task removes it from shared state |
| T2.2 Governed Agent Action | `GovernanceService` + `ActionCoordinationService` | ownership/policy/approval/evidence checks; policy denial prevents mock invocation |
| T2.3 Resumable Agent Execution | Execution + structured Checkpoints + cross-agent resume | steps 1/2 persisted, resumed worker starts at step 3; ineligible worker denied |
| T2.4 Branch-and-Merge Agent Memory | `BranchMemoryService` | branch-local Findings isolated; validated merge promotes with provenance; rejected branch retained |
| T2.5 Deadlock & Contention Detection | `CoordinationRiskService` + deterministic resource leases | dependency-cycle edge removal removes deadlock; expired lease/conflicting owner/starvation/resource contention tests |
| T2.6 Handoff Contract Validation | `HandoffService` | structured positive/negative evidence/confidence/blocker tests; artifact-edge deletion invalidates handoff |
| T2.7 Exactly-Once Action Coordination | deterministic action/attempt IDs, idempotency key, conditional attempt state, per-resource lease, mock idempotent sink | duplicate/concurrent duplicate invocation count=1; crash windows; `UNKNOWN` rather than blind retry |
| T2.8 Dependency-Preserving Memory Compaction | `MemoryCompactionService` | old Checkpoints archived while Evidence/Decision/Branch/Action lineage remains; broken lineage fails validation |

Phase 6 also adds an explicit terminal execution transition: completion is allowed only when the current Task owner has no unresolved blocker and the existing Phase 5 graph-backed completion predicate is satisfied. This preserves Phase 5 semantics rather than allowing an agent to mark arbitrary work complete.

# Phase 8 implementation mapping

| Capability | Deterministic engine | Canonical/support fixture | Objective tests |
|---|---|---|---|
| T3.4 Organizational Process Reconstruction | `OrganizationalProcessReconstructionService` | INC-001 + explicit `TRIGGERED` support edge | workflow/order/trigger/dependency/causality/ambiguity/provenance + FalkorDB necessity |
| T3.5 Policy-vs-Practice Drift | `PolicyDriftService` | POL-DB-04 / INC-001 | expected/observed graph, missing controls, order, approval, evidence, actor/control/version tests |
| T3.9 Commitment Tracking | `CommitmentTrackingService` | COM-017, COM-099 | open/fulfilled/breached/overdue/parties/provenance/consequence/history tests |
| T3.7 Initiative Collision | `InitiativeCollisionService` | PROJ-REFUND-A/B/C | high/negative/collaboration/explainability/removal-score tests |
| T3.6 Bus Factor | `BusFactorService` | PERSON-ISHA / SYS-LEDGER-EXPORT | sole/redundant expertise, authority/capability, non-mutating loss, historical tests |
| T3.8 Bottleneck & Bridge | `OrganizationalNetworkAnalysisService` | PERSON-DEV / teams / release project | articulation/bridge/redundancy/centrality/overload/single-path/projection tests |
