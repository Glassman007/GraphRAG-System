from __future__ import annotations

from abc import ABC, abstractmethod

from backend.app.ingestion.models import ArtifactMetadata, ArtifactPayload, ArtifactType

DEFAULT_INLINE_THRESHOLD_BYTES = 16384

# Binary/document-like payloads never live inline in graph properties, regardless of size.
ALWAYS_EXTERNALIZED_TYPES = frozenset({
    ArtifactType.PDF,
    ArtifactType.IMAGE,
    ArtifactType.LOG,
    ArtifactType.TRACE,
    ArtifactType.SOURCE_FILE,
    ArtifactType.ARCHIVE,
    ArtifactType.DOCUMENT,
})


def payload_bytes(payload: ArtifactPayload) -> bytes:
    content = payload.content
    return content if isinstance(content, bytes) else content.encode("utf-8")


class ArtifactStore(ABC):
    """Content-addressed artifact byte storage. FalkorDB only ever holds the returned metadata."""

    def __init__(self, *, inline_threshold_bytes: int = DEFAULT_INLINE_THRESHOLD_BYTES):
        if inline_threshold_bytes < 0:
            raise ValueError("inline_threshold_bytes must be non-negative")
        self.inline_threshold_bytes = inline_threshold_bytes

    def should_externalize(self, payload: ArtifactPayload) -> bool:
        if payload.artifact_type in ALWAYS_EXTERNALIZED_TYPES:
            return True
        return len(payload_bytes(payload)) > self.inline_threshold_bytes

    @abstractmethod
    def put(self, payload: ArtifactPayload, *, tenant_id: str, source_type: str, source_record_id: str) -> ArtifactMetadata: ...

    @abstractmethod
    def get(self, artifact_id: str) -> bytes: ...

    @abstractmethod
    def exists(self, artifact_id: str) -> bool: ...

    @abstractmethod
    def metadata(self, artifact_id: str) -> ArtifactMetadata | None: ...

    @abstractmethod
    def delete_if_safe(self, artifact_id: str) -> bool: ...
