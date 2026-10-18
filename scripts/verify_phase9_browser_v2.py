from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path.cwd()
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from backend.app import main as main_module
from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.schema import apply_schema
from backend.app.ingestion.artifacts.local import LocalArtifactStore
from backend.app.ingestion.models import SourceConfig, TrustClass
from backend.app.ingestion.pipeline import IngestionPipeline
from backend.app.ingestion.registry import SourceRegistry, fixture_source_configs
from backend.app.services.blast_radius_service import BlastRadiusService
from backend.app.services.investigation_service import RelationalInvestigationService
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.policy_drift_service import PolicyDriftService
from backend.app.services.process_reconstruction_service import OrganizationalProcessReconstructionService
from backend.app.services.routing_service import ResponsibilityRoutingService


class AcceptanceFailure(RuntimeError):
    pass


def safe_delete_graph(client: FalkorGraphClient) -> bool:
    try:
        return client.delete_graph()
    except Exception as exc:
        text = str(exc).lower()
        if "invalid graph operation on empty key" in text or "empty key" in text:
            client.graph = client.db.select_graph(client.settings.falkordb_graph)
            return False
        raise


class Runner:
    def __init__(self, *, graph_name: str, cleanup: bool):
        self.graph_name = graph_name
        self.cleanup = cleanup
        self.results: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self.created_run_ids: list[str] = []
        self.artifact_ids: list[str] = []
        self.custom_ids: dict[str, str] = {}

        os.environ["GRAPH_HACKS_INGESTION_MODE"] = "fixture"

        self.settings = Settings(
            falkordb_host=os.getenv("FALKORDB_HOST", "localhost"),
            falkordb_port=int(os.getenv("FALKORDB_PORT", "6379")),
            falkordb_graph=graph_name,
            falkordb_password=os.getenv("FALKORDB_PASSWORD") or None,
            tenant_id=os.getenv("GRAPH_TENANT_ID", "northstar"),
        )
        self.client = FalkorGraphClient(self.settings)
        self.artifact_root = ROOT / f"phase9_acceptance_artifacts_{graph_name}"
        os.environ["GRAPH_HACKS_ARTIFACT_ROOT"] = str(self.artifact_root)
        self.fixture_root = self.artifact_root / "_fixtures"
        self.fixture_root.mkdir(parents=True, exist_ok=True)

        main_module._client = lambda: self.client
        self.api = TestClient(main_module.app)

    def record(self, phase: str, name: str, ok: bool, detail: Any = None, *, critical: bool = False) -> None:
        row = {"phase": phase, "name": name, "ok": bool(ok), "detail": detail}
        self.results.append(row)
        tag = "PASS" if ok else "FAIL"
        suffix = f" :: {detail}" if detail not in (None, "") else ""
        print(f"[{tag}] {phase}: {name}{suffix}")
        if not ok:
            self.failures.append(row)
            if critical:
                raise AcceptanceFailure(f"{phase} / {name}: {detail}")

    def require(self, phase: str, name: str, condition: bool, detail: Any = None, *, critical: bool = False) -> None:
        self.record(phase, name, bool(condition), detail, critical=critical)

    def snapshot(self) -> GraphSnapshot:
        return GraphSnapshot.load(self.client)

    def setup(self) -> None:
        print("=" * 78)
        print("GraphHacks Phase 9 LIVE / BROWSER acceptance runner")
        print(f"Repository : {ROOT}")
        print(f"FalkorDB   : {self.settings.falkordb_host}:{self.settings.falkordb_port}")
        print(f"Test graph : {self.graph_name}")
        print("Mode       : fixture-backed adapters only")
        print("NOTE: company_brain is NOT modified; this runner uses an isolated graph.")
        print("=" * 78)

        deleted = safe_delete_graph(self.client)
        if deleted:
            print("[INFO] Removed a pre-existing acceptance graph with the same name")
        else:
            print("[INFO] Acceptance graph pre-clean: graph did not exist; starting fresh")

        apply_schema(self.client)
        health = self.client.health_check()
        self.require("SETUP", "FalkorDB live connection", bool(health.get("ok")), health, critical=True)

        response = self.api.get("/health")
        self.require("SETUP", "FastAPI health uses isolated FalkorDB graph", response.status_code == 200 and response.json().get("graph") == self.graph_name, response.json() if response.status_code == 200 else response.text, critical=True)

    def api_and_ingestion(self) -> None:
        phase = "PHASE 9 / API + INGESTION"

        sources_response = self.api.get("/ingestion/sources")
        self.require(phase, "GET /ingestion/sources succeeds", sources_response.status_code == 200, sources_response.status_code, critical=True)
        sources = sources_response.json().get("sources", [])
        expected_ids = {
            "DS-ING-GITHUB", "DS-ING-JIRA", "DS-ING-SLACK", "DS-ING-TEAMS",
            "DS-ING-DOCS", "DS-ING-TELEMETRY", "DS-ING-DATABASE", "DS-ING-INTERNAL",
        }
        returned_ids = {x.get("id") for x in sources}
        self.require(phase, "All eight configured adapters are exposed", returned_ids == expected_ids, sorted(returned_ids), critical=True)
        self.require(phase, "Fixture adapters are explicitly marked fixture-verified", all(x.get("verification") == "FIXTURE_VERIFIED" for x in sources), {x.get("id"): x.get("verification") for x in sources})
        source_text = sources_response.text.lower()
        self.require(phase, "Source API does not expose common token formats", "ghp_" not in source_text and "xoxb-" not in source_text and "password" not in source_text, None)

        before = self.snapshot()
        before_nodes = set(before.nodes)
        runs_before = self.api.get("/ingestion/runs").json().get("runs", [])
        dry = self.api.post("/ingestion/sources/DS-ING-GITHUB/sync", json={"mode": "full", "max_records": 3, "batch_size": 2, "dry_run": True})
        self.require(phase, "Dry-run endpoint succeeds", dry.status_code == 200 and dry.json().get("status") == "DRY_RUN", dry.json() if dry.status_code == 200 else dry.text, critical=True)
        self.require(phase, "Dry-run proposes graph mutations", bool(dry.json().get("proposed_mutations")), len(dry.json().get("proposed_mutations", [])))
        runs_after = self.api.get("/ingestion/runs").json().get("runs", [])
        after_dry = self.snapshot()
        self.require(phase, "Dry-run does not create an IngestionRun", len(runs_after) == len(runs_before), {"before": len(runs_before), "after": len(runs_after)})
        self.require(phase, "Dry-run does not mutate canonical graph state", set(after_dry.nodes) == before_nodes, {"before_nodes": len(before_nodes), "after_nodes": len(after_dry.nodes)})

        for source_id in sorted(expected_ids):
            response = self.api.post(f"/ingestion/sources/{source_id}/sync", json={"mode": "full", "max_records": 100, "batch_size": 50, "dry_run": False})
            payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {"text": response.text}
            ok = response.status_code == 200 and payload.get("status") == "SUCCEEDED"
            self.require(phase, f"Full fixture sync succeeds: {source_id}", ok, payload, critical=True)
            self.created_run_ids.append(payload["run_id"])

            run = self.api.get(f"/ingestion/runs/{payload['run_id']}")
            self.require(phase, f"Run report is queryable: {source_id}", run.status_code == 200 and run.json().get("source_id") == source_id and run.json().get("status") == "SUCCEEDED", run.json() if run.status_code == 200 else run.text)

        snapshot = self.snapshot()
        data_sources = [n for n in snapshot.nodes.values() if has_label(n, "DataSource")]
        runs = [n for n in snapshot.nodes.values() if has_label(n, "IngestionRun")]
        raw_records = [n for n in snapshot.nodes.values() if has_label(n, "SourceRecord") and n.get("record_type") != "identity_projection"]
        self.require(phase, "Eight DataSource nodes are persisted", len({n.get("id") for n in data_sources if str(n.get("id", "")).startswith("DS-ING-")}) == 8, [n.get("id") for n in data_sources])
        self.require(phase, "All source syncs created durable IngestionRun nodes", all(self.snapshot().node(rid) is not None for rid in self.created_run_ids), self.created_run_ids)
        self.require(phase, "Raw SourceRecords were persisted", len(raw_records) >= 15, len(raw_records))

        invalid = self.api.post("/ingestion/sources/NO-SUCH-SOURCE/sync", json={"mode": "incremental"})
        self.require(phase, "Unknown source returns HTTP 404", invalid.status_code == 404, invalid.status_code)
        self.require(phase, "Unknown run returns HTTP 404", self.api.get("/ingestion/runs/NOPE").status_code == 404, None)
        self.require(phase, "Unknown quarantine record returns HTTP 404", self.api.get("/ingestion/quarantine/NOPE").status_code == 404, None)
        self.require(phase, "Unknown artifact returns HTTP 404", self.api.get("/ingestion/artifacts/NOPE").status_code == 404, None)

    def ontology_resolution_provenance_artifacts(self) -> None:
        phase = "PHASE 9 / NORMALIZATION + RESOLUTION + PROVENANCE"
        snapshot = self.snapshot()

        neha = [n for n in snapshot.nodes.values() if has_label(n, "Person") and str(n.get("email") or "").lower() == "neha.verma@northstar.example"]
        self.require(phase, "GitHub/Jira/Slack/Teams resolve to ONE canonical Neha", len(neha) == 1, [n.get("id") for n in neha], critical=True)
        neha_ext = [n for n in snapshot.nodes.values() if has_label(n, "ExternalIdentity") and str(n.get("email") or "").lower() == "neha.verma@northstar.example"]
        self.require(phase, "Canonical Neha retains at least four source identities", len(neha_ext) >= 4, [(n.get("source_type"), n.get("external_id")) for n in neha_ext])
        resolved_targets = set()
        for identity in neha_ext:
            for edge in snapshot.edges_from(str(identity["id"]), {"RESOLVES_TO"}):
                resolved_targets.add(edge.target)
        self.require(phase, "All Neha ExternalIdentity nodes resolve to the same Person", len(resolved_targets) == 1 and neha and next(iter(resolved_targets), None) == neha[0]["id"], sorted(resolved_targets))

        source_specific_labels = {"GitHubPerson", "JiraPerson", "SlackPerson", "TeamsPerson", "GitHubProject", "JiraProject"}
        found_bad_labels = sorted({label for n in snapshot.nodes.values() for label in (n.get("_labels") or []) if label in source_specific_labels})
        self.require(phase, "No provider-specific canonical ontology labels were introduced", not found_bad_labels, found_bad_labels)

        raw_records = [n for n in snapshot.nodes.values() if has_label(n, "SourceRecord") and n.get("record_type") != "identity_projection"]
        missing_source = []
        missing_normalized = []
        for n in raw_records:
            rid = str(n["id"])
            if not snapshot.edges_from(rid, {"DERIVED_FROM"}):
                missing_source.append(rid)
            if not n.get("deleted") and not snapshot.edges_from(rid, {"NORMALIZED_TO"}):
                missing_normalized.append(rid)
        self.require(phase, "Every raw SourceRecord has DataSource provenance", not missing_source, missing_source)
        self.require(phase, "Every non-tombstone SourceRecord retains canonical lineage", not missing_normalized, missing_normalized)

        mapping_missing = [n.get("id") for n in raw_records if not n.get("adapter_version") or not n.get("mapping_version")]
        self.require(phase, "SourceRecords retain adapter and mapping versions", not mapping_missing, mapping_missing)
        temporal_missing = [n.get("id") for n in raw_records if not n.get("fetched_at") or not n.get("created_at")]
        self.require(phase, "SourceRecords preserve ingestion/fetch temporal metadata", not temporal_missing, temporal_missing)

        slack_claims = [n for n in snapshot.nodes.values() if has_label(n, "Claim") and n.get("source_ref_id") == "DS-ING-SLACK"]
        self.require(phase, "Slack assertions enter the graph as Claims", len(slack_claims) >= 2, [(n.get("id"), n.get("statement"), n.get("status")) for n in slack_claims])
        self.require(phase, "Slack Claims remain UNVERIFIED", slack_claims and all(n.get("status") == "UNVERIFIED" for n in slack_claims), [(n.get("id"), n.get("status")) for n in slack_claims])

        owns = [e for e in snapshot.edges_from("TEAM-PRICING", {"OWNS"}) if e.target == "SYS-PRICING-API" and e.properties.get("valid_until") is None]
        self.require(phase, "Authoritative imported ownership exists", bool(owns), [e.properties for e in owns])
        self.require(phase, "Imported ownership retains relationship provenance", bool(owns) and bool(owns[0].properties.get("source_record_ids_csv")), owns[0].properties if owns else None)

        dep_a = [e for e in snapshot.edges_from("SYS-CHECKOUT", {"DEPENDS_ON"}) if e.target == "SYS-PRICING-API" and e.properties.get("valid_until") is None]
        dep_b = [e for e in snapshot.edges_from("SYS-PRICING-API", {"DEPENDS_ON"}) if e.target == "SYS-PRICING-DB" and e.properties.get("valid_until") is None]
        self.require(phase, "Imported service dependencies exist", bool(dep_a and dep_b), {"checkout_to_pricing": bool(dep_a), "pricing_to_db": bool(dep_b)})

        artifacts = [n for n in snapshot.nodes.values() if has_label(n, "Artifact")]
        self.artifact_ids = [str(n["id"]) for n in artifacts]
        self.require(phase, "Large/document artifacts are represented by lightweight Artifact nodes", bool(artifacts), [(n.get("id"), n.get("uri"), n.get("sha256")) for n in artifacts])
        self.require(phase, "Artifact payloads physically exist outside FalkorDB", any(self.artifact_root.rglob("payload.bin")), str(self.artifact_root))
        evidence_with_artifact = []
        for n in snapshot.nodes.values():
            if has_label(n, "Evidence"):
                for e in snapshot.edges_from(str(n["id"]), {"DERIVED_FROM"}):
                    if has_label(snapshot.node(e.target), "Artifact"):
                        evidence_with_artifact.append((n["id"], e.target))
        self.require(phase, "Evidence retains DERIVED_FROM lineage to external Artifact", bool(evidence_with_artifact), evidence_with_artifact)

        if artifacts:
            meta = self.api.get(f"/ingestion/artifacts/{artifacts[0]['id']}")
            self.require(phase, "Artifact metadata is available through HTTP API", meta.status_code == 200 and bool(meta.json().get("sha256")), meta.json() if meta.status_code == 200 else meta.text)

    def existing_capabilities(self) -> None:
        phase = "PHASE 9 / EXISTING CAPABILITY INTEGRATION"

        owner = ResponsibilityRoutingService(self.client).find_owner("SYS-PRICING-API")
        self.require(phase, "Phase 3 routing consumes imported ownership", bool(owner.get("owners")) and owner["owners"][0]["actor"]["id"] == "TEAM-PRICING", owner)

        blast = BlastRadiusService(self.client).analyze("SYS-PRICING-DB")
        impacted = {x["system"]["id"] for x in blast.get("downstream_dependents", [])}
        self.require(phase, "Phase 4 blast radius consumes imported dependencies", "SYS-CHECKOUT" in impacted, sorted(impacted))

        investigation = RelationalInvestigationService(self.client).investigate_incident("INC-001")
        self.require(phase, "Relational investigation consumes imported change/evidence graph", bool(investigation and investigation.get("candidate_paths")), investigation.get("candidate_paths", [])[:3] if investigation else None)

        process = OrganizationalProcessReconstructionService(self.client).reconstruct("INC-001")
        self.require(phase, "Phase 8 process reconstruction consumes imported events", bool(process and process.get("steps")), [x.get("id") for x in process.get("steps", [])[:20]] if process else None)

        drift = PolicyDriftService(self.client).analyze("INC-001", policy_id="POL-DB-04")
        classifications = [x.get("classification") for x in drift.get("drift", [])]
        self.require(phase, "Phase 8 policy drift consumes imported policy requirements", "MISSING_REQUIRED_STEP" in classifications, classifications)

    def idempotency_and_incremental(self) -> None:
        phase = "PHASE 9 / IDEMPOTENCY + INCREMENTAL"
        snapshot_before = self.snapshot()
        canonical_before = {
            nid for nid, n in snapshot_before.nodes.items()
            if not has_label(n, "IngestionRun") and not has_label(n, "Event")
        }
        artifact_count_before = len([n for n in snapshot_before.nodes.values() if has_label(n, "Artifact")])
        person_count_before = len([n for n in snapshot_before.nodes.values() if has_label(n, "Person")])

        for source_id in (
            "DS-ING-GITHUB", "DS-ING-JIRA", "DS-ING-SLACK", "DS-ING-TEAMS",
            "DS-ING-DOCS", "DS-ING-TELEMETRY", "DS-ING-DATABASE", "DS-ING-INTERNAL",
        ):
            response = self.api.post(f"/ingestion/sources/{source_id}/sync", json={"mode": "full", "max_records": 100, "batch_size": 50, "dry_run": False})
            self.require(phase, f"Repeat full sync succeeds: {source_id}", response.status_code == 200 and response.json().get("status") == "SUCCEEDED", response.json() if response.status_code == 200 else response.text, critical=True)

        snapshot_after = self.snapshot()
        canonical_after = {
            nid for nid, n in snapshot_after.nodes.items()
            if not has_label(n, "IngestionRun") and not has_label(n, "Event")
        }
        artifact_count_after = len([n for n in snapshot_after.nodes.values() if has_label(n, "Artifact")])
        person_count_after = len([n for n in snapshot_after.nodes.values() if has_label(n, "Person")])

        self.require(phase, "Unchanged full re-sync does not duplicate canonical/source/artifact nodes", canonical_before == canonical_after, {"before": len(canonical_before), "after": len(canonical_after)})
        self.require(phase, "Unchanged re-sync does not duplicate Artifact nodes", artifact_count_before == artifact_count_after, {"before": artifact_count_before, "after": artifact_count_after})
        self.require(phase, "Unchanged re-sync does not duplicate Person nodes", person_count_before == person_count_after, {"before": person_count_before, "after": person_count_after})

        inc = self.api.post("/ingestion/sources/DS-ING-GITHUB/sync", json={"mode": "incremental", "max_records": 100, "batch_size": 50, "dry_run": False})
        payload = inc.json() if inc.status_code == 200 else {"text": inc.text}
        self.require(phase, "Incremental sync succeeds after full sync", inc.status_code == 200 and payload.get("status") == "SUCCEEDED", payload)
        self.require(phase, "Incremental sync resumes from persisted cursor", payload.get("cursor_start") is not None, payload)
        self.require(phase, "No unchanged GitHub records are re-fetched incrementally", payload.get("fetched") == 0, payload)

    def quarantine(self) -> None:
        phase = "PHASE 9 / QUARANTINE"
        fixture = self.fixture_root / "ambiguous_identity.json"
        fixture.write_text(json.dumps({"records": [
            {
                "external_id": "browser-seed",
                "record_type": "user",
                "observed_at": "2026-10-16T10:00:00+05:30",
                "display_name": "Browser Review Person",
                "email": "browser.review@northstar.example",
                "login": "browser-review",
            },
            {
                "external_id": "browser-ambiguous",
                "record_type": "user",
                "observed_at": "2026-10-16T10:01:00+05:30",
                "display_name": "Browser Review Person",
                "login": "browser-review-alt",
            },
        ]}, indent=2), encoding="utf-8")

        base = {c.source_type: c for c in fixture_source_configs(ROOT)}["github"].model_copy(deep=True)
        base.id = "DS-P9-BROWSER-AMBIG"
        base.source_instance = "browser-ambiguous-github"
        base.fixture_path = str(fixture)
        registry = SourceRegistry(self.client)
        registry.register(base, persist=False)
        pipeline = IngestionPipeline(self.client, registry=registry, artifact_store=LocalArtifactStore(self.artifact_root))
        report = pipeline.sync(base.id, mode="full", max_records=10)
        self.require(phase, "Ambiguous identity fixture ingests", report.status.value == "SUCCEEDED", report.model_dump(mode="json"), critical=True)
        self.require(phase, "Ambiguous name-only identity is quarantined", report.quarantined >= 1, report.model_dump(mode="json"))

        listing = self.api.get("/ingestion/quarantine?status=OPEN")
        records = listing.json().get("records", []) if listing.status_code == 200 else []
        candidates = [x for x in records if x.get("source_ref_id") == base.id]
        self.require(phase, "Quarantine record is visible through API", listing.status_code == 200 and bool(candidates), candidates, critical=True)
        q = candidates[0]
        self.custom_ids["quarantine_id"] = str(q["id"])
        detail = self.api.get(f"/ingestion/quarantine/{q['id']}")
        self.require(phase, "Quarantine record detail is queryable", detail.status_code == 200 and detail.json().get("status") == "OPEN", detail.json() if detail.status_code == 200 else detail.text)

        snapshot = self.snapshot()
        person = next((n for n in snapshot.nodes.values() if has_label(n, "Person") and n.get("email") == "browser.review@northstar.example"), None)
        self.require(phase, "Strong seed identity created exactly one review Person", person is not None, person, critical=True)
        before_count = len([n for n in snapshot.nodes.values() if has_label(n, "Person") and n.get("name") == "Browser Review Person"])
        resolve = self.api.post(f"/ingestion/quarantine/{q['id']}/resolve", json={"canonical_id": person["id"], "reviewer_ref": "phase9-browser-acceptance"})
        self.require(phase, "Quarantine can be manually resolved to canonical Person", resolve.status_code == 200 and resolve.json().get("status") == "RESOLVED" and resolve.json().get("resolved_to") == person["id"], resolve.json() if resolve.status_code == 200 else resolve.text)
        after = self.snapshot()
        after_count = len([n for n in after.nodes.values() if has_label(n, "Person") and n.get("name") == "Browser Review Person"])
        self.require(phase, "Manual resolution does not create duplicate Person", before_count == after_count == 1, {"before": before_count, "after": after_count})

    def source_update_and_tombstone(self) -> None:
        phase = "PHASE 9 / VERSIONING + PHASE 7 UPDATE"
        fixture = self.fixture_root / "service_update.json"
        initial = {
            "records": [{
                "external_id": "browser-catalog-pricing-api",
                "record_type": "service_record",
                "observed_at": "2026-10-16T16:00:00+05:30",
                "system": "Pricing API",
                "system_canonical_id": "SYS-PRICING-API",
                "owner_team": "Pricing Platform",
                "team_canonical_id": "TEAM-PRICING",
                "depends_on": "Pricing Database",
                "dependency_canonical_id": "SYS-PRICING-DB",
                "valid_from": "2026-01-01T00:00:00+05:30",
            }]
        }
        fixture.write_text(json.dumps(initial, indent=2), encoding="utf-8")

        cfg = {c.source_type: c for c in fixture_source_configs(ROOT)}["internal_api"].model_copy(deep=True)
        cfg.id = "DS-P9-BROWSER-UPDATE"
        cfg.source_instance = "browser-service-catalog"
        cfg.fixture_path = str(fixture)
        cfg.trust_class = TrustClass.AUTHORITATIVE
        cfg.authoritative_domains = ["service ownership", "dependencies"]
        cfg.settings["auto_validate_ownership"] = True
        cfg.settings["auto_validate_dependencies"] = True
        registry = SourceRegistry(self.client)
        registry.register(cfg, persist=False)
        pipeline = IngestionPipeline(self.client, registry=registry, artifact_store=LocalArtifactStore(self.artifact_root))

        first = pipeline.sync(cfg.id, mode="full", max_records=10)
        self.require(phase, "Authoritative baseline source version ingests", first.status.value == "SUCCEEDED", first.model_dump(mode="json"), critical=True)

        updated = json.loads(fixture.read_text(encoding="utf-8"))
        updated["records"][0]["owner_team"] = "Pricing Platform Next"
        updated["records"][0].pop("team_canonical_id", None)
        updated["records"][0]["observed_at"] = "2026-10-16T16:30:00+05:30"
        updated["records"][0]["valid_from"] = "2026-10-16T16:30:00+05:30"
        fixture.write_text(json.dumps(updated, indent=2), encoding="utf-8")

        second = pipeline.sync(cfg.id, mode="full", max_records=10)
        self.require(phase, "Changed source version ingests as a new immutable record", second.status.value == "SUCCEEDED" and second.written >= 1, second.model_dump(mode="json"), critical=True)

        snapshot = self.snapshot()
        version_records = [n for n in snapshot.nodes.values() if has_label(n, "SourceRecord") and n.get("source_id") == cfg.id and n.get("source_entity_id") == "browser-catalog-pricing-api" and n.get("record_type") != "identity_projection"]
        supersedes = []
        for n in version_records:
            supersedes.extend([(n["id"], e.target) for e in snapshot.edges_from(str(n["id"]), {"SUPERSEDES"})])
        self.require(phase, "Changed checksum creates immutable SourceRecord version chain", len(version_records) >= 2 and bool(supersedes), {"versions": [n.get("id") for n in version_records], "supersedes": supersedes})

        current_owner = ResponsibilityRoutingService(self.client).find_owner("SYS-PRICING-API")
        current_names = [x["actor"].get("name") for x in current_owner.get("owners", [])]
        self.require(phase, "Authoritative ownership update changes current Phase 3 routing", "Pricing Platform Next" in current_names, current_owner)

        historical = ResponsibilityRoutingService(self.client).find_owner("SYS-PRICING-API", as_of="2026-10-16T16:15:00+05:30")
        historical_ids = [x["actor"].get("id") for x in historical.get("owners", [])]
        self.require(phase, "Historical routing preserves previous owner before update", "TEAM-PRICING" in historical_ids, historical)

        old_edges = [e for e in self.snapshot().edges_from("TEAM-PRICING", {"OWNS"}) if e.target == "SYS-PRICING-API"]
        self.require(phase, "Old ownership is temporally closed instead of deleted", any(e.properties.get("valid_until") for e in old_edges), [e.properties for e in old_edges])

        # Third version is a tombstone. It must create deletion evidence, not delete canonical truth nodes.
        tombstone_payload = {
            "records": [{
                "external_id": "browser-catalog-pricing-api",
                "record_type": "service_record",
                "observed_at": "2026-10-16T17:00:00+05:30",
                "deleted": True,
            }]
        }
        fixture.write_text(json.dumps(tombstone_payload, indent=2), encoding="utf-8")
        third = pipeline.sync(cfg.id, mode="full", max_records=10)
        self.require(phase, "Source tombstone ingests successfully", third.status.value == "SUCCEEDED", third.model_dump(mode="json"), critical=True)
        after = self.snapshot()
        tombstones = [n for n in after.nodes.values() if has_label(n, "Evidence") and n.get("source_ref_id") == cfg.id and n.get("evidence_type") == "source_tombstone"]
        self.require(phase, "Tombstone creates deletion Evidence", bool(tombstones), [(n.get("id"), n.get("observed_at")) for n in tombstones])
        self.require(phase, "Tombstone does not hard-delete canonical Pricing API", after.node("SYS-PRICING-API") is not None, after.node("SYS-PRICING-API"))
        self.custom_ids["update_source_id"] = cfg.id

    def events_and_browser_outputs(self) -> None:
        phase = "PHASE 9 / EVENTS + BROWSER"
        snapshot = self.snapshot()
        events = [n for n in snapshot.nodes.values() if has_label(n, "Event") and str(n.get("event_type") or "").startswith("INGESTION_")]
        event_types = {n.get("event_type") for n in events}
        self.require(phase, "Ingestion run start events are durable", "INGESTION_RUN_STARTED" in event_types, sorted(x for x in event_types if x))
        self.require(phase, "Ingestion run completion events are durable", "INGESTION_RUN_COMPLETED" in event_types, sorted(x for x in event_types if x))

        self.write_browser_queries()
        self.write_report()

    def write_browser_queries(self) -> Path:
        path = ROOT / f"phase9_browser_queries_{self.graph_name}.cypher"
        qid = self.custom_ids.get("quarantine_id", "")
        update_source = self.custom_ids.get("update_source_id", "DS-P9-BROWSER-UPDATE")
        text = f"""// GraphHacks Phase 9 browser acceptance queries
// Select FalkorDB graph: {self.graph_name}
// Generated by verify_phase9_browser.py

// 1. Data sources and cursor state
MATCH (s:Entity:DataSource {{tenant_id:'{self.settings.tenant_id}'}})
RETURN s.id, s.name, s.source_type, s.trust_class, s.last_successful_cursor, s.last_sync_at
ORDER BY s.id;

// 2. Ingestion runs -> SourceRecords
MATCH (r:Entity:IngestionRun {{tenant_id:'{self.settings.tenant_id}'}})-[:INGESTED]->(sr:Entity:SourceRecord)
RETURN r.id, r.source_id, r.status, sr.id, sr.record_type, sr.external_id, sr.checksum
ORDER BY r.started_at, sr.external_id;

// 3. Multi-source identity collapse for Neha
MATCH (x:Entity:ExternalIdentity {{tenant_id:'{self.settings.tenant_id}'}})-[:RESOLVES_TO]->(p:Entity:Person)
WHERE toLower(coalesce(x.email,'')) = 'neha.verma@northstar.example'
RETURN p.id, p.name, p.email, collect({{source:x.source_type, external_id:x.external_id}}) AS identities;

// 4. SourceRecord -> canonical lineage
MATCH (sr:Entity:SourceRecord {{tenant_id:'{self.settings.tenant_id}'}})-[:NORMALIZED_TO]->(e:Entity)
WHERE sr.record_type <> 'identity_projection'
RETURN sr.id, sr.source_type, sr.external_id, labels(e), e.id, e.name
ORDER BY sr.source_type, sr.external_id
LIMIT 150;

// 5. Imported ownership/dependencies with relationship provenance
MATCH (a:Entity)-[r:OWNS|DEPENDS_ON]->(b:Entity)
WHERE a.tenant_id='{self.settings.tenant_id}' AND r.source_record_ids_csv IS NOT NULL
RETURN a.id, type(r), b.id, r.valid_from, r.valid_until, r.source_ref_id, r.source_record_ids_csv, r.mapping_rule
ORDER BY a.id, type(r), b.id;

// 6. Slack assertions must remain unverified
MATCH (c:Entity:Claim {{tenant_id:'{self.settings.tenant_id}'}})
WHERE c.source_ref_id='DS-ING-SLACK'
RETURN c.id, c.statement, c.status, c.confidence, c.source_ref_id;

// 7. Imported policy requirements
MATCH (p:Entity:Policy {{tenant_id:'{self.settings.tenant_id}', id:'POL-DB-04'}})-[r:REQUIRES]->(req:Entity)
RETURN p.id, p.version, type(r), req.id, req.name, req.status;

// 8. Evidence -> external Artifact lineage
MATCH (e:Entity:Evidence {{tenant_id:'{self.settings.tenant_id}'}})-[:DERIVED_FROM]->(a:Entity:Artifact)
RETURN e.id, e.evidence_type, a.id, a.uri, a.sha256, a.size_bytes, a.mime_type;

// 9. Quarantine records
MATCH (q:Entity:IngestionQuarantineRecord {{tenant_id:'{self.settings.tenant_id}'}})
RETURN q.id, q.status, q.reason, q.source_record_id, q.resolved_to, q.reviewer_ref, q.candidates
ORDER BY q.created_at;

// 10. Acceptance quarantine record specifically
MATCH (q:Entity:IngestionQuarantineRecord {{tenant_id:'{self.settings.tenant_id}', id:'{qid}'}})
RETURN q;

// 11. Source version / SUPERSEDES history
MATCH (new:Entity:SourceRecord {{tenant_id:'{self.settings.tenant_id}'}})-[:SUPERSEDES]->(old:Entity:SourceRecord)
WHERE new.source_id='{update_source}'
RETURN new.source_key, old.id, old.checksum, old.observed_at, new.id, new.checksum, new.observed_at, new.deleted
ORDER BY new.observed_at;

// 12. Tombstone evidence must point at canonical objects without deleting them
MATCH (e:Entity:Evidence {{tenant_id:'{self.settings.tenant_id}', source_ref_id:'{update_source}', evidence_type:'source_tombstone'}})-[:ABOUT]->(x:Entity)
RETURN e.id, e.observed_at, x.id, labels(x), x.name;

// 13. Current/historical ownership intervals for Pricing API
MATCH (owner:Entity)-[r:OWNS]->(s:Entity:System {{tenant_id:'{self.settings.tenant_id}', id:'SYS-PRICING-API'}})
RETURN owner.id, owner.name, r.valid_from, r.valid_until, r.source_ref_id, r.source_record_ids_csv
ORDER BY r.valid_from;

// 14. Ingestion event ledger
MATCH (e:Entity:Event {{tenant_id:'{self.settings.tenant_id}'}})
WHERE e.event_type STARTS WITH 'INGESTION_' OR e.event_type IN ['SOURCE_RECORD_INGESTED','SOURCE_RECORD_UPDATED','ENTITY_RESOLVED','ENTITY_RESOLUTION_QUARANTINED','ARTIFACT_STORED','EXTERNAL_FACT_WRITTEN','EXTERNAL_FACT_SUPERSEDED']
RETURN e.id, e.event_type, e.occurred_at, e.summary
ORDER BY e.occurred_at
LIMIT 200;

// 15. Imported incident/event graph used by existing process reconstruction
MATCH p=(inc:Entity:Incident {{tenant_id:'{self.settings.tenant_id}', id:'INC-001'}})-[*1..3]-(x:Entity)
RETURN p
LIMIT 80;
"""
        path.write_text(text, encoding="utf-8")
        return path

    def write_report(self, critical_error: str | None = None) -> Path:
        path = ROOT / f"phase9_acceptance_report_{self.graph_name}.json"
        payload = {
            "graph": self.graph_name,
            "tenant": self.settings.tenant_id,
            "host": self.settings.falkordb_host,
            "port": self.settings.falkordb_port,
            "artifact_root": str(self.artifact_root),
            "generated_at": datetime.now().astimezone().isoformat(),
            "passed": sum(1 for x in self.results if x["ok"]),
            "failed": sum(1 for x in self.results if not x["ok"]),
            "critical_error": critical_error,
            "results": self.results,
        }
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    def run(self) -> int:
        critical_error = None
        try:
            self.setup()
            self.api_and_ingestion()
            self.ontology_resolution_provenance_artifacts()
            self.existing_capabilities()
            self.idempotency_and_incremental()
            self.quarantine()
            self.source_update_and_tombstone()
            self.events_and_browser_outputs()
        except Exception as exc:
            critical_error = f"{type(exc).__name__}: {exc}"
            print("\n[ABORTED] A critical acceptance check failed.")
            print(critical_error)
            import traceback
            traceback.print_exc()
        finally:
            report_path = self.write_report(critical_error)
            query_path = self.write_browser_queries()
            passed = sum(1 for x in self.results if x["ok"])
            failed = sum(1 for x in self.results if not x["ok"])
            print("\n" + "=" * 78)
            print(f"RESULT: {passed} passed, {failed} failed")
            if critical_error:
                print(f"Critical error: {critical_error}")
            print(f"JSON report   : {report_path}")
            print(f"Browser Cypher: {query_path}")
            print(f"Artifact root : {self.artifact_root}")
            print(f"FalkorDB graph: {self.graph_name}")
            if self.cleanup:
                try:
                    safe_delete_graph(self.client)
                    shutil.rmtree(self.artifact_root, ignore_errors=True)
                    print("Temporary graph/artifacts cleaned up (--cleanup).")
                except Exception as exc:
                    print(f"[WARN] Cleanup failed: {exc}")
            else:
                print("Temporary graph kept for browser inspection.")
                print("Open: http://localhost:3000")
                print(f"Select graph: {self.graph_name}")
            print("=" * 78)

        return 0 if not critical_error and not self.failures else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="GraphHacks Phase 9 live/browser acceptance runner")
    parser.add_argument("--cleanup", action="store_true", help="Delete acceptance graph and artifacts after the run")
    parser.add_argument("--graph", help="Use an explicit isolated graph name")
    args = parser.parse_args()
    graph_name = args.graph or f"accept_p9_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    runner = Runner(graph_name=graph_name, cleanup=args.cleanup)
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
