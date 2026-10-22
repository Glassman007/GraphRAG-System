"""A3 scoped skills-first tests: evidence comes from Asteria fixture, no Groq."""
from collections import Counter

import pytest

from backend.app.agent_runtime import supervisor as module
from backend.app.agent_runtime.supervisor import Supervisor, SupervisorSettings, TaskSpec
from backend.app.agent_runtime.tools import ToolRegistry
from backend.tests.test_agent_runtime_evidence_grounding import asteria_fixture_graph
from backend.tests.test_supervisor_component2 import Store

INCIDENT = 'INC-AST-ROUTE-OUTAGE'
GOAL = ('Investigate the route orchestration outage and produce an evidence-backed, '
        'read-only remediation proposal. Identify the missing proof and do not execute changes.')


class DeniedProvider:
    name = 'network-disabled'
    model = 'none'
    def __init__(self):
        self.attempts = 0
    def complete(self, *args, **kwargs):
        self.attempts += 1
        raise AssertionError('Network/model dispatch must not be needed for covered skill tasks')


class TrackingTools(ToolRegistry):
    def __init__(self, snapshot, *, bad_tool=None):
        super().__init__(lambda: snapshot)
        self.calls = []
        self.bad_tool = bad_tool
    def execute(self, name, args):
        self.calls.append((name, dict(args)))
        if name == self.bad_tool:
            return {'error': 'ENTITY_NOT_FOUND', 'id': args.get('entity_id')}
        return super().execute(name, args)


def setup(*, bad_tool=None):
    snapshot = asteria_fixture_graph()
    tools = TrackingTools(snapshot, bad_tool=bad_tool)
    provider = DeniedProvider()
    store = Store()
    supervisor = Supervisor(provider=provider, tools=tools, store=store, tenant='asteria',
                            permissions=frozenset({'READ_GRAPH', 'READ_EVIDENCE'}))
    return supervisor, tools, provider, store


def settings(**overrides):
    options = dict(goal=GOAL, source_entity_id=INCIDENT, allow_external_model=True,
                   max_parallel=1, max_retries=0, max_steps_per_task=1)
    options.update(overrides)
    return SupervisorSettings(**options)


def pause_after_two_initial_tasks(store):
    done = {task for task, row in store.tasks.items() if row['status'] == 'COMPLETED'}
    return 'PAUSE' if {'analyze_dependencies', 'retrieve_evidence'} <= done else ''


def test_asteria_assigned_dependency_and_evidence_tasks_read_graph_before_provider():
    sup, tools, provider, store = setup()
    run = sup.run(settings(), subject='asteria-a3-offline',
                  control_check=lambda: pause_after_two_initial_tasks(store))
    tasks = {t['id']: t for t in run.tasks}
    assert run.status == 'PAUSED'
    assert tasks['analyze_dependencies']['status'] == 'COMPLETED'
    assert tasks['retrieve_evidence']['status'] == 'COMPLETED'
    assert tasks['verify_findings']['status'] == 'PENDING'
    assert tasks['propose_remediation']['status'] == 'PENDING'
    assert provider.attempts == 0
    assert Counter(name for name, _ in tools.calls) == Counter({'incident_context': 2, 'dependency_impact': 1})
    assert any(args.get('entity_id') == 'SYS-AST-ROUTE-API'
               for name, args in tools.calls if name == 'dependency_impact')
    for task_id in ('analyze_dependencies', 'retrieve_evidence'):
        finding = tasks[task_id]['result']
        assert finding['confidence'] == 'uncertain'
        assert INCIDENT in finding['citations']
        assert 'EVD-AST-0003' in finding['citations']
        assert all(tools.snapshot_factory().node(cid) for cid in finding['citations'])
        assert finding['knowledge_gaps']
        assert not finding['assertions']
    assert len([e for e in store.events if e['kind'] == 'SKILL_RESULT']) == 2
    assert all('READ_OK' in e['summary'] for e in store.events if e['kind'] == 'SPECIALIST_TOOL')


