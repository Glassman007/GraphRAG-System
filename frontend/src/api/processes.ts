import { apiRequest, queryString } from './client'
import type { ApiConfig, Dict } from './types'
export const getProcess=(c:ApiConfig,id:string,asOf?:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/processes/${encodeURIComponent(id)}${queryString({as_of:asOf})}`,{signal})
export const getProcessTimeline=(c:ApiConfig,id:string,asOf?:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/processes/${encodeURIComponent(id)}/timeline${queryString({as_of:asOf})}`,{signal})
export const getPolicyDrift=(c:ApiConfig,id:string,policyId:string,asOf?:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/processes/${encodeURIComponent(id)}/policy-drift${queryString({policy_id:policyId,as_of:asOf})}`,{signal})
