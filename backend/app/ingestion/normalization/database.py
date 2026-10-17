from __future__ import annotations

from backend.app.ingestion.models import NormalizedRecord
from backend.app.ingestion.normalization.base import SourceNormalizer
from backend.app.ingestion.normalization.helpers import relation, simple_entity


class DatabaseNormalizer(SourceNormalizer):
    source_type = "database"
    mapping_version = "database-map-v1"

    def _normalize(self, source_record_id, record):
        raw = record.raw_metadata
        entities, relations, warnings = [], [], []
        observed = record.observed_at or record.source_updated_at or record.fetched_at
        if record.record_type in {"service_record", "ownership", "dependency", "row"} and raw.get("system"):
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
