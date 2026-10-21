"""Source-management safety regression tests (no live graph, no Groq calls)."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.ingestion import source_catalog as catalog
from backend.app.services.phase4_graph import GraphSnapshot


def node(sid, tenant='asteria', managed=False):
    return {'id':sid,'tenant_id':tenant,'name':sid,'_labels':['Entity','DataSource'],
            **({'managed_by':'phase13-source-control'} if managed else {'fixture_pack':'asteria-v1'})}


class StubRegistry:
    def __init__(self, data):
        self.data=data

    def client_for_graph(self, *,tenant_id,graph_id):
        if tenant_id!='asteria' or graph_id!='allowed':
            raise RuntimeError('Unauthorized graph')
        return SimpleNamespace(settings=SimpleNamespace(tenant_id=tenant_id,falkordb_graph=graph_id))


def test_imported_source_hidden_preserves_graph_history(monkeypatch):
    state={'source':node('DS-FOO')}
    monkeypatch.setattr(catalog.GraphSnapshot,'load',lambda c: GraphSnapshot({'DS-FOO':state['source']},[]))
    def fake_upsert(client,label,sid,props):
        assert label=='DataSource' and sid=='DS-FOO'
        assert 'configuration_removed' not in props
        state['source'].update(props)
    events=[]
    monkeypatch.setattr(catalog,'upsert_node',fake_upsert)
    monkeypatch.setattr(catalog,'EventLedgerService',lambda client:SimpleNamespace(record=lambda event,**kwargs:events.append(event)))
    result=catalog.remove_source_from_catalog(tenant_id='asteria',graph_id='allowed',source_id='DS-FOO',actor_id='admin',registry=StubRegistry(state))
    assert result['catalog_hidden'] and result['historical_provenance_retained']
    assert state['source']['catalog_hidden'] is True
    assert events==['SOURCE_CATALOG_HIDDEN']
    with pytest.raises(KeyError):
        catalog.remove_source_from_catalog(tenant_id='asteria',graph_id='allowed',source_id='DS-FOO',actor_id='admin',registry=StubRegistry(state))


def test_managed_source_reuses_existing_credential_cleanup(monkeypatch):
    monkeypatch.setattr(catalog.GraphSnapshot,'load',lambda c:GraphSnapshot({'SRC-X':node('SRC-X',managed=True)},[]))
    calls=[]
    class StubService:
        def __init__(self,client): pass
        def delete_configuration(self,source_id,*,actor_id):
            calls.append((source_id,actor_id))
            return {'source_id':source_id,'configuration_removed':True,'historical_provenance_retained':True}
    monkeypatch.setattr(catalog,'SourceControlService',StubService)
    monkeypatch.setattr(catalog,'upsert_node',lambda *a,**k: (_ for _ in ()).throw(AssertionError('managed path must not use fixture mutation')))
    result=catalog.remove_source_from_catalog(tenant_id='asteria',graph_id='allowed',source_id='SRC-X',actor_id='admin',registry=StubRegistry({}))
    assert result['action']=='CONFIGURATION_REMOVED'
    assert calls==[('SRC-X','admin')]


def test_reject_missing_source_and_wrong_tenant(monkeypatch):
    monkeypatch.setattr(catalog.GraphSnapshot,'load',lambda c:GraphSnapshot({'DS-OTHER':node('DS-OTHER',tenant='northstar')},[]))
    monkeypatch.setattr(catalog,'upsert_node',lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError('unauthorized write')))
    for sid in ('DS-OTHER','NOT-FOUND'):
        with pytest.raises(KeyError):
            catalog.remove_source_from_catalog(tenant_id='asteria',graph_id='allowed',source_id=sid,actor_id='admin',registry=StubRegistry({}))


def test_removal_endpoint_requires_explicit_graph_and_permission():
    from backend.app.main import app
    c=TestClient(app)
    endpoint='/api/v1/sources/catalog/DS-FOO'
    no_graph=c.delete(endpoint,headers={'Authorization':'Bearer test-asteria-admin-token'})
    assert no_graph.status_code==422
    non_admin=c.delete(endpoint,headers={'Authorization':'Bearer test-reader-token'})
    assert non_admin.status_code==403
    assert any(r.path==endpoint.replace('DS-FOO','{source_id}') and 'DELETE' in r.methods for r in app.routes)


def test_removal_impact_conservatively_identifies_shared_canonical_nodes(monkeypatch):
    from backend.app.services.phase4_graph import GraphEdge
    nodes = {
        'SRC-X': node('SRC-X', managed=True),
        'SRC-Y': node('SRC-Y', managed=True),
        'R-X': {'id':'R-X','_labels':['Entity','SourceRecord'],'source_id':'SRC-X','tenant_id':'asteria'},
        'R-Y': {'id':'R-Y','_labels':['Entity','SourceRecord'],'source_id':'SRC-Y','tenant_id':'asteria'},
        'ENTITY-1': {'id':'ENTITY-1','_labels':['Entity','System'],'tenant_id':'asteria'},
    }
    edges=[GraphEdge('R-X','NORMALIZED_TO','ENTITY-1',{'source_ref_id':'SRC-X'}),
           GraphEdge('R-Y','NORMALIZED_TO','ENTITY-1',{'source_ref_id':'SRC-Y'})]
    monkeypatch.setattr(catalog.GraphSnapshot,'load',lambda c:GraphSnapshot(nodes,edges))
    result=catalog.inspect_source_removal(tenant_id='asteria',graph_id='allowed',
                                         source_id='SRC-X',registry=StubRegistry({}))
    assert result['source_records']==1
    assert result['canonical_entities_reached']==1
    assert result['canonical_entities_also_referenced_by_other_source_records']==1
    assert result['graph_shared_by_multiple_sources']
    assert not result['hard_purge_safe']


def test_removal_impact_no_writes_and_never_claims_hard_purge_safe(monkeypatch):
    monkeypatch.setattr(catalog.GraphSnapshot,'load',lambda c: GraphSnapshot({'DS-FOO':node('DS-FOO')}, []))
    monkeypatch.setattr(catalog,'upsert_node',lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError('no writes')))
    result=catalog.inspect_source_removal(tenant_id='asteria',graph_id='allowed',
                                         source_id='DS-FOO',registry=StubRegistry({}))
    assert result['source_records']==0
    assert not result['hard_purge_safe']


def test_removal_impact_requires_graph_header():
    from backend.app.main import app
    c=TestClient(app)
    resp=c.get('/api/v1/sources/catalog/SRC-X/removal-impact',headers={'Authorization':'Bearer test-asteria-admin-token'})
    assert resp.status_code==422


def test_new_dedicated_company_brain_uses_fresh_graph_and_existing_registration(tmp_path,monkeypatch):
    from backend.app.graph.registry import GraphRegistry
    from types import SimpleNamespace
    names=[]
    writes=[]
    class Graph:
        def query(self,cypher,params):
            assert cypher.startswith('CREATE (:VERINEXGraphAnchor')
            writes.append(params)
            return SimpleNamespace(result_set=[])
        def ro_query(self,cypher,params):
            return SimpleNamespace(result_set=[['ok']] if writes and params['tenant']==writes[0]['tenant_id'] else [])
        def delete(self): raise AssertionError('Must not delete successful graph')
    class DB:
        def list_graphs(self):return names
        def select_graph(self,graph_id):
            if graph_id not in names:names.append(graph_id)
            return Graph()
    registry=GraphRegistry(tmp_path/'catalog.sqlite3')
    result=registry.create_dedicated(tenant_id='asteria',display_name='Independent repository',
                                     client=SimpleNamespace(db=DB()))
    assert result['graph_id'].startswith('source_')
    assert result['dedicated'] is True
    assert writes[0]['graph_id']==result['graph_id']
    assert registry.resolve(tenant_id='asteria',graph_id=result['graph_id'])['display_name']=='Independent repository'


def test_new_graph_api_requires_management_permission():
    from backend.app.main import app
    c=TestClient(app)
    assert c.post('/api/v1/graphs',json={'display_name':'New repo'},
                  headers={'Authorization':'Bearer test-reader-token'}).status_code==403
