import {useState} from 'react'
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query'
import {Link} from 'react-router-dom'
import {useAuth} from '../../auth/AuthContext'
import {getTask, getTaskCoordination, getTaskExecution, claimTask, startTask, resumeTask, checkpointTask} from '../../api/tasks'
import {pauseTask,retryTask,completeTask,submitFinding,verifyFinding,getTaskInsights,getAgentMatches,handoffTask,resolveBlocker} from '../../api/workInsights'
import {proposeAction} from '../../api/actions'
import {canClaimTask,canStartTask,canResumeTask} from '../../permissions'
import {EntityPicker} from '../EntityPicker'
import {ErrorPanel,LoadingPanel,EmptyState} from '../AsyncState'
import {ConfirmationDialog} from '../ConfirmationDialog'
import {ReadableRecord} from '../ReadableRecord'
import {CoordinationBoard,WorkTaskSummary} from './WorkViews'
import {AdvancedCoordination} from './AdvancedCoordination'

export function TaskWorkbench({taskId}:{taskId:string}){
 const {config,hasPermission}=useAuth(),qc=useQueryClient(),key=`${config.tenantId}:${taskId}`
 const [agent,setAgent]=useState(''),[step,setStep]=useState({step_index:0,current_step:'',state_summary:''}),
 [finding,setFinding]=useState({statement:'',confidence:0.8,evidence_ids:''}),[validation,setValidation]=useState({finding_id:'',result:'INCONCLUSIVE',rationale:''}),
 [proposal,setProposal]=useState({name:'',action_type:'',target_ids:''}),[handoffAgent,setHandoffAgent]=useState(''),[blockerFix,setBlockerFix]=useState({blocker_id:'',resolution:''}),[confirm,setConfirm]=useState<string|null>(null)
 const matches=useQuery({queryKey:['work-agent-matches',key],queryFn:({signal})=>getAgentMatches(config,taskId,signal)})
 const detail=useQuery({queryKey:['work-task',key],queryFn:({signal})=>getTask(config,taskId,signal)})
 const insights=useQuery({queryKey:['work-insight',key],queryFn:({signal})=>getTaskInsights(config,taskId,signal)})
 const coord=useQuery({queryKey:['work-coord',key],queryFn:({signal})=>getTaskCoordination(config,taskId,signal)})
 const execution=useQuery({queryKey:['work-execution',key],queryFn:({signal})=>getTaskExecution(config,taskId,signal)})
 const invalidate=()=>{for(const base of ['work-task','work-insight','work-coord','work-execution'])qc.invalidateQueries({queryKey:[base,key]});qc.invalidateQueries({queryKey:['tasks']});qc.invalidateQueries({queryKey:['work-topology']})}
 const operation=useMutation({mutationFn:async(op:string)=>{
    if(op==='claim')return claimTask(config,taskId,agent)
    if(op==='start')return startTask(config,taskId,agent)
    if(op==='pause')return pauseTask(config,taskId,agent)
    if(op==='resume')return resumeTask(config,taskId,agent)
    if(op==='retry')return retryTask(config,taskId,agent)
    if(op==='complete')return completeTask(config,taskId,agent)
    if(op==='checkpoint')return checkpointTask(config,taskId,{agent_id:agent,step_index:step.step_index,current_step:step.current_step,state_summary:step.state_summary,completed_steps:[],pending_steps:[]})
    if(op==='finding')return submitFinding(config,taskId,{agent_id:agent,statement:finding.statement,confidence:Number(finding.confidence),evidence_ids:finding.evidence_ids.split(',').map(x=>x.trim()).filter(Boolean)})
    if(op==='verify')return verifyFinding(config,validation.finding_id,{agent_id:agent,result:validation.result,rationale:validation.rationale})
    if(op==='handoff')return handoffTask(config,taskId,handoffAgent)
    if(op==='resolve-blocker')return resolveBlocker(config,blockerFix.blocker_id,agent,blockerFix.resolution)
    if(op==='propose')return proposeAction(config,{task_id:taskId,agent_id:agent,name:proposal.name,action_type:proposal.action_type,target_ids:proposal.target_ids.split(',').map(x=>x.trim()).filter(Boolean)})
    throw new Error('Unsupported operation')
 },onSuccess:invalidate})
 if(detail.isLoading||insights.isLoading||coord.isLoading||execution.isLoading)return <LoadingPanel label="Reading task and coordination history…"/>
 const err=detail.error||insights.error||coord.error||execution.error||matches.error
 if(err)return <ErrorPanel error={err}/>
 if(!insights.data)return <EmptyState title="Task not found" />
 const state=String((execution.data?.execution||{}).status||''), t=detail.data
 const activeAgent=agent||String(insights.data.owner?.id||'')
 const canOperate=!!agent&&hasPermission('CLAIM_TASK')
 const workOps=[
  {id:'claim',label:'Claim task',available:canOperate&&canClaimTask(t)},
  {id:'start',label:'Start execution',available:canOperate&&canStartTask(t,coord.data)},
  {id:'pause',label:'Pause execution',available:canOperate&&state==='RUNNING'&&insights.data.owner?.id===agent},
  {id:'resume',label:'Resume from checkpoint',available:canOperate&&canResumeTask(t,execution.data,coord.data)&&['PAUSED','BLOCKED'].includes(state)},
  {id:'retry',label:'Retry failed execution',available:canOperate&&state==='FAILED'},
  {id:'complete',label:'Complete (validated)',available:canOperate&&state==='RUNNING'&&insights.data.owner?.id===agent},
 ]
 return <div className="gh-work-task"><div className="toolbar"><Link to="/work?tab=tasks">← All tasks</Link>{coord.data?.plan_ids?.map((id:string)=><Link key={id} to={`/plans/${encodeURIComponent(id)}`}>Plan {id}</Link>)}</div>
 <WorkTaskSummary insights={insights.data} detail={detail.data}/>
 <section className="panel"><h3>Agent control · governed transitions</h3><EntityPicker label="Operating agent" kind="Agent" value={agent} onChange={setAgent}/>{!agent&&activeAgent&&<p className="muted">Current recorded owner: {activeAgent}. Select an agent before acting.</p>}
 <div className="toolbar">{workOps.map(op=><button key={op.id} disabled={!op.available||operation.isPending} onClick={()=>setConfirm(op.id)}>{op.label}</button>)}</div><p className="muted">Status changes are checked by the backend. Resume/retry do not run external actions automatically. Completion requires a graph-backed completion contract.</p>
<section className="gh-work-wave"><h4>Eligible specialist agents</h4><p className="muted">Eligibility is computed from the current agent registry and task type; no claim occurs until you confirm one.</p>{(matches.data?.items||[]).map((m:any)=><div className="toolbar" key={m.agent.id}><button disabled={!m.eligible} onClick={()=>setAgent(m.agent.id)}>{m.agent.name||m.agent.id}</button><span className="muted">{m.eligible?'Eligible':m.reasons.join(', ')}</span></div>)}{matches.isLoading&&<p className="muted">Loading eligible agents…</p>}</section>
 <div className="grid-2"><div><h4>Agent handoff</h4><EntityPicker label="Destination agent" kind="Agent" value={handoffAgent} onChange={setHandoffAgent}/><button disabled={!hasPermission('CLAIM_TASK')||!handoffAgent||!insights.data.executions?.length||operation.isPending} onClick={()=>setConfirm('handoff')}>Transfer and resume</button><p className="muted">Transfers active task ownership to an eligible specialist and resumes the recorded execution. This is a state-changing operation.</p></div><div><h4>Resolve an explicit blocker</h4><label className="field"><span>Blocker</span><select value={blockerFix.blocker_id} onChange={e=>setBlockerFix(v=>({...v,blocker_id:e.target.value}))}><option value="">Select recorded blocker</option>{(insights.data.blockers||[]).map((b:any)=><option value={b.id} key={b.id}>{b.name||b.reason||b.id}</option>)}</select></label><label className="field"><span>Resolution evidence / explanation</span><textarea value={blockerFix.resolution} onChange={e=>setBlockerFix(v=>({...v,resolution:e.target.value}))}/></label><button disabled={!agent||!hasPermission('WRITE_FINDING')||!blockerFix.blocker_id||blockerFix.resolution.trim().length<5||operation.isPending} onClick={()=>setConfirm('resolve-blocker')}>Record blocker resolution</button></div></div>
 <div className="grid-2"><div><h4>Save checkpoint</h4><label className="field"><span>Step index</span><input type="number" min="0" value={step.step_index} onChange={e=>setStep(v=>({...v,step_index:Number(e.target.value)}))}/></label><label className="field"><span>Current step</span><input value={step.current_step} onChange={e=>setStep(v=>({...v,current_step:e.target.value}))}/></label><label className="field"><span>State summary</span><textarea value={step.state_summary} onChange={e=>setStep(v=>({...v,state_summary:e.target.value}))}/></label><button disabled={!agent||!hasPermission('WRITE_FINDING')||!step.current_step||!execution.data?.execution||operation.isPending} onClick={()=>setConfirm('checkpoint')}>Record checkpoint</button></div>
 <div><h4>Record specialist finding</h4><label className="field"><span>Finding statement</span><textarea value={finding.statement} onChange={e=>setFinding(v=>({...v,statement:e.target.value}))}/></label><label className="field"><span>Confidence (0–1)</span><input type="number" min="0" max="1" step="0.05" value={finding.confidence} onChange={e=>setFinding(v=>({...v,confidence:Number(e.target.value)}))}/></label><label className="field"><span>Supporting evidence IDs (optional)</span><input value={finding.evidence_ids} onChange={e=>setFinding(v=>({...v,evidence_ids:e.target.value}))}/></label><button disabled={!agent||!hasPermission('WRITE_FINDING')||finding.statement.trim().length<3||operation.isPending} onClick={()=>setConfirm('finding')}>Record finding</button></div></div>
 <div className="grid-2"><div><h4>Verify recorded finding</h4><label className="field"><span>Finding ID</span><input value={validation.finding_id} onChange={e=>setValidation(v=>({...v,finding_id:e.target.value}))} placeholder="FIND-P6-…"/></label><label className="field"><span>Outcome</span><select value={validation.result} onChange={e=>setValidation(v=>({...v,result:e.target.value}))}><option>VERIFIED</option><option>REJECTED</option><option>INCONCLUSIVE</option></select></label><label className="field"><span>Rationale</span><textarea value={validation.rationale} onChange={e=>setValidation(v=>({...v,rationale:e.target.value}))}/></label><button disabled={!agent||!hasPermission('WRITE_FINDING')||!validation.finding_id||operation.isPending} onClick={()=>setConfirm('verify')}>Submit verification</button><p className="muted">Only a backend-recognized VERIFIER agent can verify findings.</p></div><div><h4>Propose governed action</h4><label className="field"><span>Action name</span><input value={proposal.name} onChange={e=>setProposal(v=>({...v,name:e.target.value}))}/></label><label className="field"><span>Action type</span><input value={proposal.action_type} onChange={e=>setProposal(v=>({...v,action_type:e.target.value}))} placeholder="Supported type from agent capabilities"/></label><label className="field"><span>Target entity IDs</span><input value={proposal.target_ids} onChange={e=>setProposal(v=>({...v,target_ids:e.target.value}))}/></label><button disabled={!agent||!hasPermission('PROPOSE_ACTION')||!proposal.action_type||operation.isPending} onClick={()=>setConfirm('propose')}>Propose action (not execute)</button><p className="muted">A proposal cannot bypass approval, eligibility or locking checks.</p></div></div>
 {operation.error&&<ErrorPanel error={operation.error}/>} {operation.data&&<ReadableRecord title="Backend operation result" value={operation.data}/>}</section>
 <CoordinationBoard insights={insights.data}/>
 <AdvancedCoordination taskId={taskId} agent={agent} insights={insights.data}/>
 <ConfirmationDialog open={!!confirm} title={`${confirm||''} · ${taskId}`} onCancel={()=>setConfirm(null)} onConfirm={()=>{const op=confirm;setConfirm(null);if(op)operation.mutate(op)}} confirmLabel="Confirm"><p>Apply this operation as {agent||'the selected agent'}. Server permissions and task state are authoritative. This operation may persist records.</p></ConfirmationDialog>
 </div>
}
