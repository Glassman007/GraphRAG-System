import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { getSituation,getSituationContext,getSituationTimeline,getSituationClaims,getSituationEvidence,getSituationTasks,investigateSituation } from '../api/situations'
import { LoadingPanel,ErrorPanel,EmptyState } from '../components/AsyncState'
import { JsonPanel } from '../components/JsonPanel'
import { GraphView } from '../components/GraphView'
import { EntityDrawer } from '../components/EntityDrawer'
import { contextToGraph } from '../graph/adapters'
import { AsOfPicker } from '../components/AsOfPicker'
import { StatusBadge } from '../components/StatusBadge'

const tabs=['overview','timeline','knowledge','tasks','impact'] as const
export function SituationDetailPage(){
  const {situationId=''}=useParams(); const {config,hasPermission}=useAuth(); const nav=useNavigate(); const qc=useQueryClient(); const [sp,setSp]=useSearchParams(); const tab=(sp.get('tab')||'overview') as typeof tabs[number]; const asOf=sp.get('as_of')||''; const [selected,setSelected]=useState<any>(); const [question,setQuestion]=useState('')
  const situation=useQuery({queryKey:['situation',situationId,asOf],queryFn:({signal})=>getSituation(config,situationId,asOf||undefined,signal),enabled:!!situationId})
  const context=useQuery({queryKey:['situation-context',situationId,asOf],queryFn:({signal})=>getSituationContext(config,situationId,asOf||undefined,signal),enabled:!!situationId})
  const timeline=useQuery({queryKey:['situation-timeline',situationId],queryFn:({signal})=>getSituationTimeline(config,situationId,signal),enabled:tab==='timeline'})
  const claims=useQuery({queryKey:['situation-claims',situationId],queryFn:({signal})=>getSituationClaims(config,situationId,signal),enabled:tab==='knowledge'})
  const evidence=useQuery({queryKey:['situation-evidence',situationId],queryFn:({signal})=>getSituationEvidence(config,situationId,signal),enabled:tab==='knowledge'})
  const tasks=useQuery({queryKey:['situation-tasks',situationId],queryFn:({signal})=>getSituationTasks(config,situationId,signal),enabled:tab==='tasks'})
  const create=useMutation({mutationFn:()=>investigateSituation(config,situationId,{question,seed_entity_ids:[situationId],as_of:asOf||null}),onSuccess:(r:any)=>{qc.invalidateQueries({queryKey:['situation-context',situationId]});nav(`/investigations/${r.id}`)}})
  if(situation.isLoading||context.isLoading)return <LoadingPanel/>; if(situation.error)return <ErrorPanel error={situation.error}/>; if(context.error)return <ErrorPanel error={context.error}/>
  const graph=contextToGraph(context.data||{})
  return <section><div className="page-header"><div><h2>{situation.data?.name||situationId}</h2><div><StatusBadge value={situation.data?.status}/> <span className="muted">{situationId}</span></div></div><AsOfPicker value={asOf} onChange={v=>setSp(prev=>{const n=new URLSearchParams(prev);v?n.set('as_of',v):n.delete('as_of');return n})}/></div><div className="tabs">{tabs.map(t=><button key={t} className={tab===t?'active':''} onClick={()=>setSp(prev=>{const n=new URLSearchParams(prev);n.set('tab',t);return n})}>{t}</button>)}</div>{tab==='overview'&&<div className="three-col"><JsonPanel title="Situation" value={situation.data}/><div className="panel graph-panel"><h3>Context graph</h3><GraphView graph={graph} onNode={setSelected}/></div><EntityDrawer value={selected} onClose={()=>setSelected(undefined)}/></div>}{tab==='timeline'&&(timeline.isLoading?<LoadingPanel/>:timeline.error?<ErrorPanel error={timeline.error}/>:<JsonPanel title="Timeline" value={timeline.data}/>)}{tab==='knowledge'&&<div className="grid-2"><JsonPanel title="Claims" value={claims.data}/><JsonPanel title="Evidence" value={evidence.data}/></div>}{tab==='tasks'&&(tasks.data?.items?.length?<div className="list">{tasks.data.items.map((t:any)=><Link key={t.id} to={`/work?task=${t.id}`}>{t.id} — {t.name||t.title}</Link>)}</div>:<EmptyState title="No tasks"/>)}{tab==='impact'&&<div className="panel"><h3>Affected entities</h3>{(context.data?.affected_entities||[]).map((e:any)=><div key={e.id}><Link to={`/entities/${e.id}?tab=blast-radius`}>{e.id} — {e.name||e.title}</Link></div>)}</div>}<section className="panel"><h3>Start investigation</h3><textarea rows={3} value={question} onChange={e=>setQuestion(e.target.value)} placeholder="Question or investigation goal"/><button disabled={!question||!hasPermission('CREATE_INVESTIGATION')||create.isPending} onClick={()=>create.mutate()}>Run Investigation</button>{create.error&&<ErrorPanel error={create.error}/>}</section></section>
}
