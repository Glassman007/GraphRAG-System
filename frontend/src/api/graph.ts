import { apiRequest, queryString } from './client'
import type { ApiConfig, Dict } from './types'
export const findPaths=(c:ApiConfig,params:Dict,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/paths${queryString(params)}`,{signal})
