"""Offline, dependency-light Asteria v1 contract verifier.

Never reads/writes FalkorDB. Golden answers are used only here, not by the seeder.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.graph.schema import NODE_LABELS, RELATIONSHIP_TYPES
from backend.app.graph.temporal import to_epoch_us

PACK = ROOT / 'fixtures' / 'asteria' / 'v1'


def load_data():
    manifest = json.loads((PACK / 'manifest.json').read_text(encoding='utf-8'))
    batches = [json.loads((PACK / f).read_text(encoding='utf-8')) for f in manifest['seed_files']]
    scenarios = [json.loads(x.read_text(encoding='utf-8')) for x in sorted((PACK / 'scenarios').glob('*.json'))]
    truth = json.loads((PACK / 'ground_truth' / 'evaluation_only.json').read_text(encoding='utf-8'))
    return manifest, batches, scenarios, truth


def validate_pack(*, node_min=300, edge_min=550):
    manifest, batches, scenarios, truth = load_data()
    errors=[]
    def check(ok,why):
        if not ok:errors.append(why)
    check(manifest['graph']=='asteria_company_brain_v1','unexpected graph name')
    check(manifest['graph']!='company_brain','would overwrite legacy Northstar graph')
    check(manifest['tenant_id']=='asteria','tenant mismatch')
    check(manifest['simulated_only'] is True,'synthetic data must be declared')
    check(all('ground_truth' not in b for b in batches),'gold answers included in seed payload')
    check(all(b['tenant_id']=='asteria' for b in batches),'batch tenant mismatch')
    nodes=[n for b in batches for n in b.get('nodes',[])]
    edges=[e for b in batches for e in b.get('edges',[])]
    ids=[n['id'] for n in nodes]
    by_id={n['id']:n for n in nodes}
    check(len(nodes)==len(by_id),'duplicate seeded node id')
    check(len(edges)==len(set((e['source'],e['type'],e['target'],e['properties'].get('edge_id')) for e in edges)),'duplicate edge id/tuple')
    check(len(nodes)==manifest['node_count'],'manifest node count differs')
    check(len(edges)==manifest['relationship_count'],'manifest edge count differs')
    check(len(nodes)>=node_min and len(edges)>=edge_min,'dataset not meaningfully larger than Northstar')
    check(len(scenarios)>=20,'not enough independent scenarios')
    check(set(x['scenario_id'] for x in scenarios)==set(truth)==set(manifest['scenario_ids']),'scenario / evaluator manifest mismatch')
    counts=Counter(n['label'] for n in nodes)
    check(dict(sorted(counts.items()))==manifest['node_types'],'manifest label counts differ')
    for n in nodes:
        p=n.get('properties',{})
        check(n['label'] in NODE_LABELS,f'unsupported node label {n["label"]}')
        check(n['id']==p.get('id'),f'id property mismatch: {n["id"]}')
        check(p.get('tenant_id')=='asteria',f'cross tenant node: {n["id"]}')
        check(p.get('synthetic') is True and p.get('fixture_pack')=='asteria-v1',f'unmarked synthetic node: {n["id"]}')
        for f in ('created_at','observed_at','occurred_at','valid_from','valid_until'):
            if p.get(f):
                try:to_epoch_us(p[f])
                except Exception:check(False,f'invalid {f} for {n["id"]}')
        check(not ('ROOT_CAUSE' in p or 'final_answer' in p),'seed node contains golden answer')
    by_pair=defaultdict(list)
    for e in edges:
        src,rel,dst=e['source'],e['type'],e['target']
        check(src in by_id and dst in by_id,f'dangling relationship {src}-[{rel}]->{dst}')
        check(rel in RELATIONSHIP_TYPES,f'unsupported relationship type {rel}')
        check(e['properties'].get('edge_id'),f'no id for relationship {src}->{dst}')
        try:
            begin=to_epoch_us(e['properties']['valid_from'])
            if e['properties'].get('valid_until'):
                check(begin<to_epoch_us(e['properties']['valid_until']),f'reversed interval {src}-{rel}->{dst}')
        except Exception:check(False,f'invalid temporal edge {src}-{rel}->{dst}')
        check(rel!='ROOT_CAUSE',f'ground-truth leakage on relationship {src}->{dst}')
        by_pair[(src,dst)].append(e)
    evidence=[n for n in nodes if n['label']=='Evidence']
    for n in evidence:
        ident=n['id']
        source_links=[e for e in edges if e['source']==ident and e['type']=='DERIVED_FROM']
        check(any(by_id[e['target']]['label']=='SourceRecord' for e in source_links),f'evidence {ident} has no source record')
        check(n['properties'].get('provenance_status')=='SIMULATED',f'evidence {ident} lacks synthetic provenance')
    sr=[n for n in nodes if n['label']=='SourceRecord']
    for n in sr:
        check(any(e['source']==n['id'] and e['type']=='DERIVED_FROM' and by_id[e['target']]['label']=='DataSource' for e in edges),f'source record {n["id"]} has no origin')
    check(all(n['properties']['connection_status']=='SYNTHETIC_FIXTURE' for n in nodes if n['label']=='DataSource'),'misleading real connector label')
    check(all(n['properties'].get('status')!='EXECUTED' for n in nodes if n['label']=='Action'),'fixture action already executed')
    check(all(n['properties'].get('fixture_only') for n in nodes if n['label'] in {'Agent','Action','ActionAttempt','Execution'}),'runtime record lacks synthetic flag')
    check(all(s['track'] in {'COMPANY_BRAIN','CONNECTED_AGENTS','AGENT_MEMORY_COORDINATION'} for s in scenarios),'unknown scenario track')
    def has_edge(src,dst):return (src,dst) in by_pair
    for scenario in scenarios:
        sid=scenario['scenario_id']
        for ident in scenario['entry_ids']+scenario['focus_ids']:
            check(ident in by_id,f'{sid}: unknown entry or focus {ident}')
        check(bool(scenario['test_prompts']),f'{sid}: has no demo prompts')
        gold=truth[sid]
        for path in gold['paths']:
            check(len(path)>=2,f'{sid}: too-short path')
            for src,dst in zip(path,path[1:]):
                check(has_edge(src,dst),f'{sid}: missing directed path edge {src} -> {dst}')
        for item in gold.get('required_typed_edges',[]):
            check(any(e['type']==item['type'] for e in by_pair[(item['source'],item['target'])]),
                  f'{sid}: wrong or missing typed edge {item}')
        for item in gold['properties']:
            ident=item['id']
            check(ident in by_id and by_id[ident]['properties'].get(item['field'])==item['equals'],f'{sid}: invalid golden property {item}')
        for src,rel,dst in gold['absent_relationships']:
            check(not any(e['type']==rel for e in by_pair[(src,dst)]),f'{sid}: expected missing relationship {src}->{dst} exists')
        for item in gold['temporal']:
            matches=[e for e in by_pair[item['source'],item['target']] if e['type']==item['type']]
            def active(edge,t):
                at=to_epoch_us(t)
                return to_epoch_us(edge['properties']['valid_from'])<=at and (not edge['properties'].get('valid_until') or at<to_epoch_us(edge['properties']['valid_until']))
            check(any(active(e,item['active_at']) for e in matches),f'{sid}: temporal previous state wrong')
            check(not any(active(e,item['inactive_at']) for e in matches),f'{sid}: temporal future state wrong')
    # High-level scenario coverage requirements, not just raw counts.
    tracks=Counter(s['track'] for s in scenarios)
    check(all(n>=5 for n in tracks.values()) and len(tracks)==3,'incomplete three-track coverage')
    check(any(e['type']=='BLOCKED_BY' and any(x['type']=='BLOCKED_BY' and x['source']==e['target'] and x['target']==e['source'] for x in edges) for e in edges), 'no coordination deadlock')
    check(any(n['label']=='Handoff' and n['properties'].get('status')=='INVALID' for n in nodes),'no negative handoff')
    check(any(n['label']=='Finding' and n['properties'].get('memory_state')=='STALE' for n in nodes),'no stale memory example')
    check(any(e['type']=='OWNS' and e['properties'].get('valid_until') for e in edges),'no historical ownership transfer')
    return {'ok':not errors,'errors':errors,'nodes':len(nodes),'edges':len(edges), 'scenarios':len(scenarios),'tracks':dict(tracks),'labels':dict(sorted(counts.items()))}


def main():
    result=validate_pack()
    print(json.dumps(result,indent=2))
    return 0 if result['ok'] else 1

if __name__=='__main__':
    sys.exit(main())
