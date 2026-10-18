// Dev-only specimen for /design-system.html. Renders the "Read the Rain" system with its real modules.
// The graph data below is a synthetic sample for the specimen only; the app always renders backend data.
import cytoscape from 'cytoscape'
import './fonts'
import './system.css'
import { MatrixRain } from './rain'
import { decode } from './decode'
import { flowTrace, ghGraphStyle } from './graphStyle'

const rain = new MatrixRain(document.getElementById('rain') as HTMLCanvasElement, {
  density: 1,
  // Rain yields behind everything a viewer reads: panels and text blocks alike.
  maskSelector: '.gh-panel, .shell, .facts, .spec-bar, .swatches, .hero__copy, .spec-section > h2, .spec-section > p, .type-row',
})
rain.start()

for (const btn of document.querySelectorAll<HTMLButtonElement>('[data-density]')) {
  btn.addEventListener('click', () => {
    const density = Number(btn.dataset.density)
    document.querySelectorAll('[data-density]').forEach(b => b.setAttribute('aria-selected', String(b === btn)))
    if (density === 0) rain.stop()
    else {
      rain.setDensity(density)
      rain.start()
    }
  })
}

// Decode the hero on load; re-decode the answer when the "watch a trace" action runs.
const decodeAll = () => document.querySelectorAll<HTMLElement>('[data-decode]').forEach((el, i) => {
  const text = el.dataset.text ?? el.textContent ?? ''
  el.dataset.text = text
  setTimeout(() => decode(el, text, { duration: 700 }), i * 140)
})
decodeAll()

// Palette with live WCAG contrast against `panel`.
const tokens: [string, string][] = [
  ['void', 'page ground'], ['panel', 'panels, nav'], ['raised', 'hover, selected'], ['rule-faint', 'inner dividers'],
  ['rule', 'panel edges'], ['rule-bright', 'focus, corners'], ['text-muted', 'secondary text'], ['text', 'body, data'],
  ['text-bright', 'headings, values'], ['signal', 'primary fills'], ['signal-deep', 'pressed, rings'],
  ['trace', 'traced text'], ['trace-line', 'traced edges'], ['warn', 'blocked, governed'], ['crit', 'critical'],
]
const css = getComputedStyle(document.documentElement)
const hex = (name: string) => css.getPropertyValue(`--${name}`).trim()
const lum = (h: string) => {
  const [r, g, b] = [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255).map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const ratio = (a: string, b: string) => {
  const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m)
  return (x + 0.05) / (y + 0.05)
}
const swatches = document.getElementById('swatches')!
for (const [name, role] of tokens) {
  const value = hex(name)
  const r = ratio(value, hex('panel'))
  const el = document.createElement('div')
  el.className = 'swatch'
  el.innerHTML = `<div class="swatch__chip" style="background:${value}"></div><div class="swatch__meta"><b>${name}</b><span class="gh-data">${value}</span><span class="gh-muted">${role}</span><span class="gh-data" style="color:${r >= 4.5 ? 'var(--text)' : 'var(--text-muted)'}">${r.toFixed(1)}:1${r >= 4.5 ? ' · text ok' : r >= 3 ? ' · ui only' : ''}</span></div>`
  swatches.append(el)
}

// Specimen graph: synthetic sample shaped like the seeded Northstar data.
const n = (id: string, type: string, extra: Record<string, string> = {}) => ({ data: { id, label: id, type, ...extra } })
const e = (source: string, label: string, target: string, cls = '') => ({ data: { id: `${source}-${label}-${target}`, source, target, label }, classes: cls })

const elements = [
  n('INC-001', 'Incident', { severity: 'SEV-1' }), n('SYS-CHECKOUT', 'System'), n('SYS-PRICING-API', 'System'), n('SYS-PRICING-DB', 'System'),
  n('MIG-203', 'Action'), n('C-001', 'Claim'), n('C-002', 'Claim'), n('E-004', 'Evidence'), n('DEC-INC001-ROLLBACK', 'Decision'),
  n('TEAM-PRICING', 'Team'), n('PERSON-RIYA', 'Person'), n('TASK-A', 'Task', { status: 'BLOCKED' }),
  e('INC-001', 'AFFECTS', 'SYS-CHECKOUT', 'trace'), e('SYS-CHECKOUT', 'DEPENDS_ON', 'SYS-PRICING-API', 'trace'),
  e('SYS-PRICING-API', 'READS', 'SYS-PRICING-DB', 'trace'), e('MIG-203', 'CHANGED', 'SYS-PRICING-DB', 'trace'),
  e('C-002', 'ABOUT', 'MIG-203', 'trace'), e('E-004', 'SUPPORTS', 'C-001'), e('C-001', 'CONTRADICTS', 'C-002', 'inferred'),
  e('DEC-INC001-ROLLBACK', 'RESOLVES', 'INC-001'), e('TEAM-PRICING', 'OWNS', 'SYS-PRICING-API'), e('PERSON-RIYA', 'MEMBER_OF', 'TEAM-PRICING'),
  e('TASK-A', 'INVESTIGATES', 'INC-001'),
]
const traceNodes = new Set(['INC-001', 'SYS-CHECKOUT', 'SYS-PRICING-API', 'SYS-PRICING-DB', 'MIG-203', 'C-002'])

const mount = (container: HTMLElement, els: typeof elements, layout: string) => {
  const cy = cytoscape({
    container,
    elements: els as any,
    style: ghGraphStyle() as any,
    layout: { name: layout, padding: 24, animate: false } as any,
    minZoom: 0.3,
    maxZoom: 2.5,
  })
  cy.nodes().forEach(node => { if (traceNodes.has(node.id())) node.addClass('trace') })
  cy.on('tap', 'node', evt => {
    const hood = evt.target.closedNeighborhood()
    cy.elements().addClass('faded').removeClass('neighbor')
    hood.removeClass('faded')
    hood.edges().addClass('neighbor')
  })
  cy.on('tap', evt => { if (evt.target === cy) cy.elements().removeClass('faded neighbor') })
  flowTrace(cy as any)
  return cy
}

mount(document.getElementById('spec-graph')!, elements, 'cose')
const heroEls = elements.filter(el => ('classes' in el ? el.classes === 'trace' : traceNodes.has(el.data.id)))
mount(document.getElementById('hero-graph')!, heroEls, 'breadthfirst')

document.querySelectorAll('.hero__actions .gh-btn')[1]?.addEventListener('click', () => {
  rain.surge(1400)
  decodeAll()
})
