r"""Read-only A1 follow-up: diagnose Asteria Workspace run-list scope failure.

Run in main VERINEX checkout with activated environment:
    python .\VERINEX_A1_workspace_scope_diagnostic.py

Only sends HTTP GET requests under the Asteria principal. Does not inspect
other company brains, write to FalkorDB, create runs, or call any model.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GRAPH = 'asteria_company_brain_v1'
TENANT = 'asteria'
API = os.getenv('VERINEX_A1_API_BASE', 'http://127.0.0.1:8000').rstrip('/')
TOKEN = os.getenv('VERINEX_A1_API_TOKEN', 'test-asteria-admin-token')
PREFIX = '/api/v1/agent-runtime/workspace/runs'
OUTPUT = Path('VERINEX_A1_workspace_scope_diagnostic_result.json')


def get(path: str, *, graph: str = GRAPH) -> tuple[int | None, object | None, str | None]:
    req = Request(API + path, headers={
        'Authorization': f'Bearer {TOKEN}',
        'X-Tenant-ID': TENANT,
        'X-Company-Brain-ID': graph,
        'Accept': 'application/json',
    }, method='GET')
    try:
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read(2_000_000).decode('utf-8'))
            return response.status, data, None
    except HTTPError as exc:
        return exc.code, None, 'HTTP_REJECTED'
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return None, None, type(exc).__name__


def main() -> int:
    result: dict = {
        'package': 'A1', 'check': 'Asteria Workspace scope diagnostic',
        'graph': GRAPH, 'tenant': TENANT,
        'executed_at_utc': datetime.now(timezone.utc).isoformat(),
        'model_calls': 0, 'business_graph_writes': 0,
    }
    code, payload, error = get(PREFIX + '?limit=20')
    result['list_http_status'] = code
    if code != 200 or not isinstance(payload, dict) or not isinstance(payload.get('items'), list):
        result['outcome'] = 'API_UNAVAILABLE_OR_INVALID_LIST_RESPONSE'
        result['error_type'] = error
        return finish(result, 1)

    rows = payload['items']
    categories = Counter()
    scoped_ids: list[str] = []
    for item in rows:
        if not isinstance(item, dict):
            categories['invalid_item_type'] += 1
            continue
        tenant = item.get('tenant')
        graph = item.get('graph_id')
        # Validate both fields independently; deliberately do not print or follow
        # records whose scope differs from the requested Asteria graph/tenant.
        if not isinstance(tenant, str) or not tenant:
            categories['missing_tenant'] += 1
        elif tenant != TENANT:
            categories['different_tenant'] += 1
        if not isinstance(graph, str) or not graph:
            categories['missing_graph_id'] += 1
        elif graph != GRAPH:
            categories['different_graph_id'] += 1
        if tenant == TENANT and graph == GRAPH:
            categories['matching_asteria'] += 1
            run_id = item.get('id')
            if isinstance(run_id, str) and re.fullmatch(r'SRUN-[0-9A-F]{32}', run_id):
                scoped_ids.append(run_id)
            else:
                categories['invalid_matching_run_id'] += 1

    result['returned_count'] = len(rows)
    result['categories'] = dict(sorted(categories.items()))
    result['classification'] = ('SCOPE_MISMATCH_OR_LEGACY_RECORDS'
                                if any(categories[k] for k in (
                                    'invalid_item_type', 'missing_tenant', 'different_tenant',
                                    'missing_graph_id', 'different_graph_id', 'invalid_matching_run_id'))
                                else 'ALL_RETURNED_ROWS_ASTERIA_SCOPED')
    # Read only an explicitly Asteria-scoped ID, if any exists. Never probe a
    # suspect row or a run from a different graph, even for a read-only detail.
    if scoped_ids:
        rid = scoped_ids[0]
        reads = {}
        for name, path in (
            ('detail', f'{PREFIX}/{rid}'),
            ('events', f'{PREFIX}/{rid}/events'),
            ('replay', f'{PREFIX}/{rid}/replay'),
        ):
            status, response, fetch_error = get(path)
            ok = status == 200 and isinstance(response, dict)
            if name == 'detail' and ok:
                w = response.get('workspace')
                ok = isinstance(w, dict) and w.get('graph_id') == GRAPH and w.get('tenant') == TENANT
            reads[name] = {'http_status': status, 'pass': ok, 'error_type': fetch_error}
        result['matching_asteria_run_checks'] = {'run_id': rid, 'reads': reads}
    else:
        result['matching_asteria_run_checks'] = 'NO_MATCHING_OWNED_RUN_FOR_READBACK'

    # Existing A1 probe stopped on list failure before reaching this check.
    neg_code, _, neg_error = get('/api/v1/session', graph='__a1_unregistered_graph_probe__')
    result['unregistered_graph_authorization'] = {
        'http_status': neg_code, 'denied': neg_code in (403, 404), 'error_type': neg_error,
    }
    result['outcome'] = ('NEEDS_REVIEW' if result['classification'] != 'ALL_RETURNED_ROWS_ASTERIA_SCOPED'
                         else 'SCOPED_LIST_VERIFIED')
    exit_code = 2 if result['outcome'] == 'NEEDS_REVIEW' else 0
    if neg_code not in (403, 404):
        result['outcome'] = 'AUTHORIZATION_NEGATIVE_CHECK_FAILED_OR_UNAVAILABLE'
        exit_code = 2
    if isinstance(result['matching_asteria_run_checks'], dict):
        if not all(v['pass'] for v in result['matching_asteria_run_checks']['reads'].values()):
            result['outcome'] = 'ASTERIA_READBACK_FAILED'
            exit_code = 2
    return finish(result, exit_code)


def finish(result: dict, exit_code: int) -> int:
    OUTPUT.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('A1 Workspace scope diagnostic:', result['outcome'])
    print('Workspace list HTTP status:', result.get('list_http_status'))
    print('Returned row count:', result.get('returned_count', 'unknown'))
    print('Sanitized scope categories:', json.dumps(result.get('categories', {}), sort_keys=True))
    print('Asteria run readback:', json.dumps(result.get('matching_asteria_run_checks', 'NOT_RUN')))
    print('Unregistered graph authorization:', json.dumps(result.get('unregistered_graph_authorization', 'NOT_RUN')))
    print('Saved:', OUTPUT.resolve())
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
