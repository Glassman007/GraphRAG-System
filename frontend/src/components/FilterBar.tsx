import type { ReactNode } from 'react'

export function FilterBar({ children, label = 'Filters' }: { children: ReactNode; label?: string }) {
  return <section className="panel filter-bar" aria-label={label}><strong>{label}</strong><div className="filter-row">{children}</div></section>
}
