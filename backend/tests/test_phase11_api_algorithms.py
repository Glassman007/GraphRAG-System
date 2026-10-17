from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api_v1.application import decode_cursor, encode_cursor, node_visible, sanitize, stable_id
from backend.app.api_v1.security import _builtins

api = TestClient(app)

REQUIRED_PATHS = [
    "/api/v1/situations", "/api/v1/investigations", "/api/v1/entities/{entity_id}", "/api/v1/paths",
    "/api/v1/entities/{entity_id}/blast-radius", "/api/v1/claims", "/api/v1/evidence", "/api/v1/tasks",
    "/api/v1/agents", "/api/v1/decisions", "/api/v1/actions", "/api/v1/simulations/counterfactual",
    "/api/v1/history/entities/{entity_id}", "/api/v1/processes/{scope_id}", "/api/v1/risks", "/api/v1/retrieval/search",
]

@pytest.mark.parametrize("path", REQUIRED_PATHS)
def test_phase11_required_versioned_resource_paths_exist(path):
    assert path in {r.path for r in app.routes}

REQUIRED_TAGS = ["Situations","Investigations","Entities","Graph","Claims","Evidence","Tasks","Agents","Decisions","Actions","Simulations","History","Processes","Risks","Retrieval","System"]
@pytest.mark.parametrize("tag", REQUIRED_TAGS)
def test_phase11_openapi_has_expected_tag_groups(tag):
    schema=app.openapi(); tags={t for p in schema["paths"].values() for op in p.values() if isinstance(op,dict) for t in op.get("tags",[])}
    assert tag in tags

DOC_PATHS = [
    "/api/v1/situations", "/api/v1/investigations", "/api/v1/entities/{entity_id}", "/api/v1/paths",
    "/api/v1/entities/{entity_id}/blast-radius", "/api/v1/claims/{claim_id}", "/api/v1/evidence/{evidence_id}",
    "/api/v1/tasks/{task_id}/claim", "/api/v1/actions/{action_id}/execute", "/api/v1/simulations/counterfactual",
    "/api/v1/processes/{scope_id}/policy-drift", "/api/v1/risks/bus-factor", "/api/v1/retrieval/search",
]
@pytest.mark.parametrize("path", DOC_PATHS)
def test_phase11_openapi_routes_have_summary_and_responses(path):
    ops=app.openapi()["paths"][path]
    op=next(v for v in ops.values() if isinstance(v,dict) and "responses" in v)
    assert op.get("summary")
    assert "401" in op["responses"] and "422" in op["responses"]


def test_phase11_openapi_contains_common_error_schema():
    assert "ErrorResponse" in app.openapi()["components"]["schemas"]


def test_phase11_public_capabilities_is_available_without_credentials():
    r=api.get("/api/v1/capabilities")
    assert r.status_code==200 and r.json()["external_api"] is True and r.json()["api_version"]=="v1"


def test_phase11_missing_credentials_return_standard_401():
    r=api.get("/api/v1/entities/INC-001")
    assert r.status_code==401 and r.json()["error"]["code"]=="UNAUTHORIZED" and r.json()["error"]["request_id"]


def test_phase11_invalid_credentials_return_standard_401():
    r=api.get("/api/v1/entities/INC-001",headers={"Authorization":"Bearer no-such-token"})
    assert r.status_code==401 and r.json()["error"]["code"]=="UNAUTHORIZED"


def test_phase11_tenant_header_mismatch_is_rejected_before_graph_access():
    r=api.get("/api/v1/entities/INC-001",headers={"Authorization":"Bearer test-reader-token","X-Tenant-ID":"other-tenant"})
    assert r.status_code==403 and r.json()["error"]["code"]=="TENANT_MISMATCH"

@pytest.mark.parametrize("path,method,payload",[
    ("/api/v1/situations","post",{"name":"x"}),
    ("/api/v1/investigations","post",{"situation_id":"INC-X","question":"x"}),
    ("/api/v1/plans","post",{"situation_id":"INC-X","goal":"x"}),
    ("/api/v1/tasks/TASK-X/claim","post",{"agent_id":"A"}),
    ("/api/v1/actions","post",{"task_id":"T","agent_id":"A"}),
    ("/api/v1/actions/A/execute","post",{"agent_id":"A"}),
    ("/api/v1/evidence/E/invalidate","post",{"reason":"x"}),
    ("/api/v1/claims/C/revalidate","post",{"evidence_id":"E"}),
])
def test_phase11_reader_cannot_use_governed_mutations(path,method,payload):
    r=getattr(api,method)(path,headers={"Authorization":"Bearer test-reader-token"},json=payload)
    assert r.status_code==403 and r.json()["error"]["code"]=="FORBIDDEN"


def test_phase11_generated_request_id_is_returned():
    r=api.get("/api/v1/capabilities")
    assert r.headers.get("X-Request-ID")


def test_phase11_client_request_id_is_propagated():
    r=api.get("/api/v1/capabilities",headers={"X-Request-ID":"client-req-123"})
    assert r.headers["X-Request-ID"]=="client-req-123"


