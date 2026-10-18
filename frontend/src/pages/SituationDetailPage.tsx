import { useMemo,useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { getSituation,getSituationContext,getSituationTimeline,getSituationClaims,getSituationEvidence,getSituationTasks,investigateSituation } from '../api/situations'
import { LoadingPanel,ErrorPanel,EmptyState } from '../components/AsyncState'
import { GraphView } from '../components/GraphView'
import { contextToGraph } from '../graph/adapters'
import { AsOfPicker } from '../components/AsOfPicker'
import { StatusBadge } from '../components/StatusBadge'
import { ReadableRecord,ObjectLink } from '../components/ReadableRecord'
import { TechnicalDetails } from '../components/TechnicalDetails'
import { displayName } from '../presentation'

const tabs=['overview','timeline','knowledge','tasks','impact'] as const
export function SituationDetailPage(){
  const {situationId=''}=useParams();const {config,hasPermission}=useAuth();const nav=useNavigate(),qc=useQueryClient();const [sp,setSp]=useSearchParams();const tab=(sp.get('tab')||'overview') as typeof tabs[number],asOf=sp.get('as_of')||'';const [question,setQuestion]=useState('')
  const situation=useQuery({queryKey:['situation',config.tenantId,situationId,asOf],queryFn:({signal})=>getSituation(config,situationId,asOf||undefined,signal),enabled:!!situationId})
  const context=useQuery({queryKey:['situation-context',config.tenantId,situationId,asOf],queryFn:({signal})=>getSituationContext(config,situationId,asOf||undefined,signal),enabled:!!situationId})
  const timeline=useQuery({queryKey:['situation-timeline',config.tenantId,situationId],queryFn:({signal})=>getSituationTimeline(config,situationId,signal),enabled:tab==='timeline'})
  const claims=useQuery({queryKey:['situation-claims',config.tenantId,situationId],queryFn:({signal})=>getSituationClaims(config,situationId,signal),enabled:tab==='knowledge'})
  const evidence=useQuery({queryKey:['situation-evidence',config.tenantId,situationId],queryFn:({signal})=>getSituationEvidence(config,situationId,signal),enabled:tab==='knowledge'})
  const tasks=useQuery({queryKey:['situation-tasks',config.tenantId,situationId],queryFn:({signal})=>getSituationTasks(config,situationId,signal),enabled:tab==='tasks'})
  const create=useMutation({mutationFn:()=>investigateSituation(config,situationId,{question,seed_entity_ids:[situationId],as_of:asOf||null}),onSuccess:(r:any)=>{qc.invalidateQueries({queryKey:['situation-context']});nav(`/investigations/${encodeURIComponent(r.id)}`)}})
  const graph=useMemo(()=>contextToGraph(context.data||{}),[context.data]);
  if(situation.isLoading||context.isLoading)return <LoadingPanel/>;if(situation.error)return <ErrorPanel error={situation.error}/>;if(context.error)return <ErrorPanel error={context.error}/>
  const data=situation.data||{}, affected=context.data?.affected_entities||[]
  return <section><div className="page-header"><div><h2>{displayName(data)}</h2><div className="toolbar"><StatusBadge value={data.status}/>{data.severity&&<StatusBadge value={data.severity}/>}<span className="technical-secondary">{situationId}</span></div></div><AsOfPicker value={asOf} onChange={v=>setSp(prev=>{const n=new URLSearchParams(prev);v?n.set('as_of',v):n.delete('as_of');return n})}/></div>
    <nav className="gh-context-nav" aria-label="Related features"><Link to="/situations">All situations</Link><Link to={`/company-brain?tab=processes&scope=${encodeURIComponent(situationId)}`}>Company Brain</Link><Link to={`/simulations?situation=${encodeURIComponent(situationId)}`}>Simulate impact</Link><Link to={`/work?tab=tasks`}>Tasks and agents</Link><Link to="/knowledge">Knowledge</Link><Link to="/investigations">Investigations</Link></nav>
    <div className="tabs">{tabs.map(t=><button key={t} className={tab===t?'active':''} onClick={()=>setSp(prev=>{const n=new URLSearchParams(prev);n.set('tab',t);return n})}>{t}</button>)}</div>
    {tab==='overview'&&<div className="gh-situation-layout"><section className="panel"><h3>Situation summary</h3><p>{data.description||'No description has been recorded.'}</p><dl className="kv"><div className="gh-kv-row"><dt>Severity</dt><dd>{data.severity||'Unknown'}</dd></div><div className="gh-kv-row"><dt>Occurred</dt><dd>{data.occurred_at||data.created_at||'Not recorded'}</dd></div><div className="gh-kv-row"><dt>Owner</dt><dd>{data.owner_name||data.owner_id||'Not assigned'}</dd></div></dl><h4>Affected systems and teams</h4>{affected.length?affected.map((e:any)=><ObjectLink key={e.id} item={e}/>):<p className="muted">None linked in this context.</p>}<TechnicalDetails><pre>{JSON.stringify(data,null,2)}</pre></TechnicalDetails></section><div className="panel graph-panel"><h3>Context graph</h3><GraphView graph={graph}/></div></div>}
    {tab==='timeline'&&(timeline.isLoading?<LoadingPanel/>:timeline.error?<ErrorPanel error={timeline.error}/>:<ReadableRecord title="Incident timeline" value={timeline.data?.events||[]}/>)}
    {tab==='knowledge'&&<div className="grid-2"><div>{claims.isLoading?<LoadingPanel/>:claims.error?<ErrorPanel error={claims.error}/>:<ReadableRecord title="Claims" value={claims.data}/>}</div><div>{evidence.isLoading?<LoadingPanel/>:evidence.error?<ErrorPanel error={evidence.error}/>:<ReadableRecord title="Evidence" value={evidence.data}/>}</div></div>}
    {tab==='tasks'&&(tasks.isLoading?<LoadingPanel/>:tasks.error?<ErrorPanel error={tasks.error}/>:tasks.data?.items?.length?<ReadableRecord title="Connected tasks" value={tasks.data}/>:<EmptyState title="No linked tasks" detail="Start an investigation or inspect Work to create operational tasks."/>)}
    {tab==='impact'&&<section className="panel"><h3>Affected systems, projects and teams</h3>{affected.length?affected.map((e:any)=><div key={e.id}><ObjectLink item={e}/><Link to={`/entities/${encodeURIComponent(e.id)}?tab=blast-radius`}>Explore blast radius</Link></div>):<EmptyState title="No impact links returned"/>}<TechnicalDetails><pre>{JSON.stringify(context.data,null,2)}</pre></TechnicalDetails></section>}
    <section className="panel"><h3>Start investigation</h3><p>Open an evidence-led investigation grounded in this situation and its connected entities.</p><textarea aria-label="Investigation goal" rows={3} value={question} onChange={e=>setQuestion(e.target.value)} placeholder="What should the investigation establish?"/><button disabled={!question.trim()||!hasPermission('CREATE_INVESTIGATION')||create.isPending} onClick={()=>create.mutate()}>{create.isPending?'Creating…':'Run investigation'}</button>{create.error&&<ErrorPanel error={create.error}/>}</section>
  </section>
}
