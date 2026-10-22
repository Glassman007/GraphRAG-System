import { apiRequest } from './client'
import type { ApiConfig, Dict } from './types'

export interface GraphPreview {
  graph_id: string
  nodes: Dict[]
  edges: Dict[]
  total_nodes: number
  total_edges: number
  sampled: boolean
}

/** The server requires a registered, authorized Company Brain scope. */
export function getGraphPreview(config: ApiConfig, signal?: AbortSignal) {
  if (!config.graphId) throw new Error('Select a Company Brain to view its graph')
  return apiRequest<GraphPreview>(config, '/api/v1/graph/preview', { signal })
}
