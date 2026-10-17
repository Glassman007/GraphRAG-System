from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.ingestion.models import ArtifactMetadata, SourceConfig, SourceRecordEnvelope
from backend.app.services.phase4_graph import GraphSnapshot
from backend.app.services.phase6_utils import now_iso, stable_id


class IngestionProvenanceService:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    @staticmethod
    def source_record_id(source_id: str, record: SourceRecordEnvelope, *, tenant_id: str | None = None) -> str:
        parts = ([tenant_id] if tenant_id else []) + [source_id, record.external_id, record.checksum]
        return stable_id("SRCREC-ING-", *parts, length=20)

    @staticmethod
    def source_key(source_id: str, external_id: str) -> str:
        return f"{source_id}:{external_id}"

    def create_run(self, config: SourceConfig, *, cursor_start: str | None, run_id: str | None = None) -> str:
        at = now_iso()
        run_id = run_id or stable_id("INGRUN-", config.id, at, cursor_start or "START", length=20)
        upsert_node(self.client, "IngestionRun", run_id, {
            "name": f"{config.name} ingestion {at}",
            # Keep volatile run/audit nodes out of source-entity identity sets.
            # The source is canonically represented by DERIVED_FROM plus this
            # provenance reference; API serializers derive `source_id`.
            "source_ref_id": config.id,
            "status": "RUNNING",
            "started_at": at,
            "created_at": at,
            "cursor_start": cursor_start,
            "adapter_version": config.adapter_version,
            "mapping_version": config.mapping_version,
            "records_fetched": 0,
            "records_normalized": 0,
            "records_written": 0,
            "records_quarantined": 0,
            "records_failed": 0,
            "artifacts_stored": 0,
        })
        upsert_relationship(self.client, run_id, "DERIVED_FROM", config.id, {"valid_from": at, "confidence": 1.0, "source_ref_id": config.id})
        return run_id

    def complete_run(self, run_id: str, *, status: str, cursor_end: str | None, counters: dict[str, int]) -> None:
        upsert_node(self.client, "IngestionRun", run_id, {
            "status": status,
            "completed_at": now_iso(),
            "cursor_end": cursor_end,
            **counters,
        })

    def persist_source_record(self, config: SourceConfig, run_id: str, record: SourceRecordEnvelope, *, candidate_label: str | None = None, identity: dict[str, Any] | None = None) -> tuple[str, bool]:
        source_record_id = self.source_record_id(config.id, record, tenant_id=self.client.settings.tenant_id)
        source_key = self.source_key(config.id, record.external_id)
        snapshot = GraphSnapshot.load(self.client)
        existed = snapshot.node(source_record_id) is not None
        previous = [n for n in snapshot.nodes.values() if "SourceRecord" in set(n.get("_labels") or []) and n.get("source_key") == source_key and n.get("id") != source_record_id]
        props = {
            "name": f"{config.source_type}:{record.record_type}:{record.external_id}",
            "source_entity_id": record.external_id,
            "source_kind": config.source_type,
            "source_type": config.source_type,
            "source_instance": config.source_instance,
            "source_id": config.id,
            "source_key": source_key,
            "record_type": record.record_type,
            "observed_at": record.observed_at,
            "fetched_at": record.fetched_at,
            "source_updated_at": record.source_updated_at,
            "version": record.version,
            "etag": record.etag,
            "canonical_source_uri": record.canonical_source_uri,
            "checksum": record.checksum,
            "deleted": record.deleted,
            "schema_version": record.schema_version,
            "status": "TOMBSTONED" if record.deleted else "ACTIVE",
            "raw_metadata": str(record.raw_metadata),
            "created_at": record.fetched_at,
            "candidate_label": candidate_label,
            "adapter_version": config.adapter_version,
            "mapping_version": config.mapping_version,
            "trust_class": config.trust_class.value,
            "authoritative_domains": list(config.authoritative_domains),
            **(identity or {}),
        }
        upsert_node(self.client, "SourceRecord", source_record_id, props)
        upsert_relationship(self.client, source_record_id, "DERIVED_FROM", config.id, {"valid_from": record.fetched_at, "confidence": 1.0, "source_ref_id": config.id})
        upsert_relationship(self.client, run_id, "INGESTED", source_record_id, {"valid_from": record.fetched_at, "confidence": 1.0, "source_ref_id": config.id})
        if previous:
            # Updated source records create a version chain; old SourceRecords remain queryable.
            prev = sorted(previous, key=lambda x: str(x.get("source_updated_at") or x.get("fetched_at") or ""))[-1]
            upsert_relationship(self.client, source_record_id, "SUPERSEDES", str(prev["id"]), {"valid_from": record.source_updated_at or record.fetched_at, "confidence": 1.0, "source_ref_id": config.id})
        return source_record_id, existed

    def external_identity(self, config: SourceConfig, source_record_id: str, *, entity_key: str, identity: dict[str, Any]) -> str:
        external_id = str(identity.get("external_id") or identity.get("username") or identity.get("email") or entity_key)
        identity_id = stable_id("EXTID-", self.client.settings.tenant_id, config.id, external_id, entity_key, length=20)
        at = now_iso()
        upsert_node(self.client, "ExternalIdentity", identity_id, {
            "name": identity.get("name") or identity.get("email") or identity.get("username") or external_id,
            "source_type": config.source_type,
            "source_instance": config.source_instance,
            "external_id": external_id,
            "username": identity.get("username"),
            "email": identity.get("email"),
            "display_name": identity.get("name"),
            "first_seen_at": at,
            "last_seen_at": at,
            "created_at": at,
        })
        upsert_relationship(self.client, source_record_id, "REFERENCES", identity_id, {"valid_from": at, "confidence": 1.0, "source_ref_id": config.id})
        return identity_id

    def link_resolution(self, *, source_record_id: str, external_identity_id: str | None, canonical_id: str, confidence: float, source_id: str, mapping_rule: str) -> None:
        at = now_iso()
        upsert_relationship(self.client, source_record_id, "NORMALIZED_TO", canonical_id, {
            "edge_id": stable_id("ING-NORM-", self.client.settings.tenant_id, source_record_id, canonical_id, mapping_rule, length=24),
            "valid_from": at, "confidence": confidence, "source_ref_id": source_id, "mapping_rule": mapping_rule,
        })
        if external_identity_id:
            upsert_relationship(self.client, external_identity_id, "RESOLVES_TO", canonical_id, {
                "edge_id": stable_id("ING-RESOLVE-", self.client.settings.tenant_id, external_identity_id, canonical_id, length=24),
                "valid_from": at, "confidence": confidence, "source_ref_id": source_id,
            })

    def link_artifact(self, source_record_id: str, artifact: ArtifactMetadata, *, source_id: str) -> None:
        upsert_node(self.client, "Artifact", artifact.artifact_id, artifact.model_dump(mode="json"))
        upsert_relationship(self.client, source_record_id, "REFERENCES", artifact.artifact_id, {"valid_from": artifact.created_at, "confidence": 1.0, "source_ref_id": source_id})
