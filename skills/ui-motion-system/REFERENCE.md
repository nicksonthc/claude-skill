# ui-motion-system — building blocks

Genericized from the source project. `@/` is a Vite alias to `src/`; `Card`,
`Skeleton` and the Toaster wrap shadcn/ui; `cn` is shadcn's class merger.
Sections are numbered to match SKILL.md's "Moving parts". Colours are the
source's (emerald = good/alive, sky = active, amber = attention, rose =
fault) — swap them for the target palette.

---

## 1. Tokens, keyframes, utilities, reduced motion — `index.css`

Everything else in this file draws from these. Add them below the Tailwind
imports; they are deliberately unlayered (see the ring pitfall in the
comments).

```css
/* ------------------------------------------------------------------ */
/* Motion system — one vocabulary for the whole app.                  */
/* Alive things beat, arrivals pulse, loading shimmers.               */
/* ------------------------------------------------------------------ */
:root {
  --ease-out-swift: cubic-bezier(0.16, 1, 0.3, 1); /* entrances */
  --dur-fast: 150ms;  /* hover */
  --dur-base: 250ms;  /* fades */
  --dur-enter: 350ms; /* entrances */
  /* data (bars, counters): 600–700ms, set where used */
}

@keyframes rise-in      { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes fade-in-soft { from { opacity: 0; } to { opacity: 1; } }
@keyframes pop-in {
  0%   { opacity: 0; transform: scale(0.5); }
  60%  { opacity: 1; transform: scale(1.08); }
  100% { opacity: 1; transform: scale(1); }
}
@keyframes panel-in-right  { from { transform: translateX(100%); } to { transform: none; } }
@keyframes panel-out-right { from { transform: none; } to { transform: translateX(100%); } }
@keyframes shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }
/* The arrival blip: a ring dissipates around a new row. */
@keyframes arrive-flash {
  0%   { box-shadow: 0 0 0 0 rgb(16 185 129 / 0.55); }
  100% { box-shadow: 0 0 0 14px rgb(16 185 129 / 0); }
}
@keyframes motif-beat {
  0%, 100% { opacity: 0.55; transform: scale(1); }
  50%      { opacity: 1; transform: scale(1.35); }
}

.anim-rise  { animation: rise-in var(--dur-enter) var(--ease-out-swift) both; }
.anim-fade  { animation: fade-in-soft var(--dur-base) ease-out both; }
.anim-pop   { animation: pop-in 400ms var(--ease-out-swift) both; }
.page-enter { animation: rise-in 400ms var(--ease-out-swift) both; }
/* No fill mode: box-shadow must return to the card's own ring afterwards. */
.row-arrive { animation: arrive-flash 1.2s ease-out; }
/* "Alive": live chips, the active node, a processing order. */
.motif-beat { animation: motif-beat 1.4s ease-in-out infinite; transform-origin: center; }

/* Children cascade in; set `--i` inline per child (see stagger() helper).
   Capped at 10 steps so a long list doesn't take seconds to appear. */
.stagger > * {
  animation: rise-in var(--dur-enter) var(--ease-out-swift) both;
  animation-delay: calc(min(var(--i, 0), 10) * 45ms);
}

.skeleton {
  background: linear-gradient(
    90deg,
    var(--muted) 25%,
    color-mix(in oklab, var(--muted), var(--foreground) 8%) 50%,
    var(--muted) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.8s linear infinite;
}

/* Clickable cards lift on hover, settle on press. */
.card-lift {
  transition:
    transform var(--dur-fast) ease-out,
    box-shadow var(--dur-fast) ease-out,
    border-color var(--dur-fast) ease-out;
}
.card-lift:hover {
  transform: translateY(-2px);
  /* Re-state the ring alongside the lift shadow. This rule is unlayered, so it
     outranks Tailwind's `ring-*` utilities and its `box-shadow` replaces theirs
     outright — which silently erased every lifting card's outline at exactly
     the moment the pointer was on it. Composing the ring var back in keeps the
     edge (including a `hover:ring-*` colour) through the lift. */
  box-shadow:
    0 8px 24px -12px rgb(0 0 0 / 0.28),
    var(--tw-ring-shadow, 0 0 #0000);
}
.card-lift:active { transform: translateY(0); }

/* Cards that tilt under the pointer like a physical card. Angles and sheen
   position come in as custom properties from `useTilt`; this rule only decides
   how they look. Needs `position: relative` on the element (for the sheen) and
   clipping (for its rounded edge) — shadcn's Card gives both. */
.card-tilt {
  transform: perspective(900px) rotateX(var(--tilt-x, 0deg)) rotateY(var(--tilt-y, 0deg));
  transition:
    transform var(--dur-base) var(--ease-out-swift),
    box-shadow var(--dur-fast) ease-out;
}
/* Tracking has to feel welded to the pointer; the softer curve above is for
   the settle back to flat once the pointer leaves. */
.card-tilt[data-tilting] {
  transition:
    transform 90ms linear,
    box-shadow var(--dur-fast) ease-out;
}
.card-tilt:hover {
  /* Ring composed back in — a bare box-shadow here would erase the outline. */
  box-shadow:
    0 16px 32px -18px rgb(0 0 0 / 0.45),
    var(--tw-ring-shadow, 0 0 #0000);
}
/* Specular sheen sliding across the face. Painted under the card's content
   because a pseudo-element renders before real children. */
.card-tilt::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0;
  transition: opacity var(--dur-base) ease-out;
  background: radial-gradient(
    28rem circle at var(--tilt-mx, 50%) var(--tilt-my, 50%),
    color-mix(in oklab, var(--foreground) 8%, transparent),
    transparent 45%
  );
}
.card-tilt[data-tilting]::before { opacity: 1; }

/* Slide-over panels (e.g. a notification center) — exit needs a closing state. */
.panel-overlay-in  { animation: fade-in-soft 200ms ease-out both; }
.panel-overlay-out { animation: fade-in-soft 200ms ease-in reverse both; }
.panel-in          { animation: panel-in-right 300ms var(--ease-out-swift) both; }
.panel-out         { animation: panel-out-right 200ms ease-in both; }

@media (prefers-reduced-motion: reduce) {
  .motif-trace, .motif-beat,
  .anim-rise, .anim-fade, .anim-pop, .page-enter, .row-arrive,
  .stagger > *, .skeleton,
  .panel-overlay-in, .panel-overlay-out, .panel-in, .panel-out {
    animation: none;
  }
  .card-lift, .card-lift:hover, .card-lift:active {
    transition: none;
    transform: none;
    /* Drop the lift shadow, keep the ring: `box-shadow: none` here also erased
       the card's own outline, since Tailwind draws `ring-*` as a box-shadow and
       this rule is unlayered. A PC with OS animations switched off then showed
       borderless cards — the skeletons (no .card-lift) kept theirs, so the edge
       flashed on load and vanished with the real data. */
    box-shadow: var(--tw-ring-shadow, 0 0 #0000);
  }
  /* No tilt, no sheen — the card still answers the pointer, but with colour
     (the kind-tinted ring) instead of movement. */
  .card-tilt, .card-tilt:hover {
    transform: none;
    transition: none;
    box-shadow: var(--tw-ring-shadow, 0 0 #0000);
  }
  .card-tilt::before { display: none; }
}
```

