from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import backend.app.api_v1.router as v1_router
from backend.app.main import app
from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.retrieval.lexical import BM25LexicalIndex
from backend.app.retrieval.models import IndexedDocument
from backend.app.retrieval.service import RetrievalService
from backend.app.retrieval.utils import content_hash
from backend.app.retrieval.vector import LocalVectorIndex
from backend.app.services.agent_registry_service import AgentRegistryService
from backend.app.services.phase4_graph import GraphSnapshot
from backend.app.services.phase6_utils import now_iso

pytestmark = pytest.mark.integration
ADMIN={"Authorization":"Bearer test-admin-token","X-Tenant-ID":"northstar"}
READER={"Authorization":"Bearer test-reader-token","X-Tenant-ID":"northstar"}


def _tenant_client(base, tenant: str):
    s=base.settings
    return FalkorGraphClient(Settings(falkordb_host=s.falkordb_host,falkordb_port=s.falkordb_port,falkordb_graph=s.falkordb_graph,falkordb_password=s.falkordb_password,tenant_id=tenant))


def _seed_retrieval(client):
    ids={"incident":"INC-P11-RET","system":"SYS-P11-RET","source":"DS-P11-RET","record":"SR-P11-RET","artifact":"ART-P11-RET","chunk":"CH-P11-RET"}
    upsert_node(client,"Incident",ids["incident"],{"name":"P11 retrieval incident","created_at":"2026-10-16T14:00:00+05:30"})
    upsert_node(client,"System",ids["system"],{"name":"P11 Pricing API"})
    upsert_node(client,"DataSource",ids["source"],{"name":"P11 logs","source_type":"telemetry","trust_class":"STRONG"})
    upsert_node(client,"SourceRecord",ids["record"],{"name":"P11 log","source_type":"telemetry","source_id":ids["source"],"observed_at":"2026-10-16T14:08:14+05:30","raw_metadata":"region_scope cannot be null"})
    upsert_node(client,"Artifact",ids["artifact"],{"name":"p11-pricing.log","sha256":content_hash("p11"),"mime_type":"text/plain"})
    upsert_node(client,"Chunk",ids["chunk"],{"name":"P11 error chunk","content_hash":content_hash("p11chunk")})
    upsert_relationship(client,ids["incident"],"AFFECTS",ids["system"],{"valid_from":"2026-10-16T14:00:00+05:30"})
    upsert_relationship(client,ids["record"],"NORMALIZED_TO",ids["system"],{"valid_from":"2026-10-16T14:08:14+05:30"})
    upsert_relationship(client,ids["record"],"DERIVED_FROM",ids["source"],{"valid_from":"2026-10-16T14:08:14+05:30"})
    upsert_relationship(client,ids["record"],"REFERENCES",ids["artifact"],{"valid_from":"2026-10-16T14:08:14+05:30"})
    upsert_relationship(client,ids["chunk"],"PART_OF",ids["artifact"],{"valid_from":"2026-10-16T14:08:14+05:30"})
    lex=BM25LexicalIndex(); vec=LocalVectorIndex()
    doc=IndexedDocument(document_id=ids["chunk"],text="region_scope cannot be null after MIG-203 mixed version compatibility",tenant_id=client.settings.tenant_id,artifact_id=ids["artifact"],source_record_id=ids["record"],data_source_id=ids["source"],entity_ids=[ids["system"]],document_type="CHUNK",observed_at="2026-10-16T14:08:14+05:30",content_hash=content_hash("p11 indexed"))
    lex.index_document(doc);vec.index_document(doc)
    return ids, RetrievalService(client,lexical=lex,vector=vec)

@pytest.fixture
def v1_api(integration_client, monkeypatch):
    AgentRegistryService(integration_client).ensure_default_agents()
    ids,retrieval=_seed_retrieval(integration_client)
    def routed(principal):
        if principal.tenant_id==integration_client.settings.tenant_id:return integration_client
        return _tenant_client(integration_client,principal.tenant_id)
    monkeypatch.setattr(v1_router,"client_for",routed)
    monkeypatch.setattr(v1_router,"_retrieval_service_for",lambda principal: retrieval if principal.tenant_id==integration_client.settings.tenant_id else RetrievalService(_tenant_client(integration_client,principal.tenant_id),lexical=BM25LexicalIndex(),vector=LocalVectorIndex()))
    return TestClient(app), ids


