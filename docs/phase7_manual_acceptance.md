# Phase 7 Manual Acceptance

Start the API:

```powershell
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Swagger: `http://127.0.0.1:8000/docs`
FalkorDB Browser: `http://localhost:3000`

## Demo A — Learn from completed work

1. Complete a Phase 6 Task/Execution using the Phase 6 demo and record `execution_id`, `task_id`, producer agent and verifier agent.
2. Write grounded Evidence with `POST /learning/evidence`. Supply the actual Phase 6 Agent/Task/Execution IDs and `situation_id=INC-001`.
3. Create/verify a Finding with existing Phase 6 endpoints and link the Evidence.
4. Promote it with `POST /memory/findings/{finding_id}/promote`, body `{"subject_ids":["INC-001"]}`.
5. Persist any Decision genealogy with `POST /learning/decisions/{decision_id}`.
6. Persist a genuine observed Action result with `POST /learning/actions/{action_id}/outcomes`.
7. Close INC-001 only after the graph has a validated `ROOT_CAUSE`, Decision genealogy, remediation Action and observed Outcome; then call `POST /memory/incidents/INC-001/promote-precedent`.
8. Call the existing Phase 4 `GET /incidents/{later_incident}/precedents`; the learned Incident is retrieved through normal graph reasoning, not a Phase 7 list.

## Demo B — Organizational ownership change

1. Inspect current owner using `GET /entities/{system_id}/owner`.
2. Create/verify a Finding proving the new ownership.
3. Call `POST /memory/responsibility/promote`:

```json
{
  "actor_id": "TEAM-NEW",
  "resource_id": "SYS-TARGET",
  "relation_type": "OWNS",
  "verification_id": "<verified-finding-id>",
  "authority_id": "<validator-id>",
  "effective_at": "2026-10-16T15:00:00+05:30"
}
```

4. Re-run current routing. The new Team is current.
5. Query a timestamp before the change; the old Team remains reconstructable.
6. Active Tasks whose candidate path depended on the old owner show `input_status=STALE_INPUT`; parent Plans show `planning_status=REPLAN_REQUIRED`.

## Demo C — Invalidate and revalidate

1. Inspect Evidence and its supported Claim with `GET /memory/{evidence_id}/lineage`.
2. Call `POST /memory/evidence/{evidence_id}/invalidate` with `{"reason":"source corrected"}`.
3. Inspect `GET /memory/{evidence_id}/impact`: Claim -> Decision -> Task -> Plan paths are explicit.
4. Verify an unrelated Claim remains unchanged.
5. Write replacement Evidence using `/learning/evidence`, linked to the Claim with `supports_claim_ids`.
6. Call `POST /memory/claims/{claim_id}/revalidate` with the replacement Evidence ID.
7. The Claim returns to `VALIDATED`; the older invalidation Event remains queryable.

# FalkorDB Browser Cypher

All examples use tenant `northstar`.

## 1. Temporary Finding/Hypothesis

```cypher
MATCH (x:Entity {tenant_id:'northstar'})
WHERE x:Finding OR x:Hypothesis
RETURN labels(x), x.id, x.status, x.statement, x.confidence, x.created_at
ORDER BY x.created_at DESC
LIMIT 20
```

## 2. Validation and Evidence lineage

```cypher
MATCH (x:Entity {tenant_id:'northstar'})-[d:DERIVED_FROM]->(e:Evidence)
OPTIONAL MATCH (x)-[:VALIDATED_BY]->(v:Entity)
RETURN x.id, x.status, e.id AS evidence_id, e.status AS evidence_status,
       collect(DISTINCT v.id) AS validators
```

## 3. Promoted Claim

```cypher
MATCH (source:Entity {tenant_id:'northstar'})-[p:PROMOTED_TO]->(c:Claim)
MATCH (c)-[:DERIVED_FROM]->(source)
OPTIONAL MATCH (e:Evidence)-[:SUPPORTS]->(c)
OPTIONAL MATCH (c)-[:VALIDATED_BY]->(v:Entity)
RETURN source.id, source.status, c.id, c.status, c.promoted_at,
       collect(DISTINCT e.id) AS evidence,
       collect(DISTINCT v.id) AS validators
```

## 4. Decision based on promoted knowledge

```cypher
MATCH (d:Decision {tenant_id:'northstar'})-[:BASED_ON]->(c:Claim)
OPTIONAL MATCH (d)-[:BASED_ON]->(e:Evidence)
OPTIONAL MATCH (d)-[:BASED_ON]->(p:Policy)
RETURN d.id, d.summary, c.id AS claim,
       collect(DISTINCT e.id) AS evidence,
       collect(DISTINCT p.id) AS policies
```

