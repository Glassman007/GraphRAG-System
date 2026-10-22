import {describe,it,expect} from 'vitest'
import {buildDemoHarnessConfig,isAsteriaGraphAvailable} from '../demo/agentRuntimeScope'
import {hasCanonicalEntity,propagationExplanation,isProcessableChangeStatus} from '../demo/asteriaPanelScope'

const config={baseUrl:'',token:'test',tenantId:'asteria',graphId:'a_different_default_graph'}
describe('Demo Lab Asteria component 2/3/4 contracts',()=>{
 it('pins all requests to the Asteria graph even if auth has another default',()=>{
  expect(buildDemoHarnessConfig(config).graphId).toBe('asteria_company_brain_v1')
  expect(isAsteriaGraphAvailable(config,[{graph_id:'asteria_company_brain_v1',available:true}])).toBe(true)
  expect(isAsteriaGraphAvailable({...config,tenantId:'other'},[{graph_id:'asteria_company_brain_v1',available:true}])).toBe(false)
  expect(isAsteriaGraphAvailable(config,[{graph_id:'asteria_company_brain_v1',available:false}])).toBe(false)
 })
 it('does not mistake unrelated IDs for confirmed canonical entities',()=>{
  expect(hasCanonicalEntity({entity:{id:'INC-AST-ROUTE-OUTAGE'}},'INC-AST-ROUTE-OUTAGE')).toBe(true)
  expect(hasCanonicalEntity({entity:{id:'EVD-AST-0003'}},'INC-AST-ROUTE-OUTAGE')).toBe(false)
  expect(hasCanonicalEntity({},'INC-AST-ROUTE-OUTAGE')).toBe(false)
 })
 it('never labels probable events as confirmed workflow propagation',()=>{
  const unconfirmed=propagationExplanation({confidence:'PROBABLE',status:'NEEDS_REVIEW',memory_impacts:[],workflow_impacts:[]})
  expect(unconfirmed).toContain('not authoritative')
  expect(propagationExplanation({confidence:'CONFIRMED',status:'COMPLETED',memory_impacts:[],workflow_impacts:[]})).toContain('no matching')
  expect(propagationExplanation({confidence:'CONFIRMED',status:'FAILED_NEEDS_REVIEW',memory_impacts:[],workflow_impacts:[]})).toContain('failed')
  expect(isProcessableChangeStatus('PENDING')).toBe(true)
  expect(isProcessableChangeStatus('RETRY')).toBe(true)
  expect(isProcessableChangeStatus('NEEDS_REVIEW')).toBe(false)
 })
})
