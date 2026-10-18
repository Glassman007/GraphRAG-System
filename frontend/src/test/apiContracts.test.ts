import { afterEach,describe,expect,it,vi } from 'vitest'
import * as situations from '../api/situations'
import * as investigations from '../api/investigations'
import * as entities from '../api/entities'
import * as graph from '../api/graph'
import * as claims from '../api/claims'
import * as evidence from '../api/evidence'
import * as plans from '../api/plans'
import * as tasks from '../api/tasks'
import * as agents from '../api/agents'
import * as decisions from '../api/decisions'
import * as actions from '../api/actions'
import * as simulations from '../api/simulations'
import * as processes from '../api/processes'
import * as risks from '../api/risks'
import * as anomalies from '../api/anomalies'
import * as brain from '../api/companyBrain'
import * as system from '../api/system'
import { createQueryClient } from '../queryClient'
const c={baseUrl:'',token:'t',tenantId:'northstar'}
function ok(body:any={}){return new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}})}
afterEach(()=>vi.restoreAllMocks())
async function expectPath(call:()=>Promise<any>,path:string,method='GET'){const f=vi.spyOn(globalThis,'fetch').mockResolvedValue(ok({items:[],has_more:false,limit:50}));await call();expect(String(f.mock.calls[0][0])).toContain(path);expect(((f.mock.calls[0][1] as RequestInit)?.method||'GET')).toBe(method)}
describe('Phase 11 API -> frontend contracts',()=>{
 it('situations list',()=>expectPath(()=>situations.listSituations(c),'/api/v1/situations'))
 it('situation detail',()=>expectPath(()=>situations.getSituation(c,'INC'),'/api/v1/situations/INC'))
 it('situation context',()=>expectPath(()=>situations.getSituationContext(c,'INC'),'/api/v1/situations/INC/context'))
 it('situation investigation mutation',()=>expectPath(()=>situations.investigateSituation(c,'INC',{question:'q'}),'/api/v1/situations/INC/investigate','POST'))
 it('investigation detail',()=>expectPath(()=>investigations.getInvestigation(c,'INV'),'/api/v1/investigations/INV'))
 it('investigation retrieval',()=>expectPath(()=>investigations.retrieveInvestigation(c,'INV',{query:'q'}),'/api/v1/investigations/INV/retrieve','POST'))
 it('entity detail',()=>expectPath(()=>entities.getEntity(c,'SYS'),'/api/v1/entities/SYS'))
 it('entity neighbors',()=>expectPath(()=>entities.getNeighbors(c,'SYS'),'/api/v1/entities/SYS/neighbors'))
 it('blast radius',()=>expectPath(()=>entities.getBlastRadius(c,'SYS'),'/api/v1/entities/SYS/blast-radius'))
 it('bounded paths',()=>expectPath(()=>graph.findPaths(c,{from:'A',to:'B'}),'/api/v1/paths'))
 it('claim list',()=>expectPath(()=>claims.listClaims(c),'/api/v1/claims'))
 it('claim conflicts',()=>expectPath(()=>claims.getClaimConflicts(c,'C'),'/api/v1/claims/C/conflicts'))
 it('authority resolution',()=>expectPath(()=>claims.resolveConflict(c,'INC'),'/api/v1/conflicts/INC/resolve'))
 it('claim revalidation mutation',()=>expectPath(()=>claims.revalidateClaim(c,'C','E'),'/api/v1/claims/C/revalidate','POST'))
 it('evidence provenance',()=>expectPath(()=>evidence.getEvidenceProvenance(c,'E'),'/api/v1/evidence/E/provenance'))
 it('evidence invalidation mutation',()=>expectPath(()=>evidence.invalidateEvidence(c,'E','bad'),'/api/v1/evidence/E/invalidate','POST'))
 it('plans list',()=>expectPath(()=>plans.listPlans(c),'/api/v1/plans'))
 it('plan creation',()=>expectPath(()=>plans.createPlan(c,{situation_id:'INC',goal:'g'}),'/api/v1/plans','POST'))
 it('task coordination',()=>expectPath(()=>tasks.getTaskCoordination(c,'T'),'/api/v1/tasks/T/coordination-state'))
 it('task claim mutation',()=>expectPath(()=>tasks.claimTask(c,'T','A'),'/api/v1/tasks/T/claim','POST'))
 it('agent capabilities',()=>expectPath(()=>agents.getAgentCapabilities(c,'A'),'/api/v1/agents/A/capabilities'))
 it('decision genealogy',()=>expectPath(()=>decisions.getDecisionGenealogy(c,'D'),'/api/v1/decisions/D/genealogy'))
 it('action governance',()=>expectPath(()=>actions.getActionGovernance(c,'ACT'),'/api/v1/actions/ACT/governance'))
 it('action execute mutation',()=>expectPath(()=>actions.executeAction(c,'ACT','A'),'/api/v1/actions/ACT/execute','POST'))
 it('counterfactual mutation',()=>expectPath(()=>simulations.runCounterfactual(c,{situation_id:'I',interventions:[{}]}),'/api/v1/simulations/counterfactual','POST'))
 it('process reconstruction',()=>expectPath(()=>processes.getProcess(c,'I'),'/api/v1/processes/I'))
 it('policy drift',()=>expectPath(()=>processes.getPolicyDrift(c,'I','P'),'/api/v1/processes/I/policy-drift'))
 it('commitment risks',()=>expectPath(()=>risks.getCommitments(c),'/api/v1/risks/commitments'))
 it('bus factor',()=>expectPath(()=>risks.getBusFactor(c),'/api/v1/risks/bus-factor'))
 it('anomalies facade',()=>expectPath(()=>anomalies.getAnomalies(c),'/api/v1/anomalies'))
 it('company expertise facade',()=>expectPath(()=>brain.getExpertise(c),'/api/v1/company-brain/expertise'))
 it('unsafe mutations are not automatically retried',()=>{expect(createQueryClient().getDefaultOptions().mutations?.retry).toBe(false)})
})


