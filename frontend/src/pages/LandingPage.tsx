import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { getReady } from '../api/system'
import { getSituationContext, listSituations } from '../api/situations'
import { contextToGraph } from '../graph/adapters'
import { GraphView } from '../components/GraphView'
import { StatusBadge } from '../components/StatusBadge'
import { Decode } from '../components/Decode'
import { RainLayer } from '../components/RainLayer'
import { ErrorPanel } from '../components/AsyncState'

const surfaces: [string, string, string][] = [
  ['Situations', '/situations', 'what is happening, and what it touches'],
  ['Investigations', '/investigations', 'graph-first retrieval with the scope it searched'],
  ['Knowledge', '/knowledge', 'claims, the evidence behind them, and conflicts'],
  ['Company Brain', '/company-brain', 'processes, drift, bus factor, bottlenecks'],
  ['Simulations', '/simulations', 'counterfactuals that never touch the canonical graph'],
  ['Sources', '/sources', 'where every fact was learned, and when'],
]

/** Demo entry: a live answer decoded out of the rain, straight from the backend graph. */
export function LandingPage() {
  const { config } = useAuth()
  const ready = useQuery({ queryKey: ['ready', config.baseUrl], queryFn: ({ signal }) => getReady(config, signal), retry: false })
  const situations = useQuery({ queryKey: ['landing-situations'], queryFn: ({ signal }) => listSituations(config, { limit: 10 }, signal) })
  const lead = useMemo(() => {
    const items: any[] = situations.data?.items || []
    return items.find(s => String(s.status).toUpperCase() === 'OPEN') || items[0]
  }, [situations.data])
  const context = useQuery({ queryKey: ['situation-context', lead?.id, ''], queryFn: ({ signal }) => getSituationContext(config, lead.id, undefined, signal), enabled: !!lead?.id })
  const graph = useMemo(() => contextToGraph(context.data || {}), [context.data])
  // Violet marks the evidence chain the backend linked to this situation: its claims and their evidence.
  const traceIds = useMemo(() => new Set<string>([lead?.id, ...(context.data?.claims || []).map((c: any) => c.id), ...(context.data?.evidence || []).map((e: any) => e.id)].filter(Boolean)), [context.data, lead?.id])
  const title = lead ? String(lead.title || lead.name || lead.id) : ''

  return <div className="landing">
    <RainLayer density={1} />
    <header className="landing-bar">
      <span className="rail__mark">GraphHacks</span>
      <div className="gh-statusline">
        <span className={ready.data?.ready ? 'ready' : 'not-ready'}>{ready.data?.ready ? 'Backend ready' : 'Backend unavailable'}</span>
        <span>tenant {config.tenantId}</span>
      </div>
      <Link className="button-link" to="/situations">Enter console</Link>
    </header>

    <main className="landing-hero">
      <section className="landing-copy" aria-labelledby="landing-title">
        <h1 id="landing-title" className="landing-display"><Decode text="Every answer" /><br /><Decode text="has a path." delay={180} /></h1>
        <p>GraphHacks turns a company's incidents, systems, people and decisions into one FalkorDB graph, then shows the traversal behind every answer it gives.</p>
        <div className="toolbar">
          <Link className="button-link" to="/situations">Enter console</Link>
          {lead && <Link className="landing-secondary" to={`/situations/${encodeURIComponent(lead.id)}`}>Open {lead.id}</Link>}
        </div>
      </section>

      <section className="panel landing-live" aria-label="Live answer from the graph">
        <h3>Live from the graph</h3>
        {situations.error ? <ErrorPanel error={situations.error} /> : !lead ? <p className="muted">{situations.isLoading ? 'Querying FalkorDB…' : 'The graph has no situations yet. Connect a source to begin.'}</p> : <>
          <div className="landing-q"><span aria-hidden="true">&gt;</span> What is happening right now, and why?</div>
          <div className="landing-a"><Decode text={title} delay={350} duration={800} /></div>
          <div className="toolbar"><StatusBadge value={lead.status} />{lead.severity && <StatusBadge value={lead.severity} />}<span className="technical-secondary">{lead.id}</span></div>
          {context.error ? <ErrorPanel error={context.error} /> : <GraphView graph={graph} height={300} traceIds={traceIds} onNode={() => {}} />}
          <div className="landing-trace">
            <span className="status" data-tone="trace"><span className="status__glyph" aria-hidden="true">◆</span><span>traced</span></span>
            <span>{(context.data?.claims || []).length} claims · {(context.data?.evidence || []).length} evidence · {(context.data?.relationships || []).length} relationships returned by the backend</span>
          </div>
          <div className="technical-secondary">Northstar is a synthetic demo company.</div>
        </>}
      </section>
    </main>

    <nav className="landing-paths" aria-label="Console surfaces">
      <ul className="gh-tree">
        {surfaces.map(([name, to, what]) => <li key={to}><Link to={to}>{name}</Link> <span className="muted">— {what}</span></li>)}
      </ul>
    </nav>
    <footer className="landing-foot">GraphHacks · graph by <a href="https://www.falkordb.com" target="_blank" rel="noreferrer">FalkorDB</a> · WeMakeDevs Graph Hacks 2026</footer>
  </div>
}
