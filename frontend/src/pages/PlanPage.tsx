import {useMemo,useState} from 'react'
import {Link,useNavigate,useParams} from 'react-router-dom'
import {useQuery} from '@tanstack/react-query'
import {useAuth} from '../auth/AuthContext'
import {getPlan} from '../api/plans'
import {getPlanTopology} from '../api/workInsights'
import {LoadingPanel,ErrorPanel} from '../components/AsyncState'
import {ReadableRecord} from '../components/ReadableRecord'
import {WorkPlanTopology} from '../components/work/WorkViews'
import {displayName} from '../presentation'
import {WorkTimeline} from '../components/work/WorkViews'
import {getTaskInsights} from '../api/workInsights'

function PlanSelectedTask({id}:{id:string}){
 const {config}=useAuth();const q=useQuery({queryKey:['plan-inline-task',config.tenantId,id],queryFn:({signal})=>getTaskInsights(config,id,signal)})
 return <section className="panel"><h3>Selected task</h3>{q.isLoading?<LoadingPanel/>:q.error?<ErrorPanel error={q.error}/>:<><h4>{displayName(q.data?.task||{id})}</h4><p>{q.data?.task?.objective}</p><p className="muted">{q.data?.findings?.length||0} recorded findings · {q.data?.executions?.length||0} executions</p><WorkTimeline events={q.data?.events}/></>}</section>
}
export function PlanPage(){
 const {planId=''}=useParams(),{config}=useAuth(),navigate=useNavigate(),[selected,setSelected]=useState('')
 const plan=useQuery({queryKey:['plan',config.tenantId,planId],queryFn:({signal})=>getPlan(config,planId,signal)})
 const topo=useQuery({queryKey:['work-topology',config.tenantId,planId],queryFn:({signal})=>getPlanTopology(config,planId,signal)})
 const id=useMemo(()=>String(plan.data?.plan?.id||planId),[plan.data,planId])
 if(plan.isLoading||topo.isLoading)return <LoadingPanel label="Loading work plan and task dependencies…"/>
 if(plan.error||topo.error)return <ErrorPanel error={plan.error||topo.error}/>
 return <section><div className="page-header"><div><div className="eyebrow">CONNECTED WORK PLAN · {id}</div><h2>{displayName(plan.data?.plan||{id})}</h2><p>{plan.data?.plan?.goal||'Plan objective not recorded'}</p></div><Link to="/work?tab=plans">← Plans</Link></div><WorkPlanTopology value={topo.data} onTask={setSelected}/><section className="panel"><h3>Specialist task breakdown</h3><p className="muted">Each task is derived by the backend from the situation and available graph evidence; specialist assignments are candidate recommendations until claimed.</p><div className="gh-work-task-list">{(plan.data?.tasks||[]).map((detail:any)=>{const t=detail.task||detail;return <div className="gh-work-wave" key={t.id}><h4>{displayName(t)}</h4><p>{t.objective||''}</p><small>{t.priority||'—'} · {t.status||'—'} · {t.task_type||'—'}</small><div className="toolbar"><button onClick={()=>setSelected(t.id)}>Inspect</button><button onClick={()=>navigate(`/work?tab=tasks&task=${encodeURIComponent(t.id)}`)}>Open workbench →</button></div></div>})}</div></section>{selected&&<div><PlanSelectedTask id={selected}/><p><Link to={`/work?tab=tasks&task=${encodeURIComponent(selected)}`}>Open full coordination and evidence →</Link></p></div>}<ReadableRecord title="Plan validation" value={plan.data?.validation}/></section>
}
