# Example Cypher Queries and Expected Outputs

The Python service uses parameterized equivalents. These examples are useful in FalkorDB Browser.

## 1. Checkout dependencies

```cypher
MATCH p=(c:Entity:System {tenant_id:'northstar', id:'SYS-CHECKOUT'})-[:DEPENDS_ON*1..3]->(d:Entity:System)
RETURN d.id, d.name, length(p) AS depth
ORDER BY depth, d.id;
```

Expected to include direct `SYS-PRICING-API`, `SYS-ORDER`, `SYS-INVENTORY` and indirect `SYS-PRICING-DB`.

## 2. Pricing Database potential blast radius

```cypher
MATCH p=(db:Entity:System {tenant_id:'northstar', id:'SYS-PRICING-DB'})<-[:DEPENDS_ON*1..4]-(consumer:Entity:System)
RETURN DISTINCT consumer.id, consumer.name, length(p) AS depth
ORDER BY depth, consumer.id;
```

Expected set includes `SYS-PRICING-API`, `SYS-PRICING-ANALYTICS`, `SYS-CHECKOUT`, `SYS-MOBILE-OFFERS`, and `SYS-LEGACY-PROMO`. Reachability means **potential** impact, not automatically observed failure.

## 3. Current owner vs historical owner

Current:
```cypher
MATCH (owner:Entity)-[r:OWNS]->(s:Entity:System {tenant_id:'northstar', id:'SYS-LEGACY-PROMO'})
WHERE r.valid_until IS NULL
RETURN owner.id, owner.name;
```
Expected: no row.

Historical at 2026-06-01:
```cypher
MATCH (owner:Entity)-[r:OWNS]->(s:Entity:System {tenant_id:'northstar', id:'SYS-LEGACY-PROMO'})
WHERE (r.valid_from IS NULL OR r.valid_from <= '2026-06-01T00:00:00+05:30')
  AND (r.valid_until IS NULL OR r.valid_until > '2026-06-01T00:00:00+05:30')
RETURN owner.id, owner.name;
```
Expected: `TEAM-GROWTH`, Growth Integrations Team.

## 4. Conflicting incident claims

```cypher
MATCH (a:Entity:Claim)-[:ABOUT]->(:Entity:Incident {tenant_id:'northstar', id:'INC-001'})
MATCH (a)-[:CONTRADICTS]-(b:Entity:Claim)
RETURN DISTINCT a.id, a.statement, b.id, b.statement;
```
Expected conflict: `C-001` vs `C-002`.

## 5. Evidence and provenance for C-002

```cypher
MATCH (e:Entity:Evidence)-[:SUPPORTS]->(c:Entity:Claim {tenant_id:'northstar', id:'C-002'})
OPTIONAL MATCH (e)-[:DERIVED_FROM]->(src:Entity:DataSource)
RETURN e.id, e.name, src.id, src.name, e.confidence
ORDER BY e.id;
```
Expected support includes `E-001`, `E-002`, `E-003`, `E-006` with their source systems.

## 6. Incident timeline

```cypher
MATCH (ev:Entity:Event)-[:ABOUT]->(:Entity:Incident {tenant_id:'northstar', id:'INC-001'})
RETURN ev.id, ev.event_type, ev.occurred_at, ev.summary
ORDER BY ev.occurred_at, ev.id;
```
Expected order includes incident open -> v4.1 errors -> retry rise -> CPU 91%.

## 7. Open knowledge gaps

```cypher
MATCH (q:Entity:Question {tenant_id:'northstar', status:'OPEN'})-[:ABOUT]->(:Entity:Incident {id:'INC-001'})
RETURN q.id, q.text, q.priority
ORDER BY q.id;
```
Expected: `Q-001` through `Q-004`.

# Phase 3 Browser Queries

These are Browser-safe read examples for the implemented Company Brain capabilities. The application uses parameterized equivalents and adds deterministic scoring/status logic in Python services.

## 8. Claims, actors, and explicit contradiction for INC-001

```cypher
MATCH (c:Entity:Claim {tenant_id:'northstar'})-[:ABOUT]->
      (i:Entity:Incident {tenant_id:'northstar', id:'INC-001'})
OPTIONAL MATCH (c)-[:ASSERTED_BY]->(actor:Entity)
OPTIONAL MATCH (c)-[:CONTRADICTS]-(other:Entity:Claim)
RETURN c.id, c.statement, c.status, actor.id, other.id
ORDER BY c.created_at, c.id;
```

