"""Component 3 acceptance: evidence-backed memory, authorization and crash recovery."""
from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.agent_runtime.memory import AgentMemory, MemoryAssertion, MemorySearch
from backend.app.agent_runtime.supervisor import Supervisor, SupervisorSettings
from backend.app.agent_runtime.tools import ToolRegistry
from backend.tests.test_supervisor_component2 import graph, Store, ScriptedProvider, INCIDENT


ROUTE = 'SYS-AST-DISPATCH'
DB = 'SYS-AST-DB'
PERMS = frozenset({'READ_GRAPH', 'READ_EVIDENCE', 'CREATE_INVESTIGATION'})


class Backend:
    def __init__(self):
        self.items = {}
        self.checkpoints = {}
        self.lock = threading.RLock()

    def save(self, entry):
        with self.lock:
            self.items[entry['id']] = copy.deepcopy(entry)

    def get(self, item_id):
        with self.lock:
            return copy.deepcopy(self.items.get(item_id))

    def candidates(self, entity_ids, query, limit):
        with self.lock:
            return [copy.deepcopy(x) for x in self.items.values() if not entity_ids or
                    x['subject_id'] in entity_ids or query][:limit]

    def conflicting(self, subject_id, predicate, value):
        with self.lock:
            return [copy.deepcopy(x) for x in self.items.values()
                    if x['subject_id'] == subject_id and x['predicate'].casefold() == predicate.casefold()
                    and x['value'].casefold() != value.casefold()
                    and x['scope'] == 'SHARED' and x['status'] == 'VERIFIED']

    def private_for_run(self, run_id, task_ids):
        with self.lock:
            return [copy.deepcopy(x) for x in self.items.values() if x['origin_run_id'] == run_id
                    and x['origin_task_id'] in task_ids and x['scope'] == 'PRIVATE' and x['status'] == 'DRAFT']

    def checkpoint(self, run_id, *, owner, payload, revision):
        with self.lock:
            self.checkpoints[(owner, run_id)] = copy.deepcopy(payload)

    def load_checkpoint(self, run_id, *, owner):
        with self.lock:
            return copy.deepcopy(self.checkpoints.get((owner, run_id)))


def setup(tenant='asteria'):
    backend = Backend()
    return AgentMemory(backend=backend, snapshot_factory=graph, tenant=tenant), backend


def claim(value=DB, subject=ROUTE, predicate='depends_on'):
    return MemoryAssertion(subject_id=subject, predicate=predicate, value=value,
                           citations=[ROUTE, DB], source_tools=['graph_neighbors'],
                           summary='Current graph establishes the dispatch-to-database dependency')


def stage(memory, *, owner='reviewer', branch='run1:research:agent1', run='run1'):
    return memory.stage(claim=claim(), run_id=run, task_id='research', agent_id='dependency_analyst',
                        owner=owner, branch_id=branch, observed_ids={ROUTE, DB},
                        confidence='supported', goal='Investigate dispatch database dependency')


def promote(memory, *, run='run1', owner='reviewer'):
    return memory.consolidate(run_id=run, verifier_task_id='verification',
                              verifier_agent_id='policy_verifier', verifier_citations=[ROUTE, DB],
                              verifier_assertions=[{'subject_id': ROUTE, 'predicate': 'depends_on', 'value': DB}],
                              verifier_confidence='supported', verifier_conflicted=False,
                              review_required=False, task_ids=['research'], owner=owner)


def search(memory, *, requester='someone_else', perms=PERMS, entity=ROUTE):
    return memory.retrieve(requester=requester, agent_id='another_agent', permissions=perms,
                           search=MemorySearch(entity_ids=[entity], query='dispatch database dependency'))


def test_private_work_branch_invisible_to_other_agents_and_tenants():
    memory, backend = setup()
    record = stage(memory)
    assert record['scope'] == 'PRIVATE' and record['status'] == 'DRAFT'
    assert search(memory) == []
    assert memory.retrieve(requester='reviewer', agent_id='different_agent', permissions=PERMS,
                           search=MemorySearch(entity_ids=[ROUTE], query='dispatch'),
                           run_id='run1', branch_id='run1:research:agent1') == []
    other = AgentMemory(backend=backend, snapshot_factory=graph, tenant='another-tenant')
    assert search(other) == []
    with pytest.raises(PermissionError):
        memory.retrieve(requester='reviewer', agent_id='dependency_analyst', permissions=frozenset({'READ_GRAPH'}),
                        search=MemorySearch(entity_ids=[ROUTE]))


