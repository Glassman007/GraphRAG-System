import { describe,expect,it } from 'vitest'
import { anomalyToGraph,blastRadiusToGraph,contextToGraph,decisionGenealogyToGraph,filterGraph,investigationToGraph,mergeGraphs,processToGraph,relationshipsToGraph,taskPlanToGraph } from '../graph/adapters'
describe('graph adapters',()=>{
 it('renders situation context relationships',()=>{const g=contextToGraph({situation:{id:'I',_labels:['Incident']},affected_entities:[{id:'S',_labels:['System']}],relationships:[{relationship:{source:'I',target:'S',type:'AFFECTS'},neighbor:{id:'S'}}]});expect(g.nodes.map(n=>n.id)).toEqual(expect.arrayContaining(['I','S']));expect(g.edges[0].type).toBe('AFFECTS')})
 it('renders task prerequisites as backend REQUIRES edges',()=>{const g=taskPlanToGraph({tasks:[{task:{id:'T2'},prerequisites:[{entity:{id:'T1'}}]}]});expect(g.edges).toEqual(expect.arrayContaining([expect.objectContaining({source:'T2',target:'T1',type:'REQUIRES'})]))})
 it('keeps BEFORE separate from CAUSE',()=>{const g=processToGraph({steps:[{id:'A'},{id:'B'}],temporal_edges:[{source:'A',target:'B',type:'BEFORE'}],causal_edges:[{source:'B',target:'A',type:'CAUSE'}]});expect(new Set(g.edges.map(e=>e.type))).toEqual(new Set(['BEFORE','CAUSE']))})
 it('renders retrieval graph scope without global inference',()=>{const g=investigationToGraph({id:'INV'},[],[],{graph_scope:{entities:[{id:'S'}],relationships:[{source:'INV',target:'S',type:'ABOUT'}]}});expect(g.nodes.map(n=>n.id)).toContain('S')})
 it('renders decision genealogy',()=>{const g=decisionGenealogyToGraph({decision:{id:'D'},claims:[{id:'C'}],actions:[{id:'A'}],outcomes:[{id:'O'}]});expect(g.nodes.map(n=>n.id)).toEqual(expect.arrayContaining(['D','C','A','O']))})
 it('renders blast paths',()=>{const g=blastRadiusToGraph({paths:[{edges:[{source:'S1',target:'S2',type:'DEPENDS_ON'}]}]},'S1');expect(g.edges[0].type).toBe('DEPENDS_ON')})
 it('renders anomaly abnormal edge',()=>{const g=anomalyToGraph({abnormal_edge:{source:'F',target:'DB',type:'DEPENDS_ON'}});expect(g.edges[0].data.abnormal).toBe(true)})

 it('preserves string relationship types from the real v1 neighbor shape',()=>{const g=contextToGraph({situation:{id:'I'},relationships:[{relationship:'AFFECTS',source:'I',target:'S',neighbor:{id:'S'}}]});expect(g.edges[0].type).toBe('AFFECTS')})
 it('turns bounded neighbor expansion into graph material',()=>{const g=relationshipsToGraph([{relationship:'DEPENDS_ON',source:'A',target:'B',neighbor:{id:'B'}}]);expect(g.nodes.map(n=>n.id)).toEqual(expect.arrayContaining(['A','B']));expect(g.edges[0].type).toBe('DEPENDS_ON')})
 it('merges graph expansions without duplicate node ids',()=>{const g=mergeGraphs({nodes:[{id:'A',type:'System',label:'A',data:{}}],edges:[]},{nodes:[{id:'A',type:'System',label:'A2',data:{}}],edges:[]});expect(g.nodes).toHaveLength(1)})
 it('filters graph locally only for visualization',()=>{const g=filterGraph({nodes:[{id:'A',type:'System',label:'A',status:'ACTIVE',data:{}},{id:'B',type:'Team',label:'B',data:{}}],edges:[{id:'e',source:'A',target:'B',type:'OWNS',data:{}}]},{nodeType:'System'});expect(g.nodes.map(n=>n.id)).toEqual(['A']);expect(g.edges).toEqual([])})
})
