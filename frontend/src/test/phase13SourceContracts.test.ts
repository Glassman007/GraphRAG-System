import { describe,expect,it,vi,beforeEach } from 'vitest'
import { createSource,listConnectors,listSources,previewSource,syncSource,testSource } from '../api/sources'
const config={baseUrl:'',token:'test-admin-token',tenantId:'northstar'}
beforeEach(()=>vi.restoreAllMocks())
describe('Phase 13 source API contracts',()=>{
 it.each([
  ['list connectors',()=>listConnectors(config)],['list sources',()=>listSources(config)],['create source',()=>createSource(config,{display_name:'Northstar GitHub',connector_type:'github'})],['test connection',()=>testSource(config,'SRC-1')],['preview ingestion',()=>previewSource(config,'SRC-1')],['manual sync',()=>syncSource(config,'SRC-1')],
 ])('%s uses /api/v1',async(_name,call)=>{const spy=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({items:[]}),{status:200,headers:{'Content-Type':'application/json'}}));await call();expect(String(spy.mock.calls[0][0])).toContain('/api/v1/')})
})
