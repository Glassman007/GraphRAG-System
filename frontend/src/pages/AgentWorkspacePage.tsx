import {useEffect,useMemo,useState} from 'react'
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query'
import {Link} from 'react-router-dom'
import {useAuth} from '../auth/AuthContext'
import {apiRequest} from '../api/client'
import {listSourceCatalog} from '../api/sources'
import {ErrorPanel} from '../components/AsyncState'
import {GovernedToolPanel} from '../demo/GovernedToolPanel'
import {GraphView} from '../components/GraphView'
import {getEntity,getNeighbors} from '../api/entities'
import {mergeGraphs,relationshipsToGraph} from '../graph/adapters'
import {allScenarios} from '../demo/demoModel'
import './agentWorkspace.css'
import {workspaceRecoveryState} from './workspaceRecovery'

const base='/api/v1/agent-runtime/workspace'
type Brain={graph_id:string;display_name:string;available:boolean}
type BrainList={items:Brain[];default_graph_id:string|null}
type Status='QUEUED'|'RUNNING'|'PAUSING'|'PAUSED'|'CANCELLING'|'CANCELLED'|'COMPLETED'|'FAILED'|'PARTIAL'|'NEEDS_REVIEW'|'INTERRUPTED'
type Workspace={id:string;graph_id?:string;goal:string;source_entity_id?:string;owner:string;status:Status;created_at:string;updated_at:string;error?:string;execution_mode:string;recovery_available:boolean}
type Finding={summary:string;confidence:string;risk:string;citations:string[];knowledge_gaps:string[];requires_human_review:boolean}
type Task={id:string;task_id?:string;objective:string;capability:string;depends_on:string[];status:string;agent_id:string;attempts:number;result?:Finding;error?:string}
type Event={index?:number;event_index?:number;kind:string;summary:string;task_id:string;agent_id:string;status:string;created_at:string}
type Supervisor={id:string;status:string;answer:string;citations:string[];knowledge_gaps:string[];tasks:Task[];events:Event[];conflicts:unknown[];escalations:{reason:string;task_ids:string[];detail?:string}[];tokens_used:number;error?:string}
type Snapshot={created_at:string;status:string;answer:string;citations:string[];tasks:{id:string;status:string}[];knowledge_gaps:string[]}
type Detail={workspace:Workspace;supervisor:Supervisor|null;checkpoint:{revision?:number;status?:string;updated_at?:string;reactive_affected_tasks:string[]};comparison:{task_id:string;checkpoint_status:string;current_status:string}[];snapshots:Snapshot[];classification:string}
type MemoryResult={id:string;subject_id:string;predicate:string;value:string;status:string;scope:string;citations:string[];verified_at?:string;origin_run_id:string;agent_id?:string;origin_agent_id?:string;verified_by?:string;summary?:string;source_tools?:string[];valid_until?:string}
type MemoryResponse={items:MemoryResult[];count:number}
type Change={id:string;status?:string;event_type?:string;kind?:string;entity_id?:string;created_at?:string;document_json?:string;affected_task_ids?:string[];certainty?:string;confidence?:string;changed_ids?:string[];workflow_impacts?:{run_id:string;affected_task_ids:string[];status:string}[];memory_impacts?:{memory_id:string;decision:string}[];[key:string]:unknown}

type Capabilities={status:string;provider:string;model_configured:boolean;worker_durability:string;controls:string;external_action_auto_execution:boolean}
const terminal=['COMPLETED','FAILED','PARTIAL','NEEDS_REVIEW','CANCELLED']
const inProgress=['QUEUED','RUNNING','PAUSING','CANCELLING']
const num=(event:Event)=>event.event_index??event.index??0
const stamp=(value?:string)=>value?new Date(value).toLocaleString():'—'
const safe=(value:unknown)=>String(value??'—')

