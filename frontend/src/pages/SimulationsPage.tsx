import { useMemo, useState } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { runCounterfactual,runBusFactor } from '../api/simulations'
import { ErrorPanel,EmptyState,LoadingPanel } from '../components/AsyncState'
import { TechnicalDetails } from '../components/TechnicalDetails'
import { EntityPicker } from '../components/EntityPicker'
import { GraphView } from '../components/GraphView'
import type { UiGraph } from '../graph/adapters'

type Mode='remove_dependency'|'rollback_change'|'add_compatibility_layer'|'bus_factor'
function PreviewGraph({impact,title}:{impact:any;title:string}) {
  const graph:UiGraph=useMemo(()=>{
    const ids=new Set<string>((impact?.roots||[]) as string[])
    for(const id of impact?.impacted||[]) ids.add(String(id))
    const edges=new Map<string,UiGraph['edges'][number]>()
    for(const path of impact?.paths||[]) {
      for(const id of path.node_ids||[]) ids.add(String(id))
      for(const e of path.edges||[]) {
        const id=String(e.id||`${e.source}:${e.type}:${e.target}`)
        ids.add(String(e.source));ids.add(String(e.target))
        edges.set(id,{id,source:String(e.source),target:String(e.target),type:String(e.type),data:e.properties||{}})
      }
    }
    const nodes=Array.from(ids).map(id=>({id,type:'System',label:id,data:{id}}))
    return {nodes,edges:[...edges.values()]}
  },[impact])
  return <section className="panel"><h3>{title}</h3><p>{impact?.impacted?.length||0} potentially impacted systems; {impact?.paths?.length||0} dependency traversal results.</p>{graph.nodes.length?<GraphView graph={graph} height={260}/>:<EmptyState title="No systems in this impact set"/>}<p className="technical-secondary">Every edge is reconstructed exclusively from explicit backend traversal data.</p></section>
}
export function SimulationsPage(){
 const {config,hasPermission}=useAuth();const [params]=useSearchParams()
 const [mode,setMode]=useState<Mode>('remove_dependency')
 const [situation,setSituation]=useState(params.get('situation')||''),[source,setSource]=useState(''),[target,setTarget]=useState(''),[change,setChange]=useState(''),[actor,setActor]=useState(''),[depth,setDepth]=useState(6)
 const [compatId,setCompatId]=useState('SIM-COMPAT-LAYER')
 const operation=mode==='remove_dependency'?{op:'remove_dependency',source_id:source,target_id:target}:mode==='rollback_change'?{op:'rollback_change',change_id:change}:{op:'add_compatibility_layer',source_id:source,target_id:target,layer_id:compatId}
 const counter=useMutation({mutationFn:()=>runCounterfactual(config,{situation_id:situation,interventions:[operation],max_depth:depth})})
 const bus=useMutation({mutationFn:()=>runBusFactor(config,[actor])})
 const ready=mode==='bus_factor'?!!actor:!!situation&&(mode==='rollback_change'?!!change:!!source&&!!target)
 const result=(mode==='bus_factor'?bus.data:counter.data) as any
 const state=result?.result||{}
 const baseline=state?.canonical_result?.blast_radius||{}, after=state?.counterfactual_result?.blast_radius||{}
 const clearResult=()=>{counter.reset();bus.reset()}
 return <section><div className="page-header"><div><h2>Simulations</h2><p>Explore organizational changes without changing the canonical FalkorDB graph.</p></div><Link to="/scenarios">Browse scenarios</Link></div><div className="notice"><strong>SIMULATION ONLY:</strong> backend computes a hypothetical graph and retains the original graph state.</div>
  <div className="gh-step"><span>01 / CHOOSE YOUR TEST</span><div className="gh-mode-grid">{([['remove_dependency','Remove a dependency','See how deleting an existing DEPENDS_ON edge changes exposure.'],['rollback_change','Rollback a change','Remove the effects of a specific migration or deployment change.'],['add_compatibility_layer','Add compatibility layer','Insert a hypothetical service between two dependent systems.'],['bus_factor','Expert becomes unavailable','Measure organizational coverage after a person is unavailable.']] as const).map(([id,title,description])=><button key={id} type="button" className={mode===id?'gh-mode active':'gh-mode'} aria-pressed={mode===id} onClick={()=>{setMode(id);clearResult()}}><strong>{title}</strong><span>{description}</span></button>)}</div></div>
  <div className="gh-step"><span>02 / SELECT CONNECTED DATA</span><div className="panel gh-form-grid">{mode!=='bus_factor'&&<EntityPicker label="Situation or affected system" value={situation} onChange={setSituation} placeholder="Choose an incident, system, or change root"/>}{mode==='rollback_change'?<EntityPicker label="Change to roll back" kind="Change" value={change} onChange={setChange}/>:mode==='bus_factor'?<EntityPicker label="Person or agent unavailable" kind="Person" value={actor} onChange={setActor}/>:<><EntityPicker label="Dependency source system" kind="System" value={source} onChange={setSource}/><EntityPicker label="Dependency target system" kind="System" value={target} onChange={setTarget}/></>}{mode==='add_compatibility_layer'&&<label className="field"><span>Hypothetical layer ID</span><input value={compatId} onChange={e=>setCompatId(e.target.value)}/></label>}{mode!=='bus_factor'&&<label className="field"><span>Traversal depth: {depth}</span><input type="range" min={1} max={8} value={depth} onChange={e=>setDepth(Number(e.target.value))}/></label>}</div></div>
  <div className="gh-step"><span>03 / REVIEW ASSUMPTIONS</span><div className="panel"><p>{mode==='bus_factor'?'A selected person becomes unavailable. The backend estimates lost expertise coverage.':mode==='rollback_change'?'The chosen change is hypothetically rolled back. Real deployments are not modified.':mode==='remove_dependency'?'Only an existing DEPENDS_ON relationship can be removed from the hypothetical graph.':'A fictional compatibility layer is inserted and connected to the selected systems.'}</p><dl className="kv"><div className="gh-kv-row"><dt>Tenant</dt><dd>{config.tenantId}</dd></div><div className="gh-kv-row"><dt>Analysis root</dt><dd>{mode==='bus_factor'?actor:situation||'Choose an entity first'}</dd></div><div className="gh-kv-row"><dt>Graph write</dt><dd>None · read-only hypothetical computation</dd></div></dl><button className="primary" disabled={!ready||!hasPermission('READ_ORG_ANALYTICS')||counter.isPending||bus.isPending} onClick={()=>mode==='bus_factor'?bus.mutate():counter.mutate()}>{counter.isPending||bus.isPending?'Calculating…':'Run simulation'}</button>{!hasPermission('READ_ORG_ANALYTICS')&&<p className="muted">Your account does not have permission for organizational simulations.</p>}</div></div>
  {(counter.isPending||bus.isPending)&&<LoadingPanel label="Calculating hypothetical impact…"/>}{(counter.error||bus.error)&&<ErrorPanel error={counter.error||bus.error}/>}
  {result&&<div className="gh-step"><span>04 / EXAMINE RESULTS</span><div className="panel"><h3>Simulation result</h3><p><strong>{result.simulation_id}</strong> · {result.simulation_type}</p><p>{result.persisted===false?'No graph changes persisted.':'Persistence not confirmed; check backend response.'}</p>{state.delta&&<div className="gh-simulation-delta"><div><strong>{state.delta.systems_no_longer_exposed?.length||0}</strong><span>Systems no longer exposed</span></div><div><strong>{state.delta.newly_exposed_systems?.length||0}</strong><span>Newly exposed systems</span></div><div><strong>{state.delta.paths_removed_count||0}</strong><span>Paths removed</span></div></div>}{mode==='bus_factor'&&<p>See the coverage and expertise changes calculated by the backend below.</p>}</div>{mode!=='bus_factor'&&<div className="grid-2"><PreviewGraph impact={baseline} title="Original graph impact"/><PreviewGraph impact={after} title="Hypothetical impact"/></div>}{mode==='bus_factor'&&<div className="panel"><h3>Coverage details</h3><dl className="kv">{Object.entries(state||{}).filter(([,v])=>typeof v!=='object').map(([k,v])=><div className="gh-kv-row" key={k}><dt>{k.replace(/_/g,' ')}</dt><dd>{String(v)}</dd></div>)}</dl></div>}<TechnicalDetails title="Technical simulation result"><pre>{JSON.stringify(result,null,2)}</pre></TechnicalDetails></div>}
 </section>
}
