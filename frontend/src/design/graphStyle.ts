// Cytoscape stylesheet for the "Read the Rain" world (see /DESIGN.md → Graph view).
// Pure styling: semantics (nodes, edges, paths) always come from backend responses.

type Rule = { selector: string; style: Record<string, string | number | number[]> }

const C = {
  void: '#030806',
  panel: '#06110a',
  rule: '#267246',
  ruleBright: '#2fa35a',
  text: '#b8f5c4',
  textBright: '#e8fff0',
  signal: '#00ff41',
  signalDeep: '#00c032',
  trace: '#9d93ff',
  traceLine: '#7466ff',
  warn: '#ffb000',
  crit: '#ff5a4d',
}

const shapes: Record<string, string> = {
  System: 'round-rectangle',
  Service: 'round-rectangle',
  Decision: 'diamond',
  Claim: 'hexagon',
  Evidence: 'tag',
  Incident: 'octagon',
  Situation: 'octagon',
  Person: 'ellipse',
  Team: 'barrel',
  Task: 'rectangle',
  Plan: 'rectangle',
  Action: 'vee',
  Policy: 'star',
}

export function ghGraphStyle(): Rule[] {
  return [
    {
      selector: 'node',
      style: {
        shape: 'ellipse',
        width: 16,
        height: 16,
        'background-color': C.panel,
        'border-width': 1,
        'border-color': C.signalDeep,
        label: 'data(label)',
        color: C.text,
        'font-family': 'JetBrains Mono Variable, monospace',
        'font-size': 10,
        'font-weight': 500,
        'text-valign': 'bottom',
        'text-margin-y': 4,
        'text-wrap': 'ellipsis',
        'text-max-width': '120px',
        'text-background-color': C.void,
        'text-background-opacity': 0.85,
        'text-background-padding': '2px',
        'min-zoomed-font-size': 7,
      },
    },
    ...Object.entries(shapes).map(([type, shape]) => ({ selector: `node[type = "${type}"]`, style: { shape } })),
    { selector: 'node[status = "BLOCKED"], node[status = "DEGRADED"]', style: { 'border-color': C.warn } },
    { selector: 'node[status = "FAILED"], node[severity = "SEV-1"]', style: { 'border-color': C.crit } },
    {
      selector: 'edge',
      style: {
        width: 1,
        'line-color': C.rule,
        'curve-style': 'bezier',
        'target-arrow-shape': 'vee',
        'target-arrow-color': C.ruleBright,
        'arrow-scale': 0.8,
        label: '',
        color: C.ruleBright,
        'font-family': 'JetBrains Mono Variable, monospace',
        'font-size': 8,
        'text-rotation': 'autorotate',
        'text-background-color': C.void,
        'text-background-opacity': 0.85,
        'min-zoomed-font-size': 9,
      },
    },
    { selector: 'edge.inferred', style: { 'line-style': 'dashed', 'line-dash-pattern': [4, 3] } },
    {
      selector: 'node:selected',
      style: {
        'background-color': C.textBright,
        'border-color': C.signal,
        'border-width': 2,
        'underlay-color': C.signal,
        'underlay-opacity': 0.25,
        'underlay-padding': 6,
        color: C.textBright,
      },
    },
    { selector: 'edge:selected', style: { 'line-color': C.signal, 'target-arrow-color': C.signal, width: 2 } },
    { selector: '.faded', style: { opacity: 0.2 } },
    { selector: 'edge.neighbor', style: { 'line-color': C.ruleBright, label: 'data(label)' } },
    { selector: 'edge:selected', style: { label: 'data(label)' } },
    // Trace: only what the backend returned as a traversed path.
    {
      selector: 'node.trace',
      style: { 'border-color': C.trace, 'border-width': 2, color: C.trace, 'underlay-color': C.traceLine, 'underlay-opacity': 0.2, 'underlay-padding': 5 },
    },
    {
      selector: 'edge.trace',
      style: { width: 2, 'line-color': C.traceLine, 'target-arrow-color': C.trace, color: C.trace, label: 'data(label)', 'line-style': 'dashed', 'line-dash-pattern': [6, 4] },
    },
  ]
}

/** Animate the dash flow on traced edges only (24fps). Returns a stop function. */
export function flowTrace(cy: { edges: (sel: string) => { style: (k: string, v: number) => void; length: number } }) {
  if (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches) return () => {}
  let offset = 0
  let last = 0
  let raf = 0
  const tick = (t: number) => {
    if (t - last >= 1000 / 24) {
      last = t
      offset = (offset - 1) % 100
      const traced = cy.edges('.trace')
      if (traced.length) traced.style('line-dash-offset', offset)
    }
    raf = requestAnimationFrame(tick)
  }
  raf = requestAnimationFrame(tick)
  return () => cancelAnimationFrame(raf)
}
