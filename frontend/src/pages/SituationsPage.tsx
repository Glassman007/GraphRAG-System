import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { listSituations,listSituationStatuses } from '../api/situations'
import { DataTable } from '../components/DataTable'
import { ErrorPanel, EmptyState, LoadingPanel } from '../components/AsyncState'
import { Pagination } from '../components/Pagination'
import { StatusBadge } from '../components/StatusBadge'
import { AsOfPicker } from '../components/AsOfPicker'
import { FilterBar } from '../components/FilterBar'
import { useDebounced } from '../components/EntityPicker'
import { displayName, presentStatus } from '../presentation'

export function SituationsPage(){
  const {config,hasPermission}=useAuth()
  const [sp,setSp]=useSearchParams()
  const status=sp.get('status')||'', asOf=sp.get('as_of')||''
  const [text,setText]=useState(sp.get('q')||'')
  const [cursor,setCursor]=useState<string|undefined>()
  const search=useDebounced(text.trim(),320)
  useEffect(()=>{setCursor(undefined)},[status,asOf,search])
  const statuses=useQuery({queryKey:['situation-statuses',config.tenantId],queryFn:({signal})=>listSituationStatuses(config,signal),retry:false})
  const q=useQuery({queryKey:['situations',config.tenantId,status,asOf,search,cursor],queryFn:({signal})=>listSituations(config,{limit:50,cursor,status:status||undefined,q:search||undefined,as_of:asOf||undefined},signal)})
  const update=(field:string,value:string)=>setSp(prev=>{const p=new URLSearchParams(prev);value?p.set(field,value):p.delete(field);p.delete('cursor');return p})
  const options=Array.from(new Set([...(statuses.data?.items||[]),...(status?[status]:[])])).sort()
  const rows=q.data?.items||[]
  return <section><div className="page-header"><div><h2>Situations</h2><p>Search incidents by title, description, related system, or canonical ID.</p></div>{hasPermission('MANAGE_INGESTION')&&<Link to="/sources">Source health</Link>}</div>
    <FilterBar><label className="field"><span>Search situations</span><input aria-label="Search situations" value={text} onChange={e=>setText(e.target.value)} placeholder="e.g. dispatch outage or Route DB" /></label><label className="field"><span>Status</span><select aria-label="Status" value={status} onChange={e=>update('status',e.target.value)}><option value="">All statuses</option>{options.map(s=><option key={s} value={s}>{presentStatus(s)}</option>)}</select></label><AsOfPicker value={asOf} onChange={v=>update('as_of',v)}/><button type="button" onClick={()=>{setText('');setCursor(undefined);setSp({})}}>Clear filters</button></FilterBar>
    {q.isFetching&&!q.data?<LoadingPanel label="Searching organizational incidents…"/>:q.error?<ErrorPanel error={q.error}/>:rows.length?<><DataTable rows={rows} rowKey={(r:any)=>r.id} columns={[{key:'name',header:'Situation',render:(r:any)=><div><Link to={`/situations/${encodeURIComponent(r.id)}`}><strong>{displayName(r)}</strong></Link><div className="technical-secondary">{r.id}</div>{r.description&&<p className="gh-row-description">{r.description}</p>}</div>},{key:'status',header:'Status',render:(r:any)=><StatusBadge value={r.status}/>},{key:'severity',header:'Severity',render:(r:any)=>r.severity||'Not specified'},{key:'time',header:'Occurred',render:(r:any)=>r.occurred_at||r.created_at||'Not recorded'}]}/><Pagination hasMore={q.data?.has_more} nextCursor={q.data?.next_cursor} onNext={setCursor} onReset={()=>setCursor(undefined)}/></>:<EmptyState title={search||status?'No situations match your search':'No situations have been recorded'} detail={search||status?'Try another name, system, ID or status. The graph has no matching records.':'The current tenant graph has no incident entities. Check your seeded data or source ingestion.'}/>}
    {q.isFetching&&q.data&&<span className="technical-secondary" role="status">Refreshing results…</span>}
  </section>
}
