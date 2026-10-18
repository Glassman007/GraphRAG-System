import { apiRequest, makeIdempotencyKey, queryString } from './client'
import type { ApiConfig, Dict, PageResponse } from './types'
export const listActions=(c:ApiConfig,p:Dict={},signal?:AbortSignal)=>apiRequest<PageResponse>(c,`/api/v1/actions${queryString(p)}`,{signal})
export const getAction=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/actions/${encodeURIComponent(id)}`,{signal})
export const getActionGovernance=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/actions/${encodeURIComponent(id)}/governance`,{signal})
export const getActionAttempts=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/actions/${encodeURIComponent(id)}/attempts`,{signal})
export const proposeAction=(c:ApiConfig,body:Dict)=>apiRequest<Dict>(c,'/api/v1/actions',{method:'POST',body,idempotencyKey:makeIdempotencyKey('action')})
export const executeAction=(c:ApiConfig,id:string,agentId:string)=>apiRequest<Dict>(c,`/api/v1/actions/${encodeURIComponent(id)}/execute`,{method:'POST',body:{agent_id:agentId},idempotencyKey:makeIdempotencyKey(`execute-${id}`)})
