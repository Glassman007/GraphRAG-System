export function GraphLegend({ types, hidden=new Set<string>(), onToggle }: { types:string[];hidden?:Set<string>;onToggle?:(type:string)=>void }) {
  return <div className="legend" aria-label="Node category filters">{types.map(t=><button type="button" key={t} className="gh-legend-toggle" aria-pressed={!hidden.has(t)} onClick={()=>onToggle?.(t)} disabled={!onToggle}><span className="legend-dot" />{t} {hidden.has(t)?'· hidden':''}</button>)}</div>
}
