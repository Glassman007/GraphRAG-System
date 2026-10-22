import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { LandingPage } from '../pages/LandingPage'
import { getGraphPreview } from '../api/graphPreview'
import { listSituations } from '../api/situations'
import { apiRequest } from '../api/client'
import type { ApiConfig } from '../api/types'

let config: ApiConfig = {baseUrl: '', token: 'test-token', tenantId: 'asteria'}
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({config}) }))
vi.mock('../api/client', () => ({apiRequest:vi.fn()}))
vi.mock('../api/system', () => ({getReady:vi.fn().mockResolvedValue({ready:true})}))
vi.mock('../api/graphPreview', () => ({getGraphPreview:vi.fn()}))
vi.mock('../api/situations', () => ({listSituations:vi.fn()}))
vi.mock('../components/GraphView', () => ({GraphView:({graph,apiConfig}:any)=><div data-testid="live-preview">{apiConfig?.graphId}: {graph.nodes.length} nodes / {graph.edges.length} edges</div>}))
vi.mock('../components/Decode', () => ({Decode:({text}:any)=><>{text}</>}))
vi.mock('../components/RainLayer', () => ({RainLayer:()=>null}))

const ASTERIA = 'asteria_company_brain_v1'
const OTHER = 'other_company_brain'
const brains = {items:[{graph_id:ASTERIA,display_name:'Asteria',available:true},
  {graph_id:OTHER,display_name:'Other Brain',available:true}],default_graph_id:null}
const sample = {graph_id:ASTERIA,total_nodes:2,total_edges:1,sampled:false,
  nodes:[{id:'INC-AST-ROUTE-OUTAGE',name:'Route outage',_labels:['Entity','Incident']},
    {id:'SYS-AST',name:'Routing',_labels:['Entity','System']}],
  edges:[{source:'INC-AST-ROUTE-OUTAGE',target:'SYS-AST',type:'AFFECTS',properties:{}}]}

function mount() {
  const client = new QueryClient({defaultOptions:{queries:{retry:false}}})
  return render(<MemoryRouter><QueryClientProvider client={client}><LandingPage /></QueryClientProvider></MemoryRouter>)
}

describe('homepage Company Brain graph preview', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    localStorage.clear()
    config = {baseUrl:'',token:'test-token',tenantId:'asteria'}
    vi.mocked(apiRequest).mockResolvedValue(brains)
    vi.mocked(getGraphPreview).mockResolvedValue(sample)
    vi.mocked(listSituations).mockResolvedValue({items:[],limit:10,has_more:false})
  })

  it('renders Asteria canonical graph without requiring a Situation result', async () => {
    sessionStorage.setItem('verinex.workspace.graph.asteria', ASTERIA)
    mount()
    expect(await screen.findByTestId('live-preview')).toHaveTextContent(`${ASTERIA}: 2 nodes / 1 edges`)
    expect(screen.queryByText(/The graph has no situations yet/)).not.toBeInTheDocument()
    expect(vi.mocked(getGraphPreview).mock.calls[0][0].graphId).toBe(ASTERIA)
    expect(vi.mocked(listSituations).mock.calls[0][0].graphId).toBe(ASTERIA)
  })

  it('does not leak or silently fall back when saved graph is no longer authorized', async () => {
    sessionStorage.setItem('verinex.workspace.graph.asteria', 'deleted_brain')
    mount()
    expect(await screen.findByRole('alert')).toHaveTextContent(/no longer available/i)
    expect(getGraphPreview).not.toHaveBeenCalled()
    expect(listSituations).not.toHaveBeenCalled()
  })

  it('can select an authorized graph and shares the choice with Agent Workspace', async () => {
    mount()
    const selector = await screen.findByRole('combobox', {name:'Homepage Company Brain'})
    await waitFor(() => expect(screen.getByText(/Choose a Company Brain to load/)).toBeInTheDocument())
    fireEvent.change(selector, {target:{value:ASTERIA}})
    expect(await screen.findByTestId('live-preview')).toHaveTextContent(ASTERIA)
    expect(sessionStorage.getItem('verinex.workspace.graph.asteria')).toBe(ASTERIA)
    expect(localStorage.getItem('verinex.workspace.graph.asteria')).toBe(ASTERIA)
  })

  it('restores an authorized selection from an earlier browser session', async () => {
    localStorage.setItem('verinex.workspace.graph.asteria', ASTERIA)
    mount()
    expect(await screen.findByTestId('live-preview')).toHaveTextContent(ASTERIA)
  })

  it('does not display a graph if scoped preview request fails', async () => {
    sessionStorage.setItem('verinex.workspace.graph.asteria', ASTERIA)
    vi.mocked(getGraphPreview).mockRejectedValue(new Error('FalkorDB disconnected'))
    mount()
    expect(await screen.findByText(/FalkorDB disconnected/)).toBeInTheDocument()
    expect(screen.queryByTestId('live-preview')).not.toBeInTheDocument()
  })
})
