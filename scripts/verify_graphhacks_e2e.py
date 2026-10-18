"""GraphHacks/Asteria end-to-end acceptance orchestrator (safe by default).

Offline: python scripts/verify_graphhacks_e2e.py --mode offline
Full:    python scripts/verify_graphhacks_e2e.py --mode full

Full mode tests a fresh, uniquely named FalkorDB graph with its own local FastAPI
and Vite processes. It NEVER sends POST/PATCH/DELETE to Northstar or the user's
asteria_company_brain_v1 graph. Only generated test graphs can be deleted.
Tests are evidence of their actual scope, NOT of autonomous LLM execution.
"""
from __future__ import annotations

import argparse
import datetime as datetime
import hashlib
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FRONTEND = ROOT / 'frontend'
DEFAULT_REPORT = ROOT / 'reports' / 'graphhacks_e2e'
PREFIX = 'graphhacks_e2e_'
PROTECTED_GRAPHS = {'company_brain', 'asteria_company_brain_v1'}
TENANT = 'asteria'
TOKEN = 'test-asteria-admin-token'  # built-in local development principal only


class Reporter:
    def __init__(self, graph: str, mode: str):
        self.started = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.graph = graph
        self.mode = mode
        self.checks: list[dict] = []
        self.notes: list[str] = []

    def add(self, name: str, layer: str, status: str, detail: str = '', *, scenario: str | None = None, evidence: dict | None = None):
        assert status in {'PASS', 'FAIL', 'BLOCKED', 'NOT_TESTED'}
        row = {'name': name, 'layer': layer, 'status': status, 'detail': str(detail)[:1200]}
        if scenario: row['scenario_id'] = scenario
        if evidence: row['evidence'] = evidence
        self.checks.append(row)
        print(f'[{status:10}] {layer}: {name}' + (f' [{scenario}]' if scenario else ''))

    def export(self, target: Path, scenarios: list[dict]):
        target.mkdir(parents=True, exist_ok=True)
        counts = dict(Counter(r['status'] for r in self.checks))
        per_case = {}
        for s in scenarios:
            relevant = [r for r in self.checks if r.get('scenario_id') == s['scenario_id']]
            statuses = [r['status'] for r in relevant]
            checked_layers = {r['layer'] for r in relevant if r['status'] == 'PASS'}
            outcome = ('FAIL' if 'FAIL' in statuses else 'BLOCKED' if 'BLOCKED' in statuses else
                       'NOT_TESTED' if not statuses or all(t == 'NOT_TESTED' for t in statuses) else
                       'PARTIALLY_VERIFIED' if 'NOT_TESTED' in statuses else
                       'PASS_API_READS_ONLY' if 'scenario-api' in checked_layers else
                       'PASS_GRAPH_STRUCTURE_ONLY' if 'live-graph' in checked_layers else 'PASS_FIXTURE_ONLY')
            per_case[s['scenario_id']] = {'track': s['track'], 'title': s['title'], 'status': outcome,
                                          'checked_assertions': len(relevant)}
        obj = {'version': 1, 'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'started_at': self.started, 'mode': self.mode, 'isolation_graph': self.graph,
               'protected_graphs_not_mutated': sorted(PROTECTED_GRAPHS),
               'summary': counts, 'scenario_results': per_case, 'checks': self.checks,
               'notes': self.notes,
               'scope': 'PASS applies only to the stated assertion. Offline fixtures, live reads, isolated work mutations and browser interactions are evaluated separately. No autonomous agents or production connectors are certified.'}
        (target / 'acceptance.json').write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')
        rows = ''.join('<tr>' + ''.join(f'<td>{html.escape(str(x))}</td>' for x in
                       (r['status'], r['layer'], r.get('scenario_id', ''), r['name'], r['detail'])) + '</tr>' for r in self.checks)
        case_rows = ''.join('<tr>' + ''.join(f'<td>{html.escape(str(x))}</td>' for x in
                            (sid, value['track'], value['title'], value['status'])) + '</tr>' for sid, value in per_case.items())
        css = 'body{font:14px system-ui;margin:30px;max-width:1250px;background:#101511;color:#e9f9ee} table{border-collapse:collapse;width:100%;margin:16px 0 32px}td,th{border:1px solid #3d5942;padding:7px;text-align:left}th{background:#18321e}h1,h2{color:#5bf582}.warn{color:#ffd78d}'
        page = (f'<!doctype html><html lang="en"><meta charset="utf-8"><title>GraphHacks Acceptance</title><style>{css}</style>'
                f'<h1>GraphHacks Acceptance Report</h1><p>{html.escape(obj["generated_at"])} · {html.escape(self.mode)} · isolated graph {html.escape(self.graph)}</p>'
                f'<p class="warn">No automatic agent-autonomy certification. PASS is assertion-scoped.</p>'
                f'<p>Summary: {html.escape(str(counts))}</p><h2>24 scenarios</h2><table><tr><th>ID</th><th>Track</th><th>Title</th><th>Status</th></tr>{case_rows}</table>'
                f'<h2>Detailed results</h2><table><tr><th>Status</th><th>Layer</th><th>Scenario</th><th>Check</th><th>Detail</th></tr>{rows}</table></html>')
        (target / 'acceptance.html').write_text(page, encoding='utf-8')
        print(f'\nJSON report: {target / "acceptance.json"}\nHTML report: {target / "acceptance.html"}')
        return obj


