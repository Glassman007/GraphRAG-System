"""A1 Asteria-only authenticated Workspace readback with a disposable diagnostic record.

Run from G:\\graphhacks with .venv already activated:
    python .\\VERINEX_A1_workspace_readback_probe.py

Only mutates the Asteria *_agent_memory graph to create and remove its own
marked test Workspace record. Never starts an agent, calls Groq, or edits the
business graph. A detail/events/replay 200 response with empty Supervisor data
proves scope-bound API readback, NOT end-to-end Supervisor execution.
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GRAPH = 'asteria_company_brain_v1'
TENANT = 'asteria'
INCIDENT = 'INC-AST-ROUTE-OUTAGE'
API = os.getenv('VERINEX_A1_API_BASE', 'http://127.0.0.1:8000').rstrip('/')
TOKEN = os.getenv('VERINEX_A1_API_TOKEN', 'test-asteria-admin-token')
PREFIX = '/api/v1/agent-runtime/workspace/runs'
OUT = Path('VERINEX_A1_workspace_readback_probe_result.json')
MARKER = 'A1_SCOPE_READBACK_TEST_ONLY_NO_AGENT_EXECUTION'


def get(path: str, graph: str = GRAPH) -> tuple[int | None, object | None, str | None]:
    req = Request(API + path, method='GET', headers={
        'Authorization': 'Bearer ' + TOKEN,
        'X-Tenant-ID': TENANT,
        'X-Company-Brain-ID': graph,
        'Accept': 'application/json',
    })
    try:
        with urlopen(req, timeout=12) as response:
            return response.status, json.loads(response.read(2_000_000).decode('utf-8')), None
    except HTTPError as error:
        return error.code, None, 'HTTP_REJECTED'
    except (URLError, TimeoutError, OSError, ValueError) as error:
        return None, None, type(error).__name__


def main() -> int:
    result: dict = {
        'package': 'A1', 'graph': GRAPH, 'tenant': TENANT,
        'executed_at_utc': datetime.now(timezone.utc).isoformat(),
        'model_calls': 0, 'business_graph_writes': 0,
        'agent_memory_diagnostic_record_created': False,
        'agent_memory_diagnostic_record_removed': False,
        'checks': {},
    }
    client = None
    run_id = None
    owner = None
    created = False
    try:
        status, session, error = get('/api/v1/session')
        if status != 200 or not isinstance(session, dict):
            raise RuntimeError('Authenticated Asteria session unavailable: ' + str(status or error))
        if session.get('tenant_id') != TENANT:
            raise RuntimeError('Authenticated session tenant mismatch; refusing all writes')
        owner = session.get('subject')
        if not isinstance(owner, str) or not owner or len(owner) > 256:
            raise RuntimeError('Invalid authenticated subject; refusing all writes')
        result['checks']['session'] = 'PASS'

        # Asteria-only connection. No other graph is opened or examined.
        from backend.app.config import Settings
        from backend.app.graph.client import FalkorGraphClient
        from backend.app.agent_runtime.workspace import WorkspaceStore, now as workspace_now
        from backend.app.services.phase4_graph import GraphSnapshot, has_label
        settings = Settings.from_env().model_copy(update={
            'falkordb_graph': GRAPH, 'tenant_id': TENANT,
        })
        client = FalkorGraphClient(settings)
        if client.settings.falkordb_graph != GRAPH or client.settings.tenant_id != TENANT:
            raise RuntimeError('Local graph settings mismatch; refusing all writes')
        snap = GraphSnapshot.load(client)
        if not (snap.node(INCIDENT) and has_label(snap.node(INCIDENT), 'Incident')):
            raise RuntimeError('Canonical Asteria incident not present; refusing all writes')
        result['checks']['canonical_asteria_target'] = 'PASS'

        run_id = 'SRUN-' + uuid.uuid4().hex.upper()
        if not re.fullmatch(r'SRUN-[A-F0-9]{32}', run_id):
            raise RuntimeError('Internal diagnostic ID invalid')
        entry = {
            'id': run_id, 'owner': owner, 'tenant': TENANT, 'graph_id': GRAPH,
            'goal': MARKER, 'source_entity_id': INCIDENT,
            'status': 'NEEDS_REVIEW', 'command': '',
            'allow_external_model': False, 'created_at': workspace_now(),
            'updated_at': workspace_now(), 'settings': {},
            'error': MARKER, 'a1_diagnostic': True,
        }
        store = WorkspaceStore(client)
        store.create(entry)
        created = True
        result['agent_memory_diagnostic_record_created'] = True
        result['diagnostic_run_id'] = run_id

        code, body, _ = get(PREFIX + '?limit=20')
        items = body.get('items') if isinstance(body, dict) else None
        found = [x for x in (items or []) if isinstance(x, dict) and x.get('id') == run_id]
        list_ok = code == 200 and isinstance(items, list) and len(found) == 1
        list_ok = list_ok and found[0].get('graph_id') == GRAPH and found[0].get('tenant') == TENANT
        list_ok = list_ok and all(isinstance(x, dict) and x.get('graph_id') == GRAPH
                                 and x.get('tenant') == TENANT for x in items)
        result['checks']['list_contains_only_scoped_fixture'] = 'PASS' if list_ok else 'FAIL'
        result['list_http_status'] = code

        detail_code, detail, _ = get(f'{PREFIX}/{run_id}')
        ws = detail.get('workspace') if isinstance(detail, dict) else None
        detail_ok = detail_code == 200 and isinstance(ws, dict) and (
            ws.get('id') == run_id and ws.get('graph_id') == GRAPH and ws.get('tenant') == TENANT)
        # No Supervisor was run; these should be empty, not fabricated.
        detail_ok = detail_ok and detail.get('supervisor') is None
        result['checks']['detail_readback'] = 'PASS' if detail_ok else 'FAIL'
        result['detail_http_status'] = detail_code

        events_code, events, _ = get(f'{PREFIX}/{run_id}/events')
        events_ok = events_code == 200 and isinstance(events, dict) and events.get('items') == []
        result['checks']['events_readback_without_execution'] = 'PASS' if events_ok else 'FAIL'
        result['events_http_status'] = events_code

        replay_code, replay, _ = get(f'{PREFIX}/{run_id}/replay')
        replay_ok = (replay_code == 200 and isinstance(replay, dict)
                     and replay.get('events') == [] and replay.get('tasks') == [])
        result['checks']['replay_readback_without_execution'] = 'PASS' if replay_ok else 'FAIL'
        result['replay_http_status'] = replay_code

        denied_code, _, _ = get(f'{PREFIX}/{run_id}', graph='__a1_unregistered_graph_probe__')
        deny_ok = denied_code in (403, 404)
        result['checks']['invalid_graph_denied'] = 'PASS' if deny_ok else 'FAIL'
        result['invalid_graph_http_status'] = denied_code

    except Exception as error:
        # Never print credentials, raw documents, or any upstream HTTP body.
        result['error_type'] = type(error).__name__
        if isinstance(error, RuntimeError):
            result['error_summary'] = str(error)[:160]
    finally:
        if created and client is not None and run_id is not None and owner is not None:
            try:
                # Delete ONLY the unique fixture this script created, and only
                # when its explicit diagnostic marker still matches.
                memory_graph = client.db.select_graph(GRAPH + '_agent_memory')
                memory_graph.query('''MATCH (w:AgentWorkspaceRun {tenant_id:$tenant,id:$id,owner:$owner})
                    WHERE w.document_json CONTAINS $marker DELETE w''', {
                    'tenant': TENANT, 'id': run_id, 'owner': owner, 'marker': MARKER,
                })
                remaining = WorkspaceStore(client).get(run_id, owner)
                result['agent_memory_diagnostic_record_removed'] = remaining is None
            except Exception as error:
                result['cleanup_error_type'] = type(error).__name__

        expected = ('session', 'canonical_asteria_target',
                    'list_contains_only_scoped_fixture', 'detail_readback',
                    'events_readback_without_execution', 'replay_readback_without_execution',
                    'invalid_graph_denied')
        result['outcome'] = ('PASS' if all(result['checks'].get(x) == 'PASS' for x in expected)
                              and result['agent_memory_diagnostic_record_removed'] else 'PARTIAL')
        OUT.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print('A1 Workspace authenticated readback:', result['outcome'])
        print('Checks:', json.dumps(result['checks'], sort_keys=True))
        print('Diagnostic cleanup:', 'PASS' if result['agent_memory_diagnostic_record_removed'] else 'NEEDS_REVIEW')
        print('Model calls: 0; business graph writes: 0')
        if 'error_type' in result:
            print('Error type:', result['error_type'], result.get('error_summary', ''))
        if 'cleanup_error_type' in result:
            print('Cleanup error type:', result['cleanup_error_type'])
        print('Saved:', OUT.resolve())
    return 0 if result['outcome'] == 'PASS' else 2


if __name__ == '__main__':
    sys.exit(main())