And in the base layer — Tailwind v4's preflight dropped the UA hand cursor on
buttons, which left every control looking inert:

```css
@layer base {
  button:not(:disabled),
  [role="button"]:not(:disabled) {
    cursor: pointer;
  }
}
```

Dialogs, selects and popovers keep the animations shadcn ships with
(`tw-animate-css`); this system covers everything they don't.

---

## 2. Signature motif — `SignatureTrace.tsx`

One shape from the domain, drawn as an SVG path whose dashed stroke "sweeps".
The source's was a cardiac trace (one PQRST beat per 120 units); a logistics
app might draw a route line, a lab app a spectrum. Reuse it on the boot
screen, the sidebar, the login hero and the "all done" cards — and nowhere
else.

```tsx
import { cn } from "@/lib/utils"

// One repeat of the motif, `UNIT` wide, baseline y=18 in a 0..36 band.
// Example: a heartbeat — flat, P wave, QRS spike, T wave.
const UNIT = 120
function segment(x: number): string {
  return (
    `L${x + 8},18 Q${x + 16},13 ${x + 24},18 L${x + 40},18 ` +
    `L${x + 44},22 L${x + 50},3 L${x + 56},31 L${x + 62},18 ` +
    `L${x + 74},18 Q${x + 86},9 ${x + 98},18 L${x + UNIT},18 `
  )
}

function tracePath(repeats: number): string {
  let d = "M0,18 "
  for (let i = 0; i < repeats; i++) d += segment(i * UNIT)
  return d.trim()
}

/** Uses `currentColor`, so colour it with a text utility on the parent; size it
 *  with the parent's width/height. */
export function SignatureTrace({ className, repeats = 6, animate = true }: {
  className?: string
  repeats?: number
  animate?: boolean
}) {
  return (
    <svg
      viewBox={`0 0 ${repeats * UNIT} 36`}
      preserveAspectRatio="none"
      fill="none"
      className={cn("h-full w-full", className)}
      aria-hidden
    >
      <path
        d={tracePath(repeats)}
        stroke="currentColor"
        strokeWidth={1.75}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke" // stays crisp when the box stretches
        className={animate ? "motif-trace" : undefined}
      />
    </svg>
  )
}
```

