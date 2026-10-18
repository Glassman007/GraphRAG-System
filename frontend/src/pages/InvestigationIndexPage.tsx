import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { EntityPicker } from '../components/EntityPicker'
export function InvestigationIndexPage(){const [id,setId]=useState('');const nav=useNavigate();return <section><h2>Investigations</h2><div className="panel"><p>Investigations are created from a Situation. Pick an existing investigation by name, or start a new one from a situation. Exact IDs also work.</p><div className="toolbar"><EntityPicker label="Investigation" kind="Investigation" value={id} onChange={setId}/><button disabled={!id} onClick={()=>nav(`/investigations/${encodeURIComponent(id)}`)}>Open</button></div><Link to="/situations">Choose a situation to investigate</Link></div></section>}
