import { NavLink, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { getReady } from '../api/system'
import { useTechnicalMode } from '../presentation/TechnicalModeContext'

const primary=[['Situations','/situations'],['Investigations','/investigations'],['Work','/work'],['Knowledge','/knowledge'],['Company Brain','/company-brain'],['Sources','/sources']]
const advanced=[['Entities','/entities'],['Decisions','/decisions'],['Simulations','/simulations'],['Anomalies','/anomalies']]
export function AppShell(){
  const auth=useAuth(); const tech=useTechnicalMode(); const [editing,setEditing]=useState(false); const [token,setToken]=useState(auth.config.token); const [tenant,setTenant]=useState(auth.config.tenantId); const [base,setBase]=useState(auth.config.baseUrl)
  const ready=useQuery({queryKey:['ready',auth.config.baseUrl],queryFn:({signal})=>getReady(auth.config,signal),retry:false,refetchInterval:30_000})
  return <div className="app-shell"><aside className="sidebar"><h1>GraphHacks</h1><div className="muted">Company Brain</div><nav>{primary.map(([label,to])=><NavLink key={to} to={to} className={({isActive})=>isActive?'active':''}>{label}</NavLink>)}<div className="nav-section">Advanced</div>{advanced.map(([label,to])=><NavLink key={to} to={to} className={({isActive})=>isActive?'active':''}>{label}</NavLink>)}</nav></aside><main className="main"><header className="topbar"><div><strong>{auth.session?.subject || 'Not authenticated'}</strong><span className="muted"> · {auth.config.tenantId}</span></div><div className="toolbar"><label className="toggle"><input type="checkbox" checked={tech.technicalMode} onChange={e=>tech.setTechnicalMode(e.target.checked)}/>Technical Mode</label><span className={ready.data?.ready?'ready':'not-ready'}>{ready.data?.ready?'Backend ready':'Backend unavailable'}</span><button type="button" onClick={()=>setEditing(v=>!v)}>API config</button></div></header>{editing&&<section className="panel config-panel"><label className="field"><span>API base URL</span><input value={base} onChange={e=>setBase(e.target.value)} placeholder="blank uses Vite proxy" /></label><label className="field"><span>Tenant</span><input value={tenant} onChange={e=>setTenant(e.target.value)} /></label><label className="field"><span>Bearer token</span><input value={token} onChange={e=>setToken(e.target.value)} type="password" /></label><button type="button" onClick={()=>{auth.setConfig({baseUrl:base.replace(/\/$/,''),tenantId:tenant,token});setEditing(false)}}>Apply</button></section>}<Outlet/></main></div>
}
