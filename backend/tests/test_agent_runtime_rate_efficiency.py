"""No remote calls. Assertions for context cost, Groq 8K TPM and incomplete status."""
from __future__ import annotations

import json

import httpx
import pytest

from backend.app.agent_runtime.harness import compact_observation, lean_declarations
from backend.app.agent_runtime.provider import ProviderRateLimited, TokenPacer, _duration
from backend.tests.test_agent_runtime_step1 import Provider, plan, runtime, settings, tool, final


def test_context_compression_remains_json_and_preserves_source_relationship_ids():
    big = {'entity_id':'INC-AST-ROUTE-OUTAGE', 'items': [
        {'neighbor': {'id':f'INC-AST-{i}', 'name':'an outage' + 'x'*500},
         'relationship': {'source':'INC-AST-ROUTE-OUTAGE', 'target':f'INC-AST-{i}',
                          'type':'AFFECTS','properties':{'edge_id':'secret'+'a'*450,
                                                       'confidence':0.7,'valid_from':'2026-10-12'}}}
        for i in range(30)]}
    output = compact_observation(big)
    parsed=json.loads(output)
    assert len(output) <=1700
    assert parsed['entity_id']=='INC-AST-ROUTE-OUTAGE'
    assert 'INC-AST-0' in output
    assert 'secret' not in output
    assert 'INC-AST-29' not in output


def test_minimal_tool_schemas_preserve_tool_names_and_required_arguments():
    tools=lean_declarations()
    assert len(tools) == 9
    assert {x['function']['name'] for x in tools} >= {'graph_neighbors','get_entity','related_memory'}
    get_entity=next(x for x in tools if x['function']['name']=='get_entity')
    assert 'entity_id' in get_entity['function']['parameters']['required']
    assert 'title' not in json.dumps(tools)


def test_no_long_history_leak_and_evidence_is_usable():
    p=Provider([plan(),tool('get_entity',{'entity_id':'INC-AST-ROUTE-OUTAGE'}),
                tool('graph_neighbors',{'entity_id':'INC-AST-ROUTE-OUTAGE'},idx=2),
                final(['INC-AST-ROUTE-OUTAGE'])])
    harness,store=runtime(p)
    answer=harness.run(settings(max_steps=3),subject='demo')
    assert answer.status=='COMPLETED'
    model_messages=p.calls[-1][0]
    assert 'READ-ONLY GRAPH TOOL RESULTS' in json.dumps(model_messages)
    assert not any(m.get('role')=='tool' or m.get('tool_calls') for m in model_messages)
    assert len(json.dumps(model_messages)) < 11000


class Clock:
    def __init__(self):self.t=100.0;self.sleeps=[]
    def monotonic(self):return self.t
    def sleep(self,d):self.sleeps.append(d);self.t+=d


def test_rate_guard_blocks_when_wait_exceeds_request_deadline(monkeypatch):
    import backend.app.agent_runtime.provider as mod
    clock=Clock()
    monkeypatch.setattr(mod.time,'monotonic',clock.monotonic)
    monkeypatch.setattr(mod.time,'sleep',clock.sleep)
    limiter=TokenPacer(7200)
    limiter.reserve(4100,85)
    with pytest.raises(ProviderRateLimited,match='deadline') as exc:
        limiter.reserve(4100,30)
    assert exc.value.retry_after > 59
    assert clock.sleeps == []
    limiter.reserve(4100,85)
    assert clock.sleeps[0] >= 60


def test_remaining_token_header_is_respected(monkeypatch):
    import backend.app.agent_runtime.provider as mod
    clock=Clock()
    monkeypatch.setattr(mod.time,'monotonic',clock.monotonic)
    monkeypatch.setattr(mod.time,'sleep',clock.sleep)
    limiter=TokenPacer(7200)
    first=limiter.reserve(1500,40)
    limiter.settle(first,500,{'x-ratelimit-remaining-tokens':'100',
                               'x-ratelimit-reset-tokens':'7.66s'})
    limiter.reserve(600,30)
    assert 7.6 <= clock.sleeps[0] < 8.0
    assert _duration('2m59.56s')==pytest.approx(179.56)
    assert _duration('bad-value') is None


def test_rate_limited_harness_does_not_claim_success():
    class QuotaProvider(Provider):
        def complete(self,messages,tools,**kwargs):
            raise ProviderRateLimited('TPM guard',35)
    harness,store=runtime(QuotaProvider([]))
    report=harness.run(settings(),subject='demo')
    assert report.status=='INCOMPLETE'
    assert report.answer==''
    assert store.steps[-1]['kind']=='RATE_LIMIT'
    assert store.result['status']=='INCOMPLETE'


def test_provider_429_respects_retry_after_and_does_not_echo_credentials(monkeypatch):
    import backend.app.agent_runtime.provider as mod
    class FakeClient:
        def __init__(self):self.payloads=[]
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,*,json,headers):
            self.payloads.append(json)
            return httpx.Response(429,headers={'retry-after':'99'})
    client=FakeClient()
    monkeypatch.setenv('GROQ_API_KEY','gsk_private_mock_123')
    monkeypatch.setenv('GRAPH_HACKS_AGENT_MODEL','openai/gpt-oss-120b')
    monkeypatch.setattr(mod.httpx,'Client',lambda **kw:client)
    p=mod.OpenAICompatibleProvider(provider='groq')
    with pytest.raises(ProviderRateLimited) as err:
        p.complete([{'role':'user','content':'Small test'}],[], remaining_seconds=10,max_output_tokens=200)
    assert len(client.payloads)==1
    assert 'gsk_private_mock_123' not in str(err.value)
