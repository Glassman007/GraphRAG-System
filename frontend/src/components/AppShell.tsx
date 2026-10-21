import { Link, NavLink, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { getReady } from '../api/system'
import { useTechnicalMode } from '../presentation/TechnicalModeContext'
import { RainLayer, readRainPreference, writeRainPreference } from './RainLayer'

const primary=[['Agent Workspace','/agent-workspace'],['Demo Lab','/demo'],['Organization','/organization'],['Scenarios','/scenarios'],['Situations','/situations'],['Investigations','/investigations'],['Work','/work'],['Knowledge','/knowledge'],['Company Brain','/company-brain'],['Sources','/sources']]
const advanced=[['Entities','/entities'],['Decisions','/decisions'],['Simulations','/simulations'],['Anomalies','/anomalies']]
export function AppShell(){
  const auth=useAuth(); const tech=useTechnicalMode(); const [editing,setEditing]=useState(false); const [token,setToken]=useState(auth.config.token); const [tenant,setTenant]=useState(auth.config.tenantId); const [base,setBase]=useState(auth.config.baseUrl)
  const [rain,setRain]=useState(readRainPreference)
  const ready=useQuery({queryKey:['ready',auth.config.baseUrl],queryFn:({signal})=>getReady(auth.config,signal),retry:false,refetchInterval:30_000})
  const toggleRain=()=>setRain(on=>{writeRainPreference(!on);return !on})
  return <div className="app-shell">
    <RainLayer density={0.35} enabled={rain}/>
    <aside className="rail">
      <Link to="/" className="rail__brand" aria-label="GraphHacks home"><span className="rail__mark">GraphHacks</span><span className="rail__sub">Company Brain</span></Link>
      <nav aria-label="Primary">{primary.map(([label,to])=><NavLink key={to} to={to} className={({isActive})=>isActive?'active':''}>{label}</NavLink>)}<div className="nav-section">Advanced</div>{advanced.map(([label,to])=><NavLink key={to} to={to} className={({isActive})=>isActive?'active':''}>{label}</NavLink>)}</nav>
      <div className="rail__foot">Graph by <a href="https://www.falkordb.com" target="_blank" rel="noreferrer">FalkorDB</a></div>
    </aside>
    <main className="main">
      <header className="topbar">
        <div className="gh-statusline"><span><strong>{auth.session?.subject || 'Not authenticated'}</strong></span><span>{auth.config.tenantId}</span></div>
        <div className="toolbar">
          <span className={ready.data?.ready?'ready':'not-ready'}>{ready.data?.ready?'Backend ready':'Backend unavailable'}</span>
          <label className="toggle"><input type="checkbox" checked={tech.technicalMode} onChange={e=>tech.setTechnicalMode(e.target.checked)}/>Technical Mode</label>
          <button type="button" className="rain-toggle" aria-pressed={rain} onClick={toggleRain}>{rain?'Rain on':'Rain off'}</button>
          <button type="button" onClick={()=>setEditing(v=>!v)}>API config</button>
        </div>
      </header>
      {editing&&<section className="panel config-panel"><label className="field"><span>API base URL</span><input value={base} onChange={e=>setBase(e.target.value)} placeholder="blank uses Vite proxy" /></label><label className="field"><span>Tenant</span><input value={tenant} onChange={e=>setTenant(e.target.value)} /></label><label className="field"><span>Bearer token</span><input value={token} onChange={e=>setToken(e.target.value)} type="password" /></label><button type="button" className="primary" onClick={()=>{auth.setConfig({baseUrl:base.replace(/\/$/,''),tenantId:tenant,token});setEditing(false)}}>Apply</button></section>}
      <Outlet/>
    </main>
  </div>
}
