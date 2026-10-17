# guided-product-tour — building blocks

Genericized from the source project. `@/` is a Vite alias to `src/`; `Button`
and `Dialog*` are shadcn/ui (Radix) primitives and `cn` is shadcn's class
merger. Sections are numbered to match SKILL.md's "Moving parts". Domain nouns
from the source (a station console, a serial-number scan) appear only as
examples. Storage keys are namespaced `app.*` — use your app's prefix.

---

## 1. Script — `tourSteps.ts`

```ts
// The guided tour script: one entry per stop, in chapters. Steps with a
// `route` navigate there first; steps with a `scene` open that piece of UI
// (a menu, a settings section, a dialog — see tourScene.ts) so the stop can
// point at the real control; steps with a `target` spotlight that element
// (first *visible* match wins, so one selector can serve desktop and mobile;
// a stop whose target never appears is skipped). Steps without a target
// render as a centered card (welcome / hand-off to the sandbox).
//
// `roles` hides a stop from everyone else — it must match who can actually
// open that page or setting, or the stop would point at a refusal.

import type { Role } from "@/lib/types" // extension point: your role union

export type ChapterId = "basics" | "daily" | "planning" | "settings" | "users"

export interface TourChapter {
  id: ChapterId
  title: string
  /** One line for the chapter picker. */
  blurb: string
}

export const CHAPTERS: TourChapter[] = [
  { id: "basics", title: "Getting around", blurb: "The sidebar, the Guide menu and your account." },
  { id: "daily", title: "Daily work", blurb: "The pages you use every shift — then try the main flow yourself." },
  { id: "planning", title: "Planning & reports", blurb: "Creating orders, the reports and the management pages." },
  { id: "settings", title: "Settings", blurb: "Your account menu, then every setting and what it changes." },
  { id: "users", title: "Users & accounts", blurb: "Creating a user, roles, password resets." },
]

export interface TourStep {
  id: string
  chapter: ChapterId
  title: string
  body: string
  /** Navigate here before showing the step. */
  route?: string
  /** UI the step needs open (tourScene.ts). */
  scene?: string
  /** CSS selector to spotlight; omit for a centered card. */
  target?: string
  /** Preferred card side; falls back automatically when space is tight. */
  placement?: "right" | "bottom"
  /** Only these roles see the stop (omit = everyone). */
  roles?: Role[]
  /** The full tour's last stop: its button opens the hands-on sandbox. */
  finale?: boolean
}

const MANAGERS: Role[] = ["supervisor", "admin"]
const ADMIN: Role[] = ["admin"]

export const TOUR_STEPS: TourStep[] = [
  // Centered welcome — no target.
  { id: "welcome", chapter: "basics", title: "Welcome", body: "What this system is for, in one sentence, and what the tour will show — ending in a safe sandbox." },
  // The sidebar: card to its right.
  { id: "nav", chapter: "basics", target: '[data-tour="nav"]', placement: "right", title: "Navigation", body: "Every page lives here…" },
  // Same anchor, an extra stop only admins see — not conditional copy.
  { id: "guide-admin", chapter: "basics", target: '[data-tour="nav-guide"]', placement: "right", roles: ADMIN, title: "Changelog", body: "Admins also find…" },
  // A whole page: the content area is the target, so the card pins bottom-centre.
  { id: "dashboard", chapter: "daily", route: "/", target: '[data-tour="page"]', title: "Dashboard", body: "…" },
  // One control on a page.
  { id: "orders-new", chapter: "planning", route: "/orders", target: '[data-tour="orders-new"]', title: "Creating an order", body: "…" },
  // Inside a menu the tour opens.
  { id: "account-menu", chapter: "settings", scene: "account-menu", target: '[data-tour="account-menu"]', placement: "right", title: "The account menu", body: "…" },
  // A settings section, managers only.
  { id: "settings-shifts", chapter: "settings", scene: "settings:line:shifts", target: '[data-tour="settings-pane"]', roles: MANAGERS, title: "Shifts", body: "…" },
  // A dialog the tour opens on a page, admins only.
  { id: "users-create", chapter: "users", route: "/users", scene: "users:create", target: '[data-tour="users-create"]', roles: ADMIN, title: "Filling in a new user", body: "…" },
  // Finale: lives in a chapter too, so walking that chapter also ends hands-on.
  { id: "try", chapter: "daily", finale: true, title: "Now try it yourself", body: "Let's do what an operator does a hundred times a day… It's a sandbox — nothing you do is saved." },
]

/** The stops this role sees, optionally one chapter only. */
export function stepsFor(role: Role | undefined, chapter?: ChapterId): TourStep[] {
  return TOUR_STEPS.filter(
    (s) =>
      (!s.roles || (!!role && s.roles.includes(role))) &&
      (!chapter || s.chapter === chapter),
  )
}
```

