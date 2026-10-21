"""Focused Company Brain SQL graph API tests on a disposable FalkorDB graph."""
from __future__ import annotations

import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.main import app


@pytest.fixture
def schema_api(monkeypatch):
    graph = f"verinex_stage4_test_{uuid.uuid4().hex[:8]}"
    settings = Settings(falkordb_host=os.getenv("FALKORDB_HOST", "localhost"),
                        falkordb_port=int(os.getenv("FALKORDB_PORT", "6379")),
                        falkordb_password=os.getenv("FALKORDB_PASSWORD") or None,
                        falkordb_graph=graph, tenant_id="schema-test")
    try:
        client = FalkorGraphClient(settings)
        client.health_check()
    except Exception as exc:
        pytest.skip(f"FalkorDB unavailable: {type(exc).__name__}")
    monkeypatch.setenv("FALKORDB_GRAPH", graph)
    monkeypatch.setenv("GRAPH_HACKS_API_PRINCIPALS_JSON", json.dumps({
        "stage4-reader": {"subject": "reader", "tenant_id": "schema-test", "permissions": ["READ_GRAPH"]},
        "stage4-other": {"subject": "other", "tenant_id": "other-tenant", "permissions": ["READ_GRAPH"]},
        "stage4-no-graph": {"subject": "limited", "tenant_id": "schema-test", "permissions": []},
    }))
    source = {"source_repository": "sample/repo", "source_file_path": "schema.sql",
              "source_commit_sha": "a" * 40, "source_file_hash": "b" * 64,
              "source_uri": "https://github.com/sample/repo/blob/" + "a" * 40 + "/schema.sql",
              "source_ref_id": "SOURCE-A"}
    upsert_node(client, "System", "repo", {"name": "sample/repo"})
    upsert_node(client, "Document", "file", {"name": "schema.sql", **source})
    upsert_node(client, "SqlTable", "payment", {"name": "public.payment", **source})
    upsert_node(client, "SqlTable", "rental", {"name": "public.rental", **source})
    upsert_node(client, "SqlColumn", "payment-rental-id", {"name": "public.payment.rental_id", "column_name": "rental_id", "data_type": "integer", **source})
    upsert_node(client, "SqlConstraint", "payment-rental-fk", {"name": "payment_rental_id_fkey", "constraint_type": "FOREIGN_KEY",
                                                             "constraint_name": "payment_rental_id_fkey", "columns": ["rental_id"],
                                                             "referenced_table": "public.rental", "referenced_columns": ["rental_id"], "ddl_line": 10, **source})
    upsert_relationship(client, "repo", "CONTAINS", "file")
    upsert_relationship(client, "file", "DEFINES", "payment")
    upsert_relationship(client, "payment", "HAS_COLUMN", "payment-rental-id")
    upsert_relationship(client, "payment", "HAS_CONSTRAINT", "payment-rental-fk")
    upsert_relationship(client, "payment", "FOREIGN_KEY_TO", "rental", {"constraint_name": "payment_rental_id_fkey",
                                                                       "constraint_id": "payment-rental-fk", "source_columns": ["rental_id"],
                                                                       "target_columns": ["rental_id"], **source})
    try:
        with TestClient(app) as api:
            yield api
    finally:
        client.delete_graph()  # Only this test's unique disposable graph.


def _headers(token="stage4-reader", tenant="schema-test"):
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant}


def test_sql_schema_api_returns_actual_nodes_fk_and_source_detail(schema_api):
    response = schema_api.get("/api/v1/company-brain/sql-schema?source_id=SOURCE-A", headers=_headers())
    assert response.status_code == 200
    data = response.json()
    assert [table["name"] for table in data["tables"]] == ["public.payment", "public.rental"]
    assert [(edge["source_id"], edge["target_id"], edge["properties"]["constraint_name"])
            for edge in data["foreign_keys"]] == [("payment", "rental", "payment_rental_id_fkey")]
    detail = schema_api.get("/api/v1/company-brain/sql-schema/payment", headers=_headers())
    assert detail.status_code == 200
    assert detail.json()["columns"][0]["column_name"] == "rental_id"
    assert detail.json()["constraints"][0]["ddl_line"] == 10
    assert detail.json()["source"]["repository"]["name"] == "sample/repo"
    assert detail.json()["source"]["file"]["source_commit_sha"] == "a" * 40
    assert detail.json()["foreign_keys"][0]["target"]["name"] == "public.rental"


def test_sql_schema_api_filters_source_and_enforces_tenant_and_read_permission(schema_api):
    assert schema_api.get("/api/v1/company-brain/sql-schema?source_id=OTHER", headers=_headers()).json()["tables"] == []
    assert schema_api.get("/api/v1/company-brain/sql-schema", headers=_headers("stage4-other", "other-tenant")).json()["tables"] == []
    assert schema_api.get("/api/v1/company-brain/sql-schema/payment", headers=_headers("stage4-other", "other-tenant")).status_code == 404
    assert schema_api.get("/api/v1/company-brain/sql-schema", headers=_headers("stage4-no-graph")).status_code == 403
    assert schema_api.get("/api/v1/company-brain/sql-schema", headers={}).status_code == 401
