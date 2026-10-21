import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { getSqlSchema, getSqlTable } from '../api/companyBrain'
import { GraphView } from '../components/GraphView'
import { ErrorPanel, EmptyState, LoadingPanel } from '../components/AsyncState'
import { sqlSchemaToGraph } from '../graph/adapters'

function githubEvidenceUrl(uri: unknown, line?: number): string | undefined {
  try {
    const url = new URL(String(uri))
    if (url.protocol !== 'https:' || url.hostname !== 'github.com' || !url.pathname.includes('/blob/')) return undefined
    if (line && Number.isInteger(line) && line > 0) url.hash = `L${line}`
    return url.toString()
  } catch { return undefined }
}

export function SqlSchemaPanel() {
  const { config, hasPermission } = useAuth()
  const [params, setParams] = useSearchParams()
  const sourceId = params.get('source_id') || ''
  const tableId = params.get('table') || ''
  const selectTable = (id: string) => setParams(previous => {
    const next = new URLSearchParams(previous)
    next.set('tab', 'sql-schema')
    next.set('table', id)
    return next
  })
  const schema = useQuery({
    queryKey: ['company-brain-sql-schema', config.tenantId, sourceId],
    queryFn: ({ signal }) => getSqlSchema(config, {source_id: sourceId || undefined}, signal),
  })
  const detail = useQuery({
    queryKey: ['company-brain-sql-table', config.tenantId, tableId],
    queryFn: ({ signal }) => getSqlTable(config, tableId, signal),
    enabled: Boolean(tableId),
  })
  const graph = useMemo(() => sqlSchemaToGraph(schema.data || {}), [schema.data])
  if (schema.isLoading) return <LoadingPanel label="Loading SQL schema graph…" />
  if (schema.error) return <ErrorPanel error={schema.error} />
  if (!graph.nodes.length) return <EmptyState title="No SQL schema in this Company Brain" detail="Sync a source containing a SQL file to populate the schema graph." />
  const selected = detail.data
  const source = selected?.source?.file || selected?.table
  const sourceUrl = githubEvidenceUrl(source?.source_uri)
  return <section>
    <p className="muted">Recorded foreign keys point from the referencing table to the referenced table. Select a table or connection to inspect its source.</p>
    {sourceId && <p className="muted">Showing source {sourceId}. <Link to="/company-brain?tab=sql-schema">Show all SQL schemas</Link></p>}
    {schema.data?.truncated && <p className="notice">Showing the first 200 tables. Select a source to narrow the graph.</p>}
    <div className="split">
      <div className="panel graph-panel"><GraphView graph={graph} height={530} onNode={node => selectTable(String(node.id))} onEdge={edge => selectTable(String(edge.source))} /></div>
      <aside className="panel" aria-label="SQL table details">
        {!tableId ? <EmptyState title="Select a table" detail="Click a table in the graph to inspect columns, constraints and evidence." /> : detail.isLoading ? <LoadingPanel /> : detail.error ? <ErrorPanel error={detail.error} /> : selected && <>
          <h3>{selected.table?.name}</h3>
          <p className="technical-secondary">{selected.table?.id}</p>
          <h4>Columns</h4>
          <ul>{(selected.columns || []).map((column: any) => <li key={column.id}><strong>{column.column_name}</strong> · {column.data_type}{column.primary_key ? ' · primary key' : ''}{column.not_null ? ' · required' : ''}</li>)}</ul>
          <h4>Constraints</h4>
          <ul>{(selected.constraints || []).map((constraint: any) => <li key={constraint.id}>
            <strong>{constraint.constraint_name || constraint.name}</strong> · {constraint.constraint_type}
            {constraint.columns?.length ? ` (${constraint.columns.join(', ')})` : ''}
            {constraint.referenced_table ? ` → ${constraint.referenced_table} (${(constraint.referenced_columns || []).join(', ')})` : ''}
            {githubEvidenceUrl(constraint.source_uri, constraint.ddl_line) && <a href={githubEvidenceUrl(constraint.source_uri, constraint.ddl_line)} target="_blank" rel="noopener noreferrer"> Source line {constraint.ddl_line}</a>}
          </li>)}</ul>
          <h4>Foreign-key connections</h4>
          <ul>{(selected.foreign_keys || []).map((fk: any) => {
            const outgoing = fk.source.id === tableId
            const other = outgoing ? fk.target : fk.source
            return <li key={fk.properties.edge_id || `${fk.source.id}:${fk.target.id}:${fk.properties.constraint_name}`}>
              <button className="link-button" onClick={() => selectTable(String(other.id))}>{outgoing ? 'To' : 'From'} {other.name}</button>
              {' · '}{fk.properties.constraint_name}{' · '}{(fk.properties.source_columns || []).join(', ')} → {(fk.properties.target_columns || []).join(', ')}
            </li>
          })}</ul>
          <h4>GitHub source evidence</h4>
          <dl className="kv">
            <dt>Repository</dt><dd>{source?.source_repository || '—'}</dd>
            <dt>SQL file</dt><dd>{source?.source_file_path || '—'}</dd>
            <dt>Commit</dt><dd><code>{source?.source_commit_sha || '—'}</code></dd>
            <dt>File SHA-256</dt><dd><code>{source?.source_file_hash || '—'}</code></dd>
          </dl>
          <div className="toolbar">
            {sourceUrl && <a href={sourceUrl} target="_blank" rel="noopener noreferrer">View SQL at this commit</a>}
            {hasPermission('MANAGE_INGESTION') && selected.table?.source_ref_id && <Link to={`/sources/${encodeURIComponent(selected.table.source_ref_id)}`}>View source</Link>}
            <Link to={`/entities/${encodeURIComponent(tableId)}?tab=provenance`}>Entity provenance</Link>
          </div>
        </>}
      </aside>
    </div>
  </section>
}
