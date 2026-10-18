export function taskStatus(detail: any): string {
  return String(detail?.task?.status ?? detail?.status ?? '').toUpperCase()
}

export function canClaimTask(detail: any): boolean {
  const status = taskStatus(detail)
  const readiness = detail?.readiness?.ready ?? detail?.ready
  if (readiness === false) return false
  return !status || ['OPEN', 'READY', 'PENDING'].includes(status)
}

export function canStartTask(detail: any, coordination: any): boolean {
  const status = taskStatus(detail)
  const hasOwner = Boolean(coordination?.owner?.id || coordination?.claimed_by?.id || coordination?.owner_id)
  return hasOwner || ['CLAIMED', 'READY'].includes(status)
}

export function canResumeTask(detail: any, execution: any, coordination: any): boolean {
  const status = taskStatus(detail)
  const hasExecution = Boolean(execution?.id || execution?.execution?.id || coordination?.executions?.length)
  return hasExecution && !['COMPLETED', 'CANCELLED', 'FAILED', 'REJECTED'].includes(status)
}
