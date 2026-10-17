export function StatusBadge({ value }: { value?: unknown }) {
  const text = String(value ?? 'UNKNOWN')
  return <span className={`status status-${text.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`}>{text}</span>
}
