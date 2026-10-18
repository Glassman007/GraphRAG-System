from __future__ import annotations

from typing import Any
from collections import defaultdict

from backend.app.services.phase4_graph import GraphSnapshot, has_label


DONE = {'COMPLETED', 'DONE', 'VERIFIED', 'CLOSED'}


def task_dependency_analysis(snapshot: GraphSnapshot, plan_id: str) -> dict[str, Any] | None:
    """Read-only, tenant-snapshot work topology. Longest path counts dependencies, NOT runtime duration."""
    plan = snapshot.node(plan_id)
    if not has_label(plan, 'Plan'):
        return None
    ids = sorted({e.target for e in snapshot.edges_from(plan_id, {'PLAN_HAS_TASK'}) if has_label(snapshot.node(e.target), 'Task')})
    tasks = {i: snapshot.node(i) for i in ids}
    prerequisites: dict[str, list[str]] = {i: sorted({e.target for e in snapshot.edges_from(i, {'REQUIRES'}) if e.target in tasks}) for i in ids}
    downstream: dict[str, list[str]] = {i: [] for i in ids}
    for i, reqs in prerequisites.items():
        for req in reqs:
            downstream[req].append(i)
    for v in downstream.values():
        v.sort()
    remaining = {i: set(prerequisites[i]) for i in ids}
    levels: list[list[str]] = []
    while remaining:
        ready = sorted(i for i, deps in remaining.items() if not deps)
        if not ready:
            break
        levels.append(ready)
        for i in ready:
            del remaining[i]
        for deps in remaining.values():
            deps.difference_update(ready)
    cycles = bool(remaining)
    best_paths: dict[str, list[str]] = {}
    for wave in levels:
        for i in wave:
            possibilities = [best_paths[p] for p in prerequisites[i] if p in best_paths]
            chain = max(possibilities, key=lambda path:(len(path), path), default=[])
            best_paths[i] = [*chain, i]
    canonical: dict[tuple[str,str],list[str]] = defaultdict(list)
    for tid, node in tasks.items():
        signature=(str(node.get('task_type') or '').upper(), ' '.join(str(node.get('objective') or '').lower().split()))
        if signature[1]:canonical[signature].append(tid)
    duplicate_candidates=[{'task_ids':sorted(value),'reason':'Same task type and normalized objective; review before treating as duplicate'} for value in canonical.values() if len(value)>1]
    critical = max(best_paths.values(), key=lambda path:(len(path), path), default=[])
    blocked = [i for i in ids if any(str(tasks[p].get('status') or '').upper() not in DONE for p in prerequisites[i]) or str(tasks[i].get('status') or '').upper() == 'BLOCKED']
    edges = [{'source': i, 'target': p, 'type': 'REQUIRES'} for i in ids for p in prerequisites[i]]
    return {
        'plan': plan,
        'tasks': list(tasks.values()),
        'edges': edges,
        'parallel_waves': levels,
        'cycle_detected': cycles,
        'cycle_members_or_dependents': sorted(remaining),
        'longest_dependency_chain': critical if not cycles else [],
        'longest_dependency_chain_is_duration_critical_path': False,
        'explanation': 'Longest dependency chain counts edges, not task durations; it is not a time-based critical path.',
        'blocked_task_ids': blocked,
        'potential_duplicate_tasks': duplicate_candidates,
        'events': _events_about(snapshot, set(ids)|{plan_id}),
        'total': len(ids),
        'complete': sum(1 for t in tasks.values() if str(t.get('status') or '').upper() in DONE),
    }


def _events_about(snapshot: GraphSnapshot, ids: set[str]) -> list[dict[str, Any]]:
    event_ids = {e.source for i in ids for e in snapshot.edges_to(i, {'ABOUT'}) if has_label(snapshot.node(e.source), 'Event')}
    return sorted((snapshot.node(i) for i in event_ids if snapshot.node(i)), key=lambda n: (str(n.get('occurred_at') or n.get('created_at') or ''), str(n.get('id') or '')))


