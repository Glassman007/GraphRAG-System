import type { Dict } from '../api/types'

export type UiGraphNode = { id: string; type: string; label: string; status?: string; data: Dict }
export type UiGraphEdge = { id: string; source: string; target: string; type: string; data: Dict }
export type UiGraph = { nodes: UiGraphNode[]; edges: UiGraphEdge[] }

export function sqlSchemaToGraph(payload: Dict): UiGraph {
  const nodes: UiGraphNode[] = (payload.tables || []).map((table: Dict) => ({
    id: String(table.id), type: 'SqlTable', label: String(table.name || table.id), data: table,
  }))
  const known = new Set(nodes.map(node => node.id))
  const edges: UiGraphEdge[] = (payload.foreign_keys || [])
    .filter((fk: Dict) => known.has(String(fk.source_id)) && known.has(String(fk.target_id)))
    .map((fk: Dict) => ({
      id: String(fk.properties?.edge_id || `${fk.source_id}:${fk.properties?.constraint_id}:${fk.target_id}`),
      source: String(fk.source_id), target: String(fk.target_id), type: 'FOREIGN_KEY_TO', data: fk.properties || {},
    }))
  return {nodes, edges}
}

function labels(n: Dict) { return Array.isArray(n?._labels) ? n._labels : [] }
function nodeType(n: Dict) { return String(labels(n).find((x:string) => x !== 'Entity') || n?.type || n?.kind || 'Entity') }
function labelFor(n: Dict) { return String(n?.name || n?.title || n?.statement || n?.description || n?.id || 'unknown') }
// Relationship responses contain both full neighbors and ID-only endpoints.
// Never let a reference-only placeholder replace a canonical node payload.
function nodeDetailScore(node: UiGraphNode): number {
  const raw = node.data || {}
  const properties = Object.keys(raw).filter(key => !['id', 'entity_id', 'task_id', 'claim_id', 'evidence_id'].includes(key))
  return properties.length + (node.type !== 'Entity' && node.type !== 'EvidenceRoot' ? 2 : 0)
}
function preserveRichNode(map: Map<string, UiGraphNode>, next: UiGraphNode) {
  const previous = map.get(next.id)
  if (!previous) { map.set(next.id, next); return }
  const richer = nodeDetailScore(next) > nodeDetailScore(previous) ? next : previous
  const weaker = richer === next ? previous : next
  map.set(next.id, {
    ...richer,
    status: richer.status || weaker.status,
    data: {...weaker.data, ...richer.data},
  })
}
function addNode(map: Map<string, UiGraphNode>, value: any, forcedType?: string) {
  if (!value || typeof value !== 'object') return
  const id = String(value.id || value.entity_id || value.task_id || value.claim_id || value.evidence_id || '')
  if (!id) return
  preserveRichNode(map, { id, type: forcedType || nodeType(value), label: labelFor(value), status: value.status, data: value })
}
function addEdge(map: Map<string, UiGraphEdge>, source: string, type: string, target: string, data: Dict = {}) {
  if (!source || !target) return
  const id = String(data.id || `${source}:${type}:${target}`)
  map.set(id, { id, source, target, type, data })
}
function relationShape(rel: any) {
  const relationship = rel?.relationship
  const e = relationship && typeof relationship === 'object' ? relationship : (rel?.edge || rel)
  const explicitType = typeof relationship === 'string' ? relationship : undefined
  return {
    source: String(e?.source || rel?.source || ''),
    target: String(e?.target || rel?.target || ''),
    type: String(explicitType || e?.type || e?.relationship_type || rel?.type || rel?.relationship_type || 'RELATED_TO'),
    data: (e && typeof e === 'object' ? (e.properties || e) : rel?.properties) || {},
  }
}

