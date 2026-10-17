import { describe,expect,it } from 'vitest'
import { canClaimTask,canResumeTask,canStartTask,taskStatus } from '../permissions'
describe('task controls use backend state',()=>{
 it('reads nested backend task status',()=>expect(taskStatus({task:{status:'READY'}})).toBe('READY'))
 it('claim allowed for ready task',()=>expect(canClaimTask({task:{status:'READY'},readiness:{ready:true}})).toBe(true))
 it('claim blocked by backend readiness',()=>expect(canClaimTask({task:{status:'READY'},readiness:{ready:false}})).toBe(false))
 it('claim blocked for completed task',()=>expect(canClaimTask({task:{status:'COMPLETED'}})).toBe(false))
 it('start allowed when coordination has owner',()=>expect(canStartTask({task:{status:'OPEN'}},{owner:{id:'A'}})).toBe(true))
 it('resume requires an existing execution',()=>expect(canResumeTask({task:{status:'IN_PROGRESS'}},{execution:{id:'EX'}},{})).toBe(true))
 it('resume blocked for terminal task',()=>expect(canResumeTask({task:{status:'COMPLETED'}},{execution:{id:'EX'}},{})).toBe(false))
})
