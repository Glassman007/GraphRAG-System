from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.graph_service import GraphService
from backend.app.services.claim_memory_service import ClaimMemoryService
from backend.app.services.authority_resolution_service import AuthorityResolutionService
from backend.app.services.routing_service import ResponsibilityRoutingService
from backend.app.services.ownership_gap_service import OwnershipGapService
from backend.app.services.entity_resolution_service import EntityResolutionService
from backend.app.services.investigation_service import RelationalInvestigationService
from backend.app.services.blast_radius_service import BlastRadiusService
from backend.app.services.knowledge_gap_service import KnowledgeGapService
from backend.app.services.evidence_acquisition_service import EvidenceAcquisitionService
from backend.app.services.decision_genealogy_service import DecisionGenealogyService
from backend.app.services.precedent_service import StructuralPrecedentService
from backend.app.services.planning_service import ConstraintPlanningService
from backend.app.services.work_planning_service import WorkPlanningService
from backend.app.services.simulation_service import CounterfactualSimulationService
from backend.app.services.anomaly_service import GraphAnomalyService
from backend.app.services.agent_registry_service import AgentRegistryService
from backend.app.services.coordination_service import CoordinationService
from backend.app.services.specialist_agent_service import SpecialistAgentService
from backend.app.services.handoff_service import HandoffService
from backend.app.services.branch_service import BranchMemoryService
from backend.app.services.coordination_risk_service import CoordinationRiskService
from backend.app.services.governance_service import GovernanceService
from backend.app.services.action_coordination_service import ActionCoordinationService
from backend.app.services.memory_compaction_service import MemoryCompactionService
from backend.app.services.learning_writeback_service import LearningWritebackService
from backend.app.services.memory_promotion_service import MemoryPromotionService
from backend.app.services.knowledge_invalidation_service import KnowledgeInvalidationService
from backend.app.services.closed_loop_learning_service import ClosedLoopLearningService
from backend.app.services.process_reconstruction_service import OrganizationalProcessReconstructionService
from backend.app.services.policy_drift_service import PolicyDriftService
from backend.app.services.commitment_service import CommitmentTrackingService
from backend.app.services.initiative_collision_service import InitiativeCollisionService
from backend.app.services.bus_factor_service import BusFactorService
from backend.app.services.organizational_network_service import OrganizationalNetworkAnalysisService
from backend.app.ingestion.pipeline import IngestionPipeline
from backend.app.ingestion.registry import build_default_registry
from backend.app.ingestion.resolution.service import IngestionEntityResolutionService

app = FastAPI(title="GraphHacks Company Brain — Phase 1-12", version="0.12.0", description="GraphHacks stable external API with Phase 12 functional client support plus backward-compatible internal routes.")

from backend.app.api_v1.setup import install_api_v1
install_api_v1(app)


def _client() -> FalkorGraphClient:
    return FalkorGraphClient()


def _service() -> GraphService:
    return GraphService(_client())


@app.get("/health")
def health():
    try:
        return _client().health_check()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"FalkorDB unavailable: {exc}") from exc


