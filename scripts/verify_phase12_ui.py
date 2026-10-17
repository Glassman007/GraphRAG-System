from __future__ import annotations

import json
import os
import socket
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
from backend.app.services.phase6_utils import now_iso
from scripts.seed_lib import seed_all


def wait_url(url: str, timeout: float = 30.0) -> None:
    start=time.time()
    last=None
    while time.time()-start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status < 500:return
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


def main() -> int:
    graph=f"phase12_accept_{uuid.uuid4().hex[:10]}"
    temp=Path(tempfile.mkdtemp(prefix="graphhacks-phase12-"))
    backend_port=free_port()
    frontend_port=free_port()
    backend_url=f"http://127.0.0.1:{backend_port}"
    frontend_url=f"http://127.0.0.1:{frontend_port}"
    env=os.environ.copy()
    env.update({
        "FALKORDB_GRAPH":graph,
        "GRAPH_TENANT_ID":"northstar",
        "GRAPH_HACKS_ARTIFACT_ROOT":str(temp/"artifacts"),
        "GRAPH_HACKS_RETRIEVAL_ROOT":str(temp/"retrieval"),
        "VITE_API_BASE_URL":"",
        "VITE_TEST_TOKEN":"test-admin-token",
        "VITE_TENANT_ID":"northstar",
        "VITE_DEV_PORT":str(frontend_port),
        "VITE_PROXY_TARGET":backend_url,
        "PHASE12_BASE_URL":frontend_url,
    })
    os.environ.update({k:v for k,v in env.items() if k.startswith(("FALKORDB_","GRAPH_"))})
    try:
        client=FalkorGraphClient(Settings.from_env());client.delete_graph();apply_schema(client);seed_all(client);AgentRegistryService(client).ensure_default_agents()
    except Exception as exc:
        print(f"PHASE 12 UI ACCEPTANCE: CANNOT RUN\n{type(exc).__name__}: {exc}")
        return 2

    # Retrieval material used by the Investigation workspace.
    store=LocalArtifactStore(temp/"artifacts")
    meta=store.put(ArtifactPayload(name="phase12-pricing.log",content="14:08:14 ERROR region_scope cannot be null after MIG-203 during mixed-version rollout",mime_type="text/plain",artifact_type=ArtifactType.LOG),tenant_id="northstar",source_type="telemetry",source_record_id="SR-P12-VERIFY")
    upsert_node(client,"DataSource","DS-P12-VERIFY",{"name":"Phase12 pricing logs","source_type":"telemetry","trust_class":"STRONG"})
    upsert_node(client,"SourceRecord","SR-P12-VERIFY",{"name":"pricing failure log","source_type":"telemetry","source_id":"DS-P12-VERIFY","observed_at":"2026-10-16T14:08:14+05:30","raw_metadata":"region_scope cannot be null"})
    upsert_node(client,"Artifact",meta.artifact_id,meta.model_dump(mode="json"))
    upsert_relationship(client,"SR-P12-VERIFY","NORMALIZED_TO","SYS-PRICING-API",{"valid_from":"2026-10-16T14:08:14+05:30"})
    upsert_relationship(client,"SR-P12-VERIFY","DERIVED_FROM","DS-P12-VERIFY",{"valid_from":"2026-10-16T14:08:14+05:30"})
    upsert_relationship(client,"SR-P12-VERIFY","REFERENCES",meta.artifact_id,{"valid_from":"2026-10-16T14:08:14+05:30"})
    idx=temp/"retrieval"/"northstar"
    RetrievalIndexer(client,lexical=BM25LexicalIndex(idx/"lexical.json"),vector=LocalVectorIndex(path=idx/"vector.json"),artifact_store=store).index_artifact(meta.artifact_id)

    # A deterministic task for Task/Agent/blackboard inspection.
    upsert_node(client,"Task","TASK-P12-ACCEPT",{"name":"Phase12 acceptance remediation","title":"Phase12 acceptance remediation","task_type":"PREPARE_ACTION","objective":"sandbox inspection","status":"OPEN","priority":"P1","created_at":now_iso(),"expected_output_type":"ACTION_PROPOSAL","completion_condition":"acceptance inspection succeeds"})

    frontend=ROOT/"frontend"
    if not (frontend/"node_modules").exists():
        print("PHASE 12 UI ACCEPTANCE: CANNOT RUN\nfrontend/node_modules is missing. Run: cd frontend && npm install && npx playwright install chromium")
        return 2
    backend_proc=frontend_proc=None
    report=ROOT/f"phase12_acceptance_report_{graph}.json"
    cypher=ROOT/f"phase12_browser_queries_{graph}.cypher"
    try:
        backend_proc=subprocess.Popen([sys.executable,"-m","uvicorn","backend.app.main:app","--host","127.0.0.1","--port",str(backend_port)],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        frontend_proc=subprocess.Popen([NPM,"run","dev"],cwd=frontend,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        wait_url(f"{backend_url}/health");wait_url(f"{frontend_url}/")
        run=subprocess.run([NPX,"playwright","test","e2e/phase12.spec.ts"],cwd=frontend,env=env,capture_output=True,text=True)
        result={"graph":graph,"returncode":run.returncode,"stdout":run.stdout,"stderr":run.stderr,"company_brain_modified":False}
        report.write_text(json.dumps(result,indent=2),encoding="utf-8")
        cypher.write_text("""// Phase 12 isolated-browser inspection queries\nMATCH (i:Entity {id:'INC-001'})-[r]-(n:Entity) RETURN i,r,n LIMIT 100;\nMATCH (inv:Entity:Investigation)-[:HAS_RETRIEVAL]->(x:Entity:RetrievalExecution)-[:RETURNED]->(e:Entity:Evidence) RETURN inv,x,e;\nMATCH (p:Entity:Plan)-[:PLAN_HAS_TASK]->(t:Entity:Task) RETURN p,t LIMIT 100;\nMATCH (c:Entity:Claim)-[:CONTRADICTS]-(other:Entity:Claim) RETURN c,other;\nMATCH (d:Entity:Decision)-[r]-(n:Entity) RETURN d,r,n LIMIT 100;\nMATCH (a:Entity:Action)-[r]-(n:Entity) RETURN a,r,n LIMIT 100;\n""",encoding="utf-8")
        print(run.stdout)
        print(f"Isolated FalkorDB graph: {graph}\nAcceptance report: {report.name}\nBrowser queries: {cypher.name}\nNOTE: company_brain was not modified.")
        return run.returncode
    finally:
        for proc in (frontend_proc,backend_proc):
            if proc and proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
