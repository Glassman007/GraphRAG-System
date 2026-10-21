from __future__ import annotations

import ast
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node
from backend.app.ingestion.artifacts.local import LocalArtifactStore
from backend.app.ingestion.adapters.github import parse_repository
from backend.app.ingestion.credentials import CredentialStore, default_credential_store
from backend.app.ingestion.models import SourceConfig, TrustClass
from backend.app.ingestion.pipeline import IngestionPipeline
from backend.app.ingestion.registry import ADAPTERS, SourceRegistry
from backend.app.ingestion.resolution.service import IngestionEntityResolutionService
from backend.app.retrieval.indexing import RetrievalIndexer
from backend.app.retrieval.lexical import BM25LexicalIndex
from backend.app.retrieval.vector import LocalVectorIndex
from backend.app.services.event_ledger_service import EventLedgerService
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase6_utils import now_iso, stable_id


@dataclass(frozen=True)
class ConnectorDefinition:
    connector_type: str
    display_name: str
    description: str
    category: str
    supported_auth_methods: tuple[str, ...]
    supported_scopes: tuple[str, ...]
    supports_incremental_sync: bool = True
    supports_test_connection: bool = True
    supports_preview: bool = True
    supports_mapping_preview: bool = True
    supports_deletion: bool = True
    supports_live_mode: bool = True
    supports_fixture_mode: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "supported_auth_methods": list(self.supported_auth_methods), "supported_scopes": list(self.supported_scopes)}


CONNECTORS: dict[str, ConnectorDefinition] = {
    "github": ConnectorDefinition("github", "GitHub", "Repositories and engineering change history.", "Engineering", ("none", "api_token", "app"), ("organization", "repositories", "files")),
    "jira": ConnectorDefinition("jira", "Jira", "Projects, issues, assignees and delivery work.", "Work tracking", ("api_token", "username_password"), ("projects",)),
    "slack": ConnectorDefinition("slack", "Slack", "Selected engineering channels and incident conversations.", "Communication", ("api_token",), ("channels",)),
    "teams": ConnectorDefinition("teams", "Microsoft Teams", "Selected Teams conversations through the existing adapter boundary.", "Communication", ("service_credential",), ("teams", "channels"), supports_live_mode=False),
    "database": ConnectorDefinition("database", "Database", "Read-only registered relational views/tables.", "Structured data", ("service_credential", "username_password"), ("registered_views",)),
    "internal_api": ConnectorDefinition("internal_api", "Internal API", "Server-registered internal JSON API source.", "Structured data", ("api_token", "service_credential"), ("registered_endpoint",)),
    "documents": ConnectorDefinition("documents", "Documents", "Document collections used as organizational evidence.", "Knowledge", ("service_credential", "none"), ("collections",), supports_live_mode=False),
    "telemetry": ConnectorDefinition("telemetry", "Telemetry", "Runtime observations, logs and operational telemetry.", "Operations", ("api_token", "service_credential", "none"), ("services", "namespaces"), supports_live_mode=False),
}

MAPPING_EXAMPLES: dict[str, list[dict[str, str]]] = {
    "github": [{"external": "Repository", "canonical": "System", "meaning": "A repository is interpreted as an engineering system."}, {"external": "Repository owner", "canonical": "Team", "meaning": "Repository ownership contributes team responsibility evidence."}],
    "jira": [{"external": "Jira Issue", "canonical": "Work Item", "meaning": "Issues become organizational work items/tasks where the mapping supports it."}, {"external": "Jira Project", "canonical": "Project", "meaning": "Projects map to canonical projects."}, {"external": "Assignee", "canonical": "Person", "meaning": "Assignees are resolved to canonical people."}],
    "slack": [{"external": "Message", "canonical": "Evidence / Event context", "meaning": "Messages remain source evidence unless promoted by existing validation rules."}],
    "teams": [{"external": "Message", "canonical": "Evidence / Event context", "meaning": "Teams messages remain provenance-linked source material."}],
    "database": [{"external": "Registered row", "canonical": "Mapped canonical entity", "meaning": "Rows use the server-approved mapping profile; arbitrary SQL is not accepted."}],
    "internal_api": [{"external": "Registered API record", "canonical": "Mapped canonical entity", "meaning": "Only server-registered endpoints and mappings are used."}],
    "documents": [{"external": "Document", "canonical": "Document / Evidence", "meaning": "Documents become provenance-linked knowledge artifacts."}],
    "telemetry": [{"external": "Telemetry record", "canonical": "Evidence / Event", "meaning": "Runtime records become observations with source provenance."}],
}