function TaskGraph({tasks,selected,onSelect}:{tasks:Task[];selected:string;onSelect:(value:string)=>void}){
 const [showNetwork,setShowNetwork]=useState(false)
 const network=useMemo(()=>({nodes:tasks.map(t=>({id:t.task_id||t.id,type:'SupervisorTask',label:t.task_id||t.id,status:t.status,data:{id:t.task_id||t.id,description:t.objective,status:t.status,agent_id:t.agent_id}})),
 edges:tasks.flatMap(t=>(t.depends_on||[]).map(dep=>({id:`${dep}:PREREQUISITE_FOR:${t.task_id||t.id}`,source:dep,target:t.task_id||t.id,type:'PREREQUISITE_FOR',data:{}})))}),[tasks])
 const layers=useMemo(()=>{
  const byId=new Map(tasks.map(t=>[t.task_id||t.id,t]));const depth=new Map<string,number>()
  const visit=(id:string,seen:Set<string>):number=>{if(depth.has(id))return depth.get(id)!;if(seen.has(id))return 0;seen.add(id)
   const task=byId.get(id);const result=task?.depends_on?.length?1+Math.max(...task.depends_on.map(dep=>visit(dep,new Set(seen)))):0
   depth.set(id,result);return result}
  for(const task of tasks)visit(task.task_id||task.id,new Set())
  const buckets:Task[][]=[];for(const task of tasks){const level=depth.get(task.task_id||task.id)||0;(buckets[level]??=[]).push(task)}
  return buckets
 },[tasks])
 if(!tasks.length)return <div className="aw-empty">The scheduler has not persisted a task plan yet.</div>
 return <div className="aw-task-views"><div className="aw-dag" role="group" aria-label="Interactive dependency task graph">
  {layers.map((layer,i)=><div className="aw-dag-column" key={i}><span className="aw-stage">STAGE {String(i+1).padStart(2,'0')}</span>
   {layer.map(task=><button key={task.task_id||task.id} type="button" className={`aw-task aw-${task.status?.toLowerCase()} ${selected===(task.task_id||task.id)?'aw-selected':''}`} onClick={()=>onSelect(task.task_id||task.id)}>
    <span className="aw-task-heading"><b>{task.task_id||task.id}</b><small>{task.status}</small></span>
    <span className="aw-task-cap">{task.capability.replaceAll('_',' ')} · {task.agent_id||'Awaiting assignment'}</span>
    {task.depends_on?.length>0&&<span className="aw-task-deps">↳ after {task.depends_on.join(', ')}</span>}
   </button>)}
  </div>)}
 </div><details className="aw-explore" onToggle={e=>setShowNetwork(e.currentTarget.open)}><summary>Show connected dependency network (live scheduler tasks)</summary>{showNetwork&&<><GraphView graph={network} layout="breadthfirst" height={340} onNode={n=>onSelect(String(n.id))}/><p className="aw-footnote">These task IDs belong to the supervisor runtime; they are not canonical organizational entities. Edges encode validated scheduling prerequisites.</p></>}</details></div>
}

function CitationLinks({ids,graphId}:{ids:string[];graphId?:string}){return <span className="aw-citations">{ids.map(id=>graphId?<span key={id}>{id}</span>:<Link key={id} to={`/entities/${encodeURIComponent(id)}`}>{id} ↗</Link>)}{!ids.length&&<span className="aw-muted">None verified</span>}</span>}

export function EvidenceExplorer({ids,config}:{ids:string[];config:import('../api/types').ApiConfig}){
 const [selected,setSelected]=useState('')
 const focus=ids.includes(selected)?selected:ids[0]||''
 const record=useQuery({queryKey:['workspace-evidence-entity',config.tenantId,config.baseUrl,config.graphId,focus],queryFn:()=>getEntity(config,focus),enabled:!!focus&&!!config.graphId,retry:false})
 const neighborhood=useQuery({queryKey:['workspace-evidence-neighbors',config.tenantId,config.baseUrl,config.graphId,focus],queryFn:()=>getNeighbors(config,focus,{limit:40}),enabled:!!focus&&!!config.graphId&&record.isSuccess,retry:false})
 const graph=useMemo(()=>{
  const found=relationshipsToGraph(Array.isArray(neighborhood.data?.items)?neighborhood.data.items:[])
  const entity=record.data?.entity||record.data
  if(!entity)return {nodes:[],edges:[]}
  const labels=Array.isArray(entity._labels)?entity._labels.filter((x:string)=>x!=='Entity'):[]
  const type=String(labels[0]||entity.type||entity.kind||'Entity')
  const root={id:focus,type,label:String(entity.name||entity.title||entity.id||focus),status:entity.status,data:entity}
  return mergeGraphs(found,{nodes:[root],edges:[]})
 },[focus,record.data,neighborhood.data])
 if(!ids.length)return <p className="aw-muted">No verified final citations to explore.</p>
 if(!config.graphId)return <p role="alert">Select a Company Brain before retrieving evidence. Unscoped entity lookups are disabled in this explorer.</p>
 return <div className="aw-evidence-explorer"><div className="aw-controls-row"><label className="aw-field aw-grow"><span>Evidence or connected graph entity</span><select value={focus} onChange={e=>setSelected(e.target.value)}>{ids.map(id=><option value={id} key={id}>{id}</option>)}</select></label><span className="aw-muted">Scoped to selected Company Brain</span></div>
  {record.isLoading&&<p className="aw-muted">Checking selected citation in the current Company Brain…</p>}
  {record.error&&<><ErrorPanel error={record.error}/><p role="alert">This citation could not be resolved to a canonical entity in the selected graph. The explorer will not display it as verified evidence.</p></>}
  {record.data&&<><div className="aw-inspector"><b>{String(record.data?.entity?.name||record.data?.name||focus)}</b><p className="aw-muted">Canonical entity found in the selected graph. This alone does not verify the truth or provenance of associated claims.</p></div>
   {neighborhood.isLoading&&<p className="aw-muted">Retrieving connected evidence…</p>}
   {neighborhood.error&&<ErrorPanel error={neighborhood.error}/>}
   {!neighborhood.isLoading&&!neighborhood.error&&<GraphView key={`${config.tenantId}:${config.graphId}:${focus}`} graph={graph} apiConfig={config} layout="breadthfirst" height={315}/>}
   <p className="aw-footnote">Relationships are bounded graph reads. Select a node to verify its canonical identity and recorded provenance in this Company Brain. A connection does not establish causality.</p>
  </>}
 </div>
}

