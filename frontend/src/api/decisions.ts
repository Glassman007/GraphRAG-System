import { apiRequest, queryString } from './client'
import type { ApiConfig, Dict, PageResponse } from './types'
export const listDecisions=(c:ApiConfig,p:Dict={},signal?:AbortSignal)=>apiRequest<PageResponse>(c,`/api/v1/decisions${queryString(p)}`,{signal})
export const getDecision=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/decisions/${encodeURIComponent(id)}`,{signal})
export const getDecisionGenealogy=(c:ApiConfig,id:string,asOf?:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/decisions/${encodeURIComponent(id)}/genealogy${queryString({as_of:asOf})}`,{signal})
export const getDecisionEvidence=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/decisions/${encodeURIComponent(id)}/evidence`,{signal})
export const getDecisionOutcomes=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/decisions/${encodeURIComponent(id)}/outcomes`,{signal})