def _parse_jsonish(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    for fn in (json.loads, ast.literal_eval):
        try:
            parsed = fn(str(value))
            if isinstance(parsed, type(default)):
                return parsed
        except Exception:
            pass
    return default


class SourceControlService:
    def __init__(self, client: FalkorGraphClient, *, credential_store: CredentialStore | None = None, root: Path | None = None):
        self.client = client
        self.credentials = credential_store or default_credential_store()
        self.root = root or Path(__file__).resolve().parents[3]
        self.events = EventLedgerService(client)

    def list_connectors(self) -> list[dict[str, Any]]:
        return [CONNECTORS[k].as_dict() for k in sorted(CONNECTORS)]

    def connector(self, connector_type: str) -> dict[str, Any]:
        item = CONNECTORS.get(connector_type.lower())
        if not item:
            raise ValueError("Unsupported connector")
        return {**item.as_dict(), "mapping_preview": MAPPING_EXAMPLES.get(item.connector_type, [])}

    def _fixture_path(self, connector_type: str) -> str:
        folder = {"documents": "docs", "internal_api": "internal_api"}.get(connector_type, connector_type)
        path = self.root / "backend" / "tests" / "fixtures" / "ingestion" / folder / "records.json"
        if not path.exists():
            raise ValueError(f"No fixture pack exists for connector {connector_type}")
        return str(path)

    def _node_to_config(self, node: dict[str, Any]) -> SourceConfig:
        connector_type = str(node.get("connector_type") or node.get("source_type") or "").lower()
        fixture_mode = str(node.get("connection_mode") or "fixture").lower() == "fixture"
        connection = _parse_jsonish(node.get("connection_config_json"), {})
        scope = _parse_jsonish(node.get("scope_config_json"), {})
        settings = dict(connection.get("settings") or {})
        settings.update({k: v for k, v in scope.items() if k not in settings})
        selected = list(scope.get("selected") or [])
        if connector_type == "slack" and selected and not settings.get("channel"):
            settings["channel"] = selected[0]
        return SourceConfig(
            id=str(node["id"]), source_type=connector_type, name=str(node.get("display_name") or node.get("name") or node["id"]),
            source_instance=str(node.get("source_instance") or node["id"]), base_url=connection.get("base_url"),
            trust_class=TrustClass(str(node.get("trust_class") or "STANDARD")), authoritative_domains=list(_parse_jsonish(node.get("authoritative_domains"), [])),
            enabled=bool(node.get("enabled", True)), sync_mode=str(node.get("sync_mode") or "incremental"),
            adapter_version=str(node.get("adapter_version") or f"{connector_type}-v1"), mapping_version=str(node.get("mapping_version") or "phase13-v1"),
            fixture_path=self._fixture_path(connector_type) if fixture_mode else None, settings=settings,
            credential_ref=node.get("credential_ref"), connection_config=connection, scope_config=scope,
            mapping_profile=str(node.get("mapping_profile") or f"{connector_type}-default-v1"),
            expected_sync_interval_minutes=int(node.get("expected_sync_interval_minutes") or 0) or None,
        )

    def _source_node(self, source_id: str) -> dict[str, Any]:
        node = GraphSnapshot.load(self.client).node(source_id)
        if not has_label(node, "DataSource"):
            raise KeyError(source_id)
        return node or {}

    def _public_source(self, node: dict[str, Any], snapshot: GraphSnapshot | None = None) -> dict[str, Any]:
        snapshot = snapshot or GraphSnapshot.load(self.client)
        sid = str(node["id"])
        runs = [n for n in snapshot.nodes.values() if has_label(n, "IngestionRun") and (n.get("source_ref_id") == sid or any(e.target == sid for e in snapshot.edges_from(str(n.get("id")), {"DERIVED_FROM"})))]
        runs.sort(key=lambda x: str(x.get("started_at") or ""), reverse=True)
        latest = runs[0] if runs else None
        quarantine = [q for q in snapshot.nodes.values() if has_label(q, "IngestionQuarantineRecord") and q.get("source_ref_id") == sid and q.get("status") == "OPEN"]
        source_records = [n for n in snapshot.nodes.values() if has_label(n, "SourceRecord") and n.get("source_id") == sid and n.get("record_type") != "identity_projection"]
        bounded_records = source_records[:5000]
        entity_ids:set[str]=set(); artifact_ids:set[str]=set()
        for record in bounded_records:
            rid=str(record.get("id"))
            entity_ids.update(e.target for e in snapshot.edges_from(rid,{"NORMALIZED_TO"}))
            artifact_ids.update(e.target for e in snapshot.edges_from(rid,{"REFERENCES"}) if has_label(snapshot.node(e.target),"Artifact"))
        source_relationships=sum(1 for e in snapshot.edges if e.properties.get("source_ref_id")==sid)
        claim_count=sum(1 for eid in entity_ids if has_label(snapshot.node(eid),"Claim"))
        evidence_ids={n.get("id") for n in snapshot.nodes.values() if has_label(n,"Evidence") and (n.get("source_id")==sid or n.get("source_ref_id")==sid)}
        learned_labels = {"System": "systems", "Team": "teams", "Person": "people", "Project": "projects", "Policy": "policies"}
        learned = {friendly: 0 for friendly in learned_labels.values()}
        for eid in entity_ids:
            entity = snapshot.node(eid)
            for label, friendly in learned_labels.items():
                if has_label(entity, label):
                    learned[friendly] += 1
        learned["unresolved_identities"] = len(quarantine)
        expected = int(node.get("expected_sync_interval_minutes") or 0)
        last_success = node.get("last_successful_sync") or node.get("last_sync_at")
        stale = False
        if expected and last_success:
            try:
                then = datetime.fromisoformat(str(last_success).replace("Z", "+00:00"))
                stale = (datetime.now(timezone.utc) - then.astimezone(timezone.utc)).total_seconds() > expected * 60
            except Exception:
                stale = False
        connection_status = str(node.get("connection_status") or ("NOT_TESTED" if not node.get("last_connection_test") else "UNKNOWN"))
        ingest_status = str(node.get("last_ingestion_status") or (latest or {}).get("status") or "NEVER_RUN")
        lifecycle = "DISABLED" if not bool(node.get("enabled", True)) else ("STALE" if stale else ("AUTH_ERROR" if connection_status == "AUTH_FAILED" else ("SYNC_ERROR" if ingest_status == "FAILED" else ("HEALTHY" if connection_status == "HEALTHY" and ingest_status in {"SUCCEEDED", "SUCCESS"} else str(node.get("lifecycle_status") or "DRAFT")))))
        credential_ref = node.get("credential_ref")
        credential_meta = self.credentials.metadata(str(credential_ref)) if credential_ref and self.credentials.exists(str(credential_ref)) else {"configured": False, "provider": node.get("credential_provider") or self.credentials.provider}
        return {
            "source_id": sid,
            "display_name": node.get("display_name") or node.get("name") or sid,
            "description": node.get("description") or "",
            "connector_type": node.get("connector_type") or node.get("source_type"),
            "enabled": bool(node.get("enabled", True)),
            "lifecycle_status": lifecycle,
            "connection_mode": node.get("connection_mode") or "fixture",
            "trust_class": node.get("trust_class") or "STANDARD",
            "sync_mode": node.get("sync_mode") or "incremental",
            "schedule": node.get("sync_schedule") or "manual",
            "expected_sync_interval_minutes": expected or None,
            "connection": {"status": connection_status, "last_tested_at": node.get("last_connection_test"), "message": node.get("connection_message")},
            "ingestion": {"status": "STALE" if stale and ingest_status in {"SUCCEEDED", "SUCCESS"} else ingest_status, "last_attempted_sync": node.get("last_attempted_sync"), "last_successful_sync": last_success, "latest_run_id": (latest or {}).get("id"), "records_last_run": int((latest or {}).get("records_fetched") or 0), "current_cursor": node.get("last_successful_cursor"), "latest_error": node.get("last_failure")},
            "attention": {"identity_review_count": len(quarantine), "failed_record_count": int((latest or {}).get("records_failed") or 0)},
            "credential": credential_meta,
            "scope": _parse_jsonish(node.get("scope_config_json"), {}),
            "mapping": {"profile": node.get("mapping_profile") or f"{node.get('source_type')}-default-v1", "version": node.get("mapping_version") or "phase13-v1"},
            "impact": {"source_records": len(source_records), "entities": len(entity_ids), "relationships": source_relationships, "claims": claim_count, "evidence": len(evidence_ids), "artifacts": len(artifact_ids), "bounded": len(source_records)>5000},
            "learned": learned,
        }

    def list_sources(self) -> list[dict[str, Any]]:
        snapshot = GraphSnapshot.load(self.client)
        rows = [n for n in snapshot.nodes.values() if has_label(n, "DataSource") and n.get("managed_by") == "phase13-source-control"]
        return [self._public_source(n, snapshot) for n in sorted(rows, key=lambda x: str(x.get("display_name") or x.get("name") or x.get("id")))]

    def get_source(self, source_id: str) -> dict[str, Any]:
        return self._public_source(self._source_node(source_id))

    def _safe_connection_config(self, connector: str, mode: str, raw: dict[str, Any]) -> dict[str, Any]:
        cfg = dict(raw or {})
        settings = dict(cfg.get("settings") or {})
        forbidden = {k for k in settings if any(x in k.lower() for x in ("query","sql","token","password","secret","authorization","private_key"))}
        if forbidden:
            raise ValueError(f"Connection configuration contains forbidden fields: {', '.join(sorted(forbidden))}")
        if connector == "internal_api" and mode == "live":
            key = str(cfg.get("registered_endpoint") or settings.get("registered_endpoint") or "")
            registry = _parse_jsonish(os.getenv("GRAPH_HACKS_REGISTERED_INTERNAL_APIS_JSON"), {})
            if not key or key not in registry:
                raise ValueError("Internal API live sources must use a server-registered endpoint")
            item = dict(registry[key]); cfg = {"base_url": item.get("base_url"), "settings": {"path": item.get("path", "/records"), "registered_endpoint": key}}
        if connector == "database" and mode == "live":
            key = str(cfg.get("registered_view") or settings.get("registered_view") or "")
            registry = _parse_jsonish(os.getenv("GRAPH_HACKS_REGISTERED_DATABASE_VIEWS_JSON"), {})
            if not key or key not in registry:
                raise ValueError("Database live sources must use a server-registered read-only view")
            item = dict(registry[key]); cfg = {"settings": {"query": item.get("query"), "cursor_column": item.get("cursor_column", "id"), "registered_view": key}}
        if mode == "live" and connector == "github" and not cfg.get("base_url"):
            cfg["base_url"] = "https://api.github.com"
        if mode == "live" and connector == "github":
            for key in ("repository", "repository_url", "owner", "repo", "ref", "branch", "files", "anonymous", "max_file_bytes"):
                if key in cfg:
                    settings[key] = cfg.pop(key)
            repository = settings.get("repository") or settings.get("repository_url")
            if not repository and (settings.get("owner") or settings.get("repo")):
                repository = f"{settings.get('owner', '')}/{settings.get('repo', '')}"
            if repository:
                settings["repository"] = "/".join(parse_repository(repository))
                settings.pop("repository_url", None)
            cfg["settings"] = settings
        if mode == "live" and connector == "slack" and not cfg.get("base_url"):
            cfg["base_url"] = "https://slack.com/api"
        base_url = cfg.get("base_url")
        if base_url and connector in {"github","jira","slack"}:
            parsed=urlparse(str(base_url))
            allowed={x.strip().lower() for x in os.getenv("GRAPH_HACKS_ALLOWED_CONNECTOR_HOSTS","api.github.com,github.com,slack.com").split(",") if x.strip()}
            if parsed.scheme not in {"https"} or (parsed.hostname or "").lower() not in allowed:
                raise ValueError("Connector base URL is not in the server allowlist")
        return cfg

    def create_source(self, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        connector = str(payload.get("connector_type") or "").lower()
        self.connector(connector)
        display_name = str(payload.get("display_name") or "").strip()
        if not display_name:
            raise ValueError("display_name is required")
        sid = str(payload.get("source_id") or stable_id("SRC-", self.client.settings.tenant_id, connector, display_name, length=18))
        snap = GraphSnapshot.load(self.client)
        if snap.node(sid):
            raise FileExistsError(sid)
        credentials = dict(payload.get("credentials") or {})
        credential_ref = self.credentials.put(self.client.settings.tenant_id, sid, credentials) if credentials else None
        at = now_iso()
        connection_mode = str(payload.get("connection_mode") or "fixture").lower()
        if connection_mode not in {"fixture", "live"}:
            raise ValueError("connection_mode must be fixture or live")
        if connection_mode == "live" and not CONNECTORS[connector].supports_live_mode:
            raise ValueError(f"{connector} live mode is not implemented")
        safe_connection = self._safe_connection_config(connector, connection_mode, dict(payload.get("connection_config") or {}))
        props = {
            "name": display_name, "display_name": display_name, "description": str(payload.get("description") or ""),
            "source_type": connector, "connector_type": connector, "source_instance": str(payload.get("source_instance") or sid.lower()),
            "managed_by": "phase13-source-control", "enabled": bool(payload.get("enabled", True)), "lifecycle_status": "DRAFT",
            "connection_mode": connection_mode, "credential_ref": credential_ref, "credential_provider": self.credentials.provider, "credential_status": "CONFIGURED" if credential_ref else "NOT_REQUIRED",
            "connection_config_json": json.dumps(safe_connection, sort_keys=True), "scope_config_json": json.dumps(payload.get("scope_config") or {}, sort_keys=True),
            "mapping_profile": str(payload.get("mapping_profile") or f"{connector}-default-v1"), "mapping_version": "phase13-v1",
            "trust_class": str(payload.get("trust_class") or "STANDARD"), "sync_mode": str(payload.get("sync_mode") or "incremental"),
            "sync_schedule": str(payload.get("sync_schedule") or "manual"), "expected_sync_interval_minutes": int(payload.get("expected_sync_interval_minutes") or 0),
            "created_at": at, "updated_at": at,
        }
        upsert_node(self.client, "DataSource", sid, props)
        self.events.record("SOURCE_CREATED", about_ids=[sid], actor_id=actor_id, summary=f"Created source {display_name}", properties={"phase": "13", "connector_type": connector})
        return self.get_source(sid)

    def update_source(self, source_id: str, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        node = self._source_node(source_id)
        allowed: dict[str, Any] = {}
        mapping = {"display_name": "display_name", "description": "description", "enabled": "enabled", "trust_class": "trust_class", "sync_mode": "sync_mode", "sync_schedule": "sync_schedule", "expected_sync_interval_minutes": "expected_sync_interval_minutes", "mapping_profile": "mapping_profile"}
        for incoming, stored in mapping.items():
            if incoming in payload:
                allowed[stored] = payload[incoming]
        if "connection_config" in payload:
            connector=str(node.get("connector_type") or node.get("source_type") or "")
            mode=str(node.get("connection_mode") or "fixture")
            allowed["connection_config_json"] = json.dumps(self._safe_connection_config(connector,mode,payload["connection_config"] or {}), sort_keys=True)
        if "scope_config" in payload:
            allowed["scope_config_json"] = json.dumps(payload["scope_config"] or {}, sort_keys=True)
        if payload.get("credentials") is not None:
            ref = self.credentials.put(self.client.settings.tenant_id, source_id, dict(payload.get("credentials") or {}))
            allowed.update({"credential_ref": ref, "credential_provider": self.credentials.provider, "credential_status": "CONFIGURED"})
        allowed["updated_at"] = now_iso()
        upsert_node(self.client, "DataSource", source_id, allowed)
        self.events.record("SOURCE_UPDATED", about_ids=[source_id], actor_id=actor_id, summary=f"Updated source {node.get('display_name') or source_id}", properties={"phase": "13"})
        if "mapping_profile" in payload and payload.get("mapping_profile") != node.get("mapping_profile"):
            self.events.record("MAPPING_CHANGED", about_ids=[source_id], actor_id=actor_id, summary=f"Changed mapping profile for {source_id}", properties={"phase":"13","mapping_profile":payload.get("mapping_profile")})
        return self.get_source(source_id)

    def set_enabled(self, source_id: str, enabled: bool, *, actor_id: str) -> dict[str, Any]:
        self._source_node(source_id)
        upsert_node(self.client, "DataSource", source_id, {"enabled": enabled, "lifecycle_status": "DRAFT" if enabled else "DISABLED", "updated_at": now_iso()})
        self.events.record("SOURCE_ENABLED" if enabled else "SOURCE_DISABLED", about_ids=[source_id], actor_id=actor_id, summary=("Enabled" if enabled else "Disabled") + f" source {source_id}", properties={"phase": "13"})
        return self.get_source(source_id)

    def delete_configuration(self, source_id: str, *, actor_id: str, remove_credentials: bool = True) -> dict[str, Any]:
        node = self._source_node(source_id)
        ref = node.get("credential_ref")
        if remove_credentials and ref and self.credentials.exists(str(ref)):
            self.credentials.delete(str(ref))
        # Preserve the canonical DataSource/provenance; mark configuration removed instead of deleting history.
        upsert_node(self.client, "DataSource", source_id, {"enabled": False, "lifecycle_status": "DISABLED", "configuration_removed": True, "credential_ref": None, "credential_status": "REMOVED", "updated_at": now_iso()})
        self.events.record("SOURCE_UPDATED", about_ids=[source_id], actor_id=actor_id, summary=f"Removed active configuration for {source_id}; provenance retained", properties={"phase": "13", "configuration_removed": True})
        return {"source_id": source_id, "configuration_removed": True, "historical_provenance_retained": True}

    def _registry(self, source_id: str) -> SourceRegistry:
        node = self._source_node(source_id)
        config = self._node_to_config(node)
        registry = SourceRegistry(self.client)
        registry.register(config, persist=False)
        return registry

    def _pipeline(self, source_id: str) -> IngestionPipeline:
        import os
        source_registry = self._registry(source_id)
        artifact_root = Path(os.getenv("GRAPH_HACKS_ARTIFACT_ROOT") or self.root / ".graphhacks_artifacts")
        retrieval_root = Path(os.getenv("GRAPH_HACKS_RETRIEVAL_ROOT") or self.root / ".graphhacks_retrieval") / self.client.settings.tenant_id
        store = LocalArtifactStore(artifact_root)
        indexer = RetrievalIndexer(self.client, lexical=BM25LexicalIndex(retrieval_root / "lexical.json"), vector=LocalVectorIndex(path=retrieval_root / "vector.json"), artifact_store=store)
        return IngestionPipeline(self.client, registry=source_registry, artifact_store=store, retrieval_indexer=indexer, root=self.root)

    def test_connection(self, source_id: str, *, actor_id: str) -> dict[str, Any]:
        node = self._source_node(source_id)
        config, adapter = self._registry(source_id).get(source_id)
        try:
            health = adapter.health_check()
            ok = bool(health.get("ok"))
            status = "HEALTHY" if ok else str(health.get("status") or ("AUTH_FAILED" if config.credential_ref and not self.credentials.exists(config.credential_ref) else "UNREACHABLE"))
            message = str(health.get("message") or ("Connection test passed." if ok else "Connector could not verify required configuration or reachability."))
        except PermissionError as exc:
            status, message, health = "PERMISSION_ERROR", str(exc), {"ok": False}
        except Exception as exc:
            status, message, health = "UNREACHABLE", str(exc), {"ok": False}
        at = now_iso()
        upsert_node(self.client, "DataSource", source_id, {"connection_status": status, "last_connection_test": at, "connection_message": message, "lifecycle_status": "CONNECTED" if status == "HEALTHY" else "DEGRADED", "updated_at": at})
        self.events.record("CONNECTION_TESTED", about_ids=[source_id], actor_id=actor_id, summary=f"Connection test {status} for {source_id}", properties={"phase": "13", "status": status})
        checks = health.get("checks") or {"authentication": "PASS" if status == "HEALTHY" else "FAIL", "reachability": "PASS" if health.get("ok") else "FAIL", "required_permission": "PASS" if health.get("ok") else "UNKNOWN", "api_access": "PASS" if health.get("ok") else "FAIL"}
        details = {key: health[key] for key in ("repository", "branch", "ref", "commit_sha", "http_status", "retry_after", "rate_limit_reset") if key in health}
        return {"source_id": source_id, "status": status, "checks": checks, "message": message, "live": bool(health.get("live", False)), "fixture": not bool(health.get("live", False)), "connection_details": details}

    def mapping_preview(self, source_id: str) -> dict[str, Any]:
        node = self._source_node(source_id)
        connector = str(node.get("connector_type") or node.get("source_type"))
        return {"source_id": source_id, "mapping_profile": node.get("mapping_profile") or f"{connector}-default-v1", "mapping_version": node.get("mapping_version") or "phase13-v1", "mappings": MAPPING_EXAMPLES.get(connector, [])}

    def preview(self, source_id: str, *, max_records: int = 50) -> dict[str, Any]:
        before = len(GraphSnapshot.load(self.client).nodes)
        report = self._pipeline(source_id).sync(source_id, mode="full", max_records=min(max_records, 100), batch_size=min(max_records, 50), dry_run=True)
        after = len(GraphSnapshot.load(self.client).nodes)
        candidate_entities = len([m for m in report.proposed_mutations if m.kind == "node"])
        candidate_relationships = len([m for m in report.proposed_mutations if m.kind == "relationship"])
        return {"source_id": source_id, "dry_run": True, "records_fetched": report.fetched, "records_normalized": report.normalized, "candidate_entities": candidate_entities, "candidate_relationships": candidate_relationships, "ambiguous_identities": report.quarantined, "warnings": report.warnings, "errors": report.failed, "planned_writes": len(report.proposed_mutations), "canonical_graph_mutated": before != after, "mapping": self.mapping_preview(source_id)}

    def sync(self, source_id: str, *, actor_id: str, mode: str = "incremental", max_records: int = 100) -> dict[str, Any]:
        self._source_node(source_id)
        at = now_iso()
        upsert_node(self.client, "DataSource", source_id, {"last_attempted_sync": at, "last_ingestion_status": "RUNNING", "updated_at": at})
        self.events.record("SYNC_STARTED", about_ids=[source_id], actor_id=actor_id, summary=f"Manual synchronization requested for {source_id}", properties={"phase": "13"})
        report = self._pipeline(source_id).sync(source_id, mode=mode, max_records=max_records, batch_size=min(max_records, 50), dry_run=False)
        success = report.status.value in {"SUCCEEDED", "SUCCESS"}
        props = {"last_ingestion_status": "SUCCESS" if success else report.status.value, "last_failure": None if success else "; ".join(report.warnings[-3:]), "last_successful_sync": now_iso() if success else self._source_node(source_id).get("last_successful_sync"), "updated_at": now_iso()}
        upsert_node(self.client, "DataSource", source_id, props)
        self.events.record("SYNC_COMPLETED" if success else "SYNC_FAILED", about_ids=[source_id, report.run_id], actor_id=actor_id, summary=f"Synchronization {report.status.value} for {source_id}", properties={"phase": "13", "fetched": report.fetched, "written": report.written})
        return report.model_dump(mode="json")

    def list_runs(self, *, source_id: str | None = None) -> list[dict[str, Any]]:
        snapshot = GraphSnapshot.load(self.client)
        rows = [dict(n) for n in snapshot.nodes.values() if has_label(n, "IngestionRun")]
        if source_id:
            rows = [r for r in rows if r.get("source_ref_id") == source_id or any(e.target == source_id for e in snapshot.edges_from(str(r.get("id")), {"DERIVED_FROM"}))]
        return sorted(rows, key=lambda x: str(x.get("started_at") or ""), reverse=True)

    def get_run(self, run_id: str) -> dict[str, Any]:
        snap = GraphSnapshot.load(self.client); run = snap.node(run_id)
        if not has_label(run, "IngestionRun"):
            raise KeyError(run_id)
        records = [snap.node(e.target) for e in snap.edges_from(run_id, {"INGESTED"})]
        records = [r for r in records if r]
        return {**dict(run or {}), "funnel": {"fetched": int((run or {}).get("records_fetched") or 0), "normalized": int((run or {}).get("records_normalized") or 0), "resolved": max(0, int((run or {}).get("records_normalized") or 0) - int((run or {}).get("records_quarantined") or 0)), "written": int((run or {}).get("records_written") or 0), "quarantined": int((run or {}).get("records_quarantined") or 0), "failed": int((run or {}).get("records_failed") or 0)}, "record_ids": [r.get("id") for r in records[:100]]}

    def list_records(self, source_id: str, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        snap = GraphSnapshot.load(self.client)
        rows = [n for n in snap.nodes.values() if has_label(n, "SourceRecord") and n.get("source_id") == source_id and n.get("record_type") != "identity_projection"]
        rows.sort(key=lambda x: str(x.get("fetched_at") or ""), reverse=True)
        items=[]
        for n in rows[offset:offset+limit]:
            normalized=[snap.node(e.target) for e in snap.edges_from(str(n.get("id")), {"NORMALIZED_TO"})]
            normalized=[x for x in normalized if x]
            items.append({"source_record_id":n.get("id"),"external_id":n.get("source_entity_id"),"record_type":n.get("record_type"),"title":n.get("name"),"observed_at":n.get("observed_at"),"status":n.get("status"),"interpreted_as":[{"id":x.get("id"),"name":x.get("name"),"type":(x.get("_labels") or ["Entity"])[-1]} for x in normalized[:10]],"checksum":n.get("checksum"),"mapping_version":n.get("mapping_version")})
        return {"items":items,"limit":limit,"offset":offset,"has_more":offset+limit < len(rows),"total":len(rows)}

    def errors(self, source_id: str) -> list[dict[str, Any]]:
        snap=GraphSnapshot.load(self.client)
        rows=[n for n in snap.nodes.values() if has_label(n,"IngestionQuarantineRecord") and n.get("source_ref_id")==source_id]
        return [{"id":n.get("id"),"category":"ENTITY_RESOLUTION" if "IDENTITY" in str(n.get("reason") or "") else "NORMALIZATION","status":n.get("status"),"reason":n.get("reason"),"source_record_id":n.get("source_record_id"),"created_at":n.get("created_at"),"retryable":True} for n in rows]

    def identity_review(self, *, source_id: str | None = None, status: str = "OPEN") -> list[dict[str, Any]]:
        snap=GraphSnapshot.load(self.client); svc=IngestionEntityResolutionService(self.client)
        rows=svc.list_quarantine(status=status)
        if source_id: rows=[r for r in rows if r.get("source_ref_id")==source_id]
        out=[]
        for r in rows:
            candidates=_parse_jsonish(r.get("candidates"),[])
            proposed=_parse_jsonish(r.get("proposed_entity"),{})
            out.append({"review_id":r.get("id"),"incoming_identity":(proposed.get("properties") or {}).get("name") or r.get("name"),"source_id":r.get("source_ref_id"),"object_type":r.get("candidate_label"),"top_candidate":candidates[0] if candidates else None,"confidence":float((candidates[0] if candidates else {}).get("confidence") or 0.0),"reason":r.get("reason"),"age_since":r.get("created_at"),"candidates":candidates,"proposed_entity":proposed})
        return out

    def resolve_identity(self, review_id: str, action: str, *, actor_id: str, canonical_id: str | None = None, reason: str | None = None) -> dict[str, Any]:
        svc=IngestionEntityResolutionService(self.client); snap=GraphSnapshot.load(self.client); q=snap.node(review_id)
        if not has_label(q,"IngestionQuarantineRecord"): raise KeyError(review_id)
        if action in {"confirm","choose"}:
            if not canonical_id: raise ValueError("canonical_id is required")
            result=svc.resolve_quarantine(review_id,canonical_id,reviewer_ref=actor_id)
            event="IDENTITY_MATCH_CONFIRMED"
        elif action=="create":
            proposed=_parse_jsonish((q or {}).get("proposed_entity"),{})
            label=str((q or {}).get("candidate_label") or proposed.get("ontology_type") or "Entity")
            props=dict(proposed.get("properties") or {}); props.setdefault("name",(q or {}).get("name") or "New canonical entity"); props.setdefault("status","ACTIVE"); props.setdefault("created_at",now_iso())
            canonical_id=canonical_id or stable_id(f"{label.upper()}-MANUAL-",self.client.settings.tenant_id,review_id,props.get("name"),length=16)
            upsert_node(self.client,label,canonical_id,props)
            result=svc.resolve_quarantine(review_id,canonical_id,reviewer_ref=actor_id); event="IDENTITY_CREATED"
        elif action=="reject":
            upsert_node(self.client,"IngestionQuarantineRecord",review_id,{"status":"REJECTED","resolved_at":now_iso(),"reviewer_ref":actor_id,"resolution_reason":reason or "Rejected by reviewer"}); result=svc.get_quarantine(review_id) or {}; event="IDENTITY_REJECTED"
        else: raise ValueError("Unsupported identity action")
        self.events.record(event,about_ids=[review_id]+([canonical_id] if canonical_id else []),actor_id=actor_id,summary=f"Identity review {action}: {review_id}",properties={"phase":"13","reason":reason})
        return result

    def lineage_for_entity(self, entity_id: str) -> dict[str, Any]:
        snap=GraphSnapshot.load(self.client); entity=snap.node(entity_id)
        if not entity: raise KeyError(entity_id)
        record_edges=snap.edges_to(entity_id,{"NORMALIZED_TO"}); records=[]
        for edge in record_edges[:50]:
            record=snap.node(edge.source) or {}; source_id=record.get("source_id"); source=snap.node(str(source_id)) if source_id else None
            runs=[snap.node(e.source) for e in snap.edges_to(str(record.get("id")),{"INGESTED"})]; runs=[r for r in runs if r]
            artifacts=[snap.node(e.target) for e in snap.edges_from(str(record.get("id")),{"REFERENCES"}) if has_label(snap.node(e.target),"Artifact")]
            records.append({"source_record":{"id":record.get("id"),"external_id":record.get("source_entity_id"),"record_type":record.get("record_type")},"source":{"id":source_id,"name":(source or {}).get("display_name") or (source or {}).get("name")},"ingestion_run":{"id":(runs[0] if runs else {}).get("id"),"started_at":(runs[0] if runs else {}).get("started_at"),"status":(runs[0] if runs else {}).get("status")},"artifacts":[{"id":a.get("id"),"name":a.get("name"),"artifact_type":a.get("artifact_type")} for a in artifacts[:10] if a],"mapping":{"rule":edge.properties.get("mapping_rule"),"confidence":edge.properties.get("confidence")}})
        return {"entity":{"id":entity_id,"name":entity.get("name"),"type":(entity.get("_labels") or ["Entity"])[-1]},"lineage":records,"complete":bool(records)}
