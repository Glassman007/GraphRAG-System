// Select graph in FalkorDB Browser: accept_p68_20261016_152153
// These queries inspect objects created by scripts/verify_phases_6_8.py.

// PHASE 6 — task ownership, execution, checkpoints, findings, handoff
MATCH (t:Entity:Task {id:''})
OPTIONAL MATCH (t)-[:CLAIMED_BY]->(a:Entity:Agent)
OPTIONAL MATCH (t)-[:HAS_EXECUTION]->(e:Entity:Execution)
OPTIONAL MATCH (e)-[:HAS_CHECKPOINT]->(cp:Entity:Checkpoint)
RETURN t, a, e, cp;

MATCH (f:Entity:Finding {id:''})
OPTIONAL MATCH (f)-[r]-(x)
RETURN f, r, x;

MATCH (h:Entity:Handoff {id:''})
OPTIONAL MATCH (h)-[r]-(x)
RETURN h, r, x;

MATCH (b:Entity:WorkBranch)
WHERE b.id IN ['','']
OPTIONAL MATCH (b)-[r]-(x)
RETURN b, r, x;

MATCH (a:Entity:Action {id:''})
OPTIONAL MATCH (a)-[:HAS_ATTEMPT]->(attempt:Entity:ActionAttempt)
OPTIONAL MATCH (a)-[r]-(x)
RETURN a, attempt, r, x;

// PHASE 7 — promotion and learning lineage
MATCH (f:Entity:Finding {id:''})-[:PROMOTED_TO]->(c:Entity:Claim {id:''})
OPTIONAL MATCH (e:Entity:Evidence)-[:SUPPORTS]->(c)
OPTIONAL MATCH (d:Entity:Decision)-[:BASED_ON]->(c)
OPTIONAL MATCH (t:Entity:Task)-[:ADDRESSES]->(c)
RETURN f, c, e, d, t;

MATCH (s:Entity:System {id:''})
OPTIONAL MATCH (owner:Entity)-[r:OWNS]->(s)
RETURN owner.id, owner.name, r.valid_from, r.valid_until, s.id;

// PHASE 8 — process semantics
MATCH (a:Entity:Event)-[r:TRIGGERED|BEFORE]->(b:Entity:Event)
WHERE a.tenant_id='northstar'
RETURN a.id, type(r), b.id, a.occurred_at, b.occurred_at
ORDER BY a.occurred_at;

// Policy requirements
MATCH (p:Entity:Policy {id:'POL-DB-04'})-[r:REQUIRES]->(x)
RETURN p, r, x;

// Commitment COM-017
MATCH (c:Entity:Commitment {id:'COM-017'})-[r]->(x)
RETURN c, r, x;

// Duplicate-work source graph
MATCH (p:Entity:Project)-[r]->(x)
WHERE p.id IN ['PROJ-REFUND-A','PROJ-REFUND-B','PROJ-REFUND-C']
RETURN p, r, x;

// Bus factor source relationship
MATCH p=(person:Entity:Person {id:'PERSON-ISHA'})-[:EXPERT_IN]->(s:Entity:System {id:'SYS-LEDGER-EXPORT'})
RETURN p;

// Collaboration bridge fixture
MATCH p=(a)-[r]-(b)
WHERE a.id IN ['PERSON-DEV','TEAM-SECURITY','TEAM-PLATFORM','PROJ-RELEASE-GATE']
   OR b.id IN ['PERSON-DEV','TEAM-SECURITY','TEAM-PLATFORM','PROJ-RELEASE-GATE']
RETURN p;
