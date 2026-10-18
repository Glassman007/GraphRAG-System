from fastapi.testclient import TestClient

import backend.app.api_v1.router as router
from backend.app.main import app
from backend.app.services.phase4_graph import GraphSnapshot, GraphEdge

NODES = [
    {'id':'P1','_labels':['Entity','Plan']},
    {'id':'T1','_labels':['Entity','Task'],'status':'OPEN','task_type':'INVESTIGATE'},
    {'id':'T2','_labels':['Entity','Task'],'status':'COMPLETED','task_type':'INVESTIGATE'},
    {'id':'A1','_labels':['Entity','Agent'],'status':'ACTIVE','availability':'AVAILABLE','supported_task_types':'INVESTIGATE','permissions':'READ_GRAPH'},
    {'id':'A2','_labels':['Entity','Agent'],'status':'DISABLED','supported_task_types':'INVESTIGATE','permissions':'READ_GRAPH'},
]
EDGES = [GraphEdge('P1','PLAN_HAS_TASK','T1',{}),GraphEdge('P1','PLAN_HAS_TASK','T2',{}),GraphEdge('T1','REQUIRES','T2',{})]


def fake_client(monkeypatch):
    snapshot=GraphSnapshot({n['id']:n for n in NODES},EDGES)
    monkeypatch.setattr(router,'client_for',lambda principal:object())
    monkeypatch.setattr(GraphSnapshot,'load',classmethod(lambda cls,client:snapshot))
    return TestClient(app)


def test_work_read_endpoints_are_authenticated_and_tenant_scoped(monkeypatch):
    client=fake_client(monkeypatch)
    assert client.get('/api/v1/work/plans/P1/topology').status_code==401
    headers={'Authorization':'Bearer test-admin-token','X-Tenant-ID':'other-tenant'}
    assert client.get('/api/v1/work/plans/P1/topology',headers=headers).status_code==403
    admin={'Authorization':'Bearer test-admin-token','X-Tenant-ID':'northstar'}
    response=client.get('/api/v1/work/plans/P1/topology',headers=admin)
    assert response.status_code==200,response.text
    assert response.json()['parallel_waves']==[['T2'],['T1']]
    assert client.get('/api/v1/work/tasks/T1/insights',headers=admin).status_code==200
    matches=client.get('/api/v1/work/tasks/T1/agent-matches',headers=admin)
    assert matches.status_code==200 and matches.json()['items'][0]['agent']['id']=='A1'
    assert matches.json()['assignment_performed'] is False
    assert client.get('/api/v1/work/agents/A1/memory',headers=admin).status_code==200
    assert client.get('/api/v1/work/plans/BOGUS/topology',headers=admin).status_code==404


def test_reader_not_allowed_to_write_findings_or_pause(monkeypatch):
    client=fake_client(monkeypatch)
    reader={'Authorization':'Bearer test-reader-token','X-Tenant-ID':'northstar'}
    response=client.post('/api/v1/work/tasks/T1/findings',headers=reader,json={'agent_id':'A1','statement':'A finding','confidence':0.75})
    assert response.status_code==403
    response=client.post('/api/v1/tasks/T1/pause',headers=reader,json={'agent_id':'A1'})
    assert response.status_code==403


def test_retry_fails_closed_when_no_failed_execution(monkeypatch):
    client=fake_client(monkeypatch)
    admin={'Authorization':'Bearer test-admin-token','X-Tenant-ID':'northstar'}
    response=client.post('/api/v1/tasks/T1/retry',headers=admin,json={'agent_id':'A1'})
    assert response.status_code==409
