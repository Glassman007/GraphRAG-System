import { useEffect, useMemo, useRef } from 'react'
import cytoscape from 'cytoscape'
import type { UiGraph } from '../graph/adapters'
import { EmptyState } from './AsyncState'
import { GraphLegend } from './GraphLegend'

export function GraphView({ graph, onNode, onEdge, layout='cose', height=480 }: { graph: UiGraph; onNode?: (data:any)=>void; onEdge?: (data:any)=>void; layout?: 'cose'|'breadthfirst'|'circle'; height?: number }) {
  const ref=useRef<HTMLDivElement>(null)
  const types=useMemo(()=>Array.from(new Set(graph.nodes.map(n=>n.type))).sort(),[graph.nodes])
  useEffect(()=>{
    if(!ref.current || !graph.nodes.length) return
    const elements:any[]=[
      ...graph.nodes.map(n=>({data:{id:n.id,label:n.label,type:n.type,status:n.status,raw:n.data}})),
      ...graph.edges.filter(e=>graph.nodes.some(n=>n.id===e.source)&&graph.nodes.some(n=>n.id===e.target)).map(e=>({data:{id:e.id,source:e.source,target:e.target,label:e.type,type:e.type,raw:e.data}})),
    ]
    const cy=cytoscape({container:ref.current,elements,style:[
      {selector:'node',style:{'label':'data(label)','font-size':10,'text-wrap':'wrap','text-max-width':'110px','background-color':'#dedede','border-width':1,'border-color':'#111','width':38,'height':38}},
      {selector:'edge',style:{'label':'data(label)','font-size':8,'curve-style':'bezier','target-arrow-shape':'triangle','width':1,'line-color':'#777','target-arrow-color':'#777'}},
      {selector:':selected',style:{'border-width':3,'border-color':'#111','line-color':'#111','target-arrow-color':'#111'}},
    ],layout:{name:layout,padding:30,animate:false} as any,minZoom:0.2,maxZoom:2.5})
    cy.on('tap','node',evt=>onNode?.(evt.target.data()))
    cy.on('tap','edge',evt=>onEdge?.(evt.target.data()))
    return ()=>cy.destroy()
  },[graph,layout,onNode,onEdge])
  if(!graph.nodes.length) return <EmptyState title="No graph data" detail="The backend did not return graph-shaped data for this view." />
  return <div><GraphLegend types={types}/><div className="graph-canvas" ref={ref} style={{height}} aria-label="Interactive graph" /></div>
}
