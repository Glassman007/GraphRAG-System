import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { listSituations } from '../api/situations'
import { DataTable } from '../components/DataTable'
import { ErrorPanel, LoadingPanel } from '../components/AsyncState'
import { Pagination } from '../components/Pagination'
import { StatusBadge } from '../components/StatusBadge'
import { AsOfPicker } from '../components/AsOfPicker'
import { FilterBar } from '../components/FilterBar'

export function SituationsPage(){
  const {config}=useAuth(); const [sp,setSp]=useSearchParams(); const [cursor,setCursor]=useState<string|undefined>(); const status=sp.get('status')||''; const asOf=sp.get('as_of')||''
  const q=useQuery({queryKey:['situations',status,asOf,cursor],queryFn:({signal})=>listSituations(config,{limit:50,cursor,status:status||undefined,as_of:asOf||undefined},signal)})
  if(q.isLoading)return <LoadingPanel label="Loading situations…"/>; if(q.error)return <ErrorPanel error={q.error}/>
  const rows=q.data?.items||[]
  return <section><div className="page-header"><div><h2>Situations</h2><p>Operational incidents and situations requiring reasoning.</p></div></div><FilterBar><label className="field"><span>Status</span><input value={status} onChange={e=>setSp(prev=>{const n=new URLSearchParams(prev); e.target.value?n.set('status',e.target.value):n.delete('status'); return n})}/></label><AsOfPicker value={asOf} onChange={v=>setSp(prev=>{const n=new URLSearchParams(prev); v?n.set('as_of',v):n.delete('as_of'); return n})}/></FilterBar><DataTable rows={rows} rowKey={(r:any)=>r.id} columns={[{key:'id',header:'ID',render:(r:any)=><Link to={`/situations/${r.id}`}>{r.id}</Link>},{key:'name',header:'Name',render:(r:any)=>r.name||r.title||'—'},{key:'status',header:'Status',render:(r:any)=><StatusBadge value={r.status}/>},{key:'severity',header:'Severity',render:(r:any)=>r.severity||'—'}]}/><Pagination hasMore={q.data?.has_more} nextCursor={q.data?.next_cursor} onNext={setCursor} onReset={()=>setCursor(undefined)}/></section>
}
