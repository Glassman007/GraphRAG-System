"""Non-destructive Asteria v1 seeder, isolated from the legacy Northstar graph.

Run from repository root: python scripts/seed_asteria.py --check
                         python scripts/seed_asteria.py --seed
No implicit graph reset; a preexisting target graph requires --resume.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.graph.schema import apply_schema
from scripts.validate_asteria_pack import load_data, validate_pack

GRAPH='asteria_company_brain_v1'
TENANT='asteria'


def target_settings():
    # Never trust ambient FALKORDB_GRAPH/GRAPH_TENANT_ID for a demo seed.
    result=Settings.from_env().model_copy(update={'falkordb_graph': GRAPH, 'tenant_id':TENANT})
    if result.falkordb_graph=='company_brain' or result.tenant_id=='northstar':
        raise RuntimeError('Refusing to seed the Northstar/legacy graph')
    return result


def seed(client, batches, *, resume=False):
    if client.settings.falkordb_graph != GRAPH or client.settings.tenant_id != TENANT:
        raise ValueError('Safety gate: refusing seed outside Asteria graph and tenant')
    count=int(client.query('MATCH (n:Entity) RETURN count(n)').result_set[0][0])
    if count and not resume:
        raise RuntimeError(f'Target graph already has {count} nodes; aborting without changes. For a partial pack seed use --resume (existing nodes are not overwritten).')
    # Resume must never adopt, silently overwrite or cross-link unknown tenant data.
    existing={}
    if count:
        for row in client.read('MATCH (n:Entity) RETURN n.id, n.tenant_id, n.fixture_pack').result_set:
            node_id, tenant_id, marker=map(lambda x: '' if x is None else str(x),row)
            if tenant_id != TENANT or marker != 'asteria-v1':
                raise RuntimeError(f'Unsafe existing graph content ({node_id or "unknown"}). Refusing resume.')
            existing[node_id]=True
    apply_schema(client)
    created=0; untouched=0; written_edges=0
    # Two-pass load is important because edge fixtures cross sections.
    for batch in batches:
        for node in batch['nodes']:
            if node['id'] in existing:
                untouched+=1
                continue
            upsert_node(client,node['label'],node['id'],node['properties'])
            created+=1
    for batch in batches:
        for edge in batch['edges']:
            upsert_relationship(client,edge['source'],edge['type'],edge['target'],edge['properties'])
            written_edges+=1
    return {'created_nodes':created,'preserved_existing_nodes':untouched,'edge_upserts':written_edges,'graph':GRAPH,'tenant':TENANT}


def main(argv=None):
    parser=argparse.ArgumentParser(description='Validate or safely seed the isolated Asteria demo graph.')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true',help='Offline validation; no database connection')
    mode.add_argument('--seed',action='store_true',help='Seed only if target graph is empty')
    mode.add_argument('--resume',action='store_true',help='Fill partial Asteria seed without replacing any existing nodes')
    args=parser.parse_args(argv)
    report=validate_pack()
    if not report['ok']:
        print('Fixture validation failed:\n'+'\n'.join(report['errors']),file=sys.stderr)
        return 1
    if args.check:
        print(json.dumps({k:v for k,v in report.items() if k!='labels'},indent=2))
        return 0
    _,batches,_,_=load_data()
    client=FalkorGraphClient(target_settings())
    result=seed(client,batches,resume=args.resume)
    print(json.dumps(result,indent=2))
    return 0

if __name__=='__main__':
    sys.exit(main())
