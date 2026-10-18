---
name: GraphHacks — Read the Rain
description: An ASCII-grid console lit by green phosphor, where Matrix rain is the unqueried graph and every answer decodes out of it.
colors:
  void: "#030806"
  panel: "#06110A"
  raised: "#0B1C12"
  rule-faint: "#12301F"
  rule: "#267246"
  rule-bright: "#2FA35A"
  text-muted: "#3FBF6F"
  text: "#B8F5C4"
  text-bright: "#E8FFF0"
  signal: "#00FF41"
  signal-deep: "#00C032"
  trace: "#9D93FF"
  trace-line: "#7466FF"
  warn: "#FFB000"
  crit: "#FF5A4D"
typography:
  display:
    fontFamily: "Martian Mono Variable, JetBrains Mono Variable, ui-monospace, monospace"
    fontSize: "clamp(2.75rem, 7.5vw, 6rem)"
    fontWeight: 800
    lineHeight: 0.92
    letterSpacing: "-0.02em"
    fontVariation: "'wdth' 75"
  headline:
    fontFamily: "Martian Mono Variable, JetBrains Mono Variable, ui-monospace, monospace"
    fontSize: "1.75rem"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "0.01em"
    fontVariation: "'wdth' 87.5"
  title:
    fontFamily: "JetBrains Mono Variable, ui-monospace, monospace"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "0.04em"
  body:
    fontFamily: "JetBrains Mono Variable, ui-monospace, monospace"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.4286
  data:
    fontFamily: "JetBrains Mono Variable, ui-monospace, monospace"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.4286
    fontFeature: "'tnum' 1, 'zero' 1"
  label:
    fontFamily: "JetBrains Mono Variable, ui-monospace, monospace"
    fontSize: "0.6875rem"
    fontWeight: 600
    lineHeight: 1.4545
    letterSpacing: "0.14em"
  metric:
    fontFamily: "Martian Mono Variable, JetBrains Mono Variable, ui-monospace, monospace"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1
    fontFeature: "'tnum' 1, 'zero' 1"
    fontVariation: "'wdth' 87.5"
rounded:
  none: "0px"
spacing:
  hair: "4px"
  xs: "8px"
  sm: "12px"
  md: "20px"
  lg: "40px"
  xl: "80px"
components:
  button-primary:
    backgroundColor: "{colors.signal}"
    textColor: "{colors.void}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "8px 20px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.text-bright}"
    textColor: "{colors.void}"
  button-secondary:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "8px 20px"
    height: "40px"
  button-secondary-hover:
    backgroundColor: "{colors.text}"
    textColor: "{colors.void}"
  button-governed:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.warn}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "8px 20px"
    height: "40px"
  input:
    backgroundColor: "{colors.void}"
    textColor: "{colors.text-bright}"
    typography: "{typography.data}"
    rounded: "{rounded.none}"
    padding: "8px 12px"
    height: "40px"
  panel:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.none}"
    padding: "20px"
  tab-active:
    backgroundColor: "{colors.signal}"
    textColor: "{colors.void}"
    typography: "{typography.label}"
    padding: "4px 12px"
  tab:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text-muted}"
    typography: "{typography.label}"
    padding: "4px 12px"
  status-badge:
    backgroundColor: "{colors.void}"
    textColor: "{colors.text}"
    typography: "{typography.label}"
    padding: "0px 8px"
    height: "20px"
---

# Design System: GraphHacks — Read the Rain

## Overview

**Creative North Star: "Read the Rain."** The Matrix rain stands for the company graph at rest: every fact still unread, falling past as noise. Asking a question pulls characters out of the rain and *decodes* them into answers on a strict character grid. The ASCII world gives the order (cells, ruled panels, bracketed controls, status lines); the Matrix world gives the light (phosphor greens, glow, the rain itself). FalkorDB's violet is the only non-green signal color, and it means one thing: **this is the path the graph actually traversed.**

**The scene:** judges watch a screen-shared demo, often projected or compressed into a video, and on-call operators read the console in dark rooms late at night. Dark phosphor on near-black is chosen for that light, not for the "hacker" category.

**Two registers, one world:**
- **Console (Operate):** the working screens. The world contributes only four things: type, palette, density and the signature move (Decode + Trace). Navigation, tabs, tables, inputs and buttons stay standard web controls; they are restyled, never turned into a fake terminal.
- **Landing (Persuade):** the demo's opening surface. Rain runs at full intensity, the display face plays big, and the first viewport shows a real graph answer decoding out of the rain.