def safe_message(exc: Exception) -> str:
    # Do not include auth tokens, environment values or evidence bodies in reports.
    return f'{type(exc).__name__}: {str(exc).replace(TOKEN, "[REDACTED]")[:350]}'


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return int(s.getsockname()[1])


def tool(name: str) -> str | None:
    candidates = ([name + '.cmd', name] if os.name == 'nt' else [name])
    return next((p for c in candidates if (p := shutil.which(c))), None)


def wait_url(url: str, process: subprocess.Popen, seconds: int = 35):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if process.poll() is not None: raise RuntimeError('Local process exited before it became ready')
        try:
            with urlopen(url, timeout=2) as response:
                if response.status < 500: return
        except (OSError, URLError, TimeoutError):
            pass
        time.sleep(.4)
    raise TimeoutError('Local service startup timed out')


def api(base: str, path: str, *, method='GET', body=None, token=TOKEN, tenant=TENANT):
    headers = {'Accept': 'application/json', 'X-Tenant-ID': tenant}
    if token is not None: headers['Authorization'] = f'Bearer {token}'
    if body is not None: headers['Content-Type'] = 'application/json'
    req = Request(base + '/api/v1' + path, data=json.dumps(body).encode() if body is not None else None,
                  headers=headers, method=method)
    try:
        with urlopen(req, timeout=22) as r:
            return r.status, json.loads(r.read(6_000_000).decode('utf-8'))
    except HTTPError as e:
        return e.code, {'error': 'HTTP rejection', 'request_id': e.headers.get('x-request-id')}


def run_command(args: list[str], cwd: Path, env=None, timeout=180) -> dict:
    try:
        done = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, errors='replace', timeout=timeout)
        output = done.stdout + '\n' + done.stderr
        return {'code': done.returncode, 'tail': ('\n'.join(output.splitlines()[-35:]))[:3600],
                'output': output}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'code': None, 'tail': safe_message(e), 'output': safe_message(e)}


def offline_checks(report: Reporter):
    from scripts.verify_step4_demo import offline
    summary = offline()
    report.add('Fixture pack, catalog and acceptance-matrix consistency', 'offline',
               'PASS' if summary['ok'] else 'FAIL', '; '.join(summary['errors']) or '24 versioned scenario contracts checked')
    for case in summary['cases']:
        report.add('Withheld structural contract', 'fixture', 'PASS' if case['status'] == 'PASS_FIXTURE' else 'FAIL',
                   'Fixture graph only; not a live workflow result', scenario=case['scenario_id'])
    return summary['ok']


def live_graph_checks(report: Reporter):
    from scripts.seed_asteria import target_settings
    from scripts.validate_asteria_pack import load_data
    from scripts.verify_asteria_live import verify
    from backend.app.graph.client import FalkorGraphClient
    from backend.app.services.phase4_graph import GraphSnapshot
    manifest, _, scenarios, truth = load_data()
    client = FalkorGraphClient(target_settings())  # explicit canonical Asteria; read-only
    snapshot = GraphSnapshot.load(client)
    outcome = verify(snapshot, manifest, scenarios, truth)
    report.add('Existing Asteria graph matches scenario contracts', 'live-graph', 'PASS' if outcome['ok'] else 'FAIL',
               f'nodes={outcome["nodes_read"]} edges={outcome["edges_read"]}; first errors={outcome["errors"][:2]}')
    for sid, item in outcome['scenarios'].items():
        report.add('Live FalkorDB structural contract', 'live-graph', 'PASS' if item['pass'] else 'FAIL',
                   '; '.join(item['errors'][:2]) if item['errors'] else 'Required paths, typed edges, temporal and negative assertions', scenario=sid)
    return outcome['ok']


