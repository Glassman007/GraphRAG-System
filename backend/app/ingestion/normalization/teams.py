from __future__ import annotations

from backend.app.ingestion.normalization.slack import SlackNormalizer


class TeamsNormalizer(SlackNormalizer):
    source_type = "teams"
    mapping_version = "teams-map-v1"

    def _normalize(self, source_record_id, record):
        normalized = super()._normalize(source_record_id, record)
        return normalized.model_copy(update={"mapping_rule": f"teams:{record.record_type}"})
