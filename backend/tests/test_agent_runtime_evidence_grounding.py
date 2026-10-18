"""Evidence diligence checks: scripted model, real Asteria-v1 fixture graph, no Groq/FalkorDB writes."""
import json
from pathlib import Path

from backend.app.agent_runtime.harness import AgentHarness, AgentSettings, claim_evidence_dossier
from backend.app.agent_runtime.provider import Completion
from backend.app.agent_runtime.tools import ToolRegistry
from backend.app.services.phase4_graph import GraphSnapshot, GraphEdge
from backend.tests.test_agent_runtime_step1 import Provider, Store, plan, tool


def asteria_fixture_graph():
    base = Path(__file__).resolve().parents[2] / 'fixtures' / 'asteria' / 'v1' / 'seed'
    nodes, edges = {}, []
    for path in sorted(base.glob('*.json')):
        source = json.loads(path.read_text(encoding='utf-8'))
        for n in source['nodes']:
            nodes[n['id']] = {**n['properties'], '_labels':['Entity',n['label']]}
        for e in source['edges']:
            edges.append(GraphEdge(e['source'], e['type'], e['target'], e['properties']))
    return GraphSnapshot(nodes, edges)


def trial(response):
    provider=Provider([plan(),tool('graph_neighbors',{'entity_id':'INC-AST-ROUTE-OUTAGE'}),
                       Completion(json.dumps(response), [], 120)])
    store=Store()
    harness=AgentHarness(provider=provider, tools=ToolRegistry(asteria_fixture_graph),
                         store=store, tenant='asteria')
    result=harness.run(AgentSettings(goal='Investigate route outage, cause and supporting evidence',
                                      source_entity_id='INC-AST-ROUTE-OUTAGE',max_steps=2,
                                      allow_external_model=True),subject='test')
    return result,store,provider


def test_claim_evidence_review_includes_schema_log_and_competing_cpu_metric():
    text, ids=claim_evidence_dossier(asteria_fixture_graph(),'INC-AST-ROUTE-OUTAGE')
    data=json.loads(text)
    assert data['incident_id']=='INC-AST-ROUTE-OUTAGE'
    assert 'EVD-AST-0003' in ids and 'EVD-AST-0004' in ids
    assert 'SchemaError' in text and 'CPU rose' in text
    assert 'SIMULATED' in text
    assert len(text)<3700


def test_verified_causal_summary_cites_direct_evidence():
    result,store,prov=trial({
        'answer':'A 422 SchemaError preceded the observed CPU rise; the definitive system-wide cause remains unverified.',
        'citations':['INC-AST-ROUTE-OUTAGE','CLM-AST-ROUTE-SCHEMA','EVD-AST-0003'],
        'knowledge_gaps':['Definitive root cause'], 'confidence':'uncertain'})
    assert result.status=='COMPLETED',result.error
    assert 'EVD-AST-0003' in result.citations
    assert [x['kind'] for x in store.steps]==['PLAN','TOOL','EVIDENCE_REVIEW','FINALIZATION','FINAL']
    final_context=json.dumps(prov.calls[-1][0])
    assert 'EVD-AST-0003' in final_context and 'SchemaError' in final_context
    assert prov.calls[-1][1]==[]


def test_unsupported_causal_summary_is_rejected_without_evidence_citation():
    result,store,_=trial({
        'answer':'The schema change is the cause of the route outage.',
        'citations':['INC-AST-ROUTE-OUTAGE','CLM-AST-ROUTE-SCHEMA'],
        'knowledge_gaps':[], 'confidence':'supported'})
    assert result.status=='INCOMPLETE'
    assert not result.answer and not result.citations
    assert any(x['kind']=='INVALID_EVIDENCE_GROUNDING' for x in store.steps)


def test_no_claim_linked_evidence_returns_no_dossier():
    graph=asteria_fixture_graph()
    assert claim_evidence_dossier(graph,'SYS-AST-ROUTE-DB')==('',set())
    assert claim_evidence_dossier(graph,'INC-UNKNOWN')==('',set())


def test_model_early_final_must_read_evidence_before_completion():
    first = {
        'answer':'No evidence of a schema error was found by the investigator.',
        'citations':['INC-AST-ROUTE-OUTAGE'],
        'knowledge_gaps':['Cause unknown'], 'confidence':'uncertain'}
    corrected = {
        'answer':'A 422 SchemaError is logged, but whole-incident root cause still needs validation.',
        'citations':['INC-AST-ROUTE-OUTAGE','EVD-AST-0003'],
        'knowledge_gaps':['Root cause unconfirmed'], 'confidence':'uncertain'}
    provider=Provider([plan(),Completion(json.dumps(first),[],120),
                       Completion(json.dumps(corrected),[],120)])
    store=Store()
    harness=AgentHarness(provider=provider,tools=ToolRegistry(asteria_fixture_graph),
                         store=store,tenant='asteria')
    result=harness.run(AgentSettings(goal='Investigate schema failure and evidence in route outage',
                        source_entity_id='INC-AST-ROUTE-OUTAGE',max_steps=2,
                        allow_external_model=True),subject='test')
    assert result.status=='COMPLETED'
    assert any(x['kind']=='REVIEW_REQUIRED' for x in store.steps)
    assert 'EVD-AST-0003' in result.citations
    assert 'SchemaError' in json.dumps(provider.calls[-1][0])


def test_without_remaining_iterations_an_early_answer_cannot_bypass_evidence():
    provider=Provider([plan(),Completion(json.dumps({
        'answer':'The schema migration definitely caused the outage.',
        'citations':['INC-AST-ROUTE-OUTAGE'],
        'knowledge_gaps':[], 'confidence':'supported'}),[],120)])
    store=Store()
    result=AgentHarness(provider=provider,tools=ToolRegistry(asteria_fixture_graph),
            store=store,tenant='asteria').run(AgentSettings(
            goal='Investigate cause and evidence for this outage',
            source_entity_id='INC-AST-ROUTE-OUTAGE',max_steps=1,
            allow_external_model=True),subject='test')
    assert result.status=='INCOMPLETE'
    assert result.answer==''
    assert any(x['kind']=='EVIDENCE_REVIEW' for x in store.steps)
