from __future__ import annotations

from pathlib import Path
from typing import Iterable

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot,has_label
from backend.app.ingestion.artifacts.local import LocalArtifactStore
from backend.app.retrieval.chunking import DocumentChunker
from backend.app.retrieval.lexical import BM25LexicalIndex
from backend.app.retrieval.vector import LocalVectorIndex
from backend.app.retrieval.models import IndexedDocument
from backend.app.retrieval.utils import content_hash
from backend.app.graph.mutations import upsert_node,upsert_relationship
from backend.app.services.phase6_utils import now_iso, stable_id
from backend.app.services.event_ledger_service import EventLedgerService


class RetrievalIndexer:
    def __init__(self,client:FalkorGraphClient,*,lexical:BM25LexicalIndex,vector:LocalVectorIndex,artifact_store:LocalArtifactStore|None=None,chunker:DocumentChunker|None=None):
        self.client=client;self.lexical=lexical;self.vector=vector;self.artifact_store=artifact_store;self.chunker=chunker or DocumentChunker();self.events=EventLedgerService(client)
    @staticmethod
    def _superseded_at(snapshot:GraphSnapshot,source_record_id:str)->str|None:
        times=[]
        for edge in snapshot.edges_to(source_record_id,{"SUPERSEDES"}):
            newer=snapshot.node(edge.source) or {}
            value=newer.get("source_updated_at") or newer.get("observed_at") or edge.properties.get("valid_from")
            if value:times.append(str(value))
        if not times:return None
        from backend.app.graph.temporal import to_epoch_us
        return min(times,key=to_epoch_us)

    def index_document(self,doc:IndexedDocument)->None:
        self.lexical.index_document(doc);self.vector.index_document(doc)

    def index_source_record(self, source_record_id: str) -> bool:
        snapshot=GraphSnapshot.load(self.client);node=snapshot.node(source_record_id)
        if not node or not has_label(node,"SourceRecord"): return False
        superseded=[e.target for e in snapshot.edges_from(source_record_id,{"SUPERSEDES"})]
        boundary=node.get("observed_at") or node.get("source_updated_at") or node.get("fetched_at")
        # Close every derived retrieval representation whose provenance is the old
        # SourceRecord, not just the SourceRecord document itself. This prevents a
        # tombstoned/update-superseded record from leaving current Artifact chunks
        # searchable while preserving them for historical as_of retrieval.
        for old_id in superseded:
            for index in (self.lexical,self.vector):
                for doc_id,old in list(index.documents.items()):
                    if old.document_id != old_id and old.source_record_id != old_id:
                        continue
                    if old.valid_until is None:
                        index.index_document(old.model_copy(update={"valid_until":boundary}))
        if bool(node.get("deleted")) or str(node.get("status") or "").upper()=="TOMBSTONED": return False
        text=str(node.get("raw_metadata") or node.get("content") or node.get("text") or node.get("summary") or "")
        if not text: return False
        dsids=[e.target for e in snapshot.edges_from(source_record_id,{"DERIVED_FROM"}) if has_label(snapshot.node(e.target),"DataSource")]
        entity_ids=[e.target for e in snapshot.edges_from(source_record_id,{"NORMALIZED_TO"})]
        doc=IndexedDocument(document_id=source_record_id,text=text,tenant_id=self.client.settings.tenant_id,source_record_id=source_record_id,data_source_id=dsids[0] if dsids else node.get("source_id"),entity_ids=entity_ids,document_type="SOURCE_RECORD",observed_at=node.get("observed_at"),valid_from=node.get("observed_at"),valid_until=self._superseded_at(snapshot,source_record_id),content_hash=str(node.get("checksum") or content_hash(text)),metadata={"record_type":node.get("record_type"),"source_kind":node.get("source_kind")})
        self.index_document(doc);return True

    def index_artifact(self,artifact_id:str)->list[str]:
        snapshot=GraphSnapshot.load(self.client);node=snapshot.node(artifact_id)
        if not node or not has_label(node,"Artifact"):return []
        text=""
        if self.artifact_store and self.artifact_store.exists(artifact_id):
            text=self.artifact_store.get(artifact_id).decode("utf-8",errors="replace")
        if not text:text=str(node.get("text") or node.get("content") or "")
        if not text:return []
        srids=[e.source for e in snapshot.edges_to(artifact_id,{"REFERENCES"}) if has_label(snapshot.node(e.source),"SourceRecord")]
        source_record_id=srids[0] if srids else node.get("source_record_id")
        dsids=[]
        source_record={}
        if source_record_id:
            source_record=snapshot.node(str(source_record_id)) or {}
            dsids=[e.target for e in snapshot.edges_from(str(source_record_id),{"DERIVED_FROM"}) if has_label(snapshot.node(e.target),"DataSource")]
        entity_ids=set()
        if source_record_id:
            for e in snapshot.edges_from(str(source_record_id),{"NORMALIZED_TO"}):entity_ids.add(e.target)
        chunks=self.chunker.chunk(document_id=artifact_id,text=text,tenant_id=self.client.settings.tenant_id,artifact_id=artifact_id,source_record_id=str(source_record_id) if source_record_id else None,data_source_id=dsids[0] if dsids else None,entity_ids=sorted(entity_ids),document_type=str(node.get("artifact_type") or "DOCUMENT"),observed_at=source_record.get("observed_at") or node.get("observed_at"),metadata={"artifact_uri":node.get("uri")})
        superseded_at=self._superseded_at(snapshot,str(source_record_id)) if source_record_id else None
        at=now_iso()
        for chunk in chunks:
            if superseded_at:
                chunk=chunk.model_copy(update={"valid_until":superseded_at})
            self.index_document(chunk)
            upsert_node(self.client,"Chunk",chunk.document_id,{"artifact_id":artifact_id,"source_record_id":chunk.source_record_id,"sequence":chunk.metadata.get("sequence"),"heading":chunk.metadata.get("heading"),"char_start":chunk.metadata.get("char_start"),"char_end":chunk.metadata.get("char_end"),"content_hash":chunk.content_hash,"chunking_version":chunk.metadata.get("chunking_version"),"observed_at":chunk.observed_at,"valid_from":chunk.valid_from or chunk.observed_at,"valid_until":chunk.valid_until,"created_at":at})
            upsert_relationship(self.client,chunk.document_id,"PART_OF",artifact_id,{"valid_from":at})
        if chunks:
            self.events.record("DOCUMENT_INDEXED",about_ids=[artifact_id]+[c.document_id for c in chunks[:20]],summary=f"Indexed artifact {artifact_id} into {len(chunks)} retrieval chunks",occurred_at=at,event_id=stable_id("EVT-P10-","DOCUMENT_INDEXED",artifact_id,str(node.get("sha256") or ""),self.chunker.config.version),properties={"phase":"10","chunking_version":self.chunker.config.version,"embedding_model":self.vector.provider.model_id,"lexical_index_version":"phase10-bm25-v1"})
        return [c.document_id for c in chunks]
    def rebuild(self)->dict:
        # Derived indexes are rebuilt from canonical FalkorDB references + ArtifactStore,
        # so stale entries that no longer have graph provenance cannot survive rebuild.
        self.lexical.clear();self.vector.clear()
        snapshot=GraphSnapshot.load(self.client);count=0;chunks=0
        for node in snapshot.nodes.values():
            if has_label(node,"Artifact"):
                ids=self.index_artifact(str(node["id"]));count+=1 if ids else 0;chunks+=len(ids)
            elif has_label(node,"SourceRecord"):
                if self.index_source_record(str(node["id"])): count+=1
        return {"documents_indexed":count,"chunks_indexed":chunks,"lexical":self.lexical.health_check(),"vector":self.vector.health_check()}
