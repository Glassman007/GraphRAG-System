"""Asteria-only Retry Failed Work browser test: create a genuine, bounded failed Supervisor run.

Run in G:\\graphhacks with the existing venv and API running:
  python .\\VERINEX_ASTERIA_retry_button_test2.py

The initial run uses a network-disabled provider. One dependency_impact read is
intentionally failed in-process, creating an actual failed specialist and a
checkpoint. Its evidence-retrieval sibling should complete normally. This
creates operational run/coordination telemetry in Asteria and its agent-memory
store, not business-system changes. The fixture remains for one UI retry.

After clicking Retry failed work in Agent Workspace, use:
  python .\\VERINEX_ASTERIA_retry_button_test2.py --verify

This is a diagnostic, not cleanup or remediation. Never execute on other graphs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GRAPH = 'asteria_company_brain_v1'
TENANT = 'asteria'
INCIDENT = 'INC-AST-ROUTE-OUTAGE'
GOAL = ('Investigate the route orchestration outage and produce an evidence-backed, '
        'read-only remediation proposal. Separate observed facts from hypotheses; '
        'cite real Asteria evidence and identify missing proof. Do not execute changes.')
MARKER = 'ASTERIA_RETRY_BUTTON_TEST2_INJECTED_DEPENDENCY_FAILURE'
OUT = Path('VERINEX_ASTERIA_retry_button_test2_result.json')
API = os.getenv('VERINEX_A1_API_BASE', 'http://127.0.0.1:8000').rstrip('/')
TOKEN = os.getenv('VERINEX_A1_API_TOKEN', 'test-asteria-admin-token')


class BlockedProvider:
    name = 'retry-fixture-network-disabled'
    model = 'none'

    def __init__(self):
        self.calls = 0

    def complete(self, *_args, **_kwargs):
        self.calls += 1
        raise RuntimeError('RETRY_TEST_MODEL_CALL_FORBIDDEN')


def api_get(path: str) -> tuple[int, dict]:
    req = Request(API + path, method='GET', headers={
        'Authorization': 'Bearer ' + TOKEN,
        'X-Tenant-ID': TENANT,
        'X-Company-Brain-ID': GRAPH,
        'Accept': 'application/json',
    })
    try:
        with urlopen(req, timeout=12) as response:
            body = json.loads(response.read(1_500_000).decode('utf-8'))
            return response.status, body if isinstance(body, dict) else {}
    except HTTPError as error:
        return error.code, {}
    except (URLError, TimeoutError, OSError, ValueError) as error:
        raise RuntimeError(f'ASTERIA_API_UNAVAILABLE: {type(error).__name__}') from error


def asteria_client():
    from backend.app.config import Settings
    from backend.app.graph.client import FalkorGraphClient
    settings = Settings.from_env().model_copy(update={
        'tenant_id': TENANT, 'falkordb_graph': GRAPH,
    })
    client = FalkorGraphClient(settings)
    if client.settings.tenant_id != TENANT or client.settings.falkordb_graph != GRAPH:
        raise RuntimeError('ASTERIA_SCOPE_NOT_LOCKED')
    return client


def task_map(rows):
    return {str(row.get('task_id') or row.get('id')): row for row in rows}


def digest_result(result):
    return hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def setup() -> int:
    # Verify UI principal BEFORE persisting anything. Never use another user's run.
    status, session = api_get('/api/v1/session')
    owner = session.get('subject')
    if status != 200 or session.get('tenant_id') != TENANT or not isinstance(owner, str) or not owner:
        raise RuntimeError('AUTHENTICATED_ASTERIA_UI_SESSION_REQUIRED')

    from backend.app.services.phase4_graph import GraphSnapshot, has_label
    from backend.app.agent_runtime.supervisor import Supervisor, SupervisorSettings
    from backend.app.agent_runtime.supervisor_store import GraphSupervisorStore
    from backend.app.agent_runtime.memory_store import GraphMemoryStore
    from backend.app.agent_runtime.memory import AgentMemory
    from backend.app.agent_runtime.workspace import WorkspaceStore, now as workspace_now
    from backend.app.agent_runtime.tools import ToolRegistry

    client = asteria_client()
    snapshot = GraphSnapshot.load(client)
    if not has_label(snapshot.node(INCIDENT), 'Incident'):
        raise RuntimeError('KNOWN_ASTERIA_INCIDENT_UNAVAILABLE')

    # Use only this Python process's environment. Never modify the API server.
    os.environ['VERINEX_A4_HANDOFFS'] = '1'
    run_id = 'SRUN-' + uuid.uuid4().hex.upper()
    settings = SupervisorSettings(
        goal=GOAL, source_entity_id=INCIDENT, max_tasks=4, max_parallel=1,
        max_seconds=90, max_steps_per_task=1, max_retries=0,
        max_tokens_per_task=1000, allow_external_model=True,
    )
    workspace = WorkspaceStore(client)
    entry = {
        'id': run_id, 'owner': owner, 'tenant': TENANT, 'graph_id': GRAPH,
        'goal': GOAL + ' [' + MARKER + ']',
        'source_entity_id': INCIDENT, 'status': 'RUNNING', 'command': '',
        'allow_external_model': True, 'created_at': workspace_now(),
        'updated_at': workspace_now(), 'settings': settings.model_dump(),
        'error': '', 'diagnostic_marker': MARKER,
    }
    workspace.create(entry)
    provider = BlockedProvider()

    class InjectedDependencyFailure(ToolRegistry):
        attempts = 0

        def execute(self, name, arguments):
            if name == 'dependency_impact':
                self.attempts += 1
                raise ValueError('INJECTED_DEPENDENCY_READ_FAILURE_FOR_RETRY_TEST')
            return super().execute(name, arguments)

    tools = InjectedDependencyFailure(lambda: GraphSnapshot.load(client))
    sup_store = GraphSupervisorStore(client)
    backend = GraphMemoryStore(client)
    supervisor = Supervisor(
        provider=provider, tools=tools, store=sup_store,
        tenant=TENANT, permissions=frozenset({'READ_GRAPH', 'READ_EVIDENCE'}),
        memory=AgentMemory(backend=backend, snapshot_factory=lambda: GraphSnapshot.load(client), tenant=TENANT),
    )
    try:
        initial = supervisor.run(settings, subject=owner, run_id=run_id)
        workspace.capture(run_id, owner, {
            'created_at': workspace_now(), 'status': initial.status,
            'answer': initial.answer, 'citations': initial.citations,
            'tasks': [{'id': t['id'], 'status': t['status'], 'result': t.get('result')}
                      for t in initial.tasks],
            'knowledge_gaps': initial.knowledge_gaps,
        })
        workspace.update(run_id, owner, status=initial.status, command='', error=initial.error or '')
    except Exception as exc:
        workspace.update(run_id, owner, status='FAILED', command='', error='RETRY_TEST_SETUP_FAILED: ' + type(exc).__name__)
        raise RuntimeError('RETRY_TEST_SETUP_FAILED; inspect diagnostic run ID ' + run_id) from exc

    cp = backend.load_checkpoint(run_id, owner=owner)
    saved = sup_store.get(run_id) or {}
    rows = task_map(saved.get('tasks') or [])
    states = {name: row.get('status') for name, row in rows.items()}
    expected = {
        'analyze_dependencies': 'FAILED',
        'retrieve_evidence': 'COMPLETED',
        'verify_findings': 'BLOCKED',
        'propose_remediation': 'BLOCKED',
    }
    checks = {
        'injected_failure_executed': tools.attempts >= 1,
        'expected_failed_and_completed_tasks': states == expected,
        'planned_checkpoint_present': bool(cp and len(cp.get('tasks') or []) == 4),
        'record_owned_and_asteria_scoped': bool((workspace.get(run_id, owner) or {}).get('graph_id') == GRAPH),
        'no_model_calls': provider.calls == 0 and initial.tokens_used == 0,
        'persisted_supervisor_readback': len(rows) == 4,
    }
    payload = {
        'phase': 'SETUP', 'run_id': run_id, 'tenant': TENANT, 'graph': GRAPH,
        'created_at_utc': datetime.now(timezone.utc).isoformat(), 'marker': MARKER,
        'initial_status': initial.status, 'initial_tasks': states,
        'checkpoint_revision': (cp or {}).get('revision'),
        'preserve_evidence_attempts': rows.get('retrieve_evidence', {}).get('attempts'),
        'preserve_evidence_digest': digest_result(rows.get('retrieve_evidence', {}).get('result')),
        'initial_handoff_accepted': sum(e.get('kind') == 'HANDOFF_ACCEPTED' for e in saved.get('events') or []),
        'injected_failure_count': tools.attempts,
        'provider_calls': provider.calls,
        'checks': checks,
    }
    payload['verdict'] = 'RETRY_TEST2_READY' if all(checks.values()) else 'RETRY_TEST2_SETUP_NEEDS_REVIEW'
    OUT.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    print('Asteria retry fixture:', payload['verdict'])
    print('Run ID:', run_id)
    print('Task states:', json.dumps(states, sort_keys=True))
    print('Checkpoint revision:', payload['checkpoint_revision'])
    print('Injected failures:', tools.attempts, 'Model calls:', provider.calls)
    print('Scope:', TENANT, GRAPH)
    print('Saved:', OUT.resolve())
    if all(checks.values()):
        print('NEXT: Open this run in Agent Workspace, enable consent, click Retry failed work ONCE.')
    else:
        print('STOP: Do not retry this diagnostic run; send the JSON for investigation.')
    return 0 if all(checks.values()) else 2


def verify() -> int:
    if not OUT.is_file():
        raise RuntimeError('RETRY_TEST2_RESULT_FILE_MISSING: Run setup first')
    payload = json.loads(OUT.read_text(encoding='utf-8'))
    if payload.get('verdict') != 'RETRY_TEST2_READY' or payload.get('graph') != GRAPH or payload.get('tenant') != TENANT:
        raise RuntimeError('NO_VERIFIED_RETRY_FIXTURE')
    run_id = payload['run_id']
    status, session = api_get('/api/v1/session')
    owner = session.get('subject')
    if status != 200 or session.get('tenant_id') != TENANT or not owner:
        raise RuntimeError('AUTHENTICATED_ASTERIA_UI_SESSION_REQUIRED')

    from backend.app.agent_runtime.workspace import WorkspaceStore
    from backend.app.agent_runtime.supervisor_store import GraphSupervisorStore
    from backend.app.agent_runtime.memory_store import GraphMemoryStore
    client = asteria_client()
    workspace = WorkspaceStore(client).get(run_id, owner)
    if not workspace or workspace.get('diagnostic_marker') != MARKER or workspace.get('graph_id') != GRAPH:
        raise RuntimeError('OWNED_TEST_RUN_NOT_FOUND_OR_CHANGED')
    saved = GraphSupervisorStore(client).get(run_id) or {}
    cp = GraphMemoryStore(client).load_checkpoint(run_id, owner=owner)
    rows = task_map(saved.get('tasks') or [])
    states = {name: row.get('status') for name, row in rows.items()}
    events = saved.get('events') or []
    preserved = rows.get('retrieve_evidence') or {}
    initial_accepted = payload.get('initial_handoff_accepted') or 0
    count_accepted = sum(event.get('kind') == 'HANDOFF_ACCEPTED' for event in events)
    checks = {
        'four_tasks_completed': len(states) == 4 and all(s == 'COMPLETED' for s in states.values()),
        'previously_completed_evidence_preserved': bool(preserved.get('status') == 'COMPLETED'
            and preserved.get('attempts') == payload['preserve_evidence_attempts']
            and digest_result(preserved.get('result')) == payload['preserve_evidence_digest']),
        'checkpoint_revision_advanced': bool(cp and (cp.get('revision') or 0) > payload['checkpoint_revision']),
        'retry_resumed_event': any(e.get('kind') == 'RESUMED' for e in events),
        'no_duplicate_accepted_handoff_events': count_accepted <= 3 and count_accepted >= initial_accepted,
        'report_cites_known_incident': bool(saved.get('answer') and INCIDENT in (saved.get('citations') or [])),
    }
    result = {
        'phase': 'VERIFY', 'run_id': run_id, 'workspace_status': workspace.get('status'),
        'supervisor_status': saved.get('status'), 'tasks': states, 'checkpoint_revision': (cp or {}).get('revision'),
        'accepted_handoff_event_count': count_accepted,
        'checks': checks,
        'verdict': 'RETRY_TEST2_PASS' if all(checks.values()) else 'RETRY_TEST2_NEEDS_REVIEW',
    }
    filename = Path('VERINEX_ASTERIA_retry_button_test2_verification_result.json')
    filename.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('Asteria retry execution:', result['verdict'])
    print('Workspace:', result['workspace_status'], 'Supervisor:', result['supervisor_status'])
    print('Task states:', json.dumps(states, sort_keys=True))
    print('Checks:', json.dumps(checks, sort_keys=True))
    print('Saved:', filename.resolve())
    return 0 if all(checks.values()) else 2


def main() -> int:
    parser = argparse.ArgumentParser(description='Asteria-only genuine failed run for UI retry testing')
    parser.add_argument('--verify', action='store_true', help='Inspect the same run after clicking Retry in UI')
    args = parser.parse_args()
    try:
        return verify() if args.verify else setup()
    except Exception as exc:
        # Never display tokens, raw documents or graph contents on diagnostic errors.
        print('[STOP]', type(exc).__name__, str(exc)[:180])
        return 1


if __name__ == '__main__':
    sys.exit(main())
