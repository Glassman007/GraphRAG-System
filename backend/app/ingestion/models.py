from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TrustClass(str, Enum):
    AUTHORITATIVE = "AUTHORITATIVE"
    STRONG = "STRONG"
    STANDARD = "STANDARD"
    UNTRUSTED = "UNTRUSTED"


class ResolutionStatus(str, Enum):
    MATCHED = "MATCHED"
    CREATED = "CREATED"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"
    UNRESOLVED = "UNRESOLVED"
    REJECTED_MATCH = "REJECTED_MATCH"


class IngestionRunStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DRY_RUN = "DRY_RUN"


class ArtifactType(str, Enum):
    PDF = "PDF"
    IMAGE = "IMAGE"
    LOG = "LOG"
    TRACE = "TRACE"
    SOURCE_FILE = "SOURCE_FILE"
    ARCHIVE = "ARCHIVE"
    DOCUMENT = "DOCUMENT"
    JSON_PAYLOAD = "JSON_PAYLOAD"
    OTHER = "OTHER"


class SourceConfig(BaseModel):
    id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source_instance: str = Field(min_length=1)
    base_url: str | None = None
    trust_class: TrustClass = TrustClass.STANDARD
    authoritative_domains: list[str] = Field(default_factory=list)
    enabled: bool = True
    sync_mode: str = "incremental"
    adapter_version: str = "phase9-v1"
    mapping_version: str = "phase9-v1"
    fixture_path: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        payload = self.model_dump()
        # Server-side config may contain environment-variable names, but never resolved secrets.
        for key in list(payload.get("settings", {})):
            if any(token in key.lower() for token in ("token", "password", "secret", "cookie", "private_key")):
                payload["settings"][key] = "<redacted-config-reference>"
        return payload


class ArtifactPayload(BaseModel):
    name: str
    content: bytes | str
    mime_type: str = "application/octet-stream"
    artifact_type: ArtifactType = ArtifactType.OTHER
    retention_class: str | None = None
    external_uri: str | None = None


class ArtifactMetadata(BaseModel):
    artifact_id: str
    uri: str
    sha256: str
    size_bytes: int
    mime_type: str
    artifact_type: ArtifactType
    created_at: str
    source_type: str
    source_record_id: str
    retention_class: str | None = None


class SourceRecordEnvelope(BaseModel):
    source_type: str
    source_instance: str
    external_id: str
    record_type: str
    observed_at: str | None = None
    fetched_at: str
    source_updated_at: str | None = None
    version: str | None = None
    etag: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    canonical_source_uri: str | None = None
    artifacts: list[ArtifactPayload] = Field(default_factory=list)
    cursor: str | None = None
    checksum: str
    deleted: bool = False
    schema_version: str = "1"


class RelationCandidate(BaseModel):
    source_key: str
    rel_type: str
    target_key: str
    properties: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    requires_authoritative_source: bool = False


class EntityCandidate(BaseModel):
    key: str
    ontology_type: str
    properties: dict[str, Any]
    identity: dict[str, Any] = Field(default_factory=dict)
    allow_create: bool = True
    requires_resolution: bool = False
    canonical_hint: str | None = None


class NormalizedRecord(BaseModel):
    source_record_id: str
    mapping_rule: str
    mapping_version: str
    entities: list[EntityCandidate] = Field(default_factory=list)
    relations: list[RelationCandidate] = Field(default_factory=list)
    artifacts: list[ArtifactPayload] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    trust_metadata: dict[str, Any] = Field(default_factory=dict)


class ResolutionDecision(BaseModel):
    entity_key: str
    status: ResolutionStatus
    canonical_id: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class ProposedMutation(BaseModel):
    kind: str
    label_or_type: str
    source_id: str | None = None
    target_id: str | None = None
    entity_id: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class IngestionReport(BaseModel):
    run_id: str
    source_id: str
    status: IngestionRunStatus
    fetched: int = 0
    normalized: int = 0
    resolved: int = 0
    written: int = 0
    updated: int = 0
    quarantined: int = 0
    artifacts: int = 0
    failed: int = 0
    cursor_start: str | None = None
    cursor_end: str | None = None
    warnings: list[str] = Field(default_factory=list)
    proposed_mutations: list[ProposedMutation] = Field(default_factory=list)


class AdapterPage(BaseModel):
    records: list[SourceRecordEnvelope]
    next_cursor: str | None = None
    has_more: bool = False
