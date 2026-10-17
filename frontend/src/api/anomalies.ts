import { apiRequest } from './client'
import type { ApiConfig, Dict } from './types'
export const getAnomalies=(c:ApiConfig,signal?:AbortSignal)=>apiRequest<Dict>(c,'/api/v1/anomalies',{signal})
