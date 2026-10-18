"""Regression checks for run-local redundant queries and honest neighbor pagination.

Scripted model only; no live Groq, FalkorDB connection or graph mutations.
"""
import json

import pytest

from backend.app.agent_runtime.harness import (
    AgentHarness, AgentSettings, canonical_tool_key, compact_observation,
)
from backend.app.agent_runtime.provider import Completion
from backend.app.agent_runtime.tools import ToolRegistry
from backend.app.services.phase4_graph import GraphSnapshot, GraphEdge
from backend.tests.test_agent_runtime_step1 import Provider, Store, plan, tool, final


def populated_graph(size=15):
    root='INC-AST-ROUTE-OUTAGE'
    nodes={root:{'id':root,'name':'Outage','_labels':['Entity','Incident']}}
    edges=[]
    for i in range(size):
        node_id=f'INC-AST-DOWNSTREAM-{i:02d}'
        nodes[node_id]={'id':node_id,'name':f'Downstream incident {i} - '+('details'*35),
                        '_labels':['Entity','Incident'],'status':'OPEN'}
        edges.append(GraphEdge(root,'AFFECTS',node_id,{'confidence':0.7,'relationship_kind':'candidate_propagation'}))
    return GraphSnapshot(nodes,edges)


def configured(provider, graph=None, max_steps=4, registry=None):
    store=Store()
    toolset=registry or ToolRegistry(lambda:graph or populated_graph())
    harness=AgentHarness(provider=provider, tools=toolset, store=store, tenant='asteria')
    result=harness.run(AgentSettings(goal='Investigate outage and affected systems with linked evidence',
        source_entity_id='INC-AST-ROUTE-OUTAGE', max_steps=max_steps,
        allow_external_model=True),subject='tester')
    return result, store


def test_neighborhood_pages_are_disjoint_and_progress():
    registry=ToolRegistry(lambda:populated_graph())
    p1=registry.execute('graph_neighbors',{'entity_id':'INC-AST-ROUTE-OUTAGE','limit':3})
    p2=registry.execute('graph_neighbors',{'entity_id':'INC-AST-ROUTE-OUTAGE','limit':3,'offset':3})
    assert p1['next_offset']==3 and p1['total']==15 and p1['has_more']
    assert p2['next_offset']==6
    first={x['neighbor']['id'] for x in p1['items']}
    second={x['neighbor']['id'] for x in p2['items']}
    assert first.isdisjoint(second)
    assert len(first | second)==6
    p_last=registry.execute('graph_neighbors',{'entity_id':'INC-AST-ROUTE-OUTAGE','limit':3,'offset':14})
    assert p_last['next_offset'] is None and not p_last['has_more']
    assert len(p_last['items'])==1
    with pytest.raises(Exception):
        registry.execute('graph_neighbors',{'entity_id':'INC-AST-ROUTE-OUTAGE','offset':-1})


def test_compacted_page_does_not_skip_unseen_records():
    raw=ToolRegistry(lambda:populated_graph()).execute('graph_neighbors',
        {'entity_id':'INC-AST-ROUTE-OUTAGE','limit':15})
    compact=compact_observation(raw)
    model=json.loads(compact)
    assert len(compact)<=1700
    assert model['has_more'] is True
    assert 0<len(model['items'])<len(raw['items'])
    assert model['next_offset']==len(model['items'])
    shown={x['neighbor']['id'] for x in model['items']}
    paged=ToolRegistry(lambda:populated_graph()).execute('graph_neighbors',
        {'entity_id':'INC-AST-ROUTE-OUTAGE','offset':model['next_offset'],'limit':2})
    assert paged['items'][0]['neighbor']['id'] not in shown
    assert '_observation_truncated' in model


def test_normalized_query_identity_handles_defaults_and_changed_limit():
    base={'entity_id':'INC-AST-ROUTE-OUTAGE'}
    assert canonical_tool_key('graph_neighbors',base)==canonical_tool_key('graph_neighbors',
        {'entity_id':base['entity_id'],'limit':2,'offset':0,'as_of':None})
    assert canonical_tool_key('graph_neighbors',base)!=canonical_tool_key('graph_neighbors',
        {'entity_id':base['entity_id'],'offset':2})
    assert canonical_tool_key('get_entity',base)==canonical_tool_key('get_entity',base)
    with pytest.raises(ValueError): canonical_tool_key('delete_records',{})


