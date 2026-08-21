# Reference — Network Topology Blueprint

The complete design language. `examples/network-topology.html` is the
canonical implementation; when this document and that file disagree, the file
wins — and fix this document.

## Deliverable

- One `.html` file. Inline `<style>`, inline `<svg>`. No JS frameworks, no
  build step, no external assets beyond Google Fonts.
- A fixed **1920 x 1080** `.blueprint` container, centred in the viewport,
  `overflow: auto` so it can be scrolled, screenshotted, or exported to
  PDF/PNG as-is.
- Intentional at 100% zoom. **Do not make it responsive.**
- Written to disk with the Write tool. Never paste the HTML into chat, and
  never wrap it in a markdown fence.

## Palette

Warm-paper base, defined once on `:root`:

```css
--bg-base:        #EFE7D2;   /* parchment canvas   */
--bg-card:        #FBF6E5;   /* card surface       */
--bg-card-alt:    #F4ECD3;
--bg-sunken:      #E1D5B5;
--bg-grid-fine:   rgba(90, 70, 45, 0.04);
--bg-grid-major:  rgba(90, 70, 45, 0.07);

--border-base:    rgba(60, 48, 30, 0.22);
--border-strong:  rgba(60, 48, 30, 0.42);
--border-dashed:  rgba(60, 48, 30, 0.30);
--border-faint:   rgba(60, 48, 30, 0.12);

--text-primary:   #2A2316;
--text-secondary: #6A5C46;
--text-muted:     #968866;
--text-soft:      #B6A883;
```

Two grid overlays on the canvas: fine at `40px 40px`, major at
`200px 200px`, both as 1px `linear-gradient` pairs.

Card shadow is the only shadow permitted: `0 8px 24px rgba(60,48,30,0.05)`.

## Accent themes

Six themeable variables — `--accent`, `--accent-deep`, `--accent-soft`,
`--accent-bg`, `--accent-border`, `--accent-on` — plus a constant warm
secondary (`--warm: #C25D34`, `--warm-deep: #9C4824`, `--warm-soft`,
`--warm-border`) used **only** for bootstrap / one-time / out-of-band flows.

Mechanism: `cobalt` values live on bare `:root` (so it is the default with no
attribute set). Each other theme is a `[data-theme="<name>"]` block
overriding the six accent variables. The toggle sets the attribute on the
`.blueprint` root element and persists to `localStorage` under exactly
`netDiagTheme`; on load, read the key back and re-apply `.active` to the
matching swatch button. Wrap both `localStorage` calls in `try/catch` — they
throw in some contexts.

Toggle markup is a top-centre `.theme-toggle` with one
`button[data-theme-set="<name>"]` per theme, each containing a `.swatch`
whose `background` is that theme's accent hex.

## Typography

**JetBrains Mono for everything**, weights 300/400/500/600/700:

```html
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap" rel="stylesheet">
```

```css
font-family: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
```

All labels, tags, IDs and zone names are UPPERCASE with `letter-spacing`
between `0.18em` and `0.3em`. Body text is normal case.

> **No display serif.** Earlier revisions of this prompt asked for "a serif
> display face such as Tiempos Headline". That was wrong twice over: Tiempos
> Headline is a commercial Klim face that Google Fonts does not serve, so the
> request 404'd, and no `font-family` rule ever referenced it. The drawing has
> always been all-mono. If you genuinely want a display face, pick one Google
> actually serves (`Fraunces`, `Instrument Serif`, `Source Serif 4`) and apply
> it to the title block only — but mono-only is the canonical look.

## Layer order (z-index)

| z    | Layer                                     |
| ---- | ----------------------------------------- |
| 1    | `.zone-shade`, `.zone-floor-svg`          |
| 2    | `.zone-floor-label`                       |
| 3    | `.lines` (SVG flow layer)                 |
| 4    | `.box` (cards)                            |
| 5    | `.corner-marker`                          |
| 6    | `.title-block`, `.legend`, `.flow-label`, `.footer` |
| 10   | `.theme-toggle`                           |

## Frame furniture

- **Corner brackets** — four L-shaped `.corner-marker`s at the canvas
  corners, `32 x 32px`, `1.5px` border, ~50% opacity.
- **Title block** (top-left) — a tracking-out crumb
  `DRAWING · NETWORK TOPOLOGY · <DOMAIN>`, a 2-line project name with one
  segment in `--accent`, then a sub-line
  `REV X.Y · DRAWING NO <CODE> · YYYY-MM-DD`.
- **Legend** (top-right) — a bordered card listing only the line styles
  actually used, each with a `44px` sample stroke (`.legend-line`).
