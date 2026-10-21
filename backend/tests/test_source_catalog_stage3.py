"""Non-network contract checks for registered Company Brain source discovery."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app.ingestion.source_catalog import list_source_catalog
from backend.app.services.phase4_graph import GraphSnapshot


def _n(source_id, name, tenant='asteria', **kwargs):
    return {'id': source_id, 'name': name, 'tenant_id': tenant, '_labels': ['Entity','DataSource'], **kwargs}


class FakeRegistry:
    def __init__(self):
        self.graphs = {
            'asteria_company_brain_v1': [
                _n('DS-AST-GITHUB','GitHub Mirror',fixture_pack='asteria-v1'),
                _n('DS-AST-JIRA','Jira Project Export',fixture_pack='asteria-v1'),
            ],
            'company_brain': [
                _n('SRC-A','Sample-db', managed_by='phase13-source-control',connector_type='github',last_ingestion_status='SUCCEEDED'),
                _n('SRC-B','Chinook', managed_by='phase13-source-control',connector_type='github'),
                _n('SRC-C','SampleA', managed_by='phase13-source-control',connector_type='github'),
                _n('DS-OTHER','Other Tenant',tenant='other',managed_by='phase13-source-control'),
            ],
        }

    def list_for_tenant(self, *, tenant_id):
        assert tenant_id=='asteria'
        return {'items':[{'graph_id':graph_id,'display_name':graph_id,'available':True} for graph_id in self.graphs]}

    def client_for_graph(self, *, tenant_id, graph_id):
        assert tenant_id=='asteria'
        assert graph_id in self.graphs
        return SimpleNamespace(graph_id=graph_id, settings=SimpleNamespace(tenant_id=tenant_id))


def test_fixture_and_three_managed_sources_share_two_brains(monkeypatch):
    from backend.app.ingestion import source_catalog
    fake=FakeRegistry()
    monkeypatch.setattr(source_catalog.GraphSnapshot,'load',lambda client: GraphSnapshot({n['id']:n for n in fake.graphs[client.graph_id] if n['tenant_id']==client.settings.tenant_id},[]))
    result=list_source_catalog(tenant_id='asteria', registry=fake)
    assert len(result['items'])==5
    assert sum(bool(s['managed']) for s in result['items'])==3
    assert sum(not s['managed'] for s in result['items'])==2
    assert not any(s['source_id']=='DS-OTHER' for s in result['items'])
    assert all(s['graph_id']=='company_brain' for s in result['items'] if s['managed'])
    assert all(not s['can_sync'] for s in result['items'] if not s['managed'])


def test_unknown_or_unavailable_graph_never_enumerated(monkeypatch):
    from backend.app.ingestion import source_catalog
    fake=FakeRegistry()
    fake.list_for_tenant=lambda *,tenant_id: {'items':[{'graph_id':'asteria_company_brain_v1','display_name':'Asteria','available':False}]}
    monkeypatch.setattr(source_catalog.GraphSnapshot,'load',lambda client: (_ for _ in ()).throw(AssertionError('must not be called')))
    assert list_source_catalog(tenant_id='asteria',registry=fake)['items']==[]


def test_seeded_data_is_not_a_live_source(monkeypatch):
    from backend.app.ingestion import source_catalog
    fake=FakeRegistry()
    monkeypatch.setattr(source_catalog.GraphSnapshot,'load',lambda client: GraphSnapshot({n['id']:n for n in fake.graphs[client.graph_id] if n['tenant_id']==client.settings.tenant_id},[]))
    github=next(x for x in list_source_catalog(tenant_id='asteria',registry=fake)['items'] if x['source_id']=='DS-AST-GITHUB')
    assert github['fixture_pack']=='asteria-v1'
    assert github['status']=='IMPORTED'
    assert github['can_sync'] is False


def test_catalog_endpoint_registered():
    from backend.app.main import app
    matches=[r for r in app.routes if getattr(r,'path',None)=='/api/v1/sources/catalog']
    assert len(matches)==1
    assert 'GET' in matches[0].methods


def test_retrieval_index_namespaced_by_graph(tmp_path, monkeypatch):
    from backend.app.retrieval.paths import scoped_index_root
    monkeypatch.delenv('GRAPH_HACKS_RETRIEVAL_ROOT', raising=False)
    default_path=scoped_index_root(tenant_id='asteria',graph_id='company_brain',root=tmp_path)
    asteria_path=scoped_index_root(tenant_id='asteria',graph_id='asteria_company_brain_v1',root=tmp_path)
    assert asteria_path!=default_path
    assert str(asteria_path).startswith(str(tmp_path))
