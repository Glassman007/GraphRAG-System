export type Dict = Record<string, any>

export interface PageResponse<T = Dict> {
  items: T[]
  next_cursor?: string | null
  has_more: boolean
  limit: number
}

export interface ApiErrorBody {
  code: string
  message: string
  details?: unknown
  request_id?: string
}

export interface SessionResponse {
  subject: string
  tenant_id: string
  roles: string[]
  permissions: string[]
}

export interface ApiConfig {
  baseUrl: string
  token: string
  tenantId: string
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  idempotencyKey?: string
  signal?: AbortSignal
}
