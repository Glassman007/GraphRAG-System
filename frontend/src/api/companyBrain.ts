import { apiRequest, queryString } from './client'
import type { ApiConfig, Dict } from './types'
export const getExpertise=(c:ApiConfig,p:Dict={},signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/company-brain/expertise${queryString(p)}`,{signal})
