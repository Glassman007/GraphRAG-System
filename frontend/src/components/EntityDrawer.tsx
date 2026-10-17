import { Link } from 'react-router-dom'
import { JsonPanel } from './JsonPanel'
export function EntityDrawer({ value, onClose, onExpand, expanding=false }: { value?: any; onClose:()=>void; onExpand?: (id:string)=>void; expanding?: boolean }) {
  if(!value) return null
  const raw=value.raw || value.data || value
  const id=raw?.id || value.id
  return <aside className="drawer"><div className="toolbar"><h3>Selected object</h3><button type="button" onClick={onClose}>Close</button></div><div><strong>{id}</strong></div><div className="muted">{value.type || raw?._labels?.join(', ')}</div><div className="toolbar">{id && <Link to={`/entities/${encodeURIComponent(id)}`}>Open entity</Link>}{id&&onExpand&&<button type="button" disabled={expanding} onClick={()=>onExpand(String(id))}>{expanding?'Expanding…':'Expand neighbors'}</button>}</div><JsonPanel value={raw}/></aside>
}
