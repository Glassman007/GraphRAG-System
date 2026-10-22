import {useQuery} from '@tanstack/react-query'
import type {ApiConfig} from '../api/types'
import {apiRequest} from '../api/client'
import {ASTERIA_GRAPH,buildDemoHarnessConfig,isAsteriaGraphAvailable} from './agentRuntimeScope'

type RegisteredBrains={items:{graph_id:string;available:boolean}[]}

/** Reuse the same authorized, explicit Asteria scope as Demo Lab Component 1.
 * This does not grant graph permissions; the backend checks every request. */
export function useAsteriaPanelScope(config:ApiConfig){
 const scopedConfig=buildDemoHarnessConfig(config)
 const registry=useQuery({
  queryKey:['demo-harness-brains',config.baseUrl,config.tenantId,config.token],
  queryFn:({signal})=>apiRequest<RegisteredBrains>(config,'/api/v1/graphs',{signal}),
  enabled:config.tenantId==='asteria',retry:false
 })
 return {scopedConfig,registry,graphAvailable:isAsteriaGraphAvailable(config,registry.data?.items),graphId:ASTERIA_GRAPH}
}

export function hasCanonicalEntity(payload:unknown,id:string):boolean {
 if(!id||!payload||typeof payload!=='object')return false
 const obj=payload as {id?:unknown;entity?:{id?:unknown}}
 return obj.id===id||obj.entity?.id===id
}

export function propagationExplanation(event:{confidence:string;status:string;memory_impacts?:unknown[];workflow_impacts?:unknown[]}):string {
 if(event.confidence!=='CONFIRMED')return 'Source change is not authoritative/confirmed. No verified memory or workflow can be invalidated automatically.'
 if(event.status==='PENDING'||event.status==='RETRY'||event.status==='PROCESSING')return 'Confirmed change is queued or being processed; impact counts may not be final.'
 if(event.status==='FAILED_NEEDS_REVIEW')return 'Propagation failed and requires operator review; do not treat the zero counts as proof of no impact.'
 if(!(event.memory_impacts?.length||event.workflow_impacts?.length))return 'Confirmed change processed; no matching shared verified memory or saved workflow dependency was identified.'
 return 'Recorded impacts are grounded in persisted verified memory and matching saved workflow dependencies.'
}

export function isProcessableChangeStatus(status:string):boolean {
 return status==='PENDING'||status==='RETRY'
}
