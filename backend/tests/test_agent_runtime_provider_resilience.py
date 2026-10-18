"""Mocked provider reliability checks; never contacts external APIs."""
import httpx
import pytest
from backend.app.agent_runtime.provider import OpenAICompatibleProvider, ProviderError, Completion
from backend.tests.test_agent_runtime_step1 import Provider, Store, runtime, settings, plan, final


class MockClient:
    def __init__(self, responses, payloads):
        self.responses = responses
        self.payloads = payloads
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None
    def post(self, url, *, json, headers):
        self.payloads.append(json)
        return self.responses.pop(0)


def test_groq_json_plan_low_reasoning_and_retry_after(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY','gsk_fake_for_mock_test_only')
    monkeypatch.setenv('GRAPH_HACKS_AGENT_MODEL','openai/gpt-oss-120b')
    import backend.app.agent_runtime.provider as module
    waited = []
    monkeypatch.setattr(module.time,'sleep',lambda t:waited.append(t))
    response = httpx.Response(200,json={'choices':[{'message':{'content':'{"steps":["Inspect incident"]}'},'finish_reason':'stop'}], 'usage':{'total_tokens':71}})
    queue = [httpx.Response(429,headers={'retry-after':'2'}),response]
    payloads=[]
    monkeypatch.setattr(module.httpx,'Client',lambda **k:MockClient(queue,payloads))
    p=OpenAICompatibleProvider(provider='groq')
    result=p.complete([{'role':'system','content':'JSON required'}],[], remaining_seconds=45,max_output_tokens=1250)
    assert result.content == '{"steps":["Inspect incident"]}'
    assert len(payloads)==2
    assert payloads[0]['response_format']=={'type':'json_object'}
    assert payloads[0]['reasoning_effort']=='low'
    assert payloads[0]['max_completion_tokens']==1250
    assert waited[0]>=2


def test_groq_retry_after_longer_than_agent_budget_fails_cleanly(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY','gsk_fake_for_mock_test_only')
    monkeypatch.setenv('GRAPH_HACKS_AGENT_MODEL','openai/gpt-oss-120b')
    import backend.app.agent_runtime.provider as module
    responses=[httpx.Response(429,headers={'retry-after':'75'})]
    monkeypatch.setattr(module.httpx,'Client',lambda **k:MockClient(responses,[]))
    p=OpenAICompatibleProvider(provider='groq')
    with pytest.raises(ProviderError,match='rate limited .*retry-after=75'):
        p.complete([{'role':'system','content':'JSON required'}],[], remaining_seconds=15,max_output_tokens=1250)


def test_planning_truncation_is_retried_once():
    p=Provider([Completion('{"steps":["unfinished', [], 40, finish_reason='length'), plan(), final()])
    h, store=runtime(p)
    result=h.run(settings(), subject='tester')
    assert result.status=='COMPLETED'
    assert any(step['kind']=='PLAN_RETRY' for step in store.steps)
    assert len(p.calls)==3


def test_malformed_final_response_can_recover_in_next_iteration():
    p=Provider([plan(),Completion('{"answer":"unclosed', [], 40),final()])
    h, store=runtime(p)
    result=h.run(settings(max_steps=3),subject='tester')
    assert result.status=='COMPLETED'
    assert any(step['kind']=='INVALID_RESPONSE' for step in store.steps)
