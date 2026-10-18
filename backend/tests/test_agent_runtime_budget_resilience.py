"""Budget behavior: scripted provider only; no external requests or FalkorDB writes."""
import json

from backend.app.agent_runtime.harness import bounded_observation
from backend.app.agent_runtime.provider import Completion
from backend.tests.test_agent_runtime_step1 import Provider, final, plan, runtime, settings, tool


def test_large_tool_observation_is_json_safe_and_omissions_cannot_be_cited():
    items = [{'id':f'INC-FAKE-{idx}', 'description':'a' * 650} for idx in range(45)]
    compressed=bounded_observation({'items': items, 'truncated': False})
    decoded=json.loads(compressed)
    assert len(compressed) <= 4500
    assert decoded['_observation_truncated'] is True
    assert 'INC-FAKE-44' not in compressed
    assert decoded['items'][0]['id'] == 'INC-FAKE-0'


def test_bounded_agent_produces_final_before_overrunning_budget():
    provider=Provider([
        Completion(plan().content, [], 100),
        Completion('', tool('get_entity', {'entity_id':'INC-AST-ROUTE-OUTAGE'}).calls, 5700),
        Completion('', tool('graph_neighbors', {'entity_id':'INC-AST-ROUTE-OUTAGE'}, idx=2).calls, 5200),
        Completion(final().content, [], 1800),
    ])
    harness, store=runtime(provider)
    result=harness.run(settings(max_steps=4),subject='budget-test')
    assert result.status == 'COMPLETED'
    assert result.tokens_used == 12800
    assert any(step['kind']=='FINALIZATION' for step in store.steps)
    # The model's final response cannot trigger further tool calls.
    assert provider.calls[-1][1] == []


def test_billed_budget_overshoot_is_not_labeled_success():
    provider=Provider([
        Completion(plan().content, [], 5000),
        Completion('', tool('get_entity', {'entity_id':'INC-AST-ROUTE-OUTAGE'}).calls, 16000),
    ])
    harness, store=runtime(provider)
    result=harness.run(settings(max_steps=4), subject='budget-test')
    assert result.status == 'INCOMPLETE'
    assert 'budget' in result.error.lower()
    assert result.answer == '' and result.citations == []
    assert store.steps[-1]['kind']=='LIMIT'


def test_tool_calls_after_finalization_are_not_executed():
    provider=Provider([
        Completion(plan().content, [], 100),
        Completion('', tool('get_entity', {'entity_id':'INC-AST-ROUTE-OUTAGE'}).calls, 5700),
        Completion('', tool('get_entity', {'entity_id':'SYS-AST-ROUTE-DB'}, idx=2).calls, 5200),
        Completion('', tool('get_entity', {'entity_id':'SYS-AST-ROUTE-DB'}, idx=3).calls, 1000),
    ])
    harness, store=runtime(provider)
    result=harness.run(settings(max_steps=4),subject='budget-test')
    assert result.status=='FAILED'
    assert 'tool access was disabled' in result.error
    assert len([s for s in store.steps if s['kind']=='TOOL']) == 2