def _task(client, task_type="INVESTIGATE"):
    tid=f"TASK-P11-{uuid.uuid4().hex[:12]}"
    upsert_node(client,"Task",tid,{"name":"Phase 11 API task","title":"Phase 11 API task","task_type":task_type,"objective":"Exercise external API","status":"OPEN","priority":"P1","created_at":now_iso(),"expected_output_type":"ACTION_PROPOSAL" if task_type=="PREPARE_ACTION" else "INVESTIGATION_RESULT","completion_condition":"External API flow succeeds"})
    return tid


def test_phase11_api_lists_situations(v1_api):
    api,_=v1_api; r=api.get("/api/v1/situations",headers=READER); assert r.status_code==200 and any(x["id"]=="INC-001" for x in r.json()["items"])

def test_phase11_api_gets_canonical_situation(v1_api):
    api,_=v1_api; r=api.get("/api/v1/situations/INC-001",headers=READER); assert r.status_code==200 and r.json()["id"]=="INC-001"

def test_phase11_api_situation_context(v1_api):
    api,_=v1_api; r=api.get("/api/v1/situations/INC-001/context",headers=READER); assert r.status_code==200 and r.json()["situation"]["id"]=="INC-001"

def test_phase11_api_situation_timeline(v1_api):
    api,_=v1_api; r=api.get("/api/v1/situations/INC-001/timeline",headers=READER); assert r.status_code==200 and isinstance(r.json()["events"],list)

def test_phase11_api_situation_claims(v1_api):
    api,_=v1_api; r=api.get("/api/v1/situations/INC-001/claims",headers=READER); assert r.status_code==200 and isinstance(r.json()["items"],list)

def test_phase11_api_situation_evidence(v1_api):
    api,_=v1_api; r=api.get("/api/v1/situations/INC-001/evidence",headers=READER); assert r.status_code==200 and any(x["id"]=="E-003" for x in r.json()["items"])

def test_phase11_api_entity_get(v1_api):
    api,_=v1_api; r=api.get("/api/v1/entities/SYS-PRICING-API",headers=READER); assert r.status_code==200 and r.json()["id"]=="SYS-PRICING-API"

def test_phase11_api_entity_search(v1_api):
    api,_=v1_api; r=api.get("/api/v1/entities/search",params={"q":"Pricing API"},headers=READER); assert r.status_code==200 and any(x["id"]=="SYS-PRICING-API" for x in r.json()["items"])

def test_phase11_api_entity_neighbors(v1_api):
    api,_=v1_api; r=api.get("/api/v1/entities/SYS-PRICING-API/neighbors",headers=READER); assert r.status_code==200 and r.json()["items"]

def test_phase11_api_entity_relationships(v1_api):
    api,_=v1_api; r=api.get("/api/v1/entities/SYS-PRICING-API/relationships",headers=READER); assert r.status_code==200 and isinstance(r.json()["items"],list)

def test_phase11_api_entity_provenance(v1_api):
    api,_=v1_api; r=api.get("/api/v1/entities/SYS-PRICING-API/provenance",headers=READER); assert r.status_code==200 and r.json()["entity_id"]=="SYS-PRICING-API"

def test_phase11_api_entity_history(v1_api):
    api,_=v1_api; r=api.get("/api/v1/entities/SYS-PRICING-API/history",headers=READER); assert r.status_code==200 and "relationship_history" in r.json()

def test_phase11_api_historical_entity_excludes_future_relationships(v1_api):
    api,_=v1_api; r=api.get("/api/v1/history/entities/SYS-PRICING-API/at",params={"as_of":"2026-10-16T14:09:00+05:30"},headers=READER); assert r.status_code==200 and r.json()["as_of"].startswith("2026-10-16T14:09")

