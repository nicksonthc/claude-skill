# Reusable Prompt — Network Topology Blueprint (HTML) · v1

The prompt this skill grew out of, kept for provenance — see
[../CHANGELOG.md](../CHANGELOG.md) for what it got wrong. Structurally
unchanged; company names, project codes and accent-theme names were
genericised before this repo was published, so the theme names here read
`cobalt` / `moss` rather than the client names v1 shipped with.

Copy the prompt below into a new Claude session. Fill in the `INPUT` block at
the bottom with your topology and Claude will produce a single self-contained
HTML file in the same visual language as the reference render
(`network-topology.html`).

---

## PROMPT

You are designing a **printable engineering-blueprint–style network topology**
as a single self-contained HTML file. The visual reference is an architectural
drawing, not a marketing slide: think Pentagram + Field Notes + factory floor
schematic. No gradients-as-decoration, no glassmorphism, no rounded blobs, no
emoji, no stock icons.

### Deliverable

- One `.html` file. Inline `<style>` and inline `<svg>`. No external JS
  frameworks. Web fonts from Google Fonts only (JetBrains Mono + a serif
  display face such as Tiempos Headline / Fraunces / Source Serif).
- Canvas is a fixed **1920 × 1080** `.blueprint` container, centred in the
  viewport, with `overflow: auto` so it can be scrolled or exported to PDF /
  PNG / screenshotted as-is.
- The page must look intentional at 100 % zoom; do not make it responsive.

### Design language (non-negotiable)

1. **Warm-paper palette.** Off-white parchment base (`#EFE7D2` area), card
   surfaces slightly lighter (`#FBF6E5`), text in warm near-black (`#2A2316`),
   secondary text in warm grey-brown. Two fine grid overlays on the canvas:
   one at 40 px (very faint) and one at 200 px (slightly stronger).
2. **Themeable accent.** Expose CSS variables `--accent`, `--accent-deep`,
   `--accent-soft`, `--accent-bg`, `--accent-border`, `--accent-on` and ship
   **3 accent themes** togglable from a top-centre control:
   - `cobalt` — blue `#2A6DB0` (default, `.active`)
   - `moss` — green `#4F7D2B`
   - `charcoal` — slate `#2E4756`
   Persist the selection to `localStorage` under a sensible key. Plus one
   constant warm secondary (`--warm: #C25D34`) used only for special flows
   (e.g. bootstrap / one-time / out-of-band).
3. **Typography.** Monospace everywhere (JetBrains Mono). All labels,
   tags, IDs and zone names are UPPERCASE with `letter-spacing` between
   `0.18em` and `0.3em`. Body text uses normal case. Title block may use the
   serif display face for the project name.
4. **Frame furniture.** The drawing always includes:
   - Four L-shaped **corner brackets** at the canvas corners (`32 × 32 px`,
     `1.5px` border, ~50% opacity).
   - A **title block** top-left with: a tracking-out crumb
     (`DRAWING · NETWORK TOPOLOGY · <DOMAIN>`), a 2-line project name
     (one segment in `--accent`), and a sub-line of
     `REV X.Y · DRAWING NO <CODE> · YYYY-MM-DD`.
   - A **legend** top-right inside a bordered card listing the line styles
     in use (solid / dashed / warm), each with a 44 px sample stroke.
   - A **footer** bottom edge with `SHEET 1 OF 1 · SCALE 1:1 · NTS` on the
     left, a `stat-block` of counts (`NODES`, `FLOWS`, `ZONES`, `PORTS`) in
     the middle, and `CLASSIFIED · INTERNAL` (or similar) on the right.

### Components (the boxes)

Each node is a `.box` card, absolutely positioned. A card has:

- Four small **L-corner accents** in `--accent` that sit *just outside* the
  card border (`-4px` offset, `11 × 11 px`, `1.5px`).
- A **tag chip** top-left (`-9px` from top, bg `--bg-base` to break the
  border) — e.g. `SERVER · APP HOST`, `CLIENT · OPERATOR`,
  `CLOUD · EXTERNAL`, `EQUIPMENT · SHOP FLOOR`.
- A muted **box ID** top-right with the same break-border treatment —
  e.g. `RHEL-APP-01`, `HMI-01`.
- A bold **name** (18 px, tracked) and a muted **hostname** below it.
- A short **divider** that fades to transparent on the right.
- A **spec list** of `key → val` rows. Keys are fixed-width muted labels
  (`OS`, `ROLE`, `PROTO`, `AUTH`, `URL`, `USER`, `BROWSER`, `TARGET`, …).
  Values may end in a small bordered **pill** for port hints
  (e.g. `→ PG 5432`).
- Where the node hosts sub-components (Docker containers, systemd daemons,
  embedded PLCs, VMs, k8s pods), nest them inside a dashed-border
  `.rh-section` with its own `section-tag` (e.g. `DOCKER ENGINE`,
  `SYSTEMD DAEMON · NATIVE`, `EMBEDDED · PLC CONTROLLER`). Each child is a
  3-column row: name + stack description on the left, a muted
  `container | daemon | pod | controller` chip in the middle, and a
  right-aligned `cport-list` of `:port  TAG` lines. If two children inside
  the same section talk to each other internally, add a centred
  `internal-link` line like `REACT UI → PYTHON API :8080 · internal call`.

### Zones (background bands)

Group the cards into vertical (or L-shaped) **zones** behind everything else:

- Each zone is a faint dashed left+right rule with a tracking-out tag at the
  top edge — `ZONE · EXTERNAL`, `ZONE · SERVER ROOM · ADMIN HOST`,
  `ZONE · SERVER ROOM · APP HOST`, `ZONE · SHOP FLOOR`, etc.