def test_cross_session_agent_b_gets_provenance_without_transcripts():
    first, backend = setup()
    stage(first)
    records = promote(first)
    assert len(records) == 1 and records[0]['status'] == 'VERIFIED'
    # Simulate process restart: a new service instance reads the same durable backing store.
    after_restart = AgentMemory(backend=backend, snapshot_factory=graph, tenant='asteria')
    found = search(after_restart, requester='agent_B')
    assert len(found) == 1 and found[0]['value'] == DB
    assert found[0]['origin_agent_id'] == 'dependency_analyst'
    assert found[0]['verified_by'] == 'policy_verifier'
    assert found[0]['source_tools'] == ['graph_neighbors']
    assert found[0]['citations'] == [ROUTE, DB]
    assert 'owner' not in found[0] and 'branch_id' not in found[0]


def test_verifier_must_corroborate_same_factual_assertion():
    memory, backend = setup()
    stage(memory)
    assert memory.consolidate(run_id='run1', verifier_task_id='verification',
        verifier_agent_id='policy_verifier', verifier_citations=[ROUTE, DB],
        verifier_assertions=[{'subject_id': ROUTE, 'predicate': 'status', 'value': 'OK'}],
        verifier_confidence='supported', verifier_conflicted=False, review_required=False,
        task_ids=['research'], owner='reviewer') == []
    assert search(memory) == []
    assert promote(memory)[0]['status'] == 'VERIFIED'


def test_model_assertion_must_match_live_canonical_graph():
    memory, backend = setup()
    record = memory.stage(claim=claim('SYS-DOES-NOT-EXIST'), run_id='run1', task_id='research',
                          agent_id='dependency_analyst', owner='reviewer', branch_id='secret',
                          observed_ids={ROUTE, DB}, confidence='supported', goal='Database dependency discovery')
    with pytest.raises(ValueError, match='Verifier did not validate'):
        memory.verify(record['id'], verifier_agent_id='policy_verifier', verifier_task_id='verification',
                      checked_citations=[ROUTE, DB], owner='reviewer')
    assert search(memory) == []
    with pytest.raises(ValueError, match='observed'):
        memory.stage(claim=claim(), run_id='x', task_id='y', agent_id='z', owner='reviewer',
                     branch_id='private', observed_ids={ROUTE}, confidence='supported', goal='test')


def test_conflict_does_not_overwrite_verified_prior_claim():
    memory, backend = setup()
    original = stage(memory)
    assert promote(memory)[0]['status'] == 'VERIFIED'
    # New claim represents a contradictory source after a disputed graph update.
    newer = stage(memory, run='run2', branch='another')
    # Reuse the current graph fact, but fake an existing contradictory VERIFIED record.
    other = backend.get(original['id'])
    other['id'] = 'MEM-' + 'A' * 32
    other['value'] = 'SYS-OTHER-DATABASE'
    backend.save(other)
    result = memory.verify(newer['id'], verifier_agent_id='policy_verifier',
                           verifier_task_id='verification', checked_citations=[ROUTE, DB], owner='reviewer')
    assert result['status'] == 'CONFLICT'
    assert backend.get(original['id'])['status'] == 'VERIFIED'
    assert other['id'] in result['conflicts_with']


def test_stale_expired_invalidated_and_permissions_are_filtered():
    memory, backend = setup()
    saved = stage(memory)
    promote(memory)
    item = backend.get(saved['id'])
    item['verified_at'] = (datetime.now(timezone.utc) - timedelta(days=32)).isoformat()
    backend.save(item)
    assert search(memory) == []
    item['verified_at'] = datetime.now(timezone.utc).isoformat()
    item['valid_until'] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    backend.save(item)
    assert search(memory) == []
    item['valid_until'] = ''
    backend.save(item)
    assert len(search(memory)) == 1
    updated = memory.set_validity(item['id'], actor='reviewer', permission=PERMS,
                                  status='RECHECK_REQUIRED', reason='Source requires explicit re-evaluation')
    assert updated['status'] == 'RECHECK_REQUIRED' and search(memory) == []


