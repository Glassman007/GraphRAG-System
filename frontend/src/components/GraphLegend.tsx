export function GraphLegend({ types }: { types: string[] }) {
  return <div className="legend">{types.map(t => <span key={t}><span className="legend-dot" />{t}</span>)}</div>
}
