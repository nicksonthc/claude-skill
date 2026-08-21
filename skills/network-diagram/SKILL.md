---
name: network-diagram
description: Render a printable engineering-blueprint network topology diagram as a single self-contained HTML file (1920x1080, warm-paper palette, orthogonal flows, themeable accent). Use when the user asks for a network diagram, network topology, infrastructure or architecture drawing, logical network design, rack/zone layout, or a "blueprint"-style systems diagram — or mentions network-diagram, topology.html, or wants an existing network diagram revised.
---

# Network Topology Blueprint

Produces one self-contained HTML file: a fixed 1920x1080 engineering drawing
in a warm-paper palette. The visual reference is an architectural blueprint,
not a marketing slide. Full spec in [REFERENCE.md](REFERENCE.md).

## Quick start

1. **Collect the topology.** Fill in [INPUT-TEMPLATE.md](INPUT-TEMPLATE.md)
   from what the user gave you. Never invent hostnames, ports, IPs or
   revision numbers — leave a field blank and ask instead.
2. **Read the spec.** [REFERENCE.md](REFERENCE.md) is non-negotiable on
   palette, typography, frame furniture, card anatomy, zones and flows.
3. **Study the reference render.** `examples/network-topology.html` is the
   canonical output. Match its structure; copy its CSS block verbatim as a
   starting point rather than reinventing the design tokens.
4. **Write the file** to `<topic>-topology.html` next to the user's source
   material (or `docs/` if the repo has one). Use the Write tool — do not
   paste HTML into chat.
5. **Verify** before declaring done (see Verification below).

## Workflow

- [ ] INPUT block filled; blanks confirmed with the user, not guessed
- [ ] Layout sketched: column count, zone per node, rough x/y per card.
      Cards 220-520px wide, 180-460px tall, >=40px gutters
- [ ] Frame laid down: 4 corner brackets, title block, theme toggle,
      legend, zone shades, footer
- [ ] Cards placed `position: absolute` with explicit top/left/width/height,
      one class per card
- [ ] SVG flow layer drawn: orthogonal paths only, both arrow markers defined
- [ ] Numbered flow-label pills positioned near each path midpoint
- [ ] Footer stat-block counts updated to match what was actually drawn
- [ ] Theme toggle + `localStorage` persistence wired (<=20 lines vanilla JS)
- [ ] Verified

## Verification

Do all four. A diagram that renders but lies about its own counts is a
failure.

1. **Referential integrity** — every node named in a flow exists; every
   flow has exactly one numbered label; numbering is contiguous from 1.
2. **Footer counts** — `NODES` / `FLOWS` / `ZONES` / `PORTS` match the
   actual DOM, not the input block.
3. **No clipping** — no connection line crosses a card. Re-route with an
   extra bend rather than shortening.
4. **Render it** — open in a browser and look at it. The `agent-browser`
   skill can screenshot at 1920x1080; confirm no overlap, no overflow
   scrollbars on `.blueprint`, and that all three themes still read well.

## Accent themes

Three ship by default, toggled top-centre and persisted to `localStorage`
under the key `netDiagTheme`:

| Theme      | Accent    | Use for                       |
| ---------- | --------- | ----------------------------- |
| `cobalt`   | `#2A6DB0` | default (`.active` on load)   |
| `moss`     | `#4F7D2B` | green-branded drawings        |
| `charcoal` | `#2E4756` | neutral / vendor-agnostic     |

`--warm` (`#C25D34`) is constant across all three and is reserved for
bootstrap / one-time / out-of-band flows.

To add a client theme, add one `[data-theme="<name>"]` block overriding the
six `--accent*` variables, plus one swatch button. Do not touch `--warm`.

Never put a password, key, token or live credential in a card spec row, and
prefer documentation IPs (`192.0.2.0/24`, `198.51.100.0/24`) over real
addresses in anything that leaves the originating repo.

## Anti-slop rules

No emoji. No icon fonts. No gradients except the canvas grid and the divider
fade. No rounded corners. No animation beyond the theme buttons. No diagonal
or Bezier connectors. No fake KPIs, sparklines, donut charts or avatar
circles. Typography is JetBrains Mono throughout — see REFERENCE.md before
reaching for a display face.