def test_supervisor_checkpoints_completed_tasks_and_resumes_only_remaining():
    memory, backend = setup()
    provider = ScriptedProvider()
    supervisor = Supervisor(provider=provider, tools=ToolRegistry(graph), store=Store(),
                            tenant='asteria', permissions=PERMS, memory=memory)
    opts = SupervisorSettings(goal='Investigate incident dependency and historical evidence',
                              source_entity_id=INCIDENT, allow_external_model=True)
    completed = supervisor.run(opts, subject='reviewer')
    assert completed.status == 'COMPLETED'
    assert backend.checkpoints[('reviewer', completed.id)]['status'] == 'COMPLETED'
    checkpoint = backend.checkpoints[('reviewer', completed.id)]
    # Simulate abrupt termination after task 1, before the remaining tasks complete.
    checkpoint['status'] = 'RUNNING'
    for index, task in enumerate(checkpoint['tasks']):
        if index:
            task['status'] = 'RUNNING' if index == 1 else 'PENDING'
            task['result'] = None
    backend.checkpoints[('reviewer', completed.id)] = checkpoint
    resumed_provider = ScriptedProvider()
    restarted = Supervisor(provider=resumed_provider, tools=ToolRegistry(graph), store=Store(),
                           tenant='asteria', permissions=PERMS, memory=AgentMemory(backend=backend,
                           snapshot_factory=graph, tenant='asteria'))
    resumed = restarted.run(opts, subject='reviewer', resume_id=completed.id)
    assert resumed.status == 'COMPLETED'
    assert resumed.id == completed.id
    assert resumed_provider.calls['analyze_dependencies'] == 0
    assert resumed_provider.calls['retrieve_evidence'] > 0
    assert any(e['kind'] == 'RESUMED' for e in resumed.events)
    with pytest.raises(ValueError, match='Checkpoint not found'):
        restarted.run(opts, subject='other-user', resume_id=completed.id)


def test_completed_run_cannot_be_resumed():
    memory, backend = setup()
    sup = Supervisor(provider=ScriptedProvider(), tools=ToolRegistry(graph), store=Store(),
                     tenant='asteria', permissions=PERMS, memory=memory)
    opts = SupervisorSettings(goal='Investigate source outage and dependencies',
                              source_entity_id=INCIDENT, allow_external_model=True)
    result = sup.run(opts, subject='reviewer')
    with pytest.raises(ValueError, match='Only interrupted'):
        sup.run(opts, subject='reviewer', resume_id=result.id)


def test_api_memory_search_and_review_are_permission_scoped(monkeypatch):
    from backend.app.main import app
    from backend.app.api_v1 import router as routes
    memory, _ = setup()
    saved = stage(memory)
    promote(memory)
    monkeypatch.setattr(routes, '_memory_service', lambda principal: AgentMemory(
        backend=memory.backend, snapshot_factory=graph, tenant=principal.tenant_id))
    client = TestClient(app)
    headers = {'Authorization': 'Bearer test-asteria-admin-token', 'X-Tenant-ID': 'asteria'}
    res = client.post('/api/v1/agent-runtime/memory/search', headers=headers,
                      json={'entity_ids': [ROUTE], 'query': 'database'})
    assert res.status_code == 200, res.text
    assert len(res.json()['items']) == 1
    denied = client.post('/api/v1/agent-runtime/memory/search', headers={'Authorization': 'Bearer test-reader-token'},
                         json={'entity_ids': [ROUTE]})
    assert denied.status_code == 200 and denied.json()['items'] == []
    update = client.post(f'/api/v1/agent-runtime/memory/{saved["id"]}/validity', headers=headers,
                         json={'status': 'INVALIDATED', 'reason': 'Graph relation was officially withdrawn'})
    assert update.status_code == 200
    assert client.post('/api/v1/agent-runtime/memory/search', headers=headers,
                       json={'entity_ids': [ROUTE]}).json()['items'] == []

class DependencyMemoryProvider(ScriptedProvider):
    """Exercise production supervisor staging, verifier promotion and retrieval."""
    def __init__(self):
        super().__init__()
        self.memory_injected = []
        self.dependency_read_calls = 0

    def complete(self, messages, tools, **kwargs):
        if not tools:
            return super().complete(messages, tools, **kwargs)
        context = json.loads(messages[1]['content'])
        task_id = context['task_id']
        self.memory_injected.append((task_id, context.get('verified_prior_memory', [])))
        if task_id == 'analyze_dependencies':
            if context.get('verified_prior_memory'):
                # Validated prior relation is enough to avoid rerunning identical reads.
                return self._finding([ROUTE, DB], [{'subject_id': ROUTE, 'predicate': 'depends_on', 'value': DB}])
            history = [msg.get('name') for msg in messages if msg['role'] == 'tool']
            if 'get_entity' not in history:
                self.dependency_read_calls += 1
                from backend.app.agent_runtime.provider import Completion
                return Completion('', [{'id': 'route_lookup', 'name': 'get_entity',
                                        'arguments': json.dumps({'entity_id': ROUTE})}], 30)
            if 'graph_neighbors' not in history:
                self.dependency_read_calls += 1
                from backend.app.agent_runtime.provider import Completion
                return Completion('', [{'id': 'route_edges', 'name': 'graph_neighbors',
                                        'arguments': json.dumps({'entity_id': ROUTE})}], 30)
            return self._finding([ROUTE, DB], [{'subject_id': ROUTE, 'predicate': 'depends_on', 'value': DB}])
        if task_id == 'verify_findings':
            return self._finding([ROUTE, DB], [{'subject_id': ROUTE, 'predicate': 'depends_on', 'value': DB}])
        return super().complete(messages, tools, **kwargs)

    @staticmethod
    def _finding(citations, assertions):
        from backend.app.agent_runtime.provider import Completion
        return Completion(json.dumps({'summary': 'The current graph verifies dispatch depends on its database.',
            'citations': citations, 'knowledge_gaps': [], 'confidence': 'supported',
            'risk': 'low', 'requires_human_review': False, 'conflicts_with': [],
            'assertions': assertions}), [], 50)