**Signature move: Decode → Trace.** When backend data arrives, its key text decodes out of rain glyphs (about 600 ms, per character, staggered). When a result comes with a graph path (retrieval scope, blast radius, decision genealogy, provenance), that path lights up in violet and a slow pulse runs along the real traversed edges. The motion is honest: it shows only what the backend returned.

## Colors

The strategy is **Committed monochrome plus one meaning-bearing accent.** Green phosphor carries the whole surface in tonal steps, and violet appears only where the graph proved something. Amber and red are status colors only.

### Primary
- **Signal** `#00FF41`: Matrix green. Primary actions, the active nav row, the active tab, the live-status dot and the rain's bright heads. Use it as a **fill under void text** or as glow; never as body text.
- **Signal deep** `#00C032`: the pressed state of signal fills, and Cytoscape's default node ring.

### Secondary
- **Trace** `#9D93FF` (text, labels) / **Trace line** `#7466FF` (edges, rules). FalkorDB's violet. Used **only** for traversal paths, retrieval scope, provenance links and the Cypher or query that produced an answer. When something is violet, the graph proved it.

### Neutral (the phosphor ramp)
| Token | Hex | Role | Contrast on panel |
|---|---|---|---|
| void | `#030806` | page ground, input wells | — |
| panel | `#06110A` | panels, drawers, nav | — |
| raised | `#0B1C12` | hover rows, open menus, selected tab strip | — |
| rule-faint | `#12301F` | dividers inside panels, table row rules | decorative |
| rule | `#267246` | panel edges, input borders | 3.3:1 (non-text UI, WCAG 1.4.11) |
| rule-bright | `#2FA35A` | focus edges, active panel edge | — |
| text-muted | `#3FBF6F` | secondary text, labels, axis ticks | ≈8:1 |
| text | `#B8F5C4` | body and data text | ≈15:1 |
| text-bright | `#E8FFF0` | headings, key values, rain head | ≈18:1 |

### Status
- **Warn** `#FFB000` (P3 amber phosphor): degraded state, blocked tasks, and governed or consequential actions.
- **Crit** `#FF5A4D`: critical severity and errors. Use it only for text, a 1px edge or a glyph, never as a large fill.
- Status is **never conveyed by color alone**; it always has a glyph and a word (see Status badges).

### Named Rules
- **The Violet Rule:** violet means "traversed by the graph." It is never decoration and never a hover color.
- **The No-Neon-Body Rule:** `#00FF41` never sets running text; body text is `text` (`#B8F5C4`).
- **The Status-Is-Bracketed Rule:** status always reads as a glyph plus a word, e.g. `▲ BLOCKED`, `■ SEV-1`, `● OPEN`.

## Typography

Two self-hosted variable faces, both OFL: **Martian Mono Variable** (display, headline and metric roles, using the width axis 75–112.5) and **JetBrains Mono Variable** (everything else). Mono here is the world's material, because every value sits on the character grid; it is not a "technical" costume.

### Hierarchy
- **Display** (Martian 800, `wdth 75`, up to 6rem, line-height 0.92, uppercase): landing headlines and the console's page-title strip at large widths. Its condensed width echoes the rain's columns.
- **Headline** (Martian 700, `wdth 87.5`, 1.75rem, uppercase): page titles in the console.
- **Title** (JetBrains 600, 1rem, +0.04em): panel titles, drawer titles.
- **Body** (JetBrains 400, 14/20px): prose and descriptions; keep the measure at 72ch or less.
- **Data** (JetBrains 500, 14/20px, `tnum` + slashed `zero`): IDs, numbers, table cells, timestamps.
- **Label** (JetBrains 600, 11/16px, uppercase, +0.14em): column headers, field labels, tab labels and status badges.
- **Metric** (Martian 600, `wdth 87.5`, 1.5rem, tabular): measurement readouts.

### Named Rules
- **The Grid Rule:** the vertical rhythm is the 20px line (`1lh` of body text); horizontal measures use `ch`.
- **The No-Eyebrow Rule:** no kicker or eyebrow line above a heading. A heading speaks for itself, and panel titles are labels, not kickers.
- **The Real-Label Rule:** katakana and rain glyphs are texture only and never label anything.

