from __future__ import annotations

import json, os, sys, tempfile, uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.schema import apply_schema
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.ingestion.artifacts.local import LocalArtifactStore
from backend.app.ingestion.models import ArtifactPayload, ArtifactType
from backend.app.retrieval.indexing import RetrievalIndexer
from backend.app.retrieval.lexical import BM25LexicalIndex
from backend.app.retrieval.vector import LocalVectorIndex
from backend.app.services.agent_registry_service import AgentRegistryService
from backend.app.services.phase4_graph import GraphSnapshot
from backend.app.services.phase6_utils import now_iso
from scripts.seed_lib import seed_all


def check(value: bool, message: str, checks: list[dict]):
    checks.append({"check":message,"passed":bool(value)})
    if not value: raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> int:
    graph_name=f"phase11_api_accept_{uuid.uuid4().hex[:10]}"
    temp=Path(tempfile.mkdtemp(prefix="graphhacks-phase11-"))
    os.environ["FALKORDB_GRAPH"]=graph_name
    os.environ["GRAPH_TENANT_ID"]="northstar"
    os.environ["GRAPH_HACKS_ARTIFACT_ROOT"]=str(temp/"artifacts")
    os.environ["GRAPH_HACKS_RETRIEVAL_ROOT"]=str(temp/"retrieval")
    settings=Settings.from_env()
    try:
        client=FalkorGraphClient(settings);client.delete_graph();apply_schema(client);seed_all(client);AgentRegistryService(client).ensure_default_agents()
    except Exception as exc:
        print(f"PHASE 11 API ACCEPTANCE: CANNOT RUN\n{type(exc).__name__}: {exc}")
        return 2

    # Seed one graph-scoped retrieval artifact into the same configured indexes used by /api/v1.
    store=LocalArtifactStore(temp/"artifacts")
    payload=ArtifactPayload(name="phase11-pricing.log",content="14:08:14 ERROR region_scope cannot be null after MIG-203 during mixed-version rollout",mime_type="text/plain",artifact_type=ArtifactType.LOG)
    meta=store.put(payload,tenant_id="northstar",source_type="telemetry",source_record_id="SR-P11-VERIFY")
    upsert_node(client,"DataSource","DS-P11-VERIFY",{"name":"Phase11 pricing logs","source_type":"telemetry","trust_class":"STRONG"})
    upsert_node(client,"SourceRecord","SR-P11-VERIFY",{"name":"pricing failure log","source_type":"telemetry","source_id":"DS-P11-VERIFY","observed_at":"2026-10-16T14:08:14+05:30","raw_metadata":"region_scope cannot be null"})
    upsert_node(client,"Artifact",meta.artifact_id,meta.model_dump(mode="json"))
    upsert_relationship(client,"SR-P11-VERIFY","NORMALIZED_TO","SYS-PRICING-API",{"valid_from":"2026-10-16T14:08:14+05:30"})
    upsert_relationship(client,"SR-P11-VERIFY","DERIVED_FROM","DS-P11-VERIFY",{"valid_from":"2026-10-16T14:08:14+05:30"})
    upsert_relationship(client,"SR-P11-VERIFY","REFERENCES",meta.artifact_id,{"valid_from":"2026-10-16T14:08:14+05:30"})
    index_root=temp/"retrieval"/"northstar"
    RetrievalIndexer(client,lexical=BM25LexicalIndex(index_root/"lexical.json"),vector=LocalVectorIndex(path=index_root/"vector.json"),artifact_store=store).index_artifact(meta.artifact_id)

    # Import only after env points the app at the isolated graph.
    from fastapi.testclient import TestClient
    from backend.app.main import app
    api=TestClient(app)
    headers={"Authorization":"Bearer test-admin-token","X-Tenant-ID":"northstar"}
    read_headers={"Authorization":"Bearer test-reader-token","X-Tenant-ID":"northstar"}
    checks=[]
    report_path=ROOT/f"phase11_api_acceptance_{graph_name}.json"
    http_path=ROOT/f"phase11_api_examples_{graph_name}.http"
    cypher_path=ROOT/f"phase11_browser_queries_{graph_name}.cypher"
    print(f"Isolated FalkorDB graph: {graph_name}\nNOTE: company_brain is not modified and this graph is kept by default.")
    try:
        check(api.get("/health").status_code==200,"health",checks)
        check(api.get("/api/v1/ready").status_code==200,"readiness",checks)
        check(api.get("/api/v1/capabilities").json().get("external_api") is True,"capabilities",checks)
        check(api.get("/api/v1/entities/INC-001",headers=read_headers).status_code==200,"authenticate and read canonical entity",checks)
        situations=api.get("/api/v1/situations",headers=read_headers);check(situations.status_code==200 and any(x["id"]=="INC-001" for x in situations.json()["items"]),"list/get INC-001",checks)

        inv=api.post("/api/v1/investigations",headers={**headers,"Idempotency-Key":"phase11-accept-investigation"},json={"situation_id":"INC-001","question":"Why did Checkout fail during DPL-882?","seed_entity_ids":["INC-001"]})
        check(inv.status_code==201,"create investigation",checks);iid=inv.json()["id"]
        ret=api.post(f"/api/v1/investigations/{iid}/retrieve",headers=read_headers,json={"query":"region_scope cannot be null","retrieval_modes":["LEXICAL"],"max_results":5,"max_graph_hops":4})
        check(ret.status_code==200 and ret.json().get("graph_required") is True and ret.json().get("evidence_ids"),"graph-first retrieval",checks)
        evidence_id=ret.json()["evidence_ids"][0]
        check(api.get(f"/api/v1/evidence/{evidence_id}",headers=read_headers).status_code==200,"inspect returned Evidence",checks)
        check(api.get("/api/v1/entities/SYS-PRICING-API",headers=read_headers).status_code==200,"inspect canonical entity",checks)
        path=api.get("/api/v1/paths",headers=read_headers,params={"from":"INC-001","to":"SYS-PRICING-DB","max_hops":6});check(path.status_code==200 and path.json()["paths"],"find graph path",checks)
        blast=api.get("/api/v1/entities/SYS-PRICING-DB/blast-radius",headers=read_headers);check(blast.status_code==200 and blast.json().get("graph_required") is True,"blast radius",checks)
        check(api.get("/api/v1/claims/C-001/conflicts",headers=read_headers).status_code==200,"inspect conflicting Claims",checks)
        check(api.get(f"/api/v1/evidence/{evidence_id}/provenance",headers=read_headers).status_code==200,"inspect Evidence provenance",checks)

        plan=api.post("/api/v1/plans",headers={**headers,"Idempotency-Key":"phase11-accept-plan"},json={"situation_id":"INC-001","goal":"Resolve INC-001 safely"})
        check(plan.status_code==201,"create Phase 5 plan",checks)
        plan_id=plan.json()["plan"]["id"]
        check(api.get(f"/api/v1/plans/{plan_id}/tasks",headers=read_headers).status_code==200,"inspect plan tasks",checks)

        # Deterministic task/action acceptance path independent of whatever plan tasks are currently ready.
        task_id="TASK-P11-ACCEPT-ACTION";upsert_node(client,"Task",task_id,{"name":"Phase11 acceptance remediation","title":"Phase11 acceptance remediation","task_type":"PREPARE_ACTION","objective":"sandbox rollback","status":"OPEN","priority":"P1","created_at":now_iso(),"expected_output_type":"ACTION_PROPOSAL","completion_condition":"sandbox action succeeds"})
        claim=api.post(f"/api/v1/tasks/{task_id}/claim",headers=headers,json={"agent_id":"AGENT-P6-REMEDIATION"});check(claim.status_code==200,"claim Task",checks)
        check(api.post(f"/api/v1/tasks/{task_id}/start",headers=headers,json={"agent_id":"AGENT-P6-REMEDIATION"}).status_code==200,"start Task",checks)
        check(api.get("/api/v1/agents/AGENT-P6-REMEDIATION",headers=read_headers).status_code==200,"inspect Agent",checks)
        check(api.get("/api/v1/decisions/DEC-INC001-ROLLBACK/genealogy",headers=read_headers).status_code==200,"inspect Decision genealogy",checks)
        action=api.post("/api/v1/actions",headers={**headers,"Idempotency-Key":"phase11-accept-action"},json={"task_id":task_id,"agent_id":"AGENT-P6-REMEDIATION","name":"Acceptance sandbox rollback","action_type":"rollback","target_ids":["SYS-PRICING-DB"],"approval_required":False})
        check(action.status_code==201,"propose governed sandbox Action",checks);action_id=action.json()["action"]["id"]
        execute_headers={**headers,"Idempotency-Key":"phase11-accept-execute"};ex1=api.post(f"/api/v1/actions/{action_id}/execute",headers=execute_headers,json={"agent_id":"AGENT-P6-REMEDIATION"});ex2=api.post(f"/api/v1/actions/{action_id}/execute",headers=execute_headers,json={"agent_id":"AGENT-P6-REMEDIATION"})
        check(ex1.status_code==200 and ex2.status_code==200,"execute Action",checks)
        check(ex1.json()==ex2.json() and len(api.get(f"/api/v1/actions/{action_id}/attempts",headers=read_headers).json()["items"])==1,"repeat Action proves exactly-once",checks)

        before=len(GraphSnapshot.load(client).nodes);sim=api.post("/api/v1/simulations/counterfactual",headers=read_headers,json={"situation_id":"SYS-PRICING-DB","interventions":[{"type":"REMOVE_DEPENDENCY","source":"SYS-CHECKOUT","target":"SYS-PRICING-API"}]});after=len(GraphSnapshot.load(client).nodes)
        check(sim.status_code==200,"counterfactual simulation",checks);check(before==after,"simulation did not mutate canonical graph",checks)
        check(api.get("/api/v1/history/entities/SYS-PRICING-API/at",headers=read_headers,params={"as_of":"2026-10-16T14:09:00+05:30"}).status_code==200,"historical ownership/state query",checks)
        process=api.get("/api/v1/processes/INC-001",headers=read_headers);check(process.status_code==200,"reconstruct INC-001 process",checks)
        check("temporal_edges" in process.json() and "causal_edges" in process.json(),"BEFORE remains distinct from CAUSE",checks)
        check(api.get("/api/v1/processes/INC-001/policy-drift",headers=read_headers,params={"policy_id":"POL-DB-04"}).status_code==200,"policy drift",checks)
        check(api.get("/api/v1/risks/bus-factor",headers=read_headers).status_code==200,"bus-factor risk",checks)
        check(api.get("/api/v1/risks/bottlenecks",headers=read_headers).status_code==200,"bottlenecks",checks)
        check(api.get("/api/v1/risks/bridges",headers=read_headers).status_code==200,"bridges",checks)
        check(api.get("/api/v1/risks/initiative-collisions",headers=read_headers).status_code==200,"initiative collisions",checks)
        check(api.get("/api/v1/risks/ownership-gaps",headers=read_headers).status_code==200,"ownership gaps",checks)
        page=api.get("/api/v1/claims",headers=read_headers,params={"limit":1});check(page.status_code==200 and len(page.json()["items"])==1,"pagination",checks)
        check(api.get("/api/v1/entities/INC-001").status_code==401,"unauthorized request",checks)
        check(api.get("/api/v1/entities/INC-001",headers={"Authorization":"Bearer test-reader-token","X-Tenant-ID":"other-tenant"}).status_code==403,"cross-tenant header isolation",checks)
        check(api.get("/api/v1/entities/NO-SUCH-ID",headers=read_headers).status_code==404,"invalid ID",checks)
        rid=api.get("/api/v1/entities/INC-001",headers={**read_headers,"X-Request-ID":"phase11-accept-request"});check(rid.headers.get("X-Request-ID")=="phase11-accept-request","request ID propagation",checks)

        report={"graph":graph_name,"company_brain_modified":False,"passed":all(x["passed"] for x in checks),"passed_count":sum(x["passed"] for x in checks),"failed_count":sum(not x["passed"] for x in checks),"checks":checks,"investigation_id":iid,"retrieval_execution_id":ret.json().get("execution_id"),"evidence_ids":ret.json().get("evidence_ids"),"action_id":action_id}
        report_path.write_text(json.dumps(report,indent=2),encoding="utf-8")
        http_path.write_text(f'''@base = http://127.0.0.1:8000\n@token = test-admin-token\n@tenant = northstar\n\n### Situation\nGET {{{{base}}}}/api/v1/situations/INC-001\nAuthorization: Bearer {{{{token}}}}\nX-Tenant-ID: {{{{tenant}}}}\n\n### Create investigation\nPOST {{{{base}}}}/api/v1/investigations\nAuthorization: Bearer {{{{token}}}}\nX-Tenant-ID: {{{{tenant}}}}\nContent-Type: application/json\nIdempotency-Key: demo-investigation-1\n\n{{"situation_id":"INC-001","question":"Why did Checkout fail during DPL-882?","seed_entity_ids":["INC-001"]}}\n\n### Blast radius\nGET {{{{base}}}}/api/v1/entities/SYS-PRICING-DB/blast-radius\nAuthorization: Bearer {{{{token}}}}\nX-Tenant-ID: {{{{tenant}}}}\n\n### Process\nGET {{{{base}}}}/api/v1/processes/INC-001\nAuthorization: Bearer {{{{token}}}}\nX-Tenant-ID: {{{{tenant}}}}\n''',encoding="utf-8")
        cypher_path.write_text(f'''// Phase 11 isolated graph: {graph_name}\nMATCH (i:Investigation {{tenant_id:'northstar'}}) RETURN i ORDER BY i.created_at DESC;\nMATCH (i:Investigation {{tenant_id:'northstar'}})-[:HAS_RETRIEVAL]->(r:RetrievalExecution)-[:RETURNED]->(e:Evidence) RETURN i.id,r.id,e.id;\nMATCH (e:Evidence {{tenant_id:'northstar'}})-[:DERIVED_FROM]->(x) RETURN e.id,labels(x),x.id;\nMATCH (p:Plan {{tenant_id:'northstar'}})-[:PLAN_HAS_TASK]->(t:Task) RETURN p.id,t.id,t.status,t.task_type;\nMATCH (t:Task {{tenant_id:'northstar'}})-[:CLAIMED_BY]->(a:Agent) RETURN t.id,a.id;\nMATCH (a:Action {{tenant_id:'northstar'}})-[:HAS_ATTEMPT]->(x:ActionAttempt) RETURN a.id,a.status,x.id,x.execution_state;\nMATCH (d:Decision {{tenant_id:'northstar',id:'DEC-INC001-ROLLBACK'}})-[r]->(x) RETURN d.id,type(r),x.id;\n''',encoding="utf-8")
        print(f"\nPHASE 11 API ACCEPTANCE\nRESULT: {len(checks)} passed, 0 failed\nReport: {report_path}\nHTTP examples: {http_path}\nBrowser queries: {cypher_path}")
        return 0
    except Exception as exc:
        report_path.write_text(json.dumps({"graph":graph_name,"company_brain_modified":False,"passed":False,"checks":checks,"error":f"{type(exc).__name__}: {exc}"},indent=2),encoding="utf-8")
        print(f"\nPHASE 11 API ACCEPTANCE: FAIL\n{type(exc).__name__}: {exc}\nGraph kept for inspection: {graph_name}")
        return 1

if __name__=="__main__":raise SystemExit(main())