```css
@keyframes motif-sweep { from { stroke-dashoffset: 0; } to { stroke-dashoffset: -1000; } }
.motif-trace { stroke-dasharray: 1000; animation: motif-sweep 6s linear infinite; }
```

The **beat dot** is the motif's small form — `<span className="motif-beat size-1.5
rounded-full bg-emerald-500" />` — on whatever is alive right now: an honest
"Live" badge (only while the socket is connected; see
`system-status-popover`), the active node of a progress rail, the processing
order's card, a non-zero live counter.

Boot screen, while auth resolves:

```tsx
<div className="grid min-h-screen place-items-center bg-background">
  <div className="anim-fade flex flex-col items-center gap-3 text-emerald-500">
    <div className="h-9 w-44"><SignatureTrace repeats={2} /></div>
    <span className="font-mono text-[10px] tracking-widest text-muted-foreground uppercase">Acquiring signal…</span>
  </div>
</div>
```

---

## 3. Loading honesty — skeletons, three states

```tsx
// components/ui/skeleton.tsx — theme-aware shimmer placeholder.
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="skeleton" aria-hidden className={cn("skeleton rounded-md", className)} {...props} />
}
```

Every list or console screen renders **three** states, keyed on `null`:

```tsx
const { data, error } = usePolling(fetcher, 30000) // data: T[] | null — null until the first answer

{error && (
  // Above the content, which keeps showing the last good data.
  <Card className="anim-rise mb-6 flex-row items-center gap-2 p-4 text-sm text-rose-600 ring-rose-500/30">
    <AlertCircle className="size-4" /> {error}
  </Card>
)}

{data === null ? (
  <div className="stagger grid grid-cols-2 gap-4 lg:grid-cols-4">
    {Array.from({ length: 4 }, (_, i) => <TileSkeleton key={i} style={stagger(i)} />)}
  </div>
) : data.length === 0 ? (
  <Card className="anim-rise p-10 text-center text-sm text-muted-foreground">
    Nothing here yet. {/* what to do next, with a link */}
  </Card>
) : (
  <div className="stagger grid grid-cols-2 gap-4 lg:grid-cols-4">
    {data.map((row, i) => <Tile key={row.id} row={row} style={stagger(i)} />)}
  </div>
)}
```

Shape the skeleton like the content it replaces — same card, same padding,
one ghost per text line at roughly its width — so nothing shifts when the data
lands:

```tsx
function TileSkeleton({ style }: { style?: React.CSSProperties }) {
  return (
    <Card className="gap-0 p-5" style={style}>
      <div className="flex items-center justify-between">
        <Skeleton className="h-3 w-20" />            {/* label */}
        <Skeleton className="size-4 rounded-full" /> {/* icon */}
      </div>
      <Skeleton className="mt-3 h-9 w-16" />         {/* the number */}
    </Card>
  )
}
```

A lazily loaded heavy view (a 3D scene, a chart library) gets a skeleton of
its own size as its `Suspense` fallback.

---

## 4. Entrances — page-enter, stagger

