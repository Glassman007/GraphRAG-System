from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request, status
from pydantic import BaseModel, Field

from backend.app.api_v1.application import ExternalApiApplication, sanitize, stable_id, node_visible, decode_cursor, encode_cursor
from backend.app.api_v1.errors import ApiError
from backend.app.api_v1.models import (
    ActionExecuteExternal, ActionProposalExternal, BusFactorExternal, CheckpointRequestExternal,
    ClaimRevalidateExternal, CounterfactualExternal, EvidenceInvalidateExternal, InvestigationCreate,
    ErrorResponse, PageResponse, PlanCreateExternal, RetrievalRequestExternal, SituationCreate, TaskActorRequest,
    SourceCreateExternal, SourceUpdateExternal, SourcePreviewExternal, SourceSyncExternal, IdentityResolveExternal,
)
from backend.app.api_v1.security import Principal, authenticate, client_for, require
from backend.app.retrieval.models import RetrievalMode, RetrievalRequest
from backend.app.retrieval.service import RetrievalService
from backend.app.retrieval.paths import scoped_index_root
from backend.app.services.action_coordination_service import ActionCoordinationService
from backend.app.services.anomaly_service import GraphAnomalyService
from backend.app.services.authority_resolution_service import AuthorityResolutionService
from backend.app.services.company_brain_expertise_service import CompanyBrainExpertiseService
from backend.app.services.company_brain_schema_service import CompanyBrainSchemaService
from backend.app.services.agent_registry_service import AgentRegistryService
from backend.app.services.blast_radius_service import BlastRadiusService
from backend.app.services.bus_factor_service import BusFactorService
from backend.app.services.claim_memory_service import ClaimMemoryService
from backend.app.services.commitment_service import CommitmentTrackingService
from backend.app.services.coordination_service import CoordinationService
from backend.app.services.handoff_service import HandoffService
from backend.app.services.branch_service import BranchMemoryService
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
from backend.app.services.work_insights_service import task_dependency_analysis, task_insights, agent_memory
from backend.app.agent_runtime.harness import AgentHarness, AgentSettings
from backend.app.agent_runtime.provider import OpenAICompatibleProvider, ProviderError
from backend.app.agent_runtime.store import GraphRunStore
from backend.app.agent_runtime.supervisor import Supervisor, SupervisorSettings, DEFAULT_AGENTS
from backend.app.agent_runtime.supervisor_store import GraphSupervisorStore
from backend.app.agent_runtime.memory import AgentMemory, MemorySearch
from backend.app.agent_runtime.memory_store import GraphMemoryStore
from backend.app.agent_runtime.reactive import ReactiveLearning
from backend.app.agent_runtime.reactive_store import GraphReactiveStore
from backend.app.agent_runtime.tools import ToolRegistry
from backend.app.agent_runtime.governed import GovernedActions, ActionProposal, Decision, Execution, ConnectorRegistry, RISK_CLASSES
from backend.app.agent_runtime.governed_store import GraphGovernedActionStore
from backend.app.agent_runtime.workspace import (WorkspaceStart, WorkspaceStore, runner as workspace_runner,
    format_workspace, build_replay, task_comparison, now as workspace_now)
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.ingestion.source_control import SourceControlService
from backend.app.ingestion.source_catalog import list_source_catalog, remove_source_from_catalog, inspect_source_removal

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
    retrieval_root=scoped_index_root(tenant_id=principal.tenant_id,graph_id=client.settings.falkordb_graph,root=repo_root)
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


# -------------------- Step 5 / Component 1: Real bounded Agent Runtime --------------------
@router.get("/agent-runtime/status", tags=["Agent Runtime"], summary="Describe the configured bounded tool-calling runtime")
def agent_runtime_status(principal:Principal=Depends(require("READ_GRAPH"))):
    import os
    provider=(os.getenv('GRAPH_HACKS_AGENT_PROVIDER') or 'groq').strip().lower()
    key={'groq':'GROQ_API_KEY','openai':'OPENAI_API_KEY','compatible':'GRAPH_HACKS_AGENT_API_KEY'}.get(provider)
    return {'provider':provider,'configured':bool(key is not None and os.getenv(key)) or (provider=='compatible' and bool(os.getenv('GRAPH_HACKS_AGENT_BASE_URL'))),
            'mode':'MODEL_TOOL_LOOP','business_tools':'READ_ONLY','requires_explicit_model_data_consent':True,
            'supports_autonomous_multi_agent_coordination':False,'supervisor_task_scheduler_available':True,
            'persistent_verified_agent_memory_available':True,'memory_requires_verification':True,
            'supports_external_action_execution':False,'governed_action_execution_available':True,'governed_external_connectors_disabled_by_default':True}

@router.post("/agent-runtime/runs", tags=["Agent Runtime"], summary="Start a bounded, graph-grounded independent investigation")
def start_agent_runtime(request:Request, body:AgentSettings, principal:Principal=Depends(require("READ_GRAPH","READ_EVIDENCE","CREATE_INVESTIGATION"))):
    _guard_rate(request,principal,limit=12)
    if not body.allow_external_model:
        raise ApiError(422,'CONSENT_REQUIRED','Explicit permission to transmit selected organizational context to the model is required.')
    try:
        provider=OpenAICompatibleProvider()
    except ProviderError as exc:
        raise ApiError(503,'AGENT_PROVIDER_UNAVAILABLE',str(exc)) from exc
    client=client_for(principal)
    tools=ToolRegistry(lambda:GraphSnapshot.load(client))
    harness=AgentHarness(provider=provider,tools=tools,store=GraphRunStore(client),tenant=principal.tenant_id)
    try:
        return harness.run(body,subject=principal.subject).__dict__
    except ValueError as exc:
        raise ApiError(422,'AGENT_INPUT_INVALID',str(exc)) from exc

@router.get("/agent-runtime/runs/{run_id}", tags=["Agent Runtime"], summary="Read tenant-scoped persisted run and complete execution trace")
def get_agent_runtime(run_id:str,principal:Principal=Depends(require("READ_GRAPH","READ_EVIDENCE"))):
    import re
    if not re.fullmatch(r'ARUN-[0-9A-F]{32}',run_id):
        raise ApiError(422,'INVALID_RUN_ID','Invalid agent runtime ID')
    result=GraphRunStore(client_for(principal)).get(run_id)
    if result is None:_not_found('AgentRun',run_id)
    return result


# -------------------- Component 6: Live Agent Workspace --------------------
# Development deployment: one API process. Worker handles are process-local while
# supervisory DAGs, checkpoints, workspace commands and events are graph persisted.
# No business-side-effect connector can be invoked by this workspace runner.
import uuid as _workspace_uuid
from typing import Literal
from pydantic import BaseModel as _WorkspaceBaseModel

class WorkspaceControl(_WorkspaceBaseModel):
    operation: Literal['pause', 'cancel', 'resume', 'retry']
    allow_external_model: bool = False


def _workspace_store(principal: Principal) -> WorkspaceStore:
    return WorkspaceStore(client_for(principal))


def _workspace_owned(principal: Principal, run_id: str) -> dict:
    import re
    if not re.fullmatch(r'SRUN-[0-9A-F]{32}', run_id):
        raise ApiError(422, 'INVALID_RUN_ID', 'Invalid workspace run ID')
    record = _workspace_store(principal).get(run_id, principal.subject)
    if record is None:
        _not_found('Owned workspace run', run_id)
    # A run is permanently bound to its creation graph. Do not permit a different
    # graph selection to resume, inspect or control an unrelated run.
    expected = principal.graph_id or client_for(principal).settings.falkordb_graph
    if record.get('graph_id', expected) != expected:
        _not_found('Owned workspace run', run_id)
    return record


