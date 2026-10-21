from __future__ import annotations

from backend.app.ingestion.normalization.database import DatabaseNormalizer


class InternalApiNormalizer(DatabaseNormalizer):
    source_type = "internal_api"
    mapping_version = "internal-api-map-v1"

    def _normalize(self, source_record_id, record):
        normalized = super()._normalize(source_record_id, record)
        return normalized.model_copy(update={"mapping_rule": f"internal_api:{record.record_type}"})
