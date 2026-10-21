"""Focused PostgreSQL catalog ingestion regressions."""
from __future__ import annotations

import json

import pytest

from backend.app.ingestion.adapters.base import checksum_payload
from backend.app.ingestion.adapters.database import DatabaseAdapter
from backend.app.ingestion.models import SourceConfig, SourceRecordEnvelope
from backend.app.ingestion.normalization.database import DatabaseNormalizer
from backend.app.ingestion.source_control import SourceControlService


def config():
    return SourceConfig(id="SRC-DB-TEST", source_type="database", name="Test", source_instance="test",
                        settings={"mode": "schema", "schemas": ["public"], "dsn_env": "MISSING_STAGE6_DSN"})


def test_connection_health_requires_real_postgresql(monkeypatch):
    monkeypatch.delenv("MISSING_STAGE6_DSN", raising=False)
    with pytest.raises(ValueError, match="connection credential"):
        DatabaseAdapter(config()).health_check()


def test_registered_schema_scope_is_server_controlled(monkeypatch):
    service = object.__new__(SourceControlService)
    monkeypatch.setenv("GRAPH_HACKS_REGISTERED_DATABASE_SCHEMAS_JSON", json.dumps({
        "dvd": {"dsn_env": "VERINEX_STAGE6_DSN", "schemas": ["public"]}}))
    cfg = service._safe_connection_config("database", "live", {"registered_schema": "dvd", "settings": {"schemas": ["secret"]}})
    assert cfg["settings"] == {"mode": "schema", "registered_schema": "dvd",
                                "dsn_env": "VERINEX_STAGE6_DSN", "schemas": ["public"]}
    with pytest.raises(ValueError, match="server-registered"):
        service._safe_connection_config("database", "live", {"registered_schema": "unknown"})
    with pytest.raises(ValueError, match="forbidden"):
        service._safe_connection_config("database", "live", {"registered_schema": "dvd", "settings": {"query": "SELECT * FROM secret"}})


def test_catalog_normalization_has_distinct_source_identity_and_exact_fk():
    raw = {"database": "dvd", "schemas": ["public"], "tables": [
        {"schema": "public", "name": "parent", "columns": [{"name": "id", "data_type": "integer", "not_null": True}],
         "constraints": [{"name": "parent_pkey", "kind": "PRIMARY_KEY", "columns": ["id"], "referenced_table": None,
                          "referenced_columns": [], "definition": "PRIMARY KEY (id)"}]},
        {"schema": "public", "name": "child", "columns": [{"name": "parent_id", "data_type": "integer", "not_null": False}],
         "constraints": [{"name": "child_parent_fkey", "kind": "FOREIGN_KEY", "columns": ["parent_id"],
                          "referenced_table": "public.parent", "referenced_columns": ["id"],
                          "definition": "FOREIGN KEY (parent_id) REFERENCES parent(id)"}]},
    ]}
    record = SourceRecordEnvelope(source_type="database", source_instance="test", external_id="dvd:schema",
                                  record_type="database_schema", fetched_at="2026-10-21T00:00:00Z", raw_metadata=raw,
                                  canonical_source_uri="postgresql://dvd", checksum=checksum_payload(raw))
    normalized = DatabaseNormalizer(config()).normalize("record", record)
    assert [e.ontology_type for e in normalized.entities].count("SqlTable") == 2
    assert [r.properties["constraint_name"] for r in normalized.relations if r.rel_type == "FOREIGN_KEY_TO"] == ["child_parent_fkey"]
    table = next(e for e in normalized.entities if e.key == "table:public.parent")
    other = DatabaseNormalizer(config().model_copy(update={"id": "OTHER"})).normalize("record", record)
    assert table.canonical_hint != next(e for e in other.entities if e.key == table.key).canonical_hint
    assert table.canonical_hint == next(e for e in DatabaseNormalizer(config()).normalize("record", record).entities if e.key == table.key).canonical_hint
    record.checksum = "tampered"
    with pytest.raises(ValueError, match="validated catalog"):
        DatabaseNormalizer(config()).normalize("record", record)
