import { apiRequest, queryString } from './client'
import type { ApiConfig, Dict } from './types'
const get=(c:ApiConfig,path:string,p:Dict={},signal?:AbortSignal)=>apiRequest<Dict>(c,`${path}${queryString(p)}`,{signal})
export const getRisks=(c:ApiConfig,p:Dict={},s?:AbortSignal)=>get(c,'/api/v1/risks',p,s)
export const getBusFactor=(c:ApiConfig,p:Dict={},s?:AbortSignal)=>get(c,'/api/v1/risks/bus-factor',p,s)
export const getBottlenecks=(c:ApiConfig,p:Dict={},s?:AbortSignal)=>get(c,'/api/v1/risks/bottlenecks',p,s)
export const getBridges=(c:ApiConfig,p:Dict={},s?:AbortSignal)=>get(c,'/api/v1/risks/bridges',p,s)
export const getCollisions=(c:ApiConfig,p:Dict={},s?:AbortSignal)=>get(c,'/api/v1/risks/initiative-collisions',p,s)
export const getOwnershipGaps=(c:ApiConfig,p:Dict={},s?:AbortSignal)=>get(c,'/api/v1/risks/ownership-gaps',p,s)
export const getCommitments=(c:ApiConfig,p:Dict={},s?:AbortSignal)=>get(c,'/api/v1/risks/commitments',p,s)
