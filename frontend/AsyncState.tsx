import { ApiError } from '../api/client'

export function LoadingPanel({ label = 'Loading…' }: { label?: string }) {
  return <div className="panel state-panel" role="status">{label}</div>
}
export function EmptyState({ title = 'No data', detail }: { title?: string; detail?: string }) {
  return <div className="panel state-panel"><strong>{title}</strong>{detail && <div className="muted">{detail}</div>}</div>
}
export function ErrorPanel({ error }: { error: unknown }) {
  const api = error instanceof ApiError ? error : null
  return <div className="panel error-panel" role="alert"><strong>{api?.code || 'ERROR'}</strong><div>{api?.message || String(error)}</div>{api?.requestId && <small>Request: {api.requestId}</small>}</div>
}
