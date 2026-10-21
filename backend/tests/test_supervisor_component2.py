"""Component 2 acceptance: actual specialist calls, scheduling, handoffs and safeguards."""
from __future__ import annotations

import json
import threading
import time
from collections import defaultdict

import pytest
from fastapi.testclient import TestClient

from backend.app.agent_runtime.provider import Completion, ProviderError
from backend.app.agent_runtime.supervisor import (
    Supervisor, SupervisorSettings, TaskSpec, validate_dag, DEFAULT_AGENTS,
)
from backend.app.agent_runtime.tools import ToolRegistry
from backend.app.services.phase4_graph import GraphSnapshot, GraphEdge


INCIDENT = 'INC-AST-ROUTE-OUTAGE'


def graph():
    return GraphSnapshot({
        INCIDENT: {'id': INCIDENT, 'name': 'Dispatch incident', 'status': 'OPEN', '_labels': ['Entity', 'Incident']},
        'SYS-AST-DISPATCH': {'id': 'SYS-AST-DISPATCH', 'name': 'Dispatch', '_labels': ['Entity', 'System']},
        'SYS-AST-DB': {'id': 'SYS-AST-DB', 'name': 'Dispatch database', '_labels': ['Entity', 'System']},
        'EVD-AST-001': {'id': 'EVD-AST-001', 'name': 'Application trace', '_labels': ['Entity', 'Evidence']},
    }, [GraphEdge('SYS-AST-DISPATCH', 'DEPENDS_ON', 'SYS-AST-DB', {}),
        GraphEdge('EVD-AST-001', 'ABOUT', INCIDENT, {}),
        GraphEdge('SYS-AST-DB', 'AFFECTS', INCIDENT, {})])


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.run = None
        self.tasks = {}
        self.events = []
        self.result = None
    def start(self, run):
        self.run = run
    def task(self, run_id, task):
        with self.lock:
            self.tasks[task['id']] = task.copy()
    def event(self, run_id, event):
        with self.lock:
            self.events.append(event.copy())
    def finish(self, run_id, result):
        self.result = result


class ScriptedProvider:
    name = 'scripted'
    model = 'scripted-test'
    def __init__(self, *, bad_citation=False, conflict=False, transient_failure=False, planner=False):
        self.lock = threading.RLock()
        self.calls = defaultdict(int)
        self.handoffs = []
        self.bad_citation = bad_citation
        self.conflict = conflict
        self.transient_failure = transient_failure
        self.planner = planner

    def complete(self, messages, tools, **kwargs):
        if not tools:
            if 'task planner' in messages[0]['content']:
                return Completion(json.dumps({'tasks': [
                    {'id': 'collect_evidence', 'objective': 'Gather relevant organizational source evidence',
                     'capability': 'evidence_retrieval', 'depends_on': []},
                    {'id': 'verify_sources', 'objective': 'Independently verify the supplied source evidence',
                     'capability': 'verification', 'depends_on': ['collect_evidence']},
                ]}), [], 65)
            return Completion(json.dumps({'answer': 'Graph evidence supports an investigation proposal, not an executed fix.',
                                          'citations': [INCIDENT], 'confidence': 'uncertain', 'knowledge_gaps': []}), [], 90)
        context = json.loads(messages[1]['content'])
        task_id = context['task_id']
        with self.lock:
            self.calls[task_id] += 1
            attempt = self.calls[task_id]
            self.handoffs.append((task_id, context['validated_handoffs']))
        if self.transient_failure and task_id == 'analyze_dependencies' and attempt == 1:
            raise ProviderError('groq returned HTTP 503')
        if not any(msg['role'] == 'tool' for msg in messages):
            tool_name = 'incident_context' if 'incident_context' in [d['function']['name'] for d in tools] else 'get_entity'
            return Completion('', [{'id': f'{task_id}-call', 'name': tool_name,
                                     'arguments': json.dumps({'entity_id': INCIDENT})}], 30)
        citation = 'EVD-UNSEEN' if self.bad_citation and task_id == 'retrieve_evidence' else INCIDENT
        value = 'broken' if task_id == 'retrieve_evidence' and self.conflict else 'healthy'
        return Completion(json.dumps({'summary': f'Validated findings for {task_id}, recorded by read-only graph observations.',
                                      'citations': [citation], 'knowledge_gaps': [], 'confidence': 'supported',
                                      'risk': 'low', 'requires_human_review': False, 'conflicts_with': [],
                                      'assertions': ([{'subject_id': INCIDENT, 'predicate': 'status',
                                                      'value': value}] if self.conflict else [])}), [], 45)


