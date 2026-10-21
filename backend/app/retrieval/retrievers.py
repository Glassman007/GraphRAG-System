from __future__ import annotations

from backend.app.retrieval.models import GraphScope, RetrievalMode, RetrievalRequest, RetrievalResult
from backend.app.retrieval.lexical import BM25LexicalIndex
from backend.app.retrieval.vector import LocalVectorIndex
from backend.app.retrieval.document import DocumentRetriever, MetadataRetriever
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.retrieval.utils import stable_hash
from backend.app.services.phase6_utils import now_iso
from backend.app.ingestion.registry import SourceRegistry


def _filters(scope: GraphScope):
    # The graph has already selected the exact retrieval candidates.  Keep an
    # explicit (possibly empty) document-id allowlist so an empty graph scope
    # cannot accidentally turn into an unscoped corpus search via `or None`.
    # SourceRecord documents are indexed alongside Chunk/Document records.
    candidate_ids=set(scope.chunks+scope.documents+scope.source_records)
    return {
        "allowed_document_ids": candidate_ids,
        "allowed_source_ids": set(scope.data_sources) or None,
        "allowed_artifact_ids": None,
        "allowed_entity_ids": None,
    }


class LexicalRetriever:
    retrieval_type=RetrievalMode.LEXICAL
    def __init__(self,index:BM25LexicalIndex):self.index=index
    def can_handle(self,request,scope):return bool(scope.seed_entities)
    def retrieve(self,request,scope):return self.index.search(request.query,tenant_id=request.tenant_id,limit=request.max_results,as_of=request.as_of,**_filters(scope))

class VectorRetriever:
    retrieval_type=RetrievalMode.VECTOR
    def __init__(self,index:LocalVectorIndex):self.index=index
    def can_handle(self,request,scope):return bool(scope.seed_entities)
    def retrieve(self,request,scope):return self.index.search(request.query,tenant_id=request.tenant_id,limit=request.max_results,as_of=request.as_of,**_filters(scope))

class DirectDocumentRetriever:
    retrieval_type=RetrievalMode.DOCUMENT
    def __init__(self,delegate:DocumentRetriever):self.delegate=delegate
    def can_handle(self,request,scope):return bool(scope.artifacts or scope.documents or scope.chunks)
    def retrieve(self,request,scope):return self.delegate.retrieve(request,scope)

class GraphMetadataRetriever:
    retrieval_type=RetrievalMode.METADATA
    def __init__(self,delegate:MetadataRetriever):self.delegate=delegate
    def can_handle(self,request,scope):return bool(scope.retrieval_candidates)
    def retrieve(self,request,scope):return self.delegate.retrieve(request,scope)

class ConfiguredSourceRetriever:
    """Read-only retrieval from graph-selected Phase 9 configured sources.

    Default behavior reads already-ingested SourceRecords. When callers explicitly set
    metadata_filters.refresh_external=true, the retriever invokes only the server-side
    configured Phase 9 adapter for the graph-selected DataSource. Database adapters use
    fixed read-only query templates; API adapters use configured hosts/paths. No SQL, URL
    or credentials are accepted from the retrieval request.
    """
    def __init__(self,snapshot:GraphSnapshot,mode:RetrievalMode,source_types:set[str],source_registry:SourceRegistry|None=None):
        self.snapshot=snapshot;self.retrieval_type=mode;self.source_types=source_types;self.source_registry=source_registry
    def can_handle(self,request,scope):return any(t in self.source_types for t in scope.source_types.values())

    def _existing_source_record(self,source_id:str,external_id:str)->str|None:
        candidates=[]
        for node in self.snapshot.nodes.values():
            if not has_label(node,"SourceRecord") or str(node.get("source_id") or "")!=source_id or str(node.get("source_entity_id") or "")!=external_id:
                continue
            if bool(node.get("deleted")) or str(node.get("status") or "").upper()=="TOMBSTONED":
                continue
            candidates.append(node)
        if not candidates:return None
        candidates.sort(key=lambda n:str(n.get("source_updated_at") or n.get("observed_at") or n.get("fetched_at") or ""),reverse=True)
        return str(candidates[0].get("id"))

    def _fresh(self,request,scope,allowed_ds:set[str])->list[RetrievalResult]:
        if request.as_of is not None or not self.source_registry or not bool(request.metadata_filters.get("refresh_external")):
            return []
        rows=[]
        cursor=request.metadata_filters.get("cursor")
        for source_id in sorted(allowed_ds):
            try:
                config,adapter=self.source_registry.get(source_id)
            except KeyError:
                continue
            page=adapter.fetch(cursor=str(cursor) if cursor is not None else None,limit=min(request.max_results,50))
            for record in page.records:
                text=str(record.raw_metadata)
                if not text:continue
                source_record_id=self._existing_source_record(source_id,record.external_id)
                matched=[]
                if source_record_id:
                    matched=[e.target for e in self.snapshot.edges_from(source_record_id,{"NORMALIZED_TO"},as_of=request.as_of)]
                rows.append(RetrievalResult(
                    result_id=stable_hash(self.retrieval_type.value,"external",source_id,record.external_id,record.checksum,prefix="RRET"),
                    retrieval_method=self.retrieval_type,score=1.0,source_id=source_id,source_record_id=source_record_id,
                    external_uri=record.canonical_source_uri,text=text[:4000],
                    metadata={"configured_only":True,"external_refresh":True,"record_type":record.record_type,"external_id":record.external_id,"checksum":record.checksum,"adapter_version":config.adapter_version},
                    observed_at=record.observed_at,retrieved_at=now_iso(),
                    provenance={"data_source_id":source_id,"external_id":record.external_id,"checksum":record.checksum,"adapter_version":config.adapter_version},
                    graph_scope=list(scope.entities),matched_entity_ids=matched,query=request.query,rank=len(rows)+1,
                    explanation=f"{self.retrieval_type.value} source selected by FalkorDB; fetched through server-configured read-only Phase 9 adapter"
                ))
                if len(rows)>=request.max_results:return rows
        return rows

    def retrieve(self,request,scope):
        allowed_ds={sid for sid,t in scope.source_types.items() if t in self.source_types}
        fresh=self._fresh(request,scope,allowed_ds)
        if fresh:return fresh
        out=[]
        for srid in scope.source_records:
            node=self.snapshot.node(srid) or {}
            linked={e.target for e in self.snapshot.edges_from(srid,{"DERIVED_FROM"},as_of=request.as_of)}
            if not (linked & allowed_ds):continue
            text=str(node.get("raw_metadata") or node.get("content") or node.get("summary") or node.get("name") or "")
            if not text:continue
            out.append(RetrievalResult(result_id=stable_hash(self.retrieval_type.value,request.query,srid,request.as_of,prefix="RRET"),retrieval_method=self.retrieval_type,score=1.0,source_id=next(iter(linked & allowed_ds),None),source_record_id=srid,text=text[:4000],metadata={"configured_only":True,"external_refresh":False,"record_type":node.get("record_type")},observed_at=node.get("observed_at"),retrieved_at=now_iso(),provenance={"source_record_id":srid},graph_scope=list(scope.entities),matched_entity_ids=[e.target for e in self.snapshot.edges_from(srid,{"NORMALIZED_TO"},as_of=request.as_of)],query=request.query,rank=len(out)+1,explanation=f"{self.retrieval_type.value} source selected by FalkorDB; using graph-linked Phase 9 SourceRecord snapshot"))
            if len(out)>=request.max_results:break
        return out

