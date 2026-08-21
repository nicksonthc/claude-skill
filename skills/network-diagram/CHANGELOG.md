# Changelog

## v3 — sanitised for public release

The skill was developed against a real customer drawing, and the reference
render carried that drawing's data. Everything identifying was replaced before
this repo went public. Geometry, CSS structure and the design language are
untouched — only strings changed.

- **Removed a live credential.** The reference render's app-host card carried
  `USER` and `PASSWORD` spec rows holding a real account and password. The
  rows were deleted rather than refilled with plausible fakes: a canonical
  example showing a `PASSWORD` row teaches the anti-pattern, and every
  generated drawing would have copied it. Replaced with
  `AUTH  ssh · key-based`. SKILL.md, REFERENCE.md and INPUT-TEMPLATE.md each
  gained an explicit no-secrets rule so the shape cannot come back.
- **Removed real addressing.** Two internal RFC 1918 addresses and their
  hostnames became RFC 5737 documentation addresses (`192.0.2.10 ·
  win-admin-01`, `198.51.100.20 · rhel-app-01`).
- **Removed client identities.** The two external cloud nodes, the project
  name and the project code were all a real customer's. They are now a
  fictional vendor (`ACME CLOUD`, `ACME ERP`) on a fictional project
  (`EXAMPLE PLANT · MATERIAL MGMT · DEMO-0001`). The vendor's internal ERP
  system name went with them.
- **Renamed the accent themes.** The default and secondary themes were named
  after two companies, and their hexes were those companies' brand colours.
  They are now `cobalt` (`#2A6DB0`) and `moss` (`#4F7D2B`); `charcoal` is
  unchanged. Client themes are still a one-block addition — see SKILL.md.
- **Restamped the footer.** The reference render said `CLASSIFIED · INTERNAL`;
  a public example sheet now says `EXAMPLE · UNCLASSIFIED`. REFERENCE.md keeps
  the classification field but says to stamp what is actually true.

`examples/original-prompt.v1.md` got the same treatment, so it is no longer
byte-identical to the v1 it archives — structurally unchanged, identifiers
genericised. The note at its head says so.

## v2 — converted from prompt to skill

`examples/original-prompt.v1.md` is preserved as the starting point —
structurally verbatim, with identifiers genericised in v3. Every change below
was verified against the reference render
(`examples/network-topology.html`), not guessed.

### Corrected — the prompt was wrong

**Dead display font.** v1 asked for "a serif display face such as Tiempos
Headline / Fraunces / Source Serif" and said the title block "may use the
serif display face". Two problems: Tiempos Headline is a commercial Klim Type
Foundry face that Google Fonts does not serve, so the render's
`?family=…&family=Tiempos+Headline` request could never resolve; and grepping
the render found the string exactly once — in the `<link>` tag. No
`font-family` rule ever referenced it. The only declared family is
`'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace`. The
drawing has always been all-mono. REFERENCE.md now says so and explains why,
and the dead `&family=Tiempos+Headline` was removed from the example's font
URL — a change that alters zero pixels.

**Unspecified `localStorage` key.** v1 said "persist the selection to
localStorage under a sensible key", which guarantees a different key on every
regeneration. Pinned to the key the render actually uses: `netDiagTheme`.

**Vague theme mechanism.** v1 described the themes and their hexes but not how
they attach, mentioning only a `.active` class. The render uses
`[data-theme="<name>"]` blocks overriding the six `--accent*` variables, with
the default theme on bare `:root` as the no-attribute case, and swatch buttons
keyed `button[data-theme-set="<name>"]`. Documented, including the `try/catch`
the render wraps its storage calls in.

**Incomplete z-index ladder.** v1 listed four layers (zones 1, lines 3, cards
4, labels 6) and omitted three that exist. Full ladder now documented: zone
shade/floor-svg 1, zone-floor-label 2, lines 3, cards 4, corner-marker 5,
title-block/legend/flow-label/footer 6, theme-toggle 10.

### Changed — wrong contract for an agent

**Output.** v1 ended "Return **only** the final HTML, no commentary, no
markdown fence" — correct for pasting into a chat window, wrong inside a
skill. The skill now writes the file with the Write tool and explicitly
forbids pasting HTML into chat.

**Verification.** v1 said "Open it in a browser and verify it renders before
declaring done" — untestable by an agent as written. Replaced with four
concrete checks: referential integrity of flow endpoints, footer stat-block
counts matching the DOM rather than the input, no line/card clipping, and an
actual 1920x1080 screenshot via the `agent-browser` skill across all three
themes.

**Invented data.** v1's input block said "do not invent values" once, in
passing. Promoted to a rule in three places, because a blueprint that quietly
fabricates a hostname or port is worse than one with a blank field.

### Verified unchanged

Spot-checked against the render and correct as written in v1: `1920 x 1080`
canvas; `40px` / `200px` grid overlays; palette hexes (`#EFE7D2`, `#FBF6E5`,
`#2A2316`); `--warm: #C25D34`; card shadow
`0 8px 24px rgba(60,48,30,0.05)`; zone fill `rgba(60,48,30,0.025)` with
`stroke-dasharray: 6 5`; flow dasharray `8 5`; `stroke-width: 1.5`; SVG
`viewBox="0 0 1920 1080"` with `preserveAspectRatio="none"`; both arrow
markers at `14 x 14`, `refX="11" refY="7"`; corner brackets `32 x 32px`;
card L-accents `11 x 11px` at `-4px`; tag chip at `-9px`; card name `18px`;
numbered chip `18 x 18px` at `top/left: -7px`; legend sample stroke `44px`;
footer `SHEET 1 OF 1 · SCALE 1:1 · NTS`. (The accent hexes were also correct
as written in v1, but v3 replaced them — see above.)

### Not done

- No validation script yet. The four verification checks are manual; the
  footer-count and flow-endpoint checks are deterministic and worth a
  `scripts/validate.py` if this gets used often. A secret scan belongs in the
  same script — the v3 cleanup was done by hand, and a pre-commit hook is the
  durable fix.