export function AgentWorkspacePage(){
 const {config,hasPermission}=useAuth();const qc=useQueryClient()
 const brainList=useQuery({queryKey:['workspace-brains',config.baseUrl,config.tenantId,config.token],queryFn:()=>apiRequest<BrainList>(config,'/api/v1/graphs'),retry:false})
 const [selectedSource,setSelectedSource]=useState('')
 const sourceCatalog=useQuery({queryKey:['workspace-source-catalog',config.baseUrl,config.tenantId],queryFn:()=>listSourceCatalog(config),retry:false})
 const [selectedGraph,setSelectedGraph]=useState(()=>{
  try{return new URLSearchParams(window.location.search).get('graph')||sessionStorage.getItem('verinex.workspace.graph.'+config.tenantId)||localStorage.getItem('verinex.workspace.graph.'+config.tenantId)||''}catch{return ''}
 })
 const availableBrains=brainList.data?.items.filter(item=>item.available)||[]
 const activeGraph=availableBrains.some(item=>item.graph_id===selectedGraph)?selectedGraph:''
 // Deep-linked graph selections must also be visible to the homepage.
 useEffect(()=>{if(activeGraph){try{sessionStorage.setItem('verinex.workspace.graph.'+config.tenantId,activeGraph);localStorage.setItem('verinex.workspace.graph.'+config.tenantId,activeGraph)}catch{/* storage disabled */}}},[activeGraph,config.tenantId])
 const scopedConfig={...config,graphId:activeGraph||undefined}
 const graphSources=(sourceCatalog.data?.items||[]).filter(item=>item.graph_id===activeGraph)
 const changeGraph=(next:string)=>{
  setSelectedGraph(next);setSelectedSource('');setChosen('');setFocused('');setSource('');setOpenedScenario('');setMemoryRequested(false);setShowEvidence(false)
  try{sessionStorage.setItem('verinex.workspace.graph.'+config.tenantId,next);localStorage.setItem('verinex.workspace.graph.'+config.tenantId,next)}catch{/* session storage disabled */}
 }

 const [objective,setObjective]=useState('Investigate the route orchestration outage and produce an evidence-backed remediation proposal.')
 const [source,setSource]=useState('');const [consent,setConsent]=useState(false);const [parallel,setParallel]=useState(3)
 const [chosen,setChosen]=useState('');const [focused,setFocused]=useState('');const [tab,setTab]=useState<'activity'|'memory'|'replay'|'changes'|'approvals'>('activity')
 const [memoryQuery,setMemoryQuery]=useState('');const [memoryIds,setMemoryIds]=useState('');const [memoryRequested,setMemoryRequested]=useState(false)
 const [frame,setFrame]=useState(0);const [openedScenario,setOpenedScenario]=useState('');const [showEvidence,setShowEvidence]=useState(false)
 const capabilities=useQuery({queryKey:['workspace-capabilities',config.baseUrl,config.tenantId],queryFn:()=>apiRequest<Capabilities>(config,base+'/capabilities'),retry:false,refetchInterval:30000})
 const runs=useQuery({queryKey:['workspace-list',config.baseUrl,config.tenantId,config.token,activeGraph],queryFn:()=>apiRequest<{items:Workspace[]}>(scopedConfig,base+'/runs'),enabled:!!activeGraph,retry:false,refetchInterval:3500})
 const activeId=chosen||runs.data?.items[0]?.id||''
 const detail=useQuery({queryKey:['workspace-detail',config.baseUrl,config.tenantId,config.token,activeGraph,activeId],queryFn:()=>apiRequest<Detail>(scopedConfig,base+'/runs/'+encodeURIComponent(activeId)),enabled:!!activeId,retry:false,refetchInterval:2500})
 const changes=useQuery({queryKey:['workspace-changes',config.baseUrl,config.tenantId,config.token,activeGraph],queryFn:()=>apiRequest<{items:Change[]}>(scopedConfig,base+'/changes?limit=30'),enabled:!!activeGraph&&tab==='changes',retry:false,refetchInterval:6000})
 const memory=useQuery({queryKey:['workspace-memory',config.baseUrl,config.tenantId,config.token,activeGraph,memoryQuery,memoryIds],queryFn:()=>apiRequest<MemoryResponse>(scopedConfig,'/api/v1/agent-runtime/memory/search',{method:'POST',body:{query:memoryQuery,entity_ids:memoryIds.split(',').map(x=>x.trim()).filter(Boolean),limit:20}}),enabled:!!activeGraph&&tab==='memory'&&memoryRequested,retry:false})
 const refresh=()=>{qc.invalidateQueries({queryKey:['workspace-list']});qc.invalidateQueries({queryKey:['workspace-detail']})}
 const start=useMutation({mutationFn:()=>apiRequest<{id:string;status:string}>(scopedConfig,base+'/runs',{method:'POST',body:{graph_id:activeGraph||null,goal:objective.trim(),source_entity_id:source.trim()||null,max_parallel:parallel,allow_external_model:consent}}),onSuccess:record=>{setChosen(record.id);setFocused('');setTab('activity');refresh()}})
 const control=useMutation({mutationFn:(operation:'pause'|'cancel'|'resume'|'retry')=>apiRequest(scopedConfig,base+'/runs/'+encodeURIComponent(activeId)+'/control',{method:'POST',body:{operation,allow_external_model:consent}}),onSuccess:refresh})
 const current=detail.data?.workspace
 const result=detail.data?.supervisor
 const tasks=result?.tasks||[]
 const recovery=workspaceRecoveryState(current,detail.data?.checkpoint,tasks)
 const events=result?.events||[]
 const selectedTask=tasks.find(t=>(t.task_id||t.id)===focused)
 const isActive=!!current&&inProgress.includes(current.status)
 const live=!!current&&current.status==='RUNNING'
 const canStart=hasPermission('CREATE_INVESTIGATION')&&consent&&objective.trim().length>=12&&!!activeGraph
 const selectedScenario=allScenarios.find(s=>s.scenario_id===openedScenario)
 const snapshots=detail.data?.snapshots||[]
 const displayFrame=Math.min(frame,Math.max(0,events.length-1))
 return <div className="aw-page">
  <header className="aw-hero"><div><div className="eyebrow">06 / LIVE AGENT WORKSPACE</div><h1>One objective. One workspace.</h1><p>Investigate connected organizational problems, observe specialist work, inspect verified memory, and make governed decisions without switching modules.</p></div>
   <div className="aw-hero-status"><span className="aw-overline">ENGINE CAPABILITY</span><strong>{capabilities.data?.model_configured?'Live model configured':'Model not configured'}</strong><small>{capabilities.data?.provider||'Checking provider'} · Read-only agents · No autonomous external actions</small></div></header>
  <div className="aw-overview">
   <div className="aw-stat"><b>{runs.data?.items.length??0}</b><span>My recorded runs</span></div>
   <div className="aw-stat"><b>{runs.data?.items.filter(r=>inProgress.includes(r.status)).length??0}</b><span>Active / transitioning</span></div>
   <div className="aw-stat"><b>{runs.data?.items.filter(r=>r.status==='PAUSED'||r.status==='INTERRUPTED').length??0}</b><span>Waiting / interrupted</span></div>
   <div className="aw-stat"><b>{runs.data?.items.filter(r=>terminal.includes(r.status)).length??0}</b><span>Finished / needs review</span></div>
  </div>
  <section className="aw-card aw-launch" aria-label="Agent command interface"><div className="aw-head"><div><span className="aw-overline">COMMAND AGENTS</span><h2>What needs to be accomplished?</h2></div><span className="aw-chip">REAL MODEL EXECUTION ONLY</span></div>
   <label className="aw-field"><span>Company Brain</span><select aria-label="Company Brain" value={activeGraph} onChange={e=>changeGraph(e.target.value)} disabled={brainList.isLoading}>
    <option value="">Select an authorized Company Brain</option>
    {availableBrains.map(brain=><option value={brain.graph_id} key={brain.graph_id}>{brain.display_name} ({brain.graph_id})</option>)}
   </select></label>
   <label className="aw-field"><span>Source (optional)</span><select aria-label="Source" value={selectedSource} onChange={e=>setSelectedSource(e.target.value)} disabled={!activeGraph}>
    <option value="">All sources in selected Company Brain</option>
    {graphSources.map(item=><option value={item.source_id} key={item.source_id}>{item.display_name} ({item.managed?'Managed':'Imported'})</option>)}
   </select></label>
   {sourceCatalog.error&&<ErrorPanel error={sourceCatalog.error}/>}
   <p className="aw-muted">Source selection identifies provenance within this Company Brain; investigations currently query the entire selected graph. Source-exclusive retrieval requires a separate enforced filter.</p>
   {brainList.error&&<ErrorPanel error={brainList.error}/>}
   {!brainList.isLoading&&!availableBrains.length&&<p className="aw-muted">No registered Company Brains are available to this tenant. Register an existing graph first.</p>}
   <label className="aw-field"><span>Organizational objective</span><textarea rows={3} maxLength={1500} value={objective} onChange={e=>setObjective(e.target.value)} placeholder="Investigate the outage, verify dependencies, and propose the safest remediation…"/></label>
   <div className="aw-controls-row"><label className="aw-field aw-grow"><span>Starting graph entity (optional)</span><input value={source} onChange={e=>setSource(e.target.value)} placeholder="INC-AST-ROUTE-OUTAGE"/></label><label className="aw-field"><span>Parallel specialists</span><select value={parallel} onChange={e=>setParallel(Number(e.target.value))}>{[1,2,3,4].map(v=><option value={v} key={v}>{v}</option>)}</select></label></div>
   <label className="aw-consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/><span>I authorize sending the scoped organizational context and validated handoffs to the configured model. This is <b>not</b> permission to perform external actions.</span></label>
   <div className="aw-command-bottom"><button className="primary" disabled={!canStart||start.isPending} onClick={()=>start.mutate()}>{start.isPending?'Starting…':'Start investigation →'}</button><span className="aw-muted">Actual model runs require provider credentials and a reachable FalkorDB graph.</span></div>
   {start.error&&<ErrorPanel error={start.error}/>} {capabilities.error&&<ErrorPanel error={capabilities.error}/>}
   <details className="aw-scenarios" hidden={activeGraph!=="asteria_company_brain_v1"}><summary>Asteria scenario shortcuts · seeded starting points, not results</summary><div className="aw-scenario-list">{allScenarios.map(s=><button key={s.scenario_id} onClick={()=>{setOpenedScenario(s.scenario_id);setObjective(s.test_prompts[0]||`Investigate ${s.title}`);setSource(s.entry_ids[0]||'')}}>{s.scenario_id}<strong>{s.title}</strong></button>)}</div>{selectedScenario&&<p className="aw-muted">Selected fixture: {selectedScenario.scenario_id} · {selectedScenario.entry_ids.join(', ')}. You must be connected to an appropriately populated Asteria tenant for these IDs to resolve.</p>}</details>
  </section>
  <div className="aw-layout"><aside className="aw-card aw-run-list"><div className="aw-head"><div><span className="aw-overline">EXECUTION QUEUE</span><h2>Investigations</h2></div><button onClick={refresh} aria-label="Refresh runs">↻</button></div>
    {runs.error&&<ErrorPanel error={runs.error}/>}{!runs.data?.items.length&&<div className="aw-empty">No workspace runs yet. Start one above to create a real investigation.</div>}
    {runs.data?.items.map(run=><button className={`aw-run ${activeId===run.id?'aw-picked':''}`} key={run.id} onClick={()=>{control.reset();setChosen(run.id);setFocused('');setFrame(0)}}><span className="aw-run-top"><b className={`aw-pill aw-pill-${run.status.toLowerCase()}`}>{run.status.replaceAll('_',' ')}</b><small>{stamp(run.created_at)}</small></span><strong>{run.goal}</strong><small>{run.graph_id||'Legacy default'} · {run.id}</small></button>)}
    <p className="aw-footnote">Only runs owned by the authenticated principal are listed.</p>
   </aside>
   <div className="aw-main">
    {detail.error&&<ErrorPanel error={detail.error}/>}
    {!current?<section className="aw-card aw-empty-state"><span className="aw-overline">AWAITING OBJECTIVE</span><h2>The workspace is ready.</h2><p>Start an investigation or choose one of your saved runs to observe tasks and inspect verified outcomes.</p></section>:<>
     <section className="aw-card"><div className="aw-head"><div><span className="aw-overline">SUPERVISOR / {current.id}</span><h2>{current.goal}</h2><p className="aw-muted">Owner {current.owner} · {stamp(current.created_at)} · Brain: {current.graph_id||'Legacy default'}</p></div><b className={`aw-pill aw-pill-${current.status.toLowerCase()}`}>{current.status}</b></div>
      <div className="aw-metrics"><span><strong>{tasks.length}</strong> scheduled tasks</span><span><strong>{tasks.filter(t=>t.status==='COMPLETED').length}</strong> completed</span><span><strong>{events.length}</strong> recorded events</span><span><strong>{result?.tokens_used??0}</strong> tokens / estimate</span></div>
      <div className="aw-actions"><button disabled={!hasPermission('CREATE_INVESTIGATION')||!isActive||control.isPending} onClick={()=>control.mutate('pause')}>Pause after current tasks</button><button disabled={!hasPermission('CREATE_INVESTIGATION')||!isActive||control.isPending} onClick={()=>control.mutate('cancel')}>Cancel scheduling</button><button disabled={!hasPermission('CREATE_INVESTIGATION')||!consent||!recovery.canResume||control.isPending} onClick={()=>control.mutate('resume')}>Resume</button><button disabled={!hasPermission('CREATE_INVESTIGATION')||!consent||!recovery.canRetry||control.isPending} onClick={()=>control.mutate('retry')}>Retry failed work</button><button onClick={()=>detail.refetch()}>Refresh now</button></div>
      {recovery.reviewOnly&&<p className="aw-footnote">All specialist tasks completed. This run needs evidence or human review; there is no failed work to retry.</p>}
      {recovery.missingCheckpoint&&<p className="aw-footnote">No planned checkpoint is available for this run. It cannot safely resume or retry; a new investigation is required.</p>}
      {recovery.hasCheckpoint&&<p className="aw-footnote">Persisted checkpoint: revision {detail.data?.checkpoint.revision}. Recovery is only offered when there is eligible work.</p>}
      {current.error&&<p role="alert">{current.error}</p>}{control.error&&<ErrorPanel error={control.error}/>}
      <p className="aw-footnote">{live?'Polling persisted operational activity every 2.5 seconds.':'Persisted state, not a fabricated live animation.'} Pause/cancel are cooperative and may wait for active model calls. No rollback or notification is executed by the supervisor.</p>
     </section>
     {!!detail.data?.checkpoint.reactive_affected_tasks?.length&&<div className="aw-card"><strong>Targeted re-verification required</strong><p>Changed organizational evidence affects {detail.data.checkpoint.reactive_affected_tasks.join(', ')}. Resume requires fresh model consent; the supervisor rechecks the affected dependency chain.</p></div>}
     <section className="aw-card"><div className="aw-head"><div><span className="aw-overline">DEPENDENCY-AWARE COORDINATION</span><h2>Specialist task graph</h2></div><span className="aw-muted">Select a task to inspect findings</span></div>
      <TaskGraph tasks={tasks} selected={focused} onSelect={setFocused}/>
      {selectedTask&&<div className="aw-inspector"><div className="aw-head"><h3>{selectedTask.task_id||selectedTask.id}</h3><b className="aw-pill">{selectedTask.status}</b></div><p>{selectedTask.objective}</p><p className="aw-muted">Agent: {selectedTask.agent_id||'none'} · Capability: {selectedTask.capability} · Attempts: {selectedTask.attempts} · Needs: {selectedTask.depends_on.join(', ')||'no prerequisites'}</p>
      {selectedTask.result&&<><p>{selectedTask.result.summary}</p><p>Evidence confidence: <b>{selectedTask.result.confidence}</b> · Risk: {selectedTask.result.risk}</p><CitationLinks ids={selectedTask.result.citations||[]} graphId={current.graph_id}/>{!!selectedTask.result.knowledge_gaps?.length&&<p>Open questions: {selectedTask.result.knowledge_gaps.join('; ')}</p>}</>}{selectedTask.error&&<p role="alert">{selectedTask.error}</p>}</div>}
     </section>
     <section className="aw-card"><div className="aw-head"><div><span className="aw-overline">EVIDENCE-BASED OUTCOME</span><h2>Result and next decisions</h2></div><span className="aw-chip">{result?.status||'AWAITING RESULTS'}</span></div>
      {result?.answer?<p className="aw-answer">{result.answer}</p>:<p className="aw-muted">No verified final synthesis yet; individual specialist findings may still be available.</p>}
      <p className="aw-small-heading">CITED GRAPH RECORDS</p><CitationLinks ids={result?.citations||[]} graphId={current.graph_id}/>
      <details className="aw-explore" onToggle={e=>setShowEvidence(e.currentTarget.open)}><summary>Explore cited evidence and graph relationships here</summary>{showEvidence&&<EvidenceExplorer ids={result?.citations||[]} config={{...scopedConfig,graphId:current.graph_id}}/>}</details>
      {!!result?.knowledge_gaps?.length&&<><p className="aw-small-heading">UNRESOLVED QUESTIONS</p><ul>{result.knowledge_gaps.map((text,i)=><li key={i}>{text}</li>)}</ul></>}
      {!!result?.escalations?.length&&<><p className="aw-small-heading">HUMAN ESCALATION</p><ul>{result.escalations.map((e,i)=><li key={i}>{e.reason} — {e.task_ids.join(', ')} {e.detail||''}</li>)}</ul></>}
      <p className="aw-footnote">An evidence-backed recommendation is never itself authorization to execute an action. Use the approval board below for separate governed operations.</p>
     </section>
     <section className="aw-card"><nav className="aw-subnav" aria-label="Workspace inspections">{([['activity','Activity'],['memory','Memory'],['replay','Replay / compare'],['changes','Change feed'],['approvals','Approvals / actions']] as const).map(([id,label])=><button key={id} className={tab===id?'aw-current':''} onClick={()=>setTab(id)}>{label}</button>)}</nav>
      {tab==='activity'&&<><div className="aw-head"><div><span className="aw-overline">OBSERVABLE EVENTS</span><h2>Agent and tool activity</h2></div><span className="aw-chip">{events.length} EVENTS</span></div>{!events.length&&<div className="aw-empty">No persisted execution events yet.</div>}<ol className="aw-timeline">{[...events].reverse().map((e,i)=><li key={`${num(e)}:${i}`}><span className="aw-timeline-icon">{e.kind==='SPECIALIST_TOOL'?'⌘':'●'}</span><div><div><b>{e.kind.replaceAll('_',' ')}</b> <small>{e.status} · {stamp(e.created_at)}</small></div><p>{e.summary}</p><small>{e.agent_id||'supervisor'} {e.task_id&&`· ${e.task_id}`}</small></div></li>)}</ol></>}
      {tab==='memory'&&<><div className="aw-head"><div><span className="aw-overline">VERIFIED ORGANIZATIONAL KNOWLEDGE</span><h2>Memory inspector</h2></div><span className="aw-muted">Checkpoint revision {detail.data?.checkpoint.revision??'—'}</span></div><p className="aw-muted">Current verified shared knowledge only. Drafts and private agent branches are not exposed by this inspector.</p><div className="aw-controls-row"><label className="aw-field aw-grow"><span>Entity IDs, comma-separated</span><input value={memoryIds} onChange={e=>{setMemoryIds(e.target.value);setMemoryRequested(false)}} placeholder={current.source_entity_id||'SYS-AST-ROUTE-DB'}/></label><label className="aw-field aw-grow"><span>Context keywords</span><input value={memoryQuery} onChange={e=>{setMemoryQuery(e.target.value);setMemoryRequested(false)}} placeholder="Route dependency"/></label><button disabled={!memoryIds.trim()&&!memoryQuery.trim()} onClick={()=>{setMemoryRequested(true)}}>Find verified memories</button></div>
       <p className="aw-footnote">Checkpoint: {detail.data?.checkpoint.status||'not yet available'} · {stamp(detail.data?.checkpoint.updated_at)}. A checkpoint is recovery metadata, not evidence that claims are true.</p>{memory.error&&<ErrorPanel error={memory.error}/>} {memoryRequested&&!memory.isLoading&&!memory.data?.items.length&&<p className="aw-empty">No currently verified and accessible memories match this search.</p>}
       <div className="aw-memory-results">{memory.data?.items.map(m=><article className="aw-inspector" key={m.id}><div className="aw-head"><b>{m.subject_id} / {m.predicate}</b><span className="aw-chip">{m.status}</span></div><p>{m.value}</p>{m.summary&&<p className="aw-muted">{m.summary}</p>}<p className="aw-muted">Origin: {m.origin_run_id} · Agent: {m.origin_agent_id||m.agent_id||'see provenance'} · Verified by: {m.verified_by||'see provenance'} · Verified: {stamp(m.verified_at)} · Valid until: {stamp(m.valid_until)}</p><p className="aw-muted">Tools: {m.source_tools?.join(', ')||'see provenance'}</p><CitationLinks ids={m.citations||[]}/></article>)}</div>
       <button onClick={()=>{setMemoryIds(current.source_entity_id||'');setMemoryQuery(current.goal.slice(0,250));setMemoryRequested(true)}}>Search this investigation context</button>
      </>}
      {tab==='replay'&&<><div className="aw-head"><div><span className="aw-overline">PERSISTED EXECUTION REPLAY</span><h2>What happened, and when?</h2></div><span className="aw-chip">OPERATIONAL TRACE</span></div>
       <label className="aw-field"><span>Event {events.length?displayFrame+1:0} of {events.length}</span><input type="range" min={0} max={Math.max(0,events.length-1)} value={displayFrame} onChange={e=>setFrame(Number(e.target.value))} disabled={!events.length}/></label>
       {events.length>0&&<div className="aw-inspector"><h3>{events[displayFrame]?.kind}</h3><p>{events[displayFrame]?.summary}</p><p className="aw-muted">{events[displayFrame]?.agent_id||'supervisor'} · {events[displayFrame]?.task_id||'coordination'} · {stamp(events[displayFrame]?.created_at)}</p></div>}
       <p className="aw-small-heading">BEFORE / AFTER RECORDED RUN OUTCOMES</p>
       {snapshots.length<2?<p className="aw-muted">A comparison requires at least two persisted execution outcomes (for example, an initial run and a resumed investigation). No prior outcome is invented.</p>:<div className="aw-compare"><div><b>Before · {snapshots[0].status}</b><p>{snapshots[0].answer||'No final answer'}</p><small>{stamp(snapshots[0].created_at)}</small></div><div><b>After · {snapshots[snapshots.length-1].status}</b><p>{snapshots[snapshots.length-1].answer||'No final answer'}</p><small>{stamp(snapshots[snapshots.length-1].created_at)}</small></div></div>}
       <p className="aw-footnote">Replays show recorded execution decisions, tools and checkpoints, not hidden model reasoning or a complete historical graph-state simulation.</p>
      </>}
      {tab==='changes'&&<><div className="aw-head"><div><span className="aw-overline">CONTINUOUS ORGANIZATIONAL LEARNING</span><h2>Verified change feed</h2></div><button onClick={()=>changes.refetch()}>Refresh changes</button></div><p className="aw-muted">Changes are recorded by the reactive event processor. Targeted invalidations and replans do not imply automatic permission for additional model calls.</p>{changes.error&&<ErrorPanel error={changes.error}/>} {changes.data?.items.length===0&&<p className="aw-empty">No change records.</p>}<ol className="aw-timeline">{changes.data?.items.map((event,i)=><li key={event.id||i}><span className="aw-timeline-icon">↻</span><div><b>{safe(event.kind||event.event_type||event.id)}</b> · {safe(event.status)} · {safe(event.confidence||event.certainty)}<p>Changed: {(event.changed_ids||[]).join(', ')||safe(event.entity_id||event.id)}</p>{!!event.memory_impacts?.length&&<p>Memories reviewed: {event.memory_impacts.map(m=>`${m.memory_id} (${m.decision})`).join(', ')}</p>}{event.workflow_impacts?.map(w=><p key={w.run_id}>Affected workflow: <button onClick={()=>{setChosen(w.run_id);setTab('activity')}}>{w.run_id}</button> · {w.affected_task_ids?.join(', ')||'no task IDs'} · {w.status}</p>)}<small>{stamp(event.created_at)}</small><details><summary>Recorded change details</summary><pre className="aw-json">{JSON.stringify(event,null,2)}</pre></details></div></li>)}</ol></>}
      {tab==='approvals'&&<><div className="aw-head"><div><span className="aw-overline">GOVERNED ACTIONS</span><h2>Review, approve, verify</h2></div><span className="aw-chip">BACKEND-GATED</span></div><p className="aw-muted">Approval requires a separate authorized principal. Action proposals and execution remain subject to live policy checks; even a completed investigation cannot auto-approve itself.</p><GovernedToolPanel sourceId={current.source_entity_id||''}/></>}
     </section>
    </>}
   </div></div>
  <footer className="aw-disclosure"><b>Capability boundaries</b><span>Real model work: only when explicitly started with consent and credentials.</span><span>Scenario catalog: seeded inputs, not computed outcomes.</span><span>Graph verification: evidence-backed, not model retraining.</span><span>Execution: process-local background worker; restart requires checkpoint recovery.</span><span>Governed operations: independent policy, approval and connector verification.</span></footer>
 </div>
}