- **Footer** (bottom edge) — `SHEET 1 OF 1 · SCALE 1:1 · NTS` left, a
  `stat-block` of `NODES` / `FLOWS` / `ZONES` / `PORTS` centre, and the
  drawing's classification right — `CLASSIFIED · INTERNAL` for internal
  sheets, `EXAMPLE · UNCLASSIFIED` for the bundled reference render. Stamp
  what is true; never carry an internal classification onto a public sheet.

## Cards

Each node is an absolutely-positioned `.box` with:

- Four **L-corner accents** in `--accent`, sitting *just outside* the border
  (`-4px` offset, `11 x 11px`, `1.5px`).
- A **tag chip** top-left at `-9px`, background `--bg-base` to break the
  border — e.g. `SERVER · APP HOST`, `CLIENT · OPERATOR`,
  `CLOUD · EXTERNAL`, `EQUIPMENT · SHOP FLOOR`.
- A muted **box ID** top-right, same border-break treatment — `RHEL-APP-01`,
  `HMI-01`.
- A bold **name** (18px, tracked) and a muted **hostname** beneath.
- A short **divider** fading to transparent rightward.
- A **spec list** of `key → val` rows, 3-6 of them. Keys are fixed-width
  muted labels (`OS`, `ROLE`, `PROTO`, `AUTH`, `URL`, `USER`, `TARGET`).
  Values may end in a small bordered **pill** for port hints (`→ PG 5432`).

Where a node hosts sub-components (containers, daemons, pods, VMs, embedded
PLCs), nest them in a dashed-border `.rh-section` carrying its own
`section-tag` (`DOCKER ENGINE`, `SYSTEMD DAEMON · NATIVE`,
`EMBEDDED · PLC CONTROLLER`). Each child is a 3-column row: name + stack
description left, a muted `container | daemon | pod | controller | vm` chip
centre, a right-aligned `cport-list` of `:port  TAG` lines. If two children
in one section talk to each other, add a centred `internal-link` line —
`REACT UI → PYTHON API :8080 · internal call`.

## Zones

Group cards into vertical or L-shaped bands behind everything else:

- A faint dashed left+right rule with a tracking-out tag at the top edge —
  `ZONE · EXTERNAL`, `ZONE · SERVER ROOM · APP HOST`, `ZONE · SHOP FLOOR`.
- Non-rectangular zones (a shop floor wrapping several cards) are a single
  dashed SVG path, `fill: rgba(60,48,30,0.025)`, `stroke-dasharray: 6 5`.

## Flows

One full-canvas SVG layer: `viewBox="0 0 1920 1080"`,
`preserveAspectRatio="none"`, `pointer-events: none`.

- **Orthogonal right-angle paths only.** No curves, no diagonals.
- `stroke-width: 1.5`. Three styles:
  - solid `--accent` — production traffic
  - dashed `--accent` (`stroke-dasharray: 8 5`) — admin / deployment /
    out-of-band query
  - solid `--warm` — bootstrap / one-time / image pull
- Every path ends in an arrow marker. Define both in `<defs>`:
  `arrow-accent` and `arrow-warm`, each `markerWidth/Height="14"`,
  `refX="11" refY="7"`, `orient="auto"`,
  `markerUnits="userSpaceOnUse"`.
- **Route around cards, never through them.** Prefer one extra bend over a
  shorter line that clips a card.

## Flow labels

One numbered pill near each path midpoint: a bordered `--bg-card` card with
an accent border, and an `18 x 18px` numbered chip pinned at
`top: -7px; left: -7px`, filled with `--accent` (or `--warm` for warm flows).
Chips are square, not circular. Two text lines — a bold accent
protocol/port line (`HTTP / 8082`, `POSTGRES / 5432`, `SSH·SCP / 22`,
`TCP/IP / 8081`) and a smaller muted description (`→ React UI · MMS`,
`DBeaver query`, `PLC socket → Python`). Number flows in input order.

## Anti-slop checklist

- No emoji, no Font Awesome / Lucide / Heroicons, no decorative icons.
- No gradients except the canvas grid and the divider fade.
- No rounded corners anywhere — cards, buttons, pills, chips all square.
- No shadow beyond the one card shadow above.
- No animation or hover effects other than the theme buttons.
- No "AI dashboard" tropes: sparklines, fake KPIs, donut charts, avatars.
- No diagonal connectors, no Beziers, no crossings a re-route would avoid.
- No invented data. A blank field beats a plausible fiction.
- No secrets. Passwords, keys and tokens never belong in a spec row — the
  drawing gets shared, screenshotted and committed. Use `AUTH  ssh ·
  key-based` and keep the secret in a vault.
