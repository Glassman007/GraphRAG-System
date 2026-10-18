from __future__ import annotations
import json,os,shutil,socket,subprocess,sys,tempfile,time,urllib.request,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.schema import apply_schema
from backend.app.graph.mutations import upsert_node,upsert_relationship
from backend.app.services.phase6_utils import stable_id,now_iso

def wait_url(url:str,timeout:float=30):
    start=time.time();last=None
    while time.time()-start<timeout:
        try:
            with urllib.request.urlopen(url,timeout=2) as r:
                if r.status<500:return
        except Exception as exc:last=exc
        time.sleep(.5)
    raise RuntimeError(f"Timed out waiting for {url}: {last}")


def resolve_node_tool(name: str) -> str:
    """Resolve npm/npx portably; Windows exposes them as .cmd launchers."""
    candidates = [f"{name}.cmd", name] if os.name == "nt" else [name]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise RuntimeError(
        f"{name} was not found on PATH. Install Node.js/npm and verify "
        f"`{name} --version` works in this shell."
    )


NPM = resolve_node_tool("npm")
NPX = resolve_node_tool("npx")

def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main()->int:
    graph=f"phase13_accept_{uuid.uuid4().hex[:10]}";temp=Path(tempfile.mkdtemp(prefix="graphhacks-phase13-"));frontend=ROOT/"frontend"
    backend_port=free_port();frontend_port=free_port();backend_url=f"http://127.0.0.1:{backend_port}";frontend_url=f"http://127.0.0.1:{frontend_port}"
    env=os.environ.copy();env.update({"FALKORDB_GRAPH":graph,"GRAPH_TENANT_ID":"northstar","GRAPH_HACKS_ARTIFACT_ROOT":str(temp/"artifacts"),"GRAPH_HACKS_RETRIEVAL_ROOT":str(temp/"retrieval"),"GRAPH_HACKS_CREDENTIAL_ROOT":str(temp/"credentials"),"VITE_API_BASE_URL":"","VITE_TEST_TOKEN":"test-admin-token","VITE_TENANT_ID":"northstar","VITE_DEV_PORT":str(frontend_port),"VITE_PROXY_TARGET":backend_url,"PHASE13_BASE_URL":frontend_url})
    os.environ.update({k:v for k,v in env.items() if k.startswith(("FALKORDB_","GRAPH_"))})
    try:
        client=FalkorGraphClient(Settings.from_env());client.delete_graph();apply_schema(client)
        # Deterministic identity-review fixture. It is unresolved on purpose; the UI resolves it through the real Phase 4 service.
        source_id=stable_id("SRC-","northstar","github","Northstar Engineering GitHub",length=18)
        at=now_iso();upsert_node(client,"Person","PERSON-P13-CAND",{"name":"Neha Verma","email":"neha@northstar.example","status":"ACTIVE","created_at":at})
        upsert_node(client,"SourceRecord","SR-P13-AMB",{"name":"GitHub identity: Neha","source_id":source_id,"source_entity_id":"neha-verma","record_type":"user","status":"ACTIVE","created_at":at})
        upsert_node(client,"SourceRecord","SRCID-P13-AMB",{"name":"Neha Verma","source_id":source_id,"record_type":"identity_projection","candidate_label":"Person","status":"ACTIVE","created_at":at})
        upsert_relationship(client,"SR-P13-AMB","REFERENCES","SRCID-P13-AMB",{"valid_from":at})
        upsert_node(client,"IngestionQuarantineRecord","QUAR-P13-AMB",{"name":"Neha Verma","source_record_id":"SR-P13-AMB","source_ref_id":source_id,"entity_key":"subject","candidate_label":"Person","status":"OPEN","reason":"AMBIGUOUS_IDENTITY","proposed_entity":json.dumps({"ontology_type":"Person","properties":{"name":"Neha Verma"}}),"candidates":json.dumps([{"entity_id":"PERSON-P13-CAND","confidence":.87,"factors":{"name_similarity":1.0,"repository_reference":.9}}]),"created_at":at})
    except Exception as exc:
        print(f"PHASE 13 UI ACCEPTANCE: CANNOT RUN\n{type(exc).__name__}: {exc}");return 2
    if not (frontend/"node_modules").exists():
        print("PHASE 13 UI ACCEPTANCE: CANNOT RUN\nfrontend/node_modules is missing. Run: cd frontend && npm install && npx playwright install chromium");return 2
    backend_proc=frontend_proc=None;report=ROOT/f"phase13_acceptance_report_{graph}.json";cypher=ROOT/f"phase13_browser_queries_{graph}.cypher"
    try:
        backend_proc=subprocess.Popen([sys.executable,"-m","uvicorn","backend.app.main:app","--host","127.0.0.1","--port",str(backend_port)],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,text=True)
        frontend_proc=subprocess.Popen([NPM,"run","dev"],cwd=frontend,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,text=True)
        wait_url(f"{backend_url}/health");wait_url(f"{frontend_url}/")
        run=subprocess.run([NPX,"playwright","test","e2e/phase13.spec.ts"],cwd=frontend,env=env,capture_output=True,text=True)
        result={"graph":graph,"returncode":run.returncode,"stdout":run.stdout,"stderr":run.stderr,"company_brain_modified":False,"credential_root":str(temp/"credentials")};report.write_text(json.dumps(result,indent=2),encoding="utf-8")
        cypher.write_text("""// Phase 13 isolated acceptance inspection\nMATCH (s:Entity:DataSource) RETURN s;\nMATCH (run:Entity:IngestionRun)-[:INGESTED]->(r:Entity:SourceRecord) RETURN run,r LIMIT 100;\nMATCH (r:Entity:SourceRecord)-[:NORMALIZED_TO]->(n:Entity) RETURN r,n LIMIT 100;\nMATCH (q:Entity:IngestionQuarantineRecord) RETURN q;\nMATCH (e:Entity {id:'SYS-PRICING-API'})<-[r:NORMALIZED_TO]-(sr:Entity:SourceRecord) RETURN sr,r,e;\n""",encoding="utf-8")
        print(run.stdout);print(f"Isolated graph: {graph}\nReport: {report.name}\nQueries: {cypher.name}\ncompany_brain was not modified.");return run.returncode
    finally:
        for proc in (frontend_proc,backend_proc):
            if proc and proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill()
if __name__=="__main__":raise SystemExit(main())
