// Decode: key text resolves out of rain glyphs when backend data arrives (see /DESIGN.md).
// ASCII-only scramble set so the monospace layout never shifts while decoding.

import { prefersReducedMotion } from './rain'

const SCRAMBLE = '01<>/\\|=+*#%@&_-ABCDEFXZ'

export type DecodeOptions = { duration?: number }

/** Decode `text` into `el`. Returns a cancel function that settles the final text immediately. */
export function decode(el: HTMLElement, text = el.textContent ?? '', { duration = 600 }: DecodeOptions = {}) {
  el.setAttribute('aria-label', text)
  if (prefersReducedMotion() || !text) {
    el.textContent = text
    return () => {}
  }
  const chars = [...text]
  // Each character settles at its own moment, sweeping left to right with jitter.
  const settleAt = chars.map((_, i) => (i / Math.max(chars.length, 1)) * duration * 0.75 + Math.random() * duration * 0.25)
  const start = performance.now()
  let raf = 0
  el.classList.add('gh-decoding')

  const finish = () => {
    cancelAnimationFrame(raf)
    el.textContent = text
    el.classList.remove('gh-decoding')
  }

  const tick = (now: number) => {
    const t = now - start
    if (t >= duration) return finish()
    el.textContent = chars
      .map((ch, i) => (ch === ' ' || t >= settleAt[i] ? ch : SCRAMBLE[Math.floor(Math.random() * SCRAMBLE.length)]))
      .join('')
    raf = requestAnimationFrame(tick)
  }
  raf = requestAnimationFrame(tick)
  return finish
}
