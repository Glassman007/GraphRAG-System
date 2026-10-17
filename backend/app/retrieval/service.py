from __future__ import annotations

from pathlib import Path
from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot
from backend.app.retrieval.models import RetrievalMode,RetrievalRequest,RetrievalResponse,GraphScope
from backend.app.retrieval.graph_scope import GraphScopeResolver
from backend.app.retrieval.planner import RetrievalPlanner
from backend.app.retrieval.lexical import BM25LexicalIndex
from backend.app.retrieval.vector import LocalVectorIndex
from backend.app.retrieval.document import DocumentRetriever,MetadataRetriever
from backend.app.retrieval.fusion import reciprocal_rank_fusion
from backend.app.retrieval.evidence import RetrievalEvidenceService
from backend.app.ingestion.artifacts.local import LocalArtifactStore
from backend.app.retrieval.registry import RetrieverRegistry
from backend.app.retrieval.retrievers import LexicalRetriever,VectorRetriever,DirectDocumentRetriever,GraphMetadataRetriever,ConfiguredSourceRetriever
from backend.app.retrieval.rerank import deterministic_rerank
from backend.app.ingestion.registry import SourceRegistry, build_default_registry


class RetrievalService:
    def __init__(self,client:FalkorGraphClient,*,lexical:BM25LexicalIndex|None=None,vector:LocalVectorIndex|None=None,artifact_store:LocalArtifactStore|None=None,source_registry:SourceRegistry|None=None):
        self.client=client
        root=Path(".graphhacks_retrieval")/client.settings.tenant_id
        self.lexical=lexical or BM25LexicalIndex(root/"lexical.json")
        self.vector=vector or LocalVectorIndex(path=root/"vector.json")
        self.artifact_store=artifact_store
        self.source_registry=source_registry or build_default_registry(client,persist=False)
        self.planner=RetrievalPlanner()
    def graph_scope(self,request:RetrievalRequest)->GraphScope:return GraphScopeResolver(self.client).resolve(request)
    def _registry(self,snapshot:GraphSnapshot)->RetrieverRegistry:
        registry=RetrieverRegistry()
        registry.register(LexicalRetriever(self.lexical))
        registry.register(VectorRetriever(self.vector))
        registry.register(DirectDocumentRetriever(DocumentRetriever(snapshot,self.artifact_store)))
        registry.register(GraphMetadataRetriever(MetadataRetriever(snapshot)))
        registry.register(ConfiguredSourceRetriever(snapshot,RetrievalMode.SQL,{"database"},self.source_registry))
        registry.register(ConfiguredSourceRetriever(snapshot,RetrievalMode.API,{"internal_api"},self.source_registry))
        return registry
    def search(self,request:RetrievalRequest)->RetrievalResponse:
        scope=self.graph_scope(request)
        if not scope.seed_entities:
            return RetrievalResponse(graph_scope=scope,retrievers_used=[],results=[],graph_required=True)
        plan=self.planner.plan(request,scope);snapshot=GraphSnapshot.load(self.client);registry=self._registry(snapshot)
        groups,used=registry.execute(plan.modes,request,scope)
        # Replace generic registry reasons with planner explanations.
        for item in used:item["reason"]=plan.reasons.get(item["retriever"],item["reason"])
        results=reciprocal_rank_fusion(groups,limit=request.max_results) if len(groups)>1 else (groups[0][:request.max_results] if groups else [])
        results=deterministic_rerank(results,scope,snapshot)
        execution_id=None;evidence_ids=[]
        if request.writeback and results:
            execution_id,evidence_ids=RetrievalEvidenceService(self.client).persist(request,scope,plan,results)
        return RetrievalResponse(graph_scope=scope,retrievers_used=used,results=results,evidence_ids=evidence_ids,execution_id=execution_id,graph_required=True)
