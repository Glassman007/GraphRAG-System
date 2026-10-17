from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import main as main_module

pytestmark = pytest.mark.integration


@pytest.fixture
def api(integration_client, monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "_client", lambda: integration_client)
    monkeypatch.setenv("GRAPH_HACKS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    return TestClient(main_module.app)


def test_phase9_api_lists_sources_without_credentials(api):
    response = api.get("/ingestion/sources")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["sources"]) == 8
    text = response.text.lower()
    assert "ghp_" not in text and "xoxb-" not in text


def test_phase9_api_dry_run_does_not_create_run(api):
    before = api.get("/ingestion/runs").json()["runs"]
    response = api.post("/ingestion/sources/DS-ING-GITHUB/sync", json={"mode":"full","max_records":2,"dry_run":True})
    assert response.status_code == 200
    assert response.json()["status"] == "DRY_RUN"
    after = api.get("/ingestion/runs").json()["runs"]
    assert len(after) == len(before)


def test_phase9_api_sync_run_report_quarantine_and_artifact(api):
    sync = api.post("/ingestion/sources/DS-ING-TELEMETRY/sync", json={"mode":"full","max_records":10})
    assert sync.status_code == 200 and sync.json()["status"] == "SUCCEEDED"
    run_id = sync.json()["run_id"]
    run = api.get(f"/ingestion/runs/{run_id}")
    assert run.status_code == 200 and run.json()["source_id"] == "DS-ING-TELEMETRY"
    # Telemetry fixture contains a log artifact.
    from backend.app.services.phase4_graph import GraphSnapshot, has_label
    snapshot = GraphSnapshot.load(main_module._client())
    artifact = next(n for n in snapshot.nodes.values() if has_label(n, "Artifact") and n.get("source_type") == "telemetry")
    meta = api.get(f"/ingestion/artifacts/{artifact['id']}")
    assert meta.status_code == 200 and meta.json()["sha256"]


def test_phase9_api_invalid_source_and_missing_records_have_meaningful_status(api):
    assert api.post("/ingestion/sources/NOPE/sync", json={"mode":"incremental"}).status_code == 404
    assert api.get("/ingestion/runs/NOPE").status_code == 404
    assert api.get("/ingestion/quarantine/NOPE").status_code == 404
    assert api.get("/ingestion/artifacts/NOPE").status_code == 404


def test_phase9_api_quarantine_list_and_record_are_queryable(api):
    from backend.app.graph.mutations import upsert_node
    upsert_node(main_module._client(), "IngestionQuarantineRecord", "QUAR-API-P9", {
        "name": "API quarantine fixture",
        "source_record_id": "SRC-API-P9",
        "entity_key": "person:ambiguous",
        "candidate_label": "Person",
        "status": "OPEN",
        "reason": "AMBIGUOUS_IDENTITY",
        "created_at": "2026-10-16T10:00:00+05:30",
        "source_ref_id": "DS-ING-GITHUB",
    })
    listing = api.get("/ingestion/quarantine")
    assert listing.status_code == 200
    assert any(item["id"] == "QUAR-API-P9" for item in listing.json()["records"])
    record = api.get("/ingestion/quarantine/QUAR-API-P9")
    assert record.status_code == 200 and record.json()["reason"] == "AMBIGUOUS_IDENTITY"