**Copy.** Each body says what the screen is for, then the one rule people get
wrong there, in the words the screen itself uses ("the badge on a section says
how far it reaches: Line settings apply to every terminal at once; Terminal
settings only to this browser"). Plain words; an enum token only where the UI
shows it.

**Anchors** — `data-tour` attributes only, no behaviour change:

```tsx
<nav data-tour="nav">…</nav>                         {/* desktop sidebar AND phone strip both carry it */}
<div data-tour={`nav-${entry.to.replace(/\W+/g, "")}`}>{/* a nav group, keyed from its route */}
<div key={location.pathname} data-tour="page">{children}</div>  {/* the shell's page area */}
<TableCell data-tour={i === 0 ? "users-role" : undefined}>      {/* a column: first row only */}
<DialogContent data-tour="users-create">              {/* a dialog the tour opens via a scene */}
```

An empty list has no row 0, so that stop skips itself — acceptable, and
visible in the verify walk (§9).

---

## 2. Provider — `TourProvider.tsx`

Mount inside the router and the auth boundary, wrapping the app shell, so the
tour exists only for a signed-in user and every page renders under it.

```tsx
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { useAuth } from "@/context/AuthContext" // extension point: current user + role
import { tourScene } from "@/lib/tourScene"
import { TourDemoDialog } from "./TourDemoDialog"
import { TourLauncher } from "./TourLauncher"
import { markChapterDone } from "./tourProgress"
import { TourOverlay } from "./TourOverlay"
import { CHAPTERS, stepsFor, type ChapterId, type TourStep } from "./tourSteps"

// One flag per terminal (a shared kiosk): the tour auto-runs once on a fresh
// terminal and stays out of the way after that. Use a per-user key instead on
// personal devices.
const SEEN_KEY = "app.tourSeen"

interface TourApi {
  /** Run the whole tour, or one chapter. */
  start: (chapter?: ChapterId) => void
  /** The chapter picker (Guide nav group, account menu). */
  openLauncher: () => void
}

const TourContext = createContext<TourApi>({ start: () => {}, openLauncher: () => {} })
export const useTour = () => useContext(TourContext)

interface Run {
  steps: TourStep[]
  index: number
  chapter?: ChapterId
}

const storage = {
  seen: () => { try { return !!localStorage.getItem(SEEN_KEY) } catch { return true } },
  markSeen: () => { try { localStorage.setItem(SEEN_KEY, "1") } catch { /* storage unavailable */ } },
}

export function TourProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [run, setRun] = useState<Run | null>(null)
  const [launcherOpen, setLauncherOpen] = useState(false)
  const [demoOpen, setDemoOpen] = useState(false)

  const start = useCallback(
    (chapter?: ChapterId) => {
      const steps = stepsFor(user?.role, chapter)
      setLauncherOpen(false)
      setDemoOpen(false)
      if (steps.length) setRun({ steps, index: 0, chapter })
    },
    [user?.role],
  )
  const openLauncher = useCallback(() => {
    setRun(null)
    setLauncherOpen(true)
  }, [])

  // First sign-in on this terminal: the tour introduces itself, after the
  // shell has had a moment to render.
  useEffect(() => {
    if (storage.seen()) return
    const t = setTimeout(() => start(), 900)
    return () => clearTimeout(t)
  }, [start])

  const step = run ? (run.steps[run.index] ?? null) : null

  // A stop can live on another page — go there first; the overlay holds off
  // measuring its target until the route has actually rendered.
  useEffect(() => {
    if (step?.route && location.pathname !== step.route) navigate(step.route)
  }, [step, location.pathname, navigate])

  // Open (or close) what the stop points at.
  useEffect(() => {
    tourScene.set(step?.scene ?? null)
  }, [step])
  useEffect(() => () => tourScene.set(null), [])

  const finish = useCallback(
    (completed: boolean) => {
      if (!run) return
      const last = run.steps[run.steps.length - 1]
      setRun(null)
      tourScene.set(null)
      storage.markSeen() // Skip counts as seen too — it never auto-runs again
      if (!completed) return
      if (run.chapter) markChapterDone(run.chapter)
      else CHAPTERS.forEach((c) => markChapterDone(c.id))
      if (last?.finale) setDemoOpen(true) // the tour ends with the user's own hands on it
      else if (run.chapter) setLauncherOpen(true) // one chapter done — offer the next
    },
    [run],
  )

  const next = useCallback(() => {
    if (!run) return
    if (run.index >= run.steps.length - 1) finish(true)
    else setRun({ ...run, index: run.index + 1 })
  }, [run, finish])

  const back = useCallback(() => {
    if (run && run.index > 0) setRun({ ...run, index: run.index - 1 })
  }, [run])

  const value = useMemo(() => ({ start, openLauncher }), [start, openLauncher])
  const chapter = step ? CHAPTERS.find((c) => c.id === step.chapter) : undefined

  return (
    <TourContext.Provider value={value}>
      {children}
      {step && run && (
        <TourOverlay
          key={step.id} // every stop starts with fresh measurement and its entry animation
          step={step}
          chapterTitle={
            run.chapter ? chapter?.title : step.finale ? "Full tour" : `Full tour · ${chapter?.title ?? ""}`
          }
          index={run.index}
          count={run.steps.length}
          routeReady={!step.route || location.pathname === step.route}
          isLast={run.index === run.steps.length - 1}
          onBack={run.index > 0 ? back : undefined}
          onNext={next}
          onSkip={() => finish(false)}
        />
      )}
      <TourLauncher
        open={launcherOpen}
        onOpenChange={setLauncherOpen}
        role={user?.role}
        onStart={start}
        onDemo={() => {
          setLauncherOpen(false)
          setDemoOpen(true)
        }}
      />
      <TourDemoDialog
        open={demoOpen}
        onOpenChange={(o) => {
          setDemoOpen(o)
          if (!o) storage.markSeen()
        }}
      />
    </TourContext.Provider>
  )
}
```

```tsx
// App.tsx — inside the signed-in branch
<SocketProvider>
  <TourProvider>
    <AppShell>
      <Routes>…</Routes>
    </AppShell>
  </TourProvider>
</SocketProvider>
```

---

## 3. Overlay — `TourOverlay.tsx`

```tsx
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react"
import { createPortal } from "react-dom"
import { ArrowLeft, ArrowRight, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { TourStep } from "./tourSteps"

interface Rect { top: number; left: number; width: number; height: number }

// Breathing room between the target and the spotlight ring.
const PAD = 8
const TIP_W = 340
const GAP = 14
// How long to look for a target before skipping the stop. A target inside a
// menu or dialog the tour just opened (or a list still loading) gets longer.
const FIND_MS = 1600
const FIND_SCENE_MS = 3000

/**
 * One tour stop: a dimmed screen with a spotlight cut out over the target
 * (a single box-shadow paints the scrim) and a positioned coach card.
 * Targetless steps center the card instead. The layer is modal: the app
 * underneath takes no clicks while the tour is up.
 */
export function TourOverlay({
  step, chapterTitle, index, count, routeReady, isLast, onBack, onNext, onSkip,
}: {
  step: TourStep
  /** Which chapter this stop belongs to, for the card's header. */
  chapterTitle?: string
  index: number
  count: number
  /** False while the step's route hasn't rendered yet — hold measurement. */
  routeReady: boolean
  isLast: boolean
  onBack?: () => void
  onNext: () => void
  onSkip: () => void
}) {
  const [rect, setRect] = useState<Rect | null>(null)
  const tipRef = useRef<HTMLDivElement>(null)
  const [tipHeight, setTipHeight] = useState(0)
  // The card's real height decides which side of the target it fits on.
  useLayoutEffect(() => {
    const el = tipRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setTipHeight(el.offsetHeight))
    ro.observe(el)
    setTipHeight(el.offsetHeight)
    return () => ro.disconnect()
  }, [])
  const [missing, setMissing] = useState(false)
  const scrolledRef = useRef(false)

  // Follow the target at frame rate — self-corrects across route changes,
  // page-enter animations, scrolling and window resizes.
  useEffect(() => {
    scrolledRef.current = false
    setRect(null)
    setMissing(false)
    if (!step.target) return
    let raf = 0
    const started = performance.now()
    const tick = () => {
      raf = requestAnimationFrame(tick)
      if (!routeReady) return
      const el = Array.from(document.querySelectorAll<HTMLElement>(step.target!)).find((e) => {
        const r = e.getBoundingClientRect()
        return r.width > 0 && r.height > 0 // first *visible* match: hidden desktop/mobile twins exist
      })
      if (!el) {
        // Target absent (e.g. a desktop-only element on a phone): wait a
        // moment, then skip the stop rather than spotlighting nothing.
        if (performance.now() - started > (step.scene ? FIND_SCENE_MS : FIND_MS)) setMissing(true)
        return
      }
      if (!scrolledRef.current) {
        scrolledRef.current = true // once per stop — every frame would pin the page
        el.scrollIntoView({ block: "nearest", inline: "nearest" })
      }
      const r = el.getBoundingClientRect()
      setRect((prev) =>
        prev && prev.top === r.top && prev.left === r.left && prev.width === r.width && prev.height === r.height
          ? prev // unchanged: no re-render
          : { top: r.top, left: r.left, width: r.width, height: r.height },
      )
    }
    tick()
    return () => cancelAnimationFrame(raf)
  }, [step.target, step.scene, routeReady])

  useEffect(() => {
    if (missing) onNext()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [missing])

  // Captured and swallowed: a dialog the tour opened underneath must not take
  // Enter as "submit" or Escape as "close"; Tab must not wander under the scrim.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const act =
        e.key === "Escape" ? onSkip
        : e.key === "ArrowRight" || e.key === "Enter" ? onNext
        : e.key === "ArrowLeft" ? onBack
        : undefined
      if (e.key === "Tab" || act) {
        e.preventDefault()
        e.stopPropagation()
      }
      act?.()
    }
    window.addEventListener("keydown", onKey, true)
    return () => window.removeEventListener("keydown", onKey, true)
  }, [onNext, onBack, onSkip])

  const centered = !step.target
  const spot = rect
    ? { top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 }
    : null

  const vw = window.innerWidth
  const vh = window.innerHeight
  const tipW = Math.min(TIP_W, vw - 24)
  const clampLeft = (l: number) => Math.min(Math.max(l, 12), vw - tipW - 12)

  let tipStyle: CSSProperties = { top: "50%", left: "50%", transform: "translate(-50%, -50%)" }
  if (!centered && spot) {
    const pinned: CSSProperties = { bottom: 20, left: "50%", transform: "translateX(-50%)" }
    const tipH = tipHeight || 260 // first frame only, before the observer reports
    const clampTop = (t: number) => Math.min(Math.max(t, 12), vh - tipH - 12)
    const sides: Record<"right" | "left" | "bottom" | "top", () => CSSProperties | null> = {
      right: () => spot.left + spot.width + GAP + tipW <= vw - 12
        ? { left: spot.left + spot.width + GAP, top: clampTop(spot.top) } : null,
      left: () => spot.left - GAP - tipW >= 12
        ? { left: spot.left - GAP - tipW, top: clampTop(spot.top) } : null,
      bottom: () => spot.top + spot.height + GAP + tipH <= vh - 12
        ? { top: spot.top + spot.height + GAP, left: clampLeft(spot.left + spot.width / 2 - tipW / 2) } : null,
      top: () => spot.top - GAP - tipH >= 12
        ? { top: spot.top - GAP - tipH, left: clampLeft(spot.left + spot.width / 2 - tipW / 2) } : null,
    }
    // The first side with room, never on top of the target; a target too
    // big for any side (a whole page) gets the card pinned bottom-center.
    const order: (keyof typeof sides)[] =
      step.placement === "right" ? ["right", "bottom", "top", "left"] : ["bottom", "top", "right", "left"]
    const pageSized = spot.height > vh * 0.55 && spot.width > vw * 0.5
    tipStyle = pageSized ? pinned : (order.map((k) => sides[k]()).find(Boolean) ?? pinned)
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[100]" // above the dialog library's layer (shadcn dialogs sit at z-50)
      role="dialog"
      aria-modal
      aria-label="Guided tour"
      data-tour-overlay
      // An open Radix dialog sets pointer-events: none on <body>; the tour's
      // buttons must stay clickable over it.
      style={{ pointerEvents: "auto" }}
    >
      {/* Scrim: painted by the spotlight's shadow when there is a target. */}
      {(centered || !spot) && <div className="anim-fade absolute inset-0 bg-slate-950/60" />}
      {!centered && spot && (
        <div
          data-tour-ring
          className="absolute rounded-xl ring-2 ring-sky-400/80 transition-all duration-300 ease-out"
          style={{ ...spot, boxShadow: "0 0 0 200vmax rgb(2 6 23 / 0.60)" }}
        />
      )}

      <div
        ref={tipRef}
        className={cn(
          "anim-rise absolute rounded-xl border bg-card p-4 text-card-foreground shadow-2xl",
          centered && "p-6 text-center",
        )}
        style={{ width: tipW, ...tipStyle }}
      >
        {/* A brand mark above a centered card's title fits here. */}
        <div className={cn("mb-1 flex items-center gap-2", centered && "justify-center")}>
          {!centered && <Sparkles className="size-3.5 shrink-0 text-sky-500" />}
          <span className="truncate font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
            {chapterTitle || "Tour"}
          </span>
          <span className="ml-auto shrink-0 font-mono text-[10px] text-muted-foreground tabular-nums">
            {index + 1} / {count}
          </span>
        </div>
        <div className={cn("font-semibold", centered && "text-lg")}>{step.title}</div>
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{step.body}</p>

        <div className={cn("mt-4 flex items-center gap-2", centered && "justify-center")}>
          {/* Progress — a bar, since a full tour runs to two dozen stops. */}
          {!centered && (
            <div className="h-1 flex-1 overflow-hidden rounded-full bg-border">
              <div
                className="h-full rounded-full bg-emerald-500 transition-[width] duration-300"
                style={{ width: `${((index + 1) / count) * 100}%` }}
              />
            </div>
          )}
          <Button variant="ghost" size="sm" onClick={onSkip}>Skip</Button>
          {onBack && (
            <Button variant="outline" size="sm" onClick={onBack}>
              <ArrowLeft className="size-4" /> Back
            </Button>
          )}
          <Button size="sm" autoFocus onClick={onNext}>
            {isLast ? (step.finale ? "Try it yourself" : "Finish") : index === 0 && centered ? "Start tour" : "Next"}
            <ArrowRight className="size-4" />
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
```

Motion utilities the overlay uses, if the app has none:

```css
:root { --ease-out-swift: cubic-bezier(0.16, 1, 0.3, 1); --dur-base: 250ms; --dur-enter: 350ms; }
@keyframes rise-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes fade-in-soft { from { opacity: 0; } to { opacity: 1; } }
.anim-rise { animation: rise-in var(--dur-enter) var(--ease-out-swift) both; }
.anim-fade { animation: fade-in-soft var(--dur-base) ease-out both; }
@media (prefers-reduced-motion: reduce) { .anim-rise, .anim-fade { animation: none; } }
```

**Global hotkeys.** A hotkey layer that stands down "while a modal is open"
by matching dialog content will not see this overlay (it is a portal'd `div`,
not dialog content), so an Alt-chord would still act on the page behind the
tour. Add `[data-tour-overlay]` to that check — e.g. in
`keyboard-first-hotkeys`' `modalIsOpen()`:

```ts
const modalIsOpen = () => !!document.querySelector('[data-slot="dialog-content"], [data-tour-overlay]')
```

---

## 4. Scenes — `tourScene.ts`, the owners, the primitives

```ts
// The guided tour's "scene": a piece of UI a tour stop needs open — the
// account menu, a settings section, a "New user" dialog — so the stop can
// point at the real control instead of describing it. The tour sets it; the
// component that owns that UI opens it while the scene is current and closes
// it again when the scene moves on (only if the tour opened it).
//
// Scenes are plain strings, "<owner>[:<arg>[:<arg>]]", e.g.
//   "account-menu"                the account menu
//   "settings:<tab>:<section>"    the settings dialog on that section
//   "users:create"                the New user dialog on the users page
//
// A store rather than an event, so a page the tour has only just navigated
// to reads the current scene when it mounts.

import { useSyncExternalStore } from "react"

let current: string | null = null
const listeners = new Set<() => void>()

export const tourScene = {
  get: (): string | null => current,
  set(scene: string | null) {
    if (scene === current) return
    current = scene
    listeners.forEach((l) => l())
  },
  subscribe(listener: () => void) {
    listeners.add(listener)
    return () => { listeners.delete(listener) }
  },
}

export function useTourScene(): string | null {
  return useSyncExternalStore(tourScene.subscribe, tourScene.get, tourScene.get)
}

/** The args of a scene that belongs to `owner`, or null. "settings:line:shifts" → ["line", "shifts"]. */
export function sceneArgs(scene: string | null, owner: string): string[] | null {
  const [kind, ...args] = (scene ?? "").split(":")
  return kind === owner ? args : null
}

/**
 * True when a dialog / popover is being told to close because of the tour's
 * own overlay (its Next / Back buttons sit outside the dialog) — the dialog
 * the tour is pointing at must stay open. Used by the UI primitives'
 * outside-interaction and Escape handlers.
 */
export function fromTourOverlay(event: Event): boolean {
  const original = (event as CustomEvent<{ originalEvent?: Event }>).detail?.originalEvent
  const target = (original?.target ?? event.target) as Element | null
  return !!target?.closest?.("[data-tour-overlay]") || current !== null
}
```

**Owner: a menu that exists twice** (desktop sidebar + phone header) **and
opens on hover**:

```tsx
const scene = useTourScene()
const tourOpened = useRef({ menu: false, settings: false })
useEffect(() => {
  // Two copies of this menu are mounted; only the one on screen answers.
  const visible = (triggerRef.current?.getClientRects().length ?? 0) > 0
  if (scene === "account-menu" && visible) {
    tourOpened.current.menu = true
    setOpen(true)
  } else if (tourOpened.current.menu) {
    tourOpened.current.menu = false // close only what the tour opened
    setOpen(false)
  }
  const tab = sceneArgs(scene, "settings")?.[0]
  if (tab && visible) {
    tourOpened.current.settings = true
    setSettingsTab(tab)
  } else if (tourOpened.current.settings) {
    tourOpened.current.settings = false
    setSettingsTab(null)
  }
}, [scene])

// Hover intent stands down while the tour holds a scene — otherwise moving
// the pointer from the menu to the card's Next button closes the menu.
const hoverIn = (e: React.PointerEvent) => {
  if (e.pointerType !== "mouse" || tourScene.get()) return
  /* …open after an intent delay… */
}
const hoverOut = (e: React.PointerEvent) => {
  if (e.pointerType !== "mouse" || tourScene.get()) return
  /* …close after a grace delay… */
}
```

**Owner: a dialog a page opens:**

```tsx
const scene = useTourScene()
const tourOpened = useRef(false)
useEffect(() => {
  if (scene === "users:create") {
    tourOpened.current = true
    setCreateOpen(true)
  } else if (tourOpened.current) {
    tourOpened.current = false
    setCreateOpen(false)
  }
}, [scene])
```

**Owner: a section inside an open dialog** (the dialog's opener handled the
tab; the dialog picks the section):

```tsx
const scene = useTourScene()
useEffect(() => {
  const id = sceneArgs(scene, "settings")?.[1]
  if (id && SECTIONS.some((s) => s.id === id)) setSection(id as SectionId)
}, [scene])
```

**Primitives, once** — the shadcn `DialogContent` and `PopoverContent`
wrappers. Pull the consumer's own handlers out of `props` and call them in
the `else`, so app code that passes them keeps working:

```tsx
function DialogContent({ onInteractOutside, onEscapeKeyDown, ...props }: React.ComponentProps<typeof DialogPrimitive.Content>) {
  return (
    <DialogPrimitive.Content
      data-slot="dialog-content"
      // A dialog the guided tour opened stays open while the tour's own
      // buttons (outside it) are used.
      onInteractOutside={(e) => {
        if (fromTourOverlay(e)) e.preventDefault()
        else onInteractOutside?.(e)
      }}
      onEscapeKeyDown={(e) => {
        if (fromTourOverlay(e)) e.preventDefault()
        else onEscapeKeyDown?.(e)
      }}
      {...props}
    />
  )
}
```

---

## 5. Launcher + progress — `TourLauncher.tsx`, `tourProgress.ts`

```ts
// tourProgress.ts — which chapters this terminal has walked to the end (the
// ticks in the chapter picker). A convenience only, so storage failures are ignored.
import type { ChapterId } from "./tourSteps"

const DONE_KEY = "app.tourChapters"

export function readDone(): ChapterId[] {
  try {
    return JSON.parse(localStorage.getItem(DONE_KEY) ?? "[]") as ChapterId[]
  } catch {
    return []
  }
}

export function markChapterDone(id: ChapterId) {
  try {
    const done = new Set(readDone())
    done.add(id)
    localStorage.setItem(DONE_KEY, JSON.stringify([...done]))
  } catch {
    // storage unavailable
  }
}
```

```tsx
// TourLauncher.tsx
import { useState } from "react"
import { ArrowRight, Boxes, CheckCircle2, Compass, Gamepad2, ScanLine, SlidersHorizontal, Users, type LucideIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import type { Role } from "@/lib/types"
import { cn } from "@/lib/utils"
import { readDone } from "./tourProgress"
import { CHAPTERS, stepsFor, type ChapterId } from "./tourSteps"

const ICONS: Record<ChapterId, LucideIcon> = {
  basics: Compass, daily: ScanLine, planning: Boxes, settings: SlidersHorizontal, users: Users,
}

/** Roughly 15 s a stop. */
const minutes = (stops: number) => `~${Math.max(1, Math.round((stops * 15) / 60))} min`

/**
 * The chapter picker. The full tour, or one chapter at a time (only the
 * chapters this role has stops in), plus the hands-on sandbox on its own.
 * A chapter walked to the end gets a tick on this terminal.
 */
export function TourLauncher({ open, onOpenChange, role, onStart, onDemo }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  role: Role | undefined
  onStart: (chapter?: ChapterId) => void
  onDemo: () => void
}) {
  // Re-read the ticks each time it opens (a chapter may have just finished).
  const [done, setDone] = useState<ChapterId[]>(readDone)
  const chapters = CHAPTERS.map((c) => ({ ...c, stops: stepsFor(role, c.id).length })).filter((c) => c.stops > 0)
  const total = stepsFor(role).length

  return (
    <Dialog open={open} onOpenChange={(o) => { if (o) setDone(readDone()); onOpenChange(o) }}>
      <DialogContent className="sm:max-w-2xl" onOpenAutoFocus={() => setDone(readDone())}>
        <DialogHeader>
          <DialogTitle>Guided tour</DialogTitle>
          <DialogDescription>
            A walk through the pages and settings you can use, with the real screens. Take it all, or just the chapter you need.
          </DialogDescription>
        </DialogHeader>

        <button type="button" onClick={() => onStart()} className="group flex items-center gap-4 rounded-xl border border-emerald-500/40 bg-emerald-500/5 p-4 text-left hover:border-emerald-500/70">
          <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-emerald-600 text-white"><Compass className="size-5" /></span>
          <span className="min-w-0 flex-1">
            <span className="block font-semibold">Take the full tour</span>
            <span className="block text-xs text-muted-foreground">{total} stops · {minutes(total)} · every chapter below, ending in the hands-on demo</span>
          </span>
          <ArrowRight className="size-4 shrink-0 transition-transform group-hover:translate-x-0.5" />
        </button>

        <div className="grid gap-2 sm:grid-cols-2">
          {chapters.map((c) => {
            const Icon = ICONS[c.id]
            const ticked = done.includes(c.id)
            return (
              <button key={c.id} type="button" onClick={() => onStart(c.id)} className="flex items-start gap-3 rounded-xl border bg-background p-3 text-left hover:border-emerald-500/50">
                <span className={cn("grid size-9 shrink-0 place-items-center rounded-lg", ticked ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" : "bg-muted text-muted-foreground")}>
                  {ticked ? <CheckCircle2 className="size-[18px]" /> : <Icon className="size-[18px]" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="text-sm font-semibold">{c.title}</span>
                    <span className="shrink-0 text-[11px] text-muted-foreground">{c.stops} stop{c.stops === 1 ? "" : "s"}</span>
                  </span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">{c.blurb}</span>
                </span>
              </button>
            )
          })}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
          <p className="text-xs text-muted-foreground">Use ← → or Enter to move through a tour, Esc to leave it.</p>
          <Button variant="outline" size="sm" onClick={onDemo}><Gamepad2 /> Hands-on demo only</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
```

**Entry points** — both call `useTour().openLauncher()`:
- a "Guided tour" *action* row in the nav's Guide group (an item that does
  something rather than going somewhere, beside the help pages of §8);
