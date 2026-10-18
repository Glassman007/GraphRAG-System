from __future__ import annotations

from backend.app.ingestion.normalization.slack import SlackNormalizer


class TeamsNormalizer(SlackNormalizer):
    source_type = "teams"
    mapping_version = "teams-map-v1"