def test_investigation_role_uses_existing_incident_packet_without_model(monkeypatch):
    monkeypatch.setattr(module, '_incident_plan', lambda source: [
        TaskSpec(id='investigate_route', capability='investigation',
                 objective='Investigate recorded incident evidence and competing hypotheses'),
        TaskSpec(id='analyze_dependencies', capability='dependency_analysis',
                 objective='Identify bounded reverse dependency paths for incident evidence'),
    ])
    sup, tools, provider, store = setup()
    run = sup.run(settings(max_tasks=2), subject='asteria-a3-role',
                  control_check=lambda: 'PAUSE' if all(
                      t['status'] == 'COMPLETED' for t in store.tasks.values()) else '')
    states = {t['id']: t for t in run.tasks}
    assert all(t['status'] == 'COMPLETED' for t in states.values())
    assert provider.attempts == 0
    assert any(e['kind'] == 'SKILL_RESULT' and e['task_id'] == 'investigate_route'
               for e in store.events)
    assert 'EVD-AST-0005' in states['investigate_route']['result']['citations']
    assert 'complete causal chain' in ' '.join(states['investigate_route']['result']['knowledge_gaps'])


def test_typed_tool_error_stops_immediately_without_retry_or_model():
    sup, tools, provider, store = setup(bad_tool='dependency_impact')
    run = sup.run(settings(), subject='asteria-a3-error')
    states = {t['id']: t for t in run.tasks}
    assert states['analyze_dependencies']['status'] == 'FAILED'
    assert 'SKILL_TOOL_FAILED' in states['analyze_dependencies']['error']
    assert states['analyze_dependencies']['attempts'] == 1
    assert states['verify_findings']['status'] == 'BLOCKED'
    assert states['propose_remediation']['status'] == 'BLOCKED'
    assert Counter(name for name, _ in tools.calls)['dependency_impact'] == 1
    assert provider.attempts == 0
    assert any(e['kind'] == 'SPECIALIST_TOOL' and 'ENTITY_NOT_FOUND' in e['summary']
               and e['status'] == 'FAILED' for e in store.events)


def test_sparse_incident_retains_general_model_driven_specialist_fallback():
    from backend.tests.test_supervisor_component2 import graph, ScriptedProvider
    provider = ScriptedProvider()
    store = Store()
    sup = Supervisor(provider=provider, tools=ToolRegistry(graph), store=store,
                     tenant='asteria', permissions=frozenset({'READ_GRAPH', 'READ_EVIDENCE'}))
    report = sup.run(settings(max_steps_per_task=3), subject='asteria-a3-sparse')
    assert report.status == 'COMPLETED'
    assert 'analyze_dependencies' in provider.calls
    assert not any(e['kind'] == 'SKILL_RESULT' for e in store.events)


def test_model_fallback_bad_tool_target_stops_with_first_error():
    """A sparse incident must not spend five iterations on the same bad model read."""
    from backend.app.agent_runtime.provider import Completion
    from backend.tests.test_supervisor_component2 import graph

    class BadModel:
        name = 'scripted-offline'
        model = 'none'
        def __init__(self):
            self.calls = 0
        def complete(self, messages, declarations, **kwargs):
            self.calls += 1
            assert declarations  # No verified specialist results should reach synthesis.
            return Completion('', [{'id': f'bad-{self.calls}', 'name': 'incident_context',
                                    'arguments': '{"entity_id":"INC-AST-UNKNOWN"}'}], 10)

    model = BadModel()
    store = Store()
    sup = Supervisor(provider=model, tools=ToolRegistry(graph), store=store, tenant='asteria',
                     permissions=frozenset({'READ_GRAPH', 'READ_EVIDENCE'}))
    run = sup.run(settings(max_steps_per_task=5), subject='asteria-a3-bad-model')
    states = {state['id']: state for state in run.tasks}
    assert model.calls == 2  # One attempt for each independent first-stage specialist.
    assert states['analyze_dependencies']['status'] == 'FAILED'
    assert states['retrieve_evidence']['status'] == 'FAILED'
    assert 'ENTITY_NOT_FOUND' in states['retrieve_evidence']['error']
    assert states['verify_findings']['status'] == 'BLOCKED'
    assert len([e for e in store.events if e['kind'] == 'SPECIALIST_TOOL' and e['status'] == 'FAILED']) == 2
