// Matrix rain: the signature background layer of the "Read the Rain" system (see /DESIGN.md).
// Canvas 2D, fixed grid of cells: light sweeps down columns over glyphs that mutate in place.

export type RainOptions = {
  /** Share of columns that carry a drop: 0.35 for console (ambient), 1 for landing. */
  density?: number
  fps?: number
  /** Cell size in CSS px; one column per cell. */
  cell?: number
  maxDpr?: number
  /** Elements the rain should dim behind (opaque panels, graphs, tables). */
  maskSelector?: string
  /** Per-frame fade toward the void: lower = longer trails. Defaults to 0.045 at full density, 0.075 ambient. */
  fade?: number
  /** Glyph alpha multiplier behind masked regions. */
  maskAlpha?: number
}

const KATAKANA = 'ｦｱｳｴｵｶｷｹｺｻｼｽｾｿﾀﾂﾃﾅﾆﾇﾈﾊﾋﾎﾏﾐﾑﾒﾓﾔﾕﾗﾘﾜ'
const LATIN = '0123456789Z:.=*+-<>|¦"'
const GLYPHS = KATAKANA + LATIN
const KATA_COUNT = KATAKANA.length

const HEAD = '#e8fff0'
const TRAIL = '#00ff41'
const DIM = '#1f9e45'
const VOID_RGB = '3, 8, 6'

type Drop = { y: number; speed: number; active: boolean; lastRow: number }

export const prefersReducedMotion = () =>
  typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

const randomGlyph = () => Math.floor(Math.random() * GLYPHS.length)

export class MatrixRain {
  private ctx: CanvasRenderingContext2D
  private opts: Required<RainOptions>
  private dpr = 1
  private cols = 0
  private rows = 0
  private chars = new Uint8Array(0)
  private drops: Drop[] = []
  private raf = 0
  private last = 0
  private frame = 0
  private surgeUntil = 0
  private masks: DOMRect[] = []
  private running = false
  private resizeObserver?: ResizeObserver
  private onVisibility = () => {
    if (document.hidden) this.pause()
    else if (this.running) this.loop()
  }

  constructor(private canvas: HTMLCanvasElement, options: RainOptions = {}) {
    const ctx = canvas.getContext('2d', { alpha: false })
    if (!ctx) throw new Error('Canvas 2D unavailable')
    this.ctx = ctx
    const density = options.density ?? 0.35
    this.opts = { density, fps: 24, cell: 20, maxDpr: 1.5, maskSelector: '', maskAlpha: 0.15, fade: density >= 0.8 ? 0.045 : 0.075, ...options }
    canvas.setAttribute('aria-hidden', 'true')
    this.resize()
    this.resizeObserver = new ResizeObserver(() => this.resize())
    this.resizeObserver.observe(canvas)
    document.addEventListener('visibilitychange', this.onVisibility)
  }

  /** Start animating, or render one static frame when the viewer prefers reduced motion. */
  start() {
    this.running = true
    if (prefersReducedMotion()) {
      this.renderStatic()
      return
    }
    this.loop()
  }

  stop() {
    this.running = false
    this.pause()
  }

  destroy() {
    this.stop()
    this.resizeObserver?.disconnect()
    document.removeEventListener('visibilitychange', this.onVisibility)
  }

  setDensity(density: number) {
    this.opts.density = Math.max(0, Math.min(1, density))
    this.opts.fade = this.opts.density >= 0.8 ? 0.045 : 0.075
    for (const d of this.drops) d.active = Math.random() < this.opts.density
  }

  /** Briefly speed the rain up, e.g. while a graph query is in flight. */
  surge(ms = 1200) {
    this.surgeUntil = performance.now() + ms
  }

  private pause() {
    cancelAnimationFrame(this.raf)
    this.raf = 0
  }

