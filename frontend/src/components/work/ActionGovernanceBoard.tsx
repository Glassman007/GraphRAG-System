import {useState} from 'react'
import {useQuery,useMutation,useQueryClient} from '@tanstack/react-query'
import {useAuth} from '../../auth/AuthContext'
import {listActions,getAction,getActionGovernance,getActionAttempts,executeAction} from '../../api/actions'
import {EntityPicker} from '../EntityPicker'
import {ErrorPanel,LoadingPanel,EmptyState} from '../AsyncState'
import {ConfirmationDialog} from '../ConfirmationDialog'
import {ReadableRecord} from '../ReadableRecord'
import {StatusBadge} from '../StatusBadge'
import {displayName} from '../../presentation'

export function ActionGovernanceBoard(){
 const {config,hasPermission}=useAuth(),qc=useQueryClient()
 const [selected,setSelected]=useState(''),[agent,setAgent]=useState(''),[confirm,setConfirm]=useState(false)
 const actions=useQuery({queryKey:['work-actions',config.tenantId],queryFn:({signal})=>listActions(config,{limit:100},signal)})
 const detail=useQuery({queryKey:['work-action',config.tenantId,selected],queryFn:({signal})=>getAction(config,selected,signal),enabled:!!selected})
 const gov=useQuery({queryKey:['work-governance',config.tenantId,selected,agent],queryFn:({signal})=>getActionGovernance(config,selected,signal),enabled:!!selected})
 const attempts=useQuery({queryKey:['work-attempts',config.tenantId,selected],queryFn:({signal})=>getActionAttempts(config,selected,signal),enabled:!!selected})
 const execute=useMutation({mutationFn:()=>executeAction(config,selected,agent),onSuccess:()=>{qc.invalidateQueries({queryKey:['work-actions']});qc.invalidateQueries({queryKey:['work-action']});qc.invalidateQueries({queryKey:['work-governance']});qc.invalidateQueries({queryKey:['work-attempts']})}})
 if(actions.isLoading)return <LoadingPanel/>
 if(actions.error)return <ErrorPanel error={actions.error}/>
 return <div className="gh-work-board"><section className="panel"><h3>Governed action register</h3><p className="muted">Statuses and decisions come from graph records. Listing does not authorize execution.</p><div className="gh-work-action-list">{(actions.data?.items||[]).map((a:any)=><button key={a.id} className={selected===a.id?'active':''} onClick={()=>setSelected(a.id)}><span>{displayName(a)}</span><StatusBadge value={String(a.status||'PROPOSED')}/><small>{a.id}</small></button>)}</div>{!actions.data?.items?.length&&<EmptyState title="No actions yet" detail="Generate a plan, start eligible work and propose an action to see governance history."/>}{actions.data?.has_more&&<p className="muted">First 100 records shown; narrow the data at the source for older actions.</p>}</section>
 {!!selected&&<div className="grid-2"><div><ReadableRecord title="Action proposal" value={detail.data}/>{detail.error&&<ErrorPanel error={detail.error}/>}</div><div><ReadableRecord title="Governance and approval conditions" value={gov.data}/>{gov.error&&<ErrorPanel error={gov.error}/>}</div><div><ReadableRecord title="Execution / retry attempts" value={attempts.data?.items||[]}/>{attempts.error&&<ErrorPanel error={attempts.error}/>}</div><section className="panel"><h3>Execute only after governance</h3><EntityPicker label="Executing agent" kind="Agent" value={agent} onChange={setAgent}/><p className="muted">The backend rechecks approval, evidence, agent permissions, resource locks and idempotency. Clicking execute may cause real effects in configured environments.</p><button disabled={!agent||!hasPermission('EXECUTE_ACTION')||execute.isPending} onClick={()=>setConfirm(true)}>Request governed execution</button>{execute.error&&<ErrorPanel error={execute.error}/>} {execute.data&&<ReadableRecord title="Execution response" value={execute.data}/>}</section></div>}
 <ConfirmationDialog open={confirm} title="Execute action through governance" onCancel={()=>setConfirm(false)} onConfirm={()=>{setConfirm(false);execute.mutate()}}><p>Check the selected action, scope and agent carefully. This can create side effects; the backend will enforce all governance gates.</p></ConfirmationDialog>
 </div>
}
