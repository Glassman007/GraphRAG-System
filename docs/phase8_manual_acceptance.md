# Phase 8 Manual Acceptance

Use:

- FastAPI Swagger: `http://127.0.0.1:8000/docs`
- FalkorDB Browser: `http://localhost:3000`
- graph: `company_brain`
- tenant: `northstar`

Before the demo, apply schema and seed the additive Phase 8 support scenario:

```powershell
python scripts/apply_schema.py
python scripts/seed_scenarios.py
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

No destructive full reseed is required when upgrading a verified Phase 7 graph.

## Demo A — Process reconstruction and policy drift

Swagger:

1. `GET /incidents/INC-001/process`
2. Confirm the result contains explicit `TRIGGERED` and dependency relationships separately from temporal ordering.
3. `GET /processes/INC-001/policy-drift?policy_id=POL-DB-04`
4. Confirm the compatibility/downstream control requirements are derived as missing from policy graph vs observed process.

### FalkorDB Browser queries

**1. INC-001 event workflow**

```cypher
MATCH (i {id:'INC-001'})-[r]-(x)
OPTIONAL MATCH (x)-[er]-(e:Event)
RETURN i.id, type(r), x.id, type(er), e.id, e.event_type, e.occurred_at
ORDER BY e.occurred_at
```

**2. BEFORE edges**

```cypher
MATCH (a:Event)-[r:BEFORE]->(b:Event)
WHERE a.tenant_id='northstar'
RETURN a.id, a.occurred_at, b.id, b.occurred_at, r.edge_id
ORDER BY a.occurred_at
```

**3. TRIGGERED edges**

```cypher
MATCH (a)-[r:TRIGGERED]->(b)
WHERE a.tenant_id='northstar'
RETURN labels(a), a.id, labels(b), b.id, r.edge_id
ORDER BY a.id, b.id
```

You should see `EVT-INC-001 -> EVT-TASK-INV`.

**4. Dependency relationships relevant to INC-001**

```cypher
MATCH p=(a)-[r:REQUIRES|BLOCKED_BY|DEPENDS_ON]->(b)
WHERE a.tenant_id='northstar' AND b.tenant_id='northstar'
  AND (a.id='INC-001' OR b.id='INC-001' OR a.id STARTS WITH 'TASK-' OR a.id='DPL-882')
RETURN a.id, type(r), b.id, r.valid_from, r.valid_until
```

**5. Validated causal relationships / root-cause evidence**

```cypher
MATCH (i:Incident {id:'INC-001'})-[rc:ROOT_CAUSE]->(c:Claim)
OPTIONAL MATCH (e:Evidence)-[s:SUPPORTS]->(c)
RETURN i.id, c.id, c.status, c.confidence, collect({evidence:e.id, relation:type(s)}) AS evidence
```

An explicit `BEFORE` edge by itself must not appear here as causal proof.

**6. POL-DB-04 expected requirements**

```cypher
MATCH (p:Policy {id:'POL-DB-04'})-[r:REQUIRES]->(required)
RETURN p.id, required.id, labels(required), required.status, r.edge_id
ORDER BY required.id
```

**7. Observed process/control steps**

```cypher
MATCH (x)
WHERE x.tenant_id='northstar'
  AND x.id IN ['ACT-COMPAT-TEST','ACT-DOWNSTREAM-VERIFY','DPL-882','MIG-203']
