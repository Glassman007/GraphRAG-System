import { Link } from 'react-router-dom'
import { ReadableRecord } from './ReadableRecord'
import { displayName, objectType, presentRelationship } from '../presentation'
export function EntityDrawer({ value, onClose, onExpand, expanding=false }: { value?: any; onClose:()=>void; onExpand?: (id:string)=>void; expanding?: boolean }) {
  if(!value)return null
  const raw=value.raw||value.data||value
  const isEdge=!!value.source&&!!value.target
  const id=raw?.id||value.id
  return <aside className="drawer"><div className="toolbar"><h3>{isEdge?'Connected relationship':'Selected object'}</h3><button type="button" onClick={onClose}>Close</button></div>
    <p><strong>{isEdge?presentRelationship(value.type,value.source,value.target).phrase:displayName(raw)}</strong></p>
    <p className="technical-secondary">{isEdge?`${value.source} → ${value.target}`:`${objectType(raw)} · ${id}`}</p>
    <div className="toolbar">{isEdge?<><Link to={`/entities/${encodeURIComponent(value.source)}`}>Source</Link><Link to={`/entities/${encodeURIComponent(value.target)}`}>Target</Link></>:<>{id&&<Link to={`/entities/${encodeURIComponent(id)}`}>Details and provenance</Link>}{id&&onExpand&&<button type="button" disabled={expanding} onClick={()=>onExpand(String(id))}>{expanding?'Expanding…':'Expand neighbors'}</button>}</>}</div>
    <ReadableRecord value={raw}/>
  </aside>
}
