# Phase 6 Manual Acceptance

This sequence is intended for the local environment with FalkorDB at `localhost:6379` and the API at `http://127.0.0.1:8000`.

## 1. Apply the additive schema and start the API

```powershell
pip install -r requirements.txt
python scripts/apply_schema.py
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Open Swagger at `http://127.0.0.1:8000/docs` and FalkorDB Browser at `http://localhost:3000`.

No destructive reseed is required when upgrading a verified Phase 5 graph.

## 2. Initialize the four persisted specialist workers

```powershell
$base = "http://127.0.0.1:8000"
Invoke-RestMethod -Method Post "$base/agents/ensure-defaults"
```

Expected worker IDs:

- `AGENT-P6-INVESTIGATOR`
- `AGENT-P6-VERIFIER`
- `AGENT-P6-DEPENDENCY`
- `AGENT-P6-REMEDIATION`

## 3. Generate/reuse the Phase 5 INC-001 plan

```powershell
$plan = Invoke-RestMethod -Method Post "$base/plans" -ContentType "application/json" -Body (@{
  situation_id = "INC-001"
  goal = "Resolve INC-001 safely with enough evidence to select remediation."
} | ConvertTo-Json)

$planId = $plan.plan.id
$tasks = Invoke-RestMethod "$base/plans/$planId/tasks"
$tasks | ConvertTo-Json -Depth 12
```

Choose a READY investigation/evidence task from:

```powershell
$ready = Invoke-RestMethod "$base/plans/$planId/ready-tasks"
$ready | ConvertTo-Json -Depth 12
```

Copy the selected task ID into `$taskId`.

## 4. Claim, start and checkpoint durable work

```powershell
$taskId = "<READY-INVESTIGATION-TASK-ID>"
$investigator = "AGENT-P6-INVESTIGATOR"

Invoke-RestMethod -Method Post "$base/tasks/$taskId/claim" -ContentType "application/json" -Body (@{
  agent_id = $investigator
} | ConvertTo-Json)

$started = Invoke-RestMethod -Method Post "$base/tasks/$taskId/start" -ContentType "application/json" -Body (@{
  agent_id = $investigator
} | ConvertTo-Json)
$executionId = $started.execution.id

Invoke-RestMethod -Method Post "$base/tasks/$taskId/checkpoint" -ContentType "application/json" -Body (@{
  agent_id = $investigator
  execution_id = $executionId
  step_index = 1
  current_step = "Inspect connected incident evidence"
  completed_steps = @("load incident context")
  pending_steps = @("trace dependencies", "publish finding")
  state_summary = "INC-001 context loaded from FalkorDB"
} | ConvertTo-Json)

Invoke-RestMethod -Method Post "$base/tasks/$taskId/checkpoint" -ContentType "application/json" -Body (@{
  agent_id = $investigator
  execution_id = $executionId
  step_index = 2
  current_step = "Trace downstream dependency context"
  completed_steps = @("load incident context", "trace dependencies")
  pending_steps = @("publish finding")
  state_summary = "Dependency context persisted"
} | ConvertTo-Json)
```

Now restart the FastAPI process. Then prove restart reconstruction:

```powershell
Invoke-RestMethod -Method Post "$base/tasks/$taskId/resume" -ContentType "application/json" -Body (@{
  agent_id = $investigator
  execution_id = $executionId
} | ConvertTo-Json)
```

Expected: `resume_from_step` is `3`; prior checkpoints remain queryable.

## 5. Share evidence and create a Finding

Use an existing canonical Evidence ID such as `E-003` only if it is relevant to the selected task.

```powershell
Invoke-RestMethod -Method Post "$base/tasks/$taskId/evidence" -ContentType "application/json" -Body (@{
  agent_id = $investigator
  evidence_id = "E-003"
} | ConvertTo-Json)

$finding = Invoke-RestMethod -Method Post "$base/tasks/$taskId/findings" -ContentType "application/json" -Body (@{
  agent_id = $investigator
  statement = "Connected dependency evidence requires verifier review"
  confidence = 0.90
  kind = "ROOT_CAUSE_HYPOTHESIS"
  evidence_ids = @("E-003")
} | ConvertTo-Json)
$findingId = $finding.finding.id
```

