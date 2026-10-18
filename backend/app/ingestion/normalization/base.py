from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from backend.app.ingestion.models import NormalizedRecord, SourceConfig, SourceRecordEnvelope


class SourceNormalizer(ABC):
    source_type: str = "generic"
    mapping_version: str = "phase9-v1"
    supported_schema_versions: set[str] = {"1"}

    def __init__(self, config: SourceConfig):
        self.config = config

    def normalize(self, source_record_id: str, record: SourceRecordEnvelope) -> NormalizedRecord:
        if record.schema_version not in self.supported_schema_versions:
            raise ValueError(f"Unsupported {self.source_type} schema_version={record.schema_version}")
        return self._normalize(source_record_id, record)

    @abstractmethod
    def _normalize(self, source_record_id: str, record: SourceRecordEnvelope) -> NormalizedRecord:
        raise NotImplementedError

    def trust_metadata(self) -> dict[str, Any]:
        return {
            "trust_class": self.config.trust_class.value,
            "authoritative_domains": list(self.config.authoritative_domains),
            "mapping_version": self.config.mapping_version,
        }
