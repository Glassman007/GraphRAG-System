import { JsonPanel } from './JsonPanel'
export function ProvenancePanel({ value }: { value: unknown }) {
  return <JsonPanel title="Provenance" value={value ?? { note: 'No provenance returned for this object.' }} />
}
