import { Link } from 'react-router-dom'
import { TechnicalDetails } from './TechnicalDetails'
import { displayName,objectType,presentStatus } from '../presentation'
import { StatusBadge } from './StatusBadge'
import { EmptyState } from './AsyncState'

const skip=new Set(['_labels','id','tenant_id','name','title','display_name','description','summary','status','severity','statement','assertion'])
const fieldNames:Record<string,string>={occurred_at:'Occurred',created_at:'Created',updated_at:'Updated',valid_from:'Effective from',valid_until:'Effective until',owner_id:'Owner',owner_name:'Owner',source_id:'Source',source_name:'Source',source_type:'Source type',observed_at:'Observed',confidence:'Confidence',impact:'Impact',assigned_agent_id:'Assigned agent',incident_id:'Incident',situation_id:'Situation'}
const human=(key:string)=>fieldNames[key]||key.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())
function scalar(v:unknown):string {if(v===null||v===undefined||v==='')return 'Not recorded';if(typeof v==='boolean')return v?'Yes':'No';return String(v)}
export function ObjectLink({item}:{item:any}) {const id=String(item?.id||'');const kind=objectType(item||{});const route=kind==='Incident'?`/situations/${encodeURIComponent(id)}`:kind==='Claim'?`/claims/${encodeURIComponent(id)}`:kind==='Evidence'?`/evidence/${encodeURIComponent(id)}`:kind==='Decision'?`/decisions/${encodeURIComponent(id)}`:kind==='Plan'?`/plans/${encodeURIComponent(id)}`:kind==='Investigation'?`/investigations/${encodeURIComponent(id)}`:kind==='Task'?`/work?tab=tasks&task=${encodeURIComponent(id)}`:kind==='Agent'?'/work?tab=agents':`/entities/${encodeURIComponent(id)}`;return <div className="gh-record-link">{id?<Link to={route}><strong>{displayName(item)}</strong></Link>:<strong>{displayName(item)}</strong>}<span className="technical-secondary">{kind}{id?` · ${id}`:''}</span>{item?.description&&<p>{item.description}</p>}</div>}
export function ReadableRecord({value,title,empty='No records available',maxItems=60}:{value:any;title?:string;empty?:string;maxItems?:number}) {
  if(value===undefined||value===null)return <EmptyState title={empty}/>
  const items=Array.isArray(value)?value:Array.isArray(value.items)?value.items:Array.isArray(value.events)?value.events:[value]
  if(!items.length)return <EmptyState title={empty}/>
  return <div className="gh-records">{title&&<h3>{title}</h3>}{items.slice(0,maxItems).map((item:any,i:number)=>{
    if(item===null||typeof item!=='object')return <div className="panel" key={i}>{scalar(item)}</div>
    const collections=Object.entries(item).filter(([key,v])=>!key.startsWith('_')&&Array.isArray(v)&&v.length>0).slice(0,5)
    const entries=Object.entries(item).filter(([k,v])=>!skip.has(k)&&!k.startsWith('_')&&v!==null&&v!==undefined&&v!==''&&typeof v!=='object').slice(0,14)
    return <article className="panel gh-record" key={String(item.id||i)}><div className="gh-record-head"><div><ObjectLink item={item}/>{item.statement&&<p>{String(item.statement)}</p>}{item.summary&&<p>{String(item.summary)}</p>}</div><div>{item.status&&<StatusBadge value={presentStatus(item.status)}/>} {item.severity&&<StatusBadge value={item.severity}/>}</div></div>{entries.length>0&&<dl className="kv">{entries.map(([k,v])=><div className="gh-kv-row" key={k}><dt>{human(k)}</dt><dd>{scalar(v)}</dd></div>)}</dl>}{collections.map(([key,list])=><div key={key} className="gh-record-collection"><h4>{human(key)}</h4>{(list as unknown[]).slice(0,12).map((value:any,j:number)=><div key={j} className="gh-record-collection-item">{value&&typeof value==='object'?(value.id?<ObjectLink item={value}/>:<span>{String(value.summary||value.name||value.title||value.status||JSON.stringify(value).slice(0,200))}</span>):String(value)}</div>)}</div>)}<TechnicalDetails><pre>{JSON.stringify(item,null,2)}</pre></TechnicalDetails></article>
  })}{items.length>maxItems&&<p className="muted">Showing {maxItems} of {items.length} records.</p>}</div>
}
