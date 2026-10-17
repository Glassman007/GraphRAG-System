import { describe,expect,it } from 'vitest'
import { confidenceText,presentClaim,presentEntity,presentEvidence,presentRelationship,presentRisk,presentStatus,presentTemporal } from '../presentation'
describe('Phase 13 deterministic presentation layer',()=>{
 it('entity canonical ID is secondary data',()=>{const p=presentEntity({id:'SYS-PRICING-API',name:'Pricing API',_labels:['Entity','System'],status:'ACTIVE'});expect(p.title).toBe('Pricing API');expect(p.canonicalId).toBe('SYS-PRICING-API')})
 it('relationship DEPENDS_ON is human readable',()=>expect(presentRelationship('DEPENDS_ON','Checkout','Pricing API').phrase).toBe('Checkout depends on Pricing API'))
 it('unknown relationship has readable fallback',()=>expect(presentRelationship('OWNS_SERVICE_COMPONENT','Team','Adapter').phrase).toContain('owns service component'))
 it('VALIDATED is friendly',()=>expect(presentStatus('VALIDATED')).toBe('Validated'))
 it('UNVERIFIED is friendly',()=>expect(presentStatus('UNVERIFIED')).toBe('Not yet verified'))
 it('confidence .86 is high percent',()=>expect(confidenceText(.86)).toBe('High · 86%'))
 it('temporal current state is current',()=>expect(presentTemporal({status:'ACTIVE'}).label).toBe('Current'))
 it('temporal valid_until is historical',()=>expect(presentTemporal({valid_until:'2026-10-16'}).label).toBe('Historical'))
 it('superseded state is historical',()=>expect(presentTemporal({status:'SUPERSEDED'}).current).toBe(false))
 it('claim leads with assertion',()=>expect(presentClaim({id:'C-1',statement:'Deployment broke schema compatibility',status:'VALIDATED',confidence:.86}).title).toBe('Deployment broke schema compatibility'))
 it('evidence leads with source/time/meaning',()=>{const p=presentEvidence({id:'E-1',source_name:'Pricing telemetry',observed_at:'14:08',snippet:'region_scope cannot be null'});expect(p.source).toBe('Pricing telemetry');expect(p.meaning).toContain('region_scope')})
 it('risk explains consequence',()=>expect(presentRisk({risk_type:'BUS_FACTOR',bus_factor:1}).summary).toContain('concentrated'))
})
