# Phase 6 Dependency-Preserving Memory Compaction

Compaction reduces old execution trace volume without deleting durable reasoning/action lineage.

## Current deterministic policy

`compact_execution(execution_id, keep_latest=N)`:

1. reconstructs Execution/Task context from FalkorDB;
2. sorts Checkpoints by step/time;
3. marks all but the latest N active Checkpoints `ARCHIVED`;
4. keeps Finding, Evidence, Decision, Handoff, WorkBranch, Action, ActionAttempt and unresolved Blocker graph objects intact;
5. writes a `CompactionRecord` with retained IDs, archived IDs and dependency manifest;
6. links the CompactionRecord back to Execution and retained/archived entities;
7. validates lineage invariants.

Archived Checkpoints are not deleted.

## Invariants

After compaction the graph must still answer:

- which Task/Agent produced a finding;
- which Evidence supports the work;
- why a Decision was made;
- which Branch produced/promoted a result;
- what Action/ActionAttempt occurred;
- which dependencies remain relevant.

A broken Evidence->Task, Branch->Execution, Task->Execution or Action->ActionAttempt path invalidates compaction. Rejected branches remain queryable.
