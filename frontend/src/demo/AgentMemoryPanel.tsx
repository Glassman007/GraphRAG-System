import {useState} from 'react'
import {useMutation} from '@tanstack/react-query'
import {useAuth} from '../auth/AuthContext'
import {apiRequest} from '../api/client'
import {getEntity} from '../api/entities'
import {useAsteriaPanelScope,hasCanonicalEntity} from './asteriaPanelScope'
import {ErrorPanel} from '../components/AsyncState'
import type {Scenario} from './demoModel'

type Memory = {id:string;subject_id:string;predicate:string;value:string;summary:string;citations:string[];source_tools:string[];derived_memory_ids?:string[];status:string;scope:string;origin_agent_id:string;origin_run_id:string;origin_task_id:string;verified_by:string;verified_at:string;valid_until?:string;created_at:string;relevance:number}
type Result = {items:Memory[];count:number;policy:string}

export function AgentMemoryPanel({scenario}:{scenario:Scenario}){
 const {config,hasPermission}=useAuth()
 const {scopedConfig,registry:brains,graphAvailable,graphId}=useAsteriaPanelScope(config)
 const [entity,setEntity]=useState(scenario.entry_ids[0]||'')
 const [query,setQuery]=useState('dependency evidence')
 const [reviewId,setReviewId]=useState('')
 const [reason,setReason]=useState('')
 const [reviewStatus,setReviewStatus]=useState('RECHECK_REQUIRED')
 const lookup=useMutation({mutationFn:async(entityOnly:boolean)=>{
  // An absent canonical entity is different from an empty verified-memory result.
  if(entity.trim()){
   const found=await getEntity(scopedConfig,entity.trim())
   if(!hasCanonicalEntity(found,entity.trim()))throw new Error('Entity not found in selected Asteria graph')
  }
  return apiRequest<Result>(scopedConfig,'/api/v1/agent-runtime/memory/search',{
   method:'POST',body:{entity_ids:entity.trim()?[entity.trim()]:[],query:entityOnly?'':query.trim(),limit:15}
  })
 }})
 const review=useMutation({mutationFn:()=>apiRequest(scopedConfig,`/api/v1/agent-runtime/memory/${encodeURIComponent(reviewId)}/validity`,{
  method:'POST',body:{status:reviewStatus,reason}
 }),onSuccess:()=>lookup.mutate(false)})
 return <section className="panel" style={{display:'grid',gap:12}}>
  <div className="page-header"><div><div className="eyebrow">COMPONENT 3 / PERSISTENT AGENT MEMORY</div><h3>Verified knowledge across sessions</h3><p>Only current, source-backed, independently verified findings are shared. Private working branches, unresolved conflicts and stale knowledge are excluded.</p></div><span className="gh-demo-label">CROSS-SESSION</span></div>
  <p className="technical-secondary">Verified shared memory in <code>{graphId}</code> · Tenant <code>{config.tenantId}</code>. Investigation reports and handoffs do not automatically become independently verified memory.</p>
  {brains.error&&<ErrorPanel error={brains.error}/>}
  {!brains.isLoading&&!graphAvailable&&<p role="alert">Asteria graph is not authorized/available for memory retrieval.</p>}
  <div className="toolbar"><label className="field"><span>Entity ID</span><input value={entity} onChange={e=>setEntity(e.target.value)} placeholder="SYS-AST-DISPATCH"/></label><label className="field"><span>Context keywords</span><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Route Database dependency"/></label></div>
  <div className="toolbar"><button className="primary" disabled={!graphAvailable||lookup.isPending||(!query.trim()&&!entity.trim())} onClick={()=>lookup.mutate(false)}>{lookup.isPending?'Checking memory…':'Search verified memory'}</button><button disabled={!graphAvailable||lookup.isPending||!entity.trim()} onClick={()=>lookup.mutate(true)}>Search entity (ignore keywords)</button><span className="muted">Only VERIFIED / SHARED / current records; maximum 15</span></div>
  {lookup.error&&<ErrorPanel error={lookup.error}/>}
  {lookup.data&&<><div className="eyebrow">{lookup.data.count} eligible memories · VERIFIED / SHARED</div>
   {lookup.data.items.length===0?<p className="muted">No eligible verified, shared memory matched this search. An investigation can complete successfully without producing reusable independently verified assertions. Try the entity-only search to remove the keyword filter; do not interpret this as missing graph evidence.</p>:<div style={{display:'grid',gap:10}}>{lookup.data.items.map(m=><article key={m.id} className="gh-work-board" style={{padding:14}}>
    <strong>{m.subject_id} · {m.predicate} → {m.value}</strong>
    <p>{m.summary}</p><small>Memory: {m.id} · {m.status} · Verified: {m.verified_at}</small>
    <p className="muted">Source: {m.origin_agent_id} ({m.origin_task_id}) · Independent check: {m.verified_by} · Tools: {m.source_tools.join(', ')||'reused verified memory'} · Run: {m.origin_run_id}</p>{Boolean(m.derived_memory_ids?.length)&&<p className="muted">Derived from verified memory: {m.derived_memory_ids?.join(', ')}</p>}
    <div className="toolbar">{m.citations.map(id=><code key={id}>{id}</code>)}</div>
    {hasPermission('CREATE_INVESTIGATION')&&<button onClick={()=>setReviewId(m.id)}>Review validity</button>}
   </article>)}</div>}</>}
  {reviewId&&<div className="gh-work-board" style={{display:'grid',gap:8,padding:14}}><h4>Record review: {reviewId}</h4><p className="muted">This operation withdraws the memory from shared retrieval; it never changes the canonical source graph.</p>
   <label className="field"><span>Review decision</span><select value={reviewStatus} onChange={e=>setReviewStatus(e.target.value)}><option value="RECHECK_REQUIRED">Require recheck</option><option value="SUPERSEDED">Superseded</option><option value="INVALIDATED">Invalidated</option></select></label>
   <label className="field"><span>Reason (minimum 10 characters)</span><textarea rows={2} value={reason} onChange={e=>setReason(e.target.value)}/></label>
   <div className="toolbar"><button disabled={!graphAvailable||reason.trim().length<10||review.isPending} onClick={()=>review.mutate()}>Confirm review</button><button onClick={()=>setReviewId('')}>Cancel</button></div>
   {review.error&&<ErrorPanel error={review.error}/>}
  </div>}
  <p className="technical-secondary">Memory is graph-persisted in a separate FalkorDB namespace. A verified record includes an origin agent, source citations, tool provenance and verifier; thirty-day verification freshness and present-day graph evidence checks apply. Memory never provides business-action authorization.</p>
 </section>
}
