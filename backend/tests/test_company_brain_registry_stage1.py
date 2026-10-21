"""Pure/offline tests: no running FalkorDB, Groq, or graph mutations."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.graph.registry import GraphRegistry, GraphNotRegistered, InvalidGraphRegistration
from backend.app.graph import registry_api
from backend.app.main import app


class DummyGraph:
    def __init__(self, tenant_records):
        self.tenants = tenant_records

    def ro_query(self, query, params):
        assert "MATCH (n {tenant_id:$tenant})" in query
        return type("Result", (), {"result_set": [["ONE"]] if params["tenant"] in self.tenants else []})()


class DummyDB:
    def __init__(self, names, bindings):
        self.names = names
        self.bindings = bindings

    def list_graphs(self):
        return self.names

    def select_graph(self, graph_id):
        assert graph_id in self.names
        return DummyGraph(self.bindings.get(graph_id, set()))


class DummyClient:
    def __init__(self, names, bindings=None):
        self.db = DummyDB(names, bindings or {})


@pytest.fixture
def catalog(tmp_path):
    graphs = ["company_brain", "asteria_company_brain_v1", "phase13_accept_123", "verinex_neon_stage3_foo"]
    client = DummyClient(graphs, {
        "company_brain": {"northstar", "asteria"},
        "asteria_company_brain_v1": {"asteria"},
    })
    return GraphRegistry(tmp_path / "registry.sqlite3"), client


def test_registration_requires_real_existing_tenant_graph(catalog):
    registry, client = catalog
    with pytest.raises(InvalidGraphRegistration, match="does not exist"):
        registry.register_existing(graph_id="fake_graph", tenant_id="asteria", display_name="Fake", client=client)
    with pytest.raises(InvalidGraphRegistration, match="no records"):
        registry.register_existing(graph_id="asteria_company_brain_v1", tenant_id="northstar", display_name="Wrong tenant", client=client)
    assert registry.list_for_tenant(tenant_id="northstar", client=client)["items"] == []


@pytest.mark.parametrize("name", ["verinex_neon_stage3_foo", "phase13_accept_123", "company_brain_agent_memory", "../../path", "company_brain_test_123"])
def test_registration_rejects_nonproduction_graph_names(catalog, name):
    registry, client = catalog
    with pytest.raises(InvalidGraphRegistration):
        registry.register_existing(graph_id=name, tenant_id="asteria", display_name="Bad", client=client)


def test_registry_only_lists_explicit_tenant_bindings(catalog):
    registry, client = catalog
    registry.register_existing(graph_id="asteria_company_brain_v1", tenant_id="asteria", display_name="Asteria", client=client)
    registry.register_existing(graph_id="company_brain", tenant_id="northstar", display_name="Main", client=client)
    assert [x["graph_id"] for x in registry.list_for_tenant(tenant_id="asteria", client=client)["items"]] == ["asteria_company_brain_v1"]
    assert [x["graph_id"] for x in registry.list_for_tenant(tenant_id="northstar", client=client)["items"]] == ["company_brain"]
    with pytest.raises(GraphNotRegistered):
        registry.resolve(tenant_id="northstar", graph_id="asteria_company_brain_v1")


def test_registry_persists_across_instances_and_upserts_label(catalog):
    registry, client = catalog
    registry.register_existing(graph_id="asteria_company_brain_v1", tenant_id="asteria", display_name="Asteria old", client=client)
    registry.register_existing(graph_id="asteria_company_brain_v1", tenant_id="asteria", display_name="Asteria new", client=client)
    reopened = GraphRegistry(registry.path)
    assert reopened.resolve(graph_id="asteria_company_brain_v1", tenant_id="asteria")["display_name"] == "Asteria new"
    assert len(reopened.list_for_tenant(tenant_id="asteria", client=client)["items"]) == 1


def test_unavailable_graph_is_not_mistaken_for_an_accessible_database(catalog):
    registry, client = catalog
    registry.register_existing(graph_id="asteria_company_brain_v1", tenant_id="asteria", display_name="Asteria", client=client)
    missing = DummyClient(["company_brain"])
    item = registry.list_for_tenant(tenant_id="asteria", client=missing)["items"][0]
    assert item["available"] is False
    with pytest.raises(GraphNotRegistered):
        registry.client_for_graph(tenant_id="asteria", graph_id="asteria_company_brain_v1", catalog_client=missing)


def test_client_for_graph_rejects_unregistered_before_connecting(catalog):
    registry, client = catalog
    with pytest.raises(GraphNotRegistered):
        registry.client_for_graph(tenant_id="asteria", graph_id="company_brain", catalog_client=client)


def test_api_respects_tenant_binding_and_never_lists_raw_db_graphs(catalog, monkeypatch):
    registry, client = catalog
    registry.register_existing(graph_id="asteria_company_brain_v1", tenant_id="asteria", display_name="Asteria", client=client)
    registry.register_existing(graph_id="company_brain", tenant_id="northstar", display_name="Main", client=client)

    # No live connection. Both endpoints use exactly the same per-tenant policy.
    class FakeAPIRegistry(GraphRegistry):
        def __init__(self):
            super().__init__(registry.path)

        def _available_names(self, unused):
            return set(client.db.list_graphs())

    monkeypatch.setattr(registry_api, "GraphRegistry", FakeAPIRegistry)
    monkeypatch.setattr("backend.app.graph.registry.FalkorGraphClient", lambda *args, **kwargs: client)
    api = TestClient(app)
    assert api.get("/api/v1/graphs").status_code == 401
    assert api.get("/api/v1/graphs", headers={"Authorization": "Bearer test-reader-token"}).json()["items"][0]["graph_id"] == "company_brain"
    r = api.get("/api/v1/graphs", headers={"Authorization": "Bearer test-asteria-admin-token", "X-Tenant-ID": "asteria"})
    assert r.status_code == 200, r.text
    assert [x["graph_id"] for x in r.json()["items"]] == ["asteria_company_brain_v1"]
    assert api.get("/api/v1/graphs/asteria_company_brain_v1", headers={"Authorization": "Bearer test-reader-token"}).status_code == 404
    assert api.get("/api/v1/graphs/verinex_neon_stage3_foo", headers={"Authorization": "Bearer test-asteria-admin-token"}).status_code == 404
    assert api.get("/api/v1/graphs/asteria_company_brain_v1", headers={"Authorization": "Bearer test-asteria-admin-token"}).status_code == 200
    assert api.get("/api/v1/graphs", headers={"Authorization": "Bearer test-asteria-admin-token", "X-Tenant-ID": "northstar"}).status_code == 403
