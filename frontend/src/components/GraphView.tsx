import { useEffect, useMemo, useRef } from 'react'
import cytoscape from 'cytoscape'
import type { UiGraph } from '../graph/adapters'
import { flowTrace, ghGraphStyle } from '../design/graphStyle'
import { EmptyState } from './AsyncState'
import { GraphLegend } from './GraphLegend'

/**
 * Cytoscape view of a backend graph. `traceIds` marks nodes/edges the backend returned as a
 * traversed path (retrieval scope, blast radius, genealogy); they render violet with flowing dashes.
 */
export function GraphView({ graph, onNode, onEdge, layout='cose', height=480, traceIds }: { graph: UiGraph; onNode?: (data:any)=>void; onEdge?: (data:any)=>void; layout?: 'cose'|'breadthfirst'|'circle'; height?: number; traceIds?: Set<string> }) {
  const ref=useRef<HTMLDivElement>(null)
  const types=useMemo(()=>Array.from(new Set(graph.nodes.map(n=>n.type))).sort(),[graph.nodes])
  useEffect(()=>{
    if(!ref.current || !graph.nodes.length) return
    const traced=(id:string)=>traceIds?.has(id)?'trace':''
    const elements:any[]=[
      ...graph.nodes.map(n=>({data:{id:n.id,label:n.label,type:n.type,status:n.status,severity:n.data?.severity,raw:n.data},classes:traced(n.id)})),
      ...graph.edges.filter(e=>graph.nodes.some(n=>n.id===e.source)&&graph.nodes.some(n=>n.id===e.target)).map(e=>({data:{id:e.id,source:e.source,target:e.target,label:e.type,type:e.type,raw:e.data},classes:traced(e.id)||(traceIds?.has(e.source)&&traceIds?.has(e.target)?'trace':'')})),
    ]
    const cy=cytoscape({container:ref.current,elements,style:ghGraphStyle() as any,layout:(layout==='cose'?{name:'cose',padding:30,animate:false,idealEdgeLength:()=>110,nodeRepulsion:()=>14000,nodeOverlap:24,componentSpacing:80}:{name:layout,padding:30,animate:false,spacingFactor:1.3}) as any,minZoom:0.2,maxZoom:2.5})
    // A fitted small graph should not blow labels up past legibility.
    if(cy.zoom()>1.15){cy.zoom(1.15);cy.center()}
    cy.on('tap','node',evt=>{
      const hood=evt.target.closedNeighborhood()
      cy.elements().addClass('faded').removeClass('neighbor');hood.removeClass('faded');hood.edges().addClass('neighbor')
      onNode?.(evt.target.data())
    })
    cy.on('tap','edge',evt=>onEdge?.(evt.target.data()))
    cy.on('tap',evt=>{if(evt.target===cy)cy.elements().removeClass('faded neighbor')})
    const stopFlow=flowTrace(cy as any)
    return ()=>{stopFlow();cy.destroy()}
  },[graph,layout,onNode,onEdge,traceIds])
  if(!graph.nodes.length) return <EmptyState title="No graph data" detail="The backend did not return graph-shaped data for this view." />
  return <div><GraphLegend types={types}/><div className="graph-canvas" ref={ref} style={{height}} aria-label="Interactive graph" /></div>
}
