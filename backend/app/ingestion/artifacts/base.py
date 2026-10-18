from __future__ import annotations

from abc import ABC, abstractmethod

from backend.app.ingestion.models import ArtifactMetadata, ArtifactPayload


class ArtifactStore(ABC):
    @abstractmethod
    def put(self, payload: ArtifactPayload, *, tenant_id: str, source_type: str, source_record_id: str) -> ArtifactMetadata:
        raise NotImplementedError

    @abstractmethod
    def get(self, artifact_id: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def exists(self, artifact_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def metadata(self, artifact_id: str) -> ArtifactMetadata | None:
        raise NotImplementedError

    @abstractmethod
    def delete_if_safe(self, artifact_id: str) -> bool:
        raise NotImplementedError
