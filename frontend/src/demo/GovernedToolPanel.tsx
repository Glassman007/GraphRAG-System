import {useState} from 'react'
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query'
import {Link} from 'react-router-dom'
import {useAuth} from '../auth/AuthContext'
import {apiRequest,makeIdempotencyKey} from '../api/client'
import {ErrorPanel} from '../components/AsyncState'

const base='/api/v1/agent-runtime/governed'
type Tool={id:string;title:string;risk:string;side_effect:string;configured:boolean;approval_required:boolean}
type Guard={allowed:boolean;violations:string[];fingerprint:string;policies:{id:string;effect:string}[]}
type Action={id:string;status:string;revision:number;tool_id:string;risk:string;target_id:string;initiator:string;agent_id:string;
 evidence_ids:string[];rationale:string;approval?:{actor:string;reason:string;at:string;expires_at:string};
 proposal_validation?:Guard;execution?:{operation_key:string;receipt?:{receipt_id:string;operation_id:string}};
 post_action_verification?:{source:string;connector_receipt:unknown};learning_warning?:string;failure?:string}
type ActionDetail={action:Action;audit:{type:string;actor:string;occurred_at?:string;details?:unknown}[]}
type Preview={current_authorization:Guard;simulation:{baseline:{impacted:string[]};counterfactual:{impacted:string[]};scope_limit:string};connector_configured:boolean;status:string}

