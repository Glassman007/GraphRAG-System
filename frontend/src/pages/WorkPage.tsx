import {useState} from 'react'
import {Link,useSearchParams} from 'react-router-dom'
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query'
import {useAuth} from '../auth/AuthContext'
import {listPlans,createPlan} from '../api/plans'
import {listTasks} from '../api/tasks'
import {listAgents,getAgentCapabilities,getAgentTasks} from '../api/agents'
import {getAgentMemory} from '../api/workInsights'
import {EntityPicker} from '../components/EntityPicker'
import {DataTable} from '../components/DataTable'
import {ReadableRecord} from '../components/ReadableRecord'
import {ErrorPanel,LoadingPanel,EmptyState} from '../components/AsyncState'
import {StatusBadge} from '../components/StatusBadge'
import {displayName} from '../presentation'
import {TaskWorkbench} from '../components/work/TaskWorkbench'
import {AgentMemoryView,AgentCapabilityPanel} from '../components/work/WorkViews'
import {ActionGovernanceBoard} from '../components/work/ActionGovernanceBoard'
import scenarios from '../data/asteriaScenarios.json'
const tabs=['plans','tasks','agents','memory','actions']

export function WorkPage(){
 const {config,hasPermission}=useAuth(),qc=useQueryClient(),[sp,setSp]=useSearchParams()
 const tab=tabs.includes(sp.get('tab')||'')?String(sp.get('tab')):'tasks',taskId=sp.get('task')||''
 const preset=scenarios.find(s=>s.scenario_id===sp.get('scenario')&&s.entry_ids.some(id=>id.startsWith('INC-')))
 const [agent,setAgent]=useState(''),[memoryAgent,setMemoryAgent]=useState(''),[planForm,setPlanForm]=useState({situation_id:preset?.entry_ids.find(id=>id.startsWith('INC-'))||'',goal:preset?`Investigate ${preset.title.toLowerCase()} with evidence, specialist tasks, validation and approved remediation.`:'Investigate the incident, collect evidence, verify conclusions and propose a governed remediation.'}),[scenario,setScenario]=useState(preset?.scenario_id||'')
 const scope=config.tenantId
 const plans=useQuery({queryKey:['work-plans',scope],queryFn:({signal})=>listPlans(config,{limit:100},signal),enabled:tab==='plans'})
 const tasks=useQuery({queryKey:['tasks',scope],queryFn:({signal})=>listTasks(config,{limit:100},signal),enabled:tab==='tasks'})
 const agents=useQuery({queryKey:['work-agents',scope],queryFn:({signal})=>listAgents(config,{limit:100},signal),enabled:tab==='agents'||tab==='memory'})
 const capabilities=useQuery({queryKey:['work-agent-capabilities',scope,agent],queryFn:({signal})=>getAgentCapabilities(config,agent,signal),enabled:tab==='agents'&&!!agent})
 const agentWork=useQuery({queryKey:['work-agent-tasks',scope,agent],queryFn:({signal})=>getAgentTasks(config,agent,signal),enabled:tab==='agents'&&!!agent})
 const memory=useQuery({queryKey:['work-memory',scope,memoryAgent],queryFn:({signal})=>getAgentMemory(config,memoryAgent,signal),enabled:tab==='memory'&&!!memoryAgent})
 const makePlan=useMutation({mutationFn:()=>createPlan(config,{...planForm,selected_hypotheses:[],selected_claims:[],knowledge_gaps:[],constraints:[]}),onSuccess:()=>qc.invalidateQueries({queryKey:['work-plans']})})
 const scenarioOptions=scenarios.filter(x=>x.entry_ids.some(id=>id.startsWith('INC-')))
 const scenarioDetails=scenarioOptions.find(x=>x.scenario_id===scenario)
 function applyScenario(id:string){setScenario(id);const selected=scenarioOptions.find(x=>x.scenario_id===id);const incident=selected?.entry_ids.find(x=>x.startsWith('INC-'))||'';setPlanForm(v=>({...v,situation_id:incident,goal:selected?`Investigate ${selected.title.toLowerCase()} with evidence, specialist tasks, validation and approved remediation.`:v.goal}))}
 function switchTab(t:string){setSp({tab:t})}
 return <section className="gh-work-root"><div className="page-header"><div><div className="eyebrow">ORGANIZATIONAL INTELLIGENCE / WORK</div><h2>Work & Agent Coordination</h2><p>Connected plans, inspectable execution, persistent records and governed action.</p></div><Link to="/scenarios">Explore scenarios →</Link></div><nav className="tabs" aria-label="Work sections">{tabs.map(t=><button key={t} className={t===tab?'active':''} onClick={()=>switchTab(t)}>{t==='memory'?'Agent memory':t==='actions'?'Action governance':t}</button>)}</nav>
 {tab==='plans'&&<><section className="panel"><h3>Generate scenario-based work plan</h3><p>Choose a predefined Asteria incident, or search for any tenant-visible situation. The backend derives task DAGs from actual gaps, claims and governance constraints; selecting a scenario alone does not execute anything.</p>{scope==='asteria'&&<label className="field"><span>Starting scenario</span><select value={scenario} onChange={e=>applyScenario(e.target.value)}><option value="">Choose a scenario or manually select a situation</option>{scenarioOptions.map(s=><option key={s.scenario_id} value={s.scenario_id}>{s.title} · {s.scenario_id}</option>)}</select></label>}{scenarioDetails&&<p className="muted">{scenarioDetails.summary}</p>}<div className="filter-row"><EntityPicker label="Situation" kind="Incident" value={planForm.situation_id} onChange={id=>{setScenario('');setPlanForm(v=>({...v,situation_id:id}))}}/><label className="field"><span>Investigation / plan objective</span><textarea value={planForm.goal} onChange={e=>setPlanForm(v=>({...v,goal:e.target.value}))}/></label></div><button disabled={!hasPermission('CREATE_PLAN')||!planForm.situation_id||!planForm.goal.trim()||makePlan.isPending} onClick={()=>makePlan.mutate()}>Create connected plan</button>{makePlan.error&&<ErrorPanel error={makePlan.error}/>} {makePlan.data?.plan?.id&&<p><Link to={`/plans/${encodeURIComponent(makePlan.data.plan.id)}`}>Open generated plan → {makePlan.data.plan.id}</Link></p>}</section><section className="panel"><h3>Plans</h3>{plans.isLoading?<LoadingPanel/>:plans.error?<ErrorPanel error={plans.error}/>:<DataTable rows={plans.data?.items||[]} rowKey={(r:any)=>r.id} columns={[{key:'name',header:'Plan',render:(r:any)=><Link to={`/plans/${encodeURIComponent(r.id)}`}>{displayName(r)}<span className="technical-secondary">{r.id}</span></Link>},{key:'status',header:'Status',render:(r:any)=><StatusBadge value={String(r.status||'UNKNOWN')}/>},{key:'goal',header:'Goal',render:(r:any)=>r.goal||r.objective||'—'}]}/>}</section></>}
 {tab==='tasks'&&<div className="gh-work-split"><section className="panel"><h3>Task register</h3>{tasks.isLoading?<LoadingPanel/>:tasks.error?<ErrorPanel error={tasks.error}/>:<><DataTable rows={tasks.data?.items||[]} rowKey={(r:any)=>r.id} columns={[{key:'name',header:'Task',render:(r:any)=><button className="link-button" onClick={()=>setSp({tab:'tasks',task:r.id})}>{displayName(r)} <span className="technical-secondary">{r.id}</span></button>},{key:'priority',header:'Priority',render:(r:any)=>r.priority||'—'},{key:'status',header:'State',render:(r:any)=><StatusBadge value={String(r.status||'UNKNOWN')}/>}]} />{tasks.data?.has_more&&<p className="muted">Displaying first 100 tasks; use graph explorer to find older records.</p>}</>}</section><div>{taskId?<TaskWorkbench key={taskId} taskId={taskId}/>:<EmptyState title="Select a task" detail="Choose a descriptive task from the register to inspect dependencies, evidence, execution, checkpoints and work operations."/>}</div></div>}
 {tab==='agents'&&<div className="gh-work-split"><section className="panel"><h3>Specialist agent registry</h3>{agents.isLoading?<LoadingPanel/>:agents.error?<ErrorPanel error={agents.error}/>:<DataTable rows={agents.data?.items||[]} rowKey={(r:any)=>r.id} columns={[{key:'name',header:'Agent',render:(r:any)=><button className="link-button" onClick={()=>setAgent(r.id)}>{displayName(r)} <small className="technical-secondary">{r.id}</small></button>},{key:'role',header:'Type',render:(r:any)=>r.agent_type||'—'},{key:'status',header:'Availability',render:(r:any)=>r.availability||r.status||'—'}]}/>}</section><div>{!agent?<EmptyState title="Select an agent" detail="Inspect supported task types, permitted tools and current work."/>:<>{capabilities.isLoading?<LoadingPanel/>:capabilities.error?<ErrorPanel error={capabilities.error}/>:<AgentCapabilityPanel data={capabilities.data}/>} {agentWork.error?<ErrorPanel error={agentWork.error}/>:<ReadableRecord title="Assigned work / produced outputs" value={agentWork.data}/>}<button onClick={()=>{setMemoryAgent(agent);switchTab('memory')}}>Inspect persisted agent memory →</button></>}</div></div>}
 {tab==='memory'&&<><div className="panel"><h3>Persistent agent memory explorer</h3><p className="muted">Inspect graph-backed checkpoints and produced artifacts, their provenance, scope, and status. Shared records are not the same as unrestricted access to private agent context.</p><EntityPicker label="Agent" kind="Agent" value={memoryAgent} onChange={setMemoryAgent}/></div>{memoryAgent&&(memory.isLoading?<LoadingPanel/>:memory.error?<ErrorPanel error={memory.error}/>:memory.data?<AgentMemoryView data={memory.data}/>:<EmptyState title="No agent record"/>)}</>}
 {tab==='actions'&&<ActionGovernanceBoard/>}
 </section>
}
