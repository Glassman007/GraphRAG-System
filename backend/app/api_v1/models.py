from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None
    request_id: str

class ErrorResponse(BaseModel):
    error: ErrorBody

class PageResponse(BaseModel):
    items: list[dict[str, Any]]
    next_cursor: str | None = None
    has_more: bool = False
    limit: int

class SituationCreate(BaseModel):
    situation_id: str | None = None
    name: str = Field(min_length=1)
    description: str = ""
    severity: str = "MEDIUM"
    occurred_at: str | None = None

class InvestigationCreate(BaseModel):
    situation_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    seed_entity_ids: list[str] = Field(default_factory=list, max_length=50)
    as_of: str | None = None

class RetrievalRequestExternal(BaseModel):
    query: str = Field(min_length=1)
    seed_entity_ids: list[str] = Field(default_factory=list, max_length=50)
    as_of: str | None = None
    max_results: int = Field(default=10, ge=1, le=50)
    max_graph_hops: int = Field(default=3, ge=1, le=6)
    retrieval_modes: list[str] = Field(default_factory=list)
    metadata_filters: dict[str, Any] = Field(default_factory=dict)


class PlanCreateExternal(BaseModel):
    situation_id: str = Field(min_length=1)
    goal: str = Field(default="Resolve the situation safely with enough evidence to act.", min_length=1)
    selected_hypotheses: list[str] = Field(default_factory=list, max_length=100)
    selected_claims: list[str] = Field(default_factory=list, max_length=100)
    knowledge_gaps: list[str] = Field(default_factory=list, max_length=100)
    constraints: list[str] = Field(default_factory=list, max_length=100)
    as_of: str | None = None

class TaskActorRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    execution_id: str | None = None

class CheckpointRequestExternal(TaskActorRequest):
    step_index: int = Field(ge=0)
    current_step: str = Field(min_length=1)
    completed_steps: list[str] = Field(default_factory=list)
    pending_steps: list[str] = Field(default_factory=list)
    state_summary: str = ""
    last_error: str | None = None

class ActionProposalExternal(BaseModel):
    task_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    action_id: str | None = None
    name: str | None = None
    action_type: str | None = None
    target_ids: list[str] = Field(default_factory=list, max_length=50)
    approval_required: bool | None = None

class ActionExecuteExternal(BaseModel):
    agent_id: str = Field(min_length=1)
    lease_seconds: int = Field(default=60, ge=1, le=3600)

class EvidenceInvalidateExternal(BaseModel):
    reason: str = Field(min_length=1)
    actor_id: str | None = None
    timestamp: str | None = None

class ClaimRevalidateExternal(BaseModel):
    evidence_id: str = Field(min_length=1)
    validator_id: str | None = None
    timestamp: str | None = None

class CounterfactualExternal(BaseModel):
    situation_id: str = Field(min_length=1)
    interventions: list[dict[str, Any]] = Field(min_length=1, max_length=50)
    max_depth: int = Field(default=6, ge=1, le=8)

class BusFactorExternal(BaseModel):
    actor_ids: list[str] = Field(min_length=1, max_length=50)
    as_of: str | None = None

class SourceCreateExternal(BaseModel):
    source_id: str | None = None
    display_name: str = Field(min_length=1)
    connector_type: str = Field(min_length=1)
    description: str = ""
    source_instance: str | None = None
    connection_mode: str = "fixture"
    connection_config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] = Field(default_factory=dict)
    scope_config: dict[str, Any] = Field(default_factory=dict)
    mapping_profile: str | None = None
    trust_class: str = "STANDARD"
    sync_mode: str = "incremental"
    sync_schedule: str = "manual"
    expected_sync_interval_minutes: int | None = Field(default=None, ge=1, le=10080)
    enabled: bool = True

class SourceUpdateExternal(BaseModel):
    display_name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    connection_config: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None
    scope_config: dict[str, Any] | None = None
    mapping_profile: str | None = None
    trust_class: str | None = None
    sync_mode: str | None = None
    sync_schedule: str | None = None
    expected_sync_interval_minutes: int | None = Field(default=None, ge=1, le=10080)

class SourcePreviewExternal(BaseModel):
    max_records: int = Field(default=50, ge=1, le=100)

class SourceSyncExternal(BaseModel):
    mode: str = Field(default="incremental", pattern="^(incremental|full)$")
    max_records: int = Field(default=100, ge=1, le=10000)

class IdentityResolveExternal(BaseModel):
    action: str = Field(pattern="^(confirm|choose|create|reject)$")
    canonical_id: str | None = None
    reason: str | None = None