## 6. Validate a handoff contract to the Verifier

```powershell
$transfer = Invoke-RestMethod -Method Post "$base/transfers" -ContentType "application/json" -Body (@{
  source_task_id = $taskId
  from_agent_id = $investigator
  to_agent_id = "AGENT-P6-VERIFIER"
  artifact_ids = @($findingId, "E-003")
  confidence_threshold = 0.8
  contradictory_evidence_disclosed = $true
} | ConvertTo-Json)
$transferId = $transfer.handoff.id

Invoke-RestMethod "$base/transfers/$transferId/validate" | ConvertTo-Json -Depth 12
Invoke-RestMethod -Method Post "$base/transfers/$transferId/accept" -ContentType "application/json" -Body (@{
  agent_id = "AGENT-P6-VERIFIER"
} | ConvertTo-Json)

Invoke-RestMethod -Method Post "$base/findings/$findingId/verify" -ContentType "application/json" -Body (@{
  agent_id = "AGENT-P6-VERIFIER"
  result = "VERIFIED"
  rationale = "Evidence and graph path are sufficient for this finding."
} | ConvertTo-Json)
```

Negative acceptance: create the same Investigator -> Verifier transfer with only the Finding ID and no Evidence. Validation must return `valid=false`, and `/accept` must return HTTP 409.

## 7. Demonstrate branch isolation and merge/rejection

```powershell
$branchA = Invoke-RestMethod -Method Post "$base/branches" -ContentType "application/json" -Body (@{
  execution_id = $executionId
  agent_id = $investigator
  purpose = "Test schema incompatibility hypothesis"
  branch_kind = "HYPOTHESIS"
} | ConvertTo-Json)

$branchB = Invoke-RestMethod -Method Post "$base/branches" -ContentType "application/json" -Body (@{
  execution_id = $executionId
  agent_id = $investigator
  purpose = "Test saturation hypothesis"
  branch_kind = "HYPOTHESIS"
} | ConvertTo-Json)

$branchAId = $branchA.branch.id
$branchBId = $branchB.branch.id

Invoke-RestMethod -Method Post "$base/branches/$branchAId/findings" -ContentType "application/json" -Body (@{
  agent_id = $investigator
  statement = "Schema incompatibility remains structurally plausible"
  confidence = 0.90
  evidence_ids = @("E-003")
} | ConvertTo-Json)

Invoke-RestMethod -Method Post "$base/branches/$branchBId/findings" -ContentType "application/json" -Body (@{
  agent_id = $investigator
  statement = "Saturation branch is weak"
  confidence = 0.45
  evidence_ids = @("E-003")
} | ConvertTo-Json)

Invoke-RestMethod -Method Post "$base/branches/$branchAId/validate"
Invoke-RestMethod -Method Post "$base/branches/$branchAId/merge" -ContentType "application/json" -Body (@{
  agent_id = $investigator
} | ConvertTo-Json)

Invoke-RestMethod -Method Post "$base/branches/$branchBId/reject" -ContentType "application/json" -Body (@{
  agent_id = $investigator
  reason = "Insufficient structural/evidence support"
} | ConvertTo-Json)
```

Expected: Branch A is `MERGED`; Branch B is `REJECTED`; both remain queryable. Branch-local Findings do not become canonical until merge.

## 8. Demonstrate governed/idempotent action coordination

A remediation Task must be READY and owned by `AGENT-P6-REMEDIATION`. If the canonical Plan has not reached that point yet, create an isolated manual-demo Task in FalkorDB Browser rather than falsifying the canonical Plan state:

