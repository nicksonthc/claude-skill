# toast-notification-history — building blocks

Genericized from the source project. `@/` is a Vite alias to `src/`; `cn` is
clsx+tailwind-merge; Button is shadcn/ui; icons are lucide. sonner is the
toast library — the wrapper pattern ports to any toast lib with level
functions. Sections numbered to match SKILL.md's "Moving parts".

## 1. The store

```ts
// src/lib/notifications.ts
import { useSyncExternalStore } from "react"

/**
 * Persistent notification history — a module-level store (not React context)
 * so it can be written from non-component code (e.g. `notify` in api flows).
 * Mirrors every toast into a capped, localStorage-backed log the user can
 * review from the floating bell. Cleared on logout (shared-terminal hygiene).
 */

export type NotificationLevel = "success" | "error" | "warning" | "info"

export interface AppNotification {
  id: string
  level: NotificationLevel
  title: string
  description?: string
  ts: number // epoch ms
}

interface State {
  items: AppNotification[]
  lastSeenTs: number // notifications with ts > lastSeenTs are unread
}

const MAX = 20
const KEY = "app.notifications" // namespace per app if several share a host

function load(): State {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<State>
      // Validate the shape — an older build's value must not poison renders.
      if (Array.isArray(parsed.items)) {
        return {
          items: parsed.items.slice(0, MAX),
          lastSeenTs: parsed.lastSeenTs ?? 0,
        }
      }
    }
  } catch {
    // ignore malformed / unavailable storage
  }
  return { items: [], lastSeenTs: 0 }
}

let state: State = load()
let seq = 0 // two pushes in the same ms would collide on Date.now() alone
const listeners = new Set<() => void>()

function setState(next: State): void {
  state = next
  try {
    localStorage.setItem(KEY, JSON.stringify(state))
  } catch {
    // storage may be full/disabled — history still works in-memory
  }
  listeners.forEach((l) => l())
}

export const notifications = {
  subscribe(listener: () => void): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
  snapshot(): State {
    return state
  },
  push(level: NotificationLevel, title: string, description?: string): void {
    const item: AppNotification = {
      id: `${Date.now()}-${++seq}`,
      level,
      title,
      description,
      ts: Date.now(),
    }
    setState({ ...state, items: [item, ...state.items].slice(0, MAX) })
  },
  markAllRead(): void {
    if (state.items.length === 0) return
    setState({ ...state, lastSeenTs: state.items[0].ts })
  },
  clear(): void {
    setState({ items: [], lastSeenTs: Date.now() })
  },
}

export function useNotifications(): State {
  return useSyncExternalStore(notifications.subscribe, notifications.snapshot)
}

export function useUnreadCount(): number {
  const s = useNotifications()
  return s.items.filter((i) => i.ts > s.lastSeenTs).length
}
```

## 2. The notify wrapper

```ts
// src/lib/notify.ts
import { toast, type ExternalToast } from "sonner"

import { notifications, type NotificationLevel } from "./notifications"

/**
 * Drop-in replacement for sonner's `toast` (the four levels we use). Shows
 * the toast AND records it in the persistent notification history. Import as
 * `import { notify as toast } from "@/lib/notify"` so existing call sites
 * work unchanged.
 *
 * On a shared terminal "it worked" is not enough — an entry in the history
 * has to say *what* it applied to and *who* did it. Call sites supply the
 * what (`description`: record id, station, batch…); the who is stamped on
 * automatically from the signed-in user, so no call site has to thread the
 * user through.
 */

/** Who is operating this terminal — stamped onto this session's toasts.
 *  Extension point: reshape to what attribution means in the target app. */
export interface NotifyActor {
  name: string
  role: string
  employeeNo: string
  /** Terminal/station assignment, if any. */
  station: string | null
}

let actor: NotifyActor | null = null

/**
 * Installed once by the app shell for as long as someone is signed in
 * (cleared on sign-out). Module-level rather than context so `notify` stays
 * callable from anywhere, including outside React.
 */
export function setNotifyActor(next: NotifyActor | null): void {
  actor = next
}

/** "Aisyah (E1042) · operator · ST3" — omitted when nobody is signed in. */
function actorLine(): string | undefined {
  if (!actor) return undefined
  const at = actor.station ? ` · ${actor.station}` : ""
  return `${actor.name} (${actor.employeeNo}) · ${actor.role}${at}`
}

export type NotifyOptions = ExternalToast & {
  /**
   * Set false when the toast reports somebody *else's* action (a live socket
   * event, say) — the actor line would otherwise credit it to this terminal.
   * Name the real actor in `description` instead.
   */
  self?: boolean
}

function make(level: NotificationLevel) {
  return (title: string, opts?: NotifyOptions) => {
    const { self = true, ...rest } = opts ?? {}
    const own =
      typeof rest.description === "string" ? rest.description : undefined
    // Merge, don't clobber: the call site's WHAT + the stamped WHO.
    const description =
      [own, self ? actorLine() : undefined].filter(Boolean).join(" · ") ||
      undefined
    notifications.push(level, title, description)
    return toast[level](title, { ...rest, description })
  }
}

export const notify = {
  success: make("success"),
  error: make("error"),
  warning: make("warning"),
  info: make("info"),
}
```