export function contextToGraph(context: Dict): UiGraph {
  const nodes=new Map<string,UiGraphNode>(), edges=new Map<string,UiGraphEdge>()
  addNode(nodes, context.situation, 'Situation')
  for (const key of ['affected_entities','claims','evidence','tasks']) for (const item of context?.[key] || []) addNode(nodes,item)
  for (const rel of context.relationships || []) { const r=relationShape(rel); addNode(nodes, rel.neighbor); addEdge(edges,r.source,r.type,r.target,r.data) }
  return {nodes:[...nodes.values()],edges:[...edges.values()]}
}
export function investigationToGraph(investigation: Dict, findings: Dict[] = [], evidence: Dict[] = [], retrieval?: Dict): UiGraph {
  const nodes=new Map<string,UiGraphNode>(), edges=new Map<string,UiGraphEdge>(); addNode(nodes, investigation, 'Investigation')
  for (const f of findings) { addNode(nodes,f,'Finding'); addEdge(edges,String(investigation.id),'HAS_FINDING',String(f.id),{}) }
  for (const e of evidence) { addNode(nodes,e,'Evidence'); addEdge(edges,String(investigation.id),'HAS_EVIDENCE',String(e.id),{}) }
  const scope = retrieval?.graph_scope || {}
  for (const raw of scope.entities || []) { const item=typeof raw === 'string' ? {id:raw} : raw; addNode(nodes,item) }
  for (const raw of scope.relationships || scope.paths || []) {
    if (Array.isArray(raw?.edges)) for (const edge of raw.edges) { const r=relationShape(edge); addEdge(edges,r.source,r.type,r.target,r.data) }
    else { const r=relationShape(raw); addEdge(edges,r.source,r.type,r.target,r.data) }
  }
  return {nodes:[...nodes.values()],edges:[...edges.values()]}
}
export function taskPlanToGraph(payload: Dict): UiGraph {
  const nodes=new Map<string,UiGraphNode>(), edges=new Map<string,UiGraphEdge>()
  const tasks=payload.tasks || payload?.plan?.tasks || []
  for (const detail of tasks) { const task=detail.task || detail; addNode(nodes,task,'Task') }
  for (const detail of tasks) { const task=detail.task || detail; for (const p of detail.prerequisites || []) { const target=p.entity || p; addNode(nodes,target,'Task'); addEdge(edges,String(task.id),'REQUIRES',String(target.id),p) } }
  return {nodes:[...nodes.values()],edges:[...edges.values()]}
}
export function decisionGenealogyToGraph(payload: Dict): UiGraph {
  const nodes=new Map<string,UiGraphNode>(), edges=new Map<string,UiGraphEdge>()
  const root=payload.decision || payload; addNode(nodes,root,'Decision')
  const rootId=String(root.id || payload.decision_id || '')
  const groups:[string,string][]=[['claims','BASED_ON'],['evidence','SUPPORTED_BY'],['policies','GOVERNED_BY'],['approvals','APPROVED_BY'],['actions','LED_TO'],['outcomes','HAS_OUTCOME'],['alternatives','CONSIDERED']]
  for (const [key,rel] of groups) for (const raw of payload[key] || []) { const item=raw.entity || raw.claim || raw.evidence || raw.action || raw.outcome || raw.policy || raw; addNode(nodes,item); if(rootId && item?.id) addEdge(edges,rootId,rel,String(item.id),raw) }
  for (const rel of payload.relationships || payload.edges || []) { const r=relationShape(rel); addEdge(edges,r.source,r.type,r.target,r.data) }
  return {nodes:[...nodes.values()],edges:[...edges.values()]}
}
export function blastRadiusToGraph(payload: Dict, centerId: string): UiGraph {
  const nodes=new Map<string,UiGraphNode>(), edges=new Map<string,UiGraphEdge>(); addNode(nodes,{id:centerId,name:centerId},'Center')
  const candidates=[...(payload.directly_affected || []),...(payload.downstream_entities || []),...(payload.affected_entities || []),...(payload.impacted || [])]
  for (const raw of candidates) addNode(nodes,raw.entity || raw)
  for (const path of payload.paths || payload.graph_paths || []) {
    const pathEdges=path.edges || path.relationships || []
    for (const edge of pathEdges) { const r=relationShape(edge); addEdge(edges,r.source,r.type,r.target,r.data); addNode(nodes,{id:r.source}); addNode(nodes,{id:r.target}) }
  }
  return {nodes:[...nodes.values()],edges:[...edges.values()]}
}
export function processToGraph(payload: Dict): UiGraph {
  const nodes=new Map<string,UiGraphNode>(), edges=new Map<string,UiGraphEdge>()
  for (const step of payload.steps || []) addNode(nodes,step.event || step.entity || step,'ProcessStep')
  const groups:[string,string][]=[['temporal_edges','BEFORE'],['trigger_edges','TRIGGERED'],['dependency_edges','DEPENDENCY'],['causal_edges','CAUSE']]
  for (const [key,fallback] of groups) for (const raw of payload[key] || []) { const r=relationShape(raw); addEdge(edges,r.source,r.type || fallback,r.target,r.data) }
  return {nodes:[...nodes.values()],edges:[...edges.values()]}
}
export function anomalyToGraph(anomaly: Dict): UiGraph {
  const nodes=new Map<string,UiGraphNode>(), edges=new Map<string,UiGraphEdge>()
  if (anomaly.abnormal_edge) { const r=relationShape(anomaly.abnormal_edge); addNode(nodes,{id:r.source}); addNode(nodes,{id:r.target}); addEdge(edges,r.source,r.type,r.target,{...r.data,abnormal:true}) }
  for (const path of anomaly.normal_paths_present || []) for (const edge of path) { const r=relationShape(edge); addNode(nodes,{id:r.source}); addNode(nodes,{id:r.target}); addEdge(edges,r.source,r.type,r.target,{...r.data,expected:true}) }
  if (anomaly.entity) addNode(nodes,anomaly.entity)
  return {nodes:[...nodes.values()],edges:[...edges.values()]}
}