```cypher
MERGE (t:Entity:Task {tenant_id:'northstar', id:'TASK-P6-MANUAL-REMEDIATION'})
SET t.name='Phase 6 manual remediation demo',
    t.title='Phase 6 manual remediation demo',
    t.task_type='PREPARE_ACTION',
    t.objective='Demonstrate governed sandbox action coordination',
    t.status='OPEN',
    t.priority='P1',
    t.expected_output_type='ACTION_PROPOSAL',
    t.completion_condition='A selected Action proposal exists with its prerequisites represented.',
    t.created_at='2026-10-16T14:00:00+05:30';
```

Then:

```powershell
$remTask = "TASK-P6-MANUAL-REMEDIATION"
$remAgent = "AGENT-P6-REMEDIATION"
Invoke-RestMethod -Method Post "$base/tasks/$remTask/claim" -ContentType "application/json" -Body (@{agent_id=$remAgent} | ConvertTo-Json)
Invoke-RestMethod -Method Post "$base/tasks/$remTask/start" -ContentType "application/json" -Body (@{agent_id=$remAgent} | ConvertTo-Json)

$action = Invoke-RestMethod -Method Post "$base/actions" -ContentType "application/json" -Body (@{
  task_id = $remTask
  agent_id = $remAgent
  name = "Sandbox rollback"
  action_type = "rollback"
  target_ids = @("SYS-PRICING-DB")
  idempotency_key = "manual-phase6-rollback-001"
  approval_required = $false
} | ConvertTo-Json)
$actionId = $action.action.id

Invoke-RestMethod "$base/actions/$actionId/governance?agent_id=$remAgent" | ConvertTo-Json -Depth 12
Invoke-RestMethod -Method Post "$base/actions/$actionId/execute" -ContentType "application/json" -Body (@{
  agent_id = $remAgent
  lease_seconds = 60
} | ConvertTo-Json)

# Duplicate call must not invoke the sandbox side effect twice.
Invoke-RestMethod -Method Post "$base/actions/$actionId/execute" -ContentType "application/json" -Body (@{
  agent_id = $remAgent
  lease_seconds = 60
} | ConvertTo-Json)
```

Expected second result: `ALREADY_COMPLETED` (or equivalent already-completed state), with one durable successful ActionAttempt.

Policy denial test: add/apply a governing DENY Policy to the Action/target and retry with a new Action. Governance must return `DENY`; execution must not invoke the sandbox executor.

## 9. Compaction

```powershell
Invoke-RestMethod -Method Post "$base/executions/$executionId/compact" -ContentType "application/json" -Body (@{
  keep_latest = 1
  actor_id = $investigator
} | ConvertTo-Json) | ConvertTo-Json -Depth 12
```

Expected: older Checkpoints become `ARCHIVED`, not deleted; Findings/Evidence/Handoff/Branch/Action lineage remains traversable.

## 10. FalkorDB Browser verification queries

### Plan -> Task -> owner/execution/checkpoint

```cypher
MATCH (p:Entity:Plan {tenant_id:'northstar'})-[:PLAN_HAS_TASK]->(t:Entity:Task)
WHERE p.situation_id='INC-001'
OPTIONAL MATCH (t)-[c:CLAIMED_BY]->(a:Entity:Agent)
WHERE c.valid_until IS NULL
OPTIONAL MATCH (t)-[:HAS_EXECUTION]->(e:Entity:Execution)
OPTIONAL MATCH (e)-[:HAS_CHECKPOINT]->(cp:Entity:Checkpoint)
RETURN p.id, t.id, t.task_type, t.status, a.id, e.id, e.status,
       cp.id, cp.step_index, cp.status
ORDER BY t.id, cp.step_index;
```

### Shared Finding/Evidence/Handoff state

