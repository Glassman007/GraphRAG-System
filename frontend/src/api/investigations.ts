import { apiRequest, makeIdempotencyKey } from './client'
import type { ApiConfig, Dict } from './types'
export const createInvestigation=(c:ApiConfig,body:Dict)=>apiRequest<Dict>(c,'/api/v1/investigations',{method:'POST',body,idempotencyKey:makeIdempotencyKey('investigation')})
export const getInvestigation=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/investigations/${encodeURIComponent(id)}`,{signal})
export const getInvestigationFindings=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/investigations/${encodeURIComponent(id)}/findings`,{signal})
export const getInvestigationEvidence=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/investigations/${encodeURIComponent(id)}/evidence`,{signal})
export const getInvestigationRetrievals=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/investigations/${encodeURIComponent(id)}/retrievals`,{signal})
export const retrieveInvestigation=(c:ApiConfig,id:string,body:Dict)=>apiRequest<Dict>(c,`/api/v1/investigations/${encodeURIComponent(id)}/retrieve`,{method:'POST',body})
export const closeInvestigation=(c:ApiConfig,id:string)=>apiRequest<Dict>(c,`/api/v1/investigations/${encodeURIComponent(id)}/close`,{method:'POST',body:{}})
