#!/usr/bin/env python3
"""Bounded live VERINEX agent/planner acceptance runner.

Read-only preflight by default. Agent and plan tests are separately opt-in.
No SQL execution, task execution, GitHub access or graph deletion.
Designed against the available VERINEX API snapshot; later APIs may differ.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from getpass import getpass
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

SCENARIO = (
    "Investigate the potential impact of changing public.film.film_id from integer "
    "to UUID. Use the persisted SQL schema graph to identify incoming foreign keys, "
    "indirect dependency paths and their actual constraint evidence. Separate verified "
    "schema facts from unknown application dependencies. Propose read-only investigation "
    "and migration-preparation steps; do not execute any schema or application changes."
)


def api(base, api_key, method, path, body=None):
    url = base.rstrip('/') + path
    data = None if body is None else json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Accept', 'application/json')
    req.add_header('X-API-Key', api_key)
    if body is not None:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=95 if path.endswith('/runs') and method=='POST' else 25) as r:
            raw = r.read(3_000_000)
            return {'http': r.status, 'data': json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as e:
        # Server may return detailed errors, but we do not save authorization headers.
        raw = e.read(16000)
        try: detail = json.loads(raw)
        except (ValueError, UnicodeError): detail = raw.decode('utf-8', 'replace')[:500]
        return {'http': e.code, 'error': detail}
    except (urllib.error.URLError, TimeoutError) as e:
        return {'http': None, 'error': f'{type(e).__name__}: {str(e.reason) if hasattr(e,"reason") else str(e)}'[:300]}


def as_items(obj, name):
    if not isinstance(obj, dict): return []
    value = obj.get(name)
    if isinstance(value, list): return value
    if isinstance(value, dict): return value.get('items', []) if isinstance(value.get('items'), list) else []
    return []


def ident(obj):
    if not isinstance(obj, dict): return None
    return obj.get('id') or obj.get('table_id') or obj.get('entity_id')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', default='http://127.0.0.1:8000', help='Running FastAPI base URL')
    p.add_argument('--source-id', required=True, help='Existing ingested GitHub source ID')
    p.add_argument('--film-id', help='Optional public.film canonical ID, copied from Company Brain')
    p.add_argument('--run-model', action='store_true', help='Explicitly authorize one model-backed investigation that transmits scoped graph context to the provider')
    p.add_argument('--create-test-plan', action='store_true', help='Explicitly authorize writing labeled test Situation, Investigation, Plan and Tasks to the current tenant graph')
    p.add_argument('--output', default='reports/verinex_agent_evaluation/LOCAL_TEST_RESULTS.json')
    args = p.parse_args()
    if not args.base_url.startswith(('http://127.0.0.1:', 'http://localhost:')):
        p.error('For safety, only local API targets are allowed')
    key = os.environ.get('VERINEX_API_KEY') or getpass('VERINEX API key (input hidden; not saved): ')
    if not key: p.error('An API key is required')
    results = {
        'scenario': SCENARIO,
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'scope': {'source_id': args.source_id, 'api_base': args.base_url, 'run_model': args.run_model,
                  'create_test_plan': args.create_test_plan},
        'note': 'Do not interpret API success or generated prose as evidence-grounded investigation or structured planning PASS.'
    }
    try:
        status = api(args.base_url, key, 'GET', '/api/v1/agent-runtime/status')
        results['runtime_status'] = status
        q = urllib.parse.urlencode({'source_id': args.source_id})
        schema = api(args.base_url, key, 'GET', '/api/v1/company-brain/sql-schema?' + q)
        if schema.get('http') == 200:
            body = schema.get('data') or {}
            tables = as_items(body, 'tables')
            edges = as_items(body, 'foreign_keys') or as_items(body, 'relationships') or as_items(body, 'edges')
            film = next((t for t in tables if str(t.get('name') or '').lower() in {'film','public.film'}), None)
            results['schema_preflight'] = {
                'http': 200, 'table_count': len(tables), 'reported_fk_count': len(edges),
                'film_id_from_api': ident(film), 'available_top_level_fields': list(body)[:20],
                'expected_tables': 15, 'expected_direct_foreign_keys': 18,
                'counts_inconclusive_if_response_is_paginated': True,
            }
            film_id = args.film_id or ident(film)
        else:
            results['schema_preflight'] = schema
            film_id = args.film_id
        results['film_id_used'] = film_id
        if args.run_model:
            if status.get('http') != 200 or not (status.get('data') or {}).get('configured'):
                results['agent_run'] = {'status': 'BLOCKED', 'reason': 'Runtime provider not configured or status request failed'}
            else:
                payload = {'goal': SCENARIO, 'max_steps': 4, 'max_tokens': 14000,
                           'max_seconds': 65, 'allow_external_model': True}
                if film_id: payload['source_entity_id'] = film_id
                run = api(args.base_url, key, 'POST', '/api/v1/agent-runtime/runs', payload)
                results['agent_run'] = run
                body = run.get('data') if isinstance(run.get('data'),dict) else {}
                run_id = body.get('run_id') or body.get('id')
                if run.get('http') in (200, 201) and run_id:
                    results['agent_persisted_trace'] = api(args.base_url, key, 'GET', '/api/v1/agent-runtime/runs/' + urllib.parse.quote(str(run_id), safe=''))
        else:
            results['agent_run'] = {'status': 'NOT_RUN', 'reason': 'Requires --run-model and explicit external-model consent'}
        if args.create_test_plan:
            create = api(args.base_url, key, 'POST', '/api/v1/situations', {
                'name': '[EVAL ONLY] film_id UUID migration investigation',
                'description': 'Hypothetical read-only evaluation request. Not a real incident or authorized migration. ' + SCENARIO,
                'severity': 'LOW'
            })
            results['test_situation'] = create
            obj = create.get('data') if isinstance(create.get('data'),dict) else {}
            situation_id = obj.get('situation_id') or obj.get('id')
            if create.get('http') in (200, 201) and situation_id:
                inv_payload = {'situation_id': situation_id, 'question': SCENARIO}
                if film_id: inv_payload['seed_entity_ids'] = [film_id]
                results['test_investigation_record'] = api(args.base_url, key, 'POST', '/api/v1/investigations', inv_payload)
                plan = api(args.base_url, key, 'POST', '/api/v1/plans', {
                    'situation_id': situation_id,
                    'goal': 'Prepare a read-only, evidence-grounded migration investigation plan for public.film.film_id from integer to UUID. Do not execute changes.'
                })
                results['test_plan'] = plan
                obj = plan.get('data') if isinstance(plan.get('data'),dict) else {}
                plan_id = obj.get('plan_id') or obj.get('id')
                if plan.get('http') in (200, 201) and plan_id:
                    pid = urllib.parse.quote(str(plan_id), safe='')
                    results['plan_tasks'] = api(args.base_url, key, 'GET', '/api/v1/plans/' + pid + '/tasks')
                    results['plan_topology'] = api(args.base_url, key, 'GET', '/api/v1/work/plans/' + pid + '/topology')
            else:
                results['test_plan'] = {'status': 'NOT_RUN', 'reason': 'Situation creation failed'}
        else:
            results['test_plan'] = {'status': 'NOT_RUN', 'reason': 'Requires --create-test-plan; test records persist in current graph'}
    finally:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
        print(f'Wrote result evidence to: {out.resolve()}')
        print('Review and redact graph/tool output before sharing. API credentials were not written.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
