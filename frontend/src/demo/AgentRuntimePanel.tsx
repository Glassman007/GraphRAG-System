import {useState} from 'react'
import {useMutation,useQuery} from '@tanstack/react-query'
import {Link} from 'react-router-dom'
import {useAuth} from '../auth/AuthContext'
import {apiRequest} from '../api/client'
import type {Dict} from '../api/types'
import {ErrorPanel} from '../components/AsyncState'
import type {Scenario} from './demoModel'

interface RunResult {
 id:string;status:string;answer:string;plan:string[];citations:string[];
 knowledge_gaps:string[];trace:Dict[];steps_executed:number;tokens_used:number;error?:string
}

export function AgentRuntimePanel({scenario}:{scenario:Scenario}){
 const {config,hasPermission}=useAuth()
 const [goal,setGoal]=useState(()=>scenario.test_prompts[0]||`Investigate ${scenario.title}`)
 const [consent,setConsent]=useState(false)
 const [runId,setRunId]=useState('')
 const [runIdInput,setRunIdInput]=useState('')
 const [limit,setLimit]=useState(8)
 const status=useQuery({queryKey:['agent-runtime-status',config.tenantId],queryFn:({signal})=>apiRequest<Dict>(config,'/api/v1/agent-runtime/status',{signal}),retry:false})
 const run=useMutation({mutationFn:()=>apiRequest<RunResult>(config,'/api/v1/agent-runtime/runs',{
    method:'POST',body:{goal,source_entity_id:scenario.entry_ids[0],max_steps:limit,allow_external_model:consent}
 })})
 const existing=useQuery({queryKey:['agent-runtime-run',config.tenantId,runId],enabled:!!runId,
   queryFn:({signal})=>apiRequest<RunResult>(config,`/api/v1/agent-runtime/runs/${encodeURIComponent(runId)}`,{signal}),retry:false})
 const data=existing.data||run.data
 const configured=Boolean(status.data?.configured)
 return <section className="panel" style={{display:'grid',gap:12}}>
  <div className="page-header"><div><div className="eyebrow">COMPONENT 1 / AUTONOMOUS INVESTIGATION</div><h3>Ask the graph-aware agent</h3><p>One objective, model-selected read-only graph tools, sourced conclusion, persisted trace.</p></div><span className="gh-demo-label">{configured?'PROVIDER CONFIGURED':'PROVIDER NOT CONFIGURED'}</span></div>
  {status.error&&<ErrorPanel error={status.error}/>}
  {!configured&&<p className="notice">Set the backend model provider and API key before starting a run. Example: <code>GRAPH_HACKS_AGENT_PROVIDER=groq</code> and <code>GROQ_API_KEY</code>. The browser never receives your model key.</p>}
  <label className="field"><span>Organizational objective</span><textarea value={goal} maxLength={1500} rows={3} onChange={e=>setGoal(e.target.value)} /></label>
  <label className="field"><span>Maximum tool-selection iterations</span><select value={limit} onChange={e=>setLimit(Number(e.target.value))}>{[4,6,8,10,12].map(n=><option key={n} value={n}>{n}</option>)}</select></label>
  <label style={{display:'flex',alignItems:'flex-start',gap:8}}><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/><span>I authorize sending selected organizational context and read-only tool observations to the configured model provider for this investigation.</span></label>
  <div className="toolbar"><button className="primary" disabled={!configured||!consent||goal.trim().length<12||!hasPermission('CREATE_INVESTIGATION')||run.isPending} onClick={()=>{setRunId('');run.mutate()}}>{run.isPending?'Agent investigating…':'Start autonomous investigation'}</button><span className="muted">Read-only organizational tools; no actions or task creation.</span></div>
  {run.error&&<ErrorPanel error={run.error}/>}
  <details><summary>Reopen a persisted agent run</summary><label className="field"><span>Run ID</span><input placeholder="ARUN-…" value={runIdInput} onChange={e=>setRunIdInput(e.target.value.trim().toUpperCase())}/></label><button disabled={!/^ARUN-[0-9A-F]{32}$/.test(runIdInput)} onClick={()=>setRunId(runIdInput)}>Load saved trace</button>{existing.error&&<ErrorPanel error={existing.error}/>}</details>
  {data&&<section className="gh-work-board"><div className="eyebrow">RUN {data.id} · {data.status}</div><div className="gh-demo-metrics"><div><b>{data.steps_executed??'—'}</b><span>Decision iterations</span></div><div><b>{data.tokens_used??'—'}</b><span>Reported / estimated tokens</span></div><div><b>{data.trace?.length??0}</b><span>Persisted trace entries</span></div></div>
    {data.error&&<p role="alert">{data.error}</p>}
    {data.answer?<><h4>Sourced agent answer (not independently verified)</h4><p style={{whiteSpace:'pre-wrap'}}>{data.answer}</p></>:<p className="muted">No grounded final answer available for this run.</p>}
    <h4>Sources cited</h4><div className="toolbar">{(data.citations||[]).map(id=><Link key={id} to={`/entities/${encodeURIComponent(id)}`}>{id}</Link>)}{!data.citations?.length&&<span className="muted">No validated citations</span>}</div>
    <h4>Unresolved questions</h4>{(data.knowledge_gaps||[]).length?<ul>{data.knowledge_gaps.map(g=><li key={g}>{g}</li>)}</ul>:<p className="muted">None explicitly identified by model</p>}
    <h4>Initial / revised plan</h4><ol>{(data.plan||[]).map((x,i)=><li key={i}>{x}</li>)}</ol>
    <h4>Execution timeline</h4><ol className="gh-demo-steps">{(data.trace||[]).map((x,i)=><li key={x.id||i}><b>{x.kind} {x.tool||x.tool_name||''}</b> · {x.status}<p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{x.summary}</p><small>{x.created_at}</small></li>)}</ol>
    <p className="technical-secondary">This demonstrates single-agent model/tool autonomy, not multi-agent scheduling, cross-session agent recall, or external action execution. Source-ID checks do not independently prove the model's semantic conclusion.</p>
  </section>}
 </section>
}