def graph_fingerprint(name: str, tenant: str) -> str:
    """Read-only checksum of graph topology, node and edge properties."""
    from backend.app.config import Settings
    from backend.app.graph.client import FalkorGraphClient
    from backend.app.services.phase4_graph import GraphSnapshot
    settings = Settings.from_env().model_copy(update={'falkordb_graph': name, 'tenant_id': tenant})
    snap = GraphSnapshot.load(FalkorGraphClient(settings))
    material = {'nodes': sorted((k, v) for k, v in snap.nodes.items()),
                'edges': sorted((e.as_dict() for e in snap.edges),
                                key=lambda v: json.dumps(v, sort_keys=True, default=str))}
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()


def sandbox_graph_settings(name: str):
    from backend.app.config import Settings
    if not re.fullmatch(r'graphhacks_e2e_[0-9a-f]{16}', name) or name in PROTECTED_GRAPHS:
        raise RuntimeError('Invalid temporary graph name; refusing writes')
    return Settings.from_env().model_copy(update={'falkordb_graph': name, 'tenant_id': TENANT})


def sandbox_seed(name: str, reporter: Reporter):
    from backend.app.graph.client import FalkorGraphClient
    from backend.app.graph.schema import apply_schema
    from backend.app.graph.mutations import upsert_node, upsert_relationship
    from scripts.validate_asteria_pack import load_data
    client = FalkorGraphClient(sandbox_graph_settings(name))
    # A UUID-derived graph must not exist yet. If it does, stop without deleting it.
    try:
        db_graphs = client.db.list_graphs()
        if name in db_graphs:
            raise RuntimeError('Temporary graph already exists; refusing to overwrite it')
    except AttributeError:
        raise RuntimeError('Installed FalkorDB client does not support list_graphs; cannot establish safe isolation')
    _, batches, _, _ = load_data()
    nodes = 0
    edges = 0
    # Once we start creating our unique graph, even a partial failure must clean it up.
    try:
        apply_schema(client)
        for batch in batches:
            for item in batch['nodes']:
                upsert_node(client, item['label'], item['id'], item['properties'])
                nodes += 1
        for batch in batches:
            for item in batch['edges']:
                upsert_relationship(client, item['source'], item['type'], item['target'], item['properties'])
                edges += 1
    except Exception:
        try: client.delete_graph()
        except Exception: reporter.notes.append(f'Check partially seeded isolated graph: {name}')
        raise
    reporter.add('Unique graph populated from synthetic Asteria fixtures', 'isolation', 'PASS',
                 f'graph={name}; nodes={nodes}; edges={edges}; never touches existing graphs')
    return client


