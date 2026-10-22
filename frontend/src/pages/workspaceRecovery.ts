/** Derive recoverable actions from persisted state, not the NEEDS_REVIEW label alone. */
export type RecoveryWorkspace = { status:string; recovery_available:boolean }
export type RecoveryCheckpoint = {revision?:number; reactive_affected_tasks?:string[]}
export type RecoveryTask = {status:string}

export function workspaceRecoveryState(
  workspace:RecoveryWorkspace|undefined,
  checkpoint:RecoveryCheckpoint|undefined,
  tasks:readonly RecoveryTask[],
) {
  const hasCheckpoint=typeof checkpoint?.revision==='number' &&
    Number.isInteger(checkpoint.revision) && checkpoint.revision>=0
  const hasFailedWork=tasks.some(task=>['FAILED','BLOCKED'].includes(task.status))
  const hasReactiveWork=Boolean(checkpoint?.reactive_affected_tasks?.length)
  const hasRecoveryRight=Boolean(workspace?.recovery_available)
  const canResume=hasRecoveryRight && hasCheckpoint &&
    ['PAUSED','INTERRUPTED'].includes(workspace?.status||'')
  const canRetry=hasRecoveryRight && hasCheckpoint &&
    ['FAILED','PARTIAL','NEEDS_REVIEW'].includes(workspace?.status||'') &&
    (hasFailedWork || hasReactiveWork)
  const reviewOnly=workspace?.status==='NEEDS_REVIEW' && tasks.length>0 &&
    tasks.every(task=>task.status==='COMPLETED') && !hasReactiveWork
  const missingCheckpoint=Boolean(workspace &&
    ['FAILED','PARTIAL','PAUSED','INTERRUPTED'].includes(workspace.status) && !hasCheckpoint)
  return {hasCheckpoint,hasFailedWork,hasReactiveWork,canResume,canRetry,reviewOnly,missingCheckpoint}
}
