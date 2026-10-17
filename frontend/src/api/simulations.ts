import { apiRequest } from './client'
import type { ApiConfig, Dict } from './types'
export const runCounterfactual=(c:ApiConfig,body:Dict)=>apiRequest<Dict>(c,'/api/v1/simulations/counterfactual',{method:'POST',body})
export const runBusFactor=(c:ApiConfig,actorIds:string[],asOf?:string)=>apiRequest<Dict>(c,'/api/v1/simulations/bus-factor',{method:'POST',body:{actor_ids:actorIds,as_of:asOf}})
export const getSimulation=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/simulations/${encodeURIComponent(id)}`,{signal})