def make(provider=None, permissions=None):
    store = Store()
    runtime = Supervisor(provider=provider or ScriptedProvider(), tools=ToolRegistry(graph), store=store,
                         tenant='asteria', permissions=permissions or frozenset({'READ_GRAPH', 'READ_EVIDENCE'}))
    return runtime, store


def options(**kwargs):
    return SupervisorSettings(goal='Investigate the source incident and identify downstream dependencies',
                              source_entity_id=INCIDENT, allow_external_model=True, **kwargs)


def test_four_specialists_execute_actual_tools_and_validated_handoffs():
    provider = ScriptedProvider()
    supervisor, store = make(provider)
    report = supervisor.run(options(), subject='asteria-admin')
    assert report.status == 'COMPLETED', report.error
    assert len(report.tasks) == 4
    assert all(t['status'] == 'COMPLETED' for t in report.tasks)
    assert set(provider.calls) == {'analyze_dependencies', 'retrieve_evidence', 'verify_findings', 'propose_remediation'}
    handoffs = {task: refs for task, refs in provider.handoffs if refs}
    assert {ref['task_id'] for ref in handoffs['verify_findings']} == {'analyze_dependencies', 'retrieve_evidence'}
    assert [ref['task_id'] for ref in handoffs['propose_remediation']] == ['verify_findings']
    assert report.citations == [INCIDENT] and store.result['status'] == 'COMPLETED'
    assert len([e for e in store.events if e['kind'] == 'SPECIALIST_TOOL']) == 4
    assert 'ASSIGN' in {e['kind'] for e in store.events}


def test_fabricated_specialist_citation_fails_closed_and_blocks_dependent_work():
    supervisor, _ = make(ScriptedProvider(bad_citation=True))
    report = supervisor.run(options(), subject='tester')
    states = {task['id']: task for task in report.tasks}
    assert states['retrieve_evidence']['status'] == 'FAILED'
    assert states['verify_findings']['status'] == 'BLOCKED'
    assert states['propose_remediation']['status'] == 'BLOCKED'
    assert report.status == 'NEEDS_REVIEW' and not report.citations


def test_conflicting_specialist_assertions_trigger_human_escalation():
    runtime, _ = make(ScriptedProvider(conflict=True))
    run = runtime.run(options(), subject='tester')
    assert any(c['kind'] == 'INCOMPATIBLE_ASSERTIONS' for c in run.conflicts)
    assert run.status == 'NEEDS_REVIEW'
    assert run.answer  # conflict is surfaced even when supervisor synthesis is available


def test_transient_provider_failure_retries_with_alternate_qualified_agent():
    provider = ScriptedProvider(transient_failure=True)
    runtime, _ = make(provider)
    result = runtime.run(options(), subject='tester')
    task = next(t for t in result.tasks if t['id'] == 'analyze_dependencies')
    assert task['attempts'] == 2 and task['status'] == 'COMPLETED'
    assert any(event['kind'] == 'RETRY' for event in result.events)
    assert result.status == 'COMPLETED'


def test_dependency_cycle_unknown_and_duplicate_ids_are_rejected():
    a = TaskSpec(id='task_a', objective='Read organizational source data', capability='investigation', depends_on=['task_b'])
    b = TaskSpec(id='task_b', objective='Validate organizational source data', capability='verification', depends_on=['task_a'])
    with pytest.raises(ValueError, match='Cyclic'):
        validate_dag([a, b], 6)
    with pytest.raises(ValueError, match='duplicate task IDs'):
        validate_dag([a, a], 6)
    with pytest.raises(ValueError, match='Unknown dependency'):
        validate_dag([a, TaskSpec(id='task_b', objective='Validate source data used in analysis', capability='verification', depends_on=['missing'])], 6)


def test_provider_driven_decomposition_for_nonincident_goal():
    provider = ScriptedProvider(planner=True)
    runtime, _ = make(provider)
    run = runtime.run(SupervisorSettings(goal='Evaluate coordination responsibilities within our organization',
                                         allow_external_model=True), subject='tester')
    assert len(run.tasks) == 2
    assert run.tasks[0]['capability'] == 'evidence_retrieval'
    assert run.tasks[1]['depends_on'] == ['collect_evidence']


def test_no_consent_prevents_provider_and_store_calls():
    runtime, store = make()
    with pytest.raises(ValueError, match='consent'):
        runtime.run(SupervisorSettings(goal='Investigate company incident and graph evidence'), subject='tester')
    assert store.run is None


