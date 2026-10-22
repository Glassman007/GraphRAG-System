"""Two-agent deadlock: actual Asteria fixture, read-only tool, model loop grounding.

No database or external provider is needed. The live FalkorDB graph is not
assumed to match this pack until a separate live check succeeds.
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.app.agent_runtime.harness import AgentHarness, AgentSettings
from backend.app.agent_runtime.provider import Completion
from backend.app.agent_runtime.tools import ToolRegistry, declarations
from backend.app.services.phase4_graph import GraphEdge, GraphSnapshot


ROOT = Path(__file__).resolve().parents[2]
A = 'TASK-AST-DEADLOCK-A'
B = 'TASK-AST-DEADLOCK-B'


def fixture():
    data = json.loads((ROOT / 'fixtures/asteria/v1/seed/03_coordination.json').read_text())
    return GraphSnapshot(
        {n['id']: {**n['properties'], '_labels':['Entity', n['label']]} for n in data['nodes']},
        [GraphEdge(e['source'],e['type'],e['target'],e.get('properties') or {}) for e in data['edges']],
    )


def test_fixture_deadlock_reports_both_directed_edges_and_assigned_agents():
    report = ToolRegistry(fixture).execute('task_blockers',{'entity_id': A})
    assert report['deadlock_detected'] is True
    assert report['cycles'][0]['task_ids'] == [A, B, A]
    assert [(e['source'], e['type'], e['target']) for e in report['cycles'][0]['blocking_edges']] == [
        (A, 'BLOCKED_BY', B), (B, 'BLOCKED_BY', A),
    ]
    assignments = {(a['task_id'], a['agent']['id']) for a in report['assignments']}
    assert assignments == {(A, 'AGENT-AST-INVESTIGATOR'), (B, 'AGENT-AST-POLICY')}
    assert all(e['type'] in {'BLOCKED_BY','REQUIRES'} for e in report['blocking_edges'])
    assert 'write' not in report['scope'].lower()
    assert 'task_blockers' in [x['function']['name'] for x in declarations()]


def test_no_false_cycle_when_reverse_edge_expired():
    snapshot = fixture()
    snapshot.remove_edges(lambda e: e.source == B and e.target == A and e.type == 'BLOCKED_BY')
    report = ToolRegistry(lambda:snapshot).execute('task_blockers',{'entity_id':A})
    assert report['deadlock_detected'] is False
    assert report['cycles'] == []


def test_task_blockers_is_type_safe_and_read_only():
    snapshot = fixture()
    original = [(e.source,e.type,e.target) for e in snapshot.edges]
    registry = ToolRegistry(lambda:snapshot)
    assert registry.execute('task_blockers', {'entity_id':'AGENT-AST-POLICY'})['error'] == 'NOT_A_TASK'
    assert registry.execute('task_blockers', {'entity_id':A,'max_depth':2})['deadlock_detected']
    assert [(e.source,e.type,e.target) for e in snapshot.edges] == original


class ScriptedProvider:
    name='scripted'
    model='scripted-test'
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts=[]
    def complete(self, messages, tools, **kwargs):
        self.prompts.append(json.dumps(messages))
        assert self.responses, 'unexpected model call'
        return Completion(self.responses.pop(0), [], 100)


class MemoryStore:
    def __init__(self):
        self.saved=[]
    def start(self, item):self.saved.append(('start',item))
    def trace(self, run_id, item):self.saved.append(('trace',item))
    def finish(self, run_id, item):self.saved.append(('finish',item))


def conclusion(citations):
    return json.dumps({'answer':'Two task-to-task blocking edges form a recorded cycle; escalate to a human to review dependencies without mutating the graph.',
        'citations':citations,'knowledge_gaps':['Policy approval to change either dependency has not been obtained'],
        'confidence':'supported'})


def test_autonomous_task_investigation_must_review_cycle_and_cite_both_tasks():
    # This model tries to finalize prematurely (and then cites only one task).
    # The harness must first fetch *real* graph evidence, then reject the partial citation.
    provider=ScriptedProvider([
        json.dumps({'steps':['Check directed blockers', 'Verify assignments', 'Recommend human escalation']}),
        conclusion([A]),
        conclusion([A]),
        conclusion([A,B]),
    ])
    store=MemoryStore()
    runner=AgentHarness(provider=provider,tools=ToolRegistry(fixture),store=store,tenant='asteria')
    result=runner.run(AgentSettings(goal=f'Investigate directed blocking cycle between {A} and {B}, without action',
        source_entity_id=A, max_steps=4,allow_external_model=True),subject='test-user')
    assert result.status=='COMPLETED'
    assert result.citations==[A,B]
    assert result.plan[0]=='Check directed blockers'
    assert any(e['kind']=='TASK_BLOCKER_REVIEW' and f'{A} -> {B} -> {A}' in e['summary'] for e in result.trace)
    assert any(e['kind']=='INVALID_TASK_GROUNDING' for e in result.trace)
    assert any('REQUIRED TASK BLOCKER REVIEW' in prompt for prompt in provider.prompts[2:])
    assert store.saved[-1][1]['status']=='COMPLETED'
    assert not any(x['kind']=='TOOL_ERROR' for x in result.trace)
