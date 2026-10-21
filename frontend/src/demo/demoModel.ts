import scenarioPack from '../data/asteriaScenarios.json'

export type Track = 'COMPANY_BRAIN'|'CONNECTED_AGENTS'|'AGENT_MEMORY_COORDINATION'
export type Scenario = (typeof scenarioPack)[number]
export type GuideStep = {key:string;title:string;purpose:string;url:string;kind:'read'|'write';expect:string}
export const tracks:{id:Track;title:string;description:string}[]=[
 {id:'COMPANY_BRAIN',title:'Company Brain',description:'Discover hidden relationships, conflicting evidence and historical context.'},
 {id:'CONNECTED_AGENTS',title:'Agents on Connected Data',description:'Investigate a situation, plan linked work and apply governance.'},
 {id:'AGENT_MEMORY_COORDINATION',title:'Agent Memory & Coordination',description:'Inspect task handoffs, persisted findings, checkpoints and conflicts.'},
]
export const allScenarios=scenarioPack as Scenario[]
export function routeForEntity(id:string){return `/entities/${encodeURIComponent(id)}`}
export function buildGuide(s:Scenario):GuideStep[]{
 const root=s.entry_ids[0]||''
 const incident=s.entry_ids.find(id=>id.startsWith('INC-'))||s.focus_ids.find(id=>id.startsWith('INC-'))
 const situation=incident?`/situations/${encodeURIComponent(incident)}`:routeForEntity(root)
 const context=`/company-brain?tab=processes&scope=${encodeURIComponent(incident||root)}`
 const work=`/work?tab=plans&scenario=${encodeURIComponent(s.scenario_id)}`
 const steps:GuideStep[]=[
  {key:'discover',title:'Discover the organizational record',purpose:'Identify the entity and its canonical ID without typing it.',url:routeForEntity(root),kind:'read',expect:'An entity card with its current status, description and connected relationships.'},
  {key:'graph',title:'Explore connected context',purpose:'Follow recorded graph links and distinguish direct facts from inferred paths.',url:context,kind:'read',expect:'A backend-derived graph or an explicit unsupported/empty-state result.'},
 ]
 if(s.track==='COMPANY_BRAIN')return [...steps,
  {key:'knowledge',title:'Examine evidence and uncertainty',purpose:'Look for sourced claims and contradictions, not merely an answer.',url:'/knowledge',kind:'read',expect:'Claims or evidence with status, provenance and uncertainty.'},
  {key:'decisions',title:'Review decision history',purpose:'Trace what the organization decided and why.',url:'/decisions',kind:'read',expect:'Recorded decisions, or a clear no-data result.'},
  {key:'simulation',title:'Test a counterfactual',purpose:'Use a supported, non-mutating simulation on a selected entity.',url:`/simulations?situation=${encodeURIComponent(incident||root)}`,kind:'read',expect:'A hypothetical impact comparison after a simulation is explicitly run.'},
 ]
 if(s.track==='CONNECTED_AGENTS')return [...steps,
  {key:'situation',title:'Inspect the situation',purpose:'Review the incident and attached graph context.',url:situation,kind:'read',expect:'Description, affected systems and links to evidence and tasks.'},
  {key:'knowledge',title:'Review organizational knowledge',purpose:'Read claims, conflicting observations and provenance relevant to the incident.',url:'/knowledge',kind:'read',expect:'Recorded claims and evidence, not automatically accepted as fact.'},
  {key:'investigate',title:'Investigate with evidence',purpose:'Create an investigation in the Situations screen, then retrieve evidence.',url:incident?situation:'/investigations',kind:'write',expect:'A newly created investigation only after explicit user action, with provenance-linked retrieval results.'},
  {key:'work',title:'Generate and coordinate work',purpose:'Create a plan from the scenario, then inspect its task dependencies.',url:work,kind:'write',expect:'A recorded plan with inspectable task prerequisites and assigned agents.'},
  {key:'decisions',title:'Review decisions and alternatives',purpose:'Inspect the decision register and evidence genealogy before proposing remediation.',url:'/decisions',kind:'read',expect:'Decision records and their evidence-backed alternatives, if recorded.'},
  {key:'governance',title:'Review approval before action',purpose:'Check backend governance without executing an external side effect.',url:'/work?tab=actions',kind:'read',expect:'Action state and approval requirements; no execution is automatically triggered.'},
  {key:'simulation',title:'Compare hypothetical outcomes',purpose:'Use the Simulations tab to measure changed exposure.',url:`/simulations?situation=${encodeURIComponent(incident||root)}`,kind:'read',expect:'Computed baseline and hypothetical results when the operation is supported.'},
 ]
 return [...steps,
  {key:'tasks',title:'Inspect coordinated tasks',purpose:'Find blockers, dependencies and assigned specialists.',url:'/work?tab=tasks',kind:'read',expect:'Task state and explicit dependency records.'},
  {key:'agents',title:'Identify eligible agents',purpose:'Inspect declared capabilities and task ownership.',url:'/work?tab=agents',kind:'read',expect:'Supported task types, tools and permissions.'},
  {key:'memory',title:'Examine recorded agent memory',purpose:'Distinguish persisted graph records from model conversational memory.',url:'/work?tab=memory',kind:'read',expect:'Evidence-backed findings and checkpoints if persisted, or a clear empty state.'},
  {key:'handoff',title:'Validate a handoff or recover task',purpose:'Inspect contract validation, blockers, pause and retry under backend rules.',url:'/work?tab=tasks',kind:'write',expect:'Recorded status transitions only when permitted, not a simulated successful execution.'},
  {key:'outcomes',title:'Compare planned and recorded outcomes',purpose:'Check what really executed and what remains blocked.',url:'/work?tab=actions',kind:'read',expect:'Governance attempts and any recorded execution outcomes.'},
 ]
}
export type CapabilityLevel = 'IMPLEMENTED'|'PARTIAL'|'PROPOSED'
export const capabilityRegister:{name:string;track:Track;level:CapabilityLevel;scope:string}[]=[
 {name:'Entity and relationship exploration',track:'COMPANY_BRAIN',level:'IMPLEMENTED',scope:'Tenant-scoped graph reads and provenance views'},
 {name:'Temporal ownership and sourced claims',track:'COMPANY_BRAIN',level:'IMPLEMENTED',scope:'Recorded graph history; answer quality depends on evidence'},
 {name:'Graph-first retrieval',track:'CONNECTED_AGENTS',level:'IMPLEMENTED',scope:'On-demand retrieval in an explicitly created investigation'},
 {name:'Governed action proposals and attempts',track:'CONNECTED_AGENTS',level:'IMPLEMENTED',scope:'Backend approvals and permissions; not automatic execution'},
 {name:'Continuous autonomous model execution',track:'CONNECTED_AGENTS',level:'PARTIAL',scope:'Multi-agent DAG runs exist; source-change reactivation requires fresh model consent'},
 {name:'Task/checkpoint persistence and formal handoffs',track:'AGENT_MEMORY_COORDINATION',level:'IMPLEMENTED',scope:'Graph-backed states, contract validation and task coordination'},
 {name:'Verified cross-session agent knowledge',track:'AGENT_MEMORY_COORDINATION',level:'IMPLEMENTED',scope:'FalkorDB source-backed facts; private drafts not reusable'},
 {name:'Reactive fact verification and targeted replan',track:'AGENT_MEMORY_COORDINATION',level:'PARTIAL',scope:'Authoritative ingestion events recheck memory and flag only affected tasks; automatic model calls require consent'},
 {name:'Self-running cross-agent conflict resolution',track:'AGENT_MEMORY_COORDINATION',level:'PARTIAL',scope:'Explicit conflicts and verifier controls; resolution is user-guided'},
]
export function contextComparison(entity:any,neighbors:any){
 const items=Array.isArray(neighbors?.items)?neighbors.items:[]
 const links=items.filter((r:any)=>r&&typeof r==='object'&&r.neighbor&&(r.type||r.relationship))
 const ids=new Set(links.map((r:any)=>String(r.neighbor?.id||'')).filter(Boolean))
 const types=new Set(links.map((r:any)=>String(typeof r.relationship==='string'?r.relationship:r.relationship?.type||r.type||'')).filter(Boolean))
 return {entity:String(entity?.name||entity?.title||entity?.id||'Selected record'),alone:1,related:ids.size,relationships:links.length,relationshipTypes:[...types].sort()}
}
export function scenarioCountByTrack(){return tracks.map(t=>({...t,total:allScenarios.filter(s=>s.track===t.id).length}))}
