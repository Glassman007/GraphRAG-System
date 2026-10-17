import { apiRequest, queryString } from './client'
import type { ApiConfig, Dict, PageResponse } from './types'
export const listAgents=(c:ApiConfig,p:Dict={},signal?:AbortSignal)=>apiRequest<PageResponse>(c,`/api/v1/agents${queryString(p)}`,{signal})
export const getAgent=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/agents/${encodeURIComponent(id)}`,{signal})
export const getAgentTasks=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/agents/${encodeURIComponent(id)}/tasks`,{signal})
export const getAgentCapabilities=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/agents/${encodeURIComponent(id)}/capabilities`,{signal})
