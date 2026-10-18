"""Read-only seeded Asteria v1 graph contract verification; run after seeding.

Loads evaluator-only expectations locally. Does not expose them through GraphHacks API.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.temporal import to_epoch_us
from backend.app.services.phase4_graph import GraphSnapshot
from scripts.seed_asteria import target_settings
from scripts.validate_asteria_pack import load_data, validate_pack


def verify(snapshot,manifest,scenarios,truth):
    errors=[]
    graph_edges=defaultdict(list)
    for e in snapshot.edges:graph_edges[e.source,e.target].append(e)
    def has_path(path):
        return all(graph_edges.get((a,b)) for a,b in zip(path,path[1:]))
    def active(e,when):
        at=to_epoch_us(when)
        props=e.properties
        if to_epoch_us(props['valid_from'])>at:return False
        return not props.get('valid_until') or at<to_epoch_us(props['valid_until'])
    outcomes={}
    for entry in scenarios:
        sid=entry['scenario_id'];gold=truth[sid]
        failures=[]
        for path in gold['paths']:
            if not has_path(path):failures.append('path missing: '+' -> '.join(path))
        for item in gold.get('required_typed_edges',[]):
            if not any(e.type==item['type'] for e in graph_edges.get((item['source'],item['target']),[])):
                failures.append('required edge missing: '+f"{item['source']}-[{item['type']}]->{item['target']}")
        for item in gold['properties']:
            if (snapshot.nodes.get(item['id']) or {}).get(item['field'])!=item['equals']:
                failures.append('property differs: '+item['id']+'.'+item['field'])
        for src,rel,dst in gold['absent_relationships']:
            if any(e.type==rel for e in graph_edges.get((src,dst),[])):
                failures.append('unexpected relationship: '+f'{src}-[{rel}]->{dst}')
        for item in gold['temporal']:
            matches=[e for e in graph_edges.get((item['source'],item['target']),[]) if e.type==item['type']]
            if not any(active(e,item['active_at']) for e in matches):failures.append('historic edge not active')
            if any(active(e,item['inactive_at']) for e in matches):failures.append('expired edge still active')
        outcomes[sid]={'pass':not failures,'errors':failures}
        errors.extend(f'{sid}: {failure}' for failure in failures)
    # Node count is lower-bounded, since users may legitimately add runtime records.
    seeded_ids=[n['id'] for batch in load_data()[1] for n in batch['nodes']]
    for ident in seeded_ids:
        if ident not in snapshot.nodes:errors.append(f'missing node {ident}')
    return {'ok':not errors, 'nodes_read':len(snapshot.nodes),'edges_read':len(snapshot.edges),
            'minimum_seed_nodes':manifest['node_count'], 'minimum_seed_edges':manifest['relationship_count'],
            'scenarios':outcomes,'errors':errors}


def main():
    offline=validate_pack()
    if not offline['ok']:
        print('Offline pack invalid; stop before connecting to database.',file=sys.stderr)
        return 1
    manifest,_,scenarios,truth=load_data()
    client=FalkorGraphClient(target_settings())
    snapshot=GraphSnapshot.load(client)
    result=verify(snapshot,manifest,scenarios,truth)
    print(json.dumps(result,indent=2))
    return 0 if result['ok'] else 1

if __name__=='__main__':sys.exit(main())