## Layout

- **The character grid:** the base cell is `1ch × 20px` of 14px JetBrains Mono. Spacing tokens are 4 / 8 / 12 / 20 / 40 / 80px, and vertical stacks use 20px multiples.
- **Console shell:**
  - A **status bar** across the top: wordmark, tenant and principal, backend readiness, the `as_of` clock and the rain toggle.
  - A **left rail** of the 9 primary sections: `▸` marks the active row, which is a full-width signal-filled bar.
  - A **work area** of ruled panels on a 12-column grid with 20px gutters.
  - Drawers slide from the right.
- **Density:** operators read a lot at once, so default to dense data (row height 32px, 20px panel padding). Separate groups with space and a `rule-faint` rule, never with nested cards.
- **Landing:** a full-bleed first viewport. On the left is the display headline plus one sentence and two actions; on the right is a live graph panel that decodes a real answer out of the rain. Below that sits a ruled band of real capability facts, then the console's surfaces as a path into the app.
- **Breakpoints:** 640 / 960 / 1280 / 1600. Below 960 the rail collapses to a top menu button and panels stack. Tables scroll inside their own panel, never the page.
- **The rain layer:** it is fixed behind everything. Panels are opaque (`panel`) so data never sits on moving glyphs, and the rain shows only in the gutters, the margins and empty states.

## Elevation & Depth

The system is **flat and tonal**. Depth is `void → panel → raised`. There are no drop shadows: phosphor emits light, it does not cast shadows.

- **Glow is emission, not elevation.** `text-shadow: 0 0 2px rgb(0 255 65 / .55), 0 0 10px rgb(0 255 65 / .25)` goes only on the display headline, the active nav row, the focused control and rain heads, and never on body or table text.
- **Scanlines and vignette:** for the landing hero only, at very low opacity (≤0.08), and never over data.

## Shapes

- **Radius 0 everywhere.** It is a character grid.
- **Panels:**
  - a 1px `rule` CSS border;
  - an **ASCII corner tick** in each corner (`┌ ┐ └ ┘`, drawn as pseudo-elements in `rule-bright`);
  - a title seated in the top edge, `┤ TITLE ├`, with the title in Label type.
- **Glyph policy:**
  - Structural lines (panel edges, dividers, meters, progress) are **drawn in CSS** so they never misalign.
  - Box-drawing and block characters (U+2500–259F) are used only as short marks: corners, tree branches `├─ └─`, and status glyphs.
  - Neither bundled font carries that range, so they render from the `GH Glyph` fallback face (Cascadia Mono / Consolas / Menlo / DejaVu Sans Mono), where small width differences are harmless.
- **Brackets as form language:** `[ ]` frames status badges and tabs, and `>` prefixes input prompts. Pictograms come from **one SVG icon set** (Lucide, 1.5px stroke, square caps, 16px), never from emoji or Unicode pictographs.

## Components

### Buttons
- **Primary:** a solid `signal` fill, `void` label text, uppercase Label type and a 40px height. On hover the fill goes to `text-bright`; when pressed it goes to `signal-deep`. It has no radius and no shadow.
- **Secondary:** a 1px `rule` edge with `text` label. On hover it inverts, so the fill becomes `text` and the label becomes `void`.
- **Governed** (claim, invalidate, propose or execute an action): a 1px `warn` edge, a `warn` label and a `!` prefix glyph. It always opens the confirmation dialog first.
- **Disabled:** a dashed `rule-faint` edge, `text-muted` at 45%, and `cursor: not-allowed`. A disabled control stays visible and keeps its label (the permission-aware UI depends on it).
- **Focus:** a 1px `rule-bright` outline offset 2px, plus a signal glow.

### Status badges
They are bracketed and uppercase: a glyph, then the word, then the value, e.g. `[● OPEN]`, `[▲ BLOCKED]`, `[■ SEV-1]`, `[◆ TRACED]`.
- green `●` means ok / open / active;
- amber `▲` means blocked / warn / degraded;
- red `■` means critical / failed;
- violet `◆` means traced or graph-proven;
- hollow `○` means closed / resolved.

### Panels
`panel` fill with a 1px `rule` edge, corner ticks and an inset title. A panel never nests inside another panel; use a `rule-faint` divider inside it instead.