Expected: C-001 asserted by PERSON-ARJUN and C-002 asserted by PERSON-RIYA, with the contradiction visible between them.

## 9. Separate evidence/source provenance for each claim

```cypher
MATCH (e:Entity:Evidence)-[r:SUPPORTS|REFUTES]->
      (c:Entity:Claim {tenant_id:'northstar'})-[:ABOUT]->
      (:Entity:Incident {tenant_id:'northstar', id:'INC-001'})
OPTIONAL MATCH (e)-[:DERIVED_FROM]->(src:Entity:DataSource)
RETURN c.id, type(r), e.id, e.confidence, r.confidence, src.id, src.authoritative
ORDER BY c.id, e.id;
```

Expected: E-004 supports C-001; E-001/E-002/E-003/E-006 support C-002. Evidence is not moved from one claim to the other.

## 10. Authority paths through responsibility and ownership

```cypher
MATCH (c:Entity:Claim {tenant_id:'northstar', id:'C-002'})-[:ASSERTED_BY]->(actor:Entity:Person)
MATCH (e:Entity:Evidence)-[:SUPPORTS]->(c)-[:ABOUT]->(:Entity:Incident {id:'INC-001'})
MATCH (e)-[:ABOUT]->(ctx:Entity)
OPTIONAL MATCH (actor)-[resp:RESPONSIBLE_FOR]->(ctx)
OPTIONAL MATCH (actor)-[:MEMBER_OF]->(team:Entity:Team)-[own:OWNS]->(ctx)
OPTIONAL MATCH (actor)-[expert:EXPERT_IN]->(ctx)
RETURN actor.id, ctx.id, team.id, resp.confidence, own.confidence, expert.confidence
ORDER BY ctx.id;
```

The application also expands evidence-about-Change paths through `CHANGED/AFFECTS`, evaluates policy `GOVERNS`, approvals, temporal validity, evidence/source authority, and can return `UNRESOLVED` if the score/evidence/margin rules are not met.

## 11. Current owner with temporal validity

```cypher
MATCH (owner:Entity)-[r:OWNS]->
      (s:Entity:System {tenant_id:'northstar', id:'SYS-LEGACY-PROMO'})
WHERE (r.valid_from IS NULL OR r.valid_from <= '2026-10-16T17:00:00+05:30')
  AND (r.valid_until IS NULL OR r.valid_until > '2026-10-16T17:00:00+05:30')
RETURN owner.id, owner.status, r.valid_from, r.valid_until;
```

Expected: no temporally valid current owner.

Historical check:

```cypher
MATCH (owner:Entity)-[r:OWNS]->
      (s:Entity:System {tenant_id:'northstar', id:'SYS-LEGACY-PROMO'})
RETURN owner.id, owner.name, r.valid_from, r.valid_until
ORDER BY r.valid_from DESC;
```

Expected history includes TEAM-GROWTH ending 2026-07-01.

## 12. Responsibility is not expertise

```cypher
MATCH (actor:Entity)-[r:RESPONSIBLE_FOR]->
      (s:Entity:System {tenant_id:'northstar', id:'SYS-PRICING-API'})
RETURN actor.id, actor.name, r.confidence;
```

Expected: PERSON-ARJUN.

```cypher
MATCH (person:Entity:Person)-[r:EXPERT_IN]->
      (s:Entity:System {tenant_id:'northstar', id:'SYS-PRICING-DB'})
RETURN person.id, person.name, r.confidence
ORDER BY r.confidence DESC;
```

Expected strongest explicit expert: PERSON-RIYA. The routing service does not infer expertise from `MEMBER_OF` alone.

## 13. Orphaned active systems with expired/no ownership

```cypher
MATCH (s:Entity:System {tenant_id:'northstar', status:'ACTIVE'})
OPTIONAL MATCH (owner:Entity)-[r:OWNS]->(s)
WITH s, owner, r,
     CASE WHEN r IS NOT NULL
               AND (r.valid_from IS NULL OR r.valid_from <= '2026-10-16T17:00:00+05:30')
               AND (r.valid_until IS NULL OR r.valid_until > '2026-10-16T17:00:00+05:30')
          THEN 1 ELSE 0 END AS current_owner_edge
WITH s, sum(current_owner_edge) AS current_owner_count
WHERE current_owner_count = 0
RETURN s.id, s.name
ORDER BY s.id;
```