def test_phase11_api_bounded_path(v1_api):
    api,_=v1_api; r=api.get("/api/v1/paths",params={"from":"INC-001","to":"SYS-PRICING-DB","max_hops":6},headers=READER); assert r.status_code==200 and isinstance(r.json()["paths"],list)

def test_phase11_api_no_path_case(v1_api,integration_client):
    isolated=f"SYS-P11-ISO-{uuid.uuid4().hex[:6]}";upsert_node(integration_client,"System",isolated,{"name":"isolated"})
    api,_=v1_api;r=api.get("/api/v1/paths",params={"from":"INC-001","to":isolated,"max_hops":3},headers=READER);assert r.status_code==200 and r.json()["paths"]==[]

def test_phase11_api_blast_radius(v1_api):
    api,_=v1_api; r=api.get("/api/v1/entities/SYS-PRICING-DB/blast-radius",headers=READER); assert r.status_code==200 and r.json()["entity"]["id"]=="SYS-PRICING-DB"

def test_phase11_api_claims_pagination(v1_api):
    api,_=v1_api;r1=api.get("/api/v1/claims",params={"limit":1},headers=READER);assert r1.status_code==200 and len(r1.json()["items"])==1
    if r1.json()["next_cursor"]:
        r2=api.get("/api/v1/claims",params={"limit":1,"cursor":r1.json()["next_cursor"]},headers=READER);assert r2.status_code==200 and r2.json()["items"][0]["id"]!=r1.json()["items"][0]["id"]

def test_phase11_api_claim_detail(v1_api):
    api,_=v1_api;r=api.get("/api/v1/claims/C-002",headers=READER);assert r.status_code==200 and r.json()["id"]=="C-002"

def test_phase11_api_claim_evidence(v1_api):
    api,_=v1_api;r=api.get("/api/v1/claims/C-002/evidence",headers=READER);assert r.status_code==200 and "supporting" in r.json()

def test_phase11_api_claim_conflicts(v1_api):
    api,_=v1_api;r=api.get("/api/v1/claims/C-001/conflicts",headers=READER);assert r.status_code==200 and "items" in r.json()

def test_phase11_api_claim_lineage(v1_api):
    api,_=v1_api;r=api.get("/api/v1/claims/C-002/lineage",headers=READER);assert r.status_code==200 and "relationships" in r.json()

def test_phase11_api_evidence_list_and_get(v1_api):
    api,_=v1_api;r=api.get("/api/v1/evidence",headers=READER);assert r.status_code==200 and any(x["id"]=="E-003" for x in r.json()["items"])
    assert api.get("/api/v1/evidence/E-003",headers=READER).status_code==200

def test_phase11_api_evidence_provenance(v1_api):
    api,_=v1_api;r=api.get("/api/v1/evidence/E-003/provenance",headers=READER);assert r.status_code==200 and r.json()["entity_id"]=="E-003"

def test_phase11_api_artifact_metadata(v1_api):
    api,ids=v1_api;r=api.get(f"/api/v1/artifacts/{ids['artifact']}/metadata",headers=READER);assert r.status_code==200 and r.json()["id"]==ids["artifact"]

def test_phase11_api_plan_create_get_and_tasks(v1_api):
    api,_=v1_api;r=api.post("/api/v1/plans",headers={**ADMIN,"Idempotency-Key":f"p-{uuid.uuid4().hex}"},json={"situation_id":"INC-001","goal":"Resolve INC-001 safely"});assert r.status_code==201
    pid=r.json()["plan"]["id"] if "plan" in r.json() else r.json()["id"]
    assert api.get(f"/api/v1/plans/{pid}",headers=READER).status_code==200
    assert api.get(f"/api/v1/plans/{pid}/tasks",headers=READER).status_code==200

def test_phase11_api_task_detail_dependencies_and_coordination(v1_api,integration_client):
    tid=_task(integration_client);api,_=v1_api
    assert api.get(f"/api/v1/tasks/{tid}",headers=READER).status_code==200
    assert api.get(f"/api/v1/tasks/{tid}/dependencies",headers=READER).status_code==200
    assert api.get(f"/api/v1/tasks/{tid}/coordination-state",headers=READER).status_code==200

