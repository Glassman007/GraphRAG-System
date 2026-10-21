from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from backend.app.retrieval.models import IndexedDocument, RetrievalMode, RetrievalResult
from backend.app.retrieval.utils import cosine, tokenize, temporal_visible, stable_hash
from backend.app.services.phase6_utils import now_iso


class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int
    def embed(self, text: str) -> list[float]: ...


class HashingEmbeddingProvider:
    """Dependency-free deterministic local embedding for tests/offline operation.

    It uses normalized semantic concepts + feature hashing. Production providers can
    implement the same interface without changing graph-first retrieval semantics.
    """
    model_id = "phase10-hash-semantic-v1"
    def __init__(self, dimensions: int = 128):
        if dimensions < 32: raise ValueError("dimensions must be >= 32")
        self.dimensions=dimensions
    def embed(self,text:str)->list[float]:
        vec=[0.0]*self.dimensions
        toks=tokenize(text)
        features=list(toks)+[f"{a}::{b}" for a,b in zip(toks,toks[1:])]
        for token in features:
            digest=hashlib.sha256(token.encode()).digest()
            idx=int.from_bytes(digest[:4],"big")%self.dimensions
            sign=1.0 if digest[4]%2==0 else -1.0
            vec[idx]+=sign
        return vec


class VectorIndex:
    def index_document(self, document: IndexedDocument) -> None: raise NotImplementedError
    def search(self, query: str, **kwargs) -> list[RetrievalResult]: raise NotImplementedError


class LocalVectorIndex(VectorIndex):
    def __init__(self, provider: EmbeddingProvider | None = None, path: str | Path | None = None):
        self.provider=provider or HashingEmbeddingProvider()
        self.path=Path(path) if path else None
        self.documents: dict[str,IndexedDocument]={}
        self.vectors: dict[str,list[float]]={}
        if self.path and self.path.exists():
            payload=json.loads(self.path.read_text(encoding="utf-8"))
            for item in payload.values():
                if item.get("model_id") != self.provider.model_id or len(item.get("vector", [])) != self.provider.dimensions:
                    raise ValueError("Persisted vector index embedding model or dimensions do not match provider")
            self.documents={k:IndexedDocument.model_validate(v["document"]) for k,v in payload.items()}
            self.vectors={k:list(v["vector"]) for k,v in payload.items()}
    def _persist(self):
        if not self.path:return
        self.path.parent.mkdir(parents=True,exist_ok=True)
        payload={k:{"document":self.documents[k].model_dump(mode="json"),"vector":v,"model_id":self.provider.model_id} for k,v in self.vectors.items()}
        self.path.write_text(json.dumps(payload,indent=2,sort_keys=True),encoding="utf-8")
    def index_document(self,document:IndexedDocument)->None:
        prior=self.documents.get(document.document_id)
        has_vector=document.document_id in self.vectors
        if prior is not None and has_vector and prior.model_dump(mode="json")==document.model_dump(mode="json"):
            return
        same_body=prior is not None and has_vector and prior.content_hash==document.content_hash
        self.documents[document.document_id]=document
        # A metadata-only update (valid_until/provenance/etc.) must be persisted
        # without paying for a redundant embedding computation.
        if not same_body:
            vector=self.provider.embed(document.text)
            if len(vector)!=self.provider.dimensions:
                raise ValueError("Embedding provider returned unexpected dimensions")
            self.vectors[document.document_id]=vector
        self._persist()
    def delete_document(self,document_id:str)->None:
        self.documents.pop(document_id,None);self.vectors.pop(document_id,None);self._persist()
    def clear(self)->None:
        self.documents.clear();self.vectors.clear();self._persist()
    def health_check(self)->dict:
        return {"ok":True,"engine":"LOCAL_COSINE","model_id":self.provider.model_id,"documents":len(self.documents),"dimensions":self.provider.dimensions}
    def search(self,query:str,*,tenant_id:str,limit:int=10,allowed_document_ids:set[str]|None=None,allowed_source_ids:set[str]|None=None,allowed_artifact_ids:set[str]|None=None,allowed_entity_ids:set[str]|None=None,as_of:str|None=None)->list[RetrievalResult]:
        qv=self.provider.embed(query); scored=[]
        for did,d in self.documents.items():
            if d.tenant_id!=tenant_id:continue
            if allowed_document_ids is not None and did not in allowed_document_ids:continue
            if allowed_source_ids is not None and d.data_source_id not in allowed_source_ids:continue
            if allowed_artifact_ids is not None and d.artifact_id not in allowed_artifact_ids:continue
            if allowed_entity_ids is not None and not (set(d.entity_ids)&allowed_entity_ids):continue
            if not temporal_visible(d.observed_at,d.valid_from,d.valid_until,as_of):continue
            score=cosine(qv,self.vectors.get(did,[]))
            if score>0:scored.append((score,d))
        scored.sort(key=lambda x:(-x[0],x[1].document_id));out=[]
        for rank,(score,d) in enumerate(scored[:limit],1):
            out.append(RetrievalResult(result_id=stable_hash("vector",query,d.document_id,as_of,prefix="RRET"),retrieval_method=RetrievalMode.VECTOR,score=round(float(score),6),source_id=d.data_source_id,source_record_id=d.source_record_id,artifact_id=d.artifact_id,document_id=d.document_id,chunk_id=d.document_id if d.document_type=="CHUNK" else None,text=d.text[:4000],metadata=d.metadata,observed_at=d.observed_at,retrieved_at=now_iso(),provenance={"content_hash":d.content_hash,"embedding_model":self.provider.model_id},graph_scope=list(d.entity_ids),matched_entity_ids=list(d.entity_ids),query=query,rank=rank,explanation="Cosine similarity inside graph-derived tenant/source/artifact/entity scope"))
        return out