Expected to include SYS-LEGACY-PROMO. The application additionally checks whether owner entities themselves are active, reconstructs historical owners, detects multiple simultaneous owners, traverses reverse `DEPENDS_ON`, and assigns a risk basis.

# Phase 4 Browser Queries

## 14. INC-001 connected investigation spine

```cypher
MATCH (inc:Entity:Incident {tenant_id:'northstar', id:'INC-001'})
MATCH (ev:Entity:Evidence)-[:ABOUT]->(inc)
MATCH (ev)-[:ABOUT]->(start:Entity:System)
MATCH p=(start)-[:DEPENDS_ON*1..4]->(db:Entity:System {id:'SYS-PRICING-DB'})
MATCH (change:Entity:Change {id:'MIG-203'})-[:CHANGED|AFFECTS]->(changed:Entity:System)
RETURN ev.id, p, change.id, changed.id;
```

The application preserves exact nodes/typed edges and scores bounded candidate paths; it does not query `ground_truth`.

## 15. Pricing DB blast radius

```cypher
MATCH p=(root:Entity:System {tenant_id:'northstar', id:'SYS-PRICING-DB'})<-[:DEPENDS_ON*1..6]-(consumer:Entity:System)
RETURN consumer.id, length(p) AS depth, p
ORDER BY depth, consumer.id;
```

Expected reachable consumers include Pricing API, Checkout, Mobile Offers, Legacy Promotion Adapter, and Pricing Analytics. `OBSERVED` impact is assigned only when incident-linked Evidence also exists for that system.

## 16. Explicit knowledge gaps and blockers

```cypher
MATCH (q:Entity:Question {tenant_id:'northstar'})-[:ABOUT]->(:Entity:Incident {id:'INC-001'})
OPTIONAL MATCH (work:Entity)-[block:REQUIRES|BLOCKED_BY]->(q)
OPTIONAL MATCH (q)-[:RESOLVED_BY]->(resolution:Entity)
RETURN q.id, q.status, type(block), work.id, resolution.id
ORDER BY q.id;
```

## 17. Tool/source routing

```cypher
MATCH (q:Entity:Question {tenant_id:'northstar', id:'Q-003'})-[:REQUIRES]->(tool:Entity:Tool)-[r:QUERIES]->(source:Entity:DataSource)
RETURN q.id, tool.id, source.id, source.authoritative, r.capability;
```

Expected sources: `DS-DEPLOY` and `DS-LOG`.

## 18. Decision genealogy

```cypher
MATCH (d:Entity:Decision {tenant_id:'northstar', id:'DEC-INC001-ROLLBACK'})-[r:BASED_ON]->(input:Entity)
OPTIONAL MATCH (d)-[:APPROVED_BY]->(approver:Entity)
OPTIONAL MATCH (producer:Entity)-[:PRODUCED]->(d)
RETURN d.id, type(r), input.id, approver.id, producer.id;
```

## 19. Structural precedent motifs

```cypher
MATCH (ev:Entity:Evidence)-[:ABOUT]->(inc:Entity:Incident)
MATCH (ev)-[:ABOUT]->(change:Entity:Change)-[r:CHANGED|AFFECTS]->(system:Entity:System)
OPTIONAL MATCH (dependent:Entity:System)-[:DEPENDS_ON]->(system)
RETURN inc.id, change.change_type, type(r), system.system_type, dependent.system_type
ORDER BY inc.id;
```

The service compares abstract typed signatures first and only then applies secondary semantic metadata scoring.

## 20. Planning constraints

```cypher
MATCH (a:Entity:Action)-[:ABOUT]->(:Entity:Incident {id:'INC-001'})
OPTIONAL MATCH (a)-[req:REQUIRES]->(pre:Entity)
OPTIONAL MATCH (a)-[:APPROVED_BY]->(approver:Entity)
RETURN a.id, a.decision_role, type(req), pre.id, approver.id
ORDER BY a.id;
```

## 21. SCN-ANOM shadow dependency

```cypher
MATCH (ui:Entity:System {id:'SYS-ANALYTICS-UI'})-[:DEPENDS_ON]->(db:Entity:System {id:'SYS-PROD-ORDERS-DB'})
MATCH p=(ui)-[:DEPENDS_ON]->(:Entity:System {id:'SYS-ANALYTICS-API'})-[:DEPENDS_ON]->(db)
RETURN ui.id, db.id, p;
```

The simultaneous direct and API-mediated paths are the deterministic `FRONTEND_DIRECT_DATABASE` motif deviation.


