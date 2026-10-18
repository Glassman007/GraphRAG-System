import { apiRequest, makeIdempotencyKey, queryString } from './client'
import type { ApiConfig, Dict, PageResponse } from './types'
export const listPlans=(c:ApiConfig,p:Dict={},signal?:AbortSignal)=>apiRequest<PageResponse>(c,`/api/v1/plans${queryString(p)}`,{signal})
export const createPlan=(c:ApiConfig,body:Dict)=>apiRequest<Dict>(c,'/api/v1/plans',{method:'POST',body,idempotencyKey:makeIdempotencyKey('plan')})
export const getPlan=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/plans/${encodeURIComponent(id)}`,{signal})
export const getPlanTasks=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/plans/${encodeURIComponent(id)}/tasks`,{signal})
