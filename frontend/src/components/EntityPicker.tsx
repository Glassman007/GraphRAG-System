import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { browseEntities, searchEntities } from '../api/entities'
import { displayName, objectType } from '../presentation'

const allowed = ['Department','Team','Person','System','Project','Incident','Agent','Task','Policy','Decision','Change','Action','Evidence','Claim','Investigation','Plan']
export function useDebounced<T>(value:T, ms=300) {
  const [debounced,setDebounced]=useState(value)
  useEffect(()=>{const timer=setTimeout(()=>setDebounced(value),ms);return ()=>clearTimeout(timer)},[value,ms])
  return debounced
}

/** Canonical IDs remain editable. Suggestions are tenant-scoped graph search results, never mock data. */
export function EntityPicker({label,value,onChange,kind,placeholder,required=false}:{label:string;value:string;onChange:(id:string)=>void;kind?:string;placeholder?:string;required?:boolean}) {
  const {config}=useAuth()
  const [text,setText]=useState(value)
  const [selected,setSelected]=useState<{id:string;name:string}|null>(null)
  const [active,setActive]=useState(false)
  useEffect(()=>{setText(selected?.id===value?selected.name:value)},[value,selected])
  const debounced=useDebounced(text,250)
  const q=useQuery({queryKey:['picker',config.tenantId,kind||'',debounced],queryFn:({signal})=>debounced.trim()?searchEntities(config,debounced.trim(),50,signal):browseEntities(config,{kind,limit:50},signal),enabled:active,retry:false})
  const options=useMemo(()=>((q.data?.items||[]) as any[]).filter(e=>!kind||objectType(e)===kind).slice(0,30),[q.data,kind])
  return <div className="field gh-picker"><label><span>{label}{required?' *':''}</span><input aria-label={label} value={text} placeholder={placeholder||`Find ${kind?.toLowerCase()||'an entity'} by name or ID`} onChange={e=>{setSelected(null);setText(e.target.value);onChange(e.target.value);setActive(true)}} onFocus={()=>setActive(true)} onKeyDown={e=>{if(e.key==='Escape')setActive(false)}} autoComplete="off" /></label>
    {active&&<div className="gh-picker-options" role="listbox" aria-label={`${label} suggestions`}>
      {q.isLoading?<p className="muted">Looking up organization data…</p>:q.error?<p className="muted">Suggestions unavailable; you can still enter an exact ID.</p>:options.length?options.map(item=><button type="button" key={item.id} role="option" aria-selected={value===item.id} onClick={()=>{setSelected({id:item.id,name:displayName(item)});setText(displayName(item));onChange(item.id);setActive(false)}}><strong>{displayName(item)}</strong><span>{objectType(item)} · {item.id}</span></button>):<p className="muted">No matches. Enter an exact canonical ID if you know it.</p>}
      <button type="button" className="gh-picker-dismiss" onClick={()=>setActive(false)}>Close suggestions</button>
    </div>}
    {value&&value!==text&&<span className="technical-secondary">Selected canonical ID: {value}</span>}
  </div>
}
export const browseKinds=allowed