def test_capability_permissions_fail_closed():
    runtime, _ = make(permissions=frozenset({'READ_GRAPH'}))
    result = runtime.run(options(), subject='test-reader')
    assert all(t['status'] == 'BLOCKED' for t in result.tasks)
    assert any(e['reason'] == 'TASK_BLOCKED' for e in result.escalations)
    assert result.status == 'NEEDS_REVIEW'


def test_api_permissions_consent_and_live_supervisor_execution(monkeypatch):
    from backend.app.main import app
    from backend.app.api_v1 import router as routes
    from backend.app.config import Settings
    from types import SimpleNamespace
    client = TestClient(app)
    headers = {'Authorization': 'Bearer test-asteria-admin-token', 'X-Tenant-ID': 'asteria'}
    endpoint = '/api/v1/agent-runtime/supervisor/runs'
    denied = client.post(endpoint, headers=headers, json={'goal': 'Investigate graph incident and source evidence'})
    assert denied.status_code == 422 and denied.json()['error']['code'] == 'CONSENT_REQUIRED'
    denied = client.post(endpoint, headers={'Authorization': 'Bearer test-reader-token'},
                         json={'goal': 'Investigate graph incident and source evidence', 'allow_external_model': True})
    assert denied.status_code == 403
    registry = client.get('/api/v1/agent-runtime/supervisor/registry', headers=headers)
    assert registry.status_code == 200 and len(registry.json()['agents']) >= 5
    store = Store()
    monkeypatch.setattr(routes, 'OpenAICompatibleProvider', ScriptedProvider)
    monkeypatch.setattr(routes, 'client_for', lambda principal: SimpleNamespace(settings=Settings(tenant_id='asteria')))
    monkeypatch.setattr(routes.GraphSnapshot, 'load', classmethod(lambda cls, db: graph()))
    monkeypatch.setattr(routes, 'GraphSupervisorStore', lambda db: store)
    from backend.tests.test_agent_memory_component3 import Backend
    monkeypatch.setattr(routes, 'GraphMemoryStore', lambda db: Backend())
    result = client.post(endpoint, headers=headers,
                         json={'goal': 'Investigate graph incident and source evidence',
                               'source_entity_id': INCIDENT, 'allow_external_model': True})
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'COMPLETED'
    assert len(result.json()['tasks']) == 4
    assert store.run['tenant'] == 'asteria'


def test_independent_incident_specialists_really_start_in_parallel():
    rendezvous = threading.Barrier(2, timeout=5)

    class ParallelProvider(ScriptedProvider):
        def complete(self, messages, tools, **kwargs):
            if tools:
                context = json.loads(messages[1]['content'])
                if context['task_id'] in {'analyze_dependencies', 'retrieve_evidence'} and not any(m['role'] == 'tool' for m in messages):
                    rendezvous.wait()
            return super().complete(messages, tools, **kwargs)

    runtime, _ = make(ParallelProvider())
    result = runtime.run(options(max_parallel=2), subject='tester')
    assert result.status == 'COMPLETED', result.error
    assigned = [e['task_id'] for e in result.events if e['kind'] == 'ASSIGN']
    assert set(assigned[:2]) == {'analyze_dependencies', 'retrieve_evidence'}


def test_critical_risk_requires_review_even_with_supported_citations():
    class RiskProvider(ScriptedProvider):
        def complete(self, messages, tools, **kwargs):
            reply = super().complete(messages, tools, **kwargs)
            if tools and not reply.calls and json.loads(messages[1]['content'])['task_id'] == 'verify_findings':
                data = json.loads(reply.content)
                data['risk'] = 'critical'
                return Completion(json.dumps(data), [], reply.tokens)
            return reply

    runtime, _ = make(RiskProvider())
    report = runtime.run(options(), subject='tester')
    assert report.status == 'NEEDS_REVIEW'
    assert report.answer
    assert any(e['reason'] == 'SPECIALIST_REVIEW_REQUIRED' and e['task_ids'] == ['verify_findings']
               for e in report.escalations)


def test_nonretryable_provider_http_404_does_not_fabricate_success_or_retry():
    class BadProvider(ScriptedProvider):
        def complete(self, messages, tools, **kwargs):
            if tools and json.loads(messages[1]['content'])['task_id'] == 'retrieve_evidence':
                raise ProviderError('groq returned HTTP 404')
            return super().complete(messages, tools, **kwargs)

    runtime, _ = make(BadProvider())
    result = runtime.run(options(), subject='tester')
    task = next(t for t in result.tasks if t['id'] == 'retrieve_evidence')
    assert task['attempts'] == 1 and task['status'] == 'FAILED'
    assert result.status == 'NEEDS_REVIEW'
    assert result.answer == ''
