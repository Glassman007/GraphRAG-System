import {describe,expect,it} from 'vitest'
import {ASTERIA_GRAPH,buildDemoHarnessConfig,isAsteriaGraphAvailable} from '../demo/agentRuntimeScope'

describe('Demo Lab model harness graph scope',()=>{
 const auth={baseUrl:'http://localhost:8000',tenantId:'asteria',token:'test-session'}
 it('forces explicit Asteria Company Brain without changing auth',()=>{
  const next=buildDemoHarnessConfig(auth)
  expect(next).toEqual({...auth,graphId:ASTERIA_GRAPH})
  expect(next).not.toBe(auth)
 })
 it('does not accept unknown or unavailable registrations',()=>{
  expect(isAsteriaGraphAvailable(auth,undefined)).toBe(false)
  expect(isAsteriaGraphAvailable(auth,[])).toBe(false)
  expect(isAsteriaGraphAvailable(auth,[{graph_id:ASTERIA_GRAPH,available:false}])).toBe(false)
  expect(isAsteriaGraphAvailable(auth,[{graph_id:'unrelated',available:true}])).toBe(false)
 })
 it('requires both Asteria identity and an authorized available graph',()=>{
  const records=[{graph_id:ASTERIA_GRAPH,available:true}]
  expect(isAsteriaGraphAvailable(auth,records)).toBe(true)
  expect(isAsteriaGraphAvailable({...auth,tenantId:'northstar'},records)).toBe(false)
 })
})