```tsx
// In the app shell: keyed on the route so every navigation gets a fresh rise.
// Key on the pathname only — keying on the query string would remount the page
// (and reset its state) on every filter change.
<main className="min-w-0 flex-1">
  <div key={location.pathname} className="page-enter mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-10 lg:py-8">
    {children}
  </div>
</main>
```

```ts
// lib/utils.ts — inline `--i` consumed by the `.stagger` utility.
import type { CSSProperties } from "react"
export function stagger(i: number): CSSProperties {
  return { "--i": i } as CSSProperties
}
```

- `.stagger > *` animates **direct children** only. When a card is wrapped in a
  link, the index goes on the link:

  ```tsx
  // A linked tile: the <Link> is the stagger child, so it carries --i.
  return to ? <Link to={to} className="block" style={style}>{card}</Link> : card // card has style={to ? undefined : style}
  ```
- **Continue the index across sections** for one page-level cascade: tiles
  `0–3`, a panel `4`, the cards below `i + 5`.
- Entrances are **mount-only**. A poll or socket refresh that re-renders the
  same keys does not replay them — keep keys stable (the row's id, never the
  array index for live data).

Login hero, the one orchestrated moment on the least-interrupted screen —
brand, then headline, then the motif, then the form:

```tsx
<div className="anim-rise">…brand…</div>
<div className="anim-rise" style={{ animationDelay: "100ms" }}>…headline…</div>
<div className="anim-rise" style={{ animationDelay: "200ms" }}><SignatureTrace repeats={5} /></div>
<div className="anim-rise w-full max-w-sm" style={{ animationDelay: "120ms" }}>…form…</div>
```

---

## 5. Live-data feedback — arrivals, re-pop, counters, glide, rail

**Arrival flash** — a row newly entering a live list gets one blip:

```ts
import { useEffect, useMemo, useRef } from "react"

/**
 * Ids that appeared since the previous data. The first load counts as "seen",
 * so the whole list doesn't flash on mount.
 */
export function useArrivals<T, K>(rows: T[] | null, idOf: (row: T) => K): Set<K> {
  const prev = useRef<Set<K> | null>(null)
  const fresh = useMemo(() => {
    const out = new Set<K>()
    if (!rows) return out
    const seen = prev.current
    if (seen) for (const r of rows) if (!seen.has(idOf(r))) out.add(idOf(r))
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows])
  useEffect(() => {
    if (rows) prev.current = new Set(rows.map(idOf))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows])
  return fresh
}

// usage — key the diff on the business id the operator reads (a serial)
const arrived = useArrivals(queue, (u) => u.serial)
<Card className={cn("card-lift …", arrived.has(u.serial) && "row-arrive")}>
```

**Re-pop on change** — `key={value}` remounts one small element, replaying its
entrance:

```tsx
<div key={value} className="anim-pop font-mono text-xl leading-none font-semibold">{value}</div>
```

**Counters** tween instead of jumping:

```tsx
import { useEffect, useRef, useState } from "react"

/** Tweens between values — the odometer feel for live counters. Skips straight
 *  to the target under reduced motion. */
export function AnimatedNumber({ value, duration = 600 }: { value: number; duration?: number }) {
  const [display, setDisplay] = useState(value)
  const prev = useRef(value)

  useEffect(() => {
    const from = prev.current
    prev.current = value
    if (from === value) return
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setDisplay(value)
      return
    }
    const t0 = performance.now()
    let raf = 0
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / duration)
      const eased = 1 - Math.pow(1 - p, 3) // ease-out cubic
      setDisplay(Math.round(from + (value - from) * eased))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value, duration])

  return <span className="tabular-nums">{display}</span>
}
```

**Progress bars glide** on live updates:

```tsx
<div className="h-2 overflow-hidden rounded-full bg-secondary">
  <div className="h-full rounded-full bg-emerald-500 transition-[width] duration-700 ease-out" style={{ width: `${pct}%` }} />
</div>
```

**Progress rail** — connectors *fill* left→right instead of colour-fading, and
done checks cascade in like a rhythm strip:

```tsx
{i > 0 && (
  <div className="relative mt-4 h-0.5 w-8 sm:w-12">
    <div className="absolute inset-0 rounded-full bg-border" />
    <div className={cn(
      "absolute inset-0 origin-left rounded-full bg-emerald-500 transition-transform duration-500 ease-out",
      prevDone ? "scale-x-100" : "scale-x-0",
    )} />
  </div>
)}
<div className={cn("relative grid size-9 place-items-center rounded-full border-2 transition-colors duration-300", NODE[state])}>
  {state === "done" ? (
    <Check className="anim-pop size-4" strokeWidth={3} style={{ animationDelay: `${Math.min(i, 10) * 40}ms` }} />
  ) : state === "fault" ? (
    <X className="anim-pop size-4" strokeWidth={3} />
  ) : (
    <span className="font-mono">{i + 1}</span>
  )}
  {state === "active" && <span className="motif-beat absolute -top-0.5 -right-0.5 size-2.5 rounded-full bg-sky-500 ring-2 ring-background" />}
</div>
```

The rail scrolls horizontally (`overflow-x-auto` around a `min-w-max` row);
inside a dialog or grid cell, give the scroller's parent `min-w-0`, or the row
widens the dialog past its edge.

---

## 6. Confirmation moments

The operator's most important feedback — "that step is recorded" — gets the
pop:

```tsx
<Card className="anim-fade gap-3 bg-emerald-500/[0.03] p-4 ring-emerald-500/30">
  <div className="flex items-center gap-2">
    {/* The confirmation moment: the check pops like a heartbeat blip. */}
    <span className="anim-pop grid size-6 place-items-center rounded-full bg-emerald-500 text-white">
      <Check className="size-3.5" strokeWidth={3} />
    </span>
    <span className="text-sm font-medium">{name}</span>
    <span className="ml-auto font-mono text-xs text-muted-foreground">{time}</span>
  </div>
</Card>
```

A whole-flow finish ("unit completed & packed", "order created") gets a
centered card: `anim-rise` on the card, `anim-pop` on a large check icon, the
motif underneath, then the next action as the focused button. Empty states
rise in the same way (`anim-rise`); a "queue is clear" icon can pop.

---

## 7. Pick-me cards — lift, tilt, whole-card target

**Tilt hook** (mouse only):

```ts
import { useCallback, useEffect, useRef } from "react"

// Pointer-tracked 3D tilt for a card, so it behaves like a physical card held
// in the hand: it dips away under the pointer and a soft highlight slides
// across its face. The maths lives here; the look lives in `.card-tilt`.
//
// Deliberately mouse-only. On a touchscreen there is no hovering pointer to
// track, and a tap would only ever snap the card to one angle.

/** Rotation at the very corners. Past ~8° it stops reading as a card on a
 *  bench and starts reading as a carousel. */
const MAX_DEG = 6

export function useTilt<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const frame = useRef(0)

  // Writes land on the element directly rather than through state: this fires
  // on every pointer move, and re-rendering a screen's worth of cards at that
  // rate would cost far more than the effect is worth.
  const onPointerMove = useCallback((e: React.PointerEvent<T>) => {
    if (e.pointerType !== "mouse") return
    const el = ref.current
    if (!el) return
    const { clientX, clientY } = e
    cancelAnimationFrame(frame.current)
    frame.current = requestAnimationFrame(() => {
      const r = el.getBoundingClientRect()
      if (r.width === 0 || r.height === 0) return
      const x = (clientX - r.left) / r.width // 0…1 from the top-left corner
      const y = (clientY - r.top) / r.height
      // Push where the pointer is: the near edge sinks away from the viewer.
      // Signs follow CSS's axes (Y points down).
      el.style.setProperty("--tilt-y", `${(x - 0.5) * 2 * MAX_DEG}deg`)
      el.style.setProperty("--tilt-x", `${(0.5 - y) * 2 * MAX_DEG}deg`)
      el.style.setProperty("--tilt-mx", `${x * 100}%`)
      el.style.setProperty("--tilt-my", `${y * 100}%`)
      el.dataset.tilting = "true"
    })
  }, [])

  const onPointerLeave = useCallback(() => {
    cancelAnimationFrame(frame.current)
    const el = ref.current
    if (!el) return
    // Dropping the properties returns the card to flat on the slower curve —
    // `data-tilting` is what selects between tracking and settling.
    delete el.dataset.tilting
    el.style.removeProperty("--tilt-x")
    el.style.removeProperty("--tilt-y")
  }, [])

  useEffect(() => () => cancelAnimationFrame(frame.current), [])

  return { ref, onPointerMove, onPointerLeave }
}
```

