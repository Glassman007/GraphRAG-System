"""A1-only, read-only VERINEX preflight against the named Asteria Company Brain.

Run from the main VERINEX checkout with .venv activated:
    python <path-to-this-file>

This DOES NOT create/start a Supervisor run, call a model, change business data,
seed graphs, or enumerate/inspect other tenant graphs. Reads canonical Asteria,
its Asteria-specific agent memory, and optional authenticated HTTP read endpoints.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GRAPH_ID = 'asteria_company_brain_v1'
TENANT = 'asteria'
INCIDENT = 'INC-AST-ROUTE-OUTAGE'
HISTORICAL_RUN_IDS = (
    'SRUN-E633E01597404F9EADB12F19F9B3B894',
    'SRUN-95541002DA8C4855B7E70BFAC73FF47D',
)
API_BASE = os.getenv('VERINEX_A1_API_BASE', 'http://127.0.0.1:8000').rstrip('/')
# Public demo credential from this repo. Replace with a configured Asteria credential
# via VERINEX_A1_API_TOKEN if built-in development credentials are disabled.
TOKEN = os.getenv('VERINEX_A1_API_TOKEN', 'test-asteria-admin-token')
RESULTS: list[dict] = []


def record(check: str, result: str, **details: object) -> None:
    entry = {'check': check, 'result': result, **details}
    RESULTS.append(entry)
    print(f'[{result}] {check}: ' + ', '.join(f'{k}={v}' for k, v in details.items())[:250])


def api_get(path: str) -> tuple[int | None, dict | None, str | None]:
    url = API_BASE + path
    headers = {
        'Authorization': f'Bearer {TOKEN}',
        'X-Tenant-ID': TENANT,
        'X-Company-Brain-ID': GRAPH_ID,
        'Accept': 'application/json',
    }
    req = Request(url, headers=headers, method='GET')
    try:
        with urlopen(req, timeout=8) as resp:
            code = resp.status
            data = json.loads(resp.read(4_000_000).decode('utf-8'))
            return code, data, None
    except HTTPError as exc:
        # Response body deliberately omitted: could contain untrusted/sensitive data.
        return exc.code, None, f'HTTP {exc.code}'
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return None, None, type(exc).__name__


def run() -> int:
    from backend.app.config import Settings
    from backend.app.graph.client import FalkorGraphClient
    from backend.app.services.phase4_graph import GraphSnapshot, has_label
    from backend.app.agent_runtime.tools import ToolRegistry
    from backend.app.agent_runtime.supervisor_store import GraphSupervisorStore
    from backend.app.agent_runtime.workspace import WorkspaceStore

    # Do not use defaults: force this exact Asteria graph and tenant.
    settings = Settings.from_env().model_copy(update={
        'falkordb_graph': GRAPH_ID, 'tenant_id': TENANT,
    })
    client = FalkorGraphClient(settings)
    if client.settings.tenant_id != TENANT or client.settings.falkordb_graph != GRAPH_ID:
        record('Graph scope configuration', 'FAIL')
        return 2

    try:
        snapshot = GraphSnapshot.load(client)
        incident = snapshot.node(INCIDENT)
        if not incident or not has_label(incident, 'Incident'):
            record('Canonical incident exists in Asteria', 'FAIL', found=bool(incident))
            return 2
        record('Canonical incident exists in Asteria', 'PASS', id=INCIDENT,
               graph=GRAPH_ID, tenant=TENANT,
               nodes=len(snapshot.nodes), relationships=len(snapshot.edges))
    except Exception as exc:
        record('Asteria graph read', 'FAIL', error_type=type(exc).__name__, detail=str(exc)[:100])
        return 2

    expected_evidence = ('EVD-AST-0003', 'EVD-AST-0004', 'EVD-AST-0005')
    missing_evidence = [eid for eid in expected_evidence
                        if not snapshot.node(eid) or not has_label(snapshot.node(eid), 'Evidence')]
    record('Known Asteria evidence records', 'PASS' if not missing_evidence else 'FAIL',
           found=[eid for eid in expected_evidence if eid not in missing_evidence],
           missing=missing_evidence)

    registry = ToolRegistry(lambda: GraphSnapshot.load(client))
    tool_checks = (
        ('get_entity', {'entity_id': INCIDENT}),
        ('incident_context', {'entity_id': INCIDENT}),
        ('graph_neighbors', {'entity_id': INCIDENT, 'limit': 6}),
        ('graph_paths', {'entity_id': INCIDENT, 'max_depth': 3}),
    )
    for name, args in tool_checks:
        try:
            output = registry.execute(name, args)
            if output.get('error'):
                record(f'Tool {name}', 'FAIL', error=output['error'])
                continue
            if name == 'get_entity':
                ok = output.get('entity', {}).get('id') == INCIDENT
                count = 1 if ok else 0
            elif name == 'incident_context':
                ok = output.get('incident', {}).get('id') == INCIDENT
                count = sum(len(items) for items in output.get('related', {}).values())
            else:
                key = 'items' if name == 'graph_neighbors' else 'paths'
                count = len(output.get(key, []))
                ok = count > 0
            record(f'Tool {name}', 'PASS' if ok else 'FAIL', item_count=count)
        except Exception as exc:
            record(f'Tool {name}', 'FAIL', error_type=type(exc).__name__, detail=str(exc)[:90])

    try:
        store = GraphSupervisorStore(client)
        for rid in HISTORICAL_RUN_IDS:
            value = store.get(rid)
            if not value:
                record(f'Historical run {rid}', 'UNVERIFIED', reason='No Asteria record')
                continue
            errors = [{'task_id': t.get('task_id'), 'status': t.get('status'),
                       'error': (t.get('error') or '')[:120]}
                      for t in value.get('tasks', []) if t.get('error')]
            tools = [{'task_id': e.get('task_id'), 'summary': (e.get('summary') or '')[:140]}
                     for e in value.get('events', []) if e.get('kind') == 'SPECIALIST_TOOL']
            record(f'Historical run {rid}', 'INSPECTED', status=value.get('status'),
                   source_entity_id=value.get('source_entity_id'),
                   errors=errors[:8], tool_events=tools[:8])
    except Exception as exc:
        record('Historical Supervisor readback', 'UNVERIFIED', error_type=type(exc).__name__, detail=str(exc)[:90])

    try:
        wstore = WorkspaceStore(client)
        # Workspace list requires an owner, which is established via authenticated API;
        # use its graph-specific sidecar only after API confirms identity.
        record('Asteria agent-memory graph binding', 'PASS',
               memory_graph=client.settings.falkordb_graph + '_agent_memory',
               tenant=wstore.tenant)
    except Exception as exc:
        record('Asteria agent-memory graph binding', 'UNVERIFIED', error_type=type(exc).__name__)

    status, session, error = api_get('/api/v1/session')
    if status == 200:
        record('Authenticated Asteria API session', 'PASS', status_code=status)
    else:
        record('Authenticated Asteria API session', 'UNVERIFIED', status_code=status, error=error)
        return 1
    cap_code, capabilities, cap_error = api_get('/api/v1/agent-runtime/workspace/capabilities')
    if cap_code == 200 and isinstance(capabilities, dict):
        record('Agent provider availability (initialization only)', 'INSPECTED',
               configured=capabilities.get('model_configured'),
               provider=capabilities.get('provider'))
    else:
        record('Agent provider availability (initialization only)', 'UNVERIFIED',
               status_code=cap_code, error=cap_error)
    code, listing, error = api_get('/api/v1/agent-runtime/workspace/runs?limit=20')
    if code != 200 or not isinstance(listing, dict):
        record('Asteria Workspace run list', 'FAIL', status_code=code, error=error)
        return 2
    runs = listing.get('items') or []
    if any(r.get('graph_id') != GRAPH_ID or r.get('tenant') != TENANT for r in runs):
        record('Asteria Workspace run list', 'FAIL', reason='Unexpected graph or tenant in result')
        return 2
    record('Asteria Workspace run list', 'PASS', count=len(runs))
    if runs:
        rid = runs[0].get('id')
        if not isinstance(rid, str) or not rid.startswith('SRUN-'):
            record('Asteria Workspace run ID', 'FAIL')
            return 2
        for name, path in (
            ('detail', f'/api/v1/agent-runtime/workspace/runs/{rid}'),
            ('events', f'/api/v1/agent-runtime/workspace/runs/{rid}/events'),
            ('replay', f'/api/v1/agent-runtime/workspace/runs/{rid}/replay'),
        ):
            code, response, error = api_get(path)
            good = code == 200 and isinstance(response, dict)
            if name == 'detail' and good:
                w = response.get('workspace') or {}
                good = w.get('graph_id') == GRAPH_ID and w.get('tenant') == TENANT
            record(f'Asteria Workspace {name} read', 'PASS' if good else 'FAIL',
                   run_id=rid, status_code=code, error=error)
    else:
        record('Asteria Workspace detail/events/replay', 'UNVERIFIED', reason='No existing owned run')

    # Strictly negative authorization check. An intentionally unregistered name;
    # an HTTP 404/403 is expected. Never attempt to access another real graph.
    negative = Request(API_BASE + '/api/v1/session', headers={
        'Authorization': f'Bearer {TOKEN}', 'X-Tenant-ID': TENANT,
        'X-Company-Brain-ID': '__a1_unregistered_graph_probe__',
    }, method='GET')
    try:
        with urlopen(negative, timeout=8) as response:
            record('Unregistered graph denied', 'FAIL', status_code=response.status)
    except HTTPError as exc:
        record('Unregistered graph denied', 'PASS' if exc.code in (403, 404) else 'FAIL', status_code=exc.code)
    except (URLError, TimeoutError, OSError) as exc:
        record('Unregistered graph denied', 'UNVERIFIED', error_type=type(exc).__name__)
    return 2 if any(r['result'] == 'FAIL' for r in RESULTS) else (1 if any(
        r['result'] == 'UNVERIFIED' for r in RESULTS) else 0)


if __name__ == '__main__':
    try:
        exit_code = run()
    except Exception as exc:
        record('Preflight bootstrapping', 'FAIL', error_type=type(exc).__name__, detail=str(exc)[:140])
        exit_code = 2
    final = {
        'package': 'A1', 'graph': GRAPH_ID, 'tenant': TENANT,
        'executed_at_utc': datetime.now(timezone.utc).isoformat(),
        'no_model_calls': True, 'business_data_mutations': False, 'checks': RESULTS,
    }
    # Intentionally writes ONLY a local diagnostic JSON; no graph writes.
    output = Path('VERINEX_A1_asteria_preflight_result.json')
    output.write_text(json.dumps(final, indent=2, default=str), encoding='utf-8')
    print(f'\nA1 read-only results saved to: {output.resolve()}')
    sys.exit(exit_code)
