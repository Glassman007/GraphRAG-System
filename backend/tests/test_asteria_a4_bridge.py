"""A4 offline graph-contract tests; not a substitute for live FalkorDB integration."""
from types import SimpleNamespace

import pytest

from backend.app.agent_runtime.asteria_coordination_bridge import AsteriaCoordinationBridge, ROLE
from backend.app.agent_runtime.supervisor import TaskState
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.tests.test_coordination_handoff_context import MemoryGraphClient

INC = 'INC-AST-ROUTE-OUTAGE'
EVD = 'EVD-AST-0003'
RUN = 'SRUN-' + 'A' * 32


def scenario():
    db = MemoryGraphClient()
    db.settings.tenant_id = 'asteria'
    db.settings.falkordb_graph = 'asteria_company_brain_v1'
    upsert_node(db, 'Incident', INC, {'name': 'Asteria route incident'})
    upsert_node(db, 'Evidence', EVD, {'name': 'Asteria schema evidence', 'source_ref_id': 'ASTERIA-LOG'})
    tasks = {
        'retrieve_evidence': TaskState(id='retrieve_evidence', objective='Retrieve independently cited incident evidence',
            capability='evidence_retrieval', depends_on=[], agent_id='evidence_retriever'),
        'verify_findings': TaskState(id='verify_findings', objective='Verify cited incident evidence identities',
            capability='verification', depends_on=['retrieve_evidence'], agent_id='independent_verifier'),
    }
    bridge = AsteriaCoordinationBridge(db, RUN, INC, tasks)
    bridge.prepare()
    # The fake Cypher adapter does not implement CoordinationService.claim_task's
    # conditional query. Create only the ownership relationship as its precondition.
    upsert_relationship(db, bridge.task_ids['retrieve_evidence'], 'CLAIMED_BY',
                        ROLE['evidence_retrieval'][0], {'valid_from': '2026-10-22T00:00:00Z'})
    tasks['retrieve_evidence'].result = {
        'summary': 'Recorded Asteria evidence linked to route orchestration incident.',
        'citations': [INC, EVD], 'knowledge_gaps': ['A full causal chain is not proven.'],
        'confidence': 'uncertain', 'assertions': [], 'conflicts_with': [],
        'risk': 'low', 'requires_human_review': True,
    }
    return bridge, db, tasks


def test_formally_accepted_persisted_finding_is_consumed_by_downstream_task():
    bridge, db, tasks = scenario()
    ids = bridge.publish(tasks['retrieve_evidence'], ['verify_findings'])
    assert len(ids) == 1
    board = bridge.coordination.get_task_blackboard(bridge.task_ids['verify_findings'])
    assert len(board['accepted_handoff_context']) == 1
    assert board['accepted_handoff_context'][0]['handoff']['status'] == 'ACCEPTED'
    persisted = bridge.consume('retrieve_evidence', 'verify_findings')
    assert persisted['handoff_id'] == ids[0]
    assert persisted['result'] == tasks['retrieve_evidence'].result
    assert any(x.startswith('FIND-P6-') for x in persisted['artifact_ids'])
    assert EVD in persisted['artifact_ids']
    assert len(bridge.publish(tasks['retrieve_evidence'], ['verify_findings'])) == 1  # retry idempotence
    assert len(bridge.coordination.get_task_blackboard(bridge.task_ids['verify_findings'])['accepted_handoff_context']) == 1


def test_rejected_or_missing_persisted_handoff_blocks_downstream_consumption():
    bridge, db, tasks = scenario()
    with pytest.raises(ValueError, match='NOT_ACCEPTED'):
        bridge.consume('retrieve_evidence', 'verify_findings')
    # Real service creates PENDING; blackboard must not treat it as accepted.
    result = bridge.coordination.add_finding(bridge.task_ids['retrieve_evidence'], ROLE['evidence_retrieval'][0],
        statement='A persisted but unaccepted finding', confidence=0.7, evidence_ids=[EVD])
    bridge.handoffs.create_handoff(bridge.task_ids['retrieve_evidence'], ROLE['evidence_retrieval'][0],
        ROLE['verification'][0], artifact_ids=[result['finding']['id'], EVD],
        destination_task_id=bridge.task_ids['verify_findings'])
    with pytest.raises(ValueError, match='NOT_ACCEPTED'):
        bridge.consume('retrieve_evidence', 'verify_findings')


def test_tampered_finding_fails_digest_validation():
    bridge, db, tasks = scenario()
    bridge.publish(tasks['retrieve_evidence'], ['verify_findings'])
    board = bridge.coordination.get_task_blackboard(bridge.task_ids['verify_findings'])
    finding = next(a for a in board['accepted_handoff_context'][0]['artifacts'] if 'Finding' in a['_labels'])
    upsert_node(db, 'Finding', finding['id'], {'supervisor_digest': 'bad'})
    with pytest.raises(ValueError, match='DIGEST_MISMATCH'):
        bridge.consume('retrieve_evidence', 'verify_findings')


