import { useEffect, useRef } from 'react'
import { useIsFetching } from '@tanstack/react-query'
import { MatrixRain } from '../design/rain'

// Everything a viewer reads: the rain dims to 15% behind these (DESIGN.md → Matrix rain).
const MASK = '.panel, .table-wrap, .drawer, .page-header, .rail, .topbar, .summary-grid, .modal, .onboarding, .tabs, .list, .meaning-strip, .funnel, .wizard-steps, .landing-copy, .landing-live, .landing-bar, .landing-paths, .landing-foot'

export const RAIN_KEY = 'graphhacks.rain'
export function readRainPreference() {
  try { return localStorage.getItem(RAIN_KEY) !== 'off' } catch { return true }
}
export function writeRainPreference(on: boolean) {
  try { localStorage.setItem(RAIN_KEY, on ? 'on' : 'off') } catch { /* storage unavailable: preference stays per-session */ }
}

/** Fixed Matrix-rain background. Surges while backend queries are in flight. */
export function RainLayer({ density = 0.35, enabled = true }: { density?: number; enabled?: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const rain = useRef<MatrixRain>()
  const fetching = useIsFetching()

  useEffect(() => {
    if (!ref.current || typeof ResizeObserver === 'undefined') return
    let instance: MatrixRain
    try { instance = new MatrixRain(ref.current, { density, maskSelector: MASK }) } catch { return }
    rain.current = instance
    return () => { instance.destroy(); rain.current = undefined }
  }, [density])

  useEffect(() => {
    if (enabled) rain.current?.start()
    else rain.current?.stop()
  }, [enabled, density])

  useEffect(() => { if (fetching > 0) rain.current?.surge(900) }, [fetching])

  return <canvas ref={ref} className="rain-layer" aria-hidden="true" style={{ visibility: enabled ? 'visible' : 'hidden' }} />
}
