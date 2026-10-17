from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request, status

from backend.app.api_v1.application import ExternalApiApplication, sanitize, stable_id
from backend.app.api_v1.errors import ApiError
from backend.app.api_v1.models import (
    ActionExecuteExternal, ActionProposalExternal, BusFactorExternal, CheckpointRequestExternal,
    ClaimRevalidateExternal, CounterfactualExternal, EvidenceInvalidateExternal, InvestigationCreate,
    ErrorResponse, PageResponse, PlanCreateExternal, RetrievalRequestExternal, SituationCreate, TaskActorRequest,
)
from backend.app.api_v1.security import Principal, authenticate, client_for, require
from backend.app.retrieval.models import RetrievalMode, RetrievalRequest
from backend.app.retrieval.service import RetrievalService
from backend.app.services.action_coordination_service import ActionCoordinationService
from backend.app.services.anomaly_service import GraphAnomalyService
from backend.app.services.authority_resolution_service import AuthorityResolutionService
from backend.app.services.company_brain_expertise_service import CompanyBrainExpertiseService
from backend.app.services.agent_registry_service import AgentRegistryService
from backend.app.services.blast_radius_service import BlastRadiusService
from backend.app.services.bus_factor_service import BusFactorService
from backend.app.services.claim_memory_service import ClaimMemoryService
from backend.app.services.commitment_service import CommitmentTrackingService
from backend.app.services.coordination_service import CoordinationService
from backend.app.services.decision_genealogy_service import DecisionGenealogyService
from backend.app.services.governance_service import GovernanceService
from backend.app.services.initiative_collision_service import InitiativeCollisionService
from backend.app.services.knowledge_invalidation_service import KnowledgeInvalidationService
from backend.app.services.organizational_network_service import OrganizationalNetworkAnalysisService
from backend.app.services.ownership_gap_service import OwnershipGapService
from backend.app.services.policy_drift_service import PolicyDriftService
from backend.app.services.process_reconstruction_service import OrganizationalProcessReconstructionService
from backend.app.services.simulation_service import CounterfactualSimulationService
from backend.app.services.temporal_service import TemporalService
from backend.app.services.work_planning_service import WorkPlanningService
from backend.app.services.phase4_graph import GraphSnapshot, has_label

router = APIRouter(prefix="/api/v1", responses={400:{"model":ErrorResponse},401:{"model":ErrorResponse},403:{"model":ErrorResponse},404:{"model":ErrorResponse},409:{"model":ErrorResponse},422:{"model":ErrorResponse},429:{"model":ErrorResponse},503:{"model":ErrorResponse}})

# Process-local replay protection for the HTTP boundary only. Canonical side-effect idempotency
# still belongs to the underlying Phase 6/9 services.
_idem_lock = threading.Lock()
_idem: dict[tuple[str, str, str], tuple[str, Any]] = {}
_rate_lock = threading.Lock()
_rate: dict[tuple[str, str, int], int] = {}
_simulations: dict[tuple[str, str], dict[str, Any]] = {}


def _app(principal: Principal) -> ExternalApiApplication:
    return ExternalApiApplication(client_for(principal))


def _retrieval_service_for(principal: Principal) -> RetrievalService:
    import os
    from pathlib import Path
    from backend.app.ingestion.artifacts.local import LocalArtifactStore
    from backend.app.retrieval.lexical import BM25LexicalIndex
    from backend.app.retrieval.vector import LocalVectorIndex
    client=client_for(principal)
    repo_root=Path(__file__).resolve().parents[3]
    artifact_root=Path(os.getenv("GRAPH_HACKS_ARTIFACT_ROOT") or repo_root/".graphhacks_artifacts")
    retrieval_root=Path(os.getenv("GRAPH_HACKS_RETRIEVAL_ROOT") or repo_root/".graphhacks_retrieval")/principal.tenant_id
    return RetrievalService(client,lexical=BM25LexicalIndex(retrieval_root/"lexical.json"),vector=LocalVectorIndex(path=retrieval_root/"vector.json"),artifact_store=LocalArtifactStore(artifact_root))


def _not_found(kind: str, entity_id: str):
    raise ApiError(404, "NOT_FOUND", f"{kind} {entity_id} was not found.", details={"id": entity_id, "resource": kind})


