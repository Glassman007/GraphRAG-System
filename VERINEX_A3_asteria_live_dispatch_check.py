"""Read-only A3 live acceptance probe for VERINEX Asteria.

Run from G:\\graphhacks in an already activated .venv:
    python .\\VERINEX_A3_asteria_live_dispatch_check.py

Loads ONLY asteria_company_brain_v1 into a GraphSnapshot, then executes the
existing Supervisor with a provider that cannot make any network requests.
A lightweight memory-only store is used; the probe pauses before verifier and
remediation tasks. No workspace run, graph write, or Groq call is made.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

GRAPH = 'asteria_company_brain_v1'
TENANT = 'asteria'
INCIDENT = 'INC-AST-ROUTE-OUTAGE'
GOAL = ('Investigate the route orchestration outage and produce an evidence-backed, '
        'read-only remediation proposal. Separate observed facts from hypotheses; '
        'cite real Asteria evidence and identify any missing proof. Do not execute changes.')
OUTPUT = Path('VERINEX_A3_asteria_live_dispatch_check_result.json')


class NetworkDisabledProvider:
    name = 'network-disabled'
    model = 'none'

    def __init__(self):
        self.attempts = 0

    def complete(self, *args, **kwargs):
        self.attempts += 1
        raise RuntimeError('A3_PROVIDER_CALL_BLOCKED_BEFORE_NETWORK')


class EphemeralStore:
    def __init__(self):
        self.runs = []
        self.tasks = {}
        self.events = []
        self.finishes = []

    def start(self, row):
        self.runs.append(dict(row))

    def task(self, _run_id, row):
        self.tasks[row['id']] = dict(row)

    def event(self, _run_id, row):
        self.events.append(dict(row))

    def finish(self, _run_id, row):
        self.finishes.append(dict(row))


def check_live(snapshot):
    from backend.app.agent_runtime.supervisor import Supervisor, SupervisorSettings
    from backend.app.agent_runtime.tools import ToolRegistry
    from backend.app.services.phase4_graph import has_label

    output = []
    def report(name, passed, **details):
        row = {'name': name, 'status': 'PASS' if passed else 'FAIL', **details}
        output.append(row)
        display = ', '.join(f'{key}={value}' for key, value in details.items())
        print(f'[{row["status"]}] {name}' + (f': {display[:300]}' if display else ''))

    incident = snapshot.node(INCIDENT)
    report('Canonical Asteria incident', bool(incident and has_label(incident, 'Incident')),
           entity_id=INCIDENT)
    if not incident or not has_label(incident, 'Incident'):
        return output

    class TrackingTools(ToolRegistry):
        def __init__(self):
            super().__init__(lambda: snapshot)
            self.calls = []

        def execute(self, name, arguments):
            try:
                result = super().execute(name, arguments)
                self.calls.append({'name': name, 'entity_id': arguments.get('entity_id'),
                                   'status': 'ERROR' if result.get('error') else 'READ_OK',
                                   'error': str(result.get('error') or '')[:70]})
                return result
            except Exception as exc:
                self.calls.append({'name': name, 'entity_id': arguments.get('entity_id'),
                                   'status': 'EXCEPTION', 'error': type(exc).__name__})
                raise

    tools = TrackingTools()
    provider = NetworkDisabledProvider()
    store = EphemeralStore()
    supervisor = Supervisor(provider=provider, tools=tools, store=store, tenant=TENANT,
                            permissions=frozenset({'READ_GRAPH', 'READ_EVIDENCE'}), memory=None)

    def pause_before_model_steps():
        return ('PAUSE' if all(store.tasks.get(task_id, {}).get('status') == 'COMPLETED'
                               for task_id in ('analyze_dependencies', 'retrieve_evidence'))
                else '')

    run = supervisor.run(SupervisorSettings(goal=GOAL, source_entity_id=INCIDENT,
                                            allow_external_model=True, max_tasks=4,
                                            max_parallel=1, max_steps_per_task=1,
                                            max_retries=0, max_seconds=45,
                                            max_tokens_per_task=1000),
                         subject='a3-asteria-ephemeral-probe',
                         control_check=pause_before_model_steps)

    tasks = {t['id']: t for t in run.tasks}
    expected = {'analyze_dependencies', 'retrieve_evidence', 'verify_findings', 'propose_remediation'}
    report('Existing incident DAG and pause boundary', set(tasks) == expected and run.status == 'PAUSED',
           run_status=run.status, tasks={k: v['status'] for k, v in tasks.items()})
    initials_ok = all(tasks.get(tid, {}).get('status') == 'COMPLETED'
                      for tid in ('analyze_dependencies', 'retrieve_evidence'))
    report('Assigned deterministic specialist tasks', initials_ok)
    no_later_execution = all(tasks.get(tid, {}).get('status') == 'PENDING'
                             for tid in ('verify_findings', 'propose_remediation'))
    report('Verifier and remediation not started', no_later_execution)

    counts = Counter(c['name'] for c in tools.calls if c['status'] == 'READ_OK')
    all_read_ok = all(c['status'] == 'READ_OK' for c in tools.calls)
    calls_ok = (all_read_ok and counts['incident_context'] >= 2
                and counts['dependency_impact'] >= 1
                and any(c['name'] == 'dependency_impact' and c['entity_id'] == 'SYS-AST-ROUTE-API'
                        for c in tools.calls))
    report('Real Supervisor graph tool dispatch', calls_ok, tool_calls=tools.calls)

    required = {'EVD-AST-0003', 'EVD-AST-0004', 'EVD-AST-0005'}
    evidence_ok = True
    summaries = {}
    for task_id in ('analyze_dependencies', 'retrieve_evidence'):
        finding = tasks.get(task_id, {}).get('result') or {}
        cites = set(finding.get('citations', []))
        valid = bool(finding and INCIDENT in cites and required.issubset(cites)
                     and all(snapshot.node(cid) for cid in cites)
                     and finding.get('confidence') in ('uncertain', 'supported')
                     and finding.get('knowledge_gaps'))
        evidence_ok &= valid
        summaries[task_id] = {'valid': valid, 'citations_count': len(cites),
                              'known_evidence_cited': sorted(required & cites),
                              'confidence': finding.get('confidence'),
                              'knowledge_gap_count': len(finding.get('knowledge_gaps') or [])}
    report('Canonical evidence and uncertainty retained', evidence_ok, findings=summaries)

    skill_events = [e for e in store.events if e.get('kind') == 'SKILL_RESULT']
    tool_events = [e for e in store.events if e.get('kind') == 'SPECIALIST_TOOL']
    report('Persistable tool and skill events produced in memory',
           len(skill_events) >= 2 and len(tool_events) >= 3,
           skill_events=len(skill_events), tool_events=len(tool_events))
    report('No model calls or persistent supervisor/graph writes',
           provider.attempts == 0 and run.tokens_used == 0 and len(store.runs) == 1,
           provider_attempts=provider.attempts, tokens=run.tokens_used,
           in_memory_runs=len(store.runs), business_graph_writes=0)
    return output


def main():
    checks = []
    try:
        from backend.app.config import Settings
        from backend.app.graph.client import FalkorGraphClient
        from backend.app.services.phase4_graph import GraphSnapshot

        settings = Settings.from_env().model_copy(update={'falkordb_graph': GRAPH, 'tenant_id': TENANT})
        client = FalkorGraphClient(settings)
        if client.settings.falkordb_graph != GRAPH or client.settings.tenant_id != TENANT:
            raise RuntimeError('ASTERIA_SCOPE_MISMATCH')
        snapshot = GraphSnapshot.load(client)
        print(f'[PASS] Asteria graph scope: graph={GRAPH}, tenant={TENANT}')
        checks = check_live(snapshot)
    except Exception as exc:
        message = str(exc)
        checks.append({'name': 'Live Asteria probe setup', 'status': 'FAIL',
                       'error_type': type(exc).__name__, 'error_prefix': message.split(':', 1)[0][:100]})
        print(f'[FAIL] Live Asteria probe setup: {type(exc).__name__}: {message[:180]}')
    verdict = 'A3_LIVE_PASS' if checks and all(c['status'] == 'PASS' for c in checks) else 'A3_LIVE_NEEDS_REVIEW'
    OUTPUT.write_text(json.dumps({'package': 'A3', 'scope': {'graph': GRAPH, 'tenant': TENANT},
                                  'time_utc': datetime.now(timezone.utc).isoformat(),
                                  'verdict': verdict, 'checks': checks,
                                  'provider_network_enabled': False,
                                  'persistent_supervisor_store': False}, indent=2), encoding='utf-8')
    print(f'A3 live outcome: {verdict}')
    print(f'Saved: {OUTPUT.resolve()}')
    return 0 if verdict == 'A3_LIVE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