def task_insights(snapshot: GraphSnapshot, task_id: str) -> dict[str, Any] | None:
    task = snapshot.node(task_id)
    if not has_label(task, 'Task'):
        return None
    def outgoing(typ: str, kind: str | None = None):
        return [snapshot.node(e.target) for e in snapshot.edges_from(task_id, {typ}) if snapshot.node(e.target) and (not kind or has_label(snapshot.node(e.target), kind))]
    def incoming(typ: str, kind: str | None = None):
        return [snapshot.node(e.source) for e in snapshot.edges_to(task_id, {typ}) if snapshot.node(e.source) and (not kind or has_label(snapshot.node(e.source), kind))]
    executions = outgoing('HAS_EXECUTION', 'Execution')
    checkpoints = outgoing('HAS_CHECKPOINT', 'Checkpoint')
    owners = [snapshot.node(e.target) for e in snapshot.edges_from(task_id, {'CLAIMED_BY'}) if e.properties.get('valid_until') is None and has_label(snapshot.node(e.target), 'Agent')]
    findings = [f for f in incoming('ABOUT', 'Finding') if str(f.get('scope') or 'SHARED').upper() != 'BRANCH']
    explicit_conflicts = [edge.as_dict() for f in findings for _, edge, _ in snapshot.neighbors(str(f['id']), {'CONTRADICTS'}, direction='both')]
    events = _events_about(snapshot, {task_id, *[str(e['id']) for e in executions]})
    return {
        'task': task,
        'owner': owners[0] if len(owners) == 1 else None,
        'owner_conflict': len(owners) > 1,
        'prerequisites': outgoing('REQUIRES', 'Task'),
        'required_entities': [n for n in outgoing('REQUIRES') if not has_label(n, 'Task')],
        'evidence': incoming('ABOUT', 'Evidence'),
        'addresses': outgoing('ADDRESSES'),
        'related_entities': outgoing('ABOUT'),
        'candidate_agents': [{'agent':snapshot.node(e.source),'score':e.properties.get('score'),'reason':e.properties.get('reason_summary')} for e in snapshot.edges_to(task_id, {'CANDIDATE_FOR'}) if has_label(snapshot.node(e.source), 'Agent')],
        'executions': executions,
        'checkpoints': sorted(checkpoints, key=lambda n:(str(n.get('created_at') or ''), int(n.get('step_index') or 0))),
        'findings': findings,
        'handoffs': incoming('HANDOFF_FOR', 'Handoff'),
        'branches': outgoing('HAS_BRANCH', 'WorkBranch'),
        'blockers': [b for b in outgoing('BLOCKED_BY','Blocker') if str(b.get('status') or '').upper() not in {'RESOLVED','CLOSED'}],
        'actions': outgoing('PROPOSED_ACTION', 'Action'),
        'events': events,
        'recorded_conflict_edges': explicit_conflicts,
        'comparison': {'planned_output':task.get('expected_output_type') or task.get('completion_condition'), 'actual_status':task.get('status'), 'actual_findings':len(findings), 'execution_attempts':max((int(e.get('attempt') or 0) for e in executions), default=0)},
    }


def agent_memory(snapshot: GraphSnapshot, agent_id: str) -> dict[str, Any] | None:
    agent = snapshot.node(agent_id)
    if not has_label(agent, 'Agent'):
        return None
    work = [snapshot.node(e.source) for e in snapshot.edges_to(agent_id, {'CLAIMED_BY'}) if e.properties.get('valid_until') is None and has_label(snapshot.node(e.source), 'Task')]
    created = [snapshot.node(e.target) for e in snapshot.edges_from(agent_id, {'PRODUCED'}) if snapshot.node(e.target)]
    checkpoints = [node for node in snapshot.nodes.values() if has_label(node, 'Checkpoint') and node.get('agent_id') == agent_id]
    # A persisted checkpoint or finding is historical organizational memory; it is not model-conversation recall.
    records = []
    for node in created + checkpoints:
        if not node or not node.get('id'):
            continue
        # Branch-private findings require actual branch ACLs, which this read API does not implement.
        # Do not expose branch-scoped memory to arbitrary tenant-wide READ_GRAPH callers.
        if str(node.get('scope') or '').upper() == 'BRANCH':
            continue
        evidence = [snapshot.node(e.target) for e in snapshot.edges_from(str(node['id']), {'DERIVED_FROM'}) if snapshot.node(e.target)]
        scope = str(node.get('scope') or ('TASK' if has_label(node,'Checkpoint') else 'SHARED')).upper()
        records.append({'record':node,'scope':scope,'created_at':node.get('created_at') or node.get('observed_at'), 'status':node.get('status') or 'RECORDED', 'valid_until':node.get('valid_until'), 'valid_from':node.get('valid_from'), 'source_evidence':evidence,'provenance':f'{agent_id}-[:PRODUCED]->{node["id"]}' if node in created else f'checkpoint.agent_id={agent_id}', 'accessible_to': 'Authorized readers within the same tenant (READ_GRAPH); no per-agent ACL enforced'})
    unique = {str(row['record']['id']): row for row in records}
    return {'agent':agent,'owned_tasks':work,'records':sorted(unique.values(),key=lambda r:str(r.get('created_at') or ''),reverse=True), 'memory_kind':'Persisted tenant-scoped checkpoints and produced artifacts, not LLM conversation memory; branch-private records excluded', 'count':len(unique)}