@app.get("/entities/{entity_id}")
def entity(entity_id: str):
    value = _service().get_entity(entity_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return value


@app.get("/incidents/{incident_id}/context")
def incident_context(incident_id: str):
    service = _service()
    if service.get_entity(incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return service.get_incident_context(incident_id)


@app.get("/claims/{claim_id}")
def claim_detail(claim_id: str):
    value = ClaimMemoryService(_client()).get_claim(claim_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return value


@app.get("/claims/{claim_id}/history")
def claim_history(claim_id: str):
    service = ClaimMemoryService(_client())
    if service.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return service.get_claim_history(claim_id)


@app.post("/claims/{claim_id}/contradictions/{other_claim_id}")
def record_claim_contradiction(
    claim_id: str,
    other_claim_id: str,
    scope: str | None = None,
    confidence: float = Query(default=1.0, ge=0.0, le=1.0),
    source_ref_id: str | None = None,
):
    try:
        return ClaimMemoryService(_client()).record_contradiction(
            claim_id,
            other_claim_id,
            scope=scope,
            confidence=confidence,
            source_ref_id=source_ref_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/subjects/{entity_id}/claims")
def subject_claims(entity_id: str):
    service = _service()
    if service.get_entity(entity_id) is None:
        raise HTTPException(status_code=404, detail="Subject entity not found")
    return {"subject_id": entity_id, "claims": ClaimMemoryService(service.client).get_claims_about(entity_id)}


@app.get("/incidents/{incident_id}/conflicts")
def incident_conflicts(incident_id: str):
    service = _service()
    if service.get_entity(incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return ClaimMemoryService(service.client).get_conflict_set(incident_id)


@app.get("/conflicts/{entity_id}/resolve")
def resolve_conflicts(entity_id: str, as_of: str | None = None):
    service = _service()
    if service.get_entity(entity_id) is None:
        raise HTTPException(status_code=404, detail="Subject entity not found")
    return AuthorityResolutionService(service.client).resolve_subject_conflicts(entity_id, as_of=as_of)


@app.get("/entities/{entity_id}/owner")
def entity_owner(entity_id: str, as_of: str | None = None):
    service = _service()
    if service.get_entity(entity_id) is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return ResponsibilityRoutingService(service.client).find_owner(entity_id, as_of=as_of)


@app.get("/entities/{entity_id}/responsibility")
def entity_responsibility(entity_id: str, as_of: str | None = None):
    service = _service()
    if service.get_entity(entity_id) is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return ResponsibilityRoutingService(service.client).find_responsible_actor(entity_id, as_of=as_of)


@app.get("/entities/{entity_id}/experts")
def entity_experts(entity_id: str, as_of: str | None = None):
    service = _service()
    if service.get_entity(entity_id) is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return ResponsibilityRoutingService(service.client).find_experts(entity_id, as_of=as_of)


@app.get("/entities/{entity_id}/responders")
def entity_responders(entity_id: str, as_of: str | None = None):
    service = _service()
    if service.get_entity(entity_id) is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return ResponsibilityRoutingService(service.client).rank_candidate_responders(entity_id, as_of=as_of)


@app.get("/organization/orphaned-resources")
def orphaned_resources(as_of: str | None = None):
    return OwnershipGapService(_client()).detect_orphaned_resources(as_of=as_of)


@app.get("/organization/resources/{entity_id}/ownership-risk")
def resource_ownership_risk(entity_id: str, as_of: str | None = None):
    value = OwnershipGapService(_client()).inspect_resource(entity_id, as_of=as_of)
    if value is None:
        raise HTTPException(status_code=404, detail="System not found")
    return value


class EvidenceAcquisitionRequest(BaseModel):
    evidence_name: str = Field(min_length=1)
    evidence_type: str = Field(min_length=1)
    observed_at: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_id: str | None = None


class PlanRequest(BaseModel):
    # `incident_id` is retained for backward compatibility with the Phase 4 constraint-plan API.
    incident_id: str | None = Field(default=None, min_length=1)
    situation_id: str | None = Field(default=None, min_length=1)
    goal: str | None = Field(default=None, min_length=1)
    selected_hypotheses: list[str] = Field(default_factory=list)
    selected_claims: list[str] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    as_of: str | None = None


class SimulationRequest(BaseModel):
    entity_id: str = Field(min_length=1)
    operations: list[dict]
    max_depth: int = Field(default=6, ge=1, le=8)


@app.get("/source-records/{source_record_id}/resolution")
def source_record_resolution(source_record_id: str):
    value = EntityResolutionService(_client()).resolve_source_record(source_record_id)
    if value is None:
        raise HTTPException(status_code=404, detail="SourceRecord not found")
    return value


@app.post("/source-records/{source_record_id}/resolution/{entity_id}/confirm")
def confirm_source_record_resolution(source_record_id: str, entity_id: str, confidence: float = Query(default=1.0, ge=0.0, le=1.0), reviewer_ref: str | None = None):
    try:
        return EntityResolutionService(_client()).confirm_match(source_record_id, entity_id, confidence=confidence, reviewer_ref=reviewer_ref)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/incidents/{incident_id}/investigation")
def investigate_incident(incident_id: str, max_depth: int = Query(default=7, ge=1, le=8), limit: int = Query(default=20, ge=1, le=100)):
    value = RelationalInvestigationService(_client()).investigate_incident(incident_id, max_depth=max_depth, limit=limit)
    if value is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return value


@app.get("/entities/{entity_id}/blast-radius")
def blast_radius(entity_id: str, max_depth: int = Query(default=6, ge=1, le=8), as_of: str | None = None):
    value = BlastRadiusService(_client()).analyze(entity_id, max_depth=max_depth, as_of=as_of)
    if value is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return value


@app.get("/incidents/{incident_id}/knowledge-gaps")
def knowledge_gaps(incident_id: str, as_of: str | None = None):
    value = KnowledgeGapService(_client()).detect_for_incident(incident_id, as_of=as_of)
    if value is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return value


@app.get("/questions/{question_id}/tool-routing")
def question_tool_routing(question_id: str):
    value = EvidenceAcquisitionService(_client()).route_question(question_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return value


@app.post("/questions/{question_id}/acquire-evidence")
def acquire_evidence(question_id: str, request: EvidenceAcquisitionRequest):
    try:
        return EvidenceAcquisitionService(_client()).acquire_mock(question_id, **request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/decisions/{decision_id}/genealogy")
def decision_genealogy(decision_id: str, as_of: str | None = None):
    value = DecisionGenealogyService(_client()).replay(decision_id, as_of=as_of)
    if value is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return value


@app.get("/incidents/{incident_id}/precedents")
def incident_precedents(incident_id: str, limit: int = Query(default=10, ge=1, le=50)):
    value = StructuralPrecedentService(_client()).find_precedents(incident_id, limit=limit)
    if value is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return value


@app.post("/plans")
def build_plan(request: PlanRequest):
    # Preserve the Phase 4 action-order contract for legacy callers that send only `incident_id`.
    if request.situation_id is None and request.goal is None and request.incident_id:
        value = ConstraintPlanningService(_client()).plan_for_incident(request.incident_id)
        if value is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        return value

    situation_id = request.situation_id or request.incident_id
    if not situation_id:
        raise HTTPException(status_code=422, detail="situation_id (or legacy incident_id) is required")
    goal = request.goal or "Resolve the situation safely with enough evidence to act."
    try:
        value = WorkPlanningService(_client()).generate_plan(
            situation_id,
            goal,
            selected_hypotheses=request.selected_hypotheses,
            selected_claims=request.selected_claims,
            knowledge_gaps=request.knowledge_gaps,
            constraints=request.constraints,
            as_of=request.as_of,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if value is None:
        raise HTTPException(status_code=404, detail="Situation not found")
    return value


@app.get("/plans/{plan_id}")
def get_plan(plan_id: str):
    value = WorkPlanningService(_client()).get_plan(plan_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return value


@app.get("/plans/{plan_id}/tasks")
def get_plan_tasks(plan_id: str):
    value = WorkPlanningService(_client()).get_plan_tasks(plan_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return value


@app.get("/plans/{plan_id}/ready-tasks")
def get_plan_ready_tasks(plan_id: str):
    value = WorkPlanningService(_client()).get_ready_tasks(plan_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return value


@app.get("/plans/{plan_id}/validate")
def validate_plan(plan_id: str):
    service = WorkPlanningService(_client())
    if service.get_plan(plan_id) is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return service.validate_plan(plan_id)


@app.post("/plans/{plan_id}/recompute")
def recompute_plan(plan_id: str):
    try:
        value = WorkPlanningService(_client()).recompute_plan(plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if value is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return value


@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    value = WorkPlanningService(_client()).get_task(task_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return value


@app.get("/tasks/{task_id}/candidate-assignees")
def get_task_candidate_assignees(task_id: str):
    value = WorkPlanningService(_client()).get_candidate_assignees(task_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return value


@app.get("/tasks/{task_id}/prerequisites")
def get_task_prerequisites(task_id: str):
    value = WorkPlanningService(_client()).get_prerequisites(task_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return value


@app.get("/tasks/{task_id}/completion-status")
def get_task_completion_status(task_id: str):
    value = WorkPlanningService(_client()).is_task_completion_satisfied(task_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return value


@app.post("/simulations")
def simulate(request: SimulationRequest):
    try:
        value = CounterfactualSimulationService(_client()).simulate(request.entity_id, request.operations, max_depth=request.max_depth)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if value is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return value


@app.get("/anomalies")
def anomalies():
    return GraphAnomalyService(_client()).detect()


# ---------------------------------------------------------------------------
# Phase 6 — persistent agent coordination
# ---------------------------------------------------------------------------

class TaskClaimRequest(BaseModel):
    agent_id: str = Field(min_length=1)


class CheckpointRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    execution_id: str | None = None
    step_index: int = Field(ge=0)
    current_step: str = Field(min_length=1)
    completed_steps: list[str] = Field(default_factory=list)
    pending_steps: list[str] = Field(default_factory=list)
    state_summary: str = ""
    last_error: str | None = None


class ResumeRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    execution_id: str | None = None


class CompleteExecutionRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    execution_id: str | None = None


class FindingRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    kind: str = "GENERAL"
    evidence_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    branch_id: str | None = None


class FindingVerificationRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    result: str = Field(min_length=1)
    rationale: str = ""


class EvidenceShareRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)


class BlockerRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    severity: str = "MEDIUM"


class HandoffCreateRequest(BaseModel):
    source_task_id: str = Field(min_length=1)
    from_agent_id: str = Field(min_length=1)
    to_agent_id: str = Field(min_length=1)
    artifact_ids: list[str] = Field(default_factory=list)
    destination_task_id: str | None = None
    confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    contradictory_evidence_disclosed: bool = True


class HandoffDecisionRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    reason: str = ""


class BranchCreateRequest(BaseModel):
    execution_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    branch_kind: str = "HYPOTHESIS"


class BranchFindingRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    kind: str = "HYPOTHESIS"


class BranchDecisionRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    reason: str = ""


class ActionProposalRequest(BaseModel):
    task_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    action_id: str | None = None
    name: str | None = None
    action_type: str | None = None
    target_ids: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None
    approval_required: bool | None = None


class ActionExecuteRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    lease_seconds: int = Field(default=60, ge=1, le=3600)
    simulate_crash: str | None = None


class ActionRecoverRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    reconcile_external: bool = False


class CompactionRequest(BaseModel):
    keep_latest: int = Field(default=1, ge=1, le=20)
    actor_id: str | None = None


def _active_execution_for_task(task_id: str) -> str | None:
    board = CoordinationService(_client()).get_task_blackboard(task_id)
    if not board:
        return None
    active = [x for x in board.get("executions", []) if str(x.get("status") or "").upper() in {"RUNNING", "PAUSED", "BLOCKED"}]
    active.sort(key=lambda x: str(x.get("started_at") or x.get("created_at") or ""), reverse=True)
    return str(active[0].get("id")) if active else None


@app.post("/agents/ensure-defaults")
def ensure_phase6_agents():
    return {"agents": AgentRegistryService(_client()).ensure_default_agents()}


@app.get("/agents/{agent_id}/work")
def get_agent_work(agent_id: str):
    value = CoordinationService(_client()).get_agent_work(agent_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return value


@app.post("/tasks/{task_id}/claim")
def claim_task(task_id: str, request: TaskClaimRequest):
    try:
        return CoordinationService(_client()).claim_task(task_id, request.agent_id)
    except ValueError as exc:
        code = 409 if "claim failed" in str(exc).lower() or "not ready" in str(exc).lower() else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@app.post("/tasks/{task_id}/start")
def start_task(task_id: str, request: TaskClaimRequest):
    try:
        return CoordinationService(_client()).start_execution(task_id, request.agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/tasks/{task_id}/checkpoint")
def checkpoint_task(task_id: str, request: CheckpointRequest):
    execution_id = request.execution_id or _active_execution_for_task(task_id)
    if not execution_id:
        raise HTTPException(status_code=409, detail="Task has no active execution")
    try:
        return CoordinationService(_client()).save_checkpoint(
            execution_id,
            request.agent_id,
            step_index=request.step_index,
            current_step=request.current_step,
            completed_steps=request.completed_steps,
            pending_steps=request.pending_steps,
            state_summary=request.state_summary,
            last_error=request.last_error,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/tasks/{task_id}/resume")
def resume_task(task_id: str, request: ResumeRequest):
    execution_id = request.execution_id or _active_execution_for_task(task_id)
    if not execution_id:
        board = CoordinationService(_client()).get_task_blackboard(task_id)
        if not board or not board.get("executions"):
            raise HTTPException(status_code=409, detail="Task has no execution to resume")
        execution_id = str(board["executions"][-1].get("id"))
    try:
        return CoordinationService(_client()).resume_execution(execution_id, request.agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/tasks/{task_id}/complete")
def complete_task_execution(task_id: str, request: CompleteExecutionRequest):
    execution_id = request.execution_id or _active_execution_for_task(task_id)
    if not execution_id:
        raise HTTPException(status_code=409, detail="Task has no active execution")
    try:
        return CoordinationService(_client()).complete_execution(execution_id, request.agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/tasks/{task_id}/execution")
def task_execution(task_id: str):
    board = CoordinationService(_client()).get_task_blackboard(task_id)
    if board is None:
        raise HTTPException(status_code=404, detail="Task not found")
    executions = board.get("executions") or []
    if not executions:
        return {"task_id": task_id, "execution": None}
    executions.sort(key=lambda x: str(x.get("started_at") or x.get("created_at") or ""), reverse=True)
    return CoordinationService(_client()).get_execution_state(str(executions[0].get("id")), include_archived=True)


@app.get("/plans/{plan_id}/coordination-state")
def plan_blackboard(plan_id: str):
    value = CoordinationService(_client()).get_plan_blackboard(plan_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return value


@app.get("/tasks/{task_id}/coordination-state")
def task_blackboard(task_id: str):
    value = CoordinationService(_client()).get_task_blackboard(task_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return value


@app.post("/tasks/{task_id}/findings")
def create_finding(task_id: str, request: FindingRequest):
    try:
        return CoordinationService(_client()).add_finding(
            task_id,
            request.agent_id,
            statement=request.statement,
            confidence=request.confidence,
            kind=request.kind,
            evidence_ids=request.evidence_ids,
            claim_ids=request.claim_ids,
            branch_id=request.branch_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/findings/{finding_id}/verify")
def verify_finding(finding_id: str, request: FindingVerificationRequest):
    try:
        return SpecialistAgentService(_client()).verify_finding(finding_id, request.agent_id, result=request.result, rationale=request.rationale)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/tasks/{task_id}/evidence")
def share_evidence(task_id: str, request: EvidenceShareRequest):
    try:
        return CoordinationService(_client()).add_shared_evidence(task_id, request.agent_id, request.evidence_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/tasks/{task_id}/blockers")
def create_blocker(task_id: str, request: BlockerRequest):
    try:
        return CoordinationService(_client()).add_blocker(task_id, request.agent_id, reason=request.reason, severity=request.severity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/transfers")
def create_handoff(request: HandoffCreateRequest):
    try:
        return HandoffService(_client()).create_handoff(
            request.source_task_id,
            request.from_agent_id,
            request.to_agent_id,
            artifact_ids=request.artifact_ids,
            destination_task_id=request.destination_task_id,
            confidence_threshold=request.confidence_threshold,
            contradictory_evidence_disclosed=request.contradictory_evidence_disclosed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/transfers/{transfer_id}/validate")
def validate_handoff(transfer_id: str):
    return HandoffService(_client()).validate_handoff(transfer_id)


@app.post("/transfers/{transfer_id}/accept")
def accept_handoff(transfer_id: str, request: HandoffDecisionRequest):
    try:
        return HandoffService(_client()).accept_handoff(transfer_id, request.agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/transfers/{transfer_id}/reject")
def reject_handoff(transfer_id: str, request: HandoffDecisionRequest):
    try:
        return HandoffService(_client()).reject_handoff(transfer_id, request.agent_id, reason=request.reason or "Rejected by receiver")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/branches")
def create_branch(request: BranchCreateRequest):
    try:
        return BranchMemoryService(_client()).create_branch(request.execution_id, request.agent_id, purpose=request.purpose, branch_kind=request.branch_kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/branches/{branch_id}/findings")
def create_branch_finding(branch_id: str, request: BranchFindingRequest):
    try:
        return BranchMemoryService(_client()).add_branch_finding(branch_id, request.agent_id, statement=request.statement, confidence=request.confidence, evidence_ids=request.evidence_ids, kind=request.kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/branches/{branch_id}/validate")
def validate_branch(branch_id: str):
    return BranchMemoryService(_client()).validate_branch(branch_id)


@app.post("/branches/{branch_id}/merge")
def merge_branch(branch_id: str, request: BranchDecisionRequest):
    try:
        return BranchMemoryService(_client()).merge_branch(branch_id, request.agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/branches/{branch_id}/reject")
def reject_branch(branch_id: str, request: BranchDecisionRequest):
    try:
        return BranchMemoryService(_client()).reject_branch(branch_id, request.agent_id, reason=request.reason or "Rejected branch")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/coordination/deadlocks")
def coordination_deadlocks():
    return CoordinationRiskService(_client()).detect_deadlocks()


@app.get("/coordination/contention")
def coordination_contention():
    return CoordinationRiskService(_client()).detect_contention()


@app.post("/actions")
def propose_action(request: ActionProposalRequest):
    try:
        return ActionCoordinationService(_client()).propose_action(
            request.task_id,
            request.agent_id,
            action_id=request.action_id,
            name=request.name,
            action_type=request.action_type,
            target_ids=request.target_ids,
            idempotency_key=request.idempotency_key,
            approval_required=request.approval_required,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/actions/{action_id}/governance")
def action_governance(action_id: str, agent_id: str | None = None):
    return GovernanceService(_client()).evaluate_action(action_id, agent_id=agent_id)


@app.post("/actions/{action_id}/execute")
def execute_action(action_id: str, request: ActionExecuteRequest):
    try:
        return ActionCoordinationService(_client()).execute_action(action_id, request.agent_id, lease_seconds=request.lease_seconds, simulate_crash=request.simulate_crash)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/actions/{action_id}/recover")
def recover_action(action_id: str, request: ActionRecoverRequest):
    try:
        return ActionCoordinationService(_client()).recover_action(action_id, request.agent_id, reconcile_external=request.reconcile_external)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/actions/{action_id}/coordination")
def action_coordination(action_id: str):
    value = ActionCoordinationService(_client()).get_action(action_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return value


@app.post("/executions/{execution_id}/compact")
def compact_execution(execution_id: str, request: CompactionRequest):
    try:
        return MemoryCompactionService(_client()).compact_execution(execution_id, keep_latest=request.keep_latest, actor_id=request.actor_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/executions/{execution_id}")
def get_execution(execution_id: str, include_archived: bool = False):
    value = CoordinationService(_client()).get_execution_state(execution_id, include_archived=include_archived)
    if value is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return value


# ---------------------------------------------------------------------------
# Phase 7 — closed-loop organizational learning
# ---------------------------------------------------------------------------

class EvidenceWritebackRequest(BaseModel):
    source_ref: str = Field(min_length=1)
    content: str = Field(min_length=1)
    evidence_type: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    situation_id: str | None = None
    source_id: str | None = None
    concern_ids: list[str] = Field(default_factory=list)
    supports_claim_ids: list[str] = Field(default_factory=list)
    refutes_claim_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_authority: float = Field(default=0.5, ge=0.0, le=1.0)
    observed_at: str | None = None


class DecisionWritebackRequest(BaseModel):
    summary: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    plan_id: str | None = None
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    policy_ids: list[str] = Field(default_factory=list)
    action_ids: list[str] = Field(default_factory=list)
    outcome_ids: list[str] = Field(default_factory=list)
    decided_at: str | None = None


class OutcomeWritebackRequest(BaseModel):
    observed_effect: str = Field(min_length=1)
    expected_effect: str | None = None
    result: str = Field(min_length=1)
    affected_ids: list[str] = Field(default_factory=list)
    measurements: dict = Field(default_factory=dict)
    actor_id: str | None = None
    observed_at: str | None = None


class PromotionRequest(BaseModel):
    subject_ids: list[str] = Field(default_factory=list)


class ResponsibilityPromotionRequest(BaseModel):
    actor_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    relation_type: str = "OWNS"
    verification_id: str = Field(min_length=1)
    authority_id: str | None = None
    effective_at: str | None = None


class EvidenceInvalidationRequest(BaseModel):
    reason: str = Field(min_length=1)
    actor_id: str | None = None
    timestamp: str | None = None


class DependencyChangeRequest(BaseModel):
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    change_type: str = Field(min_length=1)
    actor_id: str | None = None
    timestamp: str | None = None


class EntityResolutionChangeRequest(BaseModel):
    old_entity_id: str | None = None
    new_entity_id: str = Field(min_length=1)
    actor_id: str | None = None
    timestamp: str | None = None


class OutcomeFeedbackRequest(BaseModel):
    actor_id: str | None = None
    timestamp: str | None = None


class ClaimSupersessionRequest(BaseModel):
    actor_id: str | None = None
    timestamp: str | None = None


class SourceAuthorityRequest(BaseModel):
    authoritative: bool
    authority_score: float | None = Field(default=None, ge=0.0, le=1.0)
    timestamp: str | None = None


class ClaimRevalidationRequest(BaseModel):
    evidence_id: str = Field(min_length=1)
    validator_id: str | None = None
    timestamp: str | None = None


@app.post("/learning/evidence")
def learning_write_evidence(request: EvidenceWritebackRequest):
    try:
        return LearningWritebackService(_client()).write_evidence(**request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc



@app.post("/learning/decisions/{decision_id}")
def learning_write_decision(decision_id: str, request: DecisionWritebackRequest):
    try:
        return LearningWritebackService(_client()).write_decision(decision_id, **request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/learning/actions/{action_id}/outcomes")
def learning_write_outcome(action_id: str, request: OutcomeWritebackRequest):
    try:
        return LearningWritebackService(_client()).write_outcome(action_id, **request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/learning/executions/{execution_id}/process")
def process_completed_execution(execution_id: str):
    try:
        return ClosedLoopLearningService(_client()).process_completed_execution(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/learning/situations/{situation_id}/close")
def close_learning_situation(situation_id: str):
    try:
        result = ClosedLoopLearningService(_client()).close_situation(situation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("precedent", {}).get("status") not in {"PROMOTED", "PRECEDENT_ELIGIBLE"}:
        raise HTTPException(status_code=409, detail=result)
    return result


@app.get("/learning/situations/{situation_id}/report")
def learning_situation_report(situation_id: str):
    try:
        return ClosedLoopLearningService(_client()).report(situation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/memory/hypotheses/{artifact_id}/promote")
@app.post("/memory/findings/{artifact_id}/promote")
def promote_learning_artifact(artifact_id: str, request: PromotionRequest):
    result = MemoryPromotionService(_client()).promote_artifact(artifact_id, subject_ids=request.subject_ids)
    if result.get("status") != "PROMOTED":
        raise HTTPException(status_code=409, detail=result)
    return result


@app.post("/memory/incidents/{incident_id}/promote-precedent")
def promote_incident_precedent(incident_id: str):
    result = MemoryPromotionService(_client()).promote_incident_precedent(incident_id)
    if result.get("status") != "PROMOTED":
        raise HTTPException(status_code=409, detail=result)
    return result


@app.post("/memory/responsibility/promote")
def promote_responsibility(request: ResponsibilityPromotionRequest):
    result = MemoryPromotionService(_client()).promote_responsibility(**request.model_dump())
    if result.get("status") != "PROMOTED":
        raise HTTPException(status_code=409, detail=result)
    return result


@app.post("/memory/evidence/{evidence_id}/invalidate")
def invalidate_evidence(evidence_id: str, request: EvidenceInvalidationRequest):
    try:
        return KnowledgeInvalidationService(_client()).invalidate_evidence(evidence_id, **request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc




@app.post("/memory/dependencies/change")
def dependency_changed(request: DependencyChangeRequest):
    try:
        return KnowledgeInvalidationService(_client()).dependency_changed(**request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/memory/entity-resolution/{source_record_id}/changed")
def entity_resolution_changed(source_record_id: str, request: EntityResolutionChangeRequest):
    try:
        return KnowledgeInvalidationService(_client()).entity_resolution_changed(source_record_id, **request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/memory/outcomes/{outcome_id}/evaluate")
def evaluate_outcome_feedback(outcome_id: str, request: OutcomeFeedbackRequest):
    try:
        return KnowledgeInvalidationService(_client()).process_outcome_feedback(outcome_id, **request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/memory/claims/{old_claim_id}/supersede/{new_claim_id}")
def supersede_claim(old_claim_id: str, new_claim_id: str, request: ClaimSupersessionRequest):
    try:
        return KnowledgeInvalidationService(_client()).supersede_claim(old_claim_id, new_claim_id, **request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/memory/sources/{source_id}/authority")
def change_source_authority(source_id: str, request: SourceAuthorityRequest):
    try:
        return KnowledgeInvalidationService(_client()).source_authority_changed(source_id, **request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/memory/claims/{claim_id}/revalidate")
def revalidate_claim(claim_id: str, request: ClaimRevalidationRequest):
    try:
        result = KnowledgeInvalidationService(_client()).revalidate_claim(claim_id, **request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result.get("status") != "VALIDATED":
        raise HTTPException(status_code=409, detail=result)
    return result


@app.get("/memory/{entity_id}/impact")
def memory_impact(entity_id: str):
    return KnowledgeInvalidationService(_client()).get_impact(entity_id)


@app.get("/memory/{entity_id}/lineage")
def memory_lineage(entity_id: str):
    value = LearningWritebackService(_client()).get_artifact(entity_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return value


@app.get("/memory/stale")
def stale_memory():
    return KnowledgeInvalidationService(_client()).list_stale()

# ---------------------------------------------------------------------------
# Phase 8 — remaining deterministic Company Brain analytics
# ---------------------------------------------------------------------------

class BusFactorSimulationRequest(BaseModel):
    actor_ids: list[str] = Field(min_length=1, max_length=50)
    as_of: str | None = None


@app.get("/processes/{scope_id}/reconstruct")
def reconstruct_process(scope_id: str, as_of: str | None = None, max_events: int = Query(default=250, ge=1, le=500)):
    value = OrganizationalProcessReconstructionService(_client()).reconstruct(scope_id, as_of=as_of, max_events=max_events)
    if value is None:
        raise HTTPException(status_code=404, detail="Process scope not found")
    return value


@app.get("/incidents/{incident_id}/process")
def reconstruct_incident_process(incident_id: str, as_of: str | None = None, max_events: int = Query(default=250, ge=1, le=500)):
    value = OrganizationalProcessReconstructionService(_client()).reconstruct(incident_id, as_of=as_of, max_events=max_events)
    if value is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return value


@app.get("/processes/{scope_id}/policy-drift")
def process_policy_drift(scope_id: str, policy_id: str = Query(min_length=1), as_of: str | None = None):
    value = PolicyDriftService(_client()).analyze(scope_id, policy_id, as_of=as_of)
    if value is None:
        raise HTTPException(status_code=404, detail="Process scope not found")
    if value.get("reason") == "POLICY_NOT_FOUND":
        raise HTTPException(status_code=404, detail="Policy not found")
    return value


@app.get("/policies/{policy_id}/drift")
def policy_drift(policy_id: str, scope_id: str = Query(min_length=1), as_of: str | None = None):
    value = PolicyDriftService(_client()).analyze(scope_id, policy_id, as_of=as_of)
    if value is None:
        raise HTTPException(status_code=404, detail="Process scope not found")
    if value.get("reason") == "POLICY_NOT_FOUND":
        raise HTTPException(status_code=404, detail="Policy not found")
    return value


@app.get("/commitments")
def commitments(as_of: str | None = None, status: str | None = None, entity_id: str | None = None):
    return CommitmentTrackingService(_client()).list(as_of=as_of, status=status, entity_id=entity_id)


@app.get("/commitments/at-risk")
def commitments_at_risk(as_of: str | None = None):
    service = CommitmentTrackingService(_client())
    return [x for x in service.list(as_of=as_of) if x.get("status") in {"AT_RISK", "OVERDUE", "BREACHED"}]


@app.get("/commitments/{commitment_id}")
def commitment(commitment_id: str, as_of: str | None = None):
    value = CommitmentTrackingService(_client()).get(commitment_id, as_of=as_of)
    if value is None:
        raise HTTPException(status_code=404, detail="Commitment not found")
    return value


@app.get("/entities/{entity_id}/commitments")
def entity_commitments(entity_id: str, as_of: str | None = None):
    service = _service()
    if service.get_entity(entity_id) is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return CommitmentTrackingService(_client()).list(as_of=as_of, entity_id=entity_id)


@app.get("/organization/initiative-collisions")
def initiative_collisions(as_of: str | None = None, min_score: float = Query(default=0.0, ge=0.0, le=1.0), limit: int = Query(default=100, ge=1, le=200)):
    return InitiativeCollisionService(_client()).analyze(as_of=as_of, min_score=min_score, limit=limit)


@app.get("/projects/{project_id}/collisions")
def project_collisions(project_id: str, as_of: str | None = None, min_score: float = Query(default=0.0, ge=0.0, le=1.0), limit: int = Query(default=100, ge=1, le=200)):
    value = InitiativeCollisionService(_client()).analyze(as_of=as_of, project_id=project_id, min_score=min_score, limit=limit)
    if value.get("error") == "PROJECT_NOT_FOUND":
        raise HTTPException(status_code=404, detail="Project not found")
    return value


@app.get("/organization/bus-factor")
def organization_bus_factor(as_of: str | None = None, limit: int = Query(default=100, ge=1, le=300)):
    return BusFactorService(_client()).organization_summary(as_of=as_of, limit=limit)


@app.get("/people/{person_id}/bus-factor-impact")
def person_bus_factor(person_id: str, as_of: str | None = None):
    value = BusFactorService(_client()).actor_impact(person_id, as_of=as_of)
    if value is None:
        raise HTTPException(status_code=404, detail="Actor not found")
    return value


@app.post("/organization/bus-factor/simulate")
def simulate_bus_factor(request: BusFactorSimulationRequest):
    return BusFactorService(_client()).simulate_loss(request.actor_ids, as_of=request.as_of)


@app.get("/organization/network-analysis")
def organization_network_analysis(
    projection: str = Query(default="collaboration"),
    as_of: str | None = None,
    max_nodes: int = Query(default=300, ge=1, le=300),
    max_edges: int = Query(default=1500, ge=1, le=1500),
):
    try:
        return OrganizationalNetworkAnalysisService(_client()).analyze(projection, as_of=as_of, max_nodes=max_nodes, max_edges=max_edges)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/organization/bottlenecks")
def organization_bottlenecks(projection: str = Query(default="collaboration"), as_of: str | None = None):
    try:
        result = OrganizationalNetworkAnalysisService(_client()).analyze(projection, as_of=as_of)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "projection": projection,
        "articulation_points": result["articulation_points"],
        "overloaded_nodes": result["overloaded_nodes"],
        "single_path_risks": result["single_path_risks"],
        "as_of": as_of,
    }


@app.get("/organization/bridges")
def organization_bridges(projection: str = Query(default="collaboration"), as_of: str | None = None):
    try:
        result = OrganizationalNetworkAnalysisService(_client()).analyze(projection, as_of=as_of)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"projection": projection, "bridges": result["bridges"], "community_boundaries": result["community_boundaries"], "as_of": as_of}


@app.get("/organization/centrality")
def organization_centrality(projection: str = Query(default="collaboration"), as_of: str | None = None):
    try:
        result = OrganizationalNetworkAnalysisService(_client()).analyze(projection, as_of=as_of)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"projection": projection, "centrality": result["centrality"], "as_of": as_of}


# ---------------------------------------------------------------------------
# Phase 9 — organizational data ingestion
# ---------------------------------------------------------------------------

class IngestionSyncRequest(BaseModel):
    mode: str = Field(default="incremental", pattern="^(incremental|full)$")
    max_records: int = Field(default=100, ge=1, le=10_000)
    batch_size: int = Field(default=50, ge=1, le=500)
    dry_run: bool = False


class QuarantineResolveRequest(BaseModel):
    canonical_id: str = Field(min_length=1)
    reviewer_ref: str = "manual-review"


def _ingestion_pipeline() -> IngestionPipeline:
    import os
    from pathlib import Path
    from backend.app.ingestion.artifacts.local import LocalArtifactStore
    from backend.app.retrieval.indexing import RetrievalIndexer
    from backend.app.retrieval.lexical import BM25LexicalIndex
    from backend.app.retrieval.vector import LocalVectorIndex
    client = _client()
    root = Path(__file__).resolve().parents[2]
    artifact_root = Path(os.getenv("GRAPH_HACKS_ARTIFACT_ROOT") or root / ".graphhacks_artifacts")
    retrieval_root = Path(os.getenv("GRAPH_HACKS_RETRIEVAL_ROOT") or root / ".graphhacks_retrieval") / client.settings.tenant_id
    store = LocalArtifactStore(artifact_root)
    indexer = RetrievalIndexer(client, lexical=BM25LexicalIndex(retrieval_root / "lexical.json"), vector=LocalVectorIndex(path=retrieval_root / "vector.json"), artifact_store=store)
    return IngestionPipeline(client, registry=build_default_registry(client, persist=False), artifact_store=store, retrieval_indexer=indexer)


@app.get("/ingestion/sources")
def ingestion_sources():
    client = _client()
    registry = build_default_registry(client, persist=False)
    values = []
    for config in registry.configs():
        _, adapter = registry.get(config.id)
        health = adapter.health_check()
        values.append({**config.public_dict(), "health": health, "verification": "FIXTURE_VERIFIED" if config.fixture_path else "NOT_LIVE_VERIFIED"})
    return {"sources": values}


@app.post("/ingestion/sources/{source_id}/sync")
def ingestion_sync(source_id: str, request: IngestionSyncRequest):
    try:
        return _ingestion_pipeline().sync(source_id, **request.model_dump()).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=404 if "Unknown ingestion source" in str(exc) else 400, detail=str(exc)) from exc


@app.get("/ingestion/runs")
def ingestion_runs():
    return {"runs": _ingestion_pipeline().list_runs()}


@app.get("/ingestion/runs/{run_id}")
def ingestion_run(run_id: str):
    value = _ingestion_pipeline().get_run(run_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Ingestion run not found")
    return value


@app.get("/ingestion/quarantine")
def ingestion_quarantine(status: str | None = None):
    service = IngestionEntityResolutionService(_client())
    return {"records": service.list_quarantine(status=status)}


@app.get("/ingestion/quarantine/{record_id}")
def ingestion_quarantine_record(record_id: str):
    value = IngestionEntityResolutionService(_client()).get_quarantine(record_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Quarantine record not found")
    return value


@app.post("/ingestion/quarantine/{record_id}/resolve")
def ingestion_quarantine_resolve(record_id: str, request: QuarantineResolveRequest):
    try:
        return IngestionEntityResolutionService(_client()).resolve_quarantine(record_id, request.canonical_id, reviewer_ref=request.reviewer_ref)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/ingestion/artifacts/{artifact_id}")
def ingestion_artifact(artifact_id: str):
    value = _ingestion_pipeline().get_artifact_metadata(artifact_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return value

# ---------------------------------------------------------------------------
# Phase 10 — Graph-first retrieval / GraphRAG supporting infrastructure
# ---------------------------------------------------------------------------

class RetrievalSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    tenant_id: str | None = None
    requesting_agent_id: str | None = None
    task_id: str | None = None
    investigation_id: str | None = None
    situation_id: str | None = None
    seed_entity_ids: list[str] = Field(default_factory=list)
    as_of: str | None = None
    allowed_source_types: list[str] = Field(default_factory=list)
    retrieval_modes: list[str] = Field(default_factory=list)
    max_results: int = Field(default=10, ge=1, le=50)
    max_graph_hops: int = Field(default=3, ge=1, le=6)
    metadata_filters: dict = Field(default_factory=dict)
    evidence_requirements: list[str] = Field(default_factory=list)
    writeback: bool = True

    def to_domain(self):
        from backend.app.retrieval.models import RetrievalMode, RetrievalRequest
        modes=[]
        for value in self.retrieval_modes:
            try:modes.append(RetrievalMode(value.upper()))
            except ValueError as exc:raise ValueError(f"Unsupported retrieval mode: {value}") from exc
        return RetrievalRequest(
            query=self.query,tenant_id=self.tenant_id or _client().settings.tenant_id,requesting_agent_id=self.requesting_agent_id,
            task_id=self.task_id,investigation_id=self.investigation_id,situation_id=self.situation_id,seed_entity_ids=self.seed_entity_ids,
            as_of=self.as_of,allowed_source_types=self.allowed_source_types,retrieval_modes=modes,max_results=self.max_results,
            max_graph_hops=self.max_graph_hops,metadata_filters=self.metadata_filters,evidence_requirements=self.evidence_requirements,writeback=self.writeback,
        )


def _retrieval_service():
    import os
    from pathlib import Path
    from backend.app.retrieval.service import RetrievalService
    from backend.app.retrieval.lexical import BM25LexicalIndex
    from backend.app.retrieval.vector import LocalVectorIndex
    from backend.app.ingestion.artifacts.local import LocalArtifactStore
    client=_client();root=Path(__file__).resolve().parents[2]
    artifact_root=Path(os.getenv("GRAPH_HACKS_ARTIFACT_ROOT") or root / ".graphhacks_artifacts")
    retrieval_root=Path(os.getenv("GRAPH_HACKS_RETRIEVAL_ROOT") or root / ".graphhacks_retrieval") / client.settings.tenant_id
    return RetrievalService(
        client,
        lexical=BM25LexicalIndex(retrieval_root/"lexical.json"),
        vector=LocalVectorIndex(path=retrieval_root/"vector.json"),
        artifact_store=LocalArtifactStore(artifact_root),
    )


@app.post("/retrieval/graph-scope")
def retrieval_graph_scope(request: RetrievalSearchRequest):
    try:
        value=_retrieval_service().graph_scope(request.to_domain())
        if request.seed_entity_ids and not value.seed_entities:
            raise HTTPException(status_code=404, detail="No requested seed entity exists in tenant scope")
        return value.model_dump(mode="json")
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/retrieval/search")
def retrieval_search(request: RetrievalSearchRequest):
    try:
        value=_retrieval_service().search(request.to_domain())
        if request.seed_entity_ids and not value.graph_scope.seed_entities:
            raise HTTPException(status_code=404, detail="No requested seed entity exists in tenant scope")
        return value.model_dump(mode="json")
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/retrieval/lexical")
def retrieval_lexical(request: RetrievalSearchRequest):
    payload=request.model_copy(update={"retrieval_modes":["LEXICAL"]})
    return retrieval_search(payload)


@app.post("/retrieval/vector")
def retrieval_vector(request: RetrievalSearchRequest):
    payload=request.model_copy(update={"retrieval_modes":["VECTOR"]})
    return retrieval_search(payload)


@app.post("/retrieval/document")
def retrieval_document(request: RetrievalSearchRequest):
    payload=request.model_copy(update={"retrieval_modes":["DOCUMENT"]})
    return retrieval_search(payload)


@app.get("/retrieval/executions/{execution_id}")
def retrieval_execution(execution_id: str):
    value=_service().get_entity(execution_id)
    if value is None or "RetrievalExecution" not in set(value.get("_labels") or []):
        raise HTTPException(status_code=404, detail="Retrieval execution not found")
    return value


@app.get("/retrieval/evidence/{evidence_id}")
def retrieval_evidence(evidence_id: str):
    value=_service().get_entity(evidence_id)
    if value is None or "Evidence" not in set(value.get("_labels") or []):
        raise HTTPException(status_code=404, detail="Retrieval evidence not found")
    return value


@app.post("/retrieval/index/rebuild")
def retrieval_index_rebuild():
    import os
    from pathlib import Path
    from backend.app.retrieval.indexing import RetrievalIndexer
    from backend.app.retrieval.lexical import BM25LexicalIndex
    from backend.app.retrieval.vector import LocalVectorIndex
    from backend.app.ingestion.artifacts.local import LocalArtifactStore
    client=_client();repo_root=Path(__file__).resolve().parents[2]
    retrieval_root=Path(os.getenv("GRAPH_HACKS_RETRIEVAL_ROOT") or repo_root/".graphhacks_retrieval")/client.settings.tenant_id
    artifact_root=Path(os.getenv("GRAPH_HACKS_ARTIFACT_ROOT") or repo_root/".graphhacks_artifacts")
    result=RetrievalIndexer(
        client,
        lexical=BM25LexicalIndex(retrieval_root/"lexical.json"),
        vector=LocalVectorIndex(path=retrieval_root/"vector.json"),
        artifact_store=LocalArtifactStore(artifact_root),
    ).rebuild()
    return result
