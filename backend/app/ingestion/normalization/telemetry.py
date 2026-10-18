from __future__ import annotations

from backend.app.ingestion.models import NormalizedRecord
from backend.app.ingestion.normalization.base import SourceNormalizer
from backend.app.ingestion.normalization.helpers import relation, simple_entity
from backend.app.services.phase6_utils import stable_id


class TelemetryNormalizer(SourceNormalizer):
    source_type = "telemetry"
    mapping_version = "telemetry-map-v1"

    def _normalize(self, source_record_id, record):
        raw = record.raw_metadata
        entities, relations, warnings = [], [], []
        observed = record.observed_at or raw.get("timestamp") or record.fetched_at
        system = raw.get("system") or raw.get("service")
        if record.record_type in {"metric", "alert", "trace", "log_observation", "deployment_event"}:
            if system:
                entities.append(simple_entity("system", "System", system, identity={"name": system}, canonical_hint=raw.get("system_canonical_id"), system_type="software_service"))
            event_name = raw.get("name") or raw.get("metric") or raw.get("message") or f"Telemetry {record.external_id}"
            entities.append(simple_entity("event", "Event", event_name[:120], identity={"external_id": record.external_id}, canonical_hint=raw.get("event_canonical_id"), event_type=raw.get("event_type") or record.record_type.upper(), occurred_at=observed, created_at=record.fetched_at, summary=raw.get("message") or event_name))
            evidence_name = raw.get("evidence_name") or f"Observation: {event_name}"
            entities.append(simple_entity("evidence", "Evidence", evidence_name[:120], identity={"external_id": stable_id("E-ING-", source_record_id, event_name)}, canonical_hint=raw.get("evidence_canonical_id"), evidence_type=record.record_type, status="OBSERVED", confidence=float(raw.get("confidence") or 0.9), observed_at=observed, created_at=record.fetched_at, value=raw.get("value"), unit=raw.get("unit")))
            if system:
                relations.extend([
                    relation("event", "ABOUT", "system", valid_from=observed),
                    relation("evidence", "ABOUT", "system", valid_from=observed),
                ])
            incident_id = raw.get("incident_canonical_id")
            if incident_id:
                entities.append(simple_entity("incident", "Incident", raw.get("incident_name") or incident_id, identity={"business_key": incident_id}, canonical_hint=incident_id, status="OPEN", created_at=observed))
                relations.append(relation("event", "ABOUT", "incident", valid_from=observed))
                relations.append(relation("evidence", "ABOUT", "incident", valid_from=observed))
            relations.append(relation("evidence", "DERIVED_FROM", "event", valid_from=record.fetched_at))
        else:
            warnings.append(f"UNMAPPED_TELEMETRY_RECORD_TYPE:{record.record_type}")
        return NormalizedRecord(source_record_id=source_record_id, mapping_rule=f"telemetry:{record.record_type}", mapping_version=self.mapping_version, entities=entities, relations=relations, artifacts=list(record.artifacts), warnings=warnings, trust_metadata=self.trust_metadata())
