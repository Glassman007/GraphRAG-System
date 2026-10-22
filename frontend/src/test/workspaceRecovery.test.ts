import {describe,expect,it} from 'vitest'
import {workspaceRecoveryState} from '../pages/workspaceRecovery'

const checkpoint={revision:42,reactive_affected_tasks:[]}
const complete=Array.from({length:4},()=>({status:'COMPLETED'}))
const run=(status:string,recovery_available=true)=>({status,recovery_available})

describe('Workspace recovery action eligibility',()=>{
  it('does not offer retry for an evidence-review-only Asteria investigation',()=>{
    const state=workspaceRecoveryState(run('NEEDS_REVIEW'),checkpoint,complete)
    expect(state.reviewOnly).toBe(true)
    expect(state.canRetry).toBe(false)
    expect(state.hasCheckpoint).toBe(true)
  })
  it('does not offer retry when pre-supervisor startup failed without a checkpoint',()=>{
    const state=workspaceRecoveryState(run('FAILED'),undefined,[])
    expect(state.missingCheckpoint).toBe(true)
    expect(state.canRetry).toBe(false)
  })
  it('offers retry only when failed or blocked tasks have a checkpoint',()=>{
    const state=workspaceRecoveryState(run('NEEDS_REVIEW'),checkpoint,
      [{status:'COMPLETED'},{status:'FAILED'},{status:'BLOCKED'}])
    expect(state.canRetry).toBe(true)
  })
  it('offers resume for an interrupted run with a valid checkpoint',()=>{
    const state=workspaceRecoveryState(run('INTERRUPTED'),checkpoint,[])
    expect(state.canResume).toBe(true)
    expect(state.canRetry).toBe(false)
  })
  it('keeps actions disabled when workspace does not authorize recovery',()=>{
    const state=workspaceRecoveryState(run('FAILED',false),checkpoint,[{status:'FAILED'}])
    expect(state.canRetry).toBe(false)
  })
  it('allows targeted evidence re-verification if checkpoint explicitly lists affected tasks',()=>{
    const state=workspaceRecoveryState(run('NEEDS_REVIEW'),
      {revision:44,reactive_affected_tasks:['verify_findings']},complete)
    expect(state.canRetry).toBe(true)
    expect(state.reviewOnly).toBe(false)
  })
})

