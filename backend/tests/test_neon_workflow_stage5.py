"""Focused regression: Sources can register a public repository in a new graph."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from redis import Redis

from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient
from backend.app.main import app
from backend.app.ingestion.adapters.github import GitHubAdapter
from backend.app.retrieval.indexing import RetrievalIndexer


def test_public_github_registration_initializes_fresh_graph(monkeypatch):
    graph = f"verinex_stage5_registration_{uuid.uuid4().hex[:8]}"
    tenant = f"stage5-registration-{uuid.uuid4().hex[:8]}"
    try:
        client = FalkorGraphClient(Settings(falkordb_host=os.getenv("FALKORDB_HOST", "localhost"),
                                           falkordb_port=int(os.getenv("FALKORDB_PORT", "6379")),
                                           falkordb_password=os.getenv("FALKORDB_PASSWORD") or None,
                                           falkordb_graph=graph, tenant_id=tenant))
        Redis(host=client.settings.falkordb_host, port=client.settings.falkordb_port,
              password=client.settings.falkordb_password or None, socket_connect_timeout=2).ping()
    except Exception as exc:
        pytest.skip(f"FalkorDB unavailable: {type(exc).__name__}")
    monkeypatch.setenv("FALKORDB_GRAPH", graph)
    monkeypatch.setenv("GRAPH_HACKS_API_PRINCIPALS_JSON", json.dumps({
        "stage5-registration": {"subject": "verifier", "tenant_id": tenant,
                                "permissions": ["MANAGE_INGESTION", "READ_GRAPH"]},
    }))
    headers = {"Authorization": "Bearer stage5-registration", "X-Tenant-ID": tenant}
    body = {"display_name": "Public sample", "connector_type": "github", "connection_mode": "live",
            "connection_config": {"settings": {"repository": "https://github.com/neondatabase/postgres-sample-dbs",
                                               "ref": "b54cb67534bf20775803b181b7a1c6f573422161", "anonymous": True}},
            "scope_config": {"files": ["dvdrental.sql"]}}
    try:
        with TestClient(app) as api:
            created = api.post("/api/v1/sources", json=body, headers=headers)
            assert created.status_code == 201, created.text
            assert created.json()["credential"]["configured"] is False
            assert created.json()["scope"]["files"] == ["dvdrental.sql"]
            source_id = created.json()["source_id"]
            assert api.get(f"/api/v1/sources/{source_id}", headers=headers).status_code == 200

            sql = (b"CREATE TABLE public.parent (\n id integer PRIMARY KEY\n);\n"
                   b"CREATE TABLE public.child (\n id integer PRIMARY KEY,\n parent_id integer\n);\n"
                   b"ALTER TABLE public.child ADD CONSTRAINT child_parent_fk "
                   b"FOREIGN KEY (parent_id) REFERENCES public.parent(id);\n")
            blob = hashlib.sha1(f"blob {len(sql)}\0".encode() + sql).hexdigest()
            commit = body["connection_config"]["settings"]["ref"]
            tree = "c" * 40

            class LocalGitHub:
                def get_json(self, path, *, query=None):
                    base = "/repos/neondatabase/postgres-sample-dbs"
                    if path == base:
                        return {"id": 1, "name": "postgres-sample-dbs", "full_name": "neondatabase/postgres-sample-dbs",
                                "html_url": "https://github.com/neondatabase/postgres-sample-dbs", "owner": {"login": "neondatabase"},
                                "default_branch": "main"}
                    if path == f"{base}/commits/{commit}":
                        return {"sha": commit, "commit": {"tree": {"sha": tree}}}
                    if path == f"{base}/git/trees/{tree}":
                        return {"truncated": False, "tree": [{"path": "dvdrental.sql", "type": "blob", "mode": "100644",
                                                       "sha": blob, "size": len(sql)}]}
                    if path == f"{base}/git/blobs/{blob}":
                        return {"encoding": "base64", "sha": blob, "content": base64.b64encode(sql).decode()}
                    raise AssertionError(path)

            with (patch.object(GitHubAdapter, "_client", return_value=LocalGitHub()),
                  patch.object(RetrievalIndexer, "index_artifact") as index_artifact):
                result = api.post(f"/api/v1/sources/{source_id}/sync",
                                  json={"mode": "full", "max_records": 2}, headers=headers)
            assert result.status_code == 200, result.text
            assert result.json()["status"] == "SUCCEEDED"
            index_artifact.assert_not_called()
            schema = api.get("/api/v1/company-brain/sql-schema", params={"source_id": source_id}, headers=headers)
            assert schema.status_code == 200
            assert len(schema.json()["tables"]) == 2
            assert len(schema.json()["foreign_keys"]) == 1
    finally:
        client.delete_graph()  # This test's unique graph only.
