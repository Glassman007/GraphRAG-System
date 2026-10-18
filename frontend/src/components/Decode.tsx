import { useLayoutEffect, useRef } from 'react'
import { decode } from '../design/decode'

/**
 * Text that decodes out of rain glyphs (DESIGN.md → Decode). React renders no children here:
 * the effect owns the node's text, and aria-label always carries the final string.
 */
export function Decode({ text, className, delay = 0, duration = 650 }: { text: string; className?: string; delay?: number; duration?: number }) {
  const ref = useRef<HTMLSpanElement>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.textContent = text
    let cancel = () => {}
    const timer = window.setTimeout(() => { cancel = decode(el, text, { duration }) }, delay)
    return () => { window.clearTimeout(timer); cancel() }
  }, [text, delay, duration])
  return <span ref={ref} className={className} role="text" aria-label={text} />
}
