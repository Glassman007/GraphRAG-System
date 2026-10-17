import { apiRequest } from './client'
import type { ApiConfig, Dict, SessionResponse } from './types'
export const getCapabilities = (c: ApiConfig, signal?: AbortSignal) => apiRequest<Dict>(c, '/api/v1/capabilities', { signal })
export const getReady = (c: ApiConfig, signal?: AbortSignal) => apiRequest<Dict>(c, '/api/v1/ready', { signal })
export const getSession = (c: ApiConfig, signal?: AbortSignal) => apiRequest<SessionResponse>(c, '/api/v1/session', { signal })
