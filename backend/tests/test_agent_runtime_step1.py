"""Component 1: actual model/tool loop with stubbed model but real tool registry.

The tests verify runtime mechanics, not the quality of any remote model's inferences.
"""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.app.agent_runtime.harness import AgentHarness, AgentSettings
from backend.app.agent_runtime.provider import Completion, OpenAICompatibleProvider, ProviderError
from backend.app.agent_runtime.tools import ToolRegistry, declarations
from backend.app.services.phase4_graph import GraphSnapshot, GraphEdge


class Store:
    def __init__(self):
        self.run = None
        self.steps = []
        self.result = None
    def start(self, run):self.run = run
    def trace(self, run_id, step):self.steps.append(step)
    def finish(self, run_id, result):self.result = result


class Provider:
    name = 'test-scripted-provider'
    model = 'test-scripted-model'
    def __init__(self, outputs):self.outputs=list(outputs);self.calls=[]
    def complete(self, messages, tools, **kwargs):
        self.calls.append((messages, tools, kwargs))
        if not self.outputs:raise AssertionError('Model called more than expected')
        return self.outputs.pop(0)


def plan():return Completion('{"steps":["Inspect incident and provenance","Examine affected dependencies","Report evidence"]}',[],80)
def tool(name, arguments, idx=1):return Completion('',[{'id':f'call-{idx}','name':name,'arguments':json.dumps(arguments)}],90)
def final(citations=None, *, confidence='supported'):
    return Completion(json.dumps({'answer':'Route database dependency is recorded in the graph; further verification may be needed.',
                                  'citations':citations or ['INC-AST-ROUTE-OUTAGE'],
                                  'knowledge_gaps':['Independent root cause not yet verified'], 'confidence':confidence}),[],100)


def fixture_graph():
    nodes={
        'INC-AST-ROUTE-OUTAGE':{'id':'INC-AST-ROUTE-OUTAGE','name':'Route dispatch outage','status':'OPEN','_labels':['Entity','Incident']},
        'SYS-AST-ROUTE-DB':{'id':'SYS-AST-ROUTE-DB','name':'Route State Database','_labels':['Entity','System']},
        'SYS-AST-DISPATCH':{'id':'SYS-AST-DISPATCH','name':'Dispatch','_labels':['Entity','System']},
        'EVD-AST-0001':{'id':'EVD-AST-0001','name':'Trace','source_ref_id':'SIMULATED-TRACE', '_labels':['Entity','Evidence']},
    }
    edges=[GraphEdge('EVD-AST-0001','ABOUT','INC-AST-ROUTE-OUTAGE',{}),
           GraphEdge('SYS-AST-DISPATCH','DEPENDS_ON','SYS-AST-ROUTE-DB',{}),
           GraphEdge('SYS-AST-ROUTE-DB','AFFECTS','INC-AST-ROUTE-OUTAGE',{})]
    return GraphSnapshot(nodes,edges)


def runtime(prov, store=None):
    record=store or Store()
    return AgentHarness(provider=prov,tools=ToolRegistry(fixture_graph),store=record,tenant='asteria'), record


def settings(**changes):
    return AgentSettings(goal='Investigate route outage and affected systems',source_entity_id='INC-AST-ROUTE-OUTAGE',
                         allow_external_model=True,**changes)


def test_real_dynamic_tool_loop_and_persistent_trace_contract():
    p=Provider([plan(),tool('incident_context',{'entity_id':'INC-AST-ROUTE-OUTAGE'}),final(['EVD-AST-0001'])])
    h,st=runtime(p)
    result=h.run(settings(),subject='test-admin')
    assert result.status=='COMPLETED'
    assert result.citations==['EVD-AST-0001']
    assert [x['kind'] for x in st.steps]==['PLAN','TOOL','FINAL']
    assert st.result['tokens_used']==270
    assert st.run['provider']==p.name and st.run['source_entity_id']=='INC-AST-ROUTE-OUTAGE'
    assert len(p.calls)==3 and len(p.calls[0][1])==0 and len(p.calls[1][1])>=7
    assert 'EVD-AST-0001' in p.calls[2][0][-1]['content']


