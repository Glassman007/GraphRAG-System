import {useState} from 'react'
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query'
import {useAuth} from '../auth/AuthContext'
import {apiRequest} from '../api/client'
import {useAsteriaPanelScope,propagationExplanation,isProcessableChangeStatus} from './asteriaPanelScope'
import {ErrorPanel} from '../components/AsyncState'

type MemoryImpact = {memory_id:string;decision:string;subject_id:string}
type RunImpact = {run_id:string;affected_task_ids:string[];status:string;requires_model_consent:boolean}
type Notice = {type:string;event_id:string;message:string}
type ChangeEvent = {id:string;status:string;confidence:string;occurred_at?:string;source_id?:string;
 changed_ids?:string[];changes?:unknown[];memory_impacts?:MemoryImpact[];workflow_impacts?:RunImpact[];
 notifications?:Notice[];attempts?:number;error?:string;legacy_impacts?:{entity_id:string;action:string;trigger_id:string}[]}
type Changes = {items:ChangeEvent[];count:number}
export function ReactiveLearningPanel(){
 const {config,hasPermission}=useAuth()
 const {scopedConfig,registry:brains,graphAvailable,graphId}=useAsteriaPanelScope(config)
 const cache=useQueryClient()
 const [details,setDetails]=useState<string|null>(null)
 const key=['reactive-learning',config.baseUrl,config.tenantId,graphId]
 const changes=useQuery({queryKey:key,queryFn:()=>apiRequest<Changes>(scopedConfig,'/api/v1/agent-runtime/reactive/events?limit=30'),enabled:graphAvailable,refetchInterval:graphAvailable?20000:false,retry:false})
 const hasPending=Boolean(changes.data?.items.some(event=>isProcessableChangeStatus(event.status)))
 const process=useMutation({mutationFn:()=>apiRequest(scopedConfig,'/api/v1/agent-runtime/reactive/process?limit=12',{method:'POST'}),
  onSuccess:()=>cache.invalidateQueries({queryKey:key})})
 return <section className="panel" style={{display:'grid',gap:12}}>
  <div className="page-header"><div><div className="eyebrow">COMPONENT 4 / REACTIVE ORGANIZATIONAL LEARNING</div>
   <h3>What changed, and which conclusions need review?</h3>
   <p>Validated source changes are propagated into verified memory and dependent supervisor plans. This is evidence maintenance, not model retraining.</p></div>
   <span className="gh-demo-label">CHANGE PROPAGATION</span></div>
  <p className="technical-secondary">Source-change log scoped to <code>{graphId}</code> · Tenant <code>{config.tenantId}</code>. PROBABLE changes are not authoritative and cannot automatically invalidate findings or replan workflows.</p>
  {brains.error&&<ErrorPanel error={brains.error}/>}
  {!brains.isLoading&&!graphAvailable&&<p role="alert">Asteria graph is not available. Change processing is disabled.</p>}
  <div className="toolbar"><button onClick={()=>changes.refetch()} disabled={!graphAvailable||changes.isFetching}>Refresh change timeline</button>
   {hasPermission('CREATE_INVESTIGATION')&&<button onClick={()=>process.mutate()} disabled={!graphAvailable||!hasPending||process.isPending}>{process.isPending?'Processing…':'Process queued events'}</button>}
   <span className="muted">Refresh every 20 seconds. Only queued events can be processed; existing NEEDS_REVIEW entries require authoritative evidence, not another retry.</span></div>
  {changes.error&&<ErrorPanel error={changes.error}/>}{process.error&&<ErrorPanel error={process.error}/>}
  {changes.isLoading&&<p className="muted">Checking durable event log…</p>}
  {changes.data&&<p className="muted">{changes.data.items.filter(e=>e.confidence==='CONFIRMED').length} confirmed changes · {changes.data.items.filter(e=>e.confidence!=='CONFIRMED').length} unconfirmed changes · {changes.data.items.filter(e=>isProcessableChangeStatus(e.status)).length} queued/retryable events</p>}
  {changes.data?.items.length===0&&<p className="muted">No reactive changes recorded. Ingest updated authoritative graph evidence to generate a change event; unchanged resyncs do not count.</p>}
  {changes.data?.items.map(e=><article className="gh-work-board" key={e.id} style={{padding:12,display:'grid',gap:7}}>
   <div className="toolbar"><strong>{e.confidence} · {e.status}</strong><code>{e.id}</code></div>
   <small>{e.occurred_at||'Time not available'} · Source {e.source_id||'not available'} · {e.changed_ids?.length||0} related entities</small>
   <p className="technical-secondary">{propagationExplanation(e)}</p>
   <div className="toolbar"><b>{e.memory_impacts?.length||0} memory reviews</b><b>{e.workflow_impacts?.length||0} impacted workflows</b><b>{e.legacy_impacts?.length||0} organization review targets</b><button onClick={()=>setDetails(details===e.id?null:e.id)}>{details===e.id?'Hide':'Inspect'} propagation</button></div>
   {details===e.id&&<div style={{display:'grid',gap:8}}>
    <p><strong>Changed:</strong> {(e.changed_ids||[]).map(id=><code key={id} style={{marginRight:10}}>{id}</code>)}</p>
    {e.legacy_impacts?.map((impact,i)=><p key={`${impact.entity_id}:${i}`}>Organizational review: <code>{impact.entity_id}</code> · {impact.action} (trigger {impact.trigger_id})</p>)}
    {e.memory_impacts?.map(m=><p key={m.memory_id}>Memory <code>{m.memory_id}</code>: {m.decision} · {m.subject_id}</p>)}
    {e.workflow_impacts?.map(r=><p key={r.run_id}>Run <code>{r.run_id}</code>: {r.status}; recheck tasks {r.affected_task_ids.join(', ')}. Fresh consent required before model re-execution.</p>)}
    {e.notifications?.map((n,i)=><p key={i}><strong>{n.type}:</strong> {n.message}</p>)}
    {e.error&&<p role="alert">Processing error: {e.error}. Retry limit applies.</p>}
   </div>}
  </article>)}
  <p className="technical-secondary">Automatic re-verification is restricted to source-checkable predicates. Unconfirmed changes never overwrite verified knowledge. Affected model tasks are queued for targeted resume, but sending organizational data to a model requires a newly authorized request. Business actions are never executed here.</p>
 </section>
}