**The card** — one real button, stretched over the whole card:

```tsx
export function PickCard({ item, onPick }: { item: Item; onPick: (id: string) => void }) {
  const tilt = useTilt<HTMLDivElement>()
  return (
    // Fixed width per card; the row stretches every card to the tallest.
    <div className="flex w-64 shrink-0 self-stretch sm:w-72">
      <Card
        ref={tilt.ref}
        onPointerMove={tilt.onPointerMove}
        onPointerLeave={tilt.onPointerLeave}
        className={cn(
          // A hairline ring all but disappears on a bright floor; these are
          // pick-me tiles, so give them a real edge and thicken it under the pointer,
          // in the card's own kind colour.
          "card-tilt relative h-full w-full gap-3 p-5 text-left ring-foreground/20 hover:ring-2",
          KIND_RING[item.kind],
        )}
      >
        <div className="font-mono text-4xl leading-none font-semibold">{item.code}</div>
        {/* Reserve two lines so every card in a row is the same height. */}
        <div className="mt-2 min-h-10 text-sm leading-snug text-muted-foreground">{item.name}</div>

        {/* A secondary control sits ABOVE the stretched target (relative z-10),
            so using it never triggers the card's main action. */}
        <div className="relative z-10">
          <button type="button" onClick={toggleDetails}>…</button>
        </div>

        {/* The main action stays a real button — the card's focusable,
            keyboard-reachable control — but its ::after is stretched over the
            whole card, so a tap anywhere else picks it. One button per card
            (nesting buttons is not valid HTML), the full card as the target,
            44px tall for a gloved thumb aiming straight at it. */}
        <button
          type="button"
          onClick={() => onPick(item.id)}
          className="mt-auto flex min-h-11 w-full items-center gap-1.5 rounded-lg border bg-secondary/40 px-3 text-[13px] font-medium after:absolute after:inset-0 after:content-[''] group-hover/card:bg-secondary focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:outline-none"
        >
          Pick this one <ChevronRight className="ml-auto size-4 transition-transform group-hover/card:translate-x-0.5" />
        </button>
      </Card>
    </div>
  )
}

// The grid: items-stretch, so one expanded card doesn't leave its neighbours floating.
<div className="stagger flex flex-wrap items-stretch gap-y-5">
  {items.map((it, i) => <div key={it.id} className="flex items-stretch" style={stagger(i)}><PickCard item={it} onPick={pick} /></div>)}
</div>
```

`group-hover/card:` works because shadcn's `Card` carries the `group/card`
class; add it if your card doesn't. Plain clickable cards and rows that don't
need tilt take `card-lift` with a `hover:ring-foreground/20`.

---

## 8. Toasts — countdown hairline, gloved-thumb close

Sonner exposes no remaining-time hook, so the bar is a CSS animation timed to
the same constant as the toast — one export, handed to CSS as a variable:

```tsx
// components/ui/sonner.tsx
/** How long a toast stays up. Also drives the countdown bar's CSS animation.
 *  Change it here only. */
export const TOAST_DURATION = 5000

<Sonner
  duration={TOAST_DURATION}
  style={{ "--toast-duration": `${TOAST_DURATION}ms` } as React.CSSProperties}
  toastOptions={{
    classNames: {
      toast: "app-toast",
      // Carries the countdown bar. It hangs off the content block because
      // both of the toast's own pseudo-elements are already spoken for by
      // sonner — swipe feedback and the hover bridge between stacked toasts.
      content: "app-toast-content",
      // Restyled in CSS: sonner's own rules outrank utility classes.
      closeButton: "app-toast-close",
    },
  }}
/>

// App.tsx — pushed down so toasts clear the page header's actions (desktop)
// and the sticky header + nav strip (phone).
<Toaster richColors closeButton position="top-right" offset={{ top: "84px" }} mobileOffset={{ top: "116px" }} />
```