def isolated_api_checks(base: str, report: Reporter, scenarios: list[dict]):
    """Only this locally launched API receives mutations."""
    status, session = api(base, '/session')
    report.add('Valid Asteria test principal', 'api-auth', 'PASS' if status == 200 and session.get('tenant_id') == TENANT else 'FAIL', f'http={status}; tenant={session.get("tenant_id")}')
    status, _ = api(base, '/session', token=None)
    report.add('Missing credentials rejected', 'api-auth', 'PASS' if status == 401 else 'FAIL', f'http={status}')
    status, _ = api(base, '/session', tenant='northstar')
    report.add('Cross-tenant request rejected', 'api-auth', 'PASS' if status == 403 else 'FAIL', f'http={status}')
    status, statuses = api(base, '/situations/statuses')
    report.add('Status dropdown API', 'api', 'PASS' if status == 200 and 'OPEN' in statuses.get('items', []) else 'FAIL', f'http={status}; statuses={statuses.get("items", [])}')
    needle = 'INC-AST-ROUTE-OUTAGE'
    status, found = api(base, '/situations?' + urlencode({'q': needle, 'limit': 50}))
    hits = [x.get('id') for x in found.get('items', [])]
    report.add('Situation search by exact canonical ID', 'api', 'PASS' if status == 200 and needle in hits else 'FAIL', f'http={status}; returned={hits[:6]}')
    status, found = api(base, '/situations?' + urlencode({'q': 'Route Orchestration API', 'limit': 100}))
    report.add('Situation search accepts connected system names', 'api', 'PASS' if status == 200 and len(found.get('items', [])) > 0 else 'FAIL', f'http={status}; matches={len(found.get("items", []))}')
    status, empty = api(base, '/situations?' + urlencode({'q': 'unlikely-no-match-893d55', 'limit': 50}))
    report.add('Search empty-state API result', 'api', 'PASS' if status == 200 and not empty.get('items') else 'FAIL', f'http={status}')
    # All 24 scenarios receive actual HTTP entity and neighbor verification.
    for case in scenarios:
        sid = case['scenario_id']
        ids = case['entry_ids']
        failures = []
        for node_id in ids:
            enc = quote(node_id, safe='')
            st, entity = api(base, '/entities/' + enc)
            if st != 200 or entity.get('id') != node_id: failures.append(f'entity {node_id} HTTP {st}')
            st, neighbors = api(base, '/entities/' + enc + '/neighbors?limit=100')
            if st != 200 or not isinstance(neighbors.get('items'), list): failures.append(f'neighbors {node_id} HTTP {st}')
        if ids[0].startswith('INC-'):
            st, context = api(base, '/situations/' + quote(ids[0], safe='') + '/context')
            if st != 200 or not context.get('situation'): failures.append(f'context HTTP {st}')
        report.add('Scenario root and graph-neighbor API', 'scenario-api', 'FAIL' if failures else 'PASS',
                   '; '.join(failures) if failures else 'Canonical entity and bounded relationships returned; no agent autonomy asserted', scenario=sid)
        # Focus objects must also be discoverable, not only the scenario entry.
        focus_errors = []
        historical_reads = []
        for node_id in case.get('focus_ids', [])[:8]:
            entity_path = '/entities/' + quote(node_id, safe='')
            st, obj = api(base, entity_path)
            # Superseded records have no current entity view, by design. In that case
            # validate the historic record AND a time-scoped read instead of calling
            # an expected current-time 404 an application regression.
            if st == 404:
                history_status, history = api(base, entity_path + '/history')
                old = history.get('entity') if isinstance(history, dict) else None
                until = old.get('valid_until') if isinstance(old, dict) else None
                if history_status == 200 and isinstance(old, dict) and old.get('id') == node_id and until:
                    try:
                        point = (datetime.datetime.fromisoformat(str(until).replace('Z', '+00:00'))
                                 - datetime.timedelta(seconds=1)).isoformat()
                        prior_status, prior = api(base, entity_path + '?' + urlencode({'as_of': point}))
                        if prior_status == 200 and prior.get('id') == node_id:
                            historical_reads.append(node_id)
                            continue
                        focus_errors.append(f'{node_id} historical read: HTTP {prior_status}')
                    except (ValueError, TypeError) as exc:
                        focus_errors.append(f'{node_id} invalid history timestamp: {type(exc).__name__}')
                else:
                    focus_errors.append(f'{node_id} current HTTP 404, history HTTP {history_status}')
            elif st != 200 or obj.get('id') != node_id:
                focus_errors.append(f'{node_id}: HTTP {st}')
            if node_id.startswith('EVD-'):
                prov_code, provenance = api(base, '/evidence/' + quote(node_id, safe='') + '/provenance')
                if prov_code != 200:
                    focus_errors.append(f'{node_id} provenance: HTTP {prov_code}')
        report.add('Focused records and evidence provenance', 'scenario-api',
                   'FAIL' if focus_errors else 'PASS',
                   '; '.join(focus_errors[:5]) if focus_errors else
                   ('Focused entities readable; historical as_of validated: ' + ', '.join(historical_reads)
                    if historical_reads else 'Focused entities readable; evidence lineage fetched where applicable'),
                   scenario=sid)
        report.add('Autonomous agent outcome', 'agent-runtime', 'NOT_TESTED',
                   'No autonomous model/tool scheduler is exercised by this runner', scenario=sid)
    # Bounded, actual API records are compared. These are context-coverage counts,
    # never claims about response correctness or LLM intelligence.
    st_node, node = api(base, '/entities/INC-AST-ROUTE-OUTAGE')
    st_links, links = api(base, '/entities/INC-AST-ROUTE-OUTAGE/neighbors?limit=100')
    st_context, context = api(base, '/situations/INC-AST-ROUTE-OUTAGE/context')
    report.add('Isolated incident versus connected context', 'baseline-comparison',
               'PASS' if st_node == st_links == st_context == 200 and len(links.get('items', [])) > 0 else 'FAIL',
               f'isolated_entity={bool(node.get("id"))}, graph_links={len(links.get("items", []))}, '
               f'evidence={len(context.get("evidence", []))}, claims={len(context.get("claims", []))}; no LLM benchmark',
               scenario='AST-AA-01')
    for label, path in [
        ('Route DB blast radius', '/entities/SYS-AST-ROUTE-DB/blast-radius?max_depth=5'),
        ('Historical ownership', '/entities/SYS-AST-OLD-CARRIER/history'),
        ('Expertise registry', '/company-brain/expertise?limit=50'),
        ('Task coordination', '/tasks/TASK-AST-DEADLOCK-A/coordination-state'),
        ('Work task insights', '/work/tasks/TASK-AST-DEADLOCK-A/insights'),
        ('Agent registry', '/agents'),
        ('Governance status', '/actions/ACT-AST-ROLLBACK/governance'),
        ('Claim contradiction', '/claims/CLM-AST-ROUTE-CPU/conflicts'),
        ('Evidence provenance', '/evidence/EVD-AST-0001/provenance'),
        ('Agent handoff validation', '/work/contracts/HANDOFF-AST-VALID/validation')]:
        st, _ = api(base, path)
        report.add(label, 'capability-api', 'PASS' if st == 200 else 'FAIL', f'http={st}; read-only')
    # Write only to this temporary graph, via the newly launched local test API.
    st, inv = api(base, '/investigations', method='POST', body={
        'situation_id': 'INC-AST-ROUTE-OUTAGE', 'question': 'Acceptance test: inspect connected outage evidence',
        'seed_entity_ids': ['INC-AST-ROUTE-OUTAGE', 'SYS-AST-ROUTE-DB']})
    inv_id = str(inv.get('id') or inv.get('investigation_id') or '')
    if st == 201 and inv_id:
        verify_status, _ = api(base, '/investigations/' + quote(inv_id, safe=''))
        report.add('Create and read isolated investigation', 'sandbox-write', 'PASS' if verify_status == 200 else 'FAIL', f'create={st}; read={verify_status}; output in temporary graph')
    else:
        report.add('Create and read isolated investigation', 'sandbox-write', 'FAIL', f'create HTTP={st}; returned ID={bool(inv_id)}')
    st, plan = api(base, '/plans', method='POST', body={
        'situation_id': 'INC-AST-ROUTE-OUTAGE', 'goal': 'Safely investigate Asteria route outage with evidence and approvals'})
    plan_id = str(plan.get('id') or plan.get('plan_id') or (plan.get('plan') or {}).get('id') or '')
    if st == 201 and plan_id:
        st_tasks, tasks = api(base, '/plans/' + quote(plan_id, safe='') + '/tasks')
        st_top, topo = api(base, '/work/plans/' + quote(plan_id, safe='') + '/topology')
        detail = f'plan create={st}, tasks={st_tasks}, topology={st_top}; no external action executed'
        report.add('Create plan, inspect tasks and DAG in isolated graph', 'sandbox-write',
                   'PASS' if st_tasks == 200 and st_top == 200 else 'FAIL', detail,
                   evidence={'plan_id': plan_id, 'topology_available': st_top == 200})
    else:
        report.add('Create plan, inspect tasks and DAG in isolated graph', 'sandbox-write', 'FAIL', f'create HTTP={st}; returned ID={bool(plan_id)}')
    # Simulations are non-mutating, but tested on the same isolated backend.
    st, sim = api(base, '/simulations/counterfactual', method='POST', body={
        'situation_id': 'INC-AST-ROUTE-OUTAGE', 'interventions': [
            {'op': 'remove_dependency', 'source_id': 'SYS-AST-DISPATCH', 'target_id': 'SYS-AST-ROUTE-DB'}], 'max_depth': 4})
    report.add('Non-mutating counterfactual simulation', 'simulation',
               'PASS' if st == 200 and sim.get('persisted') is False else 'FAIL', f'http={st}; persisted={sim.get("persisted", "unknown")}')