def _workspace_worker(principal: Principal, run_id: str, *, resume: bool = False,
                      retry_failed: bool = False) -> None:
    # Construct new clients in the worker thread; never reuse request-scoped state.
    store = _workspace_store(principal)
    try:
        entry = store.get(run_id, principal.subject)
        if not entry:
            return
        store.update(run_id, principal.subject, status='RUNNING')
        client = client_for(principal)
        memory = AgentMemory(backend=GraphMemoryStore(client),
                             snapshot_factory=lambda: GraphSnapshot.load(client), tenant=principal.tenant_id)
        supervisor = Supervisor(provider=OpenAICompatibleProvider(),
                                tools=ToolRegistry(lambda: GraphSnapshot.load(client)),
                                store=GraphSupervisorStore(client), tenant=principal.tenant_id,
                                permissions=principal.permissions, memory=memory)
        def command():
            current = store.get(run_id, principal.subject)
            return str((current or {}).get('command') or '')
        result = supervisor.run(SupervisorSettings.model_validate(entry['settings']),
                                subject=principal.subject, resume_id=run_id if resume else None,
                                run_id=None if resume else run_id, control_check=command,
                                retry_failed=retry_failed)
        store.capture(run_id, principal.subject, {'created_at':workspace_now(),'status':result.status,
                      'answer':result.answer,'citations':result.citations,
                      'tasks':[{'id':t['id'],'status':t['status'],'result':t.get('result')} for t in result.tasks],
                      'knowledge_gaps':result.knowledge_gaps})
        store.update(run_id, principal.subject, status=result.status, command='', error=result.error or '')
    except Exception as exc:
        # No raw prompts, credentials or untrusted model responses in error records.
        try:
            store.update(run_id, principal.subject, status='FAILED', command='',
                         error=f'{type(exc).__name__}: {str(exc)[:150]}')
        except Exception:
            pass


@router.get('/agent-runtime/workspace/capabilities', tags=['Agent Workspace'])
def workspace_capabilities(principal:Principal=Depends(require('READ_GRAPH'))):
    import os
    provider = (os.getenv('GRAPH_HACKS_AGENT_PROVIDER') or 'groq').strip().lower()
    key = {'groq':'GROQ_API_KEY','openai':'OPENAI_API_KEY','compatible':'GRAPH_HACKS_AGENT_API_KEY'}.get(provider)
    try:
        OpenAICompatibleProvider()
        configured = True
    except ProviderError:
        configured = False
    return {'status': 'LIVE_MODEL_AVAILABLE' if configured else 'MODEL_NOT_CONFIGURED',
            'provider':provider, 'model_configured':configured,
            'multi_agent': 'REAL_READ_ONLY_WITH_EXPLICIT_CONSENT',
            'live_activity': 'POLL_PERSISTED_OPERATIONAL_EVENTS',
            'controls': 'COOPERATIVE_AT_SCHEDULER_BOUNDARIES',
            'event_replay': 'PERSISTED_OPERATIONAL_EVENTS',
            'before_after': 'RECORDED_WORKSPACE_RUN_REVISIONS',
            'governed_actions': 'SEPARATE_APPROVAL_AND_EXECUTION_REQUIRED',
            'seeded_scenarios': 'CATALOG_ONLY_NOT_LIVE_RESULT',
            'worker_durability': 'SINGLE_PROCESS_BACKGROUND_WITH_EXPLICIT_CHECKPOINT_RECOVERY',
            'external_action_auto_execution':False}


@router.get('/agent-runtime/workspace/runs', tags=['Agent Workspace'])
def workspace_runs(limit:int=Query(default=30,ge=1,le=100),
                   principal:Principal=Depends(require('READ_GRAPH','READ_EVIDENCE'))):
    records=_workspace_store(principal).list(principal.subject,limit)
    return {'items':[format_workspace(r,is_live=workspace_runner.live(principal.tenant_id,r['id']))
                     for r in records]}


@router.post('/agent-runtime/workspace/runs',tags=['Agent Workspace'],status_code=202)
def workspace_start(body:WorkspaceStart, request:Request,
                    principal:Principal=Depends(require('READ_GRAPH','READ_EVIDENCE','CREATE_INVESTIGATION'))):
    _guard_rate(request,principal,limit=6)
    if not body.allow_external_model:
        raise ApiError(422,'CONSENT_REQUIRED','Authorize transmission of selected organizational evidence to the model.')
    # Explicit graph selection must match the authenticated, registry-validated scope.
    # No graph requested preserves legacy default behavior.
    if body.graph_id != principal.graph_id:
        raise ApiError(422, 'GRAPH_SCOPE_MISMATCH', 'Selected graph must match the authenticated Company Brain header.')
    # Validate provider before committing a QUEUED record.
    try:
        OpenAICompatibleProvider()
    except ProviderError as exc:
        raise ApiError(503,'AGENT_PROVIDER_UNAVAILABLE',str(exc)) from exc
    run_id='SRUN-'+_workspace_uuid.uuid4().hex.upper()
    entry={'id':run_id,'owner':principal.subject,'tenant':principal.tenant_id,
           'graph_id':principal.graph_id or client_for(principal).settings.falkordb_graph,
           'goal':body.goal,'source_entity_id':body.source_entity_id,'status':'QUEUED',
           'command':'','allow_external_model':True,'created_at':workspace_now(),
           'updated_at':workspace_now(),'settings':body.settings().model_dump(),'error':''}
    _workspace_store(principal).create(entry)
    try:
        workspace_runner.submit(tenant=principal.tenant_id,run_id=run_id,
            execute=lambda:_workspace_worker(principal,run_id))
    except Exception as exc:
        _workspace_store(principal).update(run_id,principal.subject,status='FAILED',error=type(exc).__name__)
        raise ApiError(503,'WORKER_UNAVAILABLE','Workspace worker could not start') from exc
    return {'id':run_id,'graph_id':entry['graph_id'],'status':'QUEUED','execution_mode':'LIVE_MODEL','side_effects':'NONE_READ_ONLY'}


@router.get('/agent-runtime/workspace/runs/{run_id}', tags=['Agent Workspace'])
def workspace_detail(run_id:str,principal:Principal=Depends(require('READ_GRAPH','READ_EVIDENCE'))):
    record=_workspace_owned(principal,run_id)
    client=client_for(principal)
    supervision=GraphSupervisorStore(client).get(run_id)
    checkpoint=GraphMemoryStore(client).load_checkpoint(run_id,owner=principal.subject)
    result=format_workspace(record,is_live=workspace_runner.live(principal.tenant_id,run_id))
    return {'workspace':result,'supervisor':supervision,'checkpoint':{
        'revision':(checkpoint or {}).get('revision'),
        'status':(checkpoint or {}).get('status'),
        'updated_at':(checkpoint or {}).get('updated_at'),
        'reactive_affected_tasks':(checkpoint or {}).get('reactive_affected_tasks') or []},
        'comparison':task_comparison(checkpoint,supervision),
        'snapshots':_workspace_store(principal).snapshots(run_id,principal.subject),
        'classification':'LIVE_MODEL' if supervision else 'QUEUED_OR_INTERRUPTED'}


@router.get('/agent-runtime/workspace/runs/{run_id}/events',tags=['Agent Workspace'])
def workspace_events(run_id:str,after:int=Query(default=-1,ge=-1),
                     principal:Principal=Depends(require('READ_GRAPH','READ_EVIDENCE'))):
    _workspace_owned(principal,run_id)
    record=GraphSupervisorStore(client_for(principal)).get(run_id)
    items=[e for e in (record or {}).get('events',[]) if int(e.get('event_index',e.get('index',0)))>after]
    return {'items':items[:250],'next_cursor':int(items[min(len(items),250)-1].get('event_index',
            items[min(len(items),250)-1].get('index',0))) if items else after,
            'mode':'PERSISTED_OPERATIONAL_EVENTS_NOT_PRIVATE_REASONING'}