App-shell wiring:

```tsx
useEffect(() => {
  setNotifyActor(
    user
      ? { name: user.name, role: user.role, employeeNo: user.employeeNo,
          station: lockedStation }
      : null,
  )
}, [user, lockedStation])

function signOut() {
  notifications.clear() // shared-terminal hygiene
  setNotifyActor(null)
  // …
}
```

## 3. NotificationCenter

```tsx
// src/components/NotificationCenter.tsx
import {
  Bell,
  BellOff,
  CircleCheck,
  Info,
  OctagonX,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { fmtAgo } from "@/lib/format" // "just now" / "5m ago" — see below
import {
  notifications,
  useNotifications,
  useUnreadCount,
  type NotificationLevel,
} from "@/lib/notifications"
import { cn, stagger } from "@/lib/utils"

const LEVEL: Record<
  NotificationLevel,
  { icon: typeof CircleCheck; color: string }
> = {
  success: { icon: CircleCheck, color: "text-emerald-500" },
  error: { icon: OctagonX, color: "text-rose-500" },
  warning: { icon: TriangleAlert, color: "text-amber-500" },
  info: { icon: Info, color: "text-sky-500" },
}

export function NotificationCenter() {
  const [open, setOpen] = useState(false)
  // Exit animation: keep the panel mounted while it slides out, then remove.
  const [closing, setClosing] = useState(false)
  const { items } = useNotifications()
  const unread = useUnreadCount()

  const close = () => {
    if (closing) return
    setClosing(true)
    window.setTimeout(() => {
      setOpen(false)
      setClosing(false)
    }, 200)
  }

  // Mark everything read as soon as the panel opens (closing paths are many;
  // opening is one).
  useEffect(() => {
    if (open) notifications.markAllRead()
  }, [open])

  // Esc closes the panel.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  return (
    <>
      {/* Floating bell — bottom-right, clear of the top-right toasts. */}
      {!open && (
        <button
          type="button"
          aria-label={`Notifications${unread > 0 ? ` (${unread} unread)` : ""}`}
          onClick={() => setOpen(true)}
          className="fixed right-5 bottom-5 z-40 grid size-12 place-items-center rounded-full border bg-card text-foreground shadow-lg transition-transform hover:scale-105 active:scale-95"
        >
          <Bell className="size-5" />
          {unread > 0 && (
            // key={unread}: re-mount per count change so the pop replays.
            <span
              key={unread}
              className="anim-pop absolute -top-1 -right-1 grid min-w-5 place-items-center rounded-full bg-rose-500 px-1 font-mono text-[11px] font-semibold text-white"
            >
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </button>
      )}

      {/* Slide-over history panel. */}
      {open && (
        <>
          <div
            className={cn(
              "fixed inset-0 z-40 bg-black/40 backdrop-blur-[1px]",
              closing ? "nc-overlay-out" : "nc-overlay-in",
            )}
            onClick={close}
          />
          <aside
            role="dialog"
            aria-label="Notifications"
            className={cn(
              "fixed inset-y-0 right-0 z-50 flex w-[22rem] max-w-full flex-col border-l bg-card shadow-xl",
              closing ? "nc-panel-out" : "nc-panel-in",
            )}
          >
            <div className="flex items-center gap-2 border-b px-4 py-3">
              <Bell className="size-4" />
              <span className="text-sm font-semibold">Notifications</span>
              {items.length > 0 && (
                <span className="font-mono text-xs text-muted-foreground">
                  {items.length}
                </span>
              )}
              <div className="ml-auto flex items-center gap-1">
                {items.length > 0 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    onClick={() => notifications.clear()}
                  >
                    <Trash2 className="size-3.5" /> Clear
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Close notifications"
                  onClick={close}
                >
                  <X className="size-4" />
                </Button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto">
              {items.length === 0 ? (
                <div className="grid h-full place-items-center gap-2 px-6 text-center text-muted-foreground">
                  <BellOff className="size-6" />
                  <p className="text-sm">No notifications yet.</p>
                </div>
              ) : (
                <ul className="stagger divide-y">
                  {items.map((n, i) => {
                    const { icon: Icon, color } = LEVEL[n.level]
                    return (
                      <li
                        key={n.id}
                        style={stagger(i)}
                        className="flex gap-3 px-4 py-3"
                      >
                        <Icon className={cn("mt-0.5 size-4 shrink-0", color)} />
                        <div className="min-w-0 flex-1">
                          <p className="text-sm break-words">{n.title}</p>
                          {n.description && (
                            <p className="mt-0.5 text-xs break-words text-muted-foreground">
                              {n.description}
                            </p>
                          )}
                          <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                            {fmtAgo(n.ts)}
                          </p>
                        </div>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>

            <div className="border-t px-4 py-2 text-center font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
              Last 20 events
            </div>
          </aside>
        </>
      )}
    </>
  )
}
```