def browser_spec() -> str:
    return r'''import {test, expect} from '@playwright/test';
test('Scenario explorer navigates without manual IDs', async ({page}) => {
 await page.goto('/demo');
 await expect(page.getByRole('heading',{name:'Demo & Scenario Explorer'})).toBeVisible();
 await expect(page.getByText('Company Brain',{exact:true}).first()).toBeVisible();
 await page.goto('/scenarios');
 await page.getByRole('link',{name:'Guided walkthrough and trace ↗'}).first().click();
 await expect(page).toHaveURL(/\/demo\?scenario=AST-/);
});
test('Situation search, status dropdown and true empty state', async ({page}) => {
 await page.goto('/situations');
 const search=page.getByRole('textbox',{name:'Search situations'});
 await expect(search).toBeVisible();
 await search.fill('INC-AST-ROUTE-OUTAGE');
 await expect(page.locator('a[href="/situations/INC-AST-ROUTE-OUTAGE"]')).toBeVisible({timeout:15000});
 await expect(page.getByRole('combobox',{name:'Status'})).toBeVisible();
 await search.fill('unlikely-no-match-893d55');
 await expect(page.getByText('No situations match your search')).toBeVisible({timeout:15000});
});
test('Entity graph tools and category filters interact', async ({page}) => {
 await page.goto('/entities/SYS-AST-ROUTE-DB?tab=blast-radius');
 await expect(page.getByRole('heading',{name:/Route State Database/i})).toBeVisible();
 await expect(page.getByText('What could be affected?')).toBeVisible({timeout:20000});
 await expect(page.getByRole('button',{name:'Fit all'})).toBeVisible();
 await expect(page.getByRole('button',{name:'Zoom in'})).toBeVisible();
 const btn=page.locator('.gh-legend-toggle').first();
 await expect(btn).toBeVisible();
 const state=await btn.getAttribute('aria-pressed');
 await btn.click();
 await expect(btn).toHaveAttribute('aria-pressed',state==='true'?'false':'true');
});
'''


