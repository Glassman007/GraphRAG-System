"""Asteria-only A4 live integration probe; agent telemetry writes, zero LLM calls.

Prerequisite: A4 patch applied and unit tests passed. Current PowerShell location:
G:\\graphhacks, virtualenv activated. Run: python .\\VERINEX_A4_asteria_live_handoff_probe.py

Creates a new Supervisor run and Phase-6 Plan/Task/Execution/Finding/Handoff
records in Asteria graph. No business-source data, tickets, deployments, or
business application state are modified. Do not use on other tenant/graphs.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

GRAPH = 'asteria_company_brain_v1'
TENANT = 'asteria'
INCIDENT = 'INC-AST-ROUTE-OUTAGE'
GOAL = ('Investigate the route orchestration outage and produce an evidence-backed, '
        'read-only remediation proposal. Separate observed facts from hypotheses, '
        'cite real Asteria evidence, and identify missing proof. Do not execute changes.')
RESULT = Path('VERINEX_A4_asteria_live_handoff_probe_result.json')


class DisabledProvider:
    name = 'network-disabled'
    model = 'none'
    def __init__(self):
        self.attempts = 0
    def complete(self, *args, **kwargs):
        self.attempts += 1
        raise RuntimeError('MODEL_NETWORK_ACCESS_BLOCKED')


def run():
    from backend.app.config import Settings
    from backend.app.graph.client import FalkorGraphClient
    from backend.app.agent_runtime.supervisor import Supervisor, SupervisorSettings
    from backend.app.agent_runtime.supervisor_store import GraphSupervisorStore
    from backend.app.agent_runtime.tools import ToolRegistry
    from backend.app.agent_runtime.asteria_coordination_bridge import AsteriaCoordinationBridge
    from backend.app.services.phase4_graph import GraphSnapshot, has_label

    settings = Settings.from_env().model_copy(update={'tenant_id': TENANT, 'falkordb_graph': GRAPH})
    client = FalkorGraphClient(settings)
    if client.settings.tenant_id != TENANT or client.settings.falkordb_graph != GRAPH:
        raise ValueError('WRONG_GRAPH_OR_TENANT')
    snapshot = GraphSnapshot.load(client)
    if not has_label(snapshot.node(INCIDENT), 'Incident'):
        raise ValueError('MISSING_LIVE_ASTERIA_INCIDENT')
    # Turn on bridge ONLY in this Python process, not the user's API worker.
    os.environ['VERINEX_A4_HANDOFFS'] = '1'
    provider = DisabledProvider()
    sup = Supervisor(provider=provider, tools=ToolRegistry(lambda: GraphSnapshot.load(client)),
        store=GraphSupervisorStore(client), tenant=TENANT,
        permissions=frozenset({'READ_GRAPH','READ_EVIDENCE'}), memory=None)
    record = sup.run(SupervisorSettings(goal=GOAL, source_entity_id=INCIDENT,
        max_tasks=4, max_parallel=2, max_seconds=90, max_steps_per_task=1,
        max_retries=0, max_tokens_per_task=1000, allow_external_model=True),
        subject='asteria-a4-readonly-probe')
    readback = GraphSupervisorStore(client).get(record.id) or {}
    tasks = {item['id']: item for item in record.tasks}
    bridge = AsteriaCoordinationBridge(client, record.id, INCIDENT,
        {name: type('S', (), {'capability': row['capability'], 'agent_id': row['agent_id']})()
         for name, row in tasks.items()})
    boards = {key: bridge.coordination.get_task_blackboard(bridge.task_ids[key]) or {}
              for key in ('verify_findings', 'propose_remediation')}
    verify_ctx = boards['verify_findings'].get('accepted_handoff_context') or []
    remed_ctx = boards['propose_remediation'].get('accepted_handoff_context') or []
    handoffs = [item['handoff']['id'] for item in [*verify_ctx,*remed_ctx]]
    consumed = {}
    for upstream, downstream in [('analyze_dependencies','verify_findings'),
                                  ('retrieve_evidence','verify_findings'),
                                  ('verify_findings','propose_remediation')]:
        try:
            parent = bridge.consume(upstream, downstream)
            consumed[f'{upstream}->{downstream}'] = {'handoff_id': parent['handoff_id'],
                'artifact_ids': parent['artifact_ids'], 'citations': len(parent['result']['citations'])}
        except Exception as exc:
            consumed[f'{upstream}->{downstream}'] = {'error_type': type(exc).__name__,
                'error': str(exc)[:120]}
    checks = {
        'scope': client.settings.tenant_id == TENANT and client.settings.falkordb_graph == GRAPH,
        'four_completed_tasks': len(tasks) == 4 and all(t['status']=='COMPLETED' for t in tasks.values()),
        'report_with_citations': bool(record.answer and record.citations and INCIDENT in record.citations),
        'persistent_supervisor_readback': readback.get('status') == record.status
            and len(readback.get('tasks') or []) == 4,
        'two_accepted_verifier_handoffs': len(verify_ctx) == 2,
        'one_accepted_remediation_handoff': len(remed_ctx) == 1,
        'all_three_handoffs_consumable_from_new_adapter': all('handoff_id' in row for row in consumed.values()),
        'no_model_calls': provider.attempts == 0 and record.tokens_used == 0,
        'supervisor_handoff_consumption_events': sum(e['kind']=='HANDOFF_CONSUMED' for e in record.events) == 3,
    }
    return {'run_id': record.id, 'status': record.status,
            'tasks': {k:v['status'] for k,v in tasks.items()},
            'checks': checks, 'accepted_handoff_ids': handoffs,
            'consumed_artifacts': consumed,
            'tokens': record.tokens_used, 'model_calls': provider.attempts,
            'note': 'Phase-6 execution terminal completion and crash recovery not certified; business graph was read-only except internal coordination telemetry.'}


def main():
    try:
        payload = run()
        all_pass = all(payload['checks'].values())
        payload['verdict'] = 'A4_VERTICAL_PASS' if all_pass else 'A4_VERTICAL_NEEDS_REVIEW'
        print(f"A4 run: {payload['run_id']}, status={payload['status']}")
        for key, value in payload['checks'].items():
            print(f"[{'PASS' if value else 'FAIL'}] {key}")
        print('Accepted handoffs:', payload['accepted_handoff_ids'])
        print('A4 live outcome:', payload['verdict'])
    except Exception as exc:
        payload = {'verdict':'A4_VERTICAL_FAILED', 'error_type':type(exc).__name__,
                   'error':str(exc)[:200], 'note':'Inspect partial Asteria agent telemetry for a failed run; do not assume rollback.'}
        print(f"[FAIL] A4 live probe: {type(exc).__name__}: {str(exc)[:200]}")
        all_pass = False
    payload.update({'package':'A4', 'graph':GRAPH, 'tenant':TENANT,
                    'utc':datetime.now(timezone.utc).isoformat(),
                    'model_network_enabled': False, 'business_side_effects_executed': False})
    RESULT.write_text(json.dumps(payload,indent=2),encoding='utf-8')
    print('Saved:', RESULT.resolve())
    return 0 if all_pass else 1

if __name__ == '__main__':
    raise SystemExit(main())
