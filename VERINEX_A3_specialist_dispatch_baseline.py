"""A3 baseline: Asteria-only deterministic graph reads vs Supervisor dispatch.

Run from G:\\graphhacks with .venv already active:
    python .\\VERINEX_A3_specialist_dispatch_baseline.py

No provider network calls, no persisted runs, no Workspace/API writes, no
business-graph mutations. Uses a denied provider and in-memory Supervisor store.
This is a GAP REPRODUCTION, not an A3 implementation or live specialist pass.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

GRAPH = 'asteria_company_brain_v1'
TENANT = 'asteria'
INCIDENT = 'INC-AST-ROUTE-OUTAGE'
GOAL = ('Investigate the route orchestration outage and produce an evidence-backed, '
        'read-only remediation proposal. Separate observed facts from hypotheses; '
        'cite real Asteria evidence and identify any missing proof. Do not execute changes.')
OUTPUT = Path('VERINEX_A3_specialist_dispatch_baseline_result.json')
checks: list[dict] = []


def record(name: str, result: str, **details) -> None:
    checks.append({'check': name, 'result': result, **details})
    info = ', '.join(f'{k}={v}' for k, v in details.items())
    print(f'[{result}] {name}' + (': ' + info[:245] if info else ''))


class DisabledProvider:
    name = 'a3-network-disabled'
    model = 'none'

    def __init__(self):
        self.blocked_requests = 0

    def complete(self, *args, **kwargs):
        self.blocked_requests += 1
        raise RuntimeError('A3_PROVIDER_CALL_BLOCKED_BEFORE_NETWORK')


class MemoryOnlyStore:
    def __init__(self):
        self.runs: list[dict] = []
        self.tasks: list[dict] = []
        self.events: list[dict] = []
        self.finishes: list[dict] = []

    def start(self, row):
        self.runs.append(dict(row))

    def task(self, _run_id, row):
        self.tasks.append(dict(row))

    def event(self, _run_id, row):
        self.events.append(dict(row))

    def finish(self, _run_id, row):
        self.finishes.append(dict(row))


def check(snapshot):
    from backend.app.agent_runtime.incident_skill import build_incident_packet
    from backend.app.agent_runtime.supervisor import DEFAULT_AGENTS, Supervisor, SupervisorSettings
    from backend.app.agent_runtime.tools import ToolRegistry
    from backend.app.services.phase4_graph import has_label

    node = snapshot.node(INCIDENT)
    if not node or not has_label(node, 'Incident'):
        record('Known canonical Asteria Incident', 'FAIL', reason='INCIDENT_NOT_IN_GRAPH')
        return
    record('Known canonical Asteria Incident', 'PASS', entity_id=INCIDENT)

    # Independent deterministic reads: prove the underlying tools/packet work.
    direct_tools = ToolRegistry(lambda: snapshot)
    context = direct_tools.execute('incident_context', {'entity_id': INCIDENT})
    if context.get('error') or (context.get('incident') or {}).get('id') != INCIDENT:
        record('Existing deterministic incident_context read', 'FAIL', error=context.get('error'))
        return
    counts = {kind: len(items) for kind, items in (context.get('related') or {}).items()}
    record('Existing deterministic incident_context read', 'PASS', related_counts=counts)

    packet, visible_ids = build_incident_packet(snapshot, context, INCIDENT)
    actual_ids = {id_ for id_ in visible_ids if snapshot.node(id_) is not None}
    known = {'EVD-AST-0003', 'EVD-AST-0004', 'EVD-AST-0005'}
    packet_ok = packet.get('incident', {}).get('id') == INCIDENT and INCIDENT in actual_ids and known.issubset(actual_ids)
    record('Existing incident skill evidence packet', 'PASS' if packet_ok else 'FAIL',
           canonical_ids=len(actual_ids), expected_evidence_present=sorted(known & actual_ids),
           omitted_counts=packet.get('omitted_counts'))

    system_ids = sorted({item.get('entity', {}).get('id') for item in context.get('related', {}).get('System', [])
                         if item.get('entity', {}).get('id') and
                         has_label(snapshot.node(item['entity']['id']), 'System')})
    if not system_ids:
        record('Dependency helper via incident-linked System', 'NEEDS_REVIEW', reason='NO_DIRECTLY_LINKED_SYSTEM')
    else:
        system_id = system_ids[0]
        impact = direct_tools.execute('dependency_impact', {'entity_id': system_id, 'max_depth': 4})
        impact_ok = 'error' not in impact and isinstance(impact.get('impacted'), list)
        record('Dependency helper via incident-linked System', 'PASS' if impact_ok else 'FAIL',
               system_id=system_id, impacted_count=len(impact.get('impacted', [])),
               error=impact.get('error'))

    specialists = {agent.id: agent for agent in DEFAULT_AGENTS}
    capability_agents = sorted(a.id for a in DEFAULT_AGENTS if 'dependency_analysis' in a.capabilities)
    investigators = sorted(a.id for a in DEFAULT_AGENTS if 'investigation' in a.capabilities)
    record('Existing specialist capabilities', 'PASS' if capability_agents and investigators else 'FAIL',
           investigators=investigators, dependency_agents=capability_agents,
           incident_skill_available=True)

    # Exercise the *actual* Supervisor dispatch, not the standalone AgentHarness.
    # This deliberately blocks the provider before network access. If Supervisor
    # uses a deterministic skill for its first tasks, the tracking registry will
    # observe it; otherwise the model-driven gap is reproduced without Groq.
    class TrackingTools(ToolRegistry):
        def __init__(self):
            super().__init__(lambda: snapshot)
            self.read_calls: list[dict] = []

        def execute(self, name, arguments):
            result = super().execute(name, arguments)
            self.read_calls.append({'name': name,
                                    'entity_id': str(arguments.get('entity_id', '')),
                                    'status': 'ERROR' if result.get('error') else 'READ_OK',
                                    'error_code': str(result.get('error', ''))})
            return result

    provider = DisabledProvider()
    store = MemoryOnlyStore()
    tracking = TrackingTools()
    sup = Supervisor(provider=provider, tools=tracking, store=store, tenant=TENANT,
                     permissions=frozenset({'READ_GRAPH', 'READ_EVIDENCE'}), memory=None)
    outcome = sup.run(
        SupervisorSettings(goal=GOAL, source_entity_id=INCIDENT, allow_external_model=True,
                           max_tasks=4, max_parallel=1, max_steps_per_task=1,
                           max_retries=0, max_seconds=30, max_tokens_per_task=1000),
        subject='a3-in-memory-diagnostic')
    task_states = {task['id']: task['status'] for task in outcome.tasks}
    known_tasks = {'analyze_dependencies', 'retrieve_evidence', 'verify_findings', 'propose_remediation'}
    recorded_first = bool(set(task_states) == known_tasks)
    gap_reproduced = (recorded_first and provider.blocked_requests > 0 and
                      not tracking.read_calls and task_states.get('analyze_dependencies') == 'FAILED'
                      and task_states.get('retrieve_evidence') == 'FAILED')
    record('Supervisor assigned-task deterministic dispatch', 'GAP' if gap_reproduced else 'NEEDS_REVIEW',
           run_status=outcome.status, task_statuses=task_states,
           blocked_provider_requests=provider.blocked_requests,
           supervisor_tool_reads=tracking.read_calls,
           live_model_network_calls=0)
    record('No model network calls or persistent stores', 'PASS',
           actual_model_network_calls=0, in_memory_runs=len(store.runs),
           persistent_supervisor_runs=0, business_graph_writes=0)


def main():
    try:
        from backend.app.config import Settings
        from backend.app.graph.client import FalkorGraphClient
        from backend.app.services.phase4_graph import GraphSnapshot

        settings = Settings.from_env().model_copy(update={
            'falkordb_graph': GRAPH, 'tenant_id': TENANT,
        })
        client = FalkorGraphClient(settings)
        if client.settings.falkordb_graph != GRAPH or client.settings.tenant_id != TENANT:
            raise RuntimeError('ASTERIA_SCOPE_MISMATCH')
        snapshot = GraphSnapshot.load(client)
        record('Asteria-only graph binding', 'PASS', graph=GRAPH, tenant=TENANT)
        check(snapshot)
    except Exception as exc:
        record('A3 baseline execution', 'FAIL', error_type=type(exc).__name__,
               error_code=str(exc).split(':', 1)[0][:95]
               if isinstance(exc, (ValueError, RuntimeError)) else '')
    outcomes = [item['result'] for item in checks]
    if ('FAIL' not in outcomes and 'NEEDS_REVIEW' not in outcomes and 'GAP' in outcomes):
        verdict = 'A3_BASELINE_GAPS_IDENTIFIED'
    else:
        verdict = 'A3_BASELINE_NEEDS_REVIEW'
    OUTPUT.write_text(json.dumps({'package': 'A3', 'stage': 'preimplementation_baseline',
                                  'graph': GRAPH, 'tenant': TENANT,
                                  'executed_at_utc': datetime.now(timezone.utc).isoformat(),
                                  'outcome': verdict, 'no_real_model_calls': True,
                                  'business_graph_writes': False, 'persistent_runs': False,
                                  'checks': checks}, indent=2), encoding='utf-8')
    print(f'A3 baseline outcome: {verdict}')
    print(f'Saved: {OUTPUT.resolve()}')
    return 0 if verdict == 'A3_BASELINE_GAPS_IDENTIFIED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