def browser_checks(report: Reporter, env: dict, backend_port: int, temp_dir: Path, *, unit: bool, report_dir: Path):
    npm, npx = tool('npm'), tool('npx')
    if unit:
        if not npm or not (FRONTEND / 'node_modules').exists():
            report.add('Frontend Vitest and typecheck', 'frontend-unit', 'BLOCKED', 'Run npm ci inside frontend first')
        else:
            for name, cmd in [('Vitest', [npm, 'test']), ('Typecheck', [npm, 'run', 'typecheck']),
                              ('Production build', [npm, 'run', 'build'])]:
                result = run_command(cmd, FRONTEND, env, 210)
                report.add(name, 'frontend-unit', 'PASS' if result['code'] == 0 else 'FAIL', result['tail'])
    if not npm or not npx or not (FRONTEND / 'node_modules').exists():
        report.add('Playwright UI integration', 'browser', 'BLOCKED', 'npm and frontend/node_modules required; run npm ci')
        return
    front_port = free_port()
    env.update({'VITE_DEV_PORT': str(front_port), 'VITE_PROXY_TARGET': f'http://127.0.0.1:{backend_port}',
                'VITE_API_BASE_URL': '', 'VITE_TEST_TOKEN': TOKEN, 'VITE_TENANT_ID': TENANT,
                'PHASE13_BASE_URL': f'http://127.0.0.1:{front_port}'})
    suffix = uuid.uuid4().hex[:10]
    spec = FRONTEND / 'e2e' / f'__graphhacks_acceptance_{suffix}.spec.ts'
    spec.write_text(browser_spec(), encoding='utf-8')
    log = temp_dir / 'frontend.log'
    proc = None
    try:
        with log.open('w', encoding='utf-8') as out:
            proc = subprocess.Popen([npm, 'run', 'dev'], cwd=FRONTEND, env=env, stdout=out, stderr=subprocess.STDOUT)
            wait_url(f'http://127.0.0.1:{front_port}/', proc)
            result = run_command([npx, 'playwright', 'test', str(spec.relative_to(FRONTEND))], FRONTEND, env, 230)
            report_dir.mkdir(parents=True, exist_ok=True)
            # Store the full Playwright output outside the disposable test directory.
            (report_dir / 'playwright.log').write_text(result['output'], encoding='utf-8')
            msg = result['tail'] + f'\nFull output: {report_dir / "playwright.log"}'
            if result['code'] != 0 and ('Executable doesn\'t exist' in result['output'] or 'Please run the following command' in result['output']):
                report.add('Playwright browser tests', 'browser', 'BLOCKED', 'Install Chromium: cd frontend; npx playwright install chromium')
            else:
                report.add('Playwright scenario, search and graph interactions', 'browser', 'PASS' if result['code'] == 0 else 'FAIL', msg)
    except Exception as exc:
        report.add('Playwright browser tests', 'browser', 'BLOCKED', safe_message(exc))
    finally:
        spec.unlink(missing_ok=True)
        stop(proc)
        # Startup errors help diagnose browser failures; keep them outside temp.
        try:
            report_dir.mkdir(parents=True, exist_ok=True)
            if log.exists():
                shutil.copyfile(log, report_dir / 'vite.log')
        except OSError as exc:
            report.notes.append('Could not preserve Vite startup log: ' + safe_message(exc))


