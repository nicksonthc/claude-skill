---
name: ui-motion-system
description: Motion and feedback system for a React + Tailwind dashboard, operator console or kiosk — one set of motion tokens and CSS-only utilities (no animation library), skeletons instead of blank or zeroed screens, page-enter and staggered entrances, an arrival flash for rows pushed in live, re-popping counts and tweened counters, gliding progress, confirmation pops, tilt/lift "pick-me" cards with whole-card touch targets, a toast countdown bar, and a reduced-motion mode that keeps every outline. Use when asked to polish the UI/UX, add animations, transitions or micro-interactions, add loading skeletons, make a live dashboard feel alive, highlight new rows from a websocket, make cards touch- or glove-friendly, or audit motion and reduced-motion support.
---

# UI Motion System

Harvested from a production shop-floor app worked on bright-floor kiosks and
touchscreens. Proven on React 19 · Tailwind v4 · shadcn/ui (Radix) ·
tw-animate-css · sonner 2 · next-themes — CSS keyframes plus a few small hooks.

## The idea in one line

**Motion carries information, from one vocabulary.** Alive things *beat*,
arrivals *pulse*, loading *shimmers*, confirmations *pop* — all drawn from one
token set, sparingly, everywhere. A kiosk must never look frozen, and must
never claim something the data doesn't say.

## Moving parts

1. **Tokens + utilities** (`index.css`) — durations (150 hover · 250 fade · 350
   entrance · 600–700 data), one entrance easing, keyframes, and utilities:
   `.anim-rise/.anim-fade/.anim-pop`, `.page-enter`, `.stagger`, `.skeleton`,
   `.row-arrive`, `.card-lift`, `.card-tilt`, slide-over panel in/out; one
   `prefers-reduced-motion` block.
2. **Signature motif** — one shape from the domain (the source drew a cardiac
   trace) as a sweeping SVG stroke, plus its small form, the *beat* dot, on
   whatever is alive right now.
3. **Loading honesty** — a `Skeleton` primitive shaped like the content, and a
   three-state render: `null` → skeleton, `[]` → empty state, data → content.
4. **Entrances** — the page rises on each route change; lists cascade in with
   a capped stagger whose index continues down the page.
5. **Live-data feedback** — `useArrivals` flashes rows that are new since the
   last data; `key={value}` re-pops a changed count; `AnimatedNumber` tweens;
   bars glide; a progress rail fills its connectors and cascades its checks.
6. **Confirmation moments** — a recorded step pops its check; a finished flow
   gets a centered card with the next action focused.
7. **Pick-me cards** — `card-lift` for plain clickables; `card-tilt` + `useTilt`
   (mouse only) for the big choice tiles, with the one real button stretched
   over the whole card.
8. **Toast countdown** — a hairline draining along each toast, timed to the
   toast's duration; a close button big enough for a glove.
9. **Nav indicator** — a bar that scales in beside the active item.

## Workflow

1. **Audit** with the table in REFERENCE §10: per area, what happens today and
   the gap. Prioritise: P0 loading and honesty → P1 feedback on what users do
   all day → P2 polish.
2. **Pick the motif and the metaphor** with the product owner — one shape from
   the domain, one meaning per motion.
3. **Drop in §1** (tokens, utilities, the reduced-motion block, the cursor fix).
4. **P0:** a skeleton for every list and console screen (§3); an honest Live
   badge (see `system-status-popover`); a branded boot screen (§2).
5. **P1:** page-enter and stagger (§4), arrivals, counters, glide, rail (§5),
   confirmation pops (§6).
6. **P2:** pick-me cards (§7), toasts (§8), nav indicator (§9), the login
   entrance (§4), empty states.
7. **Accept:** build + lint; no screen ever shows a blank or zeroed first
   frame; everything stops under reduced motion with outlines intact; light
   and dark both checked; a poll or socket refresh replays no entrance.

## Principles

- **One vocabulary.** Every animation draws from the tokens; nothing ad hoc.
  Decorative motion is the first cut.
- **CSS keyframes, no animation library** — the bundle cost isn't worth it on a
  kiosk. Enter-only: no route-exit animations.
- **Mount-only entrances.** A refresh that re-renders the same keys replays
  nothing; to replay on purpose, change a `key` on one small element.
- **Honest states.** Skeleton while unknown, empty state when known-empty,
  never a placeholder zero; "Live" only while the socket is.
- **Reduced motion is a mode, not an off switch.** Drop movement, keep every
  outline and colour cue — the pointer still gets an answer, in colour.
- **Big flat targets for gloved hands**: the whole card is the target, 44px
  minimum for anything aimed at directly.

## Pitfalls (each already paid for once)

- **Tailwind draws `ring-*` as a box-shadow.** An unlayered `box-shadow` (the
  hover lift, a reduced-motion `box-shadow: none`) erased card outlines —
  under reduced motion the cards went borderless while skeletons kept theirs,
  so the edge flashed on load and vanished with the data. Compose
  `var(--tw-ring-shadow, 0 0 #0000)` back into every such shadow.
- **`.row-arrive` has no fill mode** — `both` would leave the flash's final
  shadow on the card and hide its ring.
- **First load counts as seen** in the arrival diff, or the whole list flashes
  on mount; diff on the business id, not the array index.
- **`.stagger > *` animates direct children only** — when a card is wrapped in
  a link, the `--i` goes on the link. Cap the delay (10 steps × 45ms) or a long
  list takes seconds to appear.
- **Key the page-enter on the pathname**, never the query string — a filter
  change would remount the page and reset its state.
- **Tilt: mouse only** (a tap snaps the card to one angle); write CSS variables
  straight to the element in a rAF, never React state per pointer move; cap
  ±6° (past ~8° it reads as a carousel); `data-tilting` switches a 90ms linear
  tracking curve for a softer settle.
- **Nested buttons are invalid HTML** — stretch the one real button's `::after`
  over the card, and lift secondary controls above it (`relative z-10`) so they
  don't fire the main action.
- **Equal-height card rows**: `items-stretch` on the row and a reserved
  `min-h` for the two-line name, or one expanded card leaves its neighbours
  floating.
- **Tailwind v4's preflight dropped `cursor: pointer` on buttons** — every
  control looked inert until it was restored in the base layer.
- **Sonner has no remaining-time hook** — time the countdown bar from the same
  exported constant as the toast's duration; pause it on toaster hover (sonner
  pauses its timers then); hide it on loading toasts; hang it on the content
  block (sonner owns the toast's pseudo-elements); restyle the close button in
  CSS, because sonner's runtime rules outrank utilities.
- **Toasts must clear the sticky header** — separate desktop and phone offsets,
  or they land on the page's own action buttons.
- **A horizontally scrolling rail inside a dialog needs `min-w-0` on its
  parent**, or it widens the dialog past its edge.

## Extension points a new repo fills in

- **The motif:** the SVG segment builder, its colour, where it appears.
- **Tokens:** durations, easing, the status palette (good / active / attention
  / fault) and the arrival-flash colour.
- **Which lists flash arrivals**, and the id each one diffs on.
- **Card kinds** and their hover-ring colours; the card's main action.
- **Toast duration and offsets** for the app's header heights.