@router.get('/agent-runtime/workspace/runs/{run_id}/replay',tags=['Agent Workspace'])
def workspace_replay(run_id:str,principal:Principal=Depends(require('READ_GRAPH','READ_EVIDENCE'))):
    _workspace_owned(principal,run_id)
    client=client_for(principal)
    return build_replay(GraphSupervisorStore(client).get(run_id),
                        GraphMemoryStore(client).load_checkpoint(run_id,owner=principal.subject))


@router.post('/agent-runtime/workspace/runs/{run_id}/control',tags=['Agent Workspace'])
def workspace_control(run_id:str,body:WorkspaceControl,request:Request,
                      principal:Principal=Depends(require('READ_GRAPH','READ_EVIDENCE','CREATE_INVESTIGATION'))):
    _guard_rate(request,principal,limit=20)
    record=_workspace_owned(principal,run_id)
    store=_workspace_store(principal)
    live=workspace_runner.live(principal.tenant_id,run_id)
    if body.operation in {'pause','cancel'}:
        if not live or record['status'] not in {'QUEUED','RUNNING','PAUSING','CANCELLING'}:
            raise ApiError(409,'NOT_ACTIVE','Only actively executing runs can be paused or cancelled.')
        return store.update(run_id,principal.subject,
                           status='PAUSING' if body.operation=='pause' else 'CANCELLING',
                           command=body.operation.upper())
    if not body.allow_external_model:
        raise ApiError(422,'CONSENT_REQUIRED','Fresh model-data transmission consent is required.')
    if live:
        raise ApiError(409,'ALREADY_RUNNING','Run already has an active worker.')
    visible=format_workspace(record,is_live=False)
    if body.operation=='resume' and visible['status'] not in {'PAUSED','INTERRUPTED'}:
        raise ApiError(409,'NOT_RESUMABLE','Only paused or interrupted runs can resume.')
    if body.operation=='retry' and visible['status'] not in {'FAILED','PARTIAL','NEEDS_REVIEW'}:
        raise ApiError(409,'NOT_RETRYABLE','Only failed, partial or review-required runs can retry.')
    cp=GraphMemoryStore(client_for(principal)).load_checkpoint(run_id,owner=principal.subject)
    if not cp or not cp.get('tasks'):
        raise ApiError(409,'CHECKPOINT_UNAVAILABLE','No planned checkpoint exists for safe resume; launch a new run.')
    if cp.get('status')=='COMPLETED' and not cp.get('reactive_affected_tasks'):
        raise ApiError(409,'ALREADY_COMPLETED','Cannot re-run a completed DAG without changed evidence.')
    previous_status=record['status']
    record=store.update(run_id,principal.subject,status='QUEUED',command='')
    try:
        workspace_runner.submit(tenant=principal.tenant_id,run_id=run_id,
            execute=lambda:_workspace_worker(principal,run_id,resume=True,retry_failed=body.operation=='retry'))
    except ValueError as exc:
        store.update(run_id,principal.subject,status=previous_status,command='')
        raise ApiError(409,'WORKER_UNAVAILABLE',str(exc)) from exc
    return {'id':run_id,'status':'QUEUED','mode':body.operation.upper()}


@router.get('/agent-runtime/workspace/changes',tags=['Agent Workspace'])
def workspace_changes(limit:int=Query(default=30,ge=1,le=100),
                      principal:Principal=Depends(require('READ_GRAPH','READ_EVIDENCE'))):
    events=_reactive_service(principal).store.list_events(limit)
    owned=_workspace_store(principal)
    scoped=[]
    for event in events:
        item=dict(event)
        item['workflow_impacts']=[impact for impact in item.get('workflow_impacts',[])
           if owned.get(str(impact.get('run_id') or ''),principal.subject)]
        scoped.append(item)
    return {'items':scoped,'mode':'PERSISTED_VERIFICATION_EVENTS','count':len(scoped)}


# -------------------- Component 5: fail-closed governed tool execution --------------------
def _governed(principal: Principal) -> GovernedActions:
    client = client_for(principal)
    return GovernedActions(store=GraphGovernedActionStore(client),
                           snapshot_factory=lambda: GraphSnapshot.load(client),
                           tenant=principal.tenant_id,
                           run_lookup=lambda run_id:GraphSupervisorStore(client).get(run_id),
                           outcome_sink=lambda outcome:GraphReactiveStore(client).save_outcome(outcome))


