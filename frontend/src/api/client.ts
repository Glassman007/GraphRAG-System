import type { ApiConfig, ApiErrorBody, RequestOptions } from './types'

const STORAGE_KEY = 'graphhacks.phase12.api'

export class ApiError extends Error {
  status: number
  code: string
  details: unknown
  requestId?: string
  constructor(status: number, body: ApiErrorBody) {
    super(body.message || `Request failed (${status})`)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code || 'INTERNAL_ERROR'
    this.details = body.details
    this.requestId = body.request_id
  }
}

export function defaultConfig(): ApiConfig {
  const env = import.meta.env
  return {
    baseUrl: String(env.VITE_API_BASE_URL || '').replace(/\/$/, ''),
    token: String(env.VITE_TEST_TOKEN || ''),
    tenantId: String(env.VITE_TENANT_ID || 'northstar'),
  }
}

export function loadConfig(): ApiConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return { ...defaultConfig(), ...JSON.parse(raw) }
  } catch { /* ignore invalid local development state */ }
  return defaultConfig()
}

export function saveConfig(config: ApiConfig) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
}

export function makeIdempotencyKey(prefix = 'ui') {
  const random = typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`
  return `${prefix}-${random}`
}

export async function apiRequest<T>(config: ApiConfig, path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers || {})
  headers.set('Accept', 'application/json')
  headers.set('X-Tenant-ID', config.tenantId)
  if (config.graphId) headers.set('X-Company-Brain-ID', config.graphId)
  headers.set('X-Request-ID', `ui-${Date.now()}-${Math.random().toString(16).slice(2)}`)
  if (config.token) headers.set('Authorization', `Bearer ${config.token}`)
  if (options.body !== undefined) headers.set('Content-Type', 'application/json')
  if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey)
  const response = await fetch(`${config.baseUrl}${path}`, {
    ...options,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  })
  const text = await response.text()
  const payload = text ? JSON.parse(text) : null
  if (!response.ok) {
    const body: ApiErrorBody = payload?.error || { code: response.status === 401 ? 'UNAUTHORIZED' : 'INTERNAL_ERROR', message: payload?.detail || response.statusText, request_id: response.headers.get('X-Request-ID') || undefined }
    throw new ApiError(response.status, body)
  }
  return payload as T
}

export function queryString(params: Record<string, unknown>) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) value.forEach((item) => search.append(key, String(item)))
    else search.set(key, String(value))
  }
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ''
}
