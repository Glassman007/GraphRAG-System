from __future__ import annotations

from backend.app.retrieval.models import GraphScope, RetrievalResult
from backend.app.services.phase4_graph import GraphSnapshot

AUTHORITY = {"AUTHORITATIVE": 3, "STRONG": 2, "STANDARD": 1, "UNTRUSTED": 0}


def deterministic_rerank(results:list[RetrievalResult],scope:GraphScope,snapshot:GraphSnapshot)->list[RetrievalResult]:
    distances={x["entity_id"]:int(x.get("graph_distance") or 0) for x in scope.retrieval_candidates}
    scored=[]
    for item in results:
        base=float(item.score)
        source=snapshot.node(item.source_id) if item.source_id else None
        authority=AUTHORITY.get(str((source or {}).get("trust_class") or "STANDARD").upper(),1)
        ids=item.matched_entity_ids or item.graph_scope
        distance=min((distances.get(i,99) for i in ids),default=99)
        # Tiny deterministic tie-break bonuses. Retrieval relevance remains dominant.
        adjusted=base + 0.0001*authority + (0.0001/(1+distance) if distance<99 else 0.0)
        copy=item.model_copy(deep=True)
        copy.metadata={**copy.metadata,"source_authority_class":(source or {}).get("trust_class"),"graph_distance":None if distance==99 else distance,"pre_rerank_score":base}
        copy.score=round(adjusted,8)
        scored.append(copy)
    scored.sort(key=lambda r:(-r.score,r.result_id))
    for rank,item in enumerate(scored,1): item.rank=rank
    return scored