def test_phase11_api_task_claim_start_checkpoint(v1_api,integration_client):
    tid=_task(integration_client,"INVESTIGATE");api,_=v1_api
    claim=api.post(f"/api/v1/tasks/{tid}/claim",headers=ADMIN,json={"agent_id":"AGENT-P6-INVESTIGATOR"});assert claim.status_code==200
    start=api.post(f"/api/v1/tasks/{tid}/start",headers=ADMIN,json={"agent_id":"AGENT-P6-INVESTIGATOR"});assert start.status_code==200;eid=start.json()["execution"]["id"]
    cp=api.post(f"/api/v1/tasks/{tid}/checkpoint",headers=ADMIN,json={"agent_id":"AGENT-P6-INVESTIGATOR","execution_id":eid,"step_index":1,"current_step":"inspect evidence","completed_steps":[],"pending_steps":["verify"],"state_summary":"working"});assert cp.status_code==200

def test_phase11_api_invalid_task_transition_returns_409(v1_api,integration_client):
    tid=_task(integration_client,"PREPARE_ACTION");api,_=v1_api;r=api.post(f"/api/v1/tasks/{tid}/claim",headers=ADMIN,json={"agent_id":"AGENT-P6-VERIFIER"});assert r.status_code==409 and r.json()["error"]["code"]=="INVALID_STATE_TRANSITION"

