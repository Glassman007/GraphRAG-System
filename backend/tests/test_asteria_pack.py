"""Offline acceptance checks for the optional Asteria v1 graph fixture pack."""
from __future__ import annotations

import json
from collections import Counter
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.app.api_v1.security import _configured_principals
from scripts.seed_asteria import GRAPH, TENANT, seed, target_settings
from scripts.validate_asteria_pack import load_data, validate_pack


def test_asteria_pack_contracts_all_pass():
    report=validate_pack()
    assert report['ok'], report['errors']
    assert report['nodes']>=350
    assert report['edges']>=700
    assert report['scenarios']>=21
    assert all(n>=6 for n in report['tracks'].values())


def test_legacy_fixture_scripts_do_not_discover_asteria():
    from scripts.seed_lib import scenario_paths
    assert all('asteria' not in str(p).lower() for p in scenario_paths())


def test_default_legacy_target_is_not_changed(monkeypatch):
    monkeypatch.delenv('FALKORDB_GRAPH',raising=False)
    monkeypatch.delenv('GRAPH_TENANT_ID',raising=False)
    from backend.app.config import Settings
    default=Settings.from_env()
    assert default.falkordb_graph=='company_brain'
    assert default.tenant_id=='northstar'
    isolated=target_settings()
    assert isolated.falkordb_graph==GRAPH
    assert isolated.tenant_id==TENANT


def test_seed_refuses_any_non_isolated_target():
    _,batches,_,_=load_data()
    client=MagicMock()
    client.settings=SimpleNamespace(falkordb_graph='company_brain',tenant_id='northstar')
    with pytest.raises(ValueError, match='Safety gate'):
        seed(client,batches)
    client.query.assert_not_called()


def test_seed_refuses_nonempty_graph_before_writing():
    _,batches,_,_=load_data()
    client=MagicMock()
    client.settings=SimpleNamespace(falkordb_graph=GRAPH,tenant_id=TENANT)
    client.query.return_value.result_set=[[3]]
    with pytest.raises(RuntimeError,match='without changes'):
        seed(client,batches)
    client.query.assert_called_once_with('MATCH (n:Entity) RETURN count(n)')
    client.delete_graph.assert_not_called()


def test_seed_is_two_pass_and_never_deletes(monkeypatch):
    _,batches,_,_=load_data()
    client=MagicMock()
    client.settings=SimpleNamespace(falkordb_graph=GRAPH,tenant_id=TENANT)
    client.query.return_value.result_set=[[0]]
    calls=[]
    monkeypatch.setattr('scripts.seed_asteria.apply_schema', lambda _c: calls.append('schema'))
    monkeypatch.setattr('scripts.seed_asteria.upsert_node',lambda *_: calls.append('node'))
    monkeypatch.setattr('scripts.seed_asteria.upsert_relationship',lambda *_: calls.append('edge'))
    result=seed(client,batches)
    assert calls[0]=='schema'
    assert all(c=='node' for c in calls[1:result['created_nodes']+1])
    assert all(c=='edge' for c in calls[result['created_nodes']+1:])
    assert result['created_nodes']==388
    assert result['edge_upserts']==797
    client.delete_graph.assert_not_called()


def test_asteria_token_is_dev_only(monkeypatch):
    monkeypatch.delenv('GRAPH_HACKS_API_PRINCIPALS_JSON',raising=False)
    monkeypatch.setenv('GRAPH_HACKS_ENV','development')
    monkeypatch.delenv('GRAPH_HACKS_DISABLE_TEST_AUTH',raising=False)
    auth=_configured_principals()
    assert auth['test-admin-token'].tenant_id=='northstar'
    assert auth['test-asteria-admin-token'].tenant_id=='asteria'
    monkeypatch.setenv('GRAPH_HACKS_ENV','production')
    assert 'test-asteria-admin-token' not in _configured_principals()


def test_synthetic_sources_are_all_explicit():
    manifest,batches,scenarios,truth=load_data()
    nodes=[node for batch in batches for node in batch['nodes']]
    assert all(n['properties'].get('synthetic') is True for n in nodes)
    assert not any('ground_truth' in json.dumps(b) for b in batches)
    sources=[n for n in nodes if n['label']=='SourceRecord']
    assert len(sources)>20
    assert len(set(n['properties']['source_type'] for n in sources))>=8
    assert len(scenarios)==len(truth)


def test_negative_control_traversal_break_is_caught(monkeypatch):
    import scripts.validate_asteria_pack as verifier
    manifest,batches,scenarios,truth=load_data()
    # Corrupt only the test's in-memory fixture; do not touch repository source.
    mutated=json.loads(json.dumps(batches))
    mutated[-1]['edges']=[e for e in mutated[-1]['edges'] if not (e['source']=='EVD-AST-0001' and e['target']=='SRCREC-AST-0001')]
    # Other files may contain same-section relation; strip from every batch.
    for b in mutated:
        b['edges']=[e for e in b['edges'] if not (e['source']=='EVD-AST-0001' and e['target']=='SRCREC-AST-0001')]
    monkeypatch.setattr(verifier,'load_data',lambda: (manifest,mutated,scenarios,truth))
    report=verifier.validate_pack()
    assert not report['ok']
    assert any('AST-AA-01' in x for x in report['errors'])


def test_live_contract_verifier_against_reference_snapshot():
    from backend.app.services.phase4_graph import GraphSnapshot, GraphEdge
    from scripts.verify_asteria_live import verify
    manifest,batches,scenarios,truth=load_data()
    nodes={n['id']:n['properties'] for batch in batches for n in batch['nodes']}
    edges=[GraphEdge(e['source'],e['type'],e['target'],e['properties']) for batch in batches for e in batch['edges']]
    result=verify(GraphSnapshot(nodes,edges),manifest,scenarios,truth)
    assert result['ok'], result['errors']
    assert all(s['pass'] for s in result['scenarios'].values())


def test_wrong_relationship_semantics_are_not_accepted(monkeypatch):
    import scripts.validate_asteria_pack as verifier
    manifest,batches,scenarios,truth=load_data()
    modified=json.loads(json.dumps(batches))
    edits=0
    for batch in modified:
        for edge in batch['edges']:
            if edge['source']=='EVD-AST-0005' and edge['target']=='CLM-AST-ROUTE-CPU' and edge['type']=='REFUTES':
                edge['type']='SUPPORTS'
                edits+=1
    assert edits==1
    monkeypatch.setattr(verifier,'load_data',lambda:(manifest,modified,scenarios,truth))
    result=verifier.validate_pack()
    assert not result['ok']
    assert any('AST-CB-02' in err and 'typed edge' in err for err in result['errors'])
