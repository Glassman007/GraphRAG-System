from __future__ import annotations

from collections import deque
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.temporal import to_epoch_us
from backend.app.services.phase4_graph import GraphSnapshot, GraphEdge, has_label
from backend.app.retrieval.models import GraphScope, RetrievalRequest


DEFAULT_SCOPE_RELS = {
    "AFFECTS","DEPENDS_ON","CONTAINS","CHANGED","ABOUT","SUPPORTS","REFUTES","CONTRADICTS",
    "PRODUCED","DERIVED_FROM","REFERENCES","NORMALIZED_TO","GOVERNS","DOCUMENTED_BY","HAS_ARTIFACT",
    "ROOT_CAUSE","HAS_OUTCOME","PLAN_HAS_TASK","ADDRESSES","TRIGGERED","BASED_ON","SUPERSEDES","PART_OF","INGESTED","RESOLVES_TO","OWNS","RESPONSIBLE_FOR",
}


def _node_visible(node: dict[str, Any], as_of: str | None) -> bool:
    if bool(node.get("deleted")) or str(node.get("status") or "").upper()=="TOMBSTONED":
        return False
    if as_of is None:
        return node.get("valid_until") is None
    point=to_epoch_us(as_of)
    for field in ("observed_at","occurred_at","created_at","valid_from","source_updated_at"):
        value=node.get(field)
        if value is not None and field in {"observed_at","occurred_at","valid_from"} and to_epoch_us(value)>point:
            return False
    vu=node.get("valid_until")
    return vu is None or to_epoch_us(vu)>point


_RETRIEVAL_PROVENANCE_RELS = {"NORMALIZED_TO", "REFERENCES", "DERIVED_FROM", "PART_OF"}

def _retrieval_edge_visible(snapshot: GraphSnapshot, edge: GraphEdge, as_of: str | None) -> bool:
    if as_of is None:
        return edge.properties.get("valid_until") is None
    if edge.type not in _RETRIEVAL_PROVENANCE_RELS:
        return GraphSnapshot._edge_active(edge, as_of)
    # Phase 9 provenance edges are sometimes written at ingestion time. Retrieval
    # history follows the source observation represented by the edge, not the later
    # ingestion timestamp, so fixture/live data can answer historical evidence queries
    # without reseeding old provenance relationships.
    source=snapshot.node(edge.source) or {}; target=snapshot.node(edge.target) or {}
    effective=None
    for node in (source,target):
        if has_label(node,"SourceRecord"):
            effective=node.get("observed_at") or node.get("source_updated_at") or node.get("fetched_at")
            if effective: break
    if effective is None and has_label(source,"Evidence"):
        effective=source.get("observed_at") or source.get("occurred_at")
    if effective is None and has_label(source,"Chunk"):
        effective=source.get("observed_at") or source.get("valid_from")
    if effective is None:
        return GraphSnapshot._edge_active(edge, as_of)
    point=to_epoch_us(as_of)
    if to_epoch_us(effective)>point:
        return False
    vu=edge.properties.get("valid_until")
    return vu is None or to_epoch_us(vu)>point

def _retrieval_neighbors(snapshot: GraphSnapshot, entity_id: str, rel_types: set[str], as_of: str | None):
    for edge in snapshot.outgoing.get(entity_id, []):
        if edge.type in rel_types and _retrieval_edge_visible(snapshot,edge,as_of):
            yield edge.target,edge,"out"
    for edge in snapshot.incoming.get(entity_id, []):
        if edge.type in rel_types and _retrieval_edge_visible(snapshot,edge,as_of):
            yield edge.source,edge,"in"

def _source_record_active(snapshot: GraphSnapshot, source_record_id: str, as_of: str | None) -> bool:
    node = snapshot.node(source_record_id) or {}
    if not node or not has_label(node, "SourceRecord") or not _node_visible(node, as_of):
        return False
    superseders=[e for e in snapshot.incoming.get(source_record_id,[]) if e.type=="SUPERSEDES"]
    if as_of is None:
        return not bool(superseders)
    point=to_epoch_us(as_of)
    for edge in superseders:
        newer=snapshot.node(edge.source) or {}
        effective=newer.get("source_updated_at") or newer.get("observed_at") or edge.properties.get("valid_from")
        if effective is not None and to_epoch_us(effective)<=point:
            return False
    return True