def test_phase11_api_concurrent_claim_has_single_owner(v1_api,integration_client):
    tid=_task(integration_client,"INVESTIGATE");api,_=v1_api
    def claim(agent):return api.post(f"/api/v1/tasks/{tid}/claim",headers=ADMIN,json={"agent_id":agent}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool: codes=list(pool.map(claim,["AGENT-P6-INVESTIGATOR","AGENT-P6-DEPENDENCY"]))
    assert codes.count(200)==1 and codes.count(409)==1

def test_phase11_api_agents_list_detail_capabilities_tasks(v1_api):
    api,_=v1_api;r=api.get("/api/v1/agents",headers=READER);assert r.status_code==200 and any(x["id"]=="AGENT-P6-INVESTIGATOR" for x in r.json()["items"])
    assert api.get("/api/v1/agents/AGENT-P6-INVESTIGATOR",headers=READER).status_code==200
    assert api.get("/api/v1/agents/AGENT-P6-INVESTIGATOR/capabilities",headers=READER).status_code==200
    assert api.get("/api/v1/agents/AGENT-P6-INVESTIGATOR/tasks",headers=READER).status_code==200

def test_phase11_api_decision_and_genealogy(v1_api):
    api,_=v1_api;assert api.get("/api/v1/decisions/DEC-INC001-ROLLBACK",headers=READER).status_code==200
    r=api.get("/api/v1/decisions/DEC-INC001-ROLLBACK/genealogy",headers=READER);assert r.status_code==200 and r.json()["complete"] is True

def test_phase11_api_decision_evidence_and_outcomes(v1_api):
    api,_=v1_api;assert api.get("/api/v1/decisions/DEC-INC001-ROLLBACK/evidence",headers=READER).status_code==200
    assert api.get("/api/v1/decisions/DEC-INC001-ROLLBACK/outcomes",headers=READER).status_code==200

def test_phase11_api_action_governance_and_exactly_once(v1_api,integration_client):
    tid=_task(integration_client,"PREPARE_ACTION");api,_=v1_api
    assert api.post(f"/api/v1/tasks/{tid}/claim",headers=ADMIN,json={"agent_id":"AGENT-P6-REMEDIATION"}).status_code==200
    assert api.post(f"/api/v1/tasks/{tid}/start",headers=ADMIN,json={"agent_id":"AGENT-P6-REMEDIATION"}).status_code==200
    key=f"act-{uuid.uuid4().hex}";prop=api.post("/api/v1/actions",headers={**ADMIN,"Idempotency-Key":key},json={"task_id":tid,"agent_id":"AGENT-P6-REMEDIATION","name":"P11 sandbox rollback","action_type":"rollback","target_ids":["SYS-PRICING-DB"],"approval_required":False});assert prop.status_code==201;aid=prop.json()["action"]["id"]
    gov=api.get(f"/api/v1/actions/{aid}/governance",params={"agent_id":"AGENT-P6-REMEDIATION"},headers=READER);assert gov.status_code==200 and gov.json()["decision"]=="ALLOW"
    exec_key=f"exec-{uuid.uuid4().hex}";first=api.post(f"/api/v1/actions/{aid}/execute",headers={**ADMIN,"Idempotency-Key":exec_key},json={"agent_id":"AGENT-P6-REMEDIATION"});second=api.post(f"/api/v1/actions/{aid}/execute",headers={**ADMIN,"Idempotency-Key":exec_key},json={"agent_id":"AGENT-P6-REMEDIATION"});assert first.status_code==200 and second.status_code==200 and first.json()==second.json()
    attempts=api.get(f"/api/v1/actions/{aid}/attempts",headers=READER);assert attempts.status_code==200 and len(attempts.json()["items"])==1

def test_phase11_api_counterfactual_simulation_does_not_mutate_graph(v1_api,integration_client):
    api,_=v1_api;before=len(GraphSnapshot.load(integration_client).nodes);r=api.post("/api/v1/simulations/counterfactual",headers=READER,json={"situation_id":"SYS-PRICING-DB","interventions":[{"type":"REMOVE_DEPENDENCY","source":"SYS-CHECKOUT","target":"SYS-PRICING-API"}]});assert r.status_code==200 and r.json()["persisted"] is False;assert len(GraphSnapshot.load(integration_client).nodes)==before

def test_phase11_api_bus_factor_simulation(v1_api):
    api,_=v1_api;r=api.post("/api/v1/simulations/bus-factor",headers=READER,json={"actor_ids":["PERSON-RIYA"]});assert r.status_code==200 and r.json()["simulation_type"]=="BUS_FACTOR"

def test_phase11_api_process_reconstruction_keeps_semantics_distinct(v1_api):
    api,_=v1_api;r=api.get("/api/v1/processes/INC-001",headers=READER);assert r.status_code==200 and all(k in r.json() for k in ["temporal_edges","trigger_edges","dependency_edges","causal_edges"])

def test_phase11_api_policy_drift(v1_api):
    api,_=v1_api;r=api.get("/api/v1/processes/INC-001/policy-drift",params={"policy_id":"POL-DB-04"},headers=READER);assert r.status_code==200 and r.json()["policy"]["id"]=="POL-DB-04"

def test_phase11_api_bus_factor_risk(v1_api):
    api,_=v1_api;assert api.get("/api/v1/risks/bus-factor",headers=READER).status_code==200

def test_phase11_api_bottleneck_and_bridge_risks(v1_api):
    api,_=v1_api;assert api.get("/api/v1/risks/bottlenecks",headers=READER).status_code==200;assert api.get("/api/v1/risks/bridges",headers=READER).status_code==200

def test_phase11_api_initiative_collision_risk(v1_api):
    api,_=v1_api;assert api.get("/api/v1/risks/initiative-collisions",headers=READER).status_code==200

def test_phase11_api_ownership_gap_and_commitment_risks(v1_api):
    api,_=v1_api;assert api.get("/api/v1/risks/ownership-gaps",headers=READER).status_code==200;assert api.get("/api/v1/risks/commitments",headers=READER).status_code==200

def test_phase11_api_create_investigation_is_idempotent(v1_api):
    api,ids=v1_api;key=f"inv-{uuid.uuid4().hex}";body={"situation_id":ids["incident"],"question":"Why did pricing fail?","seed_entity_ids":[ids["incident"]]}
    a=api.post("/api/v1/investigations",headers={**ADMIN,"Idempotency-Key":key},json=body);b=api.post("/api/v1/investigations",headers={**ADMIN,"Idempotency-Key":key},json=body);assert a.status_code==201 and b.status_code==201 and a.json()["id"]==b.json()["id"]

def test_phase11_api_idempotency_key_conflicting_reuse_is_409(v1_api):
    api,ids=v1_api;key=f"inv-{uuid.uuid4().hex}";a=api.post("/api/v1/investigations",headers={**ADMIN,"Idempotency-Key":key},json={"situation_id":ids["incident"],"question":"q1"});assert a.status_code==201
    b=api.post("/api/v1/investigations",headers={**ADMIN,"Idempotency-Key":key},json={"situation_id":ids["incident"],"question":"q2"});assert b.status_code==409 and b.json()["error"]["code"]=="CONFLICT"

def test_phase11_api_investigation_retrieval_writes_explainable_evidence(v1_api):
    api,ids=v1_api;created=api.post("/api/v1/investigations",headers=ADMIN,json={"situation_id":ids["incident"],"question":"region_scope cannot be null","seed_entity_ids":[ids["incident"]]});iid=created.json()["id"]
    r=api.post(f"/api/v1/investigations/{iid}/retrieve",headers=READER,json={"query":"region_scope cannot be null","retrieval_modes":["LEXICAL"]});assert r.status_code==200 and r.json()["graph_required"] is True and r.json()["evidence_ids"]
    assert api.get(f"/api/v1/investigations/{iid}/evidence",headers=READER).json()["items"]
    assert api.get(f"/api/v1/investigations/{iid}/retrievals",headers=READER).json()["items"]

def test_phase11_api_retrieval_excludes_global_out_of_scope_distractor(v1_api):
    api,ids=v1_api;r=api.post("/api/v1/retrieval/search",headers=READER,json={"query":"region_scope cannot be null","seed_entity_ids":[ids["incident"]],"retrieval_modes":["LEXICAL"]});assert r.status_code==200 and all(x.get("artifact_id")==ids["artifact"] for x in r.json()["results"])

def test_phase11_api_close_investigation(v1_api):
    api,ids=v1_api;c=api.post("/api/v1/investigations",headers=ADMIN,json={"situation_id":ids["incident"],"question":"close me"});iid=c.json()["id"];r=api.post(f"/api/v1/investigations/{iid}/close",headers=ADMIN);assert r.status_code==200 and r.json()["status"]=="CLOSED"

def test_phase11_api_situation_creation_idempotency(v1_api):
    api,_=v1_api;key=f"sit-{uuid.uuid4().hex}";body={"name":"External incident"};a=api.post("/api/v1/situations",headers={**ADMIN,"Idempotency-Key":key},json=body);b=api.post("/api/v1/situations",headers={**ADMIN,"Idempotency-Key":key},json=body);assert a.status_code==201 and a.json()["id"]==b.json()["id"]

def test_phase11_api_cross_tenant_entity_isolation(v1_api,integration_client):
    other=_tenant_client(integration_client,"other-tenant");upsert_node(other,"System","SYS-P11-OTHER",{"name":"Other tenant system"});api,_=v1_api
    assert api.get("/api/v1/entities/SYS-P11-OTHER",headers=READER).status_code==404
    r=api.get("/api/v1/entities/SYS-P11-OTHER",headers={"Authorization":"Bearer test-other-admin-token","X-Tenant-ID":"other-tenant"});assert r.status_code==200 and r.json()["id"]=="SYS-P11-OTHER"

def test_phase11_api_cross_tenant_task_mutation_is_blocked(v1_api,integration_client):
    other=_tenant_client(integration_client,"other-tenant");tid=f"TASK-P11-OTHER-{uuid.uuid4().hex[:6]}";upsert_node(other,"Task",tid,{"name":"Other tenant task","task_type":"INVESTIGATE","status":"OPEN","created_at":now_iso()});api,_=v1_api
    assert api.post(f"/api/v1/tasks/{tid}/claim",headers=ADMIN,json={"agent_id":"AGENT-P6-INVESTIGATOR"}).status_code!=200
    assert GraphSnapshot.load(other).node(tid)["status"]=="OPEN"

def test_phase11_api_request_id_on_real_graph_response(v1_api):
    api,_=v1_api;r=api.get("/api/v1/entities/INC-001",headers={**READER,"X-Request-ID":"integration-req-1"});assert r.status_code==200 and r.headers["X-Request-ID"]=="integration-req-1"


def test_phase11_api_graph_necessity_dependency_removal_changes_blast_radius(v1_api,integration_client):
    from backend.app.graph.mutations import delete_relationship
    root=f"SYS-P11-GN-ROOT-{uuid.uuid4().hex[:6]}";dep=f"SYS-P11-GN-DEP-{uuid.uuid4().hex[:6]}";at=now_iso()
    upsert_node(integration_client,"System",root,{"name":"GN root","status":"ACTIVE"});upsert_node(integration_client,"System",dep,{"name":"GN dependent","status":"ACTIVE"});props={"valid_from":at,"confidence":1.0};upsert_relationship(integration_client,dep,"DEPENDS_ON",root,props)
    api,_=v1_api
    try:
        before=api.get(f"/api/v1/entities/{root}/blast-radius",headers=READER).json();assert dep in {x["system"]["id"] for x in before["downstream_dependents"]}
        assert delete_relationship(integration_client,dep,"DEPENDS_ON",root)>=1
        after=api.get(f"/api/v1/entities/{root}/blast-radius",headers=READER).json();assert dep not in {x["system"]["id"] for x in after["downstream_dependents"]}
    finally:upsert_relationship(integration_client,dep,"DEPENDS_ON",root,props)


def test_phase11_api_graph_necessity_support_edge_changes_claim_evidence(v1_api,integration_client):
    from backend.app.graph.mutations import delete_relationship
    cid=f"C-P11-GN-{uuid.uuid4().hex[:6]}";eid=f"E-P11-GN-{uuid.uuid4().hex[:6]}";at=now_iso();upsert_node(integration_client,"Claim",cid,{"statement":"GN claim","status":"OPEN","created_at":at});upsert_node(integration_client,"Evidence",eid,{"name":"GN evidence","observed_at":at,"created_at":at});props={"valid_from":at};upsert_relationship(integration_client,eid,"SUPPORTS",cid,props);api,_=v1_api
    try:
        before=api.get(f"/api/v1/claims/{cid}/evidence",headers=READER).json();assert eid in {x["evidence"]["id"] for x in before["supporting"]}
        delete_relationship(integration_client,eid,"SUPPORTS",cid);after=api.get(f"/api/v1/claims/{cid}/evidence",headers=READER).json();assert eid not in {x["evidence"]["id"] for x in after["supporting"]}
    finally:upsert_relationship(integration_client,eid,"SUPPORTS",cid,props)


def test_phase11_api_graph_necessity_decision_based_on_edge_changes_genealogy(v1_api,integration_client):
    from backend.app.graph.mutations import delete_relationship
    suffix=uuid.uuid4().hex[:6];did=f"DEC-P11-GN-{suffix}";cid=f"C-P11-DEC-{suffix}";pid=f"PERSON-P11-DEC-{suffix}";at=now_iso();upsert_node(integration_client,"Decision",did,{"name":"GN decision","created_at":at});upsert_node(integration_client,"Claim",cid,{"statement":"GN input","status":"OPEN","created_at":at});upsert_node(integration_client,"Person",pid,{"name":"GN actor","status":"ACTIVE"});props={"valid_from":at};upsert_relationship(integration_client,did,"BASED_ON",cid,props);upsert_relationship(integration_client,pid,"PRODUCED",did,props);api,_=v1_api
    try:
        before=api.get(f"/api/v1/decisions/{did}/genealogy",headers=READER).json();assert cid in {x["entity"]["id"] for x in before["claims"]}
        delete_relationship(integration_client,did,"BASED_ON",cid);after=api.get(f"/api/v1/decisions/{did}/genealogy",headers=READER).json();assert cid not in {x["entity"]["id"] for x in after["claims"]}
    finally:upsert_relationship(integration_client,did,"BASED_ON",cid,props)


def test_phase11_api_graph_necessity_ownership_edge_changes_risk(v1_api,integration_client):
    from backend.app.graph.mutations import delete_relationship
    suffix=uuid.uuid4().hex[:6];sid=f"SYS-P11-OWN-{suffix}";tid=f"TEAM-P11-OWN-{suffix}";at=now_iso();upsert_node(integration_client,"System",sid,{"name":"GN owned system","status":"ACTIVE","criticality":"LOW"});upsert_node(integration_client,"Team",tid,{"name":"GN owner","status":"ACTIVE"});props={"valid_from":at,"confidence":1.0,"authoritative":True};upsert_relationship(integration_client,tid,"OWNS",sid,props);api,_=v1_api
    try:
        before=api.get("/api/v1/risks/ownership-gaps",headers=READER).json();assert sid not in {x["resource"]["id"] for x in before["resources"]}
        delete_relationship(integration_client,tid,"OWNS",sid);after=api.get("/api/v1/risks/ownership-gaps",headers=READER).json();assert sid in {x["resource"]["id"] for x in after["resources"]}
    finally:upsert_relationship(integration_client,tid,"OWNS",sid,props)


def test_phase11_api_graph_necessity_returned_edge_controls_retrieval_provenance(v1_api,integration_client):
    from backend.app.graph.mutations import delete_relationship
    suffix=uuid.uuid4().hex[:6];iid=f"INV-P11-GN-{suffix}";rid=f"RET-P11-GN-{suffix}";eid=f"E-P11-RET-{suffix}";at=now_iso();upsert_node(integration_client,"Investigation",iid,{"question":"GN","status":"OPEN","created_at":at});upsert_node(integration_client,"RetrievalExecution",rid,{"query":"GN","status":"SUCCEEDED","started_at":at,"completed_at":at});upsert_node(integration_client,"Evidence",eid,{"name":"GN retrieved","status":"UNVERIFIED","observed_at":at,"created_at":at});p={"valid_from":at};upsert_relationship(integration_client,iid,"HAS_RETRIEVAL",rid,p);upsert_relationship(integration_client,rid,"RETURNED",eid,p);upsert_relationship(integration_client,eid,"ABOUT",iid,p);api,_=v1_api
    try:
        before=api.get(f"/api/v1/investigations/{iid}/evidence",headers=READER).json();item=next(x for x in before["items"] if x["id"]==eid);assert rid in item["retrieval_execution_ids"] and item["retrieval_provenance_complete"] is True
        delete_relationship(integration_client,rid,"RETURNED",eid);after=api.get(f"/api/v1/investigations/{iid}/evidence",headers=READER).json();item=next(x for x in after["items"] if x["id"]==eid);assert item["retrieval_execution_ids"]==[] and item["retrieval_provenance_complete"] is False
    finally:upsert_relationship(integration_client,rid,"RETURNED",eid,p)


def test_phase11_api_graph_necessity_before_edge_changes_process(v1_api,integration_client):
    from backend.app.graph.mutations import delete_relationship
    suffix=uuid.uuid4().hex[:6];iid=f"INC-P11-PROC-{suffix}";a=f"EVT-P11-A-{suffix}";b=f"EVT-P11-B-{suffix}";t1="2026-10-16T14:00:00+05:30";t2="2026-10-16T14:01:00+05:30";upsert_node(integration_client,"Incident",iid,{"name":"GN process","created_at":t1});upsert_node(integration_client,"Event",a,{"event_type":"A","occurred_at":t1,"created_at":t1});upsert_node(integration_client,"Event",b,{"event_type":"B","occurred_at":t2,"created_at":t2});upsert_relationship(integration_client,a,"ABOUT",iid,{"valid_from":t1});upsert_relationship(integration_client,b,"ABOUT",iid,{"valid_from":t2});props={"valid_from":t1};upsert_relationship(integration_client,a,"BEFORE",b,props);api,_=v1_api
    try:
        before=api.get(f"/api/v1/processes/{iid}",headers=READER).json();assert any(x.get("source")==a and x.get("target")==b for x in before["temporal_edges"])
        delete_relationship(integration_client,a,"BEFORE",b);after=api.get(f"/api/v1/processes/{iid}",headers=READER).json();assert not any(x.get("source")==a and x.get("target")==b for x in after["temporal_edges"])
    finally:upsert_relationship(integration_client,a,"BEFORE",b,props)
