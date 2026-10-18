import {describe,expect,it} from 'vitest'
import {allScenarios,buildGuide,contextComparison,tracks,capabilityRegister,scenarioCountByTrack} from '../demo/demoModel'

describe('Step 4 acceptance-oriented demo contract',()=>{
 it('provides exactly 24 complete, unique synthetic scenario walkthroughs across all hackathon tracks',()=>{
  expect(allScenarios).toHaveLength(24)
  expect(new Set(allScenarios.map(s=>s.scenario_id)).size).toBe(24)
  expect(scenarioCountByTrack().reduce((n,x)=>n+x.total,0)).toBe(24)
  for(const t of tracks)expect(allScenarios.some(s=>s.track===t.id)).toBe(true)
  for(const s of allScenarios){
   expect(s.entry_ids.length).toBeGreaterThan(0)
   expect(s.starting_state.fixture_version).toBe('asteria-v1')
   const steps=buildGuide(s)
   expect(steps.length).toBeGreaterThanOrEqual(4)
   expect(new Set(steps.map(x=>x.key)).size).toBe(steps.length)
   expect(steps.every(x=>x.url.startsWith('/')&&x.expect.length>15)).toBe(true)
   expect(JSON.stringify(s).toLowerCase()).not.toContain('golden answer')
  }
 })
 it('keeps simulated fixture presence separate from live execution',()=>{
  const proposals=capabilityRegister.filter(x=>x.level==='PROPOSED')
  expect(proposals.some(x=>x.name.includes('autonomy'))).toBe(true)
  expect(proposals.some(x=>x.name.includes('conversational recall'))).toBe(true)
 })
 it('reports graph-context counts from actual response shapes, never fabricated advantages',()=>{
  const result=contextComparison({id:'SYS-1',name:'Route DB'},{items:[
   {neighbor:{id:'SYS-2'},type:'DEPENDS_ON'},
   {neighbor:{id:'SYS-2'},relationship:'OWNS'},
   {neighbor:{id:'SYS-3'},type:'AFFECTS'},
  ]})
  expect(result.alone).toBe(1)
  expect(result.related).toBe(2)
  expect(result.relationships).toBe(3)
  expect(result.relationshipTypes).toEqual(['AFFECTS','DEPENDS_ON','OWNS'])
  expect(contextComparison({id:'EMPTY'},{items:[]}).relationships).toBe(0)
 })
 it('does not have hidden benchmark answers in the public scenario source',()=>{
  const src=JSON.stringify(allScenarios)
  expect(src).not.toContain('required_typed_edges')
  expect(src).not.toContain('absent_relationships')
  expect(src).not.toContain('final_answer')
 })
})