def test_disallowed_tool_is_rejected_and_cannot_execute_mutating_ops():
    p=Provider([plan(),tool('execute_action',{'action_id':'ACT-ROLLBACK'}),final()])
    h,st=runtime(p)
    result=h.run(settings(),subject='tester')
    assert result.status=='COMPLETED'  # allowed final cites starting entity only
    assert any(x['kind']=='TOOL_ERROR' for x in st.steps)
    assert 'execute_action' not in [x['function']['name'] for x in declarations()]


def test_fabricated_citations_are_not_accepted():
    p=Provider([plan(),final(['EVD-UNSEEN-999'])])
    h,st=runtime(p)
    result=h.run(settings(max_steps=1),subject='tester')
    assert result.status=='INCOMPLETE'
    assert result.citations==[]
    assert any(x['kind']=='INVALID_CITATIONS' for x in st.steps)


def test_agent_can_replan_after_observation():
    p=Provider([plan(),tool('graph_neighbors',{'entity_id':'SYS-AST-ROUTE-DB'}),
                Completion('{"steps":["Inspect new link", "Report bounded findings"]}',[],35),final()])
    h,st=runtime(p)
    result=h.run(settings(max_steps=4),subject='tester')
    assert result.status=='COMPLETED'
    assert any(x['kind']=='REPLAN' for x in st.steps)
    assert result.plan[0]=='Inspect new link'


def test_provider_failure_is_traced_without_fabricating_success():
    class FailingProvider(Provider):
        def complete(self,messages,tools,**kwargs):raise ProviderError('provider temporarily unavailable')
    h,st=runtime(FailingProvider([]))
    result=h.run(settings(),subject='tester')
    assert result.status=='FAILED'
    assert st.result['status']=='FAILED' and st.steps[-1]['kind']=='ERROR'


def test_no_consent_blocks_model_and_graph_mutation():
    p=Provider([plan()])
    h,st=runtime(p)
    with pytest.raises(ValueError,match='consent'):
        h.run(AgentSettings(goal='Investigate route outage and affected systems',source_entity_id='INC-AST-ROUTE-OUTAGE'),subject='tester')
    assert not p.calls and st.run is None


def test_invalid_starting_entity_fails_before_run_written():
    p=Provider([plan()]);h,st=runtime(p)
    with pytest.raises(ValueError, match='not found'):
        h.run(AgentSettings(goal='Investigate the lost source entity',source_entity_id='INC-UNKNOWN',allow_external_model=True),subject='tester')
    assert st.run is None


def test_tool_input_validation_and_tenant_snapshot():
    toolset=ToolRegistry(fixture_graph)
    assert toolset.execute('dependency_impact',{'entity_id':'SYS-AST-ROUTE-DB'})['impacted'][0]['path']['entity_id']=='SYS-AST-DISPATCH'
    assert toolset.execute('historical_record',{'entity_id':'SYS-AST-ROUTE-DB'})['entity']['id']=='SYS-AST-ROUTE-DB'
    with pytest.raises(ValueError,match='not allowlisted'):toolset.execute('cypher_query',{'query':'DELETE ALL'})
    with pytest.raises(Exception):toolset.execute('graph_paths',{'entity_id':'SYS-AST-ROUTE-DB','max_depth':100})


def test_provider_configuration_fails_closed_without_keys(monkeypatch):
    monkeypatch.setenv('GRAPH_HACKS_AGENT_PROVIDER','groq')
    monkeypatch.delenv('GROQ_API_KEY',raising=False)
    with pytest.raises(ProviderError,match='GROQ_API_KEY'):
        OpenAICompatibleProvider()
    monkeypatch.setenv('GRAPH_HACKS_AGENT_PROVIDER','compatible')
    monkeypatch.setenv('GRAPH_HACKS_AGENT_BASE_URL','http://169.254.169.254/v1')
    with pytest.raises(ProviderError,match='HTTPS'):
        OpenAICompatibleProvider()


