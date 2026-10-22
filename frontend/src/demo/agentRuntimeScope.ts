import type {ApiConfig} from '../api/types'

/** This Demo Lab contains Asteria-versioned scenarios only. Never fall back to the API default graph. */
export const ASTERIA_GRAPH='asteria_company_brain_v1'

export function buildDemoHarnessConfig(config:ApiConfig):ApiConfig {
 return {...config,graphId:ASTERIA_GRAPH}
}

export function isAsteriaGraphAvailable(config:ApiConfig,items?:{graph_id:string;available:boolean}[]):boolean {
 return config.tenantId==='asteria'&&Boolean(items?.some(item=>item.graph_id===ASTERIA_GRAPH&&item.available))
}
