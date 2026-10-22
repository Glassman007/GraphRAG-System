"""A2: Asteria target selection and typed planning must fail closed before model/tool execution."""
import pytest

from backend.app.agent_runtime.supervisor import (
    Supervisor, SupervisorSettings, TargetResolutionError, _resolve_target,
)
from backend.app.agent_runtime.tools import ToolRegistry
from backend.app.services.phase4_graph import GraphSnapshot, GraphEdge
from backend.tests.test_supervisor_component2 import graph as existing_graph, Store

INCIDENT = 'INC-AST-ROUTE-OUTAGE'
OBJECTIVE = ('Investigate the route orchestration outage and produce an evidence-backed, '
             'read-only remediation proposal. Separate observed facts from hypotheses; '
             'cite real Asteria evidence and identify any missing proof. Do not execute changes.')


class NoProvider:
    name = 'a2-offline'
    model = 'disabled'
    def __init__(self):
        self.calls = 0
    def complete(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError('Target resolution must not call a model')


def make(snapshot=None):
    snap = snapshot or existing_graph()
    provider = NoProvider()
    store = Store()
    runtime = Supervisor(provider=provider, tools=ToolRegistry(lambda: snap), store=store,
                         tenant='asteria', permissions=frozenset({'READ_GRAPH', 'READ_EVIDENCE'}))
    return runtime, provider, store


def options(**kwargs):
    return SupervisorSettings(goal=OBJECTIVE, allow_external_model=True, **kwargs)


def test_explicit_known_incident_is_prevalidated_without_model_call():
    runtime, provider, store = make()
    report = runtime.run(options(source_entity_id=INCIDENT), subject='a2', control_check=lambda: 'PAUSE')
    assert report.status == 'PAUSED'
    assert len(report.tasks) == 4
    assert all(t['status'] == 'PENDING' for t in report.tasks)
    assert store.run['source_entity_id'] == INCIDENT
    assert store.run['source_resolution_method'] == 'EXPLICIT_ENTITY'
    assert 'prevalidated incident' in store.run['plan_rationale']
    assert provider.calls == 0


def test_descriptive_objective_resolves_unique_incident_before_planning():
    # Unlike the older fake graph, this uses actual fixture-matching Incident title.
    snap = GraphSnapshot({
        INCIDENT: {'id': INCIDENT, 'name': 'Route planning failures after schema deployment', '_labels': ['Entity', 'Incident']},
        'INC-AST-FORECAST-BIAS': {'id': 'INC-AST-FORECAST-BIAS', 'name': 'Demand forecast drifts after routing outage', '_labels': ['Entity','Incident']},
    }, [])
    runtime, provider, store = make(snap)
    report = runtime.run(options(), subject='a2', control_check=lambda: 'PAUSE')
    assert report.status == 'PAUSED'
    assert store.run['source_entity_id'] == INCIDENT
    assert store.run['source_resolution_method'] == 'UNIQUE_GRAPH_INCIDENT_MATCH'
    assert len(report.tasks) == 4
    assert provider.calls == 0


def test_incident_with_existing_evidence_target_rejected_before_any_run():
    runtime, provider, store = make()
    with pytest.raises(TargetResolutionError, match='TARGET_KIND_MISMATCH'):
        runtime.run(options(source_entity_id='EVD-AST-001'), subject='a2')
    assert store.run is None and provider.calls == 0


def test_unknown_explicit_and_embedded_ids_are_rejected():
    runtime, provider, store = make()
    with pytest.raises(TargetResolutionError, match='TARGET_NOT_FOUND'):
        runtime.run(options(source_entity_id='INC-AST-NOT-FOUND'), subject='a2')
    with pytest.raises(TargetResolutionError, match='TARGET_NOT_FOUND'):
        runtime.run(SupervisorSettings(goal='Investigate INC-AST-NOT-FOUND and its incident evidence',
                                       allow_external_model=True), subject='a2')
    assert store.run is None and provider.calls == 0


def test_ambiguous_incident_matches_do_not_guess_or_call_model():
    snap = GraphSnapshot({
        INCIDENT: {'id': INCIDENT, '_labels': ['Entity', 'Incident']},
        'INC-AST-ROUTE-RETRY': {'id': 'INC-AST-ROUTE-RETRY', '_labels': ['Entity', 'Incident']},
    }, [])
    runtime, provider, store = make(snap)
    with pytest.raises(TargetResolutionError, match='TARGET_AMBIGUOUS'):
        runtime.run(SupervisorSettings(goal='Investigate route outage and route retry incidents',
                                       allow_external_model=True), subject='a2')
    assert store.run is None and provider.calls == 0


def test_nonunique_underspecified_incident_requires_input():
    runtime, provider, store = make()
    with pytest.raises(TargetResolutionError, match='TARGET_NEEDS_INPUT'):
        runtime.run(SupervisorSettings(goal='Investigate the incident and cite supporting evidence',
                                       allow_external_model=True), subject='a2')
    assert store.run is None and provider.calls == 0


def test_exact_title_match_is_accepted_and_multiple_ids_rejected():
    snap = GraphSnapshot({INCIDENT: {
        'id': INCIDENT, 'name': 'Route planning failures after schema deployment',
        '_labels': ['Incident','Entity']},
    }, [])
    assert _resolve_target(snap, 'Investigate the route planning failures after schema deployment incident', None)[0] == INCIDENT
    with pytest.raises(TargetResolutionError, match='TARGET_AMBIGUOUS'):
        _resolve_target(snap, 'Compare INC-AST-ROUTE-OUTAGE and INC-AST-FORECAST-BIAS incidents', None)


def test_incompatible_incident_dag_limit_fails_before_persistence():
    runtime, provider, store = make()
    with pytest.raises(ValueError, match='bounds'):
        runtime.run(options(source_entity_id=INCIDENT, max_tasks=2), subject='a2')
    assert store.run is None and provider.calls == 0


def test_authenticated_asteria_supervisor_api_resolves_plan_without_provider(monkeypatch):
    """HTTP boundary: real Supervisor planning, forced pause before worker dispatch."""
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.app.api_v1 import router as routes
    from backend.app.config import Settings

    snapshot = GraphSnapshot({
        INCIDENT: {'id': INCIDENT, '_labels': ['Entity', 'Incident']},
        'EVD-AST-0003': {'id': 'EVD-AST-0003', '_labels': ['Entity', 'Evidence']},
    }, [])
    provider = NoProvider()
    store = Store()

    class CheckpointSink:
        def checkpoint(self, *args, **kwargs):
            return None

    original = Supervisor.run

    def stop_after_planning(self, settings, **kwargs):
        kwargs['control_check'] = lambda: 'PAUSE'
        return original(self, settings, **kwargs)

    monkeypatch.setattr(routes, 'OpenAICompatibleProvider', lambda: provider)
    monkeypatch.setattr(routes, 'client_for', lambda principal: SimpleNamespace(settings=Settings(
        tenant_id='asteria', falkordb_graph='asteria_company_brain_v1')))
    monkeypatch.setattr(routes.GraphSnapshot, 'load', classmethod(lambda cls, client: snapshot))
    monkeypatch.setattr(routes, 'GraphSupervisorStore', lambda client: store)
    monkeypatch.setattr(routes, 'GraphMemoryStore', lambda client: CheckpointSink())
    monkeypatch.setattr(Supervisor, 'run', stop_after_planning)

    api = TestClient(app)
    headers = {'Authorization': 'Bearer test-asteria-admin-token', 'X-Tenant-ID': 'asteria'}
    route = '/api/v1/agent-runtime/supervisor/runs'
    response = api.post(route, headers=headers, json={'goal': OBJECTIVE, 'allow_external_model': True})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'PAUSED'
    assert len(response.json()['tasks']) == 4
    assert store.run['source_entity_id'] == INCIDENT
    assert store.run['source_resolution_method'] == 'UNIQUE_GRAPH_INCIDENT_MATCH'
    assert provider.calls == 0

    rejected = api.post(route, headers=headers, json={'goal': OBJECTIVE,
        'source_entity_id': 'EVD-AST-0003', 'allow_external_model': True})
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()['error']['code'] == 'AGENT_INPUT_INVALID'
    assert 'TARGET_KIND_MISMATCH' in rejected.text
    assert provider.calls == 0