def test_api_rejects_missing_permission_and_consent(monkeypatch):
    from backend.app.main import app
    client=TestClient(app)
    headers={'Authorization':'Bearer test-asteria-admin-token','X-Tenant-ID':'asteria'}
    r=client.post('/api/v1/agent-runtime/runs',headers=headers,json={'goal':'Investigate route outage and affected systems'})
    assert r.status_code==422 and r.json()['error']['code']=='CONSENT_REQUIRED'
    reader={'Authorization':'Bearer test-reader-token','X-Tenant-ID':'northstar'}
    r=client.post('/api/v1/agent-runtime/runs',headers=reader,json={'goal':'Investigate route outage and affected systems', 'allow_external_model':True})
    assert r.status_code==403
    status=client.get('/api/v1/agent-runtime/status',headers=headers)
    assert status.status_code==200 and status.json()['business_tools']=='READ_ONLY'
    assert status.json()['supports_autonomous_multi_agent_coordination'] is False


def test_api_launches_real_harness_and_returns_structured_result(monkeypatch):
    from backend.app.main import app
    from backend.app.api_v1 import router as routes
    from backend.app.config import Settings
    from types import SimpleNamespace

    record=Store()
    p=Provider([plan(),tool('incident_context',{'entity_id':'INC-AST-ROUTE-OUTAGE'}),final(['EVD-AST-0001'])])
    client=SimpleNamespace(settings=Settings(tenant_id='asteria'))
    monkeypatch.setattr(routes,'OpenAICompatibleProvider',lambda:p)
    monkeypatch.setattr(routes,'client_for',lambda principal:client)
    monkeypatch.setattr(routes.GraphSnapshot,'load',classmethod(lambda cls, c:fixture_graph()))
    monkeypatch.setattr(routes,'GraphRunStore',lambda c:record)
    web=TestClient(app)
    r=web.post('/api/v1/agent-runtime/runs',headers={
        'Authorization':'Bearer test-asteria-admin-token','X-Tenant-ID':'asteria'
    },json={'goal':'Investigate route outage and affected systems','source_entity_id':'INC-AST-ROUTE-OUTAGE',
             'allow_external_model':True})
    assert r.status_code==200,r.text
    body=r.json()
    assert body['status']=='COMPLETED' and body['citations']==['EVD-AST-0001']
    assert len(body['trace'])==3
    assert record.run['subject']=='asteria-demo-admin'
    wrong=web.post('/api/v1/agent-runtime/runs',headers={
        'Authorization':'Bearer test-asteria-admin-token','X-Tenant-ID':'northstar'
    },json={'goal':'Investigate route outage and affected systems','allow_external_model':True})
    assert wrong.status_code==403


def test_natural_language_query_without_id_uses_search_tool():
    p=Provider([plan(),tool('find_entities',{'query':'Route State Database','limit':8}),
                final(['SYS-AST-ROUTE-DB'])])
    h,record=runtime(p)
    result=h.run(AgentSettings(goal='Find the Route State Database and explain its organizational relevance.',
                               allow_external_model=True),subject='investigator')
    assert result.status=='COMPLETED'
    assert result.citations==['SYS-AST-ROUTE-DB']
    assert record.run['source_entity_id'] is None


def test_limits_prevent_invalid_steps_and_oversized_tool_calls():
    with pytest.raises(Exception):AgentSettings(goal='Investigate route outage and affected systems',max_steps=99)
    p=Provider([plan(),Completion('',[{'id':'123','name':'get_entity','arguments':'x'*3000}],50), final()])
    h,st=runtime(p)
    result=h.run(settings(),subject='tester')
    assert result.status=='FAILED' and st.result['status']=='FAILED'
    assert 'Invalid or oversized tool call' in result.error


def test_memory_lookup_is_read_only_and_does_not_promote_unverified_claims():
    snapshot=fixture_graph()
    snapshot.nodes['FIND-TEST-1']={'id':'FIND-TEST-1','status':'UNVERIFIED','statement':'Possible database regression',
                                  '_labels':['Entity','Finding'],'source_ref_id':'EVD-AST-0001'}
    snapshot.add_edge('FIND-TEST-1','ABOUT','INC-AST-ROUTE-OUTAGE')
    registry=ToolRegistry(lambda:snapshot)
    result=registry.execute('related_memory',{'entity_id':'INC-AST-ROUTE-OUTAGE','limit':10})
    assert any(x['record']['id']=='FIND-TEST-1' and x['record']['status']=='UNVERIFIED' for x in result['items'])
    assert result['note'].startswith('Historical memory is not automatically verified')
