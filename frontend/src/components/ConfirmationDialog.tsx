import type { ReactNode } from 'react'
export function ConfirmationDialog({ open, title, children, onConfirm, onCancel, confirmLabel='Confirm' }: { open: boolean; title: string; children?: ReactNode; onConfirm: () => void; onCancel: () => void; confirmLabel?: string }) {
  if (!open) return null
  return <div className="modal-backdrop" role="presentation"><div className="modal" role="dialog" aria-modal="true" aria-label={title}><h3>{title}</h3>{children}<div className="toolbar"><button type="button" onClick={onCancel}>Cancel</button><button type="button" className="danger" onClick={onConfirm}>{confirmLabel}</button></div></div></div>
}
