from __future__ import annotations

from typing import Protocol
from backend.app.retrieval.models import GraphScope, RetrievalMode, RetrievalRequest, RetrievalResult


class Retriever(Protocol):
    retrieval_type: RetrievalMode
    def can_handle(self, request: RetrievalRequest, scope: GraphScope) -> bool: ...
    def retrieve(self, request: RetrievalRequest, scope: GraphScope) -> list[RetrievalResult]: ...


class RetrieverRegistry:
    def __init__(self): self._retrievers: dict[RetrievalMode, Retriever] = {}
    def register(self, retriever: Retriever) -> None: self._retrievers[retriever.retrieval_type]=retriever
    def get(self, mode: RetrievalMode) -> Retriever | None: return self._retrievers.get(mode)
    def execute(self, modes: list[RetrievalMode], request: RetrievalRequest, scope: GraphScope) -> tuple[list[list[RetrievalResult]], list[dict[str,str]]]:
        groups=[];used=[]
        for mode in modes:
            retriever=self.get(mode)
            if retriever is None or not retriever.can_handle(request,scope): continue
            groups.append(retriever.retrieve(request,scope));used.append({"retriever":mode.value,"reason":"registered retriever accepted graph-scoped request"})
        return groups,used
