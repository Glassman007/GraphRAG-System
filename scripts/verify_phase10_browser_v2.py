from __future__ import annotations

import json, os, sys, tempfile, uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.schema import apply_schema
from backend.app.graph.mutations import upsert_node, upsert_relationship, delete_relationship
from backend.app.ingestion.artifacts.local import LocalArtifactStore
from backend.app.ingestion.models import SourceConfig, TrustClass
from backend.app.ingestion.pipeline import IngestionPipeline
from backend.app.ingestion.registry import SourceRegistry
from backend.app.retrieval.lexical import BM25LexicalIndex
from backend.app.retrieval.vector import LocalVectorIndex
from backend.app.retrieval.indexing import RetrievalIndexer
from backend.app.retrieval.models import RetrievalMode, RetrievalRequest
from backend.app.retrieval.service import RetrievalService
from backend.app.services.phase4_graph import GraphSnapshot,has_label
from scripts.seed_lib import seed_all


def check(value:bool,message:str,checks:list[dict]):
    checks.append({"check":message,"passed":bool(value)})
    if not value:raise AssertionError(message)
    print(f"[PASS] {message}")


def safe_delete_graph(client: FalkorGraphClient) -> bool:
    """Delete a graph if it exists; FalkorDB may report an empty-key error for a fresh name."""
    try:
        return client.delete_graph()
    except Exception as exc:
        text=str(exc).lower()
        if "empty key" in text or "does not exist" in text or "unknown graph" in text or "not found" in text:
            return False
        raise