OPTIONAL MATCH (x)-[r]-(y)
RETURN x.id, x.status, type(r), y.id
ORDER BY x.id
```

## Demo B — Commitment

Swagger:

1. `GET /commitments/COM-017`
2. Confirm Pricing Platform is the promisor and Payments is the promisee.
3. Confirm `E-003` is breach evidence and `DPL-882` is a dependent consequence.
4. `GET /commitments/at-risk` for deadline-based commitments such as COM-099.

**8. COM-017**

```cypher
MATCH (c:Commitment {id:'COM-017'})-[r]->(x)
RETURN c.id, c.description, c.due_at, c.status, type(r), labels(x), x.id, x.name
ORDER BY type(r), x.id
```

**9. Commitment dependencies and consequences**

```cypher
MATCH p=(x)-[r:DEPENDS_ON|REQUIRES]->(c:Commitment {id:'COM-017'})
RETURN x.id, type(r), c.id, p
UNION
MATCH p=(c:Commitment {id:'COM-017'})-[r:AFFECTS]->(x)
RETURN c.id, type(r), x.id, p
```

## Demo C — Duplicate work

Swagger:

1. `GET /organization/initiative-collisions`
2. Find `PROJ-REFUND-A` vs `PROJ-REFUND-B`; inspect score, dimensions, shared graph entities and paths.
3. `GET /projects/PROJ-REFUND-C/collisions`; compare the shared-system-only negative.

**10. Overlapping projects and shared graph entities**

```cypher
MATCH (p:Project)-[r:DEPENDS_ON|REQUIRES|ABOUT|AFFECTS]->(x)
WHERE p.id IN ['PROJ-REFUND-A','PROJ-REFUND-B','PROJ-REFUND-C']
RETURN p.id, p.goal, type(r), labels(x), x.id, x.name
ORDER BY p.id, type(r), x.id
```

## Demo D — Bus factor

Swagger:

1. `GET /organization/bus-factor`
2. `GET /people/PERSON-ISHA/bus-factor-impact`
3. `POST /organization/bus-factor/simulate`:

```json
{"actor_ids":["PERSON-ISHA"]}
```

Compare before/after. The call must not mutate the graph.

**11. Ownership / expertise concentration**

```cypher
MATCH (a)-[r:OWNS|RESPONSIBLE_FOR|EXPERT_IN]->(s:System)
WHERE a.tenant_id='northstar'
RETURN s.id, s.criticality, type(r), a.id, labels(a), r.valid_from, r.valid_until
ORDER BY s.id, type(r), a.id
```

**12. Approval concentration**

```cypher
MATCH (object)-[r:APPROVED_BY]->(actor)
WHERE object.tenant_id='northstar'
RETURN object.id, labels(object), actor.id, labels(actor), r.valid_from, r.valid_until
ORDER BY actor.id, object.id
```

## Demo E — Bottleneck / bridge

Swagger:

1. `GET /organization/network-analysis?projection=collaboration`
2. Inspect centrality, articulation points, bridges, communities, overloaded nodes and single-path risks.
3. `GET /organization/bottlenecks?projection=collaboration`
4. `GET /organization/bridges?projection=collaboration`
5. `GET /organization/centrality?projection=collaboration`

**13. Raw relationships used by collaboration projection**

```cypher
MATCH (a)-[r:MEMBER_OF|COLLABORATES_WITH|OWNS|RESPONSIBLE_FOR|DEPENDS_ON|ABOUT]->(b)
WHERE a.tenant_id='northstar' AND b.tenant_id='northstar'
  AND (a:Person OR a:Team OR b:Person OR b:Team OR a:Project OR b:Project)
RETURN labels(a), a.id, type(r), labels(b), b.id
ORDER BY a.id, type(r), b.id
```

**14. Articulation fixture**

```cypher
MATCH p=(a)-[r]-(b)
WHERE a.id IN ['PERSON-DEV','TEAM-SECURITY','TEAM-PLATFORM','PROJ-RELEASE-GATE']
   OR b.id IN ['PERSON-DEV','TEAM-SECURITY','TEAM-PLATFORM','PROJ-RELEASE-GATE']
RETURN p
```

**15. Bridge/redundancy inspection**

```cypher
MATCH p=(a)-[r:COLLABORATES_WITH|MEMBER_OF|RESPONSIBLE_FOR|DEPENDS_ON]-(b)
WHERE a.id IN ['PERSON-DEV','TEAM-SECURITY','TEAM-PLATFORM']
   OR b.id IN ['PERSON-DEV','TEAM-SECURITY','TEAM-PLATFORM']
RETURN p
```

For a controlled redundancy demonstration, temporarily add a direct `COLLABORATES_WITH` edge between the two teams in an isolated test graph, rerun network analysis, and then remove it. Do not mutate a canonical production graph merely for a demo.

## Temporal examples

Pass an explicit `as_of` query parameter to process, commitments, bus factor, and network endpoints where supported. Historical results must use only nodes/relationships valid at that instant.
