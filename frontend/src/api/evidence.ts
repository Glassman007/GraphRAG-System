import { apiRequest, queryString } from './client'
import type { ApiConfig, Dict, PageResponse } from './types'
export const listEvidence=(c:ApiConfig,p:Dict={},signal?:AbortSignal)=>apiRequest<PageResponse>(c,`/api/v1/evidence${queryString(p)}`,{signal})
export const getEvidence=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/evidence/${encodeURIComponent(id)}`,{signal})
export const getEvidenceProvenance=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/evidence/${encodeURIComponent(id)}/provenance`,{signal})
export const getEvidenceArtifact=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/evidence/${encodeURIComponent(id)}/artifact`,{signal})
export const invalidateEvidence=(c:ApiConfig,id:string,reason:string)=>apiRequest<Dict>(c,`/api/v1/evidence/${encodeURIComponent(id)}/invalidate`,{method:'POST',body:{reason}})
export const getArtifactMetadata=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/artifacts/${encodeURIComponent(id)}/metadata`,{signal})