# Phase 5 Browser Queries

Generate a plan through FastAPI first:

```http
POST /plans
Content-Type: application/json

{
  "situation_id": "INC-001",
  "goal": "Resolve INC-001 safely with enough evidence to select remediation."
}
```

Use the returned `plan.id` in the queries below.

## 22. Plan and typed tasks

```cypher
MATCH (p:Entity:Plan {tenant_id:'northstar', id:$plan_id})-[:PLAN_HAS_TASK]->(t:Entity:Task)
RETURN p.id AS plan_id,
       p.status AS plan_status,
       t.id AS task_id,
       t.task_type AS task_type,
       t.status AS task_status,
       t.expected_output_type AS expected_output_type,
       t.completion_condition AS completion_condition
ORDER BY t.priority, t.task_type, t.id;
```

## 23. Task prerequisite graph

```cypher
MATCH (p:Entity:Plan {tenant_id:'northstar', id:$plan_id})-[:PLAN_HAS_TASK]->(t:Entity:Task)
OPTIONAL MATCH (t)-[:REQUIRES]->(pre:Entity:Task)
RETURN t.id AS task_id, t.task_type AS task_type, pre.id AS prerequisite_task_id
ORDER BY t.id, prerequisite_task_id;
```

For the INC-001 plan, the conflict-resolution task should depend on relevant evidence/investigation tasks derived from the conflicting-claim context. A task with no prerequisite is independently eligible subject to its non-task requirements.

## 24. Why each task exists

```cypher
MATCH (p:Entity:Plan {tenant_id:'northstar', id:$plan_id})-[:PLAN_HAS_TASK]->(t:Entity:Task)
OPTIONAL MATCH (t)-[:ADDRESSES]->(source:Entity)
OPTIONAL MATCH (t)-[:ABOUT]->(target:Entity)
RETURN t.id,
       t.task_type,
       t.derivation_reason,
       collect(DISTINCT source.id) AS derived_from,
       collect(DISTINCT target.id) AS about
ORDER BY t.id;
```

## 25. Evidence/source requirements

```cypher
MATCH (p:Entity:Plan {tenant_id:'northstar', id:$plan_id})-[:PLAN_HAS_TASK]->(t:Entity:Task)
OPTIONAL MATCH (t)-[:REQUIRES]->(requirement:Entity)
WHERE NOT requirement:Task
RETURN t.id,
       t.task_type,
       collect(DISTINCT {
         id: requirement.id,
         labels: labels(requirement),
         status: requirement.status
       }) AS requirements
ORDER BY t.id;
```

## 26. Candidate assignees with preserved role semantics

```cypher
MATCH (candidate:Entity)-[r:CANDIDATE_FOR]->(t:Entity:Task)
MATCH (:Entity:Plan {tenant_id:'northstar', id:$plan_id})-[:PLAN_HAS_TASK]->(t)
RETURN t.id,
       t.task_type,
       candidate.id,
       labels(candidate),
       r.score,
       r.requirement,
       r.roles,
       r.reason_summary
ORDER BY t.id, r.score DESC, candidate.id;
```

`CANDIDATE_FOR` is a recommendation edge, not an actual assignment.

## 27. Pricing Database expertise path used by routing

```cypher
MATCH (actor:Entity)-[r:EXPERT_IN|OWNS|RESPONSIBLE_FOR]->(db:Entity:System {tenant_id:'northstar', id:'SYS-PRICING-DB'})
RETURN actor.id, type(r), r.confidence, db.id
ORDER BY type(r), actor.id;
```

Deleting Riya's `EXPERT_IN` relationship must change her technical-diagnosis ranking after plan recomputation.

## 28. Planner creation events

```cypher
MATCH (e:Entity:Event {tenant_id:'northstar'})
WHERE e.event_type IN ['PLAN_CREATED', 'TASK_CREATED']
MATCH (e)-[:ABOUT]->(artifact:Entity)
OPTIONAL MATCH (e)-[:PERFORMED_BY]->(generator:Entity)
RETURN e.id, e.event_type, e.occurred_at, artifact.id, generator.id
ORDER BY e.occurred_at, e.id;
```

These are structured creation/provenance events only. Phase 5 does not write task execution, claiming, handoff or autonomous-action events.

## 29. Check for task cycles manually

```cypher
MATCH (p:Entity:Plan {tenant_id:'northstar', id:$plan_id})-[:PLAN_HAS_TASK]->(t:Entity:Task)
MATCH path=(t)-[:REQUIRES*1..]->(t)
RETURN path;
```

