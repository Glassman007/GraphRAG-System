"""Homepage graph preview must use recorded scoped graph facts, never fixture placeholders."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.graph_preview_service import make_graph_preview
from backend.app.services.phase4_graph import GraphEdge, GraphSnapshot


def test_preview_uses_real_active_edges_and_canonical_node_labels():
    snapshot = GraphSnapshot(
        {
            'INC-AST-ROUTE-OUTAGE': {'id': 'INC-AST-ROUTE-OUTAGE', 'name': 'Route outage', '_labels': ['Entity', 'Incident'], 'status': 'OPEN', 'access_token': 'MUST_NOT_APPEAR'},
            'SYS-AST-ROUTING': {'id': 'SYS-AST-ROUTING', 'name': 'Route system', '_labels': ['Entity', 'System']},
            'SYS-RETIRED': {'id': 'SYS-RETIRED', 'name': 'Old service', 'valid_until': '2025-01-01', '_labels': ['Entity', 'System']},
        },
        [GraphEdge('INC-AST-ROUTE-OUTAGE', 'AFFECTS', 'SYS-AST-ROUTING', {'edge_id': 'EDGE-1'}),
         GraphEdge('SYS-AST-ROUTING', 'DEPENDS_ON', 'SYS-RETIRED', {}),
         GraphEdge('INC-AST-ROUTE-OUTAGE', 'RESOLVED', 'SYS-AST-ROUTING', {'valid_until': '2025-01-01'})],
    )
    result = make_graph_preview(snapshot)
    assert result['total_nodes'] == 2
    assert result['total_edges'] == 1
    assert {node['id'] for node in result['nodes']} == {'INC-AST-ROUTE-OUTAGE', 'SYS-AST-ROUTING'}
    assert result['edges'] == [{'source': 'INC-AST-ROUTE-OUTAGE', 'target': 'SYS-AST-ROUTING', 'type': 'AFFECTS', 'properties': {'edge_id': 'EDGE-1'}}]
    assert 'access_token' not in result['nodes'][0]
    assert result['sampled'] is False


def test_preview_works_without_any_incident_nodes():
    snapshot = GraphSnapshot(
        {'A': {'id': 'A', '_labels': ['Entity', 'SqlTable']}, 'B': {'id': 'B', '_labels': ['Entity', 'SqlTable']}},
        [GraphEdge('A', 'FOREIGN_KEY_TO', 'B', {})],
    )
    result = make_graph_preview(snapshot)
    assert len(result['nodes']) == 2 and len(result['edges']) == 1


def test_preview_limits_graph_size_without_fake_connections():
    nodes = {f'SYS-{n}': {'id': f'SYS-{n}', '_labels': ['Entity', 'System']} for n in range(70)}
    edges = [GraphEdge('SYS-0', 'CONNECTS_TO', f'SYS-{n}', {}) for n in range(1, 70)]
    result = make_graph_preview(GraphSnapshot(nodes, edges), max_nodes=12, max_edges=6)
    ids = {node['id'] for node in result['nodes']}
    assert len(ids) == 12 and len(result['edges']) == 6 and result['sampled'] is True
    assert all(edge['source'] in ids and edge['target'] in ids for edge in result['edges'])
    assert all(edge['type'] == 'CONNECTS_TO' for edge in result['edges'])


def test_preview_denies_missing_graph_selection_before_database_access():
    response = TestClient(app).get('/api/v1/graph/preview', headers={
        'Authorization': 'Bearer test-reader-token', 'X-Tenant-ID': 'northstar',
    })
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'GRAPH_SCOPE_REQUIRED'


def test_preview_denies_unauthenticated_request():
    assert TestClient(app).get('/api/v1/graph/preview').status_code == 401


def test_preview_validates_bounds():
    with pytest.raises(ValueError):
        make_graph_preview(GraphSnapshot({}, []), max_nodes=101)


def test_scoped_api_preview_isolated_to_selected_registered_brain(monkeypatch):
    """An explicitly chosen graph, not the default graph, supplies all preview data."""
    from backend.app.graph.registry import GraphRegistry
    from backend.app.api_v1 import router as v1_router

    def resolve(self, *, tenant_id, graph_id):
        if tenant_id != 'northstar' or graph_id not in {'asteria_company_brain_v1', 'other_brain'}:
            from backend.app.graph.registry import GraphNotRegistered
            raise GraphNotRegistered(graph_id)
        return {'graph_id': graph_id}

    class FakeClient:
        def __init__(self, graph_id):
            self.graph_id = graph_id

    monkeypatch.setattr(GraphRegistry, 'resolve', resolve)
    monkeypatch.setattr(v1_router, 'client_for', lambda principal: FakeClient(principal.graph_id))
    monkeypatch.setattr(GraphSnapshot, 'load', classmethod(lambda cls, client: GraphSnapshot(
        {f'{client.graph_id}-NODE': {'id': f'{client.graph_id}-NODE', 'name': 'Verified scoped entity'}}, [],
    )))
    api = TestClient(app)
    asteria = api.get('/api/v1/graph/preview', headers={
        'Authorization': 'Bearer test-reader-token', 'X-Tenant-ID': 'northstar',
        'X-Company-Brain-ID': 'asteria_company_brain_v1',
    })
    other = api.get('/api/v1/graph/preview', headers={
        'Authorization': 'Bearer test-reader-token', 'X-Tenant-ID': 'northstar',
        'X-Company-Brain-ID': 'other_brain',
    })
    assert asteria.status_code == other.status_code == 200
    assert asteria.json()['graph_id'] == 'asteria_company_brain_v1'
    assert [node['id'] for node in asteria.json()['nodes']] == ['asteria_company_brain_v1-NODE']
    assert [node['id'] for node in other.json()['nodes']] == ['other_brain-NODE']
    assert api.get('/api/v1/graph/preview', headers={
        'Authorization': 'Bearer test-reader-token', 'X-Tenant-ID': 'northstar',
        'X-Company-Brain-ID': 'unregistered_brain',
    }).status_code == 404