def test_a4_bridge_denies_wrong_graph_or_tenant():
    bridge, db, tasks = scenario()
    db.settings.falkordb_graph = 'not-asteria'
    with pytest.raises(PermissionError):
        AsteriaCoordinationBridge(db, RUN, INC, tasks)
    db.settings.falkordb_graph = 'asteria_company_brain_v1'
    db.settings.tenant_id = 'another'
    with pytest.raises(PermissionError):
        AsteriaCoordinationBridge(db, RUN, INC, tasks)


def test_supervisor_opt_in_consumes_persisted_handoff_before_verification(monkeypatch):
    from backend.app.agent_runtime import asteria_coordination_bridge as bridge_module
    from backend.app.agent_runtime.supervisor import Supervisor, SupervisorSettings
    from backend.app.agent_runtime.tools import ToolRegistry
    from backend.tests.test_agent_runtime_evidence_grounding import asteria_fixture_graph
    from backend.tests.test_asteria_a3_specialist_dispatch import DeniedProvider, GOAL
    from backend.tests.test_supervisor_component2 import Store

    calls = []

    class FakeBridge:
        def __init__(self, client, run_id, source, states):
            assert source == INC
            self.states = states
        def prepare(self):
            calls.append(('prepare',))
        def begin(self, state):
            calls.append(('begin', state.id))
        def publish(self, state, dependents):
            calls.append(('publish', state.id, tuple(dependents)))
            return [f'HANDOFF:{state.id}:{name}' for name in dependents]
        def consume(self, from_name, to_name):
            calls.append(('consume', from_name, to_name))
            return {'task_id': from_name, 'agent_id': 'persisted-role',
                    'result': self.states[from_name].result,
                    'handoff_id': f'HANDOFF:{from_name}:{to_name}',
                    'artifact_ids': ['FIND-ASTERIA-TEST']}

    monkeypatch.setattr(bridge_module, 'AsteriaCoordinationBridge', FakeBridge)
    monkeypatch.setenv('VERINEX_A4_HANDOFFS', '1')
    store = Store()
    store.client = SimpleNamespace(settings=SimpleNamespace(tenant_id='asteria', falkordb_graph='asteria_company_brain_v1'))
    provider = DeniedProvider()
    run = Supervisor(provider=provider, tools=ToolRegistry(asteria_fixture_graph),
        store=store, tenant='asteria', permissions=frozenset({'READ_GRAPH', 'READ_EVIDENCE'})).run(
        SupervisorSettings(goal=GOAL, source_entity_id=INC, allow_external_model=True, max_parallel=2),
        subject='a4-offline')
    assert all(t['status'] == 'COMPLETED' for t in run.tasks)
    assert run.answer and provider.attempts == 0
    assert ('consume', 'retrieve_evidence', 'verify_findings') in calls
    assert ('consume', 'analyze_dependencies', 'verify_findings') in calls
    assert ('consume', 'verify_findings', 'propose_remediation') in calls
    assert sum(x[0] == 'publish' for x in calls) == 4
    assert len([event for event in store.events if event['kind'] == 'HANDOFF_CONSUMED']) == 3


def test_supervisor_bridge_rejects_missing_accepted_handoff(monkeypatch):
    from backend.app.agent_runtime import asteria_coordination_bridge as bridge_module
    from backend.app.agent_runtime.supervisor import Supervisor, SupervisorSettings
    from backend.app.agent_runtime.tools import ToolRegistry
    from backend.tests.test_agent_runtime_evidence_grounding import asteria_fixture_graph
    from backend.tests.test_asteria_a3_specialist_dispatch import DeniedProvider, GOAL
    from backend.tests.test_supervisor_component2 import Store

    class RejectBridge:
        def __init__(self, client, run_id, source, states):
            pass
        def prepare(self):
            pass
        def begin(self, state):
            pass
        def publish(self, state, dependents):
            return []
        def consume(self, from_name, to_name):
            raise ValueError('BRIDGE_HANDOFF_NOT_ACCEPTED')

    monkeypatch.setattr(bridge_module, 'AsteriaCoordinationBridge', RejectBridge)
    monkeypatch.setenv('VERINEX_A4_HANDOFFS', '1')
    store = Store()
    store.client = SimpleNamespace(settings=SimpleNamespace(tenant_id='asteria', falkordb_graph='asteria_company_brain_v1'))
    run = Supervisor(provider=DeniedProvider(), tools=ToolRegistry(asteria_fixture_graph),
        store=store, tenant='asteria', permissions=frozenset({'READ_GRAPH', 'READ_EVIDENCE'})).run(
        SupervisorSettings(goal=GOAL, source_entity_id=INC, allow_external_model=True, max_parallel=2, max_retries=0),
        subject='a4-offline')
    statuses = {t['id']:t['status'] for t in run.tasks}
    assert statuses['analyze_dependencies'] == 'COMPLETED'
    assert statuses['retrieve_evidence'] == 'COMPLETED'
    assert statuses['verify_findings'] == 'FAILED'
    assert statuses['propose_remediation'] == 'BLOCKED'
    assert not run.answer
