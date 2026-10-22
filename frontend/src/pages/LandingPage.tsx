import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { apiRequest } from '../api/client'
import { getReady } from '../api/system'
import { listSituations } from '../api/situations'
import { getGraphPreview } from '../api/graphPreview'
import { previewToGraph } from '../graph/adapters'
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
  ['Organization', '/organization', 'browse systems, teams and people without memorizing IDs'],
  ['Scenarios', '/scenarios', 'guided Asteria test cases across the three tracks'],
]

type Brain = { graph_id: string; display_name: string; available: boolean }
type BrainList = { items: Brain[]; default_graph_id: string | null }

// Agent Workspace uses this same session-scoped choice. Never treat a source ID
// as a graph ID: source filtering is NOT enforced by the graph APIs.
function readWorkspaceGraph(tenantId: string) {
  try { return sessionStorage.getItem(`verinex.workspace.graph.${tenantId}`) || localStorage.getItem(`verinex.workspace.graph.${tenantId}`) || '' }
  catch { return '' }
}

export function LandingPage() {
  const { config } = useAuth()
  const [choice, setChoice] = useState(() => ({ tenant: config.tenantId, id: readWorkspaceGraph(config.tenantId) }))
  const requestedGraph = choice.tenant === config.tenantId ? choice.id : readWorkspaceGraph(config.tenantId)
  const ready = useQuery({ queryKey: ['ready', config.baseUrl], queryFn: ({ signal }) => getReady(config, signal), retry: false })
  const registry = useQuery({
    queryKey: ['landing-brains', config.baseUrl, config.tenantId, config.token],
    queryFn: ({ signal }) => apiRequest<BrainList>(config, '/api/v1/graphs', { signal }),
    retry: false,
  })
  const available = registry.data?.items.filter(brain => brain.available) || []
  // A sole authorized graph is unambiguous; otherwise require an explicit choice.
  // A stale saved choice must NEVER silently fall back to another graph.
  const activeGraph = available.some(brain => brain.graph_id === requestedGraph)
    ? requestedGraph : (!requestedGraph && available.length === 1 ? available[0].graph_id : '')
  const selectedBrain = available.find(brain => brain.graph_id === activeGraph)
  const scopedConfig = useMemo(() => ({ ...config, graphId: activeGraph || undefined }), [config, activeGraph])
  const preview = useQuery({
    queryKey: ['landing-graph-preview', config.baseUrl, config.tenantId, config.token, activeGraph],
    queryFn: ({ signal }) => getGraphPreview(scopedConfig, signal),
    enabled: !!activeGraph,
    retry: false,
  })
  const situations = useQuery({
    queryKey: ['landing-situations', config.baseUrl, config.tenantId, config.token, activeGraph],
    queryFn: ({ signal }) => listSituations(scopedConfig, { limit: 10 }, signal),
    enabled: !!activeGraph,
    retry: false,
  })
  const lead = useMemo(() => {
    const items = situations.data?.items || []
    return items.find(s => String(s.status).toUpperCase() === 'OPEN') || items[0]
  }, [situations.data])
  const graph = useMemo(() => previewToGraph(preview.data || {}), [preview.data])
  const chooseGraph = (id: string) => {
    setChoice({ tenant: config.tenantId, id })
    try {
      if (id) {
        sessionStorage.setItem(`verinex.workspace.graph.${config.tenantId}`, id)
        localStorage.setItem(`verinex.workspace.graph.${config.tenantId}`, id)
      } else {
        sessionStorage.removeItem(`verinex.workspace.graph.${config.tenantId}`)
        localStorage.removeItem(`verinex.workspace.graph.${config.tenantId}`)
      }
    } catch { /* no session storage available */ }
  }

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
          {activeGraph && <Link className="landing-secondary" to={`/agent-workspace?graph=${encodeURIComponent(activeGraph)}`}>Open selected brain</Link>}
        </div>
      </section>

      <section className="panel landing-live" aria-label="Live Company Brain graph">
        <h3>Live from the graph</h3>
        {registry.error ? <ErrorPanel error={registry.error} /> : <>
          <label className="field landing-brain-choice">
            <span>Company Brain</span>
            <select aria-label="Homepage Company Brain" value={activeGraph} onChange={event => chooseGraph(event.target.value)} disabled={registry.isLoading}>
              <option value="">Select an authorized Company Brain</option>
              {available.map(brain => <option key={brain.graph_id} value={brain.graph_id}>{brain.display_name}</option>)}
            </select>
          </label>
          {registry.isLoading ? <p className="muted">Finding authorized Company Brains…</p>
            : requestedGraph && !activeGraph ? <p role="alert">The previously selected Company Brain is no longer available to this tenant. Choose an authorized graph to continue.</p>
            : !available.length ? <p className="muted">No available Company Brains. Register a graph in Sources to begin.</p>
            : !activeGraph ? <p className="muted">Choose a Company Brain to load its live graph.</p>
            : <>
              <div className="landing-q"><span aria-hidden="true">&gt;</span> {selectedBrain?.display_name || activeGraph}</div>
              {lead && <div className="landing-a"><Decode text={String(lead.title || lead.name || lead.id)} delay={350} duration={800} /> <StatusBadge value={lead.status} /></div>}
              {preview.isLoading ? <p className="muted">Loading live, read-only graph preview…</p>
                : preview.error ? <ErrorPanel error={preview.error} />
                : !graph.nodes.length ? <p className="muted">This Company Brain has no current canonical entities to display.</p>
                : <>
                  <GraphView key={`${config.tenantId}:${activeGraph}`} graph={graph} apiConfig={scopedConfig} height={340} />
                  <div className="landing-trace">
                    <span className="status"><span className="status__glyph" aria-hidden="true">◆</span><span>live graph sample</span></span>
                    <span>{graph.nodes.length} of {preview.data?.total_nodes} nodes · {graph.edges.length} displayed relationships (of {preview.data?.total_edges} current relationships)</span>
                  </div>
                  <p className="technical-secondary">Read-only sample of recorded entities and relationships from the selected Company Brain. Connections do not establish causality or verify claims.</p>
                </>}
              {situations.error && <p className="technical-secondary">Situation summary unavailable. The graph preview is retrieved independently.</p>}
            </>}
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
