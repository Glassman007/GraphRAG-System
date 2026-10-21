#!/usr/bin/env python3
"""VERINEX investigation acceptance runner (bounded, auditable, standard library).

Read-only preflight by default. Model and graph-writing planner tests are separate
opt-ins. This script never performs database migrations or task execution.

Use --dry-run for an offline payload check and --audit-json for an offline review.
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
EXPECTED_FK_CONSTRAINTS = (
    "film_actor_film_id_fkey", "film_category_film_id_fkey", "inventory_film_id_fkey"
)


def api(base, api_key, method, path, body=None, timeout_seconds=25):
    url = base.rstrip('/') + path
    data = None if body is None else json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Accept', 'application/json')
    req.add_header('X-API-Key', api_key)
    if body is not None:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read(3_000_000)
            return {'http': response.status, 'data': json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as exc:
        raw = exc.read(16_000)
        try:
            detail = json.loads(raw)
        except (ValueError, UnicodeError):
            detail = raw.decode('utf-8', 'replace')[:500]
        return {'http': exc.code, 'error': detail}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {'http': None, 'error': f'{type(exc).__name__}: {exc}'[:300]}


def as_items(obj, name):
    if not isinstance(obj, dict):
        return []
    value = obj.get(name)
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get('items'), list):
        return value['items']
    return []


def ident(obj):
    if not isinstance(obj, dict):
        return None
    return obj.get('id') or obj.get('table_id') or obj.get('entity_id')


def build_run_payload(film_id=None, *, max_steps=6, max_tokens=14000, max_seconds=180):
    """Unambiguous request construction; does not invoke the backend/model."""
    payload = {
        'goal': SCENARIO,
        'max_steps': max_steps,
        'max_tokens': max_tokens,
        'max_seconds': max_seconds,
        'allow_external_model': True,
    }
    if film_id:
        payload['source_entity_id'] = film_id
    return payload


def audit_investigation(results):
    """Conservative audit: never calls an incomplete or uncited answer PASS."""
    run = (results.get('agent_run') or {}).get('data') or {}
    if not isinstance(run, dict):
        run = {}
    persisted = (results.get('agent_persisted_trace') or {}).get('data') or {}
    trace = run.get('trace') or persisted.get('trace') or []
    if not isinstance(trace, list):
        trace = []
    tool_steps = [s for s in trace if s.get('kind') == 'TOOL' and s.get('status') == 'RECORDED']
    duplicated = [s for s in trace if s.get('kind') == 'DUPLICATE_TOOL']
    failed_step_types = [s.get('kind') for s in trace if s.get('status') == 'FAILED']
    answer = run.get('answer') or persisted.get('answer') or ''
    citations = run.get('citations') or persisted.get('citations') or []
    gaps = run.get('knowledge_gaps') or persisted.get('knowledge_gaps') or []
    status = str(run.get('status') or persisted.get('status') or 'UNKNOWN').upper()
    # Some storage schemas keep only abridged tool summaries; no citation validation
    # should be attempted based solely on that summary.
    missing_constraints = [name for name in EXPECTED_FK_CONSTRAINTS if name.lower() not in answer.lower()]
    incomplete = status in {'INCOMPLETE', 'FAILED', 'ERROR', 'BLOCKED', 'UNKNOWN'}
    insufficient = incomplete or not tool_steps or not str(answer).strip() or not citations
    return {
        'evaluation': 'NOT_ACCEPTED' if insufficient else 'MANUAL_EVIDENCE_REVIEW_REQUIRED',
        'run_status': status,
        'recorded_graph_tool_calls': len([s for s in tool_steps if str(s.get('tool') or s.get('tool_name') or '').startswith('graph_')]),
        'recorded_tool_calls': len(tool_steps),
        'duplicate_tool_attempts': len(duplicated),
        'failed_step_types': failed_step_types,
        'answer_present': bool(str(answer).strip()),
        'citation_count': len(citations) if isinstance(citations, list) else 0,
        'knowledge_gap_count': len(gaps) if isinstance(gaps, list) else 0,
        'expected_constraint_names_missing_from_answer': missing_constraints,
        'note': 'Tool invocation is not evidence coverage. Validate FK direction, actual constraints, indirect paths and provenance against complete tool observations. No automatic PASS is assigned.',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--source-id', help='Existing SQL graph source ID (required for live requests)')
    parser.add_argument('--film-id', help='Optional public.film canonical ID')
    parser.add_argument('--run-model', action='store_true', help='Explicitly authorize one model-backed investigation')
    parser.add_argument('--create-test-plan', action='store_true', help='Unsupported in this investigation-only version; prevents accidental graph writes')
    parser.add_argument('--max-steps', type=int, default=6)
    parser.add_argument('--max-tokens', type=int, default=14000)
    parser.add_argument('--max-seconds', type=int, default=180)
    parser.add_argument('--dry-run', action='store_true', help='Print the exact model request without network access or API key')
    parser.add_argument('--audit-json', type=Path, help='Audit an existing result JSON offline; no API calls')
    parser.add_argument('--output', default='reports/verinex_agent_evaluation/LOCAL_TEST_RESULTS.json')
    args = parser.parse_args(argv)

    if args.audit_json:
        results = json.loads(args.audit_json.read_text(encoding='utf-8-sig'))
        print(json.dumps(audit_investigation(results), ensure_ascii=False, indent=2))
        return 0

    if not 1 <= args.max_steps <= 12:
        parser.error('--max-steps must be between 1 and 12')
    if not 1000 <= args.max_tokens <= 30000:
        parser.error('--max-tokens must be between 1000 and 30000')
    if not 30 <= args.max_seconds <= 600:
        parser.error('--max-seconds must be between 30 and 600')
    payload = build_run_payload(args.film_id, max_steps=args.max_steps,
                                max_tokens=args.max_tokens, max_seconds=args.max_seconds)
    if args.dry_run:
        print(json.dumps({
            'request_path': '/api/v1/agent-runtime/runs',
            'request_body': payload,
            'http_request_timeout_seconds': args.max_seconds + 40,
            'note': 'These are CLIENT-REQUESTED limits; the effective backend limits must be verified separately.',
        }, indent=2))
        return 0

    if not args.source_id:
        parser.error('--source-id is required for a live run')
    if not args.base_url.startswith(('http://127.0.0.1:', 'http://localhost:')):
        parser.error('For safety, only local API targets are allowed')
    if args.create_test_plan:
        parser.error('Structured planning is intentionally not implemented in this investigation-only runner; no planner records will be written')

    key = os.environ.get('VERINEX_API_KEY') or getpass('VERINEX API key (hidden): ')
    if not key:
        parser.error('An API key is required')
    results = {
        'scenario': SCENARIO,
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'scope': {'source_id': args.source_id, 'api_base': args.base_url,
                  'run_model': args.run_model, 'create_test_plan': args.create_test_plan},
        'note': 'HTTP success, tool call, or generated prose alone does not establish evidence-grounded investigation PASS.',
    }
    try:
        status = api(args.base_url, key, 'GET', '/api/v1/agent-runtime/status')
        results['runtime_status'] = status
        query = urllib.parse.urlencode({'source_id': args.source_id})
        schema = api(args.base_url, key, 'GET', '/api/v1/company-brain/sql-schema?' + query)
        if schema.get('http') == 200:
            body = schema.get('data') or {}
            tables = as_items(body, 'tables')
            edges = as_items(body, 'foreign_keys') or as_items(body, 'relationships') or as_items(body, 'edges')
            film = next((t for t in tables if str(t.get('name') or '').lower() in {'film', 'public.film'}), None)
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
                results['agent_run'] = {'status': 'BLOCKED', 'reason': 'Model provider not configured or status failed'}
            elif not film_id:
                results['agent_run'] = {'status': 'BLOCKED', 'reason': 'public.film entity ID not identified; no model tokens spent'}
            else:
                payload = build_run_payload(film_id, max_steps=args.max_steps,
                                            max_tokens=args.max_tokens, max_seconds=args.max_seconds)
                results['requested_model_run'] = {
                    'endpoint': '/api/v1/agent-runtime/runs', 'body': payload,
                    'http_timeout_seconds': args.max_seconds + 40,
                    'warning': 'Request values, NOT proof of effective server-enforced limits.',
                }
                run = api(args.base_url, key, 'POST', '/api/v1/agent-runtime/runs',
                          payload, timeout_seconds=args.max_seconds + 40)
                results['agent_run'] = run
                body = run.get('data') if isinstance(run.get('data'), dict) else {}
                run_id = body.get('run_id') or body.get('id')
                if run.get('http') in (200, 201) and run_id:
                    results['agent_persisted_trace'] = api(
                        args.base_url, key, 'GET',
                        '/api/v1/agent-runtime/runs/' + urllib.parse.quote(str(run_id), safe=''),
                    )
        else:
            results['agent_run'] = {'status': 'NOT_RUN', 'reason': 'Requires --run-model'}

        results['investigation_audit'] = audit_investigation(results)
        results['test_plan'] = {'status': 'NOT_RUN', 'reason': 'Planner testing is intentionally separate; no records written'}
    finally:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
        print(f'Wrote result evidence to: {out.resolve()}')
        print('Review and redact tool/graph content before sharing. No credentials were written.')
    print('Investigation audit:', results.get('investigation_audit', {}).get('evaluation', 'N/A'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
