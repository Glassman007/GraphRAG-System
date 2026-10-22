"""Fast-track MVP: bounded Asteria incident evidence -> verifier -> proposal -> report."""
from collections import Counter

from backend.tests.test_asteria_a3_specialist_dispatch import setup, settings, INCIDENT, GOAL


def test_full_asteria_mvp_pipeline_without_provider_or_business_writes():
    supervisor, tools, provider, store = setup()
    report = supervisor.run(settings(), subject='asteria-mvp')
    states = {task['id']: task for task in report.tasks}
    assert report.status == 'NEEDS_REVIEW'  # Causation explicitly NOT proven.
    assert report.error is None
    assert all(state['status'] == 'COMPLETED' for state in states.values())
    assert len(states) == 4
    assert provider.attempts == 0
    assert report.tokens_used == 0
    assert 'READ-ONLY PROPOSAL' in report.answer
    assert 'NOT executed' in report.answer or 'nothing executed' in report.answer
    assert 'not causal proof' in report.answer.lower()
    assert INCIDENT in report.citations
    assert 'EVD-AST-0003' in report.citations
    assert all(tools.snapshot_factory().node(cid) for cid in report.citations)
    assert report.knowledge_gaps
    assert store.result['answer'] == report.answer
    assert store.result['status'] == report.status
    assert Counter(name for name, _ in tools.calls) == Counter({'incident_context': 3, 'dependency_impact': 1})
    assert any(ev['kind'] == 'MVP_PARENT_FINDINGS_CONSUMED' and ev['task_id'] == 'verify_findings' for ev in store.events)
    assert any(ev['kind'] == 'MVP_PARENT_FINDINGS_CONSUMED' and ev['task_id'] == 'propose_remediation' for ev in store.events)
    assert any(ev['kind'] == 'AGGREGATE' and 'provider_calls=0' in ev['summary'] for ev in store.events)
    assert not any(ev['kind'] == 'ERROR' for ev in store.events)


def test_mvp_does_not_fake_success_if_independent_read_fails():
    sup, tools, provider, store = setup(bad_tool='incident_context')
    report = sup.run(settings(), subject='asteria-mvp-negative')
    states = {task['id']: task for task in report.tasks}
    assert states['retrieve_evidence']['status'] == 'FAILED'
    assert states['verify_findings']['status'] == 'BLOCKED'
    assert states['propose_remediation']['status'] == 'BLOCKED'
    assert report.status != 'COMPLETED'
    assert not report.answer
    assert provider.attempts == 0


def test_mvp_report_refuses_nonexistent_citations():
    from backend.app.agent_runtime.supervisor import _mvp_incident_report, TaskState, SpecialistFinding
    from backend.tests.test_agent_runtime_evidence_grounding import asteria_fixture_graph
    import pytest
    def state(key, cites):
        finding = SpecialistFinding(summary='Validated bounded read-only facts', citations=cites, confidence='uncertain')
        return TaskState(id=key, objective='Recorded incident evidence review', capability='verification',
                         depends_on=[], status='COMPLETED', result=finding.model_dump())
    states = {key: state(key, [INCIDENT, 'EVD-AST-FAKE']) for key in
              ('analyze_dependencies', 'retrieve_evidence', 'verify_findings', 'propose_remediation')}
    with pytest.raises(ValueError, match='MVP_REPORT_MISSING_EVIDENCE'):
        _mvp_incident_report(INCIDENT, states, asteria_fixture_graph())


def test_independent_verifier_read_failure_blocks_proposal_and_aggregation():
    from backend.tests.test_asteria_a3_specialist_dispatch import TrackingTools, DeniedProvider
    from backend.tests.test_agent_runtime_evidence_grounding import asteria_fixture_graph
    from backend.tests.test_supervisor_component2 import Store
    from backend.app.agent_runtime.supervisor import Supervisor

    class FailVerifierRead(TrackingTools):
        def __init__(self, snapshot):
            super().__init__(snapshot)
            self.incident_reads = 0
        def execute(self, name, args):
            if name == 'incident_context':
                self.incident_reads += 1
                if self.incident_reads == 3:
                    self.calls.append((name, dict(args)))
                    return {'error': 'ENTITY_NOT_FOUND'}
            return super().execute(name, args)

    tools = FailVerifierRead(asteria_fixture_graph())
    provider, store = DeniedProvider(), Store()
    sup = Supervisor(provider=provider, tools=tools, store=store, tenant='asteria',
                     permissions=frozenset({'READ_GRAPH', 'READ_EVIDENCE'}))
    result = sup.run(settings(), subject='asteria-verifier-fails')
    state = {row['id']: row for row in result.tasks}
    assert state['analyze_dependencies']['status'] == 'COMPLETED'
    assert state['retrieve_evidence']['status'] == 'COMPLETED'
    assert state['verify_findings']['status'] == 'FAILED'
    assert state['propose_remediation']['status'] == 'BLOCKED'
    assert not result.answer
    assert provider.attempts == 0
    assert any(e['kind'] == 'SPECIALIST_TOOL' and e['status'] == 'FAILED' for e in store.events)


def test_verifier_rejects_fabricated_predecessor_id():
    import pytest
    from backend.app.agent_runtime.supervisor import _mvp_verification_finding, SpecialistFinding
    from backend.tests.test_agent_runtime_evidence_grounding import asteria_fixture_graph
    snapshot = asteria_fixture_graph()
    parents = []
    for key in ('analyze_dependencies', 'retrieve_evidence'):
        finding = SpecialistFinding(summary='Deterministically retrieved incident evidence',
                                    citations=[INCIDENT, 'EVD-AST-FAKE'], confidence='uncertain')
        parents.append({'task_id': key, 'result': finding.model_dump()})
    with pytest.raises(ValueError, match='MVP_VERIFIER_INVALID_CITATION'):
        _mvp_verification_finding(snapshot, INCIDENT, parents, {INCIDENT, 'EVD-AST-0003'})
