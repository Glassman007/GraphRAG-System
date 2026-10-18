// Status is a glyph plus the word, never colour alone (DESIGN.md → Status badges).
const tones: Record<string, [tone: string, glyph: string]> = {}
const assign = (tone: string, glyph: string, words: string) => words.split(' ').forEach(w => { tones[w] = [tone, glyph] })
assign('ok', '●', 'open active ready validated completed succeeded success successful approved pass passed healthy enabled running armed live accepted confirmed')
assign('warn', '▲', 'blocked stale degraded pending warning warn partial needs-review in-progress claimed proposed disabled paused queued draft at-risk')
assign('crit', '■', 'failed failure breached critical error sev-1 rejected invalid invalidated unavailable fail')
assign('done', '○', 'resolved closed archived superseded cancelled canceled done retired already-completed')

export function StatusBadge({ value }: { value?: unknown }) {
  const text = String(value ?? 'UNKNOWN')
  const key = text.toLowerCase().replace(/[^a-z0-9]+/g, '-')
  const [tone, glyph] = tones[key] ?? ['neutral', '◇']
  return <span className={`status status-${key}`} data-tone={tone}><span className="status__glyph" aria-hidden="true">{glyph}</span><span>{text}</span></span>
}
