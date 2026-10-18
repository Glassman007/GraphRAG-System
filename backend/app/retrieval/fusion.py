from __future__ import annotations

from collections import defaultdict
from backend.app.retrieval.models import RetrievalResult


def reciprocal_rank_fusion(groups:list[list[RetrievalResult]],*,k:int=60,limit:int=10)->list[RetrievalResult]:
    scores=defaultdict(float);best={}
    for group in groups:
        for rank,result in enumerate(group,1):
            key=result.chunk_id or result.document_id or result.artifact_id or result.source_record_id or result.result_id
            scores[key]+=1.0/(k+rank)
            prior=best.get(key)
            if prior is None or result.score>prior.score:best[key]=result
    ordered=sorted(best,key=lambda x:(-scores[x],x))[:limit]
    out=[]
    for rank,key in enumerate(ordered,1):
        item=best[key].model_copy(deep=True);item.score=round(scores[key],8);item.rank=rank;item.explanation=f"Reciprocal Rank Fusion across scoped retrievers; fused_score={item.score}"
        out.append(item)
    return out
