from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from backend.app.ingestion.artifacts.local import LocalArtifactStore
from backend.app.retrieval.models import GraphScope, RetrievalMode, RetrievalRequest, RetrievalResult
from backend.app.retrieval.utils import stable_hash
from backend.app.services.phase4_graph import GraphSnapshot
from backend.app.services.phase6_utils import now_iso


class DocumentRetriever:
    def __init__(self, snapshot: GraphSnapshot, artifact_store: LocalArtifactStore | None = None):
        self.snapshot=snapshot;self.artifact_store=artifact_store
    def retrieve(self,request:RetrievalRequest,scope:GraphScope)->list[RetrievalResult]:
        out=[]
        for aid in scope.artifacts:
            node=self.snapshot.node(aid) or {};text=""
            if self.artifact_store and self.artifact_store.exists(aid):
                try:text=self.artifact_store.get(aid).decode("utf-8",errors="replace")
                except Exception:text=""
            if not text:
                text=str(node.get("text") or node.get("content") or node.get("snippet") or "")
            if not text:continue
            source_record_id=node.get("source_record_id")
            if not source_record_id:
                refs=[e.source for e in self.snapshot.edges_to(aid,{"REFERENCES"},as_of=request.as_of) if "SourceRecord" in set((self.snapshot.node(e.source) or {}).get("_labels") or [])]
                source_record_id=refs[0] if refs else None
            source_record=self.snapshot.node(str(source_record_id)) if source_record_id else None
            source_id=node.get("source_id") or (source_record or {}).get("source_id")
            if not source_id and source_record_id:
                ds=[e.target for e in self.snapshot.edges_from(str(source_record_id),{"DERIVED_FROM"},as_of=request.as_of) if "DataSource" in set((self.snapshot.node(e.target) or {}).get("_labels") or [])]
                source_id=ds[0] if ds else None
            matched=[e.target for e in self.snapshot.edges_from(str(source_record_id),{"NORMALIZED_TO"},as_of=request.as_of)] if source_record_id else []
            out.append(RetrievalResult(result_id=stable_hash("document",request.query,aid,request.as_of,prefix="RRET"),retrieval_method=RetrievalMode.DOCUMENT,score=1.0,source_id=source_id,source_record_id=str(source_record_id) if source_record_id else None,artifact_id=aid,document_id=aid,text=text[:4000],metadata={"mime_type":node.get("mime_type"),"uri":node.get("uri")},observed_at=(source_record or {}).get("observed_at") or node.get("observed_at"),retrieved_at=now_iso(),provenance={"artifact_id":aid,"sha256":node.get("sha256"),"source_record_id":source_record_id,"data_source_id":source_id},graph_scope=list(scope.entities),matched_entity_ids=matched,query=request.query,rank=len(out)+1,explanation="Direct document lookup because FalkorDB graph scope identified the Artifact"))
            if len(out)>=request.max_results:break
        return out


class MetadataRetriever:
    def __init__(self,snapshot:GraphSnapshot):self.snapshot=snapshot
    def retrieve(self,request:RetrievalRequest,scope:GraphScope)->list[RetrievalResult]:
        out=[]
        for eid in scope.retrieval_candidates:
            node=self.snapshot.node(eid["entity_id"]) or {}
            text="; ".join(f"{k}={v}" for k,v in sorted(node.items()) if not k.startswith("_") and k not in {"tenant_id"})
            if not text:continue
            out.append(RetrievalResult(result_id=stable_hash("metadata",request.query,eid["entity_id"],request.as_of,prefix="RRET"),retrieval_method=RetrievalMode.METADATA,score=1.0/(1+int(eid.get("graph_distance") or 0)),source_id=node.get("source_id"),source_record_id=eid["entity_id"] if "SourceRecord" in (node.get("_labels") or []) else None,artifact_id=eid["entity_id"] if "Artifact" in (node.get("_labels") or []) else None,document_id=None,text=text[:4000],metadata={"entity_id":eid["entity_id"]},observed_at=node.get("observed_at"),retrieved_at=now_iso(),provenance={"graph_entity_id":eid["entity_id"]},graph_scope=list(scope.entities),matched_entity_ids=[eid["entity_id"]],query=request.query,rank=len(out)+1,explanation="Structured metadata from a graph-scoped retrieval candidate"))
            if len(out)>=request.max_results:break
        return out