def _guard_rate(request: Request, principal: Principal, limit: int = 240) -> None:
    minute = int(time.time() // 60); key=(principal.subject, request.url.path, minute)
    with _rate_lock:
        count=_rate.get(key,0)+1; _rate[key]=count
    if count > limit:
        raise ApiError(429,"RATE_LIMITED","Rate limit exceeded for this endpoint.",details={"limit_per_minute":limit})


def _idempotent(principal: Principal, operation: str, key: str | None, payload: Any, fn):
    if not key:
        return fn()
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest(); k=(principal.tenant_id,operation,key)
    with _idem_lock:
        prior=_idem.get(k)
        if prior:
            if prior[0] != digest:
                raise ApiError(409,"CONFLICT","Idempotency-Key was already used with a different request.")
            return prior[1]
    result=fn()
    with _idem_lock:_idem[k]=(digest,result)
    return result


def _active_execution(coord: CoordinationService, task_id: str) -> str | None:
    board=coord.get_task_blackboard(task_id)
    if not board:return None
    items=[e for e in board.get("executions",[]) if str(e.get("status") or "").upper() in {"RUNNING","PAUSED","BLOCKED"}]
    items.sort(key=lambda e:str(e.get("started_at") or e.get("created_at") or ""),reverse=True)
    return str(items[0].get("id")) if items else None


@router.get("/capabilities", tags=["System"], summary="List public capabilities")
def capabilities():
    return {"api_version":"v1","graph_reasoning":True,"planning":True,"coordination":True,"learning":True,"company_brain_analytics":True,"ingestion":True,"graphrag":True,"external_api":True}

@router.get("/session", tags=["System"], summary="Get authenticated principal context")
def session(principal:Principal=Depends(authenticate)):
    return {"subject":principal.subject,"tenant_id":principal.tenant_id,"roles":list(principal.roles),"permissions":sorted(principal.permissions)}

@router.get("/ready", tags=["System"], summary="Check API dependency readiness")
def ready():
    try:
        from backend.app.graph.client import FalkorGraphClient
        health=FalkorGraphClient().health_check()
    except Exception as exc:
        raise ApiError(503,"DEPENDENCY_UNAVAILABLE","FalkorDB is unavailable.") from exc
    return {"ready":bool(health.get("ok")),"dependencies":{"falkordb":"ready" if health.get("ok") else "unavailable"}}

# -------------------- Situations --------------------
@router.get("/situations", response_model=PageResponse, tags=["Situations"], summary="List situations")
def list_situations(limit:int=Query(50,ge=1,le=100),cursor:str|None=None,status_filter:str|None=Query(None,alias="status"),as_of:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):
    return _app(principal).page(labels={"Incident"},status=status_filter,as_of=as_of,limit=limit,cursor=cursor)

@router.post("/situations", status_code=201, tags=["Situations"], summary="Create a situation")
def create_situation(body:SituationCreate, idempotency_key:str|None=Header(None,alias="Idempotency-Key"),principal:Principal=Depends(require("CREATE_INVESTIGATION"))):
    app=_app(principal); payload=body.model_dump(mode="json")
    return _idempotent(principal,"create-situation",idempotency_key,payload,lambda:app.create_situation(payload,subject=principal.subject,idempotency_key=idempotency_key))

@router.get("/situations/{situation_id}", tags=["Situations"], summary="Get a situation")
def get_situation(situation_id:str,as_of:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):
    value=_app(principal).get_node(situation_id,as_of=as_of)
    if value is None or not has_label(value,"Incident"):_not_found("Situation",situation_id)
    return value

@router.get("/situations/{situation_id}/context", tags=["Situations"], summary="Get bounded situation context")
def situation_context(situation_id:str,as_of:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):
    client=client_for(principal); app=ExternalApiApplication(client); node=app.get_node(situation_id,as_of=as_of)
    if node is None:_not_found("Situation",situation_id)
    snap=app.snapshot(); rels=app.relationships(situation_id,as_of=as_of)
    related=[x["neighbor"] for x in rels[:100]]
    return {"situation":node,"affected_entities":[x for x in related if set(x.get("_labels") or[])&{"System","Team","Project"}],"claims":[x for x in related if has_label(x,"Claim")],"evidence":[x for x in related if has_label(x,"Evidence")],"tasks":[x for x in related if has_label(x,"Task")],"relationships":rels[:100]}

@router.get("/situations/{situation_id}/timeline", tags=["Situations"], summary="Get situation timeline")
def situation_timeline(situation_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal)
    if app.get_node(situation_id) is None:_not_found("Situation",situation_id)
    return {"situation_id":situation_id,"events":TemporalService(app.client).reconstruct_incident_timeline(situation_id)}

@router.get("/situations/{situation_id}/claims", tags=["Situations"], summary="List situation claims")
def situation_claims(situation_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal)
    if app.get_node(situation_id) is None:_not_found("Situation",situation_id)
    return {"items":ClaimMemoryService(app.client).get_claims_about(situation_id)}

@router.get("/situations/{situation_id}/evidence", tags=["Situations"], summary="List situation evidence")
def situation_evidence(situation_id:str,principal:Principal=Depends(require("READ_EVIDENCE"))):
    app=_app(principal); snap=app.snapshot()
    if situation_id not in snap.nodes:_not_found("Situation",situation_id)
    ids={e.source for e in snap.edges_to(situation_id,{"ABOUT"}) if has_label(snap.node(e.source),"Evidence")}
    return {"items":[sanitize(snap.node(i)) for i in sorted(ids)]}

@router.get("/situations/{situation_id}/tasks", tags=["Situations"], summary="List situation tasks")
def situation_tasks(situation_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal); snap=app.snapshot()
    if situation_id not in snap.nodes:_not_found("Situation",situation_id)
    ids={e.source for e in snap.edges_to(situation_id,{"ABOUT","ADDRESSES"}) if has_label(snap.node(e.source),"Task")}
    return {"items":[sanitize(snap.node(i)) for i in sorted(ids)]}

@router.post("/situations/{situation_id}/investigate", status_code=201, tags=["Situations"], summary="Create an investigation for a situation")
def investigate_situation(situation_id:str,body:InvestigationCreate,idempotency_key:str|None=Header(None,alias="Idempotency-Key"),principal:Principal=Depends(require("CREATE_INVESTIGATION"))):
    payload=body.model_dump(mode="json"); payload["situation_id"]=situation_id; app=_app(principal)
    if app.get_node(situation_id) is None:_not_found("Situation",situation_id)
    return _idempotent(principal,"create-investigation",idempotency_key,payload,lambda:app.create_investigation(payload,subject=principal.subject,idempotency_key=idempotency_key))

# -------------------- Investigations / retrieval --------------------
@router.post("/investigations", status_code=201, tags=["Investigations"], summary="Create an investigation")
def create_investigation(body:InvestigationCreate,idempotency_key:str|None=Header(None,alias="Idempotency-Key"),principal:Principal=Depends(require("CREATE_INVESTIGATION"))):
    app=_app(principal); payload=body.model_dump(mode="json")
    result=_idempotent(principal,"create-investigation",idempotency_key,payload,lambda:app.create_investigation(payload,subject=principal.subject,idempotency_key=idempotency_key))
    if result.get("error") == "SITUATION_NOT_FOUND":_not_found("Situation",body.situation_id)
    return result

@router.get("/investigations/{investigation_id}", tags=["Investigations"], summary="Get an investigation")
def get_investigation(investigation_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    value=_app(principal).get_node(investigation_id)
    if value is None or not has_label(value,"Investigation"):_not_found("Investigation",investigation_id)
    return value

@router.get("/investigations/{investigation_id}/findings", tags=["Investigations"], summary="List investigation findings")
def investigation_findings(investigation_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal)
    if app.get_node(investigation_id) is None:_not_found("Investigation",investigation_id)
    return {"items":app.investigation_links(investigation_id,{"Finding"})}

@router.get("/investigations/{investigation_id}/evidence", tags=["Investigations"], summary="List investigation evidence")
def investigation_evidence(investigation_id:str,principal:Principal=Depends(require("READ_EVIDENCE"))):
    app=_app(principal); snap=app.snapshot()
    if app.get_node(investigation_id) is None:_not_found("Investigation",investigation_id)
    evidence=app.investigation_links(investigation_id,{"Evidence"},{"ABOUT"}); retrieval_ids={e.target for e in snap.edges_from(investigation_id,{"HAS_RETRIEVAL"})}
    items=[]
    for item in evidence:
        eid=str(item.get("id")); executions=sorted({e.source for e in snap.edges_to(eid,{"RETURNED"}) if e.source in retrieval_ids})
        items.append({**item,"retrieval_execution_ids":executions,"retrieval_provenance_complete":bool(executions)})
    return {"items":items}

@router.get("/investigations/{investigation_id}/retrievals", tags=["Investigations"], summary="List retrieval executions")
def investigation_retrievals(investigation_id:str,principal:Principal=Depends(require("READ_EVIDENCE"))):
    app=_app(principal)
    if app.get_node(investigation_id) is None:_not_found("Investigation",investigation_id)
    return {"items":app.investigation_links(investigation_id,{"RetrievalExecution"},{"HAS_RETRIEVAL"})}

@router.post("/investigations/{investigation_id}/retrieve", tags=["Retrieval","Investigations"], summary="Run graph-first retrieval for an investigation")
def investigation_retrieve(investigation_id:str,body:RetrievalRequestExternal,request:Request,principal:Principal=Depends(require("READ_EVIDENCE"))):
    _guard_rate(request,principal); app=_app(principal); inv=app.get_node(investigation_id)
    if inv is None or not has_label(inv,"Investigation"):_not_found("Investigation",investigation_id)
    seeds=body.seed_entity_ids or [s for s in str(inv.get("seed_entity_ids_csv") or "").split(",") if s]
    modes=[]
    for raw in body.retrieval_modes:
        try:modes.append(RetrievalMode(raw.upper()))
        except ValueError as exc:raise ApiError(422,"VALIDATION_FAILED",f"Unsupported retrieval mode: {raw}") from exc
    req=RetrievalRequest(query=body.query,tenant_id=principal.tenant_id,investigation_id=investigation_id,seed_entity_ids=seeds,as_of=body.as_of or inv.get("as_of"),retrieval_modes=modes,max_results=body.max_results,max_graph_hops=body.max_graph_hops,metadata_filters=body.metadata_filters,writeback=True)
    result=_retrieval_service_for(principal).search(req)
    return result.model_dump(mode="json")

@router.post("/investigations/{investigation_id}/close", tags=["Investigations"], summary="Close an investigation")
def close_investigation(investigation_id:str,principal:Principal=Depends(require("CREATE_INVESTIGATION"))):
    value=_app(principal).close_investigation(investigation_id,subject=principal.subject)
    if value is None:_not_found("Investigation",investigation_id)
    return value

# -------------------- Entities / graph --------------------
@router.get("/entities/search", tags=["Entities"], summary="Search canonical entities")
def entity_search(q:str=Query(min_length=1),limit:int=Query(20,ge=1,le=100),principal:Principal=Depends(require("READ_GRAPH"))):
    snap=_app(principal).snapshot(); needle=q.casefold(); values=[]
    for n in snap.nodes.values():
        if any(needle in str(n.get(k) or "").casefold() for k in ("id","name","display_name","title","email")):
            values.append(sanitize(n))
    values.sort(key=lambda n:(0 if str(n.get("id","")).casefold()==needle else 1,str(n.get("id"))))
    return {"items":values[:limit],"limit":limit}

@router.get("/entities/{entity_id}", tags=["Entities"], summary="Get a canonical entity")
def entity_get(entity_id:str,as_of:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):
    value=_app(principal).get_node(entity_id,as_of=as_of)
    if value is None:_not_found("Entity",entity_id)
    return value

@router.get("/entities/{entity_id}/neighbors", tags=["Entities"], summary="Get bounded entity neighbors")
def entity_neighbors(entity_id:str,as_of:str|None=None,limit:int=Query(50,ge=1,le=100),principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal)
    if app.get_node(entity_id,as_of=as_of) is None:_not_found("Entity",entity_id)
    return {"items":app.relationships(entity_id,as_of=as_of)[:limit],"limit":limit}

@router.get("/entities/{entity_id}/relationships", tags=["Entities"], summary="Get entity relationships")
def entity_relationships(entity_id:str,relationship_type:list[str]|None=Query(None),as_of:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal)
    if app.get_node(entity_id,as_of=as_of) is None:_not_found("Entity",entity_id)
    return {"items":app.relationships(entity_id,as_of=as_of,rel_types=set(relationship_type or [] ) or None)}

@router.get("/entities/{entity_id}/provenance", tags=["Entities"], summary="Get entity provenance summary")
def entity_provenance(entity_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal)
    if app.get_node(entity_id) is None:_not_found("Entity",entity_id)
    return app.provenance_summary(entity_id)

@router.get("/entities/{entity_id}/history", tags=["History","Entities"], summary="Get entity temporal history")
def entity_history(entity_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal); snap=app.snapshot(); node=snap.node(entity_id)
    if node is None:_not_found("Entity",entity_id)
    edges=[e.as_dict() for e in snap.edges if e.source==entity_id or e.target==entity_id]
    edges.sort(key=lambda e:str(e["properties"].get("valid_from") or ""))
    return {"entity":sanitize(node),"relationship_history":sanitize(edges)}

PATH_PROFILES={
    "DEPENDENCY":{"DEPENDS_ON","AFFECTS"},"RESPONSIBILITY":{"OWNS","RESPONSIBLE_FOR","EXPERT_IN","MEMBER_OF"},
    "EVIDENCE":{"SUPPORTS","REFUTES","ABOUT","DERIVED_FROM","PRODUCED"},"DECISION_GENEALOGY":{"BASED_ON","SUPPORTS","REFUTES","GOVERNS","APPROVED_BY","HAS_OUTCOME"},
    "PROCESS":{"BEFORE","TRIGGERED","REQUIRES","BLOCKED_BY","CAUSE","ABOUT","PRODUCED"},
}
@router.get("/paths", tags=["Graph"], summary="Find bounded canonical graph paths")
def paths(request:Request,from_id:str=Query(alias="from"),to_id:str=Query(alias="to"),max_hops:int=Query(4,ge=1,le=6),profile:str|None=None,relationship_types:list[str]|None=Query(None),as_of:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):
    _guard_rate(request,principal); app=_app(principal); snap=app.snapshot()
    if from_id not in snap.nodes:_not_found("Entity",from_id)
    if to_id not in snap.nodes:_not_found("Entity",to_id)
    rels=set(relationship_types or []) or (PATH_PROFILES.get(str(profile or "").upper()) if profile else None)
    values=snap.bounded_paths(from_id,targets={to_id},rel_types=rels,max_depth=max_hops,max_paths=20,as_of=as_of)
    return {"from":from_id,"to":to_id,"max_hops":max_hops,"as_of":as_of,"paths":values}

@router.get("/entities/{entity_id}/blast-radius", tags=["Graph"], summary="Compute bounded blast radius")
def blast_radius(entity_id:str,request:Request,max_depth:int=Query(6,ge=1,le=8),as_of:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):
    _guard_rate(request,principal); value=BlastRadiusService(client_for(principal)).analyze(entity_id,max_depth=max_depth,as_of=as_of)
    if value is None:_not_found("Entity",entity_id)
    return value

# -------------------- Claims / Evidence --------------------
@router.get("/claims", response_model=PageResponse, tags=["Claims"], summary="List claims")
def claims_list(limit:int=Query(50,ge=1,le=100),cursor:str|None=None,status_filter:str|None=Query(None,alias="status"),as_of:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):
    return _app(principal).page(labels={"Claim"},status=status_filter,as_of=as_of,limit=limit,cursor=cursor)

@router.get("/claims/{claim_id}", tags=["Claims"], summary="Get claim")
def claim_get(claim_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    value=ClaimMemoryService(client_for(principal)).get_claim(claim_id)
    if value is None:_not_found("Claim",claim_id)
    # External Claim resources expose the canonical claim fields at the top
    # level; service-only enrichment stays alongside them rather than nesting
    # the resource under an internal `claim` key.
    payload=dict(value)
    claim=dict(payload.pop("claim",{}) or {})
    return sanitize({**claim,**payload})

@router.get("/claims/{claim_id}/evidence", tags=["Claims"], summary="Get claim evidence")
def claim_evidence(claim_id:str,principal:Principal=Depends(require("READ_EVIDENCE"))):
    svc=ClaimMemoryService(client_for(principal))
    if svc.get_claim(claim_id) is None:_not_found("Claim",claim_id)
    return svc.get_claim_evidence(claim_id)

@router.get("/claims/{claim_id}/conflicts", tags=["Claims"], summary="Get conflicting claims")
def claim_conflicts(claim_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal); snap=app.snapshot()
    if snap.node(claim_id) is None:_not_found("Claim",claim_id)
    ids={nid for nid,e,_ in snap.neighbors(claim_id,{"CONTRADICTS"},direction="both") if has_label(snap.node(nid),"Claim")}
    return {"claim_id":claim_id,"items":[sanitize(snap.node(i)) for i in sorted(ids)]}

@router.get("/claims/{claim_id}/lineage", tags=["Claims"], summary="Get claim lineage")
def claim_lineage(claim_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal)
    if app.get_node(claim_id) is None:_not_found("Claim",claim_id)
    return {"claim_id":claim_id,"relationships":app.relationships(claim_id,rel_types={"DERIVED_FROM","PROMOTED_TO","VALIDATED_BY","SUPPORTS","REFUTES","SUPERSEDES"})}

@router.post("/claims/{claim_id}/revalidate", tags=["Claims"], summary="Revalidate a claim through Phase 7")
def claim_revalidate(claim_id:str,body:ClaimRevalidateExternal,principal:Principal=Depends(require("WRITE_FINDING"))):
    try:result=KnowledgeInvalidationService(client_for(principal)).revalidate_claim(claim_id,**body.model_dump())
    except ValueError as exc:raise ApiError(404,"NOT_FOUND",str(exc)) from exc
    if result.get("status")!="VALIDATED":raise ApiError(409,"INVALID_STATE_TRANSITION","Claim could not be revalidated.",details=result)
    return result

@router.get("/evidence", response_model=PageResponse, tags=["Evidence"], summary="List evidence")
def evidence_list(limit:int=Query(50,ge=1,le=100),cursor:str|None=None,as_of:str|None=None,principal:Principal=Depends(require("READ_EVIDENCE"))):
    return _app(principal).page(labels={"Evidence"},as_of=as_of,limit=limit,cursor=cursor)

@router.get("/evidence/{evidence_id}", tags=["Evidence"], summary="Get evidence")
def evidence_get(evidence_id:str,principal:Principal=Depends(require("READ_EVIDENCE"))):
    value=_app(principal).get_node(evidence_id)
    if value is None or not has_label(value,"Evidence"):_not_found("Evidence",evidence_id)
    return value

@router.get("/evidence/{evidence_id}/provenance", tags=["Evidence"], summary="Get evidence provenance")
def evidence_provenance(evidence_id:str,principal:Principal=Depends(require("READ_EVIDENCE"))):
    app=_app(principal)
    if app.get_node(evidence_id) is None:_not_found("Evidence",evidence_id)
    return app.provenance_summary(evidence_id)

@router.get("/evidence/{evidence_id}/artifact", tags=["Evidence"], summary="Get linked artifact metadata")
def evidence_artifact(evidence_id:str,principal:Principal=Depends(require("READ_EVIDENCE"))):
    app=_app(principal); snap=app.snapshot()
    if snap.node(evidence_id) is None:_not_found("Evidence",evidence_id)
    artifacts=[sanitize(snap.node(e.target)) for e in snap.edges_from(evidence_id,{"DERIVED_FROM"}) if has_label(snap.node(e.target),"Artifact")]
    return {"evidence_id":evidence_id,"artifacts":artifacts}

@router.post("/evidence/{evidence_id}/invalidate", tags=["Evidence"], summary="Invalidate evidence through Phase 7")
def evidence_invalidate(evidence_id:str,body:EvidenceInvalidateExternal,principal:Principal=Depends(require("WRITE_FINDING"))):
    try:return KnowledgeInvalidationService(client_for(principal)).invalidate_evidence(evidence_id,**body.model_dump())
    except ValueError as exc:raise ApiError(404,"NOT_FOUND",str(exc)) from exc

# -------------------- Plans --------------------
@router.get("/plans", response_model=PageResponse, tags=["Tasks"], summary="List plans")
def plans_list(limit:int=Query(50,ge=1,le=100),cursor:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):
    return _app(principal).page(labels={"Plan"},limit=limit,cursor=cursor)

@router.post("/plans", status_code=201, tags=["Tasks"], summary="Create a graph-backed work plan")
def plan_create(body:PlanCreateExternal,idempotency_key:str|None=Header(None,alias="Idempotency-Key"),principal:Principal=Depends(require("CREATE_PLAN"))):
    payload=body.model_dump(mode="json"); client=client_for(principal)
    def invoke():
        try:value=WorkPlanningService(client).generate_plan(body.situation_id,body.goal,selected_hypotheses=body.selected_hypotheses,selected_claims=body.selected_claims,knowledge_gaps=body.knowledge_gaps,constraints=body.constraints,as_of=body.as_of)
        except ValueError as exc:raise ApiError(400,"INVALID_REQUEST",str(exc)) from exc
        if value is None:_not_found("Situation",body.situation_id)
        return value
    return _idempotent(principal,"create-plan",idempotency_key,payload,invoke)

@router.get("/plans/{plan_id}", tags=["Tasks"], summary="Get plan")
def plan_get(plan_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    value=WorkPlanningService(client_for(principal)).get_plan(plan_id)
    if value is None:_not_found("Plan",plan_id)
    return value

@router.get("/plans/{plan_id}/tasks", tags=["Tasks"], summary="Get plan tasks")
def plan_tasks(plan_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    value=WorkPlanningService(client_for(principal)).get_plan_tasks(plan_id)
    if value is None:_not_found("Plan",plan_id)
    return value

# -------------------- Tasks / Agents --------------------
@router.get("/tasks", response_model=PageResponse, tags=["Tasks"], summary="List and filter tasks")
def tasks_list(limit:int=Query(50,ge=1,le=100),cursor:str|None=None,status_filter:str|None=Query(None,alias="status"),task_type:str|None=None,plan_id:str|None=None,owner_id:str|None=None,ready_only:bool=False,principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal); page=app.page(labels={"Task"},status=status_filter,filters={"task_type":task_type} if task_type else {},limit=100,cursor=cursor)
    snap=app.snapshot(); items=page["items"]
    if plan_id:items=[n for n in items if any(e.source==plan_id and e.target==n["id"] and e.type=="PLAN_HAS_TASK" for e in snap.edges)]
    if owner_id:items=[n for n in items if any(e.source==n["id"] and e.target==owner_id and e.type=="CLAIMED_BY" and snap._edge_active(e,None) for e in snap.edges)]
    if ready_only:items=[n for n in items if str(n.get("status") or "").upper()=="READY"]
    page["items"]=items[:limit]; page["has_more"]=page["has_more"] or len(items)>limit; page["limit"]=limit
    return page

@router.get("/tasks/{task_id}", tags=["Tasks"], summary="Get task")
def task_get(task_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    value=WorkPlanningService(client_for(principal)).get_task(task_id)
    if value is None:_not_found("Task",task_id)
    return value

@router.get("/tasks/{task_id}/dependencies", tags=["Tasks"], summary="Get task prerequisites")
def task_dependencies(task_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    value=WorkPlanningService(client_for(principal)).get_prerequisites(task_id)
    if value is None:_not_found("Task",task_id)
    return value

@router.get("/tasks/{task_id}/coordination-state", tags=["Tasks"], summary="Get task coordination blackboard")
def task_blackboard(task_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    value=CoordinationService(client_for(principal)).get_task_blackboard(task_id)
    if value is None:_not_found("Task",task_id)
    return value

@router.get("/tasks/{task_id}/execution", tags=["Tasks"], summary="Get latest task execution")
def task_execution(task_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    coord=CoordinationService(client_for(principal)); board=coord.get_task_blackboard(task_id)
    if board is None:_not_found("Task",task_id)
    executions=board.get("executions") or []
    if not executions:return {"task_id":task_id,"execution":None}
    executions.sort(key=lambda x:str(x.get("started_at") or x.get("created_at") or ""),reverse=True)
    return coord.get_execution_state(str(executions[0].get("id")),include_archived=True)

@router.post("/tasks/{task_id}/claim", tags=["Tasks"], summary="Claim a ready task")
def task_claim(task_id:str,body:TaskActorRequest,principal:Principal=Depends(require("CLAIM_TASK"))):
    try:return CoordinationService(client_for(principal)).claim_task(task_id,body.agent_id)
    except ValueError as exc:raise ApiError(409,"INVALID_STATE_TRANSITION",str(exc)) from exc

@router.post("/tasks/{task_id}/start", tags=["Tasks"], summary="Start task execution")
def task_start(task_id:str,body:TaskActorRequest,principal:Principal=Depends(require("CLAIM_TASK"))):
    try:return CoordinationService(client_for(principal)).start_execution(task_id,body.agent_id)
    except ValueError as exc:raise ApiError(409,"INVALID_STATE_TRANSITION",str(exc)) from exc

@router.post("/tasks/{task_id}/checkpoint", tags=["Tasks"], summary="Save task checkpoint")
def task_checkpoint(task_id:str,body:CheckpointRequestExternal,principal:Principal=Depends(require("WRITE_FINDING"))):
    coord=CoordinationService(client_for(principal)); eid=body.execution_id or _active_execution(coord,task_id)
    if not eid:raise ApiError(409,"INVALID_STATE_TRANSITION","Task has no active execution.")
    try:return coord.save_checkpoint(eid,body.agent_id,step_index=body.step_index,current_step=body.current_step,completed_steps=body.completed_steps,pending_steps=body.pending_steps,state_summary=body.state_summary,last_error=body.last_error)
    except ValueError as exc:raise ApiError(409,"INVALID_STATE_TRANSITION",str(exc)) from exc

@router.post("/tasks/{task_id}/resume", tags=["Tasks"], summary="Resume task execution")
def task_resume(task_id:str,body:TaskActorRequest,principal:Principal=Depends(require("CLAIM_TASK"))):
    coord=CoordinationService(client_for(principal)); eid=body.execution_id or _active_execution(coord,task_id)
    if not eid:
        board=coord.get_task_blackboard(task_id)
        if not board or not board.get("executions"):raise ApiError(409,"INVALID_STATE_TRANSITION","Task has no execution to resume.")
        eid=str(board["executions"][-1]["id"])
    try:return coord.resume_execution(eid,body.agent_id)
    except ValueError as exc:raise ApiError(409,"INVALID_STATE_TRANSITION",str(exc)) from exc

@router.get("/agents", response_model=PageResponse, tags=["Agents"], summary="List agents")
def agents_list(limit:int=Query(50,ge=1,le=100),cursor:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):return _app(principal).page(labels={"Agent"},limit=limit,cursor=cursor)

@router.get("/agents/{agent_id}", tags=["Agents"], summary="Get agent")
def agent_get(agent_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    value=AgentRegistryService(client_for(principal)).get_agent(agent_id)
    if value is None:_not_found("Agent",agent_id)
    return sanitize(value)

@router.get("/agents/{agent_id}/tasks", tags=["Agents"], summary="Get agent work")
def agent_tasks(agent_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    value=CoordinationService(client_for(principal)).get_agent_work(agent_id)
    if value is None:_not_found("Agent",agent_id)
    return value

@router.get("/agents/{agent_id}/capabilities", tags=["Agents"], summary="Get agent capabilities")
def agent_capabilities(agent_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    value=AgentRegistryService(client_for(principal)).get_agent(agent_id)
    if value is None:_not_found("Agent",agent_id)
    return {"agent_id":agent_id,"agent_type":value.get("agent_type"),"capabilities":value.get("capabilities") or value.get("capabilities_csv"),"permissions":value.get("permissions") or value.get("permissions_csv"),"availability":value.get("availability"),"status":value.get("status")}

# -------------------- Decisions / Actions --------------------
@router.get("/decisions", response_model=PageResponse, tags=["Decisions"], summary="List decisions")
def decisions_list(limit:int=Query(50,ge=1,le=100),cursor:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):return _app(principal).page(labels={"Decision"},limit=limit,cursor=cursor)

@router.get("/decisions/{decision_id}", tags=["Decisions"], summary="Get decision")
def decision_get(decision_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    value=_app(principal).get_node(decision_id)
    if value is None or not has_label(value,"Decision"):_not_found("Decision",decision_id)
    return value

@router.get("/decisions/{decision_id}/genealogy", tags=["Decisions"], summary="Replay decision genealogy")
def decision_genealogy(decision_id:str,as_of:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):
    value=DecisionGenealogyService(client_for(principal)).replay(decision_id,as_of=as_of)
    if value is None:_not_found("Decision",decision_id)
    return value

@router.get("/decisions/{decision_id}/evidence", tags=["Decisions"], summary="Get decision evidence")
def decision_evidence(decision_id:str,principal:Principal=Depends(require("READ_EVIDENCE"))):
    value=decision_genealogy(decision_id,None,principal)
    return {"decision_id":decision_id,"evidence":value.get("evidence",[]) if isinstance(value,dict) else []}

@router.get("/decisions/{decision_id}/outcomes", tags=["Decisions"], summary="Get decision outcomes")
def decision_outcomes(decision_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal); snap=app.snapshot()
    if snap.node(decision_id) is None:_not_found("Decision",decision_id)
    ids=set()
    for action,edge,_ in snap.neighbors(decision_id,{"PROPOSED_ACTION","BASED_ON"},direction="both"):
        if has_label(snap.node(action),"Action"):
            ids.update(e.target for e in snap.edges_from(action,{"HAS_OUTCOME"}) if has_label(snap.node(e.target),"Outcome"))
    return {"decision_id":decision_id,"outcomes":[sanitize(snap.node(i)) for i in sorted(ids)]}

@router.get("/actions", response_model=PageResponse, tags=["Actions"], summary="List actions")
def actions_list(limit:int=Query(50,ge=1,le=100),cursor:str|None=None,status_filter:str|None=Query(None,alias="status"),principal:Principal=Depends(require("READ_GRAPH"))):return _app(principal).page(labels={"Action"},status=status_filter,limit=limit,cursor=cursor)

@router.get("/actions/{action_id}", tags=["Actions"], summary="Get action")
def action_get(action_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    value=ActionCoordinationService(client_for(principal)).get_action(action_id)
    if value is None:_not_found("Action",action_id)
    return value

@router.get("/actions/{action_id}/governance", tags=["Actions"], summary="Inspect action governance")
def action_governance(action_id:str,agent_id:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal)
    if app.get_node(action_id) is None:_not_found("Action",action_id)
    return GovernanceService(app.client).evaluate_action(action_id,agent_id=agent_id)

@router.post("/actions", status_code=201, tags=["Actions"], summary="Propose governed action")
def action_propose(body:ActionProposalExternal,idempotency_key:str|None=Header(None,alias="Idempotency-Key"),principal:Principal=Depends(require("PROPOSE_ACTION"))):
    client=client_for(principal); payload=body.model_dump(mode="json")
    def invoke():
        try:return ActionCoordinationService(client).propose_action(body.task_id,body.agent_id,action_id=body.action_id,name=body.name,action_type=body.action_type,target_ids=body.target_ids,idempotency_key=idempotency_key,approval_required=body.approval_required)
        except ValueError as exc:raise ApiError(409,"INVALID_STATE_TRANSITION",str(exc)) from exc
    return _idempotent(principal,"propose-action",idempotency_key,payload,invoke)

@router.post("/actions/{action_id}/execute", tags=["Actions"], summary="Execute action through Phase 6 governance")
def action_execute(action_id:str,body:ActionExecuteExternal,idempotency_key:str|None=Header(None,alias="Idempotency-Key"),principal:Principal=Depends(require("EXECUTE_ACTION"))):
    payload={"action_id":action_id,**body.model_dump(mode="json")}
    def invoke():
        try:return ActionCoordinationService(client_for(principal)).execute_action(action_id,body.agent_id,lease_seconds=body.lease_seconds)
        except ValueError as exc:raise ApiError(409,"INVALID_STATE_TRANSITION",str(exc)) from exc
    return _idempotent(principal,"execute-action",idempotency_key,payload,invoke)

@router.get("/actions/{action_id}/attempts", tags=["Actions"], summary="Get action attempts")
def action_attempts(action_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal); snap=app.snapshot()
    if snap.node(action_id) is None:_not_found("Action",action_id)
    ids=[e.target for e in snap.edges_from(action_id,{"HAS_ATTEMPT"})]
    return {"action_id":action_id,"items":[sanitize(snap.node(i)) for i in ids if snap.node(i)]}

# -------------------- Simulations / history --------------------
@router.post("/simulations/counterfactual", tags=["Simulations"], summary="Run non-mutating counterfactual simulation")
def simulate_counterfactual(body:CounterfactualExternal,request:Request,principal:Principal=Depends(require("READ_ORG_ANALYTICS"))):
    _guard_rate(request,principal); svc=CounterfactualSimulationService(client_for(principal))
    before_count=len(GraphSnapshot.load(svc.client).nodes)
    operations=[]
    for raw in body.interventions:
        item=dict(raw); kind=str(item.get("op") or item.get("type") or "").lower()
        if kind: item["op"]=kind
        if "source_id" not in item and item.get("source") is not None:item["source_id"]=item.get("source")
        if "target_id" not in item and item.get("target") is not None:item["target_id"]=item.get("target")
        operations.append(item)
    try:value=svc.simulate(body.situation_id,operations,max_depth=body.max_depth)
    except ValueError as exc:raise ApiError(400,"INVALID_REQUEST",str(exc)) from exc
    if value is None:_not_found("Situation",body.situation_id)
    sid=stable_id("SIM-API-",principal.tenant_id,"counterfactual",body.model_dump(mode="json")); result={"simulation_id":sid,"simulation_type":"COUNTERFACTUAL","result":value,"canonical_node_count_before":before_count,"persisted":False}
    _simulations[(principal.tenant_id,sid)]=result; return result

@router.post("/simulations/bus-factor", tags=["Simulations"], summary="Simulate actor loss without graph mutation")
def simulate_bus_factor(body:BusFactorExternal,request:Request,principal:Principal=Depends(require("READ_ORG_ANALYTICS"))):
    _guard_rate(request,principal); value=BusFactorService(client_for(principal)).simulate_loss(body.actor_ids,as_of=body.as_of); sid=stable_id("SIM-API-",principal.tenant_id,"bus-factor",body.model_dump(mode="json")); result={"simulation_id":sid,"simulation_type":"BUS_FACTOR","result":value,"persisted":False}; _simulations[(principal.tenant_id,sid)]=result; return result

@router.get("/simulations/{simulation_id}", tags=["Simulations"], summary="Get process-local simulation result")
def simulation_get(simulation_id:str,principal:Principal=Depends(require("READ_ORG_ANALYTICS"))):
    value=_simulations.get((principal.tenant_id,simulation_id))
    if value is None:_not_found("Simulation",simulation_id)
    return value

@router.get("/history/entities/{entity_id}", tags=["History"], summary="Get entity history")
def history_entity(entity_id:str,principal:Principal=Depends(require("READ_GRAPH"))):return entity_history(entity_id,principal)

@router.get("/history/entities/{entity_id}/at", tags=["History"], summary="Reconstruct entity at a point in time")
def history_entity_at(entity_id:str,as_of:str=Query(min_length=1),principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal); value=app.get_node(entity_id,as_of=as_of)
    if value is None:_not_found("Entity",entity_id)
    return {"as_of":as_of,"entity":value,"relationships":app.relationships(entity_id,as_of=as_of)}

@router.get("/history/situations/{situation_id}", tags=["History"], summary="Get situation timeline")
def history_situation(situation_id:str,principal:Principal=Depends(require("READ_GRAPH"))):return situation_timeline(situation_id,principal)

# -------------------- Phase 12 thin analytics facades --------------------
@router.get("/anomalies", tags=["Risks"], summary="Detect explainable graph anomalies")
def anomalies(principal:Principal=Depends(require("READ_ORG_ANALYTICS"))):
    return GraphAnomalyService(client_for(principal)).detect()

@router.get("/conflicts/{entity_id}/resolve", tags=["Claims"], summary="Resolve explicit subject conflicts using authority rules")
def conflict_authority_resolution(entity_id:str,as_of:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal)
    if app.get_node(entity_id,as_of=as_of) is None:_not_found("Entity",entity_id)
    return AuthorityResolutionService(app.client).resolve_subject_conflicts(entity_id,as_of=as_of)

@router.get("/company-brain/expertise", tags=["Risks"], summary="List bounded organizational expertise coverage")
def company_brain_expertise(as_of:str|None=None,limit:int=Query(200,ge=1,le=500),principal:Principal=Depends(require("READ_ORG_ANALYTICS"))):
    return CompanyBrainExpertiseService(client_for(principal)).list(as_of=as_of,limit=limit)

# -------------------- Processes / Risks --------------------
@router.get("/processes/{scope_id}", tags=["Processes"], summary="Reconstruct organizational process")
def process_get(scope_id:str,as_of:str|None=None,max_events:int=Query(250,ge=1,le=500),principal:Principal=Depends(require("READ_ORG_ANALYTICS"))):
    value=OrganizationalProcessReconstructionService(client_for(principal)).reconstruct(scope_id,as_of=as_of,max_events=max_events)
    if value is None:_not_found("Process scope",scope_id)
    return value

@router.get("/processes/{scope_id}/timeline", tags=["Processes"], summary="Get reconstructed process timeline")
def process_timeline(scope_id:str,as_of:str|None=None,principal:Principal=Depends(require("READ_ORG_ANALYTICS"))):
    value=process_get(scope_id,as_of,250,principal)
    return {"scope":scope_id,"steps":value.get("steps",[]),"temporal_edges":value.get("temporal_edges",[]),"trigger_edges":value.get("trigger_edges",[]),"dependency_edges":value.get("dependency_edges",[]),"causal_edges":value.get("causal_edges",[])}

@router.get("/processes/{scope_id}/policy-drift", tags=["Processes","Risks"], summary="Compare policy with observed practice")
def process_drift(scope_id:str,policy_id:str=Query(min_length=1),as_of:str|None=None,principal:Principal=Depends(require("READ_ORG_ANALYTICS"))):
    value=PolicyDriftService(client_for(principal)).analyze(scope_id,policy_id,as_of=as_of)
    if value is None:_not_found("Process scope",scope_id)
    if value.get("reason")=="POLICY_NOT_FOUND":_not_found("Policy",policy_id)
    return value

@router.get("/risks", tags=["Risks"], summary="Get normalized organizational risk summary")
def risks(request:Request,as_of:str|None=None,principal:Principal=Depends(require("READ_ORG_ANALYTICS"))):
    _guard_rate(request,principal); client=client_for(principal)
    ownership=OwnershipGapService(client).detect_orphaned_resources(as_of=as_of)
    commitments=CommitmentTrackingService(client).list(as_of=as_of)
    return {"as_of":as_of,"risk_types":["BUS_FACTOR","BOTTLENECK","BRIDGE","OWNERSHIP_GAP","INITIATIVE_COLLISION","COMMITMENT_AT_RISK","COMMITMENT_BREACH","POLICY_DRIFT"],"ownership_gaps":ownership,"commitment_risks":[c for c in commitments if c.get("status") in {"AT_RISK","BREACHED","OVERDUE"}]}

@router.get("/risks/bus-factor", tags=["Risks"], summary="Analyze bus-factor concentration")
def risk_bus_factor(request:Request,as_of:str|None=None,limit:int=Query(100,ge=1,le=200),principal:Principal=Depends(require("READ_ORG_ANALYTICS"))):_guard_rate(request,principal); return BusFactorService(client_for(principal)).organization_summary(as_of=as_of,limit=limit)

@router.get("/risks/bottlenecks", tags=["Risks"], summary="Analyze organizational bottlenecks")
def risk_bottlenecks(request:Request,projection:str="collaboration",as_of:str|None=None,principal:Principal=Depends(require("READ_ORG_ANALYTICS"))):_guard_rate(request,principal); value=OrganizationalNetworkAnalysisService(client_for(principal)).analyze(projection,as_of=as_of); return {"projection":projection,"bottlenecks":value.get("overloaded_nodes",[]),"articulation_points":value.get("articulation_points",[])}

@router.get("/risks/bridges", tags=["Risks"], summary="Analyze graph bridges")
def risk_bridges(request:Request,projection:str="collaboration",as_of:str|None=None,principal:Principal=Depends(require("READ_ORG_ANALYTICS"))):_guard_rate(request,principal); value=OrganizationalNetworkAnalysisService(client_for(principal)).analyze(projection,as_of=as_of); return {"projection":projection,"bridges":value.get("bridges",[]),"single_path_risks":value.get("single_path_risks",[])}

@router.get("/risks/initiative-collisions", tags=["Risks"], summary="Detect overlapping initiatives")
def risk_collisions(request:Request,as_of:str|None=None,min_score:float=Query(0.0,ge=0,le=1),limit:int=Query(100,ge=1,le=200),principal:Principal=Depends(require("READ_ORG_ANALYTICS"))):_guard_rate(request,principal); return InitiativeCollisionService(client_for(principal)).analyze(as_of=as_of,min_score=min_score,limit=limit)

@router.get("/risks/ownership-gaps", tags=["Risks"], summary="Detect orphaned resources")
def risk_ownership(as_of:str|None=None,principal:Principal=Depends(require("READ_ORG_ANALYTICS"))):return OwnershipGapService(client_for(principal)).detect_orphaned_resources(as_of=as_of)

@router.get("/risks/commitments", tags=["Risks"], summary="List commitment risks")
def risk_commitments(as_of:str|None=None,status_filter:str|None=Query(None,alias="status"),principal:Principal=Depends(require("READ_ORG_ANALYTICS"))):return {"items":CommitmentTrackingService(client_for(principal)).list(as_of=as_of,status=status_filter)}

@router.get("/artifacts/{artifact_id}/metadata", tags=["Evidence"], summary="Get safe Artifact metadata")
def artifact_metadata(artifact_id:str,principal:Principal=Depends(require("READ_EVIDENCE"))):
    value=_app(principal).get_node(artifact_id)
    if value is None or not has_label(value,"Artifact"):_not_found("Artifact",artifact_id)
    return value

@router.get("/history/relationships", tags=["History"], summary="Inspect a canonical relationship over time")
def history_relationships(source_id:str=Query(min_length=1),target_id:str=Query(min_length=1),relationship_type:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):
    app=_app(principal); snap=app.snapshot()
    if snap.node(source_id) is None:_not_found("Entity",source_id)
    if snap.node(target_id) is None:_not_found("Entity",target_id)
    items=[sanitize(e.as_dict()) for e in snap.edges if e.source==source_id and e.target==target_id and (relationship_type is None or e.type==relationship_type)]
    items.sort(key=lambda x:str(x.get("properties",{}).get("valid_from") or ""))
    return {"source_id":source_id,"target_id":target_id,"relationship_type":relationship_type,"items":items}

# -------------------- public GraphRAG facade --------------------
@router.post("/retrieval/search", tags=["Retrieval"], summary="Run graph-first supporting retrieval")
def retrieval_search(body:RetrievalRequestExternal,request:Request,principal:Principal=Depends(require("READ_EVIDENCE"))):
    _guard_rate(request,principal); modes=[]
    for raw in body.retrieval_modes:
        try:modes.append(RetrievalMode(raw.upper()))
        except ValueError as exc:raise ApiError(422,"VALIDATION_FAILED",f"Unsupported retrieval mode: {raw}") from exc
    req=RetrievalRequest(query=body.query,tenant_id=principal.tenant_id,seed_entity_ids=body.seed_entity_ids,as_of=body.as_of,retrieval_modes=modes,max_results=body.max_results,max_graph_hops=body.max_graph_hops,metadata_filters=body.metadata_filters,writeback=True)
    return _retrieval_service_for(principal).search(req).model_dump(mode="json")