export function relationshipsToGraph(items: Dict[] = []): UiGraph {
  const nodes=new Map<string,UiGraphNode>(), edges=new Map<string,UiGraphEdge>()
  for (const item of items) {
    addNode(nodes,item.neighbor)
    const r=relationShape(item)
    addNode(nodes,{id:r.source}); addNode(nodes,{id:r.target})
    addEdge(edges,r.source,r.type,r.target,r.data)
  }
  return {nodes:[...nodes.values()],edges:[...edges.values()]}
}

export function mergeGraphs(...graphs: UiGraph[]): UiGraph {
  const nodes=new Map<string,UiGraphNode>(), edges=new Map<string,UiGraphEdge>()
  for (const graph of graphs) {
    for (const node of graph.nodes) {
      preserveRichNode(nodes,node)
    }
    for (const edge of graph.edges) edges.set(edge.id,edge)
  }
  return {nodes:[...nodes.values()],edges:[...edges.values()]}
}

export function filterGraph(graph: UiGraph, filters: { nodeType?: string; edgeType?: string; status?: string; source?: string }): UiGraph {
  const nodeType=(filters.nodeType||'').toLowerCase(), status=(filters.status||'').toLowerCase(), source=(filters.source||'').toLowerCase()
  const nodes=graph.nodes.filter(node => {
    if (nodeType && node.type.toLowerCase()!==nodeType) return false
    if (status && String(node.status||'').toLowerCase()!==status) return false
    if (source) {
      const raw=node.data||{}
      const hay=[raw.source_id,raw.source_type,raw.source,raw.data_source_id].filter(Boolean).join(' ').toLowerCase()
      if (!hay.includes(source)) return false
    }
    return true
  })
  const allowed=new Set(nodes.map(n=>n.id)); const edgeType=(filters.edgeType||'').toLowerCase()
  const edges=graph.edges.filter(edge => allowed.has(edge.source)&&allowed.has(edge.target)&&(!edgeType||edge.type.toLowerCase()===edgeType))
  return {nodes,edges}
}