```cypher
MATCH (t:Entity:Task {tenant_id:'northstar', id:$task_id})
OPTIONAL MATCH (f:Entity:Finding)-[:ABOUT]->(t)
OPTIONAL MATCH (ev:Entity:Evidence)-[:ABOUT]->(t)
OPTIONAL MATCH (h:Entity:Handoff)-[:HANDOFF_FOR]->(t)
RETURN t.id,
       collect(DISTINCT {id:f.id,status:f.status,confidence:f.confidence}) AS findings,
       collect(DISTINCT ev.id) AS evidence,
       collect(DISTINCT {id:h.id,status:h.status}) AS handoffs;
```

### Handoff artifacts

```cypher
MATCH (h:Entity:Handoff {tenant_id:'northstar', id:$transfer_id})
OPTIONAL MATCH (h)-[:REQUIRES]->(artifact:Entity)
OPTIONAL MATCH (h)-[:ASSIGNED_TO]->(receiver:Entity:Agent)
RETURN h.id, h.status, h.confidence_threshold,
       collect(DISTINCT artifact.id) AS artifacts,
       collect(DISTINCT receiver.id) AS receivers;
```

### Branch isolation/history

```cypher
MATCH (t:Entity:Task {tenant_id:'northstar', id:$task_id})-[:HAS_BRANCH]->(b:Entity:WorkBranch)
OPTIONAL MATCH (b)-[:CONTAINS]->(f:Entity:Finding)
RETURN b.id, b.status, b.purpose,
       collect({id:f.id,status:f.status,scope:f.scope,merged_from_branch:f.merged_from_branch}) AS branch_findings
ORDER BY b.created_at;
```

### Action -> Attempt -> resource lock

```cypher
MATCH (t:Entity:Task {tenant_id:'northstar'})-[:PROPOSED_ACTION]->(a:Entity:Action)
OPTIONAL MATCH (a)-[:HAS_ATTEMPT]->(aa:Entity:ActionAttempt)
OPTIONAL MATCH (l:Entity:Lock)-[:LOCKS]->(resource:Entity)
WHERE l.action_id=a.id
RETURN t.id, a.id, a.status, a.idempotency_key,
       aa.id, aa.execution_state, aa.external_request_id,
       collect(DISTINCT {lock:l.id,resource:resource.id,state:l.status,lease_until:l.lease_until}) AS locks;
```

### Deadlock/contention topology

```cypher
MATCH path=(t:Entity:Task)-[:REQUIRES|BLOCKED_BY*1..8]->(t)
RETURN path;
```

A valid Phase 5 plan should have no prerequisite cycle. Phase 6 deadlock tests create isolated cyclic fixtures to prove detection.

### Compaction lineage

```cypher
MATCH (e:Entity:Execution {tenant_id:'northstar', id:$execution_id})-[:HAS_COMPACTION]->(c:Entity:CompactionRecord)
OPTIONAL MATCH (c)-[:DERIVED_FROM]->(retained:Entity)
OPTIONAL MATCH (e)-[:HAS_CHECKPOINT]->(cp:Entity:Checkpoint)
RETURN e.id, c.id, c.summary, c.dependency_manifest,
       collect(DISTINCT {id:retained.id,labels:labels(retained)}) AS lineage,
       collect(DISTINCT {id:cp.id,status:cp.status,step:cp.step_index}) AS checkpoints;
```

## 11. Graph-necessity destructive checks on a test graph only

Do these only in the isolated integration graph, not the canonical demo graph:

- delete `Finding -[:ABOUT]-> Task` -> Finding disappears from task shared state;
- delete latest `HAS_CHECKPOINT` -> resume position changes/fails;
- delete Handoff `REQUIRES` Evidence -> validation fails;
- delete Branch `PART_OF` Execution -> merge validation fails;
- delete one Task wait/dependency edge -> deadlock cycle disappears;
- delete required approval/authority edge -> governance changes;
- bypass/remove idempotency/lock coordination only in test code -> duplicate-protection necessity is demonstrated by the race tests;
- delete Evidence lineage before compaction validation -> validation fails.