def _artifact_source_visible(snapshot: GraphSnapshot, artifact_id: str, as_of: str | None) -> bool:
    refs = [e for e in snapshot.incoming.get(artifact_id, []) if e.type=="REFERENCES" and has_label(snapshot.node(e.source), "SourceRecord") and _retrieval_edge_visible(snapshot,e,as_of)]
    # Canonical/non-ingestion artifacts without SourceRecord provenance keep their ordinary graph visibility.
    if not refs:
        return True
    return any(_source_record_active(snapshot, e.source, as_of) for e in refs)


class GraphScopeResolver:
    def __init__(self, client: FalkorGraphClient): self.client=client

    @staticmethod
    def resolve_snapshot(snapshot: GraphSnapshot, request: RetrievalRequest, *, allowed_rel_types: set[str] | None = None, max_entities: int = 200) -> GraphScope:
        rels=set(allowed_rel_types or DEFAULT_SCOPE_RELS)
        explicit_seed_request = bool(request.seed_entity_ids)
        seeds=[]
        for seed_id in request.seed_entity_ids:
            seed_node=snapshot.node(seed_id)
            if seed_node is None or not _node_visible(seed_node,request.as_of):
                continue
            if has_label(seed_node,"SourceRecord") and not _source_record_active(snapshot,seed_id,request.as_of):
                continue
            if has_label(seed_node,"Artifact") and not _artifact_source_visible(snapshot,seed_id,request.as_of):
                continue
            seeds.append(seed_id)
        if not seeds and not explicit_seed_request:
            q=request.query.lower()
            candidates=[]
            for node in snapshot.nodes.values():
                if not _node_visible(node,request.as_of):continue
                node_id=str(node.get("id") or "")
                if has_label(node,"SourceRecord") and not _source_record_active(snapshot,node_id,request.as_of):continue
                if has_label(node,"Artifact") and not _artifact_source_visible(snapshot,node_id,request.as_of):continue
                values=[str(node.get(k) or "") for k in ("id","name","title","summary","statement","description")]
                hits=sum(1 for v in values if v and v.lower() in q)
                if hits:candidates.append((-hits,str(node.get("id"))))
            candidates.sort();seeds=[cid for _,cid in candidates[:5]]
        entities=[];seen=set(seeds);queue=deque((s,0,[s],[]) for s in seeds);paths=[];relationships=[]
        while queue and len(seen)<=max_entities:
            current,depth,node_path,edge_path=queue.popleft()
            if current not in entities:entities.append(current)
            if depth>=request.max_graph_hops:continue
            for nxt,edge,direction in _retrieval_neighbors(snapshot,current,rels,request.as_of):
                node=snapshot.node(nxt)
                if node is None or not _node_visible(node,request.as_of):continue
                if has_label(node,"SourceRecord") and not _source_record_active(snapshot,nxt,request.as_of):continue
                if has_label(node,"Artifact") and not _artifact_source_visible(snapshot,nxt,request.as_of):continue
                if edge.as_dict() not in relationships:relationships.append(edge.as_dict())
                next_path=node_path+[nxt];next_edges=edge_path+[edge.as_dict()]
                paths.append({"node_ids":next_path,"edges":next_edges})
                if nxt not in seen and len(seen)<max_entities:
                    seen.add(nxt);queue.append((nxt,depth+1,next_path,next_edges))
        labels=lambda eid:{str(x) for x in (snapshot.node(eid) or {}).get("_labels",[])}
        data_sources=sorted(e for e in entities if "DataSource" in labels(e))
        source_type_map={e:str((snapshot.node(e) or {}).get("source_type") or (snapshot.node(e) or {}).get("source_kind") or "") for e in data_sources}
        source_records=sorted(e for e in entities if "SourceRecord" in labels(e))
        artifacts=sorted(e for e in entities if "Artifact" in labels(e))
        documents=sorted(e for e in entities if "Document" in labels(e))
        chunks=sorted(e for e in entities if "Chunk" in labels(e))

        # Retrieval-material expansion: max_graph_hops bounds organizational traversal,
        # but once the graph has selected an Artifact we may inspect its directly linked
        # storage children without turning retrieval into a global corpus search.  This
        # keeps the Artifact as the graph-required gate while allowing an indexed Chunk
        # that sits one provenance hop beyond the traversal boundary to be searched.
        # Only direct graph-linked material is added; unrelated Artifacts/Documents/Chunks
        # remain outside the scope.
        artifact_set=set(artifacts)
        if artifact_set:
            for node_id,node in snapshot.nodes.items():
                if not _node_visible(node,request.as_of):
                    continue
                if has_label(node,"Chunk"):
                    if any(
                        edge.type=="PART_OF"
                        and edge.target in artifact_set
                        and _retrieval_edge_visible(snapshot,edge,request.as_of)
                        for edge in snapshot.outgoing.get(node_id,[])
                    ):
                        chunks.append(node_id)
                elif has_label(node,"Document"):
                    if any(
                        edge.type in {"HAS_ARTIFACT","DOCUMENTED_BY"}
                        and edge.target in artifact_set
                        and _retrieval_edge_visible(snapshot,edge,request.as_of)
                        for edge in snapshot.outgoing.get(node_id,[])
                    ):
                        documents.append(node_id)
            chunks=sorted(set(chunks));documents=sorted(set(documents))

        source_types=set(request.allowed_source_types)
        if source_types:
            data_sources=[e for e in data_sources if str((snapshot.node(e) or {}).get("source_type")) in source_types]
            allowed_ds=set(data_sources)
            source_records=[e for e in source_records if any(x.target in allowed_ds for x in snapshot.edges_from(e,{"DERIVED_FROM"},as_of=request.as_of)) or (snapshot.node(e) or {}).get("source_type") in source_types]
            allowed_sr=set(source_records)
            def artifact_allowed(aid:str)->bool:
                refs=[e.source for e in snapshot.incoming.get(aid,[]) if e.type=="REFERENCES" and has_label(snapshot.node(e.source),"SourceRecord") and _retrieval_edge_visible(snapshot,e,request.as_of)]
                if refs:return any(sr in allowed_sr for sr in refs)
                return str((snapshot.node(aid) or {}).get("source_type") or "") in source_types
            artifacts=[aid for aid in artifacts if artifact_allowed(aid)]
            allowed_artifacts=set(artifacts)
            chunks=[cid for cid in chunks if any(e.target in allowed_artifacts for e in snapshot.edges_from(cid,{"PART_OF"},as_of=None))]
            documents=[did for did in documents if any(e.target in allowed_artifacts for e in snapshot.edges_from(did,{"HAS_ARTIFACT","DOCUMENTED_BY"},as_of=None)) or str((snapshot.node(did) or {}).get("source_type") or "") in source_types]
        candidates=[]
        for eid in artifacts+documents+chunks+source_records:
            candidates.append({"entity_id":eid,"labels":sorted(labels(eid)),"graph_distance":min((len(p["edges"]) for p in paths if p["node_ids"] and p["node_ids"][-1]==eid),default=0)})
        return GraphScope(seed_entities=seeds,entities=entities,relationships=relationships,data_sources=data_sources,source_types={k:v for k,v in source_type_map.items() if k in set(data_sources)},source_records=source_records,artifacts=artifacts,documents=documents,chunks=chunks,temporal_scope={"as_of":request.as_of},retrieval_candidates=candidates,paths=paths,graph_required=True)

    def resolve(self, request: RetrievalRequest) -> GraphScope:
        if request.tenant_id != self.client.settings.tenant_id:
            raise ValueError("tenant_id does not match graph client tenant")
        return self.resolve_snapshot(GraphSnapshot.load(self.client),request)
