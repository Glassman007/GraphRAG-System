import { apiRequest, queryString } from './client'
import type { ApiConfig, Dict } from './types'
export const searchEntities=(c:ApiConfig,q:string,limit=20,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/entities/search${queryString({q,limit})}`,{signal})
export const getEntity=(c:ApiConfig,id:string,asOf?:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/entities/${encodeURIComponent(id)}${queryString({as_of:asOf})}`,{signal})
export const getNeighbors=(c:ApiConfig,id:string,params:Dict={},signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/entities/${encodeURIComponent(id)}/neighbors${queryString(params)}`,{signal})
export const getRelationships=(c:ApiConfig,id:string,params:Dict={},signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/entities/${encodeURIComponent(id)}/relationships${queryString(params)}`,{signal})
export const getEntityProvenance=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/entities/${encodeURIComponent(id)}/provenance`,{signal})
export const getEntityHistory=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/entities/${encodeURIComponent(id)}/history`,{signal})
export const getEntityAt=(c:ApiConfig,id:string,asOf:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/history/entities/${encodeURIComponent(id)}/at${queryString({as_of:asOf})}`,{signal})
export const getBlastRadius=(c:ApiConfig,id:string,params:Dict={},signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/entities/${encodeURIComponent(id)}/blast-radius${queryString(params)}`,{signal})
