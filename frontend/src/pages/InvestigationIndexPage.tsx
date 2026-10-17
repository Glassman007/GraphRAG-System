import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
export function InvestigationIndexPage(){const [id,setId]=useState('');const nav=useNavigate();return <section><h2>Investigations</h2><div className="panel"><p>Investigations are created from a Situation. Enter an existing investigation ID to inspect it.</p><div className="toolbar"><input value={id} onChange={e=>setId(e.target.value)} placeholder="INV-..."/><button disabled={!id} onClick={()=>nav(`/investigations/${encodeURIComponent(id)}`)}>Open</button></div></div></section>}