```css
/* Countdown bar — a hairline draining along the toast's bottom edge so the
   reader sees the dismissal coming instead of the toast vanishing mid-read.
   Inset past the corner radius so it never pokes out of the rounded edge.
   `currentColor` picks up the rich-colours tint per level for free. */
[data-sonner-toast].app-toast[data-styled="true"] .app-toast-content::after {
  content: "";
  position: absolute;
  right: 10px; bottom: 5px; left: 10px;
  height: 2px;
  border-radius: 999px;
  background: currentColor;
  opacity: 0.3;
  transform-origin: left center;
  animation: toast-countdown var(--toast-duration, 5000ms) linear forwards;
}
/* Hovering the stack is exactly when sonner freezes its dismissal timers —
   freeze the bar with them, or it would lie about the time left. */
[data-sonner-toaster]:hover [data-sonner-toast].app-toast[data-styled="true"] .app-toast-content::after {
  animation-play-state: paused;
}
/* A toast pinned open has nothing to count down. */
[data-sonner-toast].app-toast[data-type="loading"] .app-toast-content::after { display: none; }
@keyframes toast-countdown { from { transform: scaleX(1); } to { transform: scaleX(0); } }

/* Close button. Sonner parks a 20px disc on the leading corner — on top of the
   status icon, and too small for a gloved thumb. Move it to the trailing
   corner, grow it, and give it an invisible collar so the target clears 44px.
   The selector has to outrank sonner's runtime-injected
   `[data-sonner-toast][data-styled] [data-close-button]`, hence the pile-up. */
[data-sonner-toast].app-toast[data-styled="true"] .app-toast-close {
  --toast-close-button-start: unset;
  --toast-close-button-end: 0;
  --toast-close-button-transform: translate(35%, -35%);
  width: 28px;
  height: 28px;
}
[data-sonner-toast].app-toast[data-styled="true"] .app-toast-close svg { width: 16px; height: 16px; }
[data-sonner-toast].app-toast[data-styled="true"] .app-toast-close::after {
  content: "";
  position: absolute;
  inset: -8px;
  border-radius: 50%;
}
```

Every toast mirrored into a reviewable history (so dismissing one loses
nothing) is `toast-notification-history`.

---

## 9. "You are here" — the nav indicator

```tsx
<NavLink
  to={to}
  end={end}
  className={({ isActive }) =>
    cn(
      "group relative flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
      isActive ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
    )
  }
>
  {({ isActive }) => (
    <>
      {/* A bar scales in beside the active item. */}
      <span
        aria-hidden
        className={cn(
          "absolute top-1/2 left-0 h-4 w-0.5 -translate-y-1/2 rounded-full bg-emerald-500 transition-all duration-300",
          isActive ? "scale-y-100 opacity-100" : "scale-y-0 opacity-0",
        )}
      />
      <Icon className="size-4 shrink-0" />
      <span className="flex-1 whitespace-nowrap">{label}</span>
    </>
  )}
</NavLink>
```

---

## 10. The audit — start every pass here

The source began with this table, one row per area, and worked the gaps in
priority order (P0 loading and honesty → P1 feedback on what operators do all
day → P2 polish):

| Area | Today | Gap |
|---|---|---|
| Signature motif | | |
| Page navigation | | (a hard cut between pages?) |
| Loading | | (bare spinners? tiles flashing `0`? lists rendering nothing?) |
| Live data | | (rows repaint silently? numbers jump?) |
| "Live" badge | | (says Live while the socket is down?) |
| Slide-over panels | | (appear/disappear instantly next to animated dialogs?) |
| Success moments | | (the most important confirmation has no feedback?) |
| Progress (rails, bars) | | (colour-fade only? inconsistent transitions?) |
| Micro-interactions | | (clickable cards don't read as clickable?) |
| Boot / login | | (generic spinner where the brand moment belongs?) |
| Reduced motion | | (only some animations gated?) |

**Acceptance:** build and lint pass; every list or console screen shows a
skeleton — never a blank or zeroed frame — on first load; everything new is
off under `prefers-reduced-motion: reduce` with outlines intact; light and dark
both render skeletons and shadows; no poll re-render replays an entrance.