## 5. Action and observed Outcome

```cypher
MATCH (a:Action {tenant_id:'northstar'})-[:HAS_OUTCOME]->(o:Outcome)
OPTIONAL MATCH (o)-[:ABOUT]->(target:Entity)
RETURN a.id, a.status, o.id, o.result, o.expected_effect, o.observed_effect,
       o.observed_at, collect(DISTINCT target.id) AS affected
```

## 6. Historical precedent representation

```cypher
MATCH (i:Incident {tenant_id:'northstar', precedent_eligible:true})-[:ROOT_CAUSE]->(c:Claim)
OPTIONAL MATCH (d:Decision)-[:BASED_ON]->(c)
OPTIONAL MATCH (t:Task)-[:ABOUT]->(i)
OPTIONAL MATCH (t)-[:PROPOSED_ACTION]->(a:Action)-[:HAS_OUTCOME]->(o:Outcome)
RETURN i.id, i.status, c.id AS root_cause,
       collect(DISTINCT d.id) AS decisions,
       collect(DISTINCT a.id) AS remediation,
       collect(DISTINCT o.id) AS outcomes
```

## 7. Historical and current ownership

```cypher
MATCH (owner:Entity {tenant_id:'northstar'})-[r:OWNS]->(s:System {id:'SYS-TARGET'})
RETURN owner.id, r.valid_from, r.valid_until, r.source_ref_id, r.authoritative
ORDER BY r.valid_from
```

Current only:

```cypher
MATCH (owner:Entity {tenant_id:'northstar'})-[r:OWNS]->(s:System {id:'SYS-TARGET'})
WHERE r.valid_until IS NULL
RETURN owner.id, s.id, r.valid_from
```

## 8. Stale Claim and invalidated Evidence

```cypher
MATCH (e:Evidence {tenant_id:'northstar'})-[:SUPPORTS]->(c:Claim)
WHERE e.status='INVALIDATED' OR c.status IN ['REQUIRES_REVALIDATION','INVALIDATED']
RETURN e.id, e.status, e.invalidated_at, c.id, c.status, c.stale_since
```

## 9. Affected Decisions / Tasks / Plans

```cypher
MATCH (e:Evidence {tenant_id:'northstar'})-[:SUPPORTS]->(c:Claim)
OPTIONAL MATCH (d:Decision)-[:BASED_ON]->(c)
OPTIONAL MATCH (t:Task)-[:ADDRESSES]->(c)
OPTIONAL MATCH (p:Plan)-[:PLAN_HAS_TASK]->(t)
RETURN e.id, c.id, c.status,
       collect(DISTINCT [d.id,d.applicability_status]) AS decisions,
       collect(DISTINCT [t.id,t.input_status]) AS tasks,
       collect(DISTINCT [p.id,p.planning_status]) AS plans
```

## 10. Revalidated Claim plus history events

```cypher
MATCH (c:Claim {tenant_id:'northstar'})
WHERE c.revalidated_at IS NOT NULL
OPTIONAL MATCH (ev:Event)-[:ABOUT]->(c)
WHERE ev.event_type IN ['KNOWLEDGE_INVALIDATED','KNOWLEDGE_REVALIDATED']
RETURN c.id, c.status, c.revalidated_at,
       collect(DISTINCT [ev.event_type,ev.occurred_at,ev.summary]) AS history
```

## 11. Complete learning-loop path

```cypher
MATCH (f:Finding {tenant_id:'northstar'})-[:PROMOTED_TO]->(c:Claim)
MATCH (c)-[:DERIVED_FROM]->(f)
OPTIONAL MATCH (e:Evidence)-[:SUPPORTS]->(c)
OPTIONAL MATCH (d:Decision)-[:BASED_ON]->(c)
OPTIONAL MATCH (d)-[:PRODUCED]->(a:Action)-[:HAS_OUTCOME]->(o:Outcome)
OPTIONAL MATCH (i:Incident)-[:ROOT_CAUSE]->(c)
RETURN f.id AS finding, c.id AS claim,
       collect(DISTINCT e.id) AS evidence,
       collect(DISTINCT d.id) AS decisions,
       collect(DISTINCT a.id) AS actions,
       collect(DISTINCT o.id) AS outcomes,
       collect(DISTINCT i.id) AS historical_incidents
```