## Supporting bits

```ts
// src/lib/utils.ts
/** Inline `--i` consumed by the `.stagger` utility: children cascade in. */
export function stagger(i: number): CSSProperties {
  return { "--i": i } as CSSProperties
}

/** Coarse relative time ("just now", "5m ago", "2h ago", "3d ago"). */
export function fmtAgo(ts: number): string {
  const s = Math.floor((Date.now() - ts) / 1000)
  if (s < 60) return "just now"
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}
```

```css
/* index.css — panel + badge animations */
@keyframes fade-in-soft {
  from { opacity: 0; }
  to   { opacity: 1; }
}
@keyframes pop-in {
  0%   { opacity: 0; transform: scale(0.5); }
  60%  { opacity: 1; transform: scale(1.08); }
  100% { opacity: 1; transform: scale(1); }
}
@keyframes panel-in-right {
  from { transform: translateX(100%); }
  to   { transform: none; }
}
@keyframes panel-out-right {
  from { transform: none; }
  to   { transform: translateX(100%); }
}
@keyframes rise-in {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: none; }
}

:root {
  --ease-out-swift: cubic-bezier(0.16, 1, 0.3, 1);
  --dur-enter: 350ms;
}

.anim-pop { animation: pop-in 400ms var(--ease-out-swift) both; }

/* Children cascade in; set `--i` inline per child (see stagger() helper). */
.stagger > * {
  animation: rise-in var(--dur-enter) var(--ease-out-swift) both;
  animation-delay: calc(min(var(--i, 0), 10) * 45ms);
}

.nc-overlay-in  { animation: fade-in-soft 200ms ease-out both; }
.nc-overlay-out { animation: fade-in-soft 200ms ease-in reverse both; }
.nc-panel-in    { animation: panel-in-right 300ms var(--ease-out-swift) both; }
.nc-panel-out   { animation: panel-out-right 200ms ease-in both; }

/* Kiosk / shop-floor PCs often run with OS animations off. */
@media (prefers-reduced-motion: reduce) {
  .anim-pop, .stagger > *,
  .nc-overlay-in, .nc-overlay-out, .nc-panel-in, .nc-panel-out {
    animation: none;
  }
}
```
