from __future__ import annotations

from backend.app.ingestion.normalization.database import DatabaseNormalizer


class InternalApiNormalizer(DatabaseNormalizer):
    source_type = "internal_api"
    mapping_version = "internal-api-map-v1"
