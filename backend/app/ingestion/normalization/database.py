from __future__ import annotations

from backend.app.ingestion.adapters.base import checksum_payload
from backend.app.ingestion.models import NormalizedRecord
from backend.app.ingestion.normalization.base import SourceNormalizer
from backend.app.ingestion.normalization.helpers import relation, simple_entity
from backend.app.services.phase6_utils import stable_id


def _schema_graph(config, record):
    raw = record.raw_metadata
    if not isinstance(raw.get("database"), str) or not isinstance(raw.get("tables"), list) or record.checksum != checksum_payload(raw):
        raise ValueError("Database schema record lacks validated catalog metadata")
    database = raw["database"]
    source_key = f"postgresql:{config.id}:{database}"
    source = {"source_database": database, "source_kind": "postgresql_catalog",
              "source_uri": record.canonical_source_uri, "source_schema_scope": raw.get("schemas") or []}
    entities = [simple_entity("database", "System", database,
                              canonical_hint=stable_id("SYS-POSTGRES-", source_key, length=24),
                              identity={"business_key": source_key}, system_type="postgresql_database", **source),
                simple_entity("catalog", "Document", f"{database} catalog",
                              canonical_hint=stable_id("DOC-POSTGRES-", source_key, length=24),
                              identity={"business_key": source_key + ":catalog"},
                              document_type="database_schema", **source)]
    relations = [relation("database", "CONTAINS", "catalog", **source)]
    table_names = {f"{t['schema']}.{t['name']}" for t in raw["tables"]}
    for table in raw["tables"]:
        qualified = f"{table['schema']}.{table['name']}"
        table_key = f"table:{qualified}"
        entities.append(simple_entity(table_key, "SqlTable", qualified,
                                      canonical_hint=stable_id("SQL-TABLE-", source_key, qualified, length=24),
                                      identity={"business_key": f"{source_key}:{qualified}"},
                                      schema_name=table["schema"], table_name=table["name"], **source))
        relations.append(relation("catalog", "DEFINES", table_key, **source))
        primary_columns = {name for c in table["constraints"] if c["kind"] == "PRIMARY_KEY" for name in c["columns"]}
        for column in table["columns"]:
            name = column["name"]
            entities.append(simple_entity(f"column:{qualified}:{name}", "SqlColumn", f"{qualified}.{name}",
                                          canonical_hint=stable_id("SQL-COLUMN-", source_key, qualified, name, length=24),
                                          identity={"business_key": f"{source_key}:{qualified}:{name}"},
                                          schema_name=table["schema"], table_name=table["name"], column_name=name,
                                          data_type=column["data_type"], not_null=column["not_null"],
                                          primary_key=name in primary_columns, **source))
            relations.append(relation(table_key, "HAS_COLUMN", f"column:{qualified}:{name}", **source))
        for constraint in table["constraints"]:
            name = constraint["name"]
            constraint_key = f"constraint:{qualified}:{name}"
            constraint_id = stable_id("SQL-CONSTRAINT-", source_key, constraint_key, length=24)
            facts = {**source, "constraint_id": constraint_id, "constraint_name": name,
                     "constraint_type": constraint["kind"], "columns": constraint["columns"],
                     "referenced_table": constraint.get("referenced_table"),
                     "referenced_columns": constraint.get("referenced_columns") or [],
                     "definition": constraint.get("definition")}
            entities.append(simple_entity(constraint_key, "SqlConstraint", name,
                                          canonical_hint=constraint_id,
                                          identity={"business_key": f"{source_key}:{constraint_key}"}, **facts))
            relations.append(relation(table_key, "HAS_CONSTRAINT", constraint_key, **source, constraint_id=constraint_id))
            if constraint["kind"] == "FOREIGN_KEY":
                target = constraint.get("referenced_table")
                if target not in table_names:
                    raise ValueError("Database foreign key endpoint is outside discovered schema scope")
                relations.append(relation(table_key, "FOREIGN_KEY_TO", f"table:{target}", **facts,
                                          source_columns=constraint["columns"],
                                          target_columns=constraint.get("referenced_columns") or []))
    return entities, relations


class DatabaseNormalizer(SourceNormalizer):
    source_type = "database"
    mapping_version = "database-map-v1"

    def _normalize(self, source_record_id, record):
        raw = record.raw_metadata
        entities, relations, warnings = [], [], []
        observed = record.observed_at or record.source_updated_at or record.fetched_at
        if record.record_type == "database_schema":
            entities, relations = _schema_graph(self.config, record)
        elif record.record_type in {"service_record", "ownership", "dependency", "row"} and raw.get("system"):
            system = raw["system"]
            entities.append(simple_entity("system", "System", system, identity={"name": system, "aliases": raw.get("aliases") or []}, canonical_hint=raw.get("system_canonical_id"), system_type=raw.get("system_type") or "software_service"))
            if raw.get("owner_team"):
                team = raw["owner_team"]
                entities.append(simple_entity("owner", "Team", team, identity={"name": team}, canonical_hint=raw.get("team_canonical_id"), status="ACTIVE"))
                relations.append(relation("owner", "OWNS", "system", valid_from=raw.get("valid_from") or observed, valid_until=raw.get("valid_until"), requires_authoritative_source=True, authoritative=True))
            if raw.get("depends_on"):
                dep = raw["depends_on"]
                entities.append(simple_entity("dependency", "System", dep, identity={"name": dep}, canonical_hint=raw.get("dependency_canonical_id"), system_type="service_or_database"))
                relations.append(relation("system", "DEPENDS_ON", "dependency", valid_from=raw.get("valid_from") or observed, requires_authoritative_source=True, authoritative=True))
        else:
            warnings.append(f"UNMAPPED_DATABASE_RECORD_TYPE:{record.record_type}")
        return NormalizedRecord(source_record_id=source_record_id, mapping_rule=f"database:{record.record_type}", mapping_version=self.mapping_version, entities=entities, relations=relations, artifacts=list(record.artifacts), warnings=warnings, trust_metadata=self.trust_metadata())
