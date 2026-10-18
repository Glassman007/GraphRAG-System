from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class RetrievalMode(str, Enum):
    LEXICAL = "LEXICAL"
    VECTOR = "VECTOR"
    DOCUMENT = "DOCUMENT"
    METADATA = "METADATA"
    SQL = "SQL"
    API = "API"


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=1)
    tenant_id: str
    requesting_agent_id: str | None = None
    task_id: str | None = None
    investigation_id: str | None = None
    situation_id: str | None = None
    seed_entity_ids: list[str] = Field(default_factory=list)
    as_of: str | None = None
    allowed_source_types: list[str] = Field(default_factory=list)
    retrieval_modes: list[RetrievalMode] = Field(default_factory=list)
    max_results: int = Field(default=10, ge=1, le=50)
    max_graph_hops: int = Field(default=3, ge=1, le=6)
    metadata_filters: dict[str, Any] = Field(default_factory=dict)
    evidence_requirements: list[str] = Field(default_factory=list)
    writeback: bool = True


class GraphScope(BaseModel):
    seed_entities: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    source_types: dict[str, str] = Field(default_factory=dict)
    source_records: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)
    chunks: list[str] = Field(default_factory=list)
    temporal_scope: dict[str, Any] = Field(default_factory=dict)
    retrieval_candidates: list[dict[str, Any]] = Field(default_factory=list)
    paths: list[dict[str, Any]] = Field(default_factory=list)
    graph_required: bool = True


class IndexedDocument(BaseModel):
    document_id: str
    text: str
    tenant_id: str
    artifact_id: str | None = None
    source_record_id: str | None = None
    data_source_id: str | None = None
    entity_ids: list[str] = Field(default_factory=list)
    document_type: str = "TEXT"
    observed_at: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    result_id: str
    retrieval_method: RetrievalMode
    score: float
    source_id: str | None = None
    source_record_id: str | None = None
    artifact_id: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    external_uri: str | None = None
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    observed_at: str | None = None
    retrieved_at: str
    provenance: dict[str, Any] = Field(default_factory=dict)
    graph_scope: list[str] = Field(default_factory=list)
    matched_entity_ids: list[str] = Field(default_factory=list)
    query: str
    rank: int
    explanation: str = ""


class RetrievalPlan(BaseModel):
    modes: list[RetrievalMode]
    reasons: dict[str, str]
    graph_scope_hash: str


class RetrievalResponse(BaseModel):
    graph_scope: GraphScope
    retrievers_used: list[dict[str, str]]
    results: list[RetrievalResult]
    evidence_ids: list[str] = Field(default_factory=list)
    execution_id: str | None = None
    graph_required: bool = True
