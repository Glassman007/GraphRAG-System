import {useState} from 'react'
import {useMutation,useQuery} from '@tanstack/react-query'
import {Link} from 'react-router-dom'
import {useAuth} from '../auth/AuthContext'
import {apiRequest} from '../api/client'
import {ErrorPanel} from '../components/AsyncState'
import type {Scenario} from './demoModel'

type Finding = {summary:string;citations:string[];knowledge_gaps:string[];confidence:string;assertions?:{subject_id:string;predicate:string;value:string}[];risk:string;requires_human_review:boolean}
type Task = {id:string;objective:string;capability:string;depends_on:string[];status:string;agent_id?:string|null;attempts:number;result?:Finding|null;error?:string|null}
type Event = {index?:number;event_index?:number;kind:string;summary:string;task_id?:string;agent_id?:string;status:string;created_at:string}
type Run = {id:string;goal:string;status:string;answer:string;citations:string[];knowledge_gaps:string[];tasks:Task[];events:Event[];escalations:{reason:string;task_ids:string[];detail?:string}[];conflicts:{kind:string;tasks:string[]}[];tokens_used:number;error?:string|null}
type Registry = {agents:{id:string;capabilities:string[];tools:string[];capacity:number}[]}

export function SupervisorPanel({scenario}:{scenario:Scenario}){
 const {config,hasPermission}=useAuth()
 const [goal,setGoal]=useState(scenario.test_prompts[0]||`Investigate ${scenario.title}`)
 const [consent,setConsent]=useState(false)
 const [runId,setRunId]=useState('')
 const [loadId,setLoadId]=useState('')
 const [parallel,setParallel]=useState(3)
 const [showRegistry,setShowRegistry]=useState(false)
 const [resumeResult,setResumeResult]=useState<Run|null>(null)
 const registry=useQuery({queryKey:['supervisor-registry',config.tenantId],queryFn:({signal})=>apiRequest<Registry>(config,'/api/v1/agent-runtime/supervisor/registry',{signal}),retry:false})
 const create=useMutation({mutationFn:()=>apiRequest<Run>(config,'/api/v1/agent-runtime/supervisor/runs',{
   method:'POST',body:{goal,source_entity_id:scenario.entry_ids[0],allow_external_model:consent,max_parallel:parallel}
 })})
 const resume=useMutation({mutationFn:()=>apiRequest<Run>(config,`/api/v1/agent-runtime/supervisor/runs/${encodeURIComponent(loadId)}/resume?allow_external_model=true`,{method:'POST'}),onSuccess:data=>{setResumeResult(data);setRunId('')}})
 const reopened=useQuery({queryKey:['supervisor-run',config.tenantId,runId],enabled:!!runId,
   queryFn:({signal})=>apiRequest<Run>(config,`/api/v1/agent-runtime/supervisor/runs/${encodeURIComponent(runId)}`,{signal}),retry:false})
 const data=reopened.data||resumeResult||create.data
 return <section className="panel" style={{display:'grid',gap:12}}>
  <div className="page-header"><div><div className="eyebrow">COMPONENT 2 / SUPERVISOR &amp; TASK SCHEDULER</div><h3>Coordinate specialist agents</h3><p>Read-only multi-agent investigations with parallel research, verified handoffs, dependency scheduling and human escalation.</p></div><span className="gh-demo-label">MULTI-AGENT</span></div>
  <label className="field"><span>Investigation objective</span><textarea rows={3} maxLength={1500} value={goal} onChange={e=>setGoal(e.target.value)}/></label>
  <label className="field"><span>Maximum parallel specialists</span><select value={parallel} onChange={e=>setParallel(Number(e.target.value))}>{[1,2,3,4].map(x=><option key={x} value={x}>{x}</option>)}</select></label>
  <label style={{display:'flex',alignItems:'flex-start',gap:8}}><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/><span>I authorize sending selected organizational evidence and validated specialist handoffs to the configured external model. This does not approve external actions.</span></label>
  <div className="toolbar"><button className="primary" disabled={!hasPermission('CREATE_INVESTIGATION')||!consent||goal.trim().length<12||create.isPending} onClick={()=>{setRunId('');setResumeResult(null);create.mutate()}}>{create.isPending?'Coordinating specialists…':'Start multi-agent investigation'}</button><span className="muted">No external actions or autonomous approvals.</span></div>
  {create.error&&<ErrorPanel error={create.error}/>}
  {registry.error&&<ErrorPanel error={registry.error}/>}
  <details open={showRegistry} onToggle={e=>setShowRegistry(e.currentTarget.open)}><summary>Specialist registry ({registry.data?.agents.length??0})</summary>
   <div className="gh-demo-table-scroll"><table><thead><tr><th>Agent</th><th>Capabilities</th><th>Read-only tools</th></tr></thead><tbody>{(registry.data?.agents||[]).map(a=><tr key={a.id}><td>{a.id}</td><td>{a.capabilities.join(', ')}</td><td>{a.tools.join(', ')}</td></tr>)}</tbody></table></div>
  </details>
  <details><summary>Reopen persisted supervisor run</summary><label className="field"><span>Run ID</span><input placeholder="SRUN-…" value={loadId} onChange={e=>setLoadId(e.target.value.trim().toUpperCase())}/></label><button disabled={!/^SRUN-[0-9A-F]{32}$/.test(loadId)} onClick={()=>{setResumeResult(null);setRunId(loadId)}}>Load DAG and trace</button> <button disabled={!/^SRUN-[0-9A-F]{32}$/.test(loadId)||!consent||!hasPermission('CREATE_INVESTIGATION')||resume.isPending} onClick={()=>resume.mutate()}>Resume interrupted tasks</button>{reopened.error&&<ErrorPanel error={reopened.error}/>} {resume.error&&<ErrorPanel error={resume.error}/>}</details>
  {data&&<section className="gh-work-board" style={{display:'grid',gap:12}}>
   <div className="eyebrow">RUN {data.id} · {data.status}</div><div className="gh-demo-metrics"><div><b>{data.tasks?.length??0}</b><span>Decomposed tasks</span></div><div><b>{data.tasks?.filter(t=>t.status==='COMPLETED').length??0}</b><span>Completed tasks</span></div><div><b>{data.tokens_used??0}</b><span>Provider tokens / estimate</span></div></div>
   {data.error&&<p role="alert">{data.error}</p>}
   <h4>Task DAG and handoffs</h4><ol className="gh-demo-steps">{(data.tasks||[]).map(task=><li key={task.id}><div><b>{task.id} · {task.status}</b><p>{task.objective}</p><p className="muted">{task.capability} · Assigned: {task.agent_id||'none'} · Attempts: {task.attempts} · Prerequisites: {task.depends_on.join(', ')||'none'}</p>{task.result&&<><p>{task.result.summary}</p><small>Confidence: {task.result.confidence} · Risk: {task.result.risk}</small><p>{task.result.citations.map(id=><Link key={id} to={`/entities/${encodeURIComponent(id)}`}>{id} </Link>)}</p></>}{task.error&&<p role="alert">{task.error}</p>}</div></li>)}</ol>
   <h4>Supervisor answer / proposal</h4>{data.answer?<p style={{whiteSpace:'pre-wrap'}}>{data.answer}</p>:<p className="muted">No validated aggregate answer. Inspect specialist results and escalation reasons.</p>}
   <h4>Validated final source IDs</h4><div className="toolbar">{(data.citations||[]).map(id=><Link key={id} to={`/entities/${encodeURIComponent(id)}`}>{id}</Link>)}{!data.citations?.length&&'None'}</div>
   <h4>Human escalation ({data.escalations?.length??0})</h4>{data.escalations?.length?<ul>{data.escalations.map((e,i)=><li key={i}>{e.reason} · {e.task_ids.join(', ')}{e.detail?` — ${e.detail}`:''}</li>)}</ul>:<p className="muted">No escalation recorded.</p>}
   <h4>Unresolved knowledge gaps</h4>{data.knowledge_gaps?.length?<ul>{data.knowledge_gaps.map((x,i)=><li key={i}>{x}</li>)}</ul>:<p className="muted">No additional gaps in supervisor synthesis.</p>}
   <details><summary>Execution events ({data.events?.length??0})</summary><ol className="gh-demo-steps">{(data.events||[]).map((e,i)=><li key={e.index??e.event_index??i}><b>{e.kind} · {e.status}</b><p>{e.task_id} {e.agent_id} · {e.summary}</p><small>{e.created_at}</small></li>)}</ol></details>
   <p className="technical-secondary">Specialist citations are checked against the tenant graph observations and validated handoffs. This does not independently establish the semantic truth of findings. High-risk, contradictory and incomplete findings require human review. No business actions are executed.</p>
  </section>}
 </section>
}