- Zones that aren't a clean rectangle (e.g. a shop floor wrapping around
  multiple cards) must be drawn as a single dashed-stroke SVG path with
  `fill: rgba(60,48,30,0.025)` and `stroke-dasharray: 6 5`.
- Zones live at `z-index: 1`. Connection lines sit at `z-index: 3`. Cards at
  `z-index: 4`. Flow labels at `z-index: 6`.

### Flows (the lines)

All connections are drawn in **one full-canvas SVG layer** (`viewBox=
"0 0 1920 1080"`, `preserveAspectRatio="none"`, `pointer-events: none`).

- Use orthogonal **right-angle paths only** — no curves, no diagonals.
- `stroke-width: 1.5`. Three styles:
  - **solid `--accent`** — production traffic
  - **dashed `--accent`** (`stroke-dasharray: 8 5`) — admin / deployment /
    out-of-band query
  - **solid `--warm`** — bootstrap / one-time / image pulls
- End every path with an arrow marker. Define two markers in `<defs>`:
  `arrow-accent` and `arrow-warm`, both `14 × 14`, `refX=11 refY=7`, filled
  with `var(--accent)` / `var(--warm)`.
- **Route lines around cards, never through them.** When in doubt, prefer
  one extra bend over a shorter line that clips a card.

### Flow labels (the numbered pills)

Every flow gets a small numbered pill placed near its midpoint:

- A bordered card (`bg-card`, accent border) with a 18 × 18 numbered chip
  pinned at `top: -7px; left: -7px` filled with the accent (or `--warm` for
  warm flows).
- Two text lines: a bold accent **protocol/port** line
  (`HTTP / 8082`, `POSTGRES / 5432`, `SSH·SCP / 22`, `TCP/IP / 8081`) and a
  smaller muted **description** line (`→ React UI · MMS`,
  `DBeaver query`, `PLC socket → Python`).
- Number the flows in the same order they appear in the input.

### What to avoid (anti-slop checklist)

- ❌ No emoji, no Font Awesome / Lucide / Heroicons, no decorative icons.
- ❌ No gradients on cards or buttons. The only gradients allowed are the
  faint canvas grid and the divider fade.
- ❌ No rounded corners on cards or buttons. (Pills and corner accents stay
  square. Numbered chips are square, not circular.)
- ❌ No drop-shadows beyond the very soft `0 8px 24px rgba(60,48,30,0.05)`
  the cards use.
- ❌ No animation, no hover micro-interactions other than the theme buttons.
- ❌ No "AI dashboard" tropes: sparkline graphs, fake KPIs, donut charts,
  generic avatar circles.
- ❌ No diagonal connection lines, no Bezier curves between nodes, no
  line-crossings where a re-route would avoid them.

### Process

1. Read the `INPUT` block at the bottom.
2. Sketch a layout: decide column count, which zone each node sits in,
   and the rough x/y of every card. Cards are typically 220–520 px wide
   and 180–460 px tall. Leave ≥ 40 px gutters.
3. Lay down the four corner brackets, title block, theme toggle, legend,
   zone shades, footer.
4. Place the cards with `position: absolute` and explicit `top/left/width
   /height` inside a `.<short-name>` class per card.
5. Draw the SVG lines + arrow markers, then position the flow-label pills
   over them.
6. Update the footer stat-block counts to match what you actually drew.
7. Wire up the theme toggle + `localStorage` persistence with vanilla JS
   (≤ 20 lines, at the bottom of `<body>`).
8. Sanity-check: every node referenced in a flow exists; every flow has a
   numbered label; no line crosses a card; counts in the footer are right.

### Output

Return **only** the final HTML, no commentary, no markdown fence. Save it
next to the source you were given (suggested filename: `<topic>-topology.html`).
Open it in a browser and verify it renders before declaring done.

---

## INPUT

Fill these fields before running the prompt. Leave a field blank only if
you genuinely don't have it; do not invent values.

```
PROJECT NAME      : <e.g. EXAMPLE PLANT MATERIAL MGMT>
PROJECT CODE      : <e.g. DEMO-0001>
DRAWING DOMAIN    : <e.g. MFG / DATA / SECURITY / PLATFORM>
DRAWING NO        : <e.g. NWK-MFG-001>
REVISION          : <e.g. 1.2>
DATE              : <YYYY-MM-DD>
CLASSIFICATION    : <e.g. CLASSIFIED · INTERNAL>

ZONES (left-to-right or grouped):
  - <ZONE NAME> — <one-line purpose>
  - …

NODES (one block per node):
  - id        : <short stable id, e.g. RHEL-APP-01>
    name      : <DISPLAY NAME>
    host      : <hostname or fqdn>
    zone      : <which zone above>
    tag       : <SERVER · APP HOST | CLIENT · OPERATOR | …>
    specs     :
      - <KEY> : <value>            # 3–6 rows
    children  :                    # optional — containers / daemons / pods
      - name  : <CONTAINER NAME>
        kind  : <container | daemon | pod | controller | vm>
        stack : <one-line description>
        ports :
          - <:port>  <TAG>          # e.g. :8080  API · HTTP
      - …
    internal  : <child A → child B :port · description>   # optional

FLOWS (numbered in the order you want them shown):
  - from   : <node id or node.child>
    to     : <node id or node.child>
    style  : <solid | dashed | warm>
    proto  : <e.g. HTTP / 8082>
    desc   : <e.g. → React UI · MMS>

NOTES:
  - <anything else: physical constraints, must-route-around, special
     shapes for zones, etc.>
```
