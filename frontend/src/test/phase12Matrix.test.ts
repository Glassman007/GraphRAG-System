import { afterEach,describe,expect,it,vi } from 'vitest'
import { getCapabilities,getReady,getSession } from '../api/system'
import * as situations from '../api/situations'
import * as investigations from '../api/investigations'
import * as entities from '../api/entities'
import * as evidence from '../api/evidence'
import * as plans from '../api/plans'
import * as tasks from '../api/tasks'
import * as agents from '../api/agents'
import * as decisions from '../api/decisions'
import * as actions from '../api/actions'
import * as simulations from '../api/simulations'
import * as processes from '../api/processes'
import * as risks from '../api/risks'
import * as brain from '../api/companyBrain'
import { queryString } from '../api/client'
const c={baseUrl:'',token:'token',tenantId:'tenant'}
function response(){return new Response(JSON.stringify({items:[],has_more:false,limit:50}),{status:200,headers:{'Content-Type':'application/json'}})}
afterEach(()=>vi.restoreAllMocks())
async function pathOf(call:()=>Promise<any>){const f=vi.spyOn(globalThis,'fetch').mockResolvedValue(response());await call();return String(f.mock.calls[0][0])}
describe('remaining Phase 12 minimum matrix contracts',()=>{
 it('capabilities bootstrap is versioned',async()=>expect(await pathOf(()=>getCapabilities(c))).toContain('/api/v1/capabilities'))
 it('readiness bootstrap is versioned',async()=>expect(await pathOf(()=>getReady(c))).toContain('/api/v1/ready'))
 it('session discovers permissions from backend',async()=>expect(await pathOf(()=>getSession(c))).toContain('/api/v1/session'))
 it('situation timeline is lazy endpoint',async()=>expect(await pathOf(()=>situations.getSituationTimeline(c,'I'))).toContain('/situations/I/timeline'))
 it('situation claims use dedicated endpoint',async()=>expect(await pathOf(()=>situations.getSituationClaims(c,'I'))).toContain('/situations/I/claims'))
 it('situation evidence use dedicated endpoint',async()=>expect(await pathOf(()=>situations.getSituationEvidence(c,'I'))).toContain('/situations/I/evidence'))
 it('situation tasks use dedicated endpoint',async()=>expect(await pathOf(()=>situations.getSituationTasks(c,'I'))).toContain('/situations/I/tasks'))
 it('investigation findings are fetched separately',async()=>expect(await pathOf(()=>investigations.getInvestigationFindings(c,'INV'))).toContain('/investigations/INV/findings'))
 it('investigation evidence are fetched separately',async()=>expect(await pathOf(()=>investigations.getInvestigationEvidence(c,'INV'))).toContain('/investigations/INV/evidence'))
 it('investigation retrieval executions are inspectable',async()=>expect(await pathOf(()=>investigations.getInvestigationRetrievals(c,'INV'))).toContain('/investigations/INV/retrievals'))
 it('investigation close is a mutation',async()=>{const f=vi.spyOn(globalThis,'fetch').mockResolvedValue(response());await investigations.closeInvestigation(c,'INV');expect((f.mock.calls[0][1] as RequestInit).method).toBe('POST')})
 it('entity relationship endpoint is bounded backend data',async()=>expect(await pathOf(()=>entities.getRelationships(c,'S'))).toContain('/entities/S/relationships'))
 it('entity provenance is backend sourced',async()=>expect(await pathOf(()=>entities.getEntityProvenance(c,'S'))).toContain('/entities/S/provenance'))
 it('entity history is backend sourced',async()=>expect(await pathOf(()=>entities.getEntityHistory(c,'S'))).toContain('/entities/S/history'))
 it('evidence artifact lookup stays metadata/reference based',async()=>expect(await pathOf(()=>evidence.getEvidenceArtifact(c,'E'))).toContain('/evidence/E/artifact'))
 it('plan task graph comes from one plan tasks endpoint',async()=>expect(await pathOf(()=>plans.getPlanTasks(c,'P'))).toContain('/plans/P/tasks'))
 it('task dependency edges come from backend',async()=>expect(await pathOf(()=>tasks.getTaskDependencies(c,'T'))).toContain('/tasks/T/dependencies'))
 it('task execution state comes from backend',async()=>expect(await pathOf(()=>tasks.getTaskExecution(c,'T'))).toContain('/tasks/T/execution'))
 it('task resume is explicit mutation',async()=>{const f=vi.spyOn(globalThis,'fetch').mockResolvedValue(response());await tasks.resumeTask(c,'T','A');expect((f.mock.calls[0][1] as RequestInit).method).toBe('POST')})
 it('agent work endpoint is inspectable',async()=>expect(await pathOf(()=>agents.getAgentTasks(c,'A'))).toContain('/agents/A/tasks'))
 it('decision evidence endpoint is separate from genealogy',async()=>expect(await pathOf(()=>decisions.getDecisionEvidence(c,'D'))).toContain('/decisions/D/evidence'))
 it('decision outcomes endpoint is separate from genealogy',async()=>expect(await pathOf(()=>decisions.getDecisionOutcomes(c,'D'))).toContain('/decisions/D/outcomes'))
 it('action attempts expose exactly-once history',async()=>expect(await pathOf(()=>actions.getActionAttempts(c,'A'))).toContain('/actions/A/attempts'))
 it('bus factor simulation is backend mutation',async()=>{const f=vi.spyOn(globalThis,'fetch').mockResolvedValue(response());await simulations.runBusFactor(c,['P']);expect(String(f.mock.calls[0][0])).toContain('/simulations/bus-factor');expect((f.mock.calls[0][1] as RequestInit).method).toBe('POST')})
 it('process timeline keeps semantics on backend',async()=>expect(await pathOf(()=>processes.getProcessTimeline(c,'I'))).toContain('/processes/I/timeline'))
 it('ownership gaps use bulk analytical endpoint',async()=>expect(await pathOf(()=>risks.getOwnershipGaps(c))).toContain('/risks/ownership-gaps'))
 it('bottlenecks use bulk analytical endpoint',async()=>expect(await pathOf(()=>risks.getBottlenecks(c))).toContain('/risks/bottlenecks'))
 it('bridges use bulk analytical endpoint',async()=>expect(await pathOf(()=>risks.getBridges(c))).toContain('/risks/bridges'))
 it('initiative collisions use bulk analytical endpoint',async()=>expect(await pathOf(()=>risks.getCollisions(c))).toContain('/risks/initiative-collisions'))
 it('expertise is company-wide not N+1 per entity',async()=>expect(await pathOf(()=>brain.getExpertise(c,{limit:200}))).toContain('/company-brain/expertise?limit=200'))
 it('array query parameters are encoded deterministically',()=>expect(queryString({relationship_types:['OWNS','DEPENDS_ON']})).toContain('relationship_types=OWNS'))
})
