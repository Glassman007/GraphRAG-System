"""Offline tests for selected-graph authorization and Workspace binding."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.api_v1 import router as workspace_api
from backend.app.api_v1.security import Principal, client_for
from backend.app.agent_runtime.workspace import WorkspaceStart
from backend.app.graph.registry import GraphNotRegistered


def _principal(graph: str | None = None) -> Principal:
    return Principal('alice','asteria',('ADMIN',),frozenset({'ADMIN'}),graph)


def test_header_can_only_select_tenant_registered_graph(monkeypatch):
    from backend.app.graph import registry
    def registered(self, *, tenant_id, graph_id):
        if (tenant_id,graph_id) != ('asteria','asteria_company_brain_v1'):
            raise GraphNotRegistered('Not authorized')
        return {'tenant_id': tenant_id, 'graph_id':graph_id}
    monkeypatch.setattr(registry.GraphRegistry, 'resolve', registered)
    http=TestClient(app)
    base={'Authorization':'Bearer test-asteria-admin-token'}
    ok=http.get('/api/v1/session',headers={**base,'X-Company-Brain-ID':'asteria_company_brain_v1'})
    assert ok.status_code==200
    missing=http.get('/api/v1/session',headers={**base,'X-Company-Brain-ID':'verinex_neon_stage5_xyz'})
    assert missing.status_code==404
    cross=http.get('/api/v1/session',headers={'Authorization':'Bearer test-reader-token','X-Company-Brain-ID':'asteria_company_brain_v1'})
    assert cross.status_code==404
    wrong_tenant=http.get('/api/v1/session',headers={**base,'X-Tenant-ID':'northstar','X-Company-Brain-ID':'asteria_company_brain_v1'})
    assert wrong_tenant.status_code==403


def test_client_for_scopes_without_global_settings_mutation(monkeypatch):
    from backend.app.graph import registry
    received=[]
    def select(self, *, tenant_id, graph_id, settings=None):
        received.append((tenant_id,graph_id,settings.tenant_id,settings.falkordb_graph))
        return SimpleNamespace(settings=settings.model_copy(update={'falkordb_graph':graph_id}))
    monkeypatch.setattr(registry.GraphRegistry,'client_for_graph',select)
    from backend.app.config import Settings
    original=Settings.from_env().falkordb_graph
    client=client_for(_principal('asteria_company_brain_v1'))
    assert client.settings.falkordb_graph=='asteria_company_brain_v1'
    assert received[0][:3]==('asteria','asteria_company_brain_v1','asteria')
    assert Settings.from_env().falkordb_graph==original


def test_workspace_refuses_body_header_graph_mismatch(monkeypatch):
    monkeypatch.setattr(workspace_api, '_guard_rate',lambda *args,**kwargs:None)
    with pytest.raises(Exception) as e:
        workspace_api.workspace_start(
            WorkspaceStart(goal='Investigate route outage and report facts',graph_id='company_brain',allow_external_model=True),
            SimpleNamespace(),_principal('asteria_company_brain_v1'))
    assert getattr(e.value,'code',None)=='GRAPH_SCOPE_MISMATCH'


def test_workspace_run_stores_exact_selected_graph(monkeypatch):
    monkeypatch.setattr(workspace_api, '_guard_rate',lambda *args,**kwargs:None)
    monkeypatch.setattr(workspace_api,'OpenAICompatibleProvider',lambda:object())
    fake_client=SimpleNamespace(settings=SimpleNamespace(falkordb_graph='asteria_company_brain_v1'))
    monkeypatch.setattr(workspace_api,'client_for',lambda p:fake_client)
    records=[]
    class Store:
        def create(self,item):records.append(item)
        def update(self,*args,**kwargs):return {}
    monkeypatch.setattr(workspace_api,'_workspace_store',lambda p:Store())
    monkeypatch.setattr(workspace_api.workspace_runner,'submit',lambda **kwargs:None)
    result=workspace_api.workspace_start(
        WorkspaceStart(goal='Investigate route outage and report facts',graph_id='asteria_company_brain_v1',allow_external_model=True),
        SimpleNamespace(),_principal('asteria_company_brain_v1'))
    assert records[0]['graph_id']=='asteria_company_brain_v1'
    assert result['graph_id']=='asteria_company_brain_v1'
    assert records[0]['settings']['source_entity_id'] is None


def test_workspace_run_cannot_cross_selected_graph(monkeypatch):
    class Store:
        def get(self,*args):return {'id':args[0], 'graph_id':'company_brain','owner':'alice'}
    monkeypatch.setattr(workspace_api,'_workspace_store',lambda p:Store())
    monkeypatch.setattr(workspace_api,'client_for',lambda p:SimpleNamespace(settings=SimpleNamespace(falkordb_graph=p.graph_id)))
    with pytest.raises(Exception) as e:
        workspace_api._workspace_owned(_principal('asteria_company_brain_v1'),'SRUN-'+'A'*32)
    assert getattr(e.value,'status_code',None)==404
