export function JsonPanel({ value, title }: { value: unknown; title?: string }) {
  return <section className="panel json-panel">{title && <h3>{title}</h3>}<pre>{JSON.stringify(value, null, 2)}</pre></section>
}