def test_actual_supervisor_consolidates_and_later_agent_skips_duplicate_reads():
    memory, backend = setup()
    opts = SupervisorSettings(goal='Investigate dispatch outages and database dependencies',
                              source_entity_id=INCIDENT, allow_external_model=True)
    provider_a = DependencyMemoryProvider()
    a = Supervisor(provider=provider_a, tools=ToolRegistry(graph), store=Store(),
                   tenant='asteria', permissions=PERMS, memory=memory)
    first = a.run(opts, subject='reviewer')
    assert first.status == 'COMPLETED', first.error
    assert provider_a.dependency_read_calls == 2
    retrieved = search(memory)
    assert len(retrieved) == 1
    assert retrieved[0]['subject_id'] == ROUTE and retrieved[0]['value'] == DB
    assert retrieved[0]['verified_by'] in {'policy_verifier', 'independent_verifier'}
    assert set(retrieved[0]['source_tools']) == {'get_entity', 'graph_neighbors'}
    # A new model/supervisor instance sees the memory in a different execution.
    provider_b = DependencyMemoryProvider()
    b = Supervisor(provider=provider_b, tools=ToolRegistry(graph), store=Store(),
                   tenant='asteria', permissions=PERMS, memory=AgentMemory(backend=backend,
                   snapshot_factory=graph, tenant='asteria'))
    second = b.run(opts, subject='second_investigator')
    assert second.status == 'COMPLETED', second.error
    assert provider_b.dependency_read_calls == 0  # complete contextual recall
    assert any(e['kind'] == 'MEMORY_RETRIEVED' for e in second.events)
    assert any(task == 'analyze_dependencies' and memories for task, memories in provider_b.memory_injected)


def test_memory_backend_uses_separate_graph_and_tenant_filtered_queries():
    from backend.app.agent_runtime.memory_store import GraphMemoryStore
    from types import SimpleNamespace

    class Graph:
        def __init__(self):
            self.calls = []
        def query(self, q, params):
            self.calls.append((q, params))
            return SimpleNamespace(result_set=[['ok']])
        def ro_query(self, q, params):
            self.calls.append((q, params))
            return SimpleNamespace(result_set=[])

    g = Graph()
    class DB:
        def select_graph(self, name):
            assert name == 'company_brain_agent_memory'
            return g
    client = SimpleNamespace(db=DB(), settings=SimpleNamespace(tenant_id='asteria',
                                                               falkordb_graph='company_brain'))
    backend = GraphMemoryStore(client)
    backend.candidates([ROUTE], '', 10)
    backend.private_for_run('run1', ['research'])
    backend.load_checkpoint('SRUN-X', owner='alice')
    backend.checkpoint('SRUN-X', owner='alice', payload={'updated_at': 'today'}, revision=1)
    assert len(g.calls) == 4
    assert all(params['tenant'] == 'asteria' for _, params in g.calls)
    assert all('AgentWorkflowCheckpoint' in sql or 'AgentKnowledge' in sql for sql, _ in g.calls)


def test_live_graph_edge_withdrawal_prevents_stale_claim_reuse():
    from backend.app.services.phase4_graph import GraphSnapshot, GraphEdge
    memory, backend = setup()
    stage(memory)
    promote(memory)
    changed = GraphSnapshot(graph().nodes, [GraphEdge(ROUTE, 'DEPENDS_ON', DB,
                                    {'valid_until': '2026-01-01T00:00:00+00:00'})])
    refreshed = AgentMemory(backend=backend, snapshot_factory=lambda: changed, tenant='asteria')
    assert search(refreshed) == []


def test_private_branch_owner_can_see_only_exact_task_and_agent():
    memory, _ = setup()
    stage(memory)
    allowed = memory.retrieve(requester='reviewer', agent_id='dependency_analyst', permissions=PERMS,
                   search=MemorySearch(entity_ids=[ROUTE]), run_id='run1', branch_id='run1:research:agent1')
    assert len(allowed) == 1 and allowed[0]['status'] == 'DRAFT'
    assert memory.retrieve(requester='reviewer', agent_id='dependency_analyst', permissions=PERMS,
                   search=MemorySearch(entity_ids=[ROUTE]), run_id='unrelated_run', branch_id='run1:research:agent1') == []
