import { ApiError } from '../api/client'

export function LoadingPanel({ label = 'Loading…' }: { label?: string }) {
  return <div className="panel state-panel" role="status">{label}</div>
}
export function EmptyState({ title = 'No data', detail }: { title?: string; detail?: string }) {
  return <div className="panel state-panel"><strong>{title}</strong>{detail && <div className="muted">{detail}</div>}</div>
}
export function ErrorPanel({ error }: { error: unknown }) {
  const api = error instanceof ApiError ? error : null
  const code=api?.code||'ERROR'
  const meaning=api?.status===401?'The session is not authenticated. Check your bearer token in API config.':api?.status===403?'Your account does not have permission to access this information.':api?.status===404?'This record is not available in the current tenant or graph.':api?.status===503?'Graph data is temporarily unavailable. Check FastAPI and FalkorDB.':api?.status===422?'The submitted filters or identifiers were rejected. Check the selected values.':!api&&error instanceof TypeError?'The API could not be reached. Verify your network, backend process and API base URL.':''
  return <div className="panel error-panel" role="alert"><strong>{code}</strong><div>{api?.message||String(error)}</div>{meaning&&<p>{meaning}</p>}{api?.requestId&&<small>Request: {api.requestId}</small>}</div>
}
