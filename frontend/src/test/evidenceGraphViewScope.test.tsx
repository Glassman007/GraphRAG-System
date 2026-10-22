import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { GraphView } from '../components/GraphView'
import { TechnicalModeProvider } from '../presentation/TechnicalModeContext'
import { getEntity, getEntityProvenance, getNeighbors } from '../api/entities'

const harness=vi.hoisted(()=>({tapNode:undefined as undefined|((event:any)=>void)}))
vi.mock('cytoscape',()=>({default:()=>({
  zoom:()=>1,center:()=>{},destroy:()=>{},width:()=>400,height:()=>300,
  on:(event:string,selector:any,callback?:any)=>{
    if(event==='tap'&&selector==='node')harness.tapNode=callback
  },
  elements:()=>({addClass:()=>({removeClass:()=>{}}),removeClass:()=>{}}),
})}))
vi.mock('../design/graphStyle',()=>({ghGraphStyle:()=>[],flowTrace:()=>()=>{}}))
vi.mock('../auth/AuthContext',()=>({useAuth:()=>({config:{baseUrl:'',tenantId:'asteria',token:'test'}})}))
vi.mock('../api/entities',()=>({getEntity:vi.fn(),getEntityProvenance:vi.fn(),getNeighbors:vi.fn()}))

describe('Scoped GraphView node inspection',()=>{
  beforeEach(()=>{vi.clearAllMocks();harness.tapNode=undefined})
  it('uses the selected Asteria graph for canonical node, provenance and expansion reads',async()=>{
    vi.mocked(getEntity).mockResolvedValue({id:'EVD-AST-0007',_labels:['Entity','Evidence']})
    vi.mocked(getEntityProvenance).mockResolvedValue({entity_id:'EVD-AST-0007',links:[]})
    vi.mocked(getNeighbors).mockResolvedValue({items:[]})
    const apiConfig={baseUrl:'',tenantId:'asteria',graphId:'asteria_company_brain_v1',token:'test'}
    const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
    render(<QueryClientProvider client={client}><TechnicalModeProvider><GraphView
      apiConfig={apiConfig} height={220}
      graph={{nodes:[{id:'EVD-AST-0007',label:'Evidence seven',type:'Evidence',data:{id:'EVD-AST-0007'}}],edges:[]}}
    /></TechnicalModeProvider></QueryClientProvider>)
    await waitFor(()=>expect(harness.tapNode).toBeTypeOf('function'))
    act(()=>harness.tapNode?.({target:{
      id:()=> 'EVD-AST-0007', data:()=>({id:'EVD-AST-0007',raw:{id:'EVD-AST-0007'},type:'Evidence'}),
      closedNeighborhood:()=>({removeClass:()=>{},edges:()=>({addClass:()=>{}})}),
    }}))
    await waitFor(()=>expect(screen.getByText(/Canonical entity found in the selected Company Brain/i)).toBeTruthy())
    await waitFor(()=>expect(getEntityProvenance).toHaveBeenCalled())
    expect(vi.mocked(getEntity).mock.calls[0][0].graphId).toBe('asteria_company_brain_v1')
    expect(vi.mocked(getEntityProvenance).mock.calls[0][0].graphId).toBe('asteria_company_brain_v1')
    fireEvent.click(screen.getByRole('button',{name:/Expand neighbors/i}))
    await waitFor(()=>expect(getNeighbors).toHaveBeenCalled())
    expect(vi.mocked(getNeighbors).mock.calls[0][0].graphId).toBe('asteria_company_brain_v1')
  })
  it('does not expand an evidence reference whose scoped canonical lookup fails',async()=>{
    vi.mocked(getEntity).mockRejectedValue(new Error('NOT_FOUND'))
    const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
    render(<QueryClientProvider client={client}><TechnicalModeProvider><GraphView
      apiConfig={{baseUrl:'',tenantId:'asteria',graphId:'asteria_company_brain_v1',token:'test'}}
      graph={{nodes:[{id:'EVD-AST-0007',label:'EVD-AST-0007',type:'Entity',data:{id:'EVD-AST-0007'}}],edges:[]}}
    /></TechnicalModeProvider></QueryClientProvider>)
    await waitFor(()=>expect(harness.tapNode).toBeTypeOf('function'))
    act(()=>harness.tapNode?.({target:{
      id:()=> 'EVD-AST-0007', data:()=>({id:'EVD-AST-0007',raw:{id:'EVD-AST-0007'},type:'Entity'}),
      closedNeighborhood:()=>({removeClass:()=>{},edges:()=>({addClass:()=>{}})}),
    }}))
    await waitFor(()=>expect(screen.getByText(/Canonical entity lookup failed/i)).toBeTruthy())
    expect((screen.getByRole('button',{name:/Expand neighbors/i}) as HTMLButtonElement).disabled).toBe(true)
    expect(getNeighbors).not.toHaveBeenCalled()
  })

})