### Tables
- **Header row:** Label type in `text-muted`, with a 1px `rule` underline.
- **Rows:** 32px tall, Data type, separated by `rule-faint`.
- **Hover:** the row turns `raised` and a `▸` marker appears in the leading cell.
- **Selected row:** a `raised` fill plus a `signal` marker.
- **Sorting:** sortable headers show `↑` / `↓`.
- **Empty state:** a single centered line in `text-muted`. The rain shows through only in the panel's empty area.

### Inputs / Fields
- A `void` well with a 1px `rule` edge, a `signal` caret and `text-bright` values.
- Focus: the edge turns `rule-bright` with a faint glow.
- The label sits above the field in Label type.
- Search and query inputs get a `>` prompt glyph.
- Errors: a `crit` edge, plus a message below that names the problem and the fix.

### Navigation
- **Rail item:** Label type; `▸` plus a signal fill bar when active.
- **Top status bar:** monospace status fields separated by `│`, plus a live dot for backend readiness.
- **Tabs:** bracketed. The active tab has a `signal` fill and the rest stay `text-muted`.

### Graph view (Cytoscape)
- **Canvas:** the `void` ground. A faint 20px dot grid is allowed.
- **Nodes:** 14–18px. Shape encodes type: ellipse for an entity, round-rectangle for a system, diamond for a decision, hexagon for a claim, tag for evidence. The fill is `panel` with a 1px `signal-deep` ring. The label is Data type at 10px in `text` on a `void` label background at 85% opacity.
- **Edges:** 1px `rule`. Inferred relationships are dashed and explicit ones solid. Arrowheads are `vee` in `rule-bright`.
- **Selection:** the node turns `text-bright` with a `signal` ring and underlay glow. Non-neighbors dim to 20%, and neighbor edges turn `rule-bright`.
- **Trace:** the edges and nodes the backend returned as a path render in `trace-line` / `trace`, with an animated dash flow at 24fps on those edges only. Idle edges never move.

### Matrix rain (signature layer)
- **Rendering:** Canvas 2D on one fixed full-viewport layer at `z-index: -1`, marked `aria-hidden` and with `pointer-events: none`.
- **Glyphs:** mirrored half-width katakana plus digits and a few symbols. The trail fades through the phosphor ramp and the head is `text-bright`. Columns run at varied speeds, and glyphs mutate in place.
- **Budget:**
  - 24fps;
  - device pixel ratio capped at 1.5;
  - 1 column per 18px;
  - density 0.35 in the console (ambient) and 1.0 on the landing;
  - paused while the tab is hidden.
- **Yielding:** the rain dims to 15% behind registered content regions: every panel, table and graph, and every block of readable text (headings, prose, hero copy). Text never sits on full-intensity rain. It speeds up briefly while queries are loading, and fills empty states.
- **Reduced motion:** a single static frame at low opacity. The status bar's `[RAIN ON]` toggle persists the choice per viewer.

### Decode
- Key text (IDs, titles, metric values) decodes on arrival: each character cycles through rain glyphs and then settles, staggered left to right, for ≤600 ms in total.
- `aria-label` always carries the final text.
- With reduced motion the text simply appears.

## Do's and Don'ts

### Do:
- **Do** let every answer show where it came from: violet trace, evidence and source.
- **Do** keep the controls standard (`button`, `input`, `select`, `table`, `tab` roles) and restyle them in this vocabulary.
- **Do** keep the rain behind opaque panels on working screens; let it play in margins, empty states and the landing.
- **Do** pair every status color with a glyph and a word.
- **Do** theme the browser's own surfaces: text selection (signal on void), the caret, scrollbars (`rule` thumb on `void`), focus rings and tabular numerals.

### Don't:
- **Don't** fake a terminal: no command prompt standing in for navigation, no function-key bar, no typewriter "hacking" text and no fake hex dumps.
- **Don't** use violet for anything the graph did not traverse.
- **Don't** set body text in `#00FF41`, and don't put glow on small or table text.
- **Don't** use rounded corners, drop shadows, gradient text, glassmorphism or a colored side border thicker than 1px.
- **Don't** use emoji or Unicode pictographs as icons; status glyphs inside text are fine.
- **Don't** flash: no element may flash more than 3 times per second, and there is no full-screen flicker.
- **Don't** animate data the backend did not return, and don't recompute graph reasoning to make a visual.
