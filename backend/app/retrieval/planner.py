from __future__ import annotations

import hashlib, json, re
from backend.app.retrieval.models import GraphScope, RetrievalMode, RetrievalPlan, RetrievalRequest


class RetrievalPlanner:
    IDENT=re.compile(r"\b(?:[A-Z]{2,}-[A-Z0-9-]+|[A-Z]{2,}-\d+|[A-Za-z0-9_]+\.(?:log|md|sql|json)|#[0-9]+)\b")
    def plan(self,request:RetrievalRequest,scope:GraphScope)->RetrievalPlan:
        if request.retrieval_modes:
            modes=list(dict.fromkeys(request.retrieval_modes));reasons={m.value:"explicitly requested" for m in modes}
        else:
            q=request.query.lower();modes=[];reasons={}
            if self.IDENT.search(request.query) or '"' in request.query or any(t in q for t in ("error","stack trace","exact","policy","filename","cannot be null")):
                modes.append(RetrievalMode.LEXICAL);reasons["LEXICAL"]="exact identifier/phrase/error/policy wording is present"
            if any(t in q for t in ("similar","why","cause","explain","paraphrase","seen before","historical")) or not modes:
                modes.append(RetrievalMode.VECTOR);reasons["VECTOR"]="semantic or conceptual evidence is requested"
            if scope.artifacts or scope.documents:
                modes.append(RetrievalMode.DOCUMENT);reasons["DOCUMENT"]="graph scope already identifies document/artifact candidates"
            if any(t in q for t in ("when","author","source","status","timestamp","label","repository")):
                modes.append(RetrievalMode.METADATA);reasons["METADATA"]="question primarily asks for structured metadata"
            source_types=set(scope.source_types.values())
            if "database" in source_types:
                modes.append(RetrievalMode.SQL);reasons["SQL"]="graph scope selects a configured read-only database DataSource"
            if "internal_api" in source_types:
                modes.append(RetrievalMode.API);reasons["API"]="graph scope selects a configured internal API DataSource"
            modes=list(dict.fromkeys(modes))
        # Hash the material retrieval scope, not every traversed runtime edge.
        # Retrieval writeback itself adds Evidence/ABOUT/DERIVED_FROM relationships;
        # those must not make an otherwise identical request look like a new scope.
        material_scope = {
            "seed_entities": sorted(scope.seed_entities),
            "data_sources": sorted(scope.data_sources),
            "source_types": sorted(scope.source_types.items()),
            "source_records": sorted(scope.source_records),
            "artifacts": sorted(scope.artifacts),
            "documents": sorted(scope.documents),
            "chunks": sorted(scope.chunks),
            "temporal_scope": scope.temporal_scope,
        }
        scope_hash=hashlib.sha256(json.dumps(material_scope,sort_keys=True,default=str).encode()).hexdigest()
        return RetrievalPlan(modes=modes,reasons=reasons,graph_scope_hash=scope_hash)