describe('additional external API contracts',()=>{
 it('system capabilities',()=>expectPath(()=>system.getCapabilities(c),'/api/v1/capabilities'))
 it('system readiness',()=>expectPath(()=>system.getReady(c),'/api/v1/ready'))
 it('session discovery',()=>expectPath(()=>system.getSession(c),'/api/v1/session'))
 it('investigation create',()=>expectPath(()=>investigations.createInvestigation(c,{situation_id:'INC',question:'q'}),'/api/v1/investigations','POST'))
 it('investigation findings',()=>expectPath(()=>investigations.getInvestigationFindings(c,'INV'),'/api/v1/investigations/INV/findings'))
 it('investigation evidence',()=>expectPath(()=>investigations.getInvestigationEvidence(c,'INV'),'/api/v1/investigations/INV/evidence'))
 it('investigation retrieval history',()=>expectPath(()=>investigations.getInvestigationRetrievals(c,'INV'),'/api/v1/investigations/INV/retrievals'))
 it('investigation close mutation',()=>expectPath(()=>investigations.closeInvestigation(c,'INV'),'/api/v1/investigations/INV/close','POST'))
 it('entity search',()=>expectPath(()=>entities.searchEntities(c,'pricing'),'/api/v1/entities/search'))
 it('entity relationships',()=>expectPath(()=>entities.getRelationships(c,'SYS'),'/api/v1/entities/SYS/relationships'))
 it('entity provenance',()=>expectPath(()=>entities.getEntityProvenance(c,'SYS'),'/api/v1/entities/SYS/provenance'))
 it('entity history',()=>expectPath(()=>entities.getEntityHistory(c,'SYS'),'/api/v1/entities/SYS/history'))
 it('evidence detail',()=>expectPath(()=>evidence.getEvidence(c,'E'),'/api/v1/evidence/E'))
 it('evidence artifact references',()=>expectPath(()=>evidence.getEvidenceArtifact(c,'E'),'/api/v1/evidence/E/artifact'))
 it('artifact metadata',()=>expectPath(()=>evidence.getArtifactMetadata(c,'ART'),'/api/v1/artifacts/ART/metadata'))
 it('plan detail',()=>expectPath(()=>plans.getPlan(c,'P'),'/api/v1/plans/P'))
 it('plan tasks',()=>expectPath(()=>plans.getPlanTasks(c,'P'),'/api/v1/plans/P/tasks'))
 it('task list',()=>expectPath(()=>tasks.listTasks(c),'/api/v1/tasks'))
 it('task detail',()=>expectPath(()=>tasks.getTask(c,'T'),'/api/v1/tasks/T'))
 it('task dependencies',()=>expectPath(()=>tasks.getTaskDependencies(c,'T'),'/api/v1/tasks/T/dependencies'))
 it('task execution',()=>expectPath(()=>tasks.getTaskExecution(c,'T'),'/api/v1/tasks/T/execution'))
 it('task start mutation',()=>expectPath(()=>tasks.startTask(c,'T','A'),'/api/v1/tasks/T/start','POST'))
 it('task resume mutation',()=>expectPath(()=>tasks.resumeTask(c,'T','A'),'/api/v1/tasks/T/resume','POST'))
 it('task checkpoint mutation',()=>expectPath(()=>tasks.checkpointTask(c,'T',{agent_id:'A',step_index:0,current_step:'x'}),'/api/v1/tasks/T/checkpoint','POST'))
 it('agent list',()=>expectPath(()=>agents.listAgents(c),'/api/v1/agents'))
 it('agent tasks',()=>expectPath(()=>agents.getAgentTasks(c,'A'),'/api/v1/agents/A/tasks'))
 it('decision list',()=>expectPath(()=>decisions.listDecisions(c),'/api/v1/decisions'))
 it('decision evidence',()=>expectPath(()=>decisions.getDecisionEvidence(c,'D'),'/api/v1/decisions/D/evidence'))
 it('decision outcomes',()=>expectPath(()=>decisions.getDecisionOutcomes(c,'D'),'/api/v1/decisions/D/outcomes'))
 it('action list',()=>expectPath(()=>actions.listActions(c),'/api/v1/actions'))
 it('action proposal mutation',()=>expectPath(()=>actions.proposeAction(c,{task_id:'T',agent_id:'A',action_type:'rollback'}),'/api/v1/actions','POST'))
 it('action attempts',()=>expectPath(()=>actions.getActionAttempts(c,'ACT'),'/api/v1/actions/ACT/attempts'))
 it('bus factor simulation mutation',()=>expectPath(()=>simulations.runBusFactor(c,['A']),'/api/v1/simulations/bus-factor','POST'))
 it('simulation lookup',()=>expectPath(()=>simulations.getSimulation(c,'SIM'),'/api/v1/simulations/SIM'))
 it('process timeline',()=>expectPath(()=>processes.getProcessTimeline(c,'I'),'/api/v1/processes/I/timeline'))
 it('risk summary',()=>expectPath(()=>risks.getRisks(c),'/api/v1/risks'))
 it('ownership gaps',()=>expectPath(()=>risks.getOwnershipGaps(c),'/api/v1/risks/ownership-gaps'))
 it('bottlenecks',()=>expectPath(()=>risks.getBottlenecks(c),'/api/v1/risks/bottlenecks'))
 it('bridges',()=>expectPath(()=>risks.getBridges(c),'/api/v1/risks/bridges'))
 it('initiative collisions',()=>expectPath(()=>risks.getCollisions(c),'/api/v1/risks/initiative-collisions'))
})
