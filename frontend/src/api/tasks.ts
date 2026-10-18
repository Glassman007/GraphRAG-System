import { apiRequest, queryString } from './client'
import type { ApiConfig, Dict, PageResponse } from './types'
export const listTasks=(c:ApiConfig,p:Dict={},signal?:AbortSignal)=>apiRequest<PageResponse>(c,`/api/v1/tasks${queryString(p)}`,{signal})
export const getTask=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/tasks/${encodeURIComponent(id)}`,{signal})
export const getTaskDependencies=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/tasks/${encodeURIComponent(id)}/dependencies`,{signal})
export const getTaskCoordination=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/tasks/${encodeURIComponent(id)}/coordination-state`,{signal})
export const getTaskExecution=(c:ApiConfig,id:string,signal?:AbortSignal)=>apiRequest<Dict>(c,`/api/v1/tasks/${encodeURIComponent(id)}/execution`,{signal})
const mutate=(c:ApiConfig,id:string,op:string,body:Dict)=>apiRequest<Dict>(c,`/api/v1/tasks/${encodeURIComponent(id)}/${op}`,{method:'POST',body})
export const claimTask=(c:ApiConfig,id:string,agentId:string)=>mutate(c,id,'claim',{agent_id:agentId})
export const startTask=(c:ApiConfig,id:string,agentId:string)=>mutate(c,id,'start',{agent_id:agentId})
export const resumeTask=(c:ApiConfig,id:string,agentId:string,executionId?:string)=>mutate(c,id,'resume',{agent_id:agentId,execution_id:executionId})
export const checkpointTask=(c:ApiConfig,id:string,body:Dict)=>mutate(c,id,'checkpoint',body)