def test_phase11_invalid_request_id_is_replaced():
    r=api.get("/api/v1/capabilities",headers={"X-Request-ID":"bad id with spaces"})
    assert r.headers["X-Request-ID"]!="bad id with spaces"


def test_phase11_unknown_versioned_route_uses_standard_error():
    r=api.get("/api/v1/no-such-resource")
    assert r.status_code==404 and r.json()["error"]["code"]=="NOT_FOUND"

@pytest.mark.parametrize("path",[
    "/api/v1/claims?limit=101", "/api/v1/evidence?limit=999", "/api/v1/paths?from=A&to=B&max_hops=7",
    "/api/v1/risks/bus-factor?limit=999", "/api/v1/entities/search?q=x&limit=101",
])
def test_phase11_query_bounds_return_422_before_graph_execution(path):
    r=api.get(path,headers={"Authorization":"Bearer test-reader-token"})
    assert r.status_code==422 and r.json()["error"]["code"]=="VALIDATION_FAILED"


def test_phase11_retrieval_max_result_bound():
    r=api.post("/api/v1/retrieval/search",headers={"Authorization":"Bearer test-reader-token"},json={"query":"x","max_results":51})
    assert r.status_code==422 and r.json()["error"]["code"]=="VALIDATION_FAILED"


def test_phase11_schema_validation_does_not_leak_traceback():
    r=api.post("/api/v1/investigations",headers={"Authorization":"Bearer test-admin-token"},json={"question":"missing situation"})
    text=r.text.lower()
    assert r.status_code==422 and "traceback" not in text and "cypher" not in text


def test_phase11_no_arbitrary_database_routes_exposed():
    paths={r.path.lower() for r in app.routes if r.path.startswith("/api/v1")}
    assert not any("cypher" in p or "sql/query" in p or "proxy" in p for p in paths)


def test_phase11_phase5_forbidden_route_tokens_remain_absent():
    paths={r.path.lower() for r in app.routes}
    forbidden={"claim-task","execute-task","handoff","blackboard","langgraph"}
    assert not any(token in path for path in paths for token in forbidden)


def test_phase11_cursor_roundtrip():
    assert decode_cursor(encode_cursor("CLAIM-XYZ"))=="CLAIM-XYZ"


def test_phase11_invalid_cursor_is_rejected():
    with pytest.raises(ValueError): decode_cursor("%%%")


def test_phase11_stable_id_is_deterministic():
    assert stable_id("X-","a",{"b":1})==stable_id("X-","a",{"b":1})


def test_phase11_stable_id_changes_with_input():
    assert stable_id("X-","a")!=stable_id("X-","b")


def test_phase11_sanitize_removes_secret_like_properties_recursively():
    value=sanitize({"name":"ok","api_token":"secret","nested":{"password":"pw","x":1},"items":[{"private_key":"x","safe":2}]})
    assert value=={"name":"ok","nested":{"x":1},"items":[{"safe":2}]}


def test_phase11_node_visible_current_excludes_closed_validity():
    assert node_visible({"id":"X","valid_until":"2026-10-16T14:00:00+05:30"},None) is False


def test_phase11_node_visible_historical_respects_validity_interval():
    node={"id":"X","valid_from":"2026-10-16T13:00:00+05:30","valid_until":"2026-10-16T15:00:00+05:30"}
    assert node_visible(node,"2026-10-16T14:00:00+05:30") is True
    assert node_visible(node,"2026-10-16T16:00:00+05:30") is False


def test_phase11_admin_test_principal_has_governed_permissions():
    p=_builtins()["test-admin-token"]
    assert {"READ_GRAPH","CREATE_INVESTIGATION","CREATE_PLAN","CLAIM_TASK","PROPOSE_ACTION","EXECUTE_ACTION"} <= p.permissions


def test_phase11_reader_test_principal_is_read_only():
    p=_builtins()["test-reader-token"]
    assert "READ_GRAPH" in p.permissions and "EXECUTE_ACTION" not in p.permissions and "PROPOSE_ACTION" not in p.permissions


def test_phase11_other_tenant_test_principal_is_separate():
    assert _builtins()["test-other-admin-token"].tenant_id=="other-tenant"


def test_phase11_production_mode_disables_builtin_test_credentials(monkeypatch):
    from backend.app.api_v1.security import _configured_principals
    monkeypatch.setenv("GRAPH_HACKS_ENV", "production")
    monkeypatch.delenv("GRAPH_HACKS_DISABLE_TEST_AUTH", raising=False)
    monkeypatch.delenv("GRAPH_HACKS_API_PRINCIPALS_JSON", raising=False)
    assert "test-admin-token" not in _configured_principals()


def test_phase11_configured_principal_remains_available_in_production(monkeypatch):
    from backend.app.api_v1.security import _configured_principals
    monkeypatch.setenv("GRAPH_HACKS_ENV", "production")
    monkeypatch.setenv("GRAPH_HACKS_API_PRINCIPALS_JSON", '{"prod-token":{"subject":"svc","tenant_id":"northstar","roles":["READER"],"permissions":["READ_GRAPH"]}}')
    principals = _configured_principals()
    assert "test-admin-token" not in principals
    assert principals["prod-token"].tenant_id == "northstar"