Expected result for a valid Phase 5 plan: **no rows**.

## 30. Planner-owned graph state for one task

```cypher
MATCH (t:Entity:Task {tenant_id:'northstar', id:$task_id})
OPTIONAL MATCH (t)-[out]->(target:Entity)
OPTIONAL MATCH (candidate:Entity)-[cand:CANDIDATE_FOR]->(t)
RETURN t,
       collect(DISTINCT {type:type(out), target:target.id}) AS outgoing_semantics,
       collect(DISTINCT {candidate:candidate.id, score:cand.score, requirement:cand.requirement}) AS candidates;
```

# Phase 6 coordination queries

For the complete Phase 6 manual demo and Browser acceptance queries, see `docs/phase6_manual_acceptance.md`.

## 31. Active Task owner and resumable execution

```cypher
MATCH (t:Entity:Task {tenant_id:'northstar', id:$task_id})
OPTIONAL MATCH (t)-[c:CLAIMED_BY]->(a:Entity:Agent)
WHERE c.valid_until IS NULL
OPTIONAL MATCH (t)-[:HAS_EXECUTION]->(e:Entity:Execution)
OPTIONAL MATCH (e)-[:HAS_CHECKPOINT]->(cp:Entity:Checkpoint)
RETURN t.id, t.status, a.id, e.id, e.status,
       collect({id:cp.id,step:cp.step_index,status:cp.status}) AS checkpoints;
```

## 32. Shared coordination state

```cypher
MATCH (t:Entity:Task {tenant_id:'northstar', id:$task_id})
OPTIONAL MATCH (f:Entity:Finding)-[:ABOUT]->(t)
OPTIONAL MATCH (ev:Entity:Evidence)-[:ABOUT]->(t)
OPTIONAL MATCH (h:Entity:Handoff)-[:HANDOFF_FOR]->(t)
OPTIONAL MATCH (t)-[:HAS_BRANCH]->(b:Entity:WorkBranch)
RETURN t.id,
       collect(DISTINCT f.id) AS findings,
       collect(DISTINCT ev.id) AS evidence,
       collect(DISTINCT h.id) AS transfers,
       collect(DISTINCT {id:b.id,status:b.status}) AS branches;
```

## 33. Action attempt and resource leases

```cypher
MATCH (t:Entity:Task {tenant_id:'northstar'})-[:PROPOSED_ACTION]->(a:Entity:Action)
OPTIONAL MATCH (a)-[:HAS_ATTEMPT]->(aa:Entity:ActionAttempt)
OPTIONAL MATCH (l:Entity:Lock)-[:LOCKS]->(resource:Entity)
WHERE l.action_id=a.id
RETURN t.id, a.id, a.status, a.idempotency_key,
       aa.id, aa.execution_state, aa.external_request_id,
       collect(DISTINCT {lock:l.id,resource:resource.id,state:l.status,lease_until:l.lease_until}) AS resource_leases;
```

# Phase 8 Company Brain analytics

```cypher
// Explicit process trigger; chronology is not enough to infer this.
MATCH (a)-[r:TRIGGERED]->(b)
WHERE a.tenant_id='northstar'
RETURN a.id, type(r), b.id
```

```cypher
// Policy requirements used for expected-process construction.
MATCH (p:Policy {id:'POL-DB-04'})-[r:REQUIRES]->(x)
RETURN p.id, x.id, x.status, r.edge_id
```

```cypher
// Commitment parties, breach/fulfillment and subject.
MATCH (c:Commitment {id:'COM-017'})-[r]->(x)
WHERE type(r) IN ['PROMISED_BY','MADE_BY','OWED_TO','COMMITTED_TO','ABOUT','SATISFIED_BY','BREACHED_BY']
RETURN c.id, type(r), x.id, labels(x)
```

```cypher
// Project neighborhoods used for collision candidate/scoring dimensions.
MATCH (p:Project)-[r:DEPENDS_ON|REQUIRES|ABOUT|AFFECTS]->(x)
RETURN p.id, type(r), x.id, labels(x)
```

```cypher
// Coverage relationships used for bus-factor analysis.
MATCH (actor)-[r:OWNS|RESPONSIBLE_FOR|EXPERT_IN]->(resource)
RETURN actor.id, type(r), resource.id, resource.criticality, r.valid_from, r.valid_until
```
