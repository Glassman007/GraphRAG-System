import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { listSourceCatalog, removeCatalogSource, inspectSourceRemoval } from '../../api/sources'
import { ConfirmationDialog } from '../../components/ConfirmationDialog'
import { ErrorPanel, LoadingPanel } from '../../components/AsyncState'

export function SourcesPage() {
 const {config,hasPermission}=useAuth()
 const qc=useQueryClient()
 const [pendingRemoval,setPendingRemoval]=useState<{graph_id:string;source_id:string;display_name:string;managed:boolean}|null>(null)
 const impact=useQuery({
  queryKey:['source-removal-impact',config.tenantId,pendingRemoval?.graph_id,pendingRemoval?.source_id],
  queryFn:({signal})=>inspectSourceRemoval({...config,graphId:pendingRemoval!.graph_id},pendingRemoval!.source_id,signal),
  enabled:!!pendingRemoval,retry:false,
 })
 const removal=useMutation({
  mutationFn:({graph_id,source_id}:{graph_id:string;source_id:string})=>removeCatalogSource({...config,graphId:graph_id},source_id),
  onSuccess:()=>{setPendingRemoval(null);qc.invalidateQueries({queryKey:['source-catalog']});qc.invalidateQueries({queryKey:['workspace-source-catalog']});qc.invalidateQueries({queryKey:['sources']})},
 })
 const catalog=useQuery({queryKey:['source-catalog',config.baseUrl,config.tenantId],queryFn:({signal})=>listSourceCatalog(config,signal),retry:false})
 if(catalog.isLoading)return <LoadingPanel label="Loading Company Brain sources…"/>
 if(catalog.error)return <ErrorPanel error={catalog.error}/>
 const items=catalog.data?.items||[]
 const brains=(catalog.data?.brains||[]).filter((b:any)=>b.available)
 const managed=items.filter((x:any)=>x.managed)
 const fixture=items.filter((x:any)=>!x.managed)
 return <section>
  <div className="page-header"><div><h2>Sources</h2><p>Registered Company Brains and their connected or imported sources.</p></div><Link className="button-link" to="/sources/new">Add source</Link></div>
  <div className="summary-grid">
   <div className="metric"><strong>{brains.length}</strong><span>Company Brains</span></div>
   <div className="metric"><strong>{managed.length}</strong><span>Managed source configurations</span></div>
   <div className="metric"><strong>{fixture.length}</strong><span>Existing / seeded sources</span></div>
   <div className="metric"><strong>{items.length}</strong><span>Visible sources</span></div>
  </div>
  <p className="muted">Each card is a distinct source. Sources shown under the same Company Brain currently share graph storage; source-exclusive agent retrieval is not yet enforced. To isolate a source as its own Company Brain, it must be ingested or migrated into a dedicated graph.</p>
  {removal.error&&<p role="alert">Could not remove source: {String(removal.error)}</p>}
  {!brains.length&&<p role="alert">No registered Company Brains. Register a graph before connecting sources.</p>}
  {brains.map((brain:any)=>{const rows=items.filter((s:any)=>s.graph_id===brain.graph_id);return <section key={brain.graph_id} className="panel">
   <h3>{brain.display_name}</h3><p className="muted">{brain.graph_id} · {rows.length} sources</p>
   <p><Link to={`/agent-workspace?graph=${encodeURIComponent(brain.graph_id)}`}>Open in Agent Workspace →</Link></p>
   {rows.length===0?<p>No source records found in this graph.</p>:<div className="card-grid">{rows.map((s:any)=>
     <div className="panel source-card" key={s.source_id}>
      <h3>{s.display_name}</h3><p className="muted">{s.source_id}</p>
      <dl className="kv"><dt>Type</dt><dd>{s.connector_type}</dd><dt>Status</dt><dd>{s.status}</dd><dt>Origin</dt><dd>{s.managed?'Managed connector':s.fixture_pack?'Imported Asteria fixture':'Existing graph record'}</dd></dl>
      {s.managed?<Link to={`/sources/${encodeURIComponent(s.source_id)}?graph=${encodeURIComponent(brain.graph_id)}`}>Manage source →</Link>:<span className="badge">Imported provenance</span>}
      {hasPermission('MANAGE_INGESTION')&&<button type="button" className="danger" disabled={removal.isPending} onClick={()=>setPendingRemoval({graph_id:brain.graph_id,source_id:s.source_id,display_name:s.display_name,managed:!!s.managed})}>{s.managed?'Remove source':'Hide imported source'}</button>}
     </div>)}</div>}
  </section>})}
  <ConfirmationDialog open={!!pendingRemoval} title={pendingRemoval?.managed?'Remove managed source?':'Hide imported source?'} confirmLabel={pendingRemoval?.managed?'Remove connector':'Hide source'} onCancel={()=>setPendingRemoval(null)} onConfirm={()=>{if(pendingRemoval&&impact.data&&!removal.isPending)removal.mutate({graph_id:pendingRemoval.graph_id,source_id:pendingRemoval.source_id})}}>
   <p><strong>{pendingRemoval?.display_name}</strong> ({pendingRemoval?.source_id})</p>
   <p>{pendingRemoval?.managed?'This disables the connector configuration and removes stored credentials.':'This hides the imported fixture from the source catalog.'} Historical graph entities, ingestion evidence, and provenance are retained. This does not purge data from FalkorDB.</p>
   {impact.isLoading&&<p>Inspecting source lineage before removal…</p>}
   {impact.error&&<p role="alert">Could not assess source footprint. Removal is blocked.</p>}
   {impact.data&&<p>Source records: {String(impact.data.source_records)} · Canonical entities reached: {String(impact.data.canonical_entities_reached)} · Shared canonical entities: {String(impact.data.canonical_entities_also_referenced_by_other_source_records)} · Other sources in graph: {Number(impact.data.data_sources_in_selected_graph)-1}. <strong>Permanent data purge is NOT performed by this action.</strong></p>}
  </ConfirmationDialog>
 </section>
}
