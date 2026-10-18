import { apiRequest, queryString } from './client'
import type { ApiConfig, Dict, PageResponse } from './types'
export const listClaims=(c:ApiConfig,p:Dict={},signal?:AbortSignal)=>apiRequest<PageResponse>(c,`/api/v1/claims${queryString(p)}`,{signal})
export const getClaim=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/claims/${encodeURIComponent(id)}`,{signal})
export const getClaimEvidence=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/claims/${encodeURIComponent(id)}/evidence`,{signal})
export const getClaimConflicts=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/claims/${encodeURIComponent(id)}/conflicts`,{signal})
export const getClaimLineage=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/claims/${encodeURIComponent(id)}/lineage`,{signal})
export const revalidateClaim=(c:ApiConfig,id:string,evidenceId:string)=>apiRequest<Dict>(c,`/api/v1/claims/${encodeURIComponent(id)}/revalidate`,{method:'POST',body:{evidence_id:evidenceId}})
export const resolveConflict=(c:ApiConfig,entityId:string,asOf?:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/conflicts/${encodeURIComponent(entityId)}/resolve${queryString({as_of:asOf})}`,{signal})
