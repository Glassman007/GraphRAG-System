# Phase 6 Execution State Machines

## Task coordination lifecycle

Phase 5 Task statuses remain valid. Phase 6 uses the execution-relevant subset:

```text
OPEN -> READY -> CLAIMED -> IN_PROGRESS
                         -> BLOCKED -> IN_PROGRESS
                         -> COMPLETED / FAILED / CANCELLED
```

`READY` is computed from the existing Phase 5 prerequisite/blocker graph. Claiming does not bypass readiness.

## Execution lifecycle

`Execution` is durable and task-linked:

```text
RUNNING <-> PAUSED
RUNNING -> BLOCKED
RUNNING -> COMPLETED | FAILED | CANCELLED
```

Phase 6 persists `RUNNING` and resumable state and exposes an explicit completion transition. `complete_execution(...)` may set the Execution and Task to `COMPLETED` only when the current owner has no unresolved blockers and the existing Phase 5 `is_task_completion_satisfied(...)` graph predicate returns satisfied. There is no autonomous scheduler or manual completion bypass.

## Checkpoint semantics

A Checkpoint stores only resumable structured state:

- execution/task/agent IDs;
- step index and current step;
- completed/pending step lists;
- concise state summary;
- attempt number;
- timestamp/last error.

It never stores private model chain-of-thought.

Resume selects the highest non-archived/latest Checkpoint by step index and resumes at `step_index + 1`. Cross-agent resume additionally validates capability, current blockers and ownership transfer.

## Handoff lifecycle

```text
PENDING -> ACCEPTED
PENDING -> REJECTED
```

Acceptance is impossible until the structured handoff contract validates.

## Branch lifecycle

```text
OPEN -> VALIDATED -> MERGED
OPEN -> REJECTED
OPEN -> ABANDONED   (reserved state; no automatic transition)
```

Rejected branch state remains queryable and is never silently deleted.

## Action lifecycle

Action coordination uses two related states.

### Action

```text
PROPOSED -> EXECUTING -> SUCCEEDED
                     -> FAILED
                     -> UNKNOWN
```

Governance is evaluated immediately before execution. A non-`ALLOW` governance result prevents the mock side effect.

### ActionAttempt

```text
PENDING -> EXECUTING -> SUCCEEDED
                     -> FAILED
                     -> UNKNOWN
```

`UNKNOWN` is mandatory when the external call may have succeeded but local success was not durably recorded and the destination cannot be safely reconciled. Phase 6 does not blindly retry that state.

## Locks

Resource lock state is:

```text
AVAILABLE/RELEASED -> ACTIVE -> RELEASED
```

Each resource has a deterministic lock identity. `ACTIVE` includes owner, action, acquisition/heartbeat time and `lease_until`. An expired `ACTIVE` lock is detectable as abandoned.