  private resize() {
    const { cell, maxDpr } = this.opts
    const w = this.canvas.clientWidth || window.innerWidth
    const h = this.canvas.clientHeight || window.innerHeight
    this.dpr = Math.min(window.devicePixelRatio || 1, maxDpr)
    this.canvas.width = Math.round(w * this.dpr)
    this.canvas.height = Math.round(h * this.dpr)
    this.cols = Math.ceil(w / cell)
    this.rows = Math.ceil(h / cell)
    this.chars = new Uint8Array(this.cols * this.rows).map(randomGlyph)
    this.drops = Array.from({ length: this.cols }, () => this.newDrop(true))
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0)
    this.ctx.fillStyle = `rgb(${VOID_RGB})`
    this.ctx.fillRect(0, 0, w, h)
    this.ctx.font = `600 ${cell - 2}px "MS Gothic", "Yu Gothic", "Hiragino Kaku Gothic ProN", "Noto Sans JP", "JetBrains Mono Variable", monospace`
    this.ctx.textBaseline = 'top'
    if (this.running && prefersReducedMotion()) this.renderStatic()
  }

  private newDrop(scatter: boolean): Drop {
    return {
      y: scatter ? -Math.random() * this.rows * 1.2 : -Math.random() * 12,
      speed: 0.25 + Math.random() * 0.75,
      active: Math.random() < this.opts.density,
      lastRow: -1,
    }
  }

  private refreshMasks() {
    if (!this.opts.maskSelector) return
    this.masks = Array.from(document.querySelectorAll(this.opts.maskSelector), el => el.getBoundingClientRect())
  }

  private alphaAt(x: number, y: number) {
    const c = this.opts.cell / 2
    for (const r of this.masks) {
      if (x + c >= r.left && x + c <= r.right && y + c >= r.top && y + c <= r.bottom) return this.opts.maskAlpha
    }
    return 1
  }

  private drawGlyph(col: number, row: number, color: string, alpha: number) {
    const { cell } = this.opts
    const x = col * cell
    const y = row * cell
    const ctx = this.ctx
    const a = alpha * this.alphaAt(x, y)
    ctx.globalAlpha = 1
    ctx.fillStyle = `rgb(${VOID_RGB})`
    ctx.fillRect(x, y, cell, cell)
    if (a <= 0.01) return
    ctx.globalAlpha = a
    ctx.fillStyle = color
    const glyph = this.chars[row * this.cols + col]
    if (glyph < KATA_COUNT) {
      // Mirrored katakana: the film's signature.
      ctx.setTransform(-this.dpr, 0, 0, this.dpr, (x + cell) * this.dpr, y * this.dpr)
      ctx.fillText(GLYPHS[glyph], 1, 1)
      ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0)
    } else {
      ctx.fillText(GLYPHS[glyph], x + 2, y + 1)
    }
    ctx.globalAlpha = 1
  }

  private step(now: number) {
    const ctx = this.ctx
    const w = this.canvas.width / this.dpr
    const h = this.canvas.height / this.dpr
    if (this.frame % 12 === 0) this.refreshMasks()
    this.frame++

    // Trails: fade everything a little toward the void each frame.
    ctx.globalAlpha = 1
    ctx.fillStyle = `rgba(${VOID_RGB}, ${this.opts.fade})`
    ctx.fillRect(0, 0, w, h)

    const speedScale = now < this.surgeUntil ? 2.4 : 1
    for (let c = 0; c < this.cols; c++) {
      const d = this.drops[c]
      if (!d.active) {
        if (Math.random() < 0.002) d.active = Math.random() < this.opts.density
        continue
      }
      d.y += d.speed * speedScale
      const row = Math.floor(d.y)
      if (row !== d.lastRow && row >= 0 && row < this.rows) {
        if (d.lastRow >= 0 && d.lastRow < this.rows) this.drawGlyph(c, d.lastRow, TRAIL, 0.9)
        this.chars[row * this.cols + c] = randomGlyph()
        this.drawGlyph(c, row, HEAD, 1)
        d.lastRow = row
      }
      // Glyphs mutate in place inside the visible trail.
      if (Math.random() < 0.04 && row > 2) {
        const r = row - 1 - Math.floor(Math.random() * Math.min(row, 18))
        if (r >= 0 && r < this.rows) {
          this.chars[r * this.cols + c] = randomGlyph()
          this.drawGlyph(c, r, DIM, 0.55)
        }
      }
      if (row > this.rows + 24) {
        this.drops[c] = this.newDrop(false)
        this.drops[c].active = Math.random() < this.opts.density
      }
    }
  }

  private loop = () => {
    this.raf = requestAnimationFrame(t => {
      if (!this.running || document.hidden) return
      if (t - this.last >= 1000 / this.opts.fps) {
        this.last = t
        this.step(t)
      }
      this.loop()
    })
  }

  private renderStatic() {
    this.pause()
    this.refreshMasks()
    for (let i = 0; i < 90; i++) this.step(0)
    // Settle to a quiet still frame.
    this.ctx.fillStyle = `rgba(${VOID_RGB}, 0.45)`
    this.ctx.fillRect(0, 0, this.canvas.width / this.dpr, this.canvas.height / this.dpr)
  }
}