export function GovernedToolPanel({sourceId}:{sourceId:string}){
 const {config,hasPermission}=useAuth()
 const cache=useQueryClient()
 const [tool,setTool]=useState('incident_notification')
 const [target,setTarget]=useState(sourceId)
 const [evidence,setEvidence]=useState('')
 const [reason,setReason]=useState('')
 const [agent,setAgent]=useState('remediation_specialist')
 const [runId,setRunId]=useState('')
 const [message,setMessage]=useState('Incident response team: verified evidence requires a controlled investigation of the affected system.')
 const [requestKey,setRequestKey]=useState(()=>makeIdempotencyKey('gov'))
 const [selected,setSelected]=useState('')
 const [approvalReason,setApprovalReason]=useState('I independently reviewed the evidence, policy and blast radius.')
 const tools=useQuery({queryKey:['governed-tools',config.tenantId],queryFn:()=>apiRequest<{tools:Tool[];policy:string}>(config,base+'/tools')})
 const actions=useQuery({queryKey:['governed-actions',config.tenantId],queryFn:()=>apiRequest<{items:Action[]}>(config,base+'/actions?limit=30')})
 const detail=useQuery({queryKey:['governed-detail',config.tenantId,selected],queryFn:()=>apiRequest<ActionDetail>(config,base+'/actions/'+encodeURIComponent(selected)),enabled:!!selected})
 const preview=useQuery({queryKey:['governed-preview',config.tenantId,selected],queryFn:()=>apiRequest<Preview>(config,base+'/actions/'+encodeURIComponent(selected)+'/preview'),enabled:!!selected})
 const reload=()=>{cache.invalidateQueries({queryKey:['governed-actions',config.tenantId]});cache.invalidateQueries({queryKey:['governed-detail',config.tenantId]});cache.invalidateQueries({queryKey:['governed-preview',config.tenantId]})}
 const create=useMutation({mutationFn:()=>apiRequest<Action>(config,base+'/actions',{method:'POST',body:{tool_id:tool,target_id:target.trim(),
  evidence_ids:evidence.split(',').map(x=>x.trim()).filter(Boolean),rationale:reason,agent_id:runId.trim()?agent.trim():'manual_operator',
  supervisor_run_id:runId.trim()||null,idempotency_key:requestKey,
  arguments:tool==='incident_notification'?{incident_id:target.trim(),message}:{change_id:target.trim(),reason:message}}}),
  onSuccess:(data)=>{setSelected(data.id);setRequestKey(makeIdempotencyKey('gov'));reload()}})
 const mutate=useMutation({mutationFn:({actionId,op}:{actionId:string;op:string})=>apiRequest<Action>(config,
  base+'/actions/'+encodeURIComponent(actionId)+'/'+op,{method:'POST',
  ...(op==='approve'||op==='reject'||op==='escalate'?{body:{reason:approvalReason}}:{}),
  ...(op==='execute'?{body:{acknowledge_external_side_effect:true}}:{})}),onSuccess:()=>reload()})
 const learn=useMutation({mutationFn:(actionId:string)=>apiRequest(config,base+'/actions/'+encodeURIComponent(actionId)+'/learn-outcome',{method:'POST'}),onSuccess:()=>reload()})
 const selectedAction=detail.data?.action
 const canEdit=hasPermission('PROPOSE_ACTION')
 const canApprove=hasPermission('APPROVE_ACTION')
 const canExecute=hasPermission('EXECUTE_ACTION')
 return <section className="panel" style={{display:'grid',gap:12}}>
  <div className="page-header"><div><div className="eyebrow">COMPONENT 5 / GOVERNED TOOL EXECUTION</div>
   <h3>Recommend first. Authorize separately. Verify afterward.</h3>
   <p>The graph supports a proposal, never permission to act. External connectors are disabled unless an operator explicitly configures them on the backend.</p></div>
   <span className="gh-demo-label">HUMAN GATED</span></div>
  {tools.error&&<ErrorPanel error={tools.error}/>}{actions.error&&<ErrorPanel error={actions.error}/>}
  <div className="gh-work-board" style={{padding:14,display:'grid',gap:10}}>
   <strong>1 / Build evidence-grounded proposal</strong>
   <label className="field"><span>Allowlisted tool</span><select value={tool} onChange={e=>{setTool(e.target.value);setRequestKey(makeIdempotencyKey('gov'))}}>
    {tools.data?.tools.map(t=><option key={t.id} value={t.id}>{t.title} — {t.risk} / {t.configured?'configured':'disabled'}</option>)}
    {!tools.data&&<option value="incident_notification">Notify incident responders</option>}
   </select></label>
   <div className="toolbar"><label className="field"><span>Graph target ID</span><input value={target} onChange={e=>setTarget(e.target.value)}/></label>
    <label className="field"><span>Evidence IDs, comma-separated</span><input value={evidence} onChange={e=>setEvidence(e.target.value)} placeholder="EVD-AST-0001"/></label></div>
   <div className="toolbar"><label className="field"><span>Specialist (validated supervisor run required)</span><input value={agent} onChange={e=>setAgent(e.target.value)}/></label>
    <label className="field"><span>Supervisor run (optional; blank means human proposal)</span><input value={runId} onChange={e=>setRunId(e.target.value)} placeholder="SRUN-..."/></label></div>
   <label className="field"><span>{tool==='deployment_rollback'?'Rollback reason':'Notification message'}</span><textarea rows={2} value={message} onChange={e=>setMessage(e.target.value)}/></label>
   <label className="field"><span>Evidence-based rationale (minimum 20 characters)</span><textarea rows={2} value={reason} onChange={e=>setReason(e.target.value)} placeholder="Explain verified dependency, affected systems and why this operation is proposed"/></label>
   <div className="toolbar"><button disabled={!canEdit||create.isPending||reason.length<20||!evidence.trim()} onClick={()=>create.mutate()}>
    {create.isPending?'Validating…':'Create proposal (no external effect)'}</button><small className="muted">A read-only graph simulation is stored with every proposal.</small></div>
   {create.error&&<ErrorPanel error={create.error}/>}
  </div>
  <div className="gh-work-board" style={{padding:14,display:'grid',gap:9}}>
   <div className="toolbar"><strong>2 / Review durable actions</strong><button onClick={()=>actions.refetch()}>Refresh</button></div>
   {actions.data?.items.length===0&&<p className="muted">No governed proposals yet.</p>}
   <div className="toolbar">{actions.data?.items.map(a=><button key={a.id} className={selected===a.id?'primary':''} onClick={()=>setSelected(a.id)}>
    {a.tool_id} · {a.status} · {a.id.slice(-8)}</button>)}</div>
   {selected&&!actions.data?.items.some(x=>x.id===selected)&&<button onClick={()=>setSelected(selected)}>Selected: {selected}</button>}
   {detail.error&&<ErrorPanel error={detail.error}/>}{preview.error&&<ErrorPanel error={preview.error}/>}
   {selectedAction&&<div style={{display:'grid',gap:10}}>
    <strong>{selectedAction.tool_id} → {selectedAction.target_id}</strong>
    <p>State: <b>{selectedAction.status}</b> · Risk: {selectedAction.risk} · Initiator: {selectedAction.initiator} · Agent: {selectedAction.agent_id}</p>
    <p>{selectedAction.rationale}</p>
    <div className="toolbar">{selectedAction.evidence_ids.map(e=><Link key={e} to={'/entities/'+encodeURIComponent(e)}>{e}</Link>)}</div>
    <p><strong>Current policy gate:</strong> {preview.data?.current_authorization.allowed?'ALLOW (evidence and policy checks passed)':'BLOCKED / NEEDS REVIEW'}</p>
    {!!preview.data?.current_authorization.violations.length&&<p role="alert">{preview.data.current_authorization.violations.join(' · ')}</p>}
    <p><strong>Simulation:</strong> {preview.data?.simulation.baseline.impacted.length??'?'} baseline systems → {preview.data?.simulation.counterfactual.impacted.length??'?'} hypothetical systems. Predictions are graph-only.</p>
    <p><strong>Connector:</strong> {preview.data?.connector_configured?'configured; requires human approval':'not configured; cannot execute'}</p>
    <div className="toolbar">
     {selectedAction.status==='PROPOSED'&&<button disabled={!canEdit||mutate.isPending} onClick={()=>mutate.mutate({actionId:selected,op:'request-approval'})}>Request human approval</button>}
     {selectedAction.status==='PENDING_APPROVAL'&&<><label className="field"><span>Approver decision reason</span><input value={approvalReason} onChange={e=>setApprovalReason(e.target.value)}/></label>
      <button disabled={!canApprove||mutate.isPending||approvalReason.length<12} onClick={()=>mutate.mutate({actionId:selected,op:'approve'})}>Approve (separate authorized person)</button>
      <button disabled={!canApprove||mutate.isPending||approvalReason.length<12} onClick={()=>mutate.mutate({actionId:selected,op:'reject'})}>Reject</button></>}
     {selectedAction.status==='APPROVED'&&<button disabled={!canExecute||mutate.isPending||!preview.data?.connector_configured} onClick={()=>{
      if(window.confirm('Confirm a REAL external side effect. Have you checked the target and approval?'))mutate.mutate({actionId:selected,op:'execute'})
     }}>Execute through approved connector</button>}
     {['AWAITING_VERIFICATION','OUTCOME_UNKNOWN','EXECUTING'].includes(selectedAction.status)&&<button disabled={!canExecute||mutate.isPending} onClick={()=>mutate.mutate({actionId:selected,op:'verify'})}>Read back external outcome (no retry)</button>}
     {['OUTCOME_UNKNOWN','FAILED','STALE_PRECONDITION'].includes(selectedAction.status)&&<button disabled={!canExecute||mutate.isPending} onClick={()=>mutate.mutate({actionId:selected,op:'escalate'})}>Escalate to human review</button>}
     {['COMPLETED','FAILED'].includes(selectedAction.status)&&<button disabled={!canExecute||learn.isPending} onClick={()=>learn.mutate(selected)}>Reconcile verified outcome to learning</button>}
    </div>
    {selectedAction.failure&&<p role="alert">{selectedAction.failure}</p>}
    {selectedAction.learning_warning&&<p role="alert">{selectedAction.learning_warning}</p>}
    {mutate.error&&<ErrorPanel error={mutate.error}/>}{learn.error&&<ErrorPanel error={learn.error}/>}
    {selectedAction.post_action_verification&&<p><strong>Independent outcome:</strong> {JSON.stringify(selectedAction.post_action_verification.connector_receipt)}</p>}
    <div><strong>Immutable audit entries ({detail.data?.audit.length})</strong><ol>{detail.data?.audit.map((event,i)=><li key={i}><code>{event.type}</code> · {event.actor} · {event.occurred_at||'time unavailable'}</li>)}</ol></div>
   </div>}
  </div>
  <p className="technical-secondary">Only configured, HTTPS allowlisted receiver adapters can cause side effects. Approval is time-limited and cannot come from the proposing principal or originating specialist. A remote timeout becomes OUTCOME_UNKNOWN; it is never silently retried. Completion requires independent authenticated connector readback.</p>
 </section>
}