- "Take the tour" in the account menu (close the menu first).

---

## 6–7. Sandboxes

The sandbox finale and the flow sandbox live in [`SANDBOX.md`](SANDBOX.md).

---

## 8. Guide hub — framed help pages

The launcher's natural home is a **Guide** nav group: the help pages, the
"Guided tour" action, and (admin) a changelog. Static self-contained HTML
help pages under `public/docs/` are framed inside the app rather than ported,
so they open like any page with the sidebar still there:

```tsx
/**
 * A static page under public/docs shown inside the app. Each page is a
 * self-contained HTML file (no build step), so it is framed rather than
 * ported; it hides its own back link and theme toggle when framed and
 * follows the app's theme through the shared `theme` key.
 */
function DocFrame({ src, title }: { src: string; title: string }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
        <span>Guide · <span className="text-foreground">{title}</span></span>
        <a href={src} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-secondary">
          Open in a new tab <ArrowUpRight className="size-3.5" />
        </a>
      </div>
      {/* Fills the main column under the app chrome; the page scrolls inside. */}
      <iframe src={src} title={title} className="block h-[calc(100dvh-12rem)] w-full rounded-xl border bg-background lg:h-[calc(100dvh-6.5rem)]" />
    </div>
  )
}

/** `/guide/qa#q54` opens answer 54 — only a hash of the expected shape is handed on. */
export function QaPage() {
  const { hash } = useLocation()
  return <DocFrame src={`/docs/faq.html${/^#q\d+$/.test(hash) ? hash : ""}`} title="Q&A" />
}
```

Inside each framed page:

```js
// Inside the app's frame rather than a tab of its own: the app's chrome takes over.
document.documentElement.classList.toggle("embedded", window.self !== window.top);
// CSS: .embedded .header-actions { display: none; }

