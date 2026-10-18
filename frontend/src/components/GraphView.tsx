import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import cytoscape from 'cytoscape'
import { useAuth } from '../auth/AuthContext'
import { getNeighbors } from '../api/entities'
import type { UiGraph } from '../graph/adapters'
import { mergeGraphs, relationshipsToGraph } from '../graph/adapters'
import { flowTrace, ghGraphStyle } from '../design/graphStyle'
import { EmptyState } from './AsyncState'
import { GraphLegend } from './GraphLegend'
import { useDebounced } from './EntityPicker'
import { displayName, presentRelationship } from '../presentation'
import { TechnicalDetails } from './TechnicalDetails'
import { Link } from 'react-router-dom'

type Layout = 'cose'|'breadthfirst'|'circle'
type GraphProps = {graph:UiGraph;onNode?:(data:any)=>void;onEdge?:(data:any)=>void;layout?:Layout;height?:number;traceIds?:Set<string>}
const inference=(data:any)=>data?.inferred===true||data?.is_inferred===true||data?.expected===true||String(data?.inference_type||'').toUpperCase()==='INFERRED'
export function GraphView({graph,onNode,onEdge,layout='cose',height=480,traceIds}:GraphProps) {
  const {config}=useAuth()
  const ref=useRef<HTMLDivElement>(null),cyRef=useRef<cytoscape.Core|null>(null)
  const onNodeRef=useRef(onNode),onEdgeRef=useRef(onEdge)
  onNodeRef.current=onNode;onEdgeRef.current=onEdge
  const [activeLayout,setLayout]=useState<Layout>(layout)
  const [hidden,setHidden]=useState<Set<string>>(new Set())
  const [search,setSearch]=useState(''),q=useDebounced(search.trim(),200)
  const [focus,setFocus]=useState(''),[picked,setPicked]=useState<any>(null)
  const [expanded,setExpanded]=useState<UiGraph>({nodes:[],edges:[]})
  const [expanding,setExpanding]=useState(false),[expandError,setExpandError]=useState('')
  const merged=useMemo(()=>mergeGraphs(graph,expanded),[graph,expanded])
  const types=useMemo(()=>Array.from(new Set(merged.nodes.map(n=>n.type))).sort(),[merged])
  const visible=useMemo(()=>{
    const nodes=merged.nodes.filter(n=>!hidden.has(n.type))
    const ids=new Set(nodes.map(n=>n.id))
    return {nodes,edges:merged.edges.filter(e=>ids.has(e.source)&&ids.has(e.target))}
  },[merged,hidden])
  const toggle=useCallback((t:string)=>setHidden(prev=>{const next=new Set(prev);next.has(t)?next.delete(t):next.add(t);return next}),[])
  const signature=useMemo(()=>JSON.stringify(visible),[visible])
  const traceSignature=useMemo(()=>[...(traceIds||[])].sort().join('|'),[traceIds])
  useEffect(()=>{setExpanded({nodes:[],edges:[]});setPicked(null);setFocus('')},[graph])
  useEffect(()=>{
    if(!ref.current||!visible.nodes.length) {cyRef.current?.destroy();cyRef.current=null;return}
    const present=new Set(visible.nodes.map(n=>n.id))
    const elements:any[]=[...visible.nodes.map(n=>({data:{id:n.id,label:n.label,type:n.type,status:n.status,severity:n.data?.severity,raw:n.data},classes:traceIds?.has(n.id)?'trace':''})),...visible.edges.filter(e=>present.has(e.source)&&present.has(e.target)).map(e=>({data:{id:e.id,source:e.source,target:e.target,label:e.type,type:e.type,raw:e.data},classes:[traceIds?.has(e.id)?'trace':'',inference(e.data)?'inferred':''].filter(Boolean).join(' ')}))]
    const cy=cytoscape({container:ref.current,elements,style:ghGraphStyle() as any,layout:activeLayout==='cose'?{name:'cose',padding:32,animate:false,idealEdgeLength:()=>110,nodeRepulsion:()=>14000}:{name:activeLayout,padding:32,animate:false,spacingFactor:1.3} as any,minZoom:.15,maxZoom:3})
    cyRef.current=cy
    if(cy.zoom()>1.2){cy.zoom(1.2);cy.center()}
    cy.on('tap','node',evt=>{const hood=evt.target.closedNeighborhood();cy.elements().addClass('faded').removeClass('neighbor');hood.removeClass('faded');hood.edges().addClass('neighbor');setFocus(evt.target.id());setPicked({...evt.target.data(),kind:'node'});onNodeRef.current?.(evt.target.data())})
    cy.on('tap','edge',evt=>{cy.elements().removeClass('faded neighbor');setPicked({...evt.target.data(),kind:'edge'});onEdgeRef.current?.(evt.target.data())})
    cy.on('tap',evt=>{if(evt.target===cy){cy.elements().removeClass('faded neighbor');setPicked(null)}})
    const stop=flowTrace(cy as any)
    return ()=>{stop();cy.destroy();if(cyRef.current===cy)cyRef.current=null}
  // signature represents the graph value, avoiding Cytoscape resets on unrelated React renders.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[signature,activeLayout,traceSignature])
  const zoom=(factor:number)=>{const cy=cyRef.current;if(!cy)return;cy.zoom({level:Math.min(3,Math.max(.15,cy.zoom()*factor)),renderedPosition:{x:cy.width()/2,y:cy.height()/2}})}
  const locate=(term:string)=>{const cy=cyRef.current;if(!cy||!term)return;const n=cy.nodes().filter(e=>String(e.data('id')).toLowerCase().includes(term.toLowerCase())||String(e.data('label')).toLowerCase().includes(term.toLowerCase())).first();if(!n.length)return;setFocus(n.id());setPicked({...n.data(),kind:'node'});cy.animate({fit:{eles:n, padding:100},duration:200});onNodeRef.current?.(n.data())}
  const expand=async()=>{if(!focus)return;setExpanding(true);setExpandError('');try{const rels=await getNeighbors(config,focus,{limit:50});const items=Array.isArray(rels.items)?rels.items:[];const neighbors=relationshipsToGraph(items);setExpanded(prev=>mergeGraphs(prev,neighbors))}catch(e){setExpandError(String(e))}finally{setExpanding(false)}}
  if(!merged.nodes.length)return <EmptyState title="No graph data" detail="The backend did not return graph-shaped data for this view." />
  return <div className="gh-graph"><div className="gh-graph-toolbar"><label className="field"><span>Find node</span><input value={search} placeholder="Name or ID" onChange={e=>setSearch(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')locate(search)}}/></label><button onClick={()=>locate(q)} disabled={!q}>Find</button><button onClick={()=>cyRef.current?.fit(undefined,32)}>Fit all</button><button onClick={()=>zoom(1.3)} aria-label="Zoom in">+</button><button onClick={()=>zoom(1/1.3)} aria-label="Zoom out">−</button><label className="field"><span>Layout</span><select value={activeLayout} onChange={e=>setLayout(e.target.value as Layout)}><option value="cose">Network</option><option value="breadthfirst">Hierarchy</option><option value="circle">Circle</option></select></label></div>
    <GraphLegend types={types} hidden={hidden} onToggle={toggle}/>
    <div className="gh-graph-key">Solid edge = recorded relationship · Dashed edge = explicitly inferred · Violet = explicitly provided trace</div>
    {visible.nodes.length?<div className="graph-canvas" ref={ref} style={{height}} aria-label="Interactive graph"/>:<EmptyState title="All node categories hidden" detail="Select a category above to show it again."/>}
    {picked&&<section className="panel gh-graph-inspector" aria-label="Graph selection"><div className="toolbar" style={{justifyContent:'space-between'}}><h3>{picked.kind==='edge'?'Relationship':'Selected entity'}</h3><button onClick={()=>{setPicked(null);cyRef.current?.elements().removeClass('faded neighbor')}}>Close</button></div>{picked.kind==='edge'?<><p><strong>{presentRelationship(picked.type,picked.source,picked.target).phrase}</strong></p><div className="technical-secondary">{picked.type} · {picked.source} → {picked.target}</div><p>{inference(picked.raw)?'Inferred relationship: verify its source before relying on it.':'Graph relationship returned by the backend. Its existence does not establish causality.'}</p><div className="toolbar"><Link to={`/entities/${encodeURIComponent(picked.source)}`}>View source</Link><Link to={`/entities/${encodeURIComponent(picked.target)}`}>View target</Link></div></>:<><strong>{displayName(picked.raw||{id:picked.id})}</strong><p className="technical-secondary">{picked.type} · {picked.id}</p>{picked.raw?.description&&<p>{picked.raw.description}</p>}{picked.raw?.status&&<p>Status: {String(picked.raw.status)}</p>}{picked.raw?.source_name&&<p>Source: {String(picked.raw.source_name)}</p>}{picked.raw?.observed_at&&<p>Observed: {String(picked.raw.observed_at)}</p>}<div className="toolbar"><Link to={`/entities/${encodeURIComponent(picked.id)}`}>Details and provenance</Link><button onClick={expand} disabled={expanding}>{expanding?'Expanding…':'Expand neighbors'}</button></div>{expandError&&<p role="alert">{expandError}</p>}</> }<TechnicalDetails><pre>{JSON.stringify(picked.raw||picked,null,2)}</pre></TechnicalDetails></section>}
  </div>
}
