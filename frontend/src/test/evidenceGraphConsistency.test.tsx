import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { relationshipsToGraph, mergeGraphs } from '../graph/adapters'
import { EvidenceExplorer } from '../pages/AgentWorkspacePage'
import { getEntity, getNeighbors } from '../api/entities'
import type { ApiConfig } from '../api/types'

vi.mock('../api/entities', () => ({getEntity:vi.fn(),getNeighbors:vi.fn()}))
vi.mock('../components/GraphView', () => ({
  GraphView: ({apiConfig,graph}:any) => <div data-testid="scoped-graph">
    <span data-testid="graph-scope">{apiConfig?.graphId||'MISSING'}</span>
    <span data-testid="graph-nodes">{JSON.stringify(graph.nodes.map((n:any)=>({id:n.id,type:n.type})))}</span>
  </div>,
}))

const scope = (graphId='asteria_company_brain_v1'): ApiConfig => ({baseUrl:'',tenantId:'asteria',graphId,token:'test'})
function mount(ids:string[], config=scope()) {
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
  return render(<QueryClientProvider client={client}><EvidenceExplorer ids={ids} config={config}/></QueryClientProvider>)
}

describe('Asteria Evidence Explorer consistency', () => {
  beforeEach(()=>{vi.clearAllMocks()})

  it('keeps the full Evidence neighbor instead of overwriting it with an ID-only endpoint', () => {
    const g=relationshipsToGraph([{source:'INC-AST-ROUTE-OUTAGE',target:'EVD-AST-0007',relationship:'SUPPORTS',
      neighbor:{id:'EVD-AST-0007',name:'Route evidence',_labels:['Entity','Evidence'],source_record_id:'SRC-1'}}])
    expect(g.nodes.find(n=>n.id==='EVD-AST-0007')).toMatchObject({type:'Evidence',label:'Route evidence',data:{source_record_id:'SRC-1'}})
    expect(g.nodes.find(n=>n.id==='INC-AST-ROUTE-OUTAGE')?.type).toBe('Entity')
  })

  it('preserves full graph records when merging placeholder expansions', () => {
    const root={id:'EVD-AST-0007',type:'Evidence',label:'Route evidence',data:{id:'EVD-AST-0007',_labels:['Entity','Evidence'],source_record_id:'SRC-1'}}
    const placeholder={id:'EVD-AST-0007',type:'Entity',label:'EVD-AST-0007',data:{id:'EVD-AST-0007'}}
    const result=mergeGraphs({nodes:[root],edges:[]},{nodes:[placeholder],edges:[]})
    expect(result.nodes).toHaveLength(1)
    expect(result.nodes[0]).toMatchObject({type:'Evidence',data:{source_record_id:'SRC-1'}})
  })

  it('passes selected graph scope to the graph and its canonical root', async()=>{
    vi.mocked(getEntity).mockResolvedValue({id:'INC-AST-ROUTE-OUTAGE',name:'Route outage',_labels:['Entity','Incident']})
    vi.mocked(getNeighbors).mockResolvedValue({items:[{source:'INC-AST-ROUTE-OUTAGE',target:'EVD-AST-0007',relationship:'HAS_EVIDENCE',
      neighbor:{id:'EVD-AST-0007',_labels:['Entity','Evidence'],name:'Evidence seven'}}]})
    mount(['INC-AST-ROUTE-OUTAGE'])
    await waitFor(()=>expect(screen.getByTestId('graph-scope').textContent).toBe('asteria_company_brain_v1'))
    expect(screen.getByTestId('graph-nodes').textContent).toContain('"type":"Incident"')
    expect(screen.getByTestId('graph-nodes').textContent).toContain('"type":"Evidence"')
    expect(vi.mocked(getNeighbors).mock.calls[0][0].graphId).toBe('asteria_company_brain_v1')
  })

  it('refuses unscoped evidence queries', ()=>{
    mount(['EVD-AST-0007'],scope(''))
    expect(screen.getByText(/Unscoped entity lookups are disabled/i)).toBeTruthy()
    expect(getEntity).not.toHaveBeenCalled()
    expect(getNeighbors).not.toHaveBeenCalled()
  })

  it('never displays a failed canonical lookup as verified graph evidence', async()=>{
    vi.mocked(getEntity).mockRejectedValue(new Error('Entity EVD-AST-0007 was not found'))
    mount(['EVD-AST-0007'])
    await waitFor(()=>expect(screen.getByText(/citation could not be resolved/i)).toBeTruthy())
    expect(screen.queryByTestId('scoped-graph')).toBeNull()
    expect(getNeighbors).not.toHaveBeenCalled()
  })

  it('does not carry an Asteria graph result into a different selected graph', async()=>{
    vi.mocked(getEntity).mockResolvedValue({id:'INC-AST-ROUTE-OUTAGE',_labels:['Entity','Incident']})
    vi.mocked(getNeighbors).mockResolvedValue({items:[]})
    const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
    const view=(config:ApiConfig)=><QueryClientProvider client={client}><EvidenceExplorer ids={['INC-AST-ROUTE-OUTAGE']} config={config}/></QueryClientProvider>
    const result=render(view(scope()))
    await waitFor(()=>expect(screen.getByTestId('graph-scope').textContent).toBe('asteria_company_brain_v1'))
    result.rerender(view(scope('another_authorized_graph')))
    await waitFor(()=>expect(screen.getByTestId('graph-scope').textContent).toBe('another_authorized_graph'))
    expect(vi.mocked(getEntity).mock.calls.some(call=>call[0].graphId==='another_authorized_graph')).toBe(true)
  })
})
