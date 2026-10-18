"""Allowlisted, read-only organizational tools. No dynamic Cypher or external actions."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.graph.temporal import to_epoch_us


def current(node: dict | None, as_of: str | None = None) -> bool:
    if not node:
        return False
    when = to_epoch_us(as_of or datetime.now(timezone.utc).isoformat())
    start = node.get('valid_from')
    end = node.get('valid_until')
    return (not start or to_epoch_us(start) <= when) and (not end or to_epoch_us(end) > when)


def thin(node: dict | None) -> dict:
    if not node:
        return {}
    keys = ('id','name','title','description','summary','status','severity','criticality','owner_id',
            'source_type','source_ref_id','observed_at','occurred_at','created_at','valid_from','valid_until',
            'statement','confidence','actor_id','decision','rationale','_labels')
    return {k: str(v)[:550] if isinstance(v, str) else v for k,v in node.items() if k in keys and v is not None}


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class FindEntities(Strict):
    query: str = Field(min_length=2, max_length=120)
    limit: int = Field(default=8, ge=1, le=15)


class EntityArg(Strict):
    entity_id: str = Field(min_length=2, max_length=150)


class NeighborsArg(EntityArg):
    limit: int = Field(default=20, ge=1, le=40)
    offset: int = Field(default=0, ge=0, le=10000)
    as_of: str | None = None


class MemoryArg(EntityArg):
    limit: int = Field(default=20, ge=1, le=40)
    as_of: str | None = None


class PathsArg(EntityArg):
    target_id: str | None = Field(default=None, max_length=150)
    max_depth: int = Field(default=3, ge=1, le=5)
    direction: str = Field(default='both', pattern='^(both|out|in)$')


class DependencyArg(EntityArg):
    max_depth: int = Field(default=4, ge=1, le=6)


SCHEMAS: dict[str, type[Strict]] = {
    'find_entities': FindEntities,
    'get_entity': EntityArg,
    'graph_neighbors': NeighborsArg,
    'graph_paths': PathsArg,
    'dependency_impact': DependencyArg,
    'incident_context': EntityArg,
    'historical_record': EntityArg,
    'expertise': FindEntities,
    'related_memory': MemoryArg,
}

DESCRIPTIONS = {
    'find_entities':'Search the canonical graph by descriptive name or stable ID.',
    'get_entity':'Retrieve a canonical entity, including its current/historical validity.',
    'graph_neighbors':'Inspect directed, typed relationships. Use offset and a small limit (2-4) to page; repeat with next_offset, not the same offset.',
    'graph_paths':'Find bounded multi-hop paths from an entity to a specific target or reachable neighbors.',
    'dependency_impact':'Find operational systems that depend on a selected system (reverse DEPENDS_ON paths).',
    'incident_context':'Retrieve incident evidence, competing claims, events, decisions and linked systems.',
    'historical_record':'Inspect current and superseded relationships and earlier owners/policies.',
    'expertise':'Discover employees or teams with recorded EXPERT_IN and CANDIDATE_EXPERT edges.',
    'related_memory':'Retrieve persisted claims, findings, checkpoints and outcomes connected to an entity, including validity and provenance.',
}


def declarations() -> list[dict]:
    return [{'type':'function', 'function':{'name':n,'description':DESCRIPTIONS[n],
             'parameters':schema.model_json_schema()}} for n,schema in SCHEMAS.items()]


class ToolRegistry:
    def __init__(self, snapshot_factory):
        self.snapshot_factory = snapshot_factory

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in SCHEMAS:
            raise ValueError('Tool not allowlisted')
        a = SCHEMAS[name].model_validate(arguments)
        snapshot: GraphSnapshot = self.snapshot_factory()  # observe latest graph state each tool call
        node = snapshot.node(getattr(a, 'entity_id', ''))
        if name == 'find_entities':
            terms = a.query.lower().strip().split()
            values = []
            for n in snapshot.nodes.values():
                if not current(n) or has_label(n,'AgentRun') or has_label(n,'AgentStep'):
                    continue
                candidate = ' '.join(str(n.get(k) or '') for k in ('name','title','id','description')).lower()
                if all(t in candidate for t in terms):
                    values.append(thin(n))
            return {'items':values[:a.limit], 'has_more':len(values)>a.limit}
        if not node:
            return {'error':'ENTITY_NOT_FOUND', 'id':a.entity_id}
        if name == 'get_entity':
            return {'entity':thin(node),'currently_valid':current(node)}
        if name == 'graph_neighbors':
            items=[]
            for nxt, edge, direction in snapshot.neighbors(a.entity_id,as_of=a.as_of):
                other=snapshot.node(nxt)
                if other and current(other,a.as_of):
                    items.append({'direction':direction,'relationship':edge.as_dict(),'neighbor':thin(other)})
            page=items[a.offset:a.offset+a.limit]
            next_offset=a.offset+len(page) if a.offset+len(page)<len(items) else None
            return {'entity_id':a.entity_id,'offset':a.offset,'items':page,
                    'next_offset':next_offset,'has_more':next_offset is not None,
                    'total':len(items),'truncated':next_offset is not None}
        if name == 'graph_paths':
            paths = snapshot.bounded_paths(a.entity_id,targets={a.target_id} if a.target_id else None,
                                           max_depth=a.max_depth,direction=a.direction,max_paths=15)
            return {'paths':paths,'truncated_or_bounded':len(paths)>=15}
        if name == 'dependency_impact':
            result=snapshot.dependency_reachability(a.entity_id,reverse=True,max_depth=a.max_depth)
            return {'impacted':[{'path':x,'name':(snapshot.node(x['entity_id']) or {}).get('name')}
                                for x in result[:25]],'truncated':len(result)>25}
        if name == 'related_memory':
            # Graph-backed memory retrieval is READ ONLY. Prefer direct relevant nodes,
            # then bounded two-hop context through Task/Investigation/Incident paths.
            supported={'Claim','Finding','Checkpoint','CompactionRecord','Outcome','Decision'}
            items=[]
            visited={a.entity_id}
            frontier=[(a.entity_id, [])]
            for depth in range(2):
                next_frontier=[]
                for entity, chain in frontier:
                    for nxt,edge,_ in snapshot.neighbors(entity,as_of=a.as_of):
                        if nxt in visited:continue
                        visited.add(nxt)
                        other=snapshot.node(nxt)
                        if not other or not current(other,a.as_of):continue
                        path=[*chain,edge.as_dict()]
                        if any(has_label(other,label) for label in supported):
                            items.append({'record':thin(other),'path':path,
                                          'valid':current(other,a.as_of),
                                          'source_ref_id':other.get('source_ref_id')})
                        if depth==0:next_frontier.append((nxt,path))
                frontier=next_frontier[:40]
            return {'items':items[:a.limit], 'truncated':len(items)>a.limit,
                    'note':'Historical memory is not automatically verified; check provenance and validity.'}
        if name == 'incident_context':
            if not has_label(node,'Incident'):
                return {'error':'NOT_AN_INCIDENT'}
            rels=snapshot.neighbors(a.entity_id,as_of=None)
            grouped={k:[] for k in ('Evidence','Claim','Event','Decision','System','Deployment','Change','Policy','Finding')}
            for linked, edge, _ in rels:
                other=snapshot.node(linked)
                if not current(other):
                    continue
                for label in grouped:
                    if has_label(other,label) and len(grouped[label])<15:
                        grouped[label].append({'entity':thin(other),'relationship':edge.as_dict()})
            return {'incident':thin(node),'related':grouped}
        if name == 'historical_record':
            history=[]
            for edge in snapshot.edges:
                if edge.source==a.entity_id or edge.target==a.entity_id:
                    history.append({'type':edge.type,'source':edge.source,'target':edge.target,
                                    'valid_from':edge.properties.get('valid_from'),
                                    'valid_until':edge.properties.get('valid_until'),
                                    'current':snapshot._edge_active(edge,None),
                                    'source_ref_id':edge.properties.get('source_ref_id')})
            return {'entity':thin(node),'currently_valid':current(node),
                    'relationships':history[:35], 'truncated':len(history)>35}
        if name == 'expertise':
            items=[]
            for e in snapshot.edges:
                if e.type not in {'EXPERT_IN','CANDIDATE_EXPERT'} or not snapshot._edge_active(e,None):continue
                actor=snapshot.node(e.source); domain=snapshot.node(e.target)
                if not actor or not domain:continue
                if a.query.lower() not in (' '.join([str(domain.get('name','')),str(domain.get('id',''))])).lower():continue
                items.append({'expert':thin(actor),'domain':thin(domain),'relationship':e.type,
                              'source_ref_id':e.properties.get('source_ref_id'),'confidence':e.properties.get('confidence')})
            return {'items':items[:a.limit],'truncated':len(items)>a.limit}
        raise AssertionError('Unreachable')