def test_repeated_same_page_skips_backend_read_and_suggests_offset():
    calls=[]
    registry=ToolRegistry(lambda:populated_graph())
    original=registry.execute
    def track(name,args):
        calls.append((name,args))
        return original(name,args)
    registry.execute=track
    p=Provider([plan(),tool('graph_neighbors',{'entity_id':'INC-AST-ROUTE-OUTAGE','limit':20}),
                tool('graph_neighbors',{'entity_id':'INC-AST-ROUTE-OUTAGE','limit':3},idx=2),
                final(['INC-AST-ROUTE-OUTAGE'],confidence='insufficient')])
    result,store=configured(p,max_steps=3,registry=registry)
    assert result.status=='INSUFFICIENT_EVIDENCE'
    assert len(calls)==1
    assert [step['kind'] for step in store.steps].count('DUPLICATE_TOOL')==1
    # The next model call sees an actionable suggestion instead of duplicate graph facts.
    payload=json.dumps(p.calls[-1][0])
    assert 'DUPLICATE_TOOL_QUERY' in payload
    assert 'next_offset' not in payload or 'offset' in payload
    assert 'suggested_next' in payload


def test_next_page_executes_normally_and_returns_new_neighbors():
    calls=[]
    registry=ToolRegistry(lambda:populated_graph())
    original=registry.execute
    def track(name,args):
        calls.append((name,args))
        return original(name,args)
    registry.execute=track
    p=Provider([plan(),tool('graph_neighbors',{'entity_id':'INC-AST-ROUTE-OUTAGE','limit':2}),
                tool('graph_neighbors',{'entity_id':'INC-AST-ROUTE-OUTAGE','offset':2,'limit':2},idx=2),
                final(['INC-AST-ROUTE-OUTAGE'],confidence='insufficient')])
    result,store=configured(p,max_steps=3,registry=registry)
    assert result.status=='INSUFFICIENT_EVIDENCE'
    assert len(calls)==2
    assert 'DUPLICATE_TOOL' not in [s['kind'] for s in store.steps]


def test_identical_non_neighbor_tool_query_is_skipped():
    calls=[]
    registry=ToolRegistry(lambda:populated_graph())
    original=registry.execute
    def track(name,args):calls.append((name,args)); return original(name,args)
    registry.execute=track
    p=Provider([plan(),tool('get_entity',{'entity_id':'INC-AST-ROUTE-OUTAGE'}),
                tool('get_entity',{'entity_id':'INC-AST-ROUTE-OUTAGE'},idx=2),
                final(['INC-AST-ROUTE-OUTAGE'],confidence='insufficient')])
    result,store=configured(p,max_steps=3,registry=registry)
    assert result.status=='INSUFFICIENT_EVIDENCE'
    assert len(calls)==1
    assert any(step['kind']=='DUPLICATE_TOOL' for step in store.steps)


def test_duplicate_query_only_short_feedback_no_new_citation_ids():
    p=Provider([plan(),tool('graph_neighbors',{'entity_id':'INC-AST-ROUTE-OUTAGE'}),
                tool('graph_neighbors',{'entity_id':'INC-AST-ROUTE-OUTAGE'},idx=2),
                final(['INC-AST-ROUTE-OUTAGE'], confidence='insufficient')])
    result, _=configured(p,max_steps=3)
    assert result.status=='INSUFFICIENT_EVIDENCE'
    messages=p.calls[-1][0]
    duplicate=[m for m in messages if m['role']=='user' and 'DUPLICATE_TOOL_QUERY' in m['content']]
    assert len(duplicate)==1
    assert 'Downstream incident' not in duplicate[0]['content']


def test_tool_read_only_guard_remains_strict():
    registry=ToolRegistry(lambda:populated_graph())
    with pytest.raises(ValueError,match='allowlisted'):
        registry.execute('write_graph',{'entity_id':'INC-AST-ROUTE-OUTAGE'})
