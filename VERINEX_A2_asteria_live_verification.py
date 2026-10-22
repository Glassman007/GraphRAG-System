r"""A2 acceptance: live Asteria target resolution + typed DAG, with no model calls.

Run from the VERINEX main checkout with the existing virtual environment active:
    python .\VERINEX_A2_asteria_live_verification.py

Reads ONLY tenant 'asteria' / graph 'asteria_company_brain_v1'. No API writes,
no Groq calls, no specialist dispatch, no persisted Supervisor runs, no graph
mutations. Every successful plan is immediately paused before scheduling tasks.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

GRAPH = 'asteria_company_brain_v1'
TENANT = 'asteria'
INCIDENT = 'INC-AST-ROUTE-OUTAGE'
EVIDENCE = 'EVD-AST-0003'
GOAL = (
    'Investigate the route orchestration outage and produce an evidence-backed, '
    'read-only remediation proposal. Separate observed facts from hypotheses; '
    'cite real Asteria evidence and identify any missing proof. Do not execute changes.'
)
OUTPUT = Path('VERINEX_A2_asteria_live_verification_result.json')
results: list[dict] = []


def record(name: str, ok: bool, **details):
    row = {'check': name, 'result': 'PASS' if ok else 'FAIL', **details}
    results.append(row)
    short = ', '.join(f'{k}={v}' for k, v in details.items())
    print(f'[{row["result"]}] {name}' + (f': {short[:230]}' if short else ''))


class DisabledProvider:
    name = 'a2-network-disabled'
    model = 'none'

    def __init__(self):
        self.calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError('A2_UNEXPECTED_MODEL_CALL')


class MemoryOnlyStore:
    def __init__(self):
        self.runs = []
        self.tasks = []
        self.events = []
        self.finishes = []

    def start(self, data):
        self.runs.append(dict(data))

    def task(self, run_id, data):
        self.tasks.append(dict(data))

    def event(self, run_id, data):
        self.events.append(dict(data))

    def finish(self, run_id, data):
        self.finishes.append(dict(data))


def check_suite(snapshot):
    from backend.app.agent_runtime.supervisor import (
        Supervisor, SupervisorSettings, TargetResolutionError,
    )
    from backend.app.agent_runtime.tools import ToolRegistry
    from backend.app.services.phase4_graph import has_label

    incident = snapshot.node(INCIDENT)
    evidence = snapshot.node(EVIDENCE)
    if not incident or not has_label(incident, 'Incident'):
        record('Live canonical incident', False, reason='Missing Incident-kind canonical target')
        return
    if not evidence or not has_label(evidence, 'Evidence'):
        record('Live known evidence', False, reason='Missing Evidence-kind negative fixture')
        return
    record('Live Asteria target and evidence', True, incident=INCIDENT, evidence=EVIDENCE)

    all_providers = []
    all_stores = []

    def make():
        provider, store = DisabledProvider(), MemoryOnlyStore()
        all_providers.append(provider)
        all_stores.append(store)
        sup = Supervisor(provider=provider,
                         tools=ToolRegistry(lambda: snapshot), store=store,
                         tenant=TENANT,
                         permissions=frozenset({'READ_GRAPH', 'READ_EVIDENCE'}),
                         memory=None)
        return sup, provider, store

    expected = {
        'analyze_dependencies': ('dependency_analysis', []),
        'retrieve_evidence': ('evidence_retrieval', []),
        'verify_findings': ('verification', ['analyze_dependencies', 'retrieve_evidence']),
        'propose_remediation': ('remediation_proposal', ['verify_findings']),
    }

    def check_plan(name, goal, explicit, expected_method):
        supervisor, provider, store = make()
        report = supervisor.run(
            SupervisorSettings(goal=goal, source_entity_id=explicit,
                               allow_external_model=True, max_tasks=4),
            subject='a2-in-memory-validation',
            control_check=lambda: 'PAUSE',
        )
        # No scheduler assignment or worker execution is permitted in this test.
        dag = {t['id']: (t['capability'], t['depends_on']) for t in report.tasks}
        valid = (
            report.status == 'PAUSED'
            and dag == expected
            and all(t['status'] == 'PENDING' and t['attempts'] == 0 for t in report.tasks)
            and len(store.runs) == 1
            and store.runs[0].get('source_entity_id') == INCIDENT
            and store.runs[0].get('source_resolution_method') == expected_method
            and bool(store.runs[0].get('plan_rationale'))
            and provider.calls == 0
            and report.tokens_used == 0
            and not any(event['kind'] == 'ASSIGN' for event in store.events)
        )
        record(name, valid, status=report.status,
               source=store.runs[0].get('source_entity_id') if store.runs else None,
               method=store.runs[0].get('source_resolution_method') if store.runs else None,
               tasks=len(report.tasks), model_attempts=provider.calls)

    check_plan('Explicit canonical incident plan', GOAL, INCIDENT, 'EXPLICIT_ENTITY')
    check_plan('Descriptive objective resolves incident', GOAL, None, 'UNIQUE_GRAPH_INCIDENT_MATCH')
    check_plan('Objective containing canonical incident ID',
               'Investigate incident INC-AST-ROUTE-OUTAGE and review its source evidence',
               None, 'OBJECTIVE_CANONICAL_ID')

    def must_reject(name, goal, explicit, code):
        supervisor, provider, store = make()
        observed = None
        try:
            supervisor.run(SupervisorSettings(goal=goal, source_entity_id=explicit,
                                             allow_external_model=True),
                           subject='a2-in-memory-validation',
                           control_check=lambda: 'PAUSE')
        except TargetResolutionError as exc:
            observed = str(exc).split(':', 1)[0]
        except Exception as exc:
            observed = type(exc).__name__
        valid = (observed == code and not store.runs and not store.tasks
                 and not store.events and not store.finishes and provider.calls == 0)
        record(name, valid, expected=code, observed=observed,
               persisted_runs=len(store.runs), model_attempts=provider.calls)

    must_reject('Unknown explicit ID rejected', GOAL, 'INC-AST-A2-ABSENT-ENTITY', 'TARGET_NOT_FOUND')
    must_reject('Evidence node rejected for incident objective', GOAL, EVIDENCE, 'TARGET_KIND_MISMATCH')
    must_reject('Underspecified incident requires input',
                'Investigate the incident and cite supporting evidence', None, 'TARGET_NEEDS_INPUT')
    must_reject('Multiple embedded incident IDs rejected',
                'Compare incidents INC-AST-ROUTE-OUTAGE and INC-AST-FORECAST-BIAS using evidence',
                None, 'TARGET_AMBIGUOUS')

    record('No provider calls or persisted telemetry',
           all(p.calls == 0 for p in all_providers),
           model_attempts=sum(p.calls for p in all_providers),
           persistent_store_used=False, workers_dispatched=False)


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
        snapshot = GraphSnapshot.load(client)  # read-only Asteria graph snapshot
        record('Asteria-only graph binding', True, graph=GRAPH, tenant=TENANT)
        check_suite(snapshot)
    except Exception as exc:
        # Avoid printing source records, credentials, prompts, or query payloads.
        record('A2 runtime verification', False, error_type=type(exc).__name__,
               error_code=str(exc).split(':', 1)[0][:90] if isinstance(exc, ValueError) else '')
    finally:
        outcome = 'A2_LIVE_PASS' if results and all(r['result'] == 'PASS' for r in results) else 'A2_LIVE_FAIL'
        data = {
            'package': 'A2', 'stage': 'live_asteria_no_model',
            'graph': GRAPH, 'tenant': TENANT,
            'executed_at_utc': datetime.now(timezone.utc).isoformat(),
            'outcome': outcome,
            'model_network_calls_permitted': False,
            'business_graph_writes': False,
            'persistent_supervisor_runs': False,
            'checks': results,
        }
        OUTPUT.write_text(json.dumps(data, indent=2), encoding='utf-8')
        print(f'A2 live outcome: {outcome}')
        print(f'Saved: {OUTPUT.resolve()}')
    return 0 if outcome == 'A2_LIVE_PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