def main()->int:
    graph_name=f"phase10_accept_{uuid.uuid4().hex[:10]}"
    settings=Settings(falkordb_host=os.getenv("FALKORDB_HOST","localhost"),falkordb_port=int(os.getenv("FALKORDB_PORT","6379")),falkordb_graph=graph_name,falkordb_password=os.getenv("FALKORDB_PASSWORD") or None,tenant_id=os.getenv("GRAPH_TENANT_ID","northstar"))
    try:
        client=FalkorGraphClient(settings);safe_delete_graph(client);apply_schema(client);seed_all(client)
    except Exception as exc:
        print(f"PHASE 10 ACCEPTANCE: CANNOT RUN\n{type(exc).__name__}: {exc}")
        return 2
    temp=Path(tempfile.mkdtemp(prefix="graphhacks-phase10-"));artifact_store=LocalArtifactStore(temp/"artifacts");lex=BM25LexicalIndex(temp/"lexical.json");vec=LocalVectorIndex(path=temp/"vector.json");indexer=RetrievalIndexer(client,lexical=lex,vector=vec,artifact_store=artifact_store)
    checks=[];report_path=ROOT/f"phase10_acceptance_report_{graph_name}.json";cypher_path=ROOT/f"phase10_browser_queries_{graph_name}.cypher"
    print(f"Isolated FalkorDB graph: {graph_name}\nNOTE: company_brain is not modified and this graph is kept by default.")
    try:
        fixture=temp/"telemetry.json"
        fixture.write_text(json.dumps({"records":[
            {"external_id":"p10-e003","record_type":"log_observation","observed_at":"2026-10-16T14:08:14+05:30","name":"Pricing write error","message":"region_scope cannot be null while v4.1 writer is active","system":"Pricing API","system_canonical_id":"SYS-PRICING-API","incident_canonical_id":"INC-001","incident_name":"Pricing checkout errors","artifacts":[{"name":"pricing-error.log","content":"14:08:14 ERROR region_scope cannot be null after MIG-203 during mixed rollout","mime_type":"text/plain","artifact_type":"LOG"}]},
            {"external_id":"p10-e004","record_type":"log_observation","observed_at":"2026-10-16T14:12:00+05:30","name":"Later diagnostic","message":"region_scope cannot be null follow-up after 14:12","system":"Pricing API","system_canonical_id":"SYS-PRICING-API","incident_canonical_id":"INC-001","incident_name":"Pricing checkout errors","artifacts":[{"name":"pricing-later.log","content":"14:12:00 region_scope cannot be null later diagnostic","mime_type":"text/plain","artifact_type":"LOG"}]},
            {"external_id":"p10-hist","record_type":"log_observation","observed_at":"2026-06-12T11:00:00+05:30","name":"Historical legacy writer failure","message":"old worker rejected after database constraint migration","system":"Pricing Database","system_canonical_id":"SYS-PRICING-DB","incident_canonical_id":"INC-074","incident_name":"Legacy client schema rejection","artifacts":[{"name":"inc074.log","content":"old worker rejected after database constraint migration; legacy client incompatible with new schema","mime_type":"text/plain","artifact_type":"LOG"}]}
        ]},indent=2),encoding="utf-8")
        cfg=SourceConfig(id="DS-P10-VERIFY",source_type="telemetry",name="Phase10 telemetry",source_instance="phase10-verify",trust_class=TrustClass.STRONG,authoritative_domains=["runtime observations"],fixture_path=str(fixture))
        reg=SourceRegistry(client);reg.register(cfg,persist=False)
        pipe=IngestionPipeline(client,registry=reg,artifact_store=artifact_store,retrieval_indexer=indexer)
        ing=pipe.sync(cfg.id,mode="full",max_records=20)
        check(ing.status.value=="SUCCEEDED" and ing.artifacts==3,"Phase 9 ingestion automatically feeds Phase 10 indexes",checks)

        # Also index canonical source/artifact references already present in the isolated graph.
        indexer.rebuild()
        snapshot=GraphSnapshot.load(client)
        check(any(has_label(n,"Chunk") for n in snapshot.nodes.values()),"document/artifact chunk metadata exists in FalkorDB",checks)

        service=RetrievalService(client,lexical=lex,vector=vec,artifact_store=artifact_store)
        base=dict(tenant_id=settings.tenant_id,seed_entity_ids=["INC-001"],max_graph_hops=6,max_results=10,investigation_id="INC-001")
        scope=service.graph_scope(RetrievalRequest(query="Why did Checkout fail during DPL-882?",writeback=False,**base))
        expected_scope={"INC-001","DPL-882","MIG-203","SYS-PRICING-API","SYS-PRICING-DB"}
        check("INC-001" in scope.seed_entities and expected_scope.issubset(set(scope.entities)),"graph scope includes INC-001, DPL-882, MIG-203, Pricing API and Pricing DB",checks)
        check(bool(scope.artifacts and scope.data_sources),"graph scope discovers source/artifact candidates",checks)

        exact=service.search(RetrievalRequest(query="region_scope cannot be null",retrieval_modes=[RetrievalMode.LEXICAL],writeback=False,**base))
        check(any("region_scope cannot be null" in r.text for r in exact.results),"lexical retrieval finds exact pricing error inside graph scope",checks)

        hist=service.search(RetrievalRequest(query="schema compatibility during mixed rollout",tenant_id=settings.tenant_id,seed_entity_ids=["INC-074"],max_graph_hops=6,max_results=10,retrieval_modes=[RetrievalMode.VECTOR],writeback=False))
        check(any("old worker" in r.text for r in hist.results),"vector retrieval finds paraphrased historical incident material",checks)

        hybrid=service.search(RetrievalRequest(query="Why did Checkout fail during DPL-882?",retrieval_modes=[RetrievalMode.LEXICAL,RetrievalMode.VECTOR],writeback=True,**base))
        check(bool(hybrid.execution_id and hybrid.evidence_ids),"hybrid retrieval writes graph-linked Evidence",checks)
        snap=GraphSnapshot.load(client);ev=hybrid.evidence_ids[0]
        check(has_label(snap.node(ev),"Evidence") and (snap.node(ev) or {}).get("status")=="UNVERIFIED","retrieved Evidence remains unverified organizational evidence",checks)
        check(bool(snap.edges_from(ev,{"DERIVED_FROM"})),"retrieved Evidence retains chunk/artifact/source provenance",checks)

        again=service.search(RetrievalRequest(query="Why did Checkout fail during DPL-882?",retrieval_modes=[RetrievalMode.LEXICAL,RetrievalMode.VECTOR],writeback=True,**base))
        check(again.execution_id==hybrid.execution_id and again.evidence_ids==hybrid.evidence_ids,"duplicate retrieval writeback is idempotent",checks)

        temporal=service.search(RetrievalRequest(query="region_scope cannot be null",retrieval_modes=[RetrievalMode.LEXICAL],as_of="2026-10-16T14:09:00+05:30",writeback=False,**base))
        texts="\n".join(r.text for r in temporal.results)
        check("14:08:14" in texts and "14:12:00" not in texts,"14:09 temporal retrieval includes E-003-era evidence and excludes future E-004-era evidence",checks)

        snap=GraphSnapshot.load(client)
        e003_sr=next(n for n in snap.nodes.values() if has_label(n,"SourceRecord") and n.get("source_entity_id")=="p10-e003")
        art_edge=next(e for e in snap.edges_from(str(e003_sr["id"]),{"REFERENCES"}))
        artifact_id=art_edge.target
        before=set(service.graph_scope(RetrievalRequest(query="region_scope",writeback=False,**base)).artifacts)
        # The ingested artifact is intentionally reachable by more than one provenance path
        # (SourceRecord -> Artifact and Evidence -> Artifact). Remove every graph provenance
        # edge that puts this artifact into the scoped neighborhood; otherwise deleting only
        # one redundant edge would correctly leave the artifact reachable through the other.
        provenance_types={"REFERENCES","DERIVED_FROM","HAS_ARTIFACT","DOCUMENTED_BY","PART_OF"}
        provenance_edges=[e for e in snap.edges_to(artifact_id,provenance_types)]
        removed=sum(delete_relationship(client,e.source,e.type,artifact_id) for e in provenance_edges)
        after=set(service.graph_scope(RetrievalRequest(query="region_scope",writeback=False,**base)).artifacts)
        check(removed>=1 and artifact_id in before and artifact_id not in after,"removing FalkorDB provenance paths materially changes retrieval scope",checks)
        for e in provenance_edges:
            upsert_relationship(client,e.source,e.type,artifact_id,e.properties)

        report={"graph":graph_name,"company_brain_modified":False,"checks":checks,"passed":all(x["passed"] for x in checks),"retrieval_execution":hybrid.execution_id,"evidence_ids":hybrid.evidence_ids}
        report_path.write_text(json.dumps(report,indent=2),encoding="utf-8")
        cypher_path.write_text(f'''// Phase 10 isolated graph: {graph_name}\nMATCH (r:RetrievalExecution {{tenant_id:'{settings.tenant_id}'}}) RETURN r ORDER BY r.completed_at DESC;\nMATCH (r:RetrievalExecution {{tenant_id:'{settings.tenant_id}'}})-[:RETURNED]->(e:Evidence) RETURN r.id,e.id,e.retrieval_method,e.status;\nMATCH (e:Evidence {{tenant_id:'{settings.tenant_id}'}})-[:DERIVED_FROM]->(x) RETURN e.id,labels(x),x.id;\nMATCH (c:Chunk {{tenant_id:'{settings.tenant_id}'}})-[:PART_OF]->(a:Artifact) RETURN c.id,c.heading,c.sequence,a.id,a.uri;\nMATCH (sr:SourceRecord {{tenant_id:'{settings.tenant_id}'}})-[:REFERENCES]->(a:Artifact) RETURN sr.id,sr.observed_at,a.id,a.uri ORDER BY sr.observed_at;\nMATCH p=(i:Incident {{tenant_id:'{settings.tenant_id}',id:'INC-001'}})-[*1..6]-(x) WHERE any(n IN nodes(p) WHERE n:Artifact OR n:SourceRecord OR n:DataSource) RETURN p LIMIT 50;\n''',encoding="utf-8")
        print(f"\nReport: {report_path}\nBrowser queries: {cypher_path}\nPHASE 10 ACCEPTANCE: PASS")
        return 0
    except Exception as exc:
        report_path.write_text(json.dumps({"graph":graph_name,"passed":False,"checks":checks,"error":f"{type(exc).__name__}: {exc}"},indent=2),encoding="utf-8")
        print(f"\nPHASE 10 ACCEPTANCE: FAIL\n{type(exc).__name__}: {exc}\nGraph kept for inspection: {graph_name}")
        return 1

if __name__=="__main__":raise SystemExit(main())
