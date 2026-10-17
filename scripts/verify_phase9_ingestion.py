from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> int:
    graph_name = f"phase9_accept_{uuid.uuid4().hex[:10]}"
    settings = Settings(
        falkordb_host=os.getenv("FALKORDB_HOST", "localhost"),
        falkordb_port=int(os.getenv("FALKORDB_PORT", "6379")),
        falkordb_graph=graph_name,
        falkordb_password=os.getenv("FALKORDB_PASSWORD") or None,
        tenant_id=os.getenv("GRAPH_TENANT_ID", "northstar"),
    )
    client = FalkorGraphClient(settings)
    client.delete_graph()
    apply_schema(client)
    temp_root = Path(tempfile.mkdtemp(prefix="graphhacks-phase9-"))
    print(f"Isolated FalkorDB graph: {graph_name}")
    print("NOTE: company_brain is not modified.")
    try:
        registry = SourceRegistry(client)
        configs = {cfg.source_type: cfg for cfg in fixture_source_configs(ROOT)}
        for source_type in ("github", "jira", "slack", "documents", "telemetry", "internal_api"):
            cfg = configs[source_type].model_copy(deep=True)
            cfg.id = f"DS-P9-VERIFY-{source_type.upper()}"
            cfg.source_instance = f"verify-{source_type}"
            registry.register(cfg, persist=False)
        pipeline = IngestionPipeline(client, registry=registry, artifact_store=LocalArtifactStore(temp_root / "artifacts"))

        for cfg in registry.configs():
            report = pipeline.sync(cfg.id, mode="full", max_records=100)
            check(report.status.value == "SUCCEEDED", f"{cfg.source_type} fixture ingestion succeeds")

        snapshot = GraphSnapshot.load(client)
        neha = [n for n in snapshot.nodes.values() if has_label(n, "Person") and str(n.get("email") or "").lower() == "neha.verma@northstar.example"]
        check(len(neha) == 1, "GitHub/Jira/Slack identity resolves to one canonical Neha")
        neha_ext = [n for n in snapshot.nodes.values() if has_label(n, "ExternalIdentity") and str(n.get("email") or "").lower() == "neha.verma@northstar.example"]
        check(len(neha_ext) >= 3, "canonical Neha retains multiple ExternalIdentity nodes")

        raw_records = [n for n in snapshot.nodes.values() if has_label(n, "SourceRecord") and n.get("record_type") != "identity_projection"]
        check(raw_records and all(snapshot.edges_from(str(n["id"]), {"DERIVED_FROM"}) for n in raw_records), "every raw SourceRecord has source provenance")
        check(all(snapshot.edges_from(str(n["id"]), {"NORMALIZED_TO"}) or n.get("deleted") for n in raw_records), "normalized SourceRecords retain canonical lineage")
        check(any(has_label(n, "Artifact") for n in snapshot.nodes.values()), "large/source artifacts are externalized with lightweight graph references")

        owner = ResponsibilityRoutingService(client).find_owner("SYS-PRICING-API")
        check(owner and owner["owners"] and owner["owners"][0]["actor"]["id"] == "TEAM-PRICING", "existing Phase 3 routing consumes imported ownership")

        blast = BlastRadiusService(client).analyze("SYS-PRICING-DB")
        impacted = {x["system"]["id"] for x in blast["downstream_dependents"]}
        check("SYS-CHECKOUT" in impacted, "existing Phase 4 blast radius consumes imported dependencies")

        investigation = RelationalInvestigationService(client).investigate_incident("INC-001")
        check(bool(investigation and investigation["candidate_paths"]), "existing relational investigation consumes imported evidence/dependency/change graph")

        process = OrganizationalProcessReconstructionService(client).reconstruct("INC-001")
        check(bool(process and process["steps"]), "existing Phase 8 process reconstruction consumes imported events")
        drift = PolicyDriftService(client).analyze("INC-001", policy_id="POL-DB-04")
        classes = {x["classification"] for x in drift["drift"]}
        check("MISSING_REQUIRED_STEP" in classes, "existing Phase 8 policy drift consumes imported policy requirements")

        canonical_before = {nid for nid, n in snapshot.nodes.items() if not any(has_label(n, x) for x in ("IngestionRun", "Event"))}
        for cfg in registry.configs():
            pipeline.sync(cfg.id, mode="full", max_records=100)
        snapshot2 = GraphSnapshot.load(client)
        canonical_after = {nid for nid, n in snapshot2.nodes.items() if not any(has_label(n, x) for x in ("IngestionRun", "Event"))}
        check(canonical_before == canonical_after, "full re-ingestion does not duplicate canonical/source/artifact state")

        # Authoritative source update: same external record, changed owner. This must flow through Phase 7 temporal promotion.
        original = Path(configs["internal_api"].fixture_path)
        update_fixture = temp_root / "internal-update.json"
        shutil.copyfile(original, update_fixture)
        payload = json.loads(update_fixture.read_text(encoding="utf-8"))
        payload["records"][0]["owner_team"] = "Pricing Platform Next"
        payload["records"][0].pop("team_canonical_id", None)
        payload["records"][0]["observed_at"] = "2026-10-16T16:30:00+05:30"
        payload["records"][0]["valid_from"] = "2026-10-16T16:30:00+05:30"
        update_fixture.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        update_cfg = SourceConfig(id="DS-P9-VERIFY-UPDATE", source_type="internal_api", name="Update Catalog", source_instance="verify-update", trust_class=TrustClass.AUTHORITATIVE, authoritative_domains=["service ownership", "dependencies"], fixture_path=str(update_fixture))
        update_registry = SourceRegistry(client); update_registry.register(update_cfg, persist=False)
        update_pipeline = IngestionPipeline(client, registry=update_registry, artifact_store=LocalArtifactStore(temp_root / "artifacts"))
        update_report = update_pipeline.sync(update_cfg.id, mode="full", max_records=10)
        check(update_report.status.value == "SUCCEEDED", "authoritative source update ingests successfully")
        new_owner = ResponsibilityRoutingService(client).find_owner("SYS-PRICING-API")
        check(new_owner and new_owner["owners"][0]["actor"]["name"] == "Pricing Platform Next", "authoritative ownership update changes current Phase 3 routing through Phase 7 promotion")

        print("\nPHASE 9 ACCEPTANCE: PASS")
        return 0
    except Exception as exc:
        print(f"\nPHASE 9 ACCEPTANCE: FAIL\n{type(exc).__name__}: {exc}")
        return 1
    finally:
        client.delete_graph()
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
