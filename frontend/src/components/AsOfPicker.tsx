export function AsOfPicker({ value, onChange, label='As of' }: { value?: string; onChange: (value: string) => void; label?: string }) {
  return <label className="field"><span>{label}</span><input type="text" placeholder="2026-10-16T14:09:00+05:30" value={value || ''} onChange={e => onChange(e.target.value)} /></label>
}