// Theme — the same localStorage key the app's theme library writes (next-themes: "theme").
function applyTheme() {
  const pref = localStorage.getItem("theme");
  const dark = pref === "dark" || ((pref === "system" || !pref) && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}
// Follow the app when its theme switch is used while this page is open —
// a change made in another document fires `storage` here.
window.addEventListener("storage", (e) => { if (e.key === "theme") applyTheme(); });

// Deep links: #q54 opens that answer.
function openFromHash() {
  const id = location.hash.slice(1);
  if (!/^q\d+$/.test(id)) return;
  const el = document.getElementById(id);
  if (!el) return;
  el.open = true; // <details>
  el.scrollIntoView({ block: "center" });
}
window.addEventListener("hashchange", openFromHash);
```

---

## 9. Verification — walk it as every role

The tour is pure UI over real screens, so the check is a walk, not a unit
test. The source shipped without an automated one; this Playwright sketch
walks every chapter as every role (`signInAs` and `openLauncher` are the
extension points):

```ts
import { expect, test, type Page } from "@playwright/test"
import { CHAPTERS, stepsFor } from "../src/components/tour/tourSteps"

const PAD = 8 // TourOverlay's spotlight padding

// The ring settles after scrollIntoView, so poll rather than read once.
async function ringOn(page: Page, target: string) {
  await expect.poll(async () => {
    const [r, t] = await Promise.all([
      page.locator("[data-tour-ring]").boundingBox(),
      page.locator(`${target} >> visible=true`).first().boundingBox(),
    ])
    return !!r && !!t && Math.abs(r.x + PAD - t.x) < 3 && Math.abs(r.y + PAD - t.y) < 3
  }).toBe(true)
}

for (const role of ["operator", "supervisor", "admin"] as const) {
  test(`tour as ${role}`, async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("app.tourSeen", "1")) // no auto-run mid-test
    await signInAs(page, role)
    for (const chapter of CHAPTERS) {
      const stops = stepsFor(role, chapter.id)
      if (!stops.length) continue
      await openLauncher(page)
      await page.getByRole("button", { name: new RegExp(chapter.title) }).click()
      for (const stop of stops) {
        if (stop.target) await ringOn(page, stop.target) // times out on a skipped stop = broken anchor
        else await expect(page.getByRole("dialog", { name: "Guided tour" })).toContainText(stop.title)
        await page.screenshot({ path: `proof/${role}-${chapter.id}-${stop.id}.png` })
        await page.keyboard.press("ArrowRight")
      }
      await expect(page.locator("[data-tour-overlay]")).toHaveCount(0)
      // Finishing opened the launcher (or the sandbox, after a finale) — close it,
      // then nothing a scene opened may be left behind.
      await page.keyboard.press("Escape")
      await expect(page.locator('[data-slot="dialog-content"]')).toHaveCount(0)
    }
  })
}

test("sandbox sends nothing", async ({ page }) => {
  await signInAs(page, "operator")
  const calls: string[] = []
  page.on("request", (r) => { if (r.url().includes("/api/")) calls.push(r.url()) })
  await openLauncher(page)
  await page.getByRole("button", { name: "Hands-on demo only" }).click()
  /* walk the sandbox to its done card */
  expect(calls).toEqual([])
})
```

A stop the data legitimately empties (a table with no rows) can be listed as
an expected skip; every other skip is a broken anchor.