def _governed_call(fn):
    try:
        return fn()
    except LookupError as exc:
        raise ApiError(404, 'NOT_FOUND', str(exc)) from exc
    except PermissionError as exc:
        raise ApiError(403, 'FORBIDDEN', str(exc)) from exc
    except ValueError as exc:
        raise ApiError(409, 'GOVERNED_ACTION_BLOCKED', str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(409, 'GOVERNED_STATE_CONFLICT', str(exc)) from exc


@router.get('/agent-runtime/governed/tools', tags=['Governed Actions'])
def governed_tools(principal: Principal = Depends(require('READ_GRAPH'))):
    return {'tools':ConnectorRegistry().list_tools(), 'risk_classes':RISK_CLASSES,
            'policy':'Explicit allow policy, evidence, independent human approval and fresh preconditions required; no model can approve'}


@router.get('/agent-runtime/governed/actions', tags=['Governed Actions'])
def governed_actions(limit:int=Query(30,ge=1,le=100),principal:Principal=Depends(require('READ_GRAPH'))):
    return {'items':GraphGovernedActionStore(client_for(principal)).list_actions(limit)}


@router.post('/agent-runtime/governed/actions', tags=['Governed Actions'], status_code=201)
def governed_propose(body:ActionProposal,request:Request,principal:Principal=Depends(require('PROPOSE_ACTION','READ_GRAPH','READ_EVIDENCE'))):
    _guard_rate(request,principal,limit=20)
    return _governed_call(lambda:_governed(principal).propose(body,subject=principal.subject))


@router.get('/agent-runtime/governed/actions/{action_id}', tags=['Governed Actions'])
def governed_detail(action_id:str, principal:Principal=Depends(require('READ_GRAPH'))):
    return _governed_call(lambda:_governed(principal).detail(action_id))


@router.get('/agent-runtime/governed/actions/{action_id}/preview', tags=['Governed Actions'])
def governed_preview(action_id:str, principal:Principal=Depends(require('READ_GRAPH','READ_ORG_ANALYTICS'))):
    return _governed_call(lambda:_governed(principal).preview(action_id))


@router.post('/agent-runtime/governed/actions/{action_id}/request-approval', tags=['Governed Actions'])
def governed_request_approval(action_id:str, request:Request,principal:Principal=Depends(require('PROPOSE_ACTION'))):
    _guard_rate(request,principal,limit=20)
    return _governed_call(lambda:_governed(principal).request_approval(action_id,subject=principal.subject))


@router.post('/agent-runtime/governed/actions/{action_id}/approve', tags=['Governed Actions'])
def governed_approve(action_id:str,body:Decision,request:Request,principal:Principal=Depends(require('APPROVE_ACTION'))):
    _guard_rate(request,principal,limit=20)
    return _governed_call(lambda:_governed(principal).decide(action_id,subject=principal.subject,
                             approve=True,reason=body.reason,approver_permissions=principal.permissions,
                             approver_roles=principal.roles))


@router.post('/agent-runtime/governed/actions/{action_id}/reject', tags=['Governed Actions'])
def governed_reject(action_id:str,body:Decision,request:Request,principal:Principal=Depends(require('APPROVE_ACTION'))):
    _guard_rate(request,principal,limit=20)
    return _governed_call(lambda:_governed(principal).decide(action_id,subject=principal.subject,
                             approve=False,reason=body.reason,approver_permissions=principal.permissions,
                             approver_roles=principal.roles))


@router.post('/agent-runtime/governed/actions/{action_id}/execute', tags=['Governed Actions'])
def governed_execute(action_id:str,body:Execution,request:Request,principal:Principal=Depends(require('EXECUTE_ACTION'))):
    _guard_rate(request,principal,limit=10)
    return _governed_call(lambda:_governed(principal).execute(action_id,subject=principal.subject,
                         permissions=principal.permissions,confirmed=body.acknowledge_external_side_effect))


@router.post('/agent-runtime/governed/actions/{action_id}/verify', tags=['Governed Actions'])
def governed_verify(action_id:str,request:Request,principal:Principal=Depends(require('EXECUTE_ACTION'))):
    _guard_rate(request,principal,limit=20)
    return _governed_call(lambda:_governed(principal).verify(action_id,subject=principal.subject))


@router.post('/agent-runtime/governed/actions/{action_id}/escalate', tags=['Governed Actions'])
def governed_escalate(action_id:str,body:Decision,request:Request,principal:Principal=Depends(require('EXECUTE_ACTION'))):
    _guard_rate(request,principal,limit=20)
    return _governed_call(lambda:_governed(principal).escalate(action_id,subject=principal.subject,
                                       reason=body.reason,permissions=principal.permissions))


@router.post('/agent-runtime/governed/actions/{action_id}/learn-outcome', tags=['Governed Actions'])
def governed_reconcile_learning(action_id:str,request:Request,principal:Principal=Depends(require('EXECUTE_ACTION'))):
    _guard_rate(request,principal,limit=15)
    return _governed_call(lambda:_governed(principal).learn_verified_outcome(action_id))


# -------------------- Component 2: autonomous specialist coordination --------------------
@router.get("/agent-runtime/supervisor/registry", tags=["Agent Runtime"], summary="Discover scoped specialist agent capabilities")
def supervisor_registry(principal: Principal = Depends(require("READ_GRAPH", "READ_EVIDENCE"))):
    return {'agents': Supervisor(provider=None, tools=None, store=None, tenant=principal.tenant_id,
                                 permissions=principal.permissions).registry(),
            'business_tools': 'READ_ONLY', 'human_approval_required_for_actions': True}


@router.post("/agent-runtime/supervisor/runs", tags=["Agent Runtime"], summary="Run bounded, evidence-checked multi-agent supervisor")
def start_supervisor_run(request: Request, body: SupervisorSettings,
                         principal: Principal = Depends(require("READ_GRAPH", "READ_EVIDENCE", "CREATE_INVESTIGATION"))):
    _guard_rate(request, principal, limit=6)
    if not body.allow_external_model:
        raise ApiError(422, 'CONSENT_REQUIRED', 'Explicit permission to transmit organizational context to the model is required.')
    try:
        provider = OpenAICompatibleProvider()
    except ProviderError as exc:
        raise ApiError(503, 'AGENT_PROVIDER_UNAVAILABLE', str(exc)) from exc
    client = client_for(principal)
    memory = AgentMemory(backend=GraphMemoryStore(client), snapshot_factory=lambda: GraphSnapshot.load(client),
                         tenant=principal.tenant_id)
    supervisor = Supervisor(provider=provider, tools=ToolRegistry(lambda: GraphSnapshot.load(client)),
                            store=GraphSupervisorStore(client), tenant=principal.tenant_id,
                            permissions=principal.permissions, memory=memory)
    try:
        return supervisor.run(body, subject=principal.subject).__dict__
    except ValueError as exc:
        raise ApiError(422, 'AGENT_INPUT_INVALID', str(exc)) from exc



# -------------------- Component 4: reactive organizational learning --------------------
def _reactive_service(principal: Principal) -> ReactiveLearning:
    client = client_for(principal)
    return ReactiveLearning(store=GraphReactiveStore(client), memory=AgentMemory(
        backend=GraphMemoryStore(client), snapshot_factory=lambda: GraphSnapshot.load(client),
        tenant=principal.tenant_id), snapshot_factory=lambda: GraphSnapshot.load(client),
        tenant=principal.tenant_id)


@router.get('/agent-runtime/reactive/events', tags=['Agent Runtime'],
            summary='Inspect tenant-scoped change events, affected findings and escalations')
def reactive_events(limit: int = Query(default=30, ge=1, le=100),
                    principal: Principal = Depends(require('READ_GRAPH', 'READ_EVIDENCE'))):
    events = _reactive_service(principal).store.list_events(limit)
    return {'items': events, 'count': len(events), 'mode': 'VERIFIED_CHANGES_ONLY_AUTOMATED',
            'note': 'External model execution requires fresh consent on reactive resume.'}


@router.post('/agent-runtime/reactive/process', tags=['Agent Runtime'],
             summary='Retry durable pending organizational changes without full investigation replay')
def process_reactive_events(request: Request, limit: int = Query(default=12, ge=1, le=50),
                            principal: Principal = Depends(require('READ_GRAPH', 'READ_EVIDENCE', 'CREATE_INVESTIGATION'))):
    _guard_rate(request, principal, limit=12)
    applied = _reactive_service(principal).process(limit=limit)
    return {'processed': len(applied), 'events': applied,
            'note': 'Only deterministic propagation runs here; no external model or business action.'}


@router.get('/agent-runtime/reactive/runs/{run_id}/impact', tags=['Agent Runtime'],
            summary='Read scoped source-change replan instructions for the owner')
def reactive_run_impact(run_id: str,
                        principal: Principal = Depends(require('READ_GRAPH', 'READ_EVIDENCE'))):
    import re
    if not re.fullmatch(r'SRUN-[0-9A-F]{32}', run_id):
        raise ApiError(422, 'INVALID_RUN_ID', 'Invalid supervisor run ID')
    cp = GraphMemoryStore(client_for(principal)).load_checkpoint(run_id, owner=principal.subject)
    if not cp: _not_found('Owned supervisor checkpoint', run_id)
    return {'run_id': run_id, 'status': cp.get('status'),
            'affected_task_ids': cp.get('reactive_affected_tasks') or [],
            'change_event_ids': cp.get('reactive_change_event_ids') or [],
            'requires_fresh_model_consent': bool(cp.get('reactive_affected_tasks'))}


@router.post('/agent-runtime/reactive/outcomes/{action_id}/learn', tags=['Agent Runtime'],
             summary='Persist only graph-confirmed action outcomes for future organizational reasoning')
def reactive_learn_outcome(action_id: str, request: Request,
                           principal: Principal = Depends(require('READ_GRAPH', 'READ_EVIDENCE', 'CREATE_INVESTIGATION'))):
    _guard_rate(request, principal, limit=20)
    try:
        return _reactive_service(principal).learn_action_outcome(action_id=action_id)
    except ValueError as exc:
        raise ApiError(422, 'ACTION_OUTCOME_UNVERIFIED', str(exc)) from exc



# -------------------- Component 3: durable, evidence-backed agent memory --------------------
def _memory_service(principal: Principal) -> AgentMemory:
    client = client_for(principal)
    return AgentMemory(backend=GraphMemoryStore(client),
                       snapshot_factory=lambda: GraphSnapshot.load(client), tenant=principal.tenant_id)


@router.post('/agent-runtime/memory/search', tags=['Agent Runtime'],
             summary='Search currently verified agent knowledge with provenance and permissions')
def search_agent_memory(body: MemorySearch,
                        principal: Principal = Depends(require('READ_GRAPH', 'READ_EVIDENCE'))):
    memory = _memory_service(principal)
    if not body.entity_ids and not body.query.strip():
        raise ApiError(422, 'INVALID_SEARCH', 'Provide entity_ids or a contextual query.')
    results = memory.retrieve(requester=principal.subject, agent_id='external_reader',
                               permissions=principal.permissions, search=body)
    return {'items': results, 'count': len(results), 'policy': 'VERIFIED_SHARED_CURRENT_ONLY',
            'note': 'Archived or private agent observations are excluded.'}


class MemoryReview(BaseModel):
    status: str
    reason: str = Field(min_length=10, max_length=500)


@router.post('/agent-runtime/memory/{memory_id}/validity', tags=['Agent Runtime'],
             summary='Explicitly invalidate, supersede or flag shared memory for recheck')
def mark_agent_memory(memory_id: str, body: MemoryReview,
                      principal: Principal = Depends(require('READ_GRAPH', 'READ_EVIDENCE', 'CREATE_INVESTIGATION'))):
    import re
    if not re.fullmatch(r'MEM-[0-9A-F]{32}', memory_id):
        raise ApiError(422, 'INVALID_MEMORY_ID', 'Invalid agent memory ID')
    try:
        result = _memory_service(principal).set_validity(memory_id, actor=principal.subject,
                                                         permission=principal.permissions,
                                                         status=body.status, reason=body.reason)
    except PermissionError as exc:
        raise ApiError(404, 'NOT_FOUND', 'Memory not found in tenant') from exc
    except ValueError as exc:
        raise ApiError(409, 'MEMORY_INVALID_STATE', str(exc)) from exc
    return {'id': result['id'], 'status': result['status'], 'reviewed_by': result['reviewed_by']}


@router.post('/agent-runtime/supervisor/runs/{run_id}/resume', tags=['Agent Runtime'],
             summary='Resume persisted incomplete supervisor DAG without rerunning completed tasks')
def resume_supervisor_run(request: Request, run_id: str,
                          allow_external_model: bool = Query(default=False),
                          principal: Principal = Depends(require('READ_GRAPH', 'READ_EVIDENCE', 'CREATE_INVESTIGATION'))):
    import re
    _guard_rate(request, principal, limit=4)
    if not re.fullmatch(r'SRUN-[0-9A-F]{32}', run_id):
        raise ApiError(422, 'INVALID_RUN_ID', 'Invalid supervisor run ID')
    if not allow_external_model:
        raise ApiError(422, 'CONSENT_REQUIRED', 'Fresh consent is required to resume model execution')
    try:
        provider = OpenAICompatibleProvider()
    except ProviderError as exc:
        raise ApiError(503, 'AGENT_PROVIDER_UNAVAILABLE', str(exc)) from exc
    client = client_for(principal)
    memory = AgentMemory(backend=GraphMemoryStore(client), snapshot_factory=lambda: GraphSnapshot.load(client),
                         tenant=principal.tenant_id)
    supervisor = Supervisor(provider=provider, tools=ToolRegistry(lambda: GraphSnapshot.load(client)),
                            store=GraphSupervisorStore(client), tenant=principal.tenant_id,
                            permissions=principal.permissions, memory=memory)
    try:
        # Settings are discarded in favour of the persisted original plan and constraints.
        return supervisor.run(SupervisorSettings(goal='Resume saved organizational investigation',
                                                allow_external_model=True),
                              subject=principal.subject, resume_id=run_id).__dict__
    except ValueError as exc:
        raise ApiError(409, 'RESUME_UNAVAILABLE', str(exc)) from exc


@router.get("/agent-runtime/supervisor/runs/{run_id}", tags=["Agent Runtime"], summary="Read tenant-isolated supervisor run DAG, trace and results")
def get_supervisor_run(run_id: str, principal: Principal = Depends(require("READ_GRAPH", "READ_EVIDENCE"))):
    import re
    if not re.fullmatch(r'SRUN-[0-9A-F]{32}', run_id):
        raise ApiError(422, 'INVALID_RUN_ID', 'Invalid supervisor run ID')
    result = GraphSupervisorStore(client_for(principal)).get(run_id)
    if result is None:
        _not_found('SupervisorRun', run_id)
    return result


@router.get("/capabilities", tags=["System"], summary="List public capabilities")
def capabilities():
    return {"api_version":"v1","graph_reasoning":True,"planning":True,"coordination":True,"learning":True,"company_brain_analytics":True,"ingestion":True,"source_control":True,"human_interpretation":True,"graphrag":True,"external_api":True}

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
def list_situations(limit:int=Query(50,ge=1,le=100),cursor:str|None=None,status_filter:str|None=Query(None,alias="status"),q:str|None=Query(None,max_length=200),as_of:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):
    return _app(principal).page(labels={"Incident"},status=status_filter,search=q,as_of=as_of,limit=limit,cursor=cursor)

@router.get("/situations/statuses", tags=["Situations"], summary="List available situation statuses")
def situation_statuses(principal:Principal=Depends(require("READ_GRAPH"))):
    snap=_app(principal).snapshot()
    return {"items": sorted({str(node.get("status")) for node in snap.nodes.values() if has_label(node,"Incident") and node_visible(node,None) and node.get("status")})}

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

@router.get("/entities/browse", tags=["Entities"], summary="Browse organization entities")
def browse_entities(kind:str|None=Query(None,max_length=64),q:str|None=Query(None,max_length=200),limit:int=Query(50,ge=1,le=100),cursor:str|None=None,principal:Principal=Depends(require("READ_GRAPH"))):
    allowed={"Department","Team","Person","System","Project","Incident","Agent","Task","Policy","Decision","Change","Action","Evidence","Claim","Investigation","Plan"}
    if kind and kind not in allowed:raise ApiError(422,"INVALID_TYPE","Unsupported entity category.")
    return _app(principal).page(labels={"Team"} if kind=="Department" else ({kind} if kind else allowed),
                                filters={"team_type":"DEPARTMENT"} if kind=="Department" else None,
                                search=q,limit=limit,cursor=cursor)

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

@router.get("/work/plans/{plan_id}/topology", tags=["Tasks"], summary="Inspect plan dependency waves and longest dependency chain")
def work_plan_topology(plan_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    value=task_dependency_analysis(GraphSnapshot.load(client_for(principal)),plan_id)
    if value is None:_not_found("Plan",plan_id)
    return value

@router.get("/work/tasks/{task_id}/insights", tags=["Tasks"], summary="Inspect work provenance and execution history")
def work_task_insights(task_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    value=task_insights(GraphSnapshot.load(client_for(principal)),task_id)
    if value is None:_not_found("Task",task_id)
    return value

@router.get("/work/tasks/{task_id}/agent-matches", tags=["Agents"], summary="Inspect candidate agent eligibility without assigning them")
def work_agent_matches(task_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    snapshot=GraphSnapshot.load(client_for(principal)); task=snapshot.node(task_id)
    if not has_label(task,"Task"):_not_found("Task",task_id)
    candidates=[]
    for agent in snapshot.nodes.values():
        if not has_label(agent,"Agent"):continue
        evaluation=AgentRegistryService._eligibility(agent,task)
        candidates.append({"agent":agent,"eligible":evaluation["eligible"],"reasons":evaluation["reason_codes"],"task_type":evaluation["task_type"]})
    return {"task_id":task_id,"items":sorted(candidates,key=lambda v:(not v['eligible'],str(v['agent'].get('name') or v['agent'].get('id')))),"assignment_performed":False}

@router.get("/work/agents/{agent_id}/memory", tags=["Agents"], summary="Inspect persisted agent artifacts and checkpoints")
def work_agent_memory(agent_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    value=agent_memory(GraphSnapshot.load(client_for(principal)),agent_id)
    if value is None:_not_found("Agent",agent_id)
    return value

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

@router.post("/tasks/{task_id}/pause", tags=["Tasks"], summary="Pause an owned running task")
def task_pause(task_id:str,body:TaskActorRequest,principal:Principal=Depends(require("CLAIM_TASK"))):
    coord=CoordinationService(client_for(principal))
    eid=body.execution_id or _active_execution(coord,task_id)
    if not eid:raise ApiError(409,"INVALID_STATE_TRANSITION","No active execution to pause.")
    try:return coord.pause_execution(eid,body.agent_id)
    except ValueError as exc:raise ApiError(409,"INVALID_STATE_TRANSITION",str(exc)) from exc

@router.post("/tasks/{task_id}/retry", tags=["Tasks"], summary="Retry failed task from persisted checkpoint")
def task_retry(task_id:str,body:TaskActorRequest,principal:Principal=Depends(require("CLAIM_TASK"))):
    coord=CoordinationService(client_for(principal))
    board=coord.get_task_blackboard(task_id)
    if not board: _not_found("Task",task_id)
    candidates=[e for e in board.get('executions',[]) if str(e.get('status') or '').upper()=='FAILED']
    if body.execution_id:candidates=[e for e in candidates if str(e.get('id'))==body.execution_id]
    if not candidates:raise ApiError(409,"INVALID_STATE_TRANSITION","Retry requires a failed execution; no action is executed automatically.")
    candidates.sort(key=lambda e:str(e.get('started_at') or e.get('created_at') or ''),reverse=True)
    try:return coord.resume_execution(str(candidates[0]['id']),body.agent_id)
    except ValueError as exc:raise ApiError(409,"INVALID_STATE_TRANSITION",str(exc)) from exc

class FindingCreateRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    statement: str = Field(min_length=3, max_length=4000)
    confidence: float = Field(ge=0, le=1)
    kind: str = Field(default="GENERAL", max_length=60)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    claim_ids: list[str] = Field(default_factory=list, max_length=50)

class FindingVerifyRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    result: str = Field(pattern="^(VERIFIED|REJECTED|INCONCLUSIVE)$")
    rationale: str = Field(default="", max_length=3000)

@router.post("/work/tasks/{task_id}/findings", tags=["Tasks"], summary="Record an agent finding with provenance")
def work_add_finding(task_id:str,body:FindingCreateRequest,principal:Principal=Depends(require("WRITE_FINDING"))):
    coord=CoordinationService(client_for(principal))
    owner=(coord.get_task_owner(task_id) or {}).get('owner')
    if not owner or str(owner.get('id'))!=body.agent_id:
        raise ApiError(409,'INVALID_STATE_TRANSITION','Only the active task owner may submit a task finding')
    try:return coord.add_finding(task_id,body.agent_id,statement=body.statement,confidence=body.confidence,kind=body.kind,evidence_ids=body.evidence_ids,claim_ids=body.claim_ids)
    except ValueError as exc:raise ApiError(409,"INVALID_REQUEST",str(exc)) from exc

@router.post("/work/findings/{finding_id}/verify", tags=["Tasks"], summary="Verify a finding using a verifier agent")
def work_verify_finding(finding_id:str,body:FindingVerifyRequest,principal:Principal=Depends(require("WRITE_FINDING"))):
    coord=CoordinationService(client_for(principal))
    try:return coord.verify_finding(finding_id,body.agent_id,result=body.result,rationale=body.rationale)
    except ValueError as exc:raise ApiError(409,"INVALID_REQUEST",str(exc)) from exc

class WorkHandoffRequest(BaseModel):
    destination_agent_id: str = Field(min_length=1, max_length=128)
    execution_id: str | None = None

class WorkResolveBlockerRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    resolution: str = Field(min_length=5, max_length=3000)

@router.post("/tasks/{task_id}/transfer", tags=["Tasks"], summary="Transfer an execution to another eligible agent and resume")
def task_handoff(task_id:str,body:WorkHandoffRequest,principal:Principal=Depends(require("CLAIM_TASK"))):
    coord=CoordinationService(client_for(principal));eid=body.execution_id or _active_execution(coord,task_id)
    if not eid:raise ApiError(409,"INVALID_STATE_TRANSITION","No active execution to hand off")
    try:return coord.transfer_execution(eid,body.destination_agent_id)
    except ValueError as exc:raise ApiError(409,"INVALID_STATE_TRANSITION",str(exc)) from exc

@router.post("/work/blockers/{blocker_id}/resolve", tags=["Tasks"], summary="Record blocker resolution")
def work_resolve_blocker(blocker_id:str,body:WorkResolveBlockerRequest,principal:Principal=Depends(require("WRITE_FINDING"))):
    coord=CoordinationService(client_for(principal))
    snapshot=GraphSnapshot.load(coord.client);blocker=snapshot.node(blocker_id)
    if not has_label(blocker,'Blocker'):_not_found('Blocker',blocker_id)
    owner=(coord.get_task_owner(str(blocker.get('task_id') or '')) or {}).get('owner')
    if not owner or str(owner.get('id'))!=body.agent_id:
        raise ApiError(409,'INVALID_STATE_TRANSITION','Only the active task owner may resolve its blocker')
    try:return coord.resolve_blocker(blocker_id,body.agent_id,resolution=body.resolution)
    except ValueError as exc:raise ApiError(409,"INVALID_REQUEST",str(exc)) from exc

@router.post("/tasks/{task_id}/complete", tags=["Tasks"], summary="Complete an execution only if completion conditions hold")
def task_complete(task_id:str,body:TaskActorRequest,principal:Principal=Depends(require("CLAIM_TASK"))):
    coord=CoordinationService(client_for(principal)); eid=body.execution_id or _active_execution(coord,task_id)
    if not eid:raise ApiError(409,"INVALID_STATE_TRANSITION","No running execution to complete.")
    try:return coord.complete_execution(eid,body.agent_id)
    except ValueError as exc:raise ApiError(409,"INVALID_STATE_TRANSITION",str(exc)) from exc

class WorkHandoffContractRequest(BaseModel):
    source_task_id: str = Field(min_length=1, max_length=128)
    from_agent_id: str = Field(min_length=1, max_length=128)
    to_agent_id: str = Field(min_length=1, max_length=128)
    artifact_ids: list[str] = Field(default_factory=list, max_length=50)
    destination_task_id: str | None = None
    confidence_threshold: float = Field(default=0.6, ge=0, le=1)
    contradictory_evidence_disclosed: bool = True

class WorkHandoffActorRequest(BaseModel):
    agent_id: str = Field(min_length=1,max_length=128)
    reason: str = Field(default='',max_length=2000)

@router.post("/work/contracts", tags=["Tasks"], summary="Create graph-backed handoff contract")
def work_create_handoff(body:WorkHandoffContractRequest,principal:Principal=Depends(require("CLAIM_TASK"))):
    client=client_for(principal);coord=CoordinationService(client)
    owner=(coord.get_task_owner(body.source_task_id) or {}).get('owner')
    if not owner or str(owner.get('id'))!=body.from_agent_id:
        raise ApiError(409,'INVALID_STATE_TRANSITION','Only the current owner can prepare a handoff contract')
    try:return HandoffService(client).create_handoff(body.source_task_id,body.from_agent_id,body.to_agent_id,artifact_ids=body.artifact_ids,destination_task_id=body.destination_task_id,confidence_threshold=body.confidence_threshold,contradictory_evidence_disclosed=body.contradictory_evidence_disclosed)
    except ValueError as exc:raise ApiError(409,'INVALID_REQUEST',str(exc)) from exc

@router.get("/work/contracts/{contract_id}/validation", tags=["Tasks"], summary="Validate recorded handoff contract")
def work_validate_handoff(contract_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    svc=HandoffService(client_for(principal))
    if svc.get_handoff(contract_id) is None:_not_found('Handoff',contract_id)
    return svc.validate_handoff(contract_id)

@router.post("/work/contracts/{contract_id}/accept", tags=["Tasks"], summary="Accept validated handoff contract")
def work_accept_handoff(contract_id:str,body:WorkHandoffActorRequest,principal:Principal=Depends(require("CLAIM_TASK"))):
    try:return HandoffService(client_for(principal)).accept_handoff(contract_id,body.agent_id)
    except ValueError as exc:raise ApiError(409,'INVALID_STATE_TRANSITION',str(exc)) from exc

@router.post("/work/contracts/{contract_id}/reject", tags=["Tasks"], summary="Reject a handoff contract")
def work_reject_handoff(contract_id:str,body:WorkHandoffActorRequest,principal:Principal=Depends(require("CLAIM_TASK"))):
    if len(body.reason.strip())<5:raise ApiError(422,'INVALID_REQUEST','Rejection requires an explanation')
    try:return HandoffService(client_for(principal)).reject_handoff(contract_id,body.agent_id,reason=body.reason)
    except ValueError as exc:raise ApiError(409,'INVALID_STATE_TRANSITION',str(exc)) from exc

class WorkBranchCreate(BaseModel):
    agent_id: str = Field(min_length=1,max_length=128)
    purpose: str = Field(min_length=5,max_length=500)

class WorkBranchFinding(BaseModel):
    agent_id: str = Field(min_length=1,max_length=128)
    statement: str = Field(min_length=3,max_length=4000)
    confidence: float = Field(ge=0,le=1)
    evidence_ids: list[str] = Field(default_factory=list,max_length=50)

@router.post("/work/executions/{execution_id}/branches", tags=["Tasks"], summary="Create isolated working-memory branch")
def work_create_branch(execution_id:str,body:WorkBranchCreate,principal:Principal=Depends(require("WRITE_FINDING"))):
    client=client_for(principal);snapshot=GraphSnapshot.load(client);execution=snapshot.node(execution_id)
    if not has_label(execution,'Execution'):_not_found('Execution',execution_id)
    task_id=str(execution.get('task_id') or '')
    owner=(CoordinationService(client).get_task_owner(task_id) or {}).get('owner')
    if not owner or str(owner.get('id'))!=body.agent_id:raise ApiError(409,'INVALID_STATE_TRANSITION','Only the active task owner can create branches')
    try:return BranchMemoryService(client).create_branch(execution_id,body.agent_id,purpose=body.purpose)
    except ValueError as exc:raise ApiError(409,'INVALID_REQUEST',str(exc)) from exc

@router.post("/work/branches/{branch_id}/findings", tags=["Tasks"], summary="Record isolated branch finding")
def work_branch_finding(branch_id:str,body:WorkBranchFinding,principal:Principal=Depends(require("WRITE_FINDING"))):
    client=client_for(principal);service=BranchMemoryService(client)
    detail=service.get_branch(branch_id)
    if detail is None:_not_found('WorkBranch',branch_id)
    owner=(CoordinationService(client).get_task_owner(str(detail['branch'].get('task_id') or '')) or {}).get('owner')
    if not owner or str(owner.get('id'))!=body.agent_id:raise ApiError(409,'INVALID_STATE_TRANSITION','Only the task owner can write a branch finding')
    try:return service.add_branch_finding(branch_id,body.agent_id,statement=body.statement,confidence=body.confidence,evidence_ids=body.evidence_ids)
    except ValueError as exc:raise ApiError(409,'INVALID_REQUEST',str(exc)) from exc

@router.post("/work/branches/{branch_id}/validate", tags=["Tasks"], summary="Validate isolated branch before promotion")
def work_validate_branch(branch_id:str,principal:Principal=Depends(require("WRITE_FINDING"))):
    service=BranchMemoryService(client_for(principal))
    if service.get_branch(branch_id) is None:_not_found('WorkBranch',branch_id)
    return service.validate_branch(branch_id)

@router.post("/work/branches/{branch_id}/merge", tags=["Tasks"], summary="Promote validated branch findings to shared graph")
def work_merge_branch(branch_id:str,body:TaskActorRequest,principal:Principal=Depends(require("WRITE_FINDING"))):
    client=client_for(principal);service=BranchMemoryService(client);detail=service.get_branch(branch_id)
    if detail is None:_not_found('WorkBranch',branch_id)
    owner=(CoordinationService(client).get_task_owner(str(detail['branch'].get('task_id') or '')) or {}).get('owner')
    if not owner or str(owner.get('id'))!=body.agent_id:raise ApiError(409,'INVALID_STATE_TRANSITION','Only the active task owner can promote branch findings')
    try:return service.merge_branch(branch_id,body.agent_id)
    except ValueError as exc:raise ApiError(409,'INVALID_STATE_TRANSITION',str(exc)) from exc

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
    return {"agent_id":agent_id,"agent_type":value.get("agent_type"),"capabilities":value.get("capabilities") or value.get("capabilities_csv"),"supported_task_types":value.get("supported_task_types"),"supported_tools":value.get("supported_tools"),"actions_may_propose":value.get("actions_may_propose"),"actions_may_execute":value.get("actions_may_execute"),"permissions":value.get("permissions") or value.get("permissions_csv"),"availability":value.get("availability"),"status":value.get("status")}

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

@router.get("/company-brain/sql-schema", tags=["Graph"], summary="Browse persisted SQL tables and foreign keys")
def company_brain_sql_schema(source_id:str|None=None,limit:int=Query(200,ge=1,le=200),principal:Principal=Depends(require("READ_GRAPH"))):
    return CompanyBrainSchemaService(client_for(principal)).list_tables(source_id=source_id,limit=limit)


@router.get("/company-brain/sql-schema/{table_id}", tags=["Graph"], summary="Inspect a persisted SQL table and source evidence")
def company_brain_sql_table(table_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    value=CompanyBrainSchemaService(client_for(principal)).table_detail(table_id)
    if value is None:_not_found("SQL table",table_id)
    return value


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


# -------------------- Phase 13 Source Control --------------------
def _sources(principal: Principal) -> SourceControlService:
    return SourceControlService(client_for(principal))

@router.get("/connectors", tags=["Sources"], summary="List supported connector definitions")
def list_connectors(principal:Principal=Depends(require("MANAGE_INGESTION"))):
    return {"items": _sources(principal).list_connectors()}

@router.get("/connectors/{connector_type}", tags=["Sources"], summary="Get connector definition")
def get_connector(connector_type:str, principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:return _sources(principal).connector(connector_type)
    except ValueError as exc: raise ApiError(404,"NOT_FOUND",str(exc)) from exc

@router.get("/sources", tags=["Sources"], summary="List organization source instances")
def list_sources(principal:Principal=Depends(require("MANAGE_INGESTION"))):
    return {"items": _sources(principal).list_sources()}

@router.post("/sources", tags=["Sources"], status_code=201, summary="Create a source instance")
def create_source(body:SourceCreateExternal, principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:return _sources(principal).create_source(body.model_dump(exclude_none=True), actor_id=principal.subject)
    except FileExistsError as exc: raise ApiError(409,"CONFLICT","A source with this ID already exists.",details={"source_id":str(exc)}) from exc
    except ValueError as exc: raise ApiError(422,"VALIDATION_FAILED",str(exc)) from exc

@router.get("/sources/catalog", tags=["Sources"], summary="List sources in authorized Company Brains")
def source_catalog(principal: Principal = Depends(require("READ_GRAPH"))):
    # Includes read-only Asteria fixture sources. Never treats them as active connectors.
    return list_source_catalog(tenant_id=principal.tenant_id)


@router.get("/sources/catalog/{source_id}/removal-impact", tags=["Sources"],
            summary="Inspect source lineage before disconnecting (read-only)")
def source_removal_impact(source_id: str, principal: Principal = Depends(require("MANAGE_INGESTION"))):
    if not principal.graph_id:
        raise ApiError(422, "GRAPH_REQUIRED", "Select an authorized Company Brain to inspect this source")
    try:
        return inspect_source_removal(tenant_id=principal.tenant_id,
                                      graph_id=principal.graph_id,
                                      source_id=source_id)
    except KeyError:
        _not_found("Source", source_id)
    except ValueError as exc:
        raise ApiError(422, "VALIDATION_FAILED", str(exc)) from exc


@router.delete("/sources/catalog/{source_id}", tags=["Sources"],
               summary="Remove source from catalog; retain historical evidence")
def remove_catalog_source(source_id: str, principal: Principal = Depends(require("MANAGE_INGESTION"))):
    if not principal.graph_id:
        raise ApiError(422, "GRAPH_REQUIRED", "Select an authorized Company Brain before removing a source")
    try:
        return remove_source_from_catalog(tenant_id=principal.tenant_id,
                                          graph_id=principal.graph_id,
                                          source_id=source_id, actor_id=principal.subject)
    except KeyError as exc:
        _not_found("Source", source_id)
    except ValueError as exc:
        raise ApiError(422, "VALIDATION_FAILED", str(exc)) from exc


@router.get("/sources/runs", tags=["Sources"], summary="List ingestion runs")
def list_ingestion_runs(source_id:str|None=None, principal:Principal=Depends(require("MANAGE_INGESTION"))):
    return {"items": _sources(principal).list_runs(source_id=source_id)}

@router.get("/sources/runs/{run_id}", tags=["Sources"], summary="Get ingestion run detail")
def get_ingestion_run(run_id:str, principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:return _sources(principal).get_run(run_id)
    except KeyError as exc: _not_found("IngestionRun",run_id)

@router.get("/sources/identity-review", tags=["Sources"], summary="List unresolved ingestion identities")
def list_identity_review(source_id:str|None=None,status:str="OPEN",principal:Principal=Depends(require("MANAGE_INGESTION"))):
    return {"items": _sources(principal).identity_review(source_id=source_id,status=status)}

@router.post("/sources/identity-review/{review_id}/resolve", tags=["Sources"], summary="Resolve an ambiguous source identity")
def resolve_identity(review_id:str,body:IdentityResolveExternal,principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:return _sources(principal).resolve_identity(review_id,body.action,actor_id=principal.subject,canonical_id=body.canonical_id,reason=body.reason)
    except KeyError as exc:_not_found("IdentityReview",review_id)
    except ValueError as exc:raise ApiError(422,"VALIDATION_FAILED",str(exc)) from exc

@router.get("/sources/{source_id}", tags=["Sources"], summary="Get a source instance")
def get_source(source_id:str, principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:return _sources(principal).get_source(source_id)
    except KeyError as exc:_not_found("Source",source_id)

@router.patch("/sources/{source_id}", tags=["Sources"], summary="Update a source instance")
def update_source(source_id:str,body:SourceUpdateExternal,principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:return _sources(principal).update_source(source_id,body.model_dump(exclude_none=True),actor_id=principal.subject)
    except KeyError as exc:_not_found("Source",source_id)

@router.post("/sources/{source_id}/test", tags=["Sources"], summary="Test a source connection without ingesting")
def test_source(source_id:str,principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:return _sources(principal).test_connection(source_id,actor_id=principal.subject)
    except KeyError as exc:_not_found("Source",source_id)

@router.get("/sources/{source_id}/mapping", tags=["Sources"], summary="Preview source mapping")
def source_mapping(source_id:str,principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:return _sources(principal).mapping_preview(source_id)
    except KeyError as exc:_not_found("Source",source_id)

@router.post("/sources/{source_id}/preview", tags=["Sources"], summary="Dry-run ingestion preview")
def preview_source(source_id:str,body:SourcePreviewExternal,principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:return _sources(principal).preview(source_id,max_records=body.max_records)
    except KeyError as exc:_not_found("Source",source_id)
    except ValueError as exc:raise ApiError(422,"VALIDATION_FAILED",str(exc)) from exc

@router.post("/sources/{source_id}/sync", tags=["Sources"], summary="Run source synchronization")
def sync_source(source_id:str,body:SourceSyncExternal,principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:return _sources(principal).sync(source_id,actor_id=principal.subject,mode=body.mode,max_records=body.max_records)
    except KeyError as exc:_not_found("Source",source_id)
    except ValueError as exc:raise ApiError(422,"VALIDATION_FAILED",str(exc)) from exc

@router.post("/sources/{source_id}/disable", tags=["Sources"], summary="Disable future synchronization")
def disable_source(source_id:str,principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:return _sources(principal).set_enabled(source_id,False,actor_id=principal.subject)
    except KeyError as exc:_not_found("Source",source_id)

@router.post("/sources/{source_id}/enable", tags=["Sources"], summary="Enable synchronization")
def enable_source(source_id:str,principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:return _sources(principal).set_enabled(source_id,True,actor_id=principal.subject)
    except KeyError as exc:_not_found("Source",source_id)

@router.delete("/sources/{source_id}", tags=["Sources"], summary="Remove active source configuration while retaining provenance")
def delete_source(source_id:str,principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:return _sources(principal).delete_configuration(source_id,actor_id=principal.subject)
    except KeyError as exc:_not_found("Source",source_id)

@router.get("/sources/{source_id}/runs", tags=["Sources"], summary="List source ingestion runs")
def source_runs(source_id:str,principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:_sources(principal).get_source(source_id)
    except KeyError as exc:_not_found("Source",source_id)
    return {"items":_sources(principal).list_runs(source_id=source_id)}

@router.get("/sources/{source_id}/records", tags=["Sources"], summary="Browse bounded source records")
def source_records(source_id:str,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:return _sources(principal).list_records(source_id,limit=limit,offset=offset)
    except KeyError as exc:_not_found("Source",source_id)

@router.get("/sources/{source_id}/errors", tags=["Sources"], summary="List source ingestion errors and review items")
def source_errors(source_id:str,principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:_sources(principal).get_source(source_id)
    except KeyError as exc:_not_found("Source",source_id)
    return {"items":_sources(principal).errors(source_id)}

@router.get("/sources/{source_id}/identity-review", tags=["Sources"], summary="List identity issues for a source")
def source_identity_review(source_id:str,principal:Principal=Depends(require("MANAGE_INGESTION"))):
    try:_sources(principal).get_source(source_id)
    except KeyError as exc:_not_found("Source",source_id)
    return {"items":_sources(principal).identity_review(source_id=source_id)}

@router.get("/lineage/entities/{entity_id}", tags=["Sources","Entities"], summary="Explain how GraphHacks learned an entity")
def entity_lineage(entity_id:str,principal:Principal=Depends(require("READ_GRAPH"))):
    try:return _sources(principal).lineage_for_entity(entity_id)
    except KeyError as exc:_not_found("Entity",entity_id)
