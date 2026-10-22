"""VERINEX A2, step 1: verify current objective-to-target behavior on Asteria.

Reads ONLY the configured Asteria Company Brain. Uses an in-memory Supervisor
store and a network-disabled provider. Never calls Groq, creates persistent
runs, invokes specialist tools, writes the business graph, or changes source.

Expected current behavior (not claimed as a PASS for A2):
  - explicit canonical Asteria incident has a valid 4-task deterministic DAG
  - unknown explicit ID is rejected before a provider call
  - descriptive objective without ID attempts model-driven decomposition
  - an evidence node given as incident target is not type-rejected up front
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

GRAPH_ID = 'asteria_company_brain_v1'
TENANT_ID = 'asteria'
INCIDENT_ID = 'INC-AST-ROUTE-OUTAGE'
EVIDENCE_ID = 'EVD-AST-0003'
OBJECTIVE = (
    'Investigate the route orchestration outage and produce an evidence-backed, '
    'read-only remediation proposal. Separate observed facts from hypotheses; '
    'cite real Asteria evidence and identify any missing proof. Do not execute changes.'
)
RESULTS: list[dict] = []


def observe(check: str, result: str, **details):
    entry = {'check': check, 'result': result, **details}
    RESULTS.append(entry)
    print(f'[{result}] {check}: ' + ', '.join(f'{k}={v}' for k, v in details.items())[:220])


class NoNetworkProvider:
    """No network path. Records any attempt to use the planner/model."""
    name = 'A2-network-blocked-provider'
    model = 'no-external-model'

    def __init__(self):
        self.calls: list[str] = []

    def complete(self, messages, tools, **kwargs):
        role = 'planner_or_synthesizer' if not tools else 'specialist'
        self.calls.append(role)
        raise RuntimeError('A2_MODEL_CALL_INTERCEPTED_NO_NETWORK')


class InMemoryStore:
    def __init__(self):
        self.runs = []
        self.tasks = []
        self.events = []
        self.result = None

    def start(self, run):
        self.runs.append(run.copy())

    def task(self, run_id, task):
        self.tasks.append(task.copy())

    def event(self, run_id, event):
        self.events.append(event.copy())

    def finish(self, run_id, result):
        self.result = result.copy()


def main() -> int:
    from backend.app.config import Settings
    from backend.app.graph.client import FalkorGraphClient
    from backend.app.services.phase4_graph import GraphSnapshot, has_label
    from backend.app.agent_runtime.supervisor import (
        Supervisor, SupervisorSettings, _incident_plan, validate_dag,
    )
    from backend.app.agent_runtime.tools import ToolRegistry

    settings = Settings.from_env().model_copy(update={
        'falkordb_graph': GRAPH_ID,
        'tenant_id': TENANT_ID,
    })
    client = FalkorGraphClient(settings)
    if client.settings.falkordb_graph != GRAPH_ID or client.settings.tenant_id != TENANT_ID:
        raise RuntimeError('Asteria graph/tenant binding mismatch')
    snapshot = GraphSnapshot.load(client)
    incident = snapshot.node(INCIDENT_ID)
    if not incident or not has_label(incident, 'Incident'):
        observe('Canonical Asteria incident', 'FAIL', incident_present=bool(incident))
        return 2
    observe('Canonical Asteria incident', 'PASS', id=INCIDENT_ID, graph=GRAPH_ID, tenant=TENANT_ID)

    specs = _incident_plan(INCIDENT_ID)
    validate_dag(specs, SupervisorSettings(goal=OBJECTIVE).max_tasks)
    valid = len(specs) == 4 and all(INCIDENT_ID in s.objective for s in specs)
    observe('Existing typed incident DAG', 'PASS' if valid else 'FAIL',
            tasks=[{'id': s.id, 'capability': s.capability, 'depends_on': s.depends_on} for s in specs])

    def supervisor():
        fake = NoNetworkProvider()
        store = InMemoryStore()
        runtime = Supervisor(provider=fake, tools=ToolRegistry(lambda: snapshot),
                             store=store, tenant=TENANT_ID,
                             permissions=frozenset({'READ_GRAPH', 'READ_EVIDENCE'}), memory=None)
        return runtime, fake, store

    bad_id = 'INC-AST-A2-ABSENT-ENTITY'
    if snapshot.node(bad_id):
        observe('Unknown starting entity rejected', 'FAIL', reason='Negative test ID already exists')
    else:
        runtime, fake, store = supervisor()
        try:
            runtime.run(SupervisorSettings(goal=OBJECTIVE, source_entity_id=bad_id,
                                           allow_external_model=True), subject='a2-read-only-probe')
            observe('Unknown starting entity rejected', 'FAIL', reason='Was not rejected')
        except ValueError as exc:
            safe = not fake.calls and not store.runs
            observe('Unknown starting entity rejected', 'PASS' if safe else 'FAIL',
                    exception_type=type(exc).__name__, model_attempts=len(fake.calls))

    runtime, fake, store = supervisor()
    report = runtime.run(SupervisorSettings(goal=OBJECTIVE, allow_external_model=True),
                         subject='a2-read-only-probe')
    attempted = bool(fake.calls)
    observe('Descriptive objective without ID', 'GAP' if attempted else 'PASS',
            provider_attempts=len(fake.calls), provider_is_network_disabled=True,
            status=report.status, selected_source=store.runs[0].get('source_entity_id') if store.runs else None)

    evidence = snapshot.node(EVIDENCE_ID)
    if evidence and has_label(evidence, 'Evidence'):
        runtime, fake, store = supervisor()
        report = runtime.run(SupervisorSettings(goal=OBJECTIVE, source_entity_id=EVIDENCE_ID,
                                                allow_external_model=True), subject='a2-read-only-probe')
        # The current code accepts any existing entity as a source, falling back to
        # the model planner for non-Incident labels; observe but do not assume outcome.
        observe('Incident objective with evidence-node target', 'GAP' if fake.calls else 'INSPECT',
                evidence_id=EVIDENCE_ID, provider_attempts=len(fake.calls),
                status=report.status, source_accepted=bool(store.runs))
    else:
        observe('Incident objective with evidence-node target', 'UNVERIFIED',
                reason='Known Asteria evidence node not available')

    return 2 if any(r['result'] == 'FAIL' for r in RESULTS) else 0


if __name__ == '__main__':
    try:
        exit_code = main()
    except Exception as exc:
        observe('A2 baseline execution', 'FAIL', error_type=type(exc).__name__, detail=str(exc)[:150])
        exit_code = 2
    finally:
        outcome = 'A2_BASELINE_GAPS_IDENTIFIED' if any(r['result'] == 'GAP' for r in RESULTS) else (
            'CHECK_FAILED' if any(r['result'] == 'FAIL' for r in RESULTS) else 'A2_BASELINE_NO_GAPS_OBSERVED'
        )
        result = {
            'package': 'A2', 'stage': 'existing_behavior_only',
            'graph': GRAPH_ID, 'tenant': TENANT_ID,
            'executed_at_utc': datetime.now(timezone.utc).isoformat(),
            'no_external_model_calls': True, 'no_graph_writes': True,
            'no_persistent_supervisor_runs': True,
            'outcome': outcome, 'checks': RESULTS,
        }
        output = Path('VERINEX_A2_target_resolution_baseline_result.json')
        output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print('A2 baseline outcome:', outcome)
        print('Saved:', output.resolve())
    raise SystemExit(exit_code)