def stop(proc):
    if not proc or proc.poll() is not None:
        return
    if os.name == 'nt':
        # npm.cmd launches node.exe/Vite as descendants. Terminating only npm.cmd
        # leaves the Vite process holding frontend.log open on Windows.
        # The PID is only the child process created by THIS runner.
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                       capture_output=True, timeout=15, check=False)
        try:
            proc.wait(timeout=8)
            return
        except subprocess.TimeoutExpired:
            pass
    proc.terminate()
    try:
        proc.wait(timeout=7)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def cleanup_temporary_directory(temp, reporter: Reporter):
    # Report should always be exported even if a Windows process holds a log.
    if temp is None:
        return
    for attempt in range(6):
        try:
            temp.cleanup()
            return
        except (PermissionError, OSError) as exc:
            if attempt < 5:
                time.sleep(1)
            else:
                reporter.add('Temporary log directory cleanup', 'cleanup', 'BLOCKED', safe_message(exc))
                reporter.notes.append(f'Manually remove leftover temporary logs when processes stop: {temp.name}')


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=['offline', 'read-only', 'full'], default='full',
                   help='offline: fixtures; read-only: also inspect seeded Asteria; full: isolated API and browser tests')
    p.add_argument('--report-dir', type=Path, default=DEFAULT_REPORT)
    p.add_argument('--skip-browser', action='store_true')
    p.add_argument('--skip-unit', action='store_true', help='Skip pytest, Vitest, typecheck and build')
    p.add_argument('--keep-test-graph', action='store_true', help='Retain ONLY the unique graph created during this run for inspection')
    args = p.parse_args(argv)
    graph_name = PREFIX + uuid.uuid4().hex[:16] if args.mode == 'full' else '(no temporary graph)'
    recorder = Reporter(graph_name, args.mode)
    scenarios = []
    graph_client = None
    protected_before: dict[str, str] = {}
    backend = None
    temp = None
    try:
        from scripts.validate_asteria_pack import load_data
        _, _, scenarios, _ = load_data()
        if not offline_checks(recorder):
            recorder.notes.append('Offline contracts failed; skip live operations')
            return 1
        if args.mode in ('read-only', 'full'):
            try: live_graph_checks(recorder)
            except Exception as exc:
                recorder.add('Canonical Asteria read-only verification', 'live-graph', 'BLOCKED', safe_message(exc))
        if args.mode != 'full': return 0 if not any(c['status'] in ('FAIL', 'BLOCKED') for c in recorder.checks) else 1
        for target, tenant in [('company_brain', 'northstar'), ('asteria_company_brain_v1', 'asteria')]:
            try: protected_before[target] = graph_fingerprint(target, tenant)
            except Exception as exc:
                recorder.add(f'Protected graph baseline: {target}', 'isolation', 'NOT_TESTED',
                             'Could not read snapshot: ' + safe_message(exc))
        # Unit tests never modify the canonical graph, and are run before sandbox mutation.
        if not args.skip_unit:
            result = run_command([sys.executable, '-m', 'pytest', '-m', 'not integration', '-q'], ROOT, timeout=220)
            recorder.add('Backend non-integration regression suite', 'backend-unit',
                         'PASS' if result['code'] == 0 else 'FAIL', result['tail'])
        temp = tempfile.TemporaryDirectory(prefix='graphhacks-e2e-')
        scratch = Path(temp.name)
        graph_client = sandbox_seed(graph_name, recorder)
        from backend.app.services.phase4_graph import GraphSnapshot
        from scripts.validate_asteria_pack import load_data
        from scripts.verify_asteria_live import verify
        m, _, s, t = load_data()
        isolated = verify(GraphSnapshot.load(graph_client), m, s, t)
        recorder.add('Isolated graph matches all 24 scenario contracts', 'isolation', 'PASS' if isolated['ok'] else 'FAIL', f'nodes={isolated["nodes_read"]}; edges={isolated["edges_read"]}')
        if not isolated['ok']:
            return 1
        port = free_port()
        url = f'http://127.0.0.1:{port}'
        env = os.environ.copy()
        env.update({'FALKORDB_GRAPH': graph_name, 'GRAPH_TENANT_ID': TENANT,
                    'GRAPH_HACKS_ENV': 'development', 'GRAPH_HACKS_DISABLE_TEST_AUTH': '0',
                    'GRAPH_HACKS_API_PRINCIPALS_JSON': '', 'GRAPH_HACKS_ARTIFACT_ROOT': str(scratch / 'artifacts'),
                    'GRAPH_HACKS_RETRIEVAL_ROOT': str(scratch / 'retrieval'),
                    'GRAPH_HACKS_CREDENTIAL_ROOT': str(scratch / 'credentials')})
        with (scratch / 'backend.log').open('w', encoding='utf-8') as log:
            backend = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app',
                                        '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            wait_url(url + '/health', backend)
            status, ready = api(url, '/ready')
            recorder.add('Isolated backend readiness', 'api', 'PASS' if status == 200 and ready.get('ready') else 'FAIL', f'http={status}')
            isolated_api_checks(url, recorder, scenarios)
            if not args.skip_browser:
                browser_checks(recorder, env, port, scratch, unit=not args.skip_unit, report_dir=args.report_dir)
            else:
                recorder.add('Browser interaction tests', 'browser', 'NOT_TESTED', 'Explicit --skip-browser')
    except Exception as exc:
        recorder.add('Orchestrator setup or execution', 'runner', 'BLOCKED', safe_message(exc))
    finally:
        stop(backend)
        if temp is not None:
            try:
                backend_log = Path(temp.name) / 'backend.log'
                if backend_log.exists():
                    args.report_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(backend_log, args.report_dir / 'backend.log')
            except OSError as exc:
                recorder.notes.append('Could not preserve backend log: ' + safe_message(exc))
        if graph_client is not None:
            if args.keep_test_graph:
                recorder.notes.append(f'Temporary graph deliberately retained: {graph_name}')
            else:
                try:
                    if graph_client.settings.falkordb_graph != graph_name or graph_name in PROTECTED_GRAPHS:
                        raise RuntimeError('Deletion safety guard rejected graph')
                    graph_client.delete_graph()
                    recorder.add('Only owned temporary graph removed', 'cleanup', 'PASS', graph_name)
                except Exception as exc:
                    recorder.add('Temporary graph cleanup', 'cleanup', 'FAIL', safe_message(exc))
                    recorder.notes.append(f'Inspect leftover temporary graph: {graph_name}')
        for target, original in protected_before.items():
            try:
                current = graph_fingerprint(target, 'asteria' if target == 'asteria_company_brain_v1' else 'northstar')
                recorder.add(f'Protected graph unchanged: {target}', 'isolation',
                             'PASS' if current == original else 'FAIL',
                             'Read-only structural/content checksum comparison; no canonical writes sent')
            except Exception as exc:
                recorder.add(f'Protected graph unchanged: {target}', 'isolation', 'BLOCKED', safe_message(exc))
        cleanup_temporary_directory(temp, recorder)
        try: final = recorder.export(args.report_dir, scenarios)
        except Exception as exc:
            print('Could not save report:', safe_message(exc), file=sys.stderr)
            return 2
    bad = any(c['status'] in ('FAIL', 'BLOCKED') for c in recorder.checks)
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
