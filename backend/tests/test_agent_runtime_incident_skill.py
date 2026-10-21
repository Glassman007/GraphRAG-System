"""Offline, deterministic tests for the opt-in incident skill; no provider/network writes."""
import json

import pytest
from pydantic import ValidationError

from backend.app.agent_runtime.harness import AgentHarness, AgentSettings
from backend.app.agent_runtime.incident_skill import build_incident_packet
from backend.app.agent_runtime.provider import Completion
from backend.app.agent_runtime.tools import ToolRegistry
from backend.tests.test_agent_runtime_evidence_grounding import asteria_fixture_graph
from backend.tests.test_agent_runtime_step1 import Provider, Store, plan, tool, final, fixture_graph

INCIDENT='INC-AST-ROUTE-OUTAGE'


def run_with(response):
    provider=Provider([response])
    store=Store()
    snap=asteria_fixture_graph()
    harness=AgentHarness(provider=provider,tools=ToolRegistry(lambda:snap),store=store,tenant='asteria')
    result=harness.run(AgentSettings(goal='Investigate route outage and justify evidence',
                                     source_entity_id=INCIDENT, execution_mode='incident_skill',
                                     allow_external_model=True, max_tokens=4000),subject='efficiency_test')
    return result,store,provider


def good():
    return Completion(json.dumps({'answer': 'The v3 schema mismatch is recorded; the full outage cause is not independently proven.',
          'citations':['EVD-AST-0003','EVD-AST-0005'],
          'knowledge_gaps':['Direct confirmation of whole-incident causality'], 'confidence':'uncertain'}),[],800)


def test_one_model_call_and_real_read_only_tool_trace():
    result, store, provider=run_with(good())
    assert result.status=='COMPLETED',result.error
    assert [x['kind'] for x in store.steps] == ['PLAN','TOOL','EVIDENCE_REVIEW','FINAL']
    assert result.tokens_used==800
    assert len(provider.calls)==1 and provider.calls[0][1]==[]
    messages=provider.calls[0][0]
    packet_text=messages[1]['content']
    assert 'INC-AST-ROUTE-OUTAGE' in packet_text
    assert 'EVD-AST-0003' in packet_text and 'SchemaError' in packet_text
    assert 'EVT-AST-DEPLOY' in packet_text
    assert len(json.dumps(messages))<7000
    assert store.result['status']=='COMPLETED'


def test_citation_hallucination_fails_closed():
    bad=Completion(json.dumps({'answer': 'A fabricated source supposedly proves the cause.',
          'citations':['EVD-FAKE-123'],'knowledge_gaps':[], 'confidence':'supported'}), [],100)
    result,store,_=run_with(bad)
    assert result.status=='FAILED'
    assert not result.answer and not result.citations
    assert 'INVALID_CITATIONS' in [s['kind'] for s in store.steps]


def test_causal_claim_requires_directly_reviewed_evidence():
    bad=Completion(json.dumps({'answer': 'The outage was fully explained by the deployment.',
          'citations':[INCIDENT], 'knowledge_gaps':[], 'confidence':'supported'}),[],120)
    result,store,_=run_with(bad)
    assert result.status=='FAILED'
    assert 'INVALID_EVIDENCE_GROUNDING' in [s['kind'] for s in store.steps]


def test_packet_deduplicates_dossier_evidence_and_discloses_omissions():
    snap=asteria_fixture_graph()
    ctx=ToolRegistry(lambda:snap).execute('incident_context', {'entity_id':INCIDENT})
    packet, allowed=build_incident_packet(snap,ctx,INCIDENT)
    assert {'EVD-AST-0003','EVD-AST-0004','EVD-AST-0005'}.issubset(allowed)
    assert all(x['id'] not in {'EVD-AST-0003','EVD-AST-0004','EVD-AST-0005'} for x in packet['other_evidence'])
    assert all(isinstance(n,int) and n>=0 for n in packet['omitted_counts'].values())


def test_non_incident_is_rejected_before_any_model_call():
    provider=Provider([])
    store=Store()
    graph=asteria_fixture_graph()
    harness=AgentHarness(provider=provider,tools=ToolRegistry(lambda:graph),store=store,tenant='asteria')
    with pytest.raises(ValueError,match='current Incident'):
        harness.run(AgentSettings(goal='Investigate route database evidence',source_entity_id='SYS-AST-ROUTE-DB',
                                  execution_mode='incident_skill',allow_external_model=True),subject='test')
    assert len(provider.calls)==0


def test_default_general_behavior_is_not_changed():
    prov=Provider([plan(),tool('incident_context',{'entity_id':INCIDENT}),final(['EVD-AST-0001'])])
    store=Store()
    harness=AgentHarness(provider=prov,tools=ToolRegistry(fixture_graph),store=store,tenant='asteria')
    result=harness.run(AgentSettings(goal='Investigate route outage and the evidence',source_entity_id=INCIDENT,
                                     allow_external_model=True),subject='general_regression')
    assert result.status=='COMPLETED'
    assert len(prov.calls)==3


def test_missing_consent_and_unknown_mode_are_rejected():
    with pytest.raises(ValidationError):
        AgentSettings(goal='Investigate route outage evidence',execution_mode='arbitrary')
    prov=Provider([])
    store=Store()
    harness=AgentHarness(provider=prov,tools=ToolRegistry(asteria_fixture_graph),store=store,tenant='asteria')
    with pytest.raises(ValueError,match='consent'):
        harness.run(AgentSettings(goal='Investigate route outage evidence',source_entity_id=INCIDENT,
                                  execution_mode='incident_skill'),subject='no-consent')
