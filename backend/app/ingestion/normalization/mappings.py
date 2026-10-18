from __future__ import annotations

from backend.app.ingestion.models import SourceConfig
from backend.app.ingestion.normalization.base import SourceNormalizer
from backend.app.ingestion.normalization.database import DatabaseNormalizer
from backend.app.ingestion.normalization.documents import DocumentNormalizer
from backend.app.ingestion.normalization.github import GitHubNormalizer
from backend.app.ingestion.normalization.internal_api import InternalApiNormalizer
from backend.app.ingestion.normalization.jira import JiraNormalizer
from backend.app.ingestion.normalization.slack import SlackNormalizer
from backend.app.ingestion.normalization.teams import TeamsNormalizer
from backend.app.ingestion.normalization.telemetry import TelemetryNormalizer


NORMALIZERS: dict[str, type[SourceNormalizer]] = {
    "github": GitHubNormalizer,
    "jira": JiraNormalizer,
    "slack": SlackNormalizer,
    "teams": TeamsNormalizer,
    "documents": DocumentNormalizer,
    "telemetry": TelemetryNormalizer,
    "database": DatabaseNormalizer,
    "internal_api": InternalApiNormalizer,
}


def normalizer_for(config: SourceConfig) -> SourceNormalizer:
    cls = NORMALIZERS.get(config.source_type)
    if cls is None:
        raise ValueError(f"No normalization mapping registered for source_type={config.source_type}")
    return cls(config)


def mapping_catalog() -> list[dict[str, str]]:
    return [
        {"source_type": name, "normalizer": cls.__name__, "mapping_version": cls.mapping_version}
        for name, cls in sorted(NORMALIZERS.items())
    ]
