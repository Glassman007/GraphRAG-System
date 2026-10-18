import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../api/client'
import { getEntity, getEntityProvenance, getNeighbors, getEntityHistory } from '../api/entities'
import { getSituationContext,getSituationTimeline,getSituationEvidence,getSituationTasks,getSituationClaims } from '../api/situations'
import { getTaskInsights } from '../api/workInsights'
import { getActionGovernance,getActionAttempts } from '../api/actions'
import { GraphView } from '../components/GraphView'
import { EntityPicker } from '../components/EntityPicker'
import { relationshipsToGraph } from '../graph/adapters'
import { TechnicalDetails } from '../components/TechnicalDetails'
import { displayName,presentRelationship } from '../presentation'
import { contextComparison } from './demoModel'
import type { Scenario } from './demoModel'
import type { ApiConfig } from '../api/types'

type Entry={name:string;status:'OK'|'ERROR'|'SKIPPED';response?:any;error?:string;requestId?:string;endpoint:string}
type Trace={root:string;collectedAt:string;entries:Entry[]}
const rows=(v:any)=>Array.isArray(v)?v:Array.isArray(v?.items)?v.items:[]
async function probe(name:string,endpoint:string,call:()=>Promise<any>):Promise<Entry>{
 try{return {name,endpoint,status:'OK',response:await call()}}
 catch(e){return {name,endpoint,status:'ERROR',error:e instanceof Error?e.message:String(e),requestId:e instanceof ApiError?e.requestId:undefined}}
}
export async function collectDemoTrace(c:ApiConfig,s:Scenario,permission:(p:string)=>boolean,signal?:AbortSignal):Promise<Trace>{
 const root=s.entry_ids[0],isIncident=root.startsWith('INC-'),isTask=root.startsWith('TASK-'),isAction=root.startsWith('ACT-')
 const required:{name:string;endpoint:string;permission:string;call:()=>Promise<any>}[]=[
  {name:'Root record',endpoint:`/api/v1/entities/${encodeURIComponent(root)}`,permission:'READ_GRAPH',call:()=>getEntity(c,root,undefined,signal)},
  {name:'Connected relationships',endpoint:`/api/v1/entities/${encodeURIComponent(root)}/neighbors`,permission:'READ_GRAPH',call:()=>getNeighbors(c,root,{limit:100},signal)},
  {name:'Historical relationships',endpoint:`/api/v1/entities/${encodeURIComponent(root)}/history`,permission:'READ_GRAPH',call:()=>getEntityHistory(c,root,signal)},
  {name:'Provenance',endpoint:`/api/v1/entities/${encodeURIComponent(root)}/provenance`,permission:'READ_EVIDENCE',call:()=>getEntityProvenance(c,root,signal)},
 ]
 if(isIncident)required.push(
  {name:'Incident context',endpoint:`/api/v1/situations/${encodeURIComponent(root)}/context`,permission:'READ_GRAPH',call:()=>getSituationContext(c,root,undefined,signal)},
  {name:'Incident timeline',endpoint:`/api/v1/situations/${encodeURIComponent(root)}/timeline`,permission:'READ_GRAPH',call:()=>getSituationTimeline(c,root,signal)},
  {name:'Claims',endpoint:`/api/v1/situations/${encodeURIComponent(root)}/claims`,permission:'READ_GRAPH',call:()=>getSituationClaims(c,root,signal)},
  {name:'Evidence',endpoint:`/api/v1/situations/${encodeURIComponent(root)}/evidence`,permission:'READ_EVIDENCE',call:()=>getSituationEvidence(c,root,signal)},
  {name:'Related tasks',endpoint:`/api/v1/situations/${encodeURIComponent(root)}/tasks`,permission:'READ_GRAPH',call:()=>getSituationTasks(c,root,signal)}
 )
 if(isTask)required.push({name:'Task execution, findings and checkpoints',endpoint:`/api/v1/work/tasks/${encodeURIComponent(root)}/insights`,permission:'READ_GRAPH',call:()=>getTaskInsights(c,root,signal)})
 if(isAction)required.push(
  {name:'Governance and approval gates',endpoint:`/api/v1/actions/${encodeURIComponent(root)}/governance`,permission:'READ_GRAPH',call:()=>getActionGovernance(c,root,signal)},
  {name:'Action attempts',endpoint:`/api/v1/actions/${encodeURIComponent(root)}/attempts`,permission:'READ_GRAPH',call:()=>getActionAttempts(c,root,signal)}
 )
 const entries=await Promise.all(required.map(x=>permission(x.permission)?probe(x.name,x.endpoint,x.call):Promise.resolve({name:x.name,endpoint:x.endpoint,status:'SKIPPED' as const,error:`Missing ${x.permission} permission` })))
 return {root,collectedAt:new Date().toISOString(),entries}
}
function EventList({title,values}:{title:string;values:any[]}){
 return <section className="panel"><h4>{title} <small>({values.length})</small></h4>{values.length?values.slice(0,30).map((v:any,i)=><div className="gh-demo-event" key={v.id||i}><strong>{displayName(v.entity||v.event||v)}</strong><div className="technical-secondary">{v.status||v.type||v.event_type||'Recorded'} · {v.occurred_at||v.created_at||v.observed_at||'Time not recorded'}</div>{(v.statement||v.description||v.state_summary)&&<p>{v.statement||v.description||v.state_summary}</p>}{v.id&&<Link to={`/entities/${encodeURIComponent(v.id)}`}>Inspect source {v.id}</Link>}</div>):<p className="muted">No records returned for this category. This is not evidence that the activity occurred.</p>}{values.length>30&&<p className="muted">Showing first 30 records. Open the linked module for more.</p>}</section>
}
export function LiveTracePanel({scenario}:{scenario:Scenario}){
 const {config,hasPermission}=useAuth(),[enabled,setEnabled]=useState(false)
 const [taskId,setTaskId]=useState(scenario.entry_ids.concat(scenario.focus_ids).find(x=>x.startsWith('TASK-'))||'')
 const [actionId,setActionId]=useState(scenario.entry_ids.concat(scenario.focus_ids).find(x=>x.startsWith('ACT-'))||'')
 const taskQuery=useQuery({queryKey:['demo-task-insights',config.tenantId,taskId],queryFn:({signal})=>getTaskInsights(config,taskId,signal),enabled:enabled&&!!taskId&&hasPermission('READ_GRAPH'),retry:false})
 const approvalQuery=useQuery({queryKey:['demo-action-governance',config.tenantId,actionId],queryFn:({signal})=>getActionGovernance(config,actionId,signal),enabled:enabled&&!!actionId&&hasPermission('READ_GRAPH'),retry:false})
 const attemptQuery=useQuery({queryKey:['demo-action-attempts',config.tenantId,actionId],queryFn:({signal})=>getActionAttempts(config,actionId,signal),enabled:enabled&&!!actionId&&hasPermission('READ_GRAPH'),retry:false})
 const q=useQuery({queryKey:['demo-live-trace',config.baseUrl,config.tenantId,scenario.scenario_id,enabled],queryFn:({signal})=>collectDemoTrace(config,scenario,hasPermission,signal),enabled,retry:false,staleTime:0})
 const entries=q.data?.entries||[]
 const get=(name:string)=>entries.find(x=>x.name===name&&x.status==='OK')?.response
 const root=get('Root record'),neighbors=get('Connected relationships')
 const contrast=root&&neighbors?contextComparison(root,neighbors):null
 const graph=relationshipsToGraph(rows(neighbors));const context=get('Incident context');const task=taskQuery.data||get('Task execution, findings and checkpoints')
 const events=rows(get('Incident timeline')?.events)
 const evidence=rows(get('Evidence'))
 const claims=rows(get('Claims'))
 const tasks=rows(get('Related tasks'))
 const attempts=rows(get('Action attempts'))
 const provenance=get('Provenance')
 const errors=entries.filter(x=>x.status!=='OK')
 const historical=rows(get('Historical relationships')?.relationship_history).filter((r:any)=>r.properties?.valid_until)
 const contextLayers=[
  {name:'Graph relationships',value:contrast?.relationships,detail:'Direct, bounded connections to other records'},
  {name:'Historical relationships',value:get('Historical relationships')?historical.length:undefined,detail:'Ended or superseded links in recorded history'},
  {name:'Evidence records',value:get('Evidence')?evidence.length:undefined,detail:'Cited incident evidence; not automatically a true claim'},
  {name:'Persisted checkpoints',value:task?rows(task.checkpoints).length:undefined,detail:'Graph-backed state, not LLM conversational memory'},
  {name:'Coordination executions / handoffs',value:task?rows(task.executions).length+rows(task.handoffs).length:undefined,detail:'Recorded work transitions; not autonomous execution proof'},
 ]
 return <section className="gh-demo-trace"><div className="page-header"><div><h3>Live evidence and execution trace</h3><p>Read-only requests to your current tenant graph. No generated or simulated success events.</p></div><button className="primary" onClick={()=>{setEnabled(true);if(enabled)void q.refetch()}} disabled={q.isFetching||!hasPermission('READ_GRAPH')}>{q.isFetching?'Collecting…':enabled?'Refresh live trace':'Collect live trace'}</button></div>
 {!hasPermission('READ_GRAPH')&&<p role="alert">Your session lacks graph read permission.</p>}
 {!enabled&&<p className="notice">Select “Collect live trace” to query the authenticated backend. Synthetic source records remain labeled synthetic. Nothing is executed by this control.</p>}
 {q.isError&&<p role="alert">Live trace failed: {String(q.error)}</p>}
 {q.data&&<><section className="panel"><h4>Inspect recorded task / action traces</h4><p>Choose a connected task or governed action by name. This makes additional read-only API requests. Empty records do not imply a successful run.</p><div className="grid-2"><EntityPicker label="Task to trace" kind="Task" value={taskId} onChange={setTaskId}/><EntityPicker label="Action to trace" kind="Action" value={actionId} onChange={setActionId}/></div>{taskQuery.isFetching&&<p role="status">Loading task state…</p>}{approvalQuery.isFetching&&<p role="status">Loading action governance…</p>}{taskQuery.error&&<p role="alert">Task trace unavailable: {String(taskQuery.error)}</p>}{approvalQuery.error&&<p role="alert">Action governance unavailable: {String(approvalQuery.error)}</p>}{attemptQuery.error&&<p role="alert">Action attempts unavailable: {String(attemptQuery.error)}</p>}</section><div className="panel"><p><strong>Root:</strong> {contrast?.entity||scenario.entry_ids[0]} · Collected {q.data.collectedAt}</p><div className="gh-demo-metrics"><div><b>{entries.filter(x=>x.status==='OK').length}</b><span>API reads succeeded</span></div><div><b>{errors.length}</b><span>Skipped / failed</span></div><div><b>{contrast?.relationships??'—'}</b><span>Recorded relationships</span></div></div>{errors.map(x=><p key={x.name} role="status"><strong>{x.name} ({x.status}):</strong> {x.error||'Unavailable'} {x.requestId&&`· Request ${x.requestId}`}</p>)}</div>
 <div className="grid-2"><section className="panel"><h3>Isolated record context</h3><p>Starting from this record alone, with relationship and evidence traversal excluded.</p><b>{root?displayName(root):'Root unavailable'}</b><p>{root?.description||root?.summary||'No record description returned'}</p><span className="technical-secondary">One root record · This is a context-ablation display, not a measured AI accuracy benchmark.</span></section><section className="panel"><h3>Connected graph context</h3><p>Same root plus the live, bounded neighborhood returned by the backend.</p><div className="gh-demo-metrics"><div><b>{contrast?.related??'—'}</b><span>Distinct connected entities</span></div><div><b>{contrast?.relationships??'—'}</b><span>Relationship records</span></div></div><p>{contrast?.relationshipTypes.join(', ')||'No relationship types returned'}</p><span className="technical-secondary">This compares available context, not answer quality, execution speed or model accuracy.</span></section></div>
 <section className="panel"><h3>Context-layer ablation (record coverage)</h3><p>Suppressing each layer produces an isolated view with zero records from that layer. Including it exposes the bounded live records shown here. This does not measure model accuracy, reasoning quality or business outcomes.</p><div className="gh-demo-table-scroll"><table className="gh-demo-matrix"><thead><tr><th>Context layer</th><th>Without layer</th><th>With layer (observed)</th><th>Meaning</th></tr></thead><tbody>{contextLayers.map(l=><tr key={l.name}><td>{l.name}</td><td>Hidden in isolated view</td><td>{l.value===undefined?'Not inspected / unavailable':`${l.value} recorded`}</td><td>{l.detail}</td></tr>)}</tbody></table></div></section>
 {graph.edges.length>0&&<section className="panel"><h3>Traversed graph neighborhood</h3><GraphView graph={graph} height={330}/><div className="gh-demo-event-list">{graph.edges.slice(0,12).map(x=><p key={x.id}>{presentRelationship(x.type,x.source,x.target).phrase}</p>)}</div></section>}
 <div className="grid-2"><EventList title="Chronological events" values={events}/><EventList title="Evidence and sources" values={[...evidence,...(context?.evidence||[])]}/><EventList title="Claims and decisions about the incident" values={[...claims,...(context?.claims||[])]}/><EventList title="Task transitions and work" values={[...tasks,...(context?.tasks||[]),...rows(task?.executions)]}/><EventList title="Checkpoints and recorded agent findings" values={[...rows(task?.checkpoints),...rows(task?.findings)]}/><EventList title="Governance and execution attempts" values={[...attempts,...rows(attemptQuery.data),...(approvalQuery.data?[approvalQuery.data]:[]),...(get('Governance and approval gates')?[get('Governance and approval gates')]:[])]}/></div>
 {provenance&&<section className="panel"><h3>Root provenance</h3><p>Recorded origin metadata is available. Inspect the technical payload for exact source references and timestamps.</p><TechnicalDetails><pre>{JSON.stringify(provenance,null,2)}</pre></TechnicalDetails></section>}
 <TechnicalDetails title="Raw read-only trace and API results"><pre>{JSON.stringify({root_trace:q.data,task:taskQuery.data,governance:approvalQuery.data,action_attempts:attemptQuery.data},null,2)}</pre></TechnicalDetails>
 </>}
 </section>
}
