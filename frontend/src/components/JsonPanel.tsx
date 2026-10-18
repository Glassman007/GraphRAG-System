import { TechnicalDetails } from './TechnicalDetails'
export function JsonPanel({ value, title }: { value: unknown; title?: string }) {
  return <section className="panel json-panel"><TechnicalDetails title={title ? `${title} — technical details` : 'Technical details'}><pre>{JSON.stringify(value, null, 2)}</pre></TechnicalDetails></section>
}
