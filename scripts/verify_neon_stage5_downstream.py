"""Verify Sources-to-Company-Brain wiring with the integrity-checked Stage 3 artifact.

GitHub transport is replaced in-process. This does not verify remote access.
The unique FalkorDB graph is left intact for browser inspection.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.ingestion.adapters.github import GitHubAdapter
from backend.app.main import app

REPO = "neondatabase/postgres-sample-dbs"


def main() -> int:
    previous = json.loads(Path("reports/verinex_neon_integration/STAGE_3_REMOTE.json").read_text(encoding="utf-8"))
    blob_path = (Path(previous["artifact_root"]) / "neon-stage3" / "github" /
                 previous["source_file_hash"][:2] / previous["source_file_hash"] / "payload.bin")
    content = blob_path.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest()
    blob_sha = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
    assert sha256 == previous["source_file_hash"] and blob_sha == previous["source_blob_sha"]
    commit = previous["source_commit_sha"]
    tree = "c" * 40

    class LocalVerifiedGitHub:
        def get_json(self, path, *, query=None):
            base = f"/repos/{REPO}"
            if path == base:
                return {"id": 1, "name": "postgres-sample-dbs", "full_name": REPO,
                        "html_url": f"https://github.com/{REPO}", "owner": {"login": "neondatabase"},
                        "default_branch": "main"}
            if path == f"{base}/commits/{commit}":
                return {"sha": commit, "commit": {"tree": {"sha": tree}}}
            if path == f"{base}/git/trees/{tree}":
                return {"truncated": False, "tree": [{"path": "dvdrental.sql", "type": "blob", "mode": "100644",
                                                   "sha": blob_sha, "size": len(content)}]}
            if path == f"{base}/git/blobs/{blob_sha}":
                return {"encoding": "base64", "sha": blob_sha, "content": base64.b64encode(content).decode("ascii")}
            raise AssertionError(f"Unexpected local GitHub transport path: {path}")

    suffix = uuid.uuid4().hex[:8]
    graph, tenant, source_id = f"verinex_neon_stage5_downstream_{suffix}", f"neon-stage5-{suffix}", f"SRC-NEON-STAGE5-{suffix.upper()}"
    root = Path(os.getenv("TEMP", ".")) / "verinex-neon-stage5" / suffix
    os.environ.update({"FALKORDB_GRAPH": graph, "GRAPH_HACKS_ARTIFACT_ROOT": str(root / "artifacts"),
                       "GRAPH_HACKS_RETRIEVAL_ROOT": str(root / "retrieval"),
                       "GRAPH_HACKS_API_PRINCIPALS_JSON": json.dumps({
                           "stage5-local-admin": {"subject": "stage5-verifier", "tenant_id": tenant,
                                                  "permissions": ["ADMIN"]}})})
    headers = {"Authorization": "Bearer stage5-local-admin", "X-Tenant-ID": tenant}
    evidence = {"status": "DOWNSTREAM_ONLY", "graph": graph, "tenant": tenant, "source_id": source_id,
                "artifact_sha256": sha256, "git_blob_sha": blob_sha, "commit": commit}
    with TestClient(app) as api:
        created = api.post("/api/v1/sources", headers=headers, json={
            "source_id": source_id, "display_name": "Neon DVD rental downstream", "connector_type": "github",
            "connection_mode": "live", "connection_config": {"settings": {
                "repository": f"https://github.com/{REPO}", "ref": commit, "anonymous": True}},
            "scope_config": {"files": ["dvdrental.sql"]},
        })
        assert created.status_code == 201, created.text
        assert created.json()["credential"]["configured"] is False
        runs = []
        with patch.object(GitHubAdapter, "_client", return_value=LocalVerifiedGitHub()):
            for _ in range(2):
                response = api.post(f"/api/v1/sources/{source_id}/sync", headers=headers,
                                    json={"mode": "full", "max_records": 2})
                assert response.status_code == 200, response.text
                run = response.json()
                runs.append({key: run[key] for key in ("run_id", "status", "fetched", "normalized", "written",
                                                       "quarantined", "failed", "artifacts", "warnings")})
                assert run["status"] == "SUCCEEDED" and run["failed"] == run["quarantined"] == 0, run
                schema = api.get("/api/v1/company-brain/sql-schema", headers=headers,
                                 params={"source_id": source_id})
                assert schema.status_code == 200, schema.text
                graph_data = schema.json()
                assert len(graph_data["tables"]) == 15 and len(graph_data["foreign_keys"]) == 18
        evidence["runs"] = runs
        by_name = {table["name"]: table for table in graph_data["tables"]}
        path = [f"public.{name}" for name in ("payment", "rental", "inventory", "film")]
        constraints = []
        for from_name, to_name in zip(path, path[1:]):
            matches = [edge for edge in graph_data["foreign_keys"]
                       if edge["source_id"] == by_name[from_name]["id"] and edge["target_id"] == by_name[to_name]["id"]]
            assert len(matches) == 1
            constraints.append(matches[0]["properties"]["constraint_name"])
        payment = api.get(f"/api/v1/company-brain/sql-schema/{by_name['public.payment']['id']}", headers=headers)
        assert payment.status_code == 200
        detail = payment.json()
        assert detail["source"]["file"]["source_file_hash"] == sha256
        assert detail["source"]["file"]["source_commit_sha"] == commit
        assert any(c["constraint_name"] == "payment_rental_id_fkey" and c["ddl_line"] for c in detail["constraints"])
        source = api.get(f"/api/v1/sources/{source_id}", headers=headers).json()
        assert source["ingestion"]["status"] == "SUCCESS"
        evidence.update({"table_count": len(graph_data["tables"]), "foreign_key_count": len(graph_data["foreign_keys"]),
                         "path": path, "path_constraints": constraints,
                         "payment_columns": len(detail["columns"]), "payment_constraints": len(detail["constraints"]),
                         "source_ingestion_status": source["ingestion"]["status"],
                         "source_credential_configured": source["credential"]["configured"]})
    output = Path("reports/verinex_neon_integration/STAGE_5_DOWNSTREAM.json")
    output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: evidence[key] for key in ("status", "graph", "tenant", "source_id", "table_count",
                                                      "foreign_key_count", "path", "source_ingestion_status")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
