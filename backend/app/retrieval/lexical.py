from __future__ import annotations

import json
import math
from pathlib import Path
from collections import Counter
from typing import Iterable

from backend.app.retrieval.models import IndexedDocument, RetrievalMode, RetrievalResult
from backend.app.retrieval.utils import tokenize, temporal_visible, stable_hash
from backend.app.services.phase6_utils import now_iso


class LexicalIndex:
    def index_document(self, document: IndexedDocument) -> None: raise NotImplementedError
    def delete_document(self, document_id: str) -> None: raise NotImplementedError
    def search(self, query: str, **kwargs) -> list[RetrievalResult]: raise NotImplementedError
    def health_check(self) -> dict: raise NotImplementedError


class BM25LexicalIndex(LexicalIndex):
    def __init__(self, path: str | Path | None = None, *, k1: float = 1.5, b: float = 0.75):
        self.path = Path(path) if path else None
        self.k1, self.b = float(k1), float(b)
        self.documents: dict[str, IndexedDocument] = {}
        if self.path and self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.documents = {k: IndexedDocument.model_validate(v) for k, v in payload.items()}

    def _persist(self) -> None:
        if not self.path: return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({k: v.model_dump(mode="json") for k,v in self.documents.items()}, indent=2, sort_keys=True), encoding="utf-8")

    def index_document(self, document: IndexedDocument) -> None:
        prior = self.documents.get(document.document_id)
        # Content equality alone is not enough for an idempotent index update:
        # temporal/provenance metadata can change while the body stays identical
        # (for example when a source version is superseded/tombstoned).
        if prior is not None and prior.model_dump(mode="json") == document.model_dump(mode="json"):
            return
        self.documents[document.document_id] = document
        self._persist()

    def delete_document(self, document_id: str) -> None:
        self.documents.pop(document_id, None); self._persist()

    def clear(self) -> None:
        self.documents.clear(); self._persist()

    def health_check(self) -> dict:
        return {"ok": True, "engine": "BM25", "documents": len(self.documents), "version": "phase10-bm25-v1"}

    def _scoped(self, *, tenant_id: str, allowed_document_ids: set[str] | None, allowed_source_ids: set[str] | None, allowed_artifact_ids: set[str] | None, allowed_entity_ids: set[str] | None, as_of: str | None) -> list[IndexedDocument]:
        out=[]
        for d in self.documents.values():
            if d.tenant_id != tenant_id: continue
            if allowed_document_ids is not None and d.document_id not in allowed_document_ids: continue
            if allowed_source_ids is not None and d.data_source_id not in allowed_source_ids: continue
            if allowed_artifact_ids is not None and d.artifact_id not in allowed_artifact_ids: continue
            if allowed_entity_ids is not None and not (set(d.entity_ids) & allowed_entity_ids): continue
            if not temporal_visible(d.observed_at, d.valid_from, d.valid_until, as_of): continue
            out.append(d)
        return out

    def search(self, query: str, *, tenant_id: str, limit: int = 10, allowed_document_ids: set[str] | None = None, allowed_source_ids: set[str] | None = None, allowed_artifact_ids: set[str] | None = None, allowed_entity_ids: set[str] | None = None, as_of: str | None = None) -> list[RetrievalResult]:
        docs=self._scoped(tenant_id=tenant_id, allowed_document_ids=allowed_document_ids, allowed_source_ids=allowed_source_ids, allowed_artifact_ids=allowed_artifact_ids, allowed_entity_ids=allowed_entity_ids, as_of=as_of)
        if not docs: return []
        q=tokenize(query)
        if not q: return []
        tokenized={d.document_id: tokenize(d.text) for d in docs}
        avgdl=sum(len(v) for v in tokenized.values())/max(1,len(tokenized))
        df=Counter()
        for toks in tokenized.values():
            for t in set(toks): df[t]+=1
        results=[]
        n=len(docs)
        for d in docs:
            toks=tokenized[d.document_id]; tf=Counter(toks); dl=len(toks) or 1; score=0.0
            for t in q:
                if tf[t] == 0: continue
                idf=math.log(1+(n-df[t]+0.5)/(df[t]+0.5))
                score += idf*(tf[t]*(self.k1+1))/(tf[t]+self.k1*(1-self.b+self.b*dl/max(avgdl,1)))
            phrase_bonus = 1.0 if query.lower() in d.text.lower() else 0.0
            score += phrase_bonus
            if score <= 0: continue
            results.append((score,d))
        results.sort(key=lambda x:(-x[0],x[1].document_id))
        out=[]
        for rank,(score,d) in enumerate(results[:limit],1):
            out.append(RetrievalResult(
                result_id=stable_hash("lexical", query, d.document_id, as_of, prefix="RRET"), retrieval_method=RetrievalMode.LEXICAL,
                score=round(float(score),6), source_id=d.data_source_id, source_record_id=d.source_record_id, artifact_id=d.artifact_id,
                document_id=d.document_id, chunk_id=d.document_id if d.document_type=="CHUNK" else None, text=d.text[:4000], metadata=d.metadata,
                observed_at=d.observed_at, retrieved_at=now_iso(), provenance={"content_hash":d.content_hash,"index":"BM25","version":"phase10-bm25-v1"},
                graph_scope=list(d.entity_ids), matched_entity_ids=list(d.entity_ids), query=query, rank=rank,
                explanation="BM25 match inside graph-derived tenant/source/artifact/entity scope",
            ))
        return out
