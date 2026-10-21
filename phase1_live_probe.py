"""VERINEX Phase 1: read-only FalkorDB source/graph inventory.

Run from VERINEX repository root, e.g.:
 python phase1_live_probe.py --dataset chinook --source-id CHINOOK-GITHUB-TEST --graph company_brain --tenant northstar
 python phase1_live_probe.py --dataset asteria --graph asteria_company_brain_v1 --tenant asteria

Reads existing graphs only; NO schema setup, graph deletes, seeding, ingestion,
updates, model calls, or external source syncs.
"""
from __future__ import annotations
import argparse
import json
from collections import Counter

from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot

EXPECTED_FK = {
    ('album', ('artist_id',), 'artist', ('artist_id',)),
    ('customer', ('support_rep_id',), 'employee', ('employee_id',)),
    ('employee', ('reports_to',), 'employee', ('employee_id',)),
    ('invoice', ('customer_id',), 'customer', ('customer_id',)),
    ('invoice_line', ('invoice_id',), 'invoice', ('invoice_id',)),
    ('invoice_line', ('track_id',), 'track', ('track_id',)),
    ('playlist_track', ('playlist_id',), 'playlist', ('playlist_id',)),
    ('playlist_track', ('track_id',), 'track', ('track_id',)),
    ('track', ('album_id',), 'album', ('album_id',)),
    ('track', ('genre_id',), 'genre', ('genre_id',)),
    ('track', ('media_type_id',), 'media_type', ('media_type_id',)),
}
EXPECTED_TABLES = {'album','artist','customer','employee','genre','invoice','invoice_line','media_type','playlist','playlist_track','track'}

def labels(node):
    return set(node.get('_labels') or [])

def short_table(node):
    return str(node.get('table_name') or node.get('name') or '').split('.')[-1].lower()

def column_tuple(raw):
    if raw is None:
        return tuple()
    if isinstance(raw, (list, tuple)):
        return tuple(str(x).strip().lower() for x in raw)
    value = str(raw).strip().strip('[]')
    return tuple(x.strip().strip("\"'").lower() for x in value.split(',') if x.strip())

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset', choices=['chinook', 'asteria'], required=True)
    p.add_argument('--source-id', default='CHINOOK-GITHUB-TEST')
    p.add_argument('--graph', required=True)
    p.add_argument('--tenant', required=True)
    args=p.parse_args()
    cfg=Settings.from_env().model_copy(update={'tenant_id':args.tenant,'falkordb_graph':args.graph})
    client=FalkorGraphClient(cfg)
    health=client.health_check()
    snap=GraphSnapshot.load(client)
    result={'dataset':args.dataset, 'graph':args.graph,'tenant':args.tenant,
            'connected':bool(health.get('ok')),'node_count':len(snap.nodes),'relationship_count':len(snap.edges),
            'node_types':dict(sorted(Counter(l for node in snap.nodes.values() for l in labels(node) if l!='Entity').items())),
            'relationship_types':dict(sorted(Counter(e.type for e in snap.edges).items()))}
    if args.dataset == 'chinook':
        sid=args.source_id
        owned={nid:n for nid,n in snap.nodes.items() if str(n.get('source_ref_id') or '')==sid}
        tabs={nid:n for nid,n in owned.items() if 'SqlTable' in labels(n)}
        table_names={short_table(n) for n in tabs.values()}
        constraints=[n for n in owned.values() if 'SqlConstraint' in labels(n) and str(n.get('constraint_type')).upper()=='FOREIGN_KEY']
        fks=[]; mappings=set()
        for e in snap.edges:
            if e.type!='FOREIGN_KEY_TO' or e.source not in tabs or e.target not in tabs:
                continue
            if e.properties.get('source_ref_id') not in (None,sid):
                continue
            record={'from_table':short_table(tabs[e.source]),'from_columns':list(column_tuple(e.properties.get('source_columns') or e.properties.get('columns'))),
                    'to_table':short_table(tabs[e.target]),'to_columns':list(column_tuple(e.properties.get('target_columns') or e.properties.get('referenced_columns'))),
                    'constraint_name':e.properties.get('constraint_name'),'edge_id':e.properties.get('edge_id')}
            fks.append(record)
            mappings.add((record['from_table'],tuple(record['from_columns']),record['to_table'],tuple(record['to_columns'])))
        result.update({'source_id':sid,'source_node_exists':sid in snap.nodes,
                       'source_scoped_entity_count':len(owned),'sql_table_count':len(tabs),
                       'sql_constraint_fk_count':len(constraints),'fk_relationship_count':len(fks),
                       'tables':sorted(table_names),'fk_mappings':fks,
                       'matches_pinned_chinook_11_tables':table_names==EXPECTED_TABLES and len(tabs)==11,
                       'matches_pinned_chinook_11_fks':mappings==EXPECTED_FK and len(fks)==11,
                       'missing_fk_mappings':[list(x) for x in sorted(EXPECTED_FK-mappings)],
                       'extra_fk_mappings':[list(x) for x in sorted(mappings-EXPECTED_FK)]})
    else:
        decisions=[{'id':n['id'],'name':n.get('name')} for n in snap.nodes.values() if 'Decision' in labels(n)]
        owning=[{'from':e.source,'to':e.target} for e in snap.edges if e.type=='OWNS']
        sources={nid for nid,n in snap.nodes.items() if 'SourceRecord' in labels(n)}
        evidence=[n for n in snap.nodes.values() if 'Evidence' in labels(n)]
        refs=[{'evidence':n['id'],'ref':n['source_ref_id'],'resolved':n['source_ref_id'] in sources}
              for n in evidence if n.get('source_ref_id')]
        result.update({'decisions':decisions,'owns_edges':owning,'source_record_count':len(sources),
                       'evidence_count':len(evidence),'evidence_source_refs':refs,
                       'unresolved_evidence_source_refs':[r for r in refs if not r['resolved']]})
    print(json.dumps(result,indent=2,default=str))

if __name__=='__main__': main()
