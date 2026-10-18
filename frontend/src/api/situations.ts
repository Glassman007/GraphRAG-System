import { apiRequest, makeIdempotencyKey, queryString } from './client'
import type { ApiConfig, Dict, PageResponse } from './types'
export const listSituations=(c:ApiConfig,p:Dict={},signal?:AbortSignal)=>apiRequest<PageResponse>(c,`/api/v1/situations${queryString(p)}`,{signal})
export const getSituation=(c:ApiConfig,id:string,asOf?:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/situations/${encodeURIComponent(id)}${queryString({as_of:asOf})}`,{signal})
export const getSituationContext=(c:ApiConfig,id:string,asOf?:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/situations/${encodeURIComponent(id)}/context${queryString({as_of:asOf})}`,{signal})
export const getSituationTimeline=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/situations/${encodeURIComponent(id)}/timeline`,{signal})
export const getSituationClaims=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/situations/${encodeURIComponent(id)}/claims`,{signal})
export const getSituationEvidence=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/situations/${encodeURIComponent(id)}/evidence`,{signal})
export const getSituationTasks=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/situations/${encodeURIComponent(id)}/tasks`,{signal})
export const investigateSituation=(c:ApiConfig,id:string,body:Dict)=>apiRequest<Dict>(c,`/api/v1/situations/${encodeURIComponent(id)}/investigate`,{method:'POST',body:{...body,situation_id:id},idempotencyKey:makeIdempotencyKey('investigation')})
export const listSituationStatuses=(c:ApiConfig,signal?:AbortSignal)=>apiRequest<{items:string[]}>(c,'/api/v1/situations/statuses',{signal})
