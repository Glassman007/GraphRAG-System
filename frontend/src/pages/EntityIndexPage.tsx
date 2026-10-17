import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { searchEntities } from '../api/entities'
import { DataTable } from '../components/DataTable'
import { EmptyState,ErrorPanel,LoadingPanel } from '../components/AsyncState'
export function EntityIndexPage(){const {config}=useAuth();const [term,setTerm]=useState('');const q=useQuery({queryKey:['entity-search',term],queryFn:({signal})=>searchEntities(config,term,50,signal),enabled:term.length>0});return <section><h2>Entities</h2><div className="panel"><label className="field"><span>Search canonical graph</span><input value={term} onChange={e=>setTerm(e.target.value)} placeholder="System, person, team, project or ID"/></label></div>{!term?<EmptyState title="Enter an entity name or canonical ID"/>:q.isLoading?<LoadingPanel/>:q.error?<ErrorPanel error={q.error}/>:<DataTable rows={q.data?.items||[]} rowKey={(r:any)=>r.id} columns={[{key:'id',header:'ID',render:(r:any)=><Link to={`/entities/${r.id}`}>{r.id}</Link>},{key:'type',header:'Type',render:(r:any)=>(r._labels||[]).filter((x:string)=>x!=='Entity').join(', ')},{key:'name',header:'Name',render:(r:any)=>r.name||r.title||r.display_name||'—'}]}/>}</section>}
