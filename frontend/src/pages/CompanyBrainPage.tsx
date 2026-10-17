import { useMemo,useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation,useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { getProcess,getProcessTimeline,getPolicyDrift } from '../api/processes'
import { getCommitments,getOwnershipGaps,getBusFactor,getBottlenecks,getBridges,getCollisions } from '../api/risks'
import { getExpertise } from '../api/companyBrain'
import { runBusFactor } from '../api/simulations'
import { GraphView } from '../components/GraphView'
import { processToGraph } from '../graph/adapters'
import { JsonPanel } from '../components/JsonPanel'
import { ErrorPanel,EmptyState,LoadingPanel } from '../components/AsyncState'
import { AsOfPicker } from '../components/AsOfPicker'

const tabs=['processes','policy-drift','commitments','ownership-gaps','expertise','bus-factor','bottlenecks','bridges','duplicate-initiatives']
export function CompanyBrainPage(){
 const {config}=useAuth();const [sp,setSp]=useSearchParams();const tab=sp.get('tab')||'processes';const [scope,setScope]=useState('');const [policy,setPolicy]=useState('');const [asOf,setAsOf]=useState('');const [actor,setActor]=useState('')
 const process=useQuery({queryKey:['process',scope,asOf],queryFn:({signal})=>getProcess(config,scope,asOf||undefined,signal),enabled:(tab==='processes'||tab==='policy-drift')&&!!scope})
 const timeline=useQuery({queryKey:['process-timeline',scope,asOf],queryFn:({signal})=>getProcessTimeline(config,scope,asOf||undefined,signal),enabled:tab==='processes'&&!!scope})
 const drift=useQuery({queryKey:['policy-drift',scope,policy,asOf],queryFn:({signal})=>getPolicyDrift(config,scope,policy,asOf||undefined,signal),enabled:tab==='policy-drift'&&!!scope&&!!policy})
 const commitments=useQuery({queryKey:['commitments',asOf],queryFn:({signal})=>getCommitments(config,{as_of:asOf||undefined},signal),enabled:tab==='commitments'})
 const ownership=useQuery({queryKey:['ownership-gaps',asOf],queryFn:({signal})=>getOwnershipGaps(config,{as_of:asOf||undefined},signal),enabled:tab==='ownership-gaps'})
 const expertise=useQuery({queryKey:['expertise',asOf],queryFn:({signal})=>getExpertise(config,{as_of:asOf||undefined,limit:200},signal),enabled:tab==='expertise'})
 const bus=useQuery({queryKey:['bus-factor',asOf],queryFn:({signal})=>getBusFactor(config,{as_of:asOf||undefined},signal),enabled:tab==='bus-factor'})
 const bottlenecks=useQuery({queryKey:['bottlenecks',asOf],queryFn:({signal})=>getBottlenecks(config,{as_of:asOf||undefined},signal),enabled:tab==='bottlenecks'})
 const bridges=useQuery({queryKey:['bridges',asOf],queryFn:({signal})=>getBridges(config,{as_of:asOf||undefined},signal),enabled:tab==='bridges'})
 const collisions=useQuery({queryKey:['collisions',asOf],queryFn:({signal})=>getCollisions(config,{as_of:asOf||undefined},signal),enabled:tab==='duplicate-initiatives'})
 const simulate=useMutation({mutationFn:()=>runBusFactor(config,[actor],asOf||undefined)})
 const processGraph=useMemo(()=>processToGraph(process.data||{}),[process.data])
 const active=tab==='processes'?(scope?process:null):tab==='policy-drift'?(scope&&policy?drift:null):tab==='commitments'?commitments:tab==='ownership-gaps'?ownership:tab==='expertise'?expertise:tab==='bus-factor'?bus:tab==='bottlenecks'?bottlenecks:tab==='bridges'?bridges:collisions
 let content:any=null
 if(active?.isLoading) content=<LoadingPanel/>
 else if(active?.error) content=<ErrorPanel error={active.error}/>
 else if(tab==='processes')content=!scope?<EmptyState title="Enter a process/situation scope ID"/>:<div><div className="panel graph-panel"><GraphView graph={processGraph} layout="breadthfirst"/></div><div className="grid-2"><JsonPanel title="Reconstruction" value={process.data}/>{timeline.error?<ErrorPanel error={timeline.error}/>:timeline.isLoading?<LoadingPanel/>:<JsonPanel title="Timeline semantics" value={timeline.data}/>}</div></div>
 else if(tab==='policy-drift')content=<JsonPanel title="Policy-vs-practice drift" value={drift.data||{instruction:'Enter both scope and policy ID.'}}/>
 else if(tab==='commitments')content=<JsonPanel title="Commitments" value={commitments.data}/>
 else if(tab==='ownership-gaps')content=<JsonPanel title="Ownership gaps" value={ownership.data}/>
 else if(tab==='expertise')content=<><div className="notice">Expertise is organizational capability coverage, not employee ranking.</div><JsonPanel title="Expertise coverage" value={expertise.data}/></>
 else if(tab==='bus-factor')content=<div><JsonPanel title="Bus factor" value={bus.data}/><section className="panel"><label className="field"><span>Simulate actor unavailable</span><input value={actor} onChange={e=>setActor(e.target.value)}/></label><button disabled={!actor} onClick={()=>simulate.mutate()}>Simulate loss</button>{simulate.error&&<ErrorPanel error={simulate.error}/>} {simulate.isPending&&<LoadingPanel label="Running simulation…"/>}{simulate.data&&<JsonPanel value={simulate.data}/>}</section></div>
 else if(tab==='bottlenecks')content=<JsonPanel title="Bottlenecks" value={bottlenecks.data}/>
 else if(tab==='bridges')content=<JsonPanel title="Bridge risks" value={bridges.data}/>
 else if(tab==='duplicate-initiatives')content=<JsonPanel title="Initiative collisions" value={collisions.data}/>
 return <section><div className="page-header"><div><h2>Company Brain</h2><p>Processes, obligations and structural organizational risks.</p></div><AsOfPicker value={asOf} onChange={setAsOf}/></div><div className="tabs wrap">{tabs.map(t=><button key={t} className={tab===t?'active':''} onClick={()=>setSp(prev=>{const n=new URLSearchParams(prev);n.set('tab',t);return n})}>{t}</button>)}</div>{(tab==='processes'||tab==='policy-drift')&&<section className="panel filter-row"><label className="field"><span>Process scope ID</span><input value={scope} onChange={e=>setScope(e.target.value)} placeholder="Incident / plan / process scope"/></label>{tab==='policy-drift'&&<label className="field"><span>Policy ID</span><input value={policy} onChange={e=>setPolicy(e.target.value)}/></label>}</section>}{content}</section>
}
