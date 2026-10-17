# Phase 6 Coordination Model

## Scope

Phase 6 turns a persisted Phase 5 `Plan -> Task` graph into durable coordinated execution. FalkorDB is the canonical coordination state. Python services are deterministic adapters over graph state; they do not own a process-local blackboard.

## Persisted objects

Phase 6 reuses `Plan`, `Task`, `Agent`, `Action`, `Evidence`, `Decision`, `WorkBranch`, `Checkpoint`, and `Handoff`, and adds only the missing durable coordination records:

- `Execution` — one resumable execution record for a Task.
- `Finding` — structured shared or branch-local worker result.
- `Blocker` — explicit unresolved execution blocker.
- `Lock` — lease-bearing resource coordination record.
- `ActionAttempt` — durable idempotent action-attempt state.
- `CompactionRecord` — dependency manifest for archived checkpoint trace.

## Blackboard structure

A Task can accumulate graph state such as:

```text
Task -[:CLAIMED_BY]-> Agent
Task -[:HAS_EXECUTION]-> Execution
Execution -[:HAS_CHECKPOINT]-> Checkpoint
Task -[:HAS_CHECKPOINT]-> Checkpoint
Agent -[:PRODUCED]-> Finding
Finding -[:ABOUT]-> Task
Task -[:BLOCKED_BY]-> Blocker
Evidence -[:ABOUT]-> Task
Task -[:HAS_BRANCH]-> WorkBranch
Task -[:PROPOSED_ACTION]-> Action
Handoff -[:HANDOFF_FOR]-> Task
```

The service reconstructs task/plan coordination views from those nodes/relationships after every process restart. There is no canonical Python dictionary containing task owner, progress, findings, blockers or action state.

## Specialist agents

Exactly four built-in functional worker types are persisted as `Agent` nodes:

| Type | Supported work | Important permissions | Prohibited by design |
|---|---|---|---|
| INVESTIGATOR | `INVESTIGATE`, `ACQUIRE_EVIDENCE` | graph read, finding/evidence write, checkpoint | action approval/execution |
| VERIFIER | claim/evidence/policy validation work | graph read, finding validation, checkpoint | remediation execution |
| DEPENDENCY_ANALYST | dependency-oriented `INVESTIGATE` | graph read, blast-radius finding, checkpoint | remediation execution |
| REMEDIATION_WORKER | `PREPARE_ACTION`, `VALIDATE_OUTCOME` | action proposal, sandbox execution subject to governance | policy override |

Agent capability/task/permission metadata is stored in FalkorDB. `ensure_default_agents()` is idempotent and deliberately preserves mutable `status` and `availability` rather than resetting them during process reconstruction.

## Claiming

`claim_task(task_id, agent_id)` requires:

1. Phase 5 readiness is true;
2. persisted Agent capability is compatible, or the Agent is already a Phase 5 `CANDIDATE_FOR` candidate with equivalent capability;
3. no active `Task -[:CLAIMED_BY]-> Agent` relationship exists;
4. Task state is claimable.

The ownership transition is a single conditional FalkorDB mutation, not `read owner -> if none -> write owner`. A postcondition check detects conflicting active claims if a deployment cannot serialize conflicting graph writes.

Task completion is also explicit rather than autonomous: only the active owner may complete an Execution, unresolved Blockers must be absent, and the existing Phase 5 graph-backed completion validator must report the Task's evidence/action/approval condition as satisfied. Completion closes the Execution, sets the Task `COMPLETED`, and temporally ends the active `CLAIMED_BY` relationship.

## Shared artifacts

Findings and Evidence are shared by reference rather than duplicated per worker. A verifier sees the same `Finding`/`Evidence` nodes the investigator created. Branch-local Findings have `scope=BRANCH` and are excluded from normal shared Task queries until a validated merge creates an explicitly promoted shared Finding.

## Process restart invariant

After a process disappears, a new process can reconstruct:

- Plan/Task and Task owner;
- active Execution;
- latest Checkpoint and next step;
- Findings and Evidence;
- unresolved Blockers;
- Handoffs;
- Branches;
- proposed Actions, attempts and resource Locks;
- compaction lineage.

This invariant is covered by real-FalkorDB integration tests.
