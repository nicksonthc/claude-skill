# console-app-shell — building blocks

Genericized from the source project. `@/` is a Vite alias to `src/`; `Card`,
`Dialog*`, `Popover*` and `Button` are shadcn/ui (Radix); `cn` is shadcn's
class merger; routing is react-router 7. Storage keys are namespaced `app.*` —
use your app's prefix. Sections are numbered to match SKILL.md's "Moving parts".

---

## 1. One nav registry — `AppShell.tsx`

```tsx
import type { LucideIcon } from "lucide-react"
import type { Role } from "@/lib/types" // extension point

type Gate = {
  adminOnly?: boolean
  /** Only these roles see it (the page guards itself too — this is courtesy). */
  roles?: Role[]
}

/** One item inside a group: an app page (`to`), or an action (`action`) — e.g.
 *  a guided tour that runs over whatever page is open. */
type NavChild = Gate & { label: string; icon: LucideIcon } & (
    | { to: string; action?: never }
    | { action: "tour"; to?: never }
  )

type NavEntry = Gate & {
  /** The route — or, for a group, just its key in the saved nav order. */
  to: string
  label: string
  icon: LucideIcon
  end: boolean
  /** Shows a live count (e.g. open tickets). */
  badge?: boolean
  /** The entry becomes a collapsible group of these. */
  children?: NavChild[]
}

function canSee(user: { role: Role } | null, item: Gate): boolean {
  return (
    (!item.adminOnly || user?.role === "admin") &&
    (!item.roles || (!!user && item.roles.includes(user.role)))
  )
}

const MANAGERS: Role[] = ["supervisor", "admin"]

const NAV: NavEntry[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/work", label: "Workstation", icon: ScanLine, end: false },
  { to: "/queue", label: "Quarantine", icon: Wrench, end: false, badge: true },
  { to: "/orders", label: "Orders", icon: Boxes, end: false },
  { to: "/reports", label: "Reports", icon: FileText, end: false },
  {
    to: "/manage",
    label: "Management",
    icon: ChartNoAxesCombined,
    end: false,
    roles: MANAGERS,
    // Fed by the hub registry (§4): the sidebar and the page read one list.
    children: HUB_ITEMS.map((m) => ({ to: `/manage/${m.slug}`, label: m.title, icon: m.icon, adminOnly: m.adminOnly })),
  },
  { to: "/users", label: "Users", icon: Users, end: false, adminOnly: true },
  {
    // Not a route — the group's key in the saved nav order.
    to: "/guide",
    label: "Guide",
    icon: BookMarked,
    end: false,
    children: [
      { to: "/guide/qa", label: "Q&A", icon: CircleQuestionMark },
      { action: "tour", label: "Guided tour", icon: Compass },
      { to: "/changelog", label: "Changelog", icon: History, adminOnly: true },
    ],
  },
]

type NavItem = (typeof NAV)[number]

/** NAV in this terminal's saved order (§2), minus what this role cannot open. */
function useOrderedNav(): { all: NavItem[]; visible: NavItem[] } {
  const { user } = useAuth()
  const order = useNavOrder()
  const all = applyNavOrder(NAV, order)
  return {
    all,
    // The entries themselves, not copies — the reorder mode matches on
    // identity. A group's children are filtered where they are drawn, and a
    // group with none left for this role is hidden.
    visible: all.filter((n) => canSee(user, n) && (!n.children || n.children.some((c) => canSee(user, c)))),
  }
}
```

The shell renders the registry three ways: the desktop sidebar (groups
fold), the phone header strip (groups flatten), and the reorder list (§2).

---

## 2. Per-terminal page order — `lib/navOrder.ts` + reorder mode

```ts
import { useSyncExternalStore } from "react"

/**
 * The sidebar's page order, as this terminal's user arranged it — a
 * localStorage-backed store. Per browser, not per account: it describes how
 * *this* console is laid out.
 *
 * Stored as the route paths in order. Applying it is forgiving both ways: a
 * stored path that no longer exists is ignored, and a page added after the
 * order was saved keeps its default place relative to its neighbours (it is
 * appended after the stored ones in default order), so a release never hides
 * a new page.
 */
const KEY = "app.ui.navOrder"

function load(): string[] | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const parsed: unknown = JSON.parse(raw)
      if (Array.isArray(parsed) && parsed.every((p) => typeof p === "string")) return parsed
    }
  } catch {
    // malformed / unavailable storage — fall through to the default order
  }
  return null
}

let state: string[] | null = load()
const listeners = new Set<() => void>()

function setState(next: string[] | null): void {
  state = next
  try {
    if (next) localStorage.setItem(KEY, JSON.stringify(next))
    else localStorage.removeItem(KEY)
  } catch {
    // storage full/disabled — the order still applies for this session
  }
  listeners.forEach((l) => l())
}

export const navOrder = {
  subscribe(listener: () => void): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
  snapshot: (): string[] | null => state,
  set: (paths: string[]): void => setState(paths),
  /** Back to the order the app ships with. */
  reset: (): void => setState(null),
}

/** The saved order, or null when this terminal uses the default. */
export function useNavOrder(): string[] | null {
  return useSyncExternalStore(navOrder.subscribe, navOrder.snapshot)
}

/** `items` re-sorted by the saved order; unknown/new items keep default order
 *  after the saved ones. */
export function applyNavOrder<T extends { to: string }>(items: T[], order: string[] | null): T[] {
  if (!order) return items
  const rank = new Map(order.map((p, i) => [p, i]))
  return items
    .map((item, i) => ({ item, i }))
    .sort((a, b) => (rank.get(a.item.to) ?? order.length + a.i) - (rank.get(b.item.to) ?? order.length + b.i))
    .map(({ item }) => item)
}
```

```tsx
/**
 * The sidebar in "Reorder" mode: the pages become a drag-and-drop list (with
 * up/down buttons for keyboard and touch). Every move is saved at once, so
 * "Done" only leaves the mode. Links are not rendered here, so a drag can never
 * turn into a navigation.
 */
function NavReorder() {
  const { all, visible } = useOrderedNav()
  const [dragging, setDragging] = useState<string | null>(null)

  /** Persist a new order of the visible pages. Pages this role cannot see
   *  keep their place after them, so an operator's reorder never shuffles an
   *  admin's view of the same terminal into nonsense. */
  function save(next: NavItem[]) {
    const hidden = all.filter((n) => !next.includes(n))
    navOrder.set([...next, ...hidden].map((n) => n.to))
  }

  function move(from: number, to: number) {
    if (to < 0 || to >= visible.length || from === to) return
    const next = [...visible]
    const [item] = next.splice(from, 1)
    next.splice(to, 0, item)
    save(next)
  }

  return (
    <ul className="space-y-1" aria-label="Reorder pages">
      {visible.map(({ to, label, icon: Icon }, i) => (
        <li
          key={to}
          draggable
          onDragStart={(e) => {
            setDragging(to)
            e.dataTransfer.effectAllowed = "move"
            e.dataTransfer.setData("text/plain", to)
          }}
          onDragOver={(e) => {
            e.preventDefault()
            if (!dragging || dragging === to) return
            // Live reorder: the dragged page slides into the slot under the
            // pointer, so what you see on drop is what gets saved.
            move(visible.findIndex((n) => n.to === dragging), i)
          }}
          onDrop={(e) => e.preventDefault()}
          onDragEnd={() => setDragging(null)}
          className={cn(
            "flex cursor-grab items-center gap-2 rounded-md border border-dashed px-2 py-1.5 text-sm font-medium active:cursor-grabbing",
            dragging === to ? "border-emerald-500/60 bg-emerald-500/10 text-foreground" : "bg-background text-muted-foreground",
          )}
        >
          <GripVertical className="size-4 shrink-0 opacity-60" />
          <Icon className="size-4 shrink-0" />
          <span className="flex-1 truncate">{label}</span>
          <button type="button" aria-label={`Move ${label} up`} disabled={i === 0} onClick={() => move(i, i - 1)} className="rounded p-0.5 hover:bg-secondary disabled:opacity-25">
            <ArrowUp className="size-3.5" />
          </button>
          <button type="button" aria-label={`Move ${label} down`} disabled={i === visible.length - 1} onClick={() => move(i, i + 1)} className="rounded p-0.5 hover:bg-secondary disabled:opacity-25">
            <ArrowDown className="size-3.5" />
          </button>
        </li>
      ))}
    </ul>
  )
}
```

In the shell: a small "Reorder / Done" toggle above the nav (its title says
"saved on this terminal"), a "Reset" button while reordering and an order is
saved, and Escape leaves the mode:

```tsx
const [reordering, setReordering] = useState(false)
const savedOrder = useNavOrder()
// Esc leaves reorder mode — the order is already saved on every move.
useEffect(() => {
  if (!reordering) return
  const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setReordering(false) }
  window.addEventListener("keydown", onKey)
  return () => window.removeEventListener("keydown", onKey)
}, [reordering])

<nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
  <div className="flex items-center justify-between px-3 pb-1">
    <span className="text-[10px] tracking-widest text-muted-foreground uppercase">{reordering ? "Drag to reorder" : "Pages"}</span>
    {reordering && savedOrder && <button type="button" onClick={() => navOrder.reset()}>Reset</button>}
    <button type="button" aria-pressed={reordering} title={reordering ? "Finish reordering" : "Reorder the pages in this sidebar (saved on this terminal)"} onClick={() => setReordering((r) => !r)}>
      {reordering ? "Done" : "Reorder"}
    </button>
  </div>
  {reordering ? <NavReorder /> : <NavItems />}
</nav>
```

---

## 3. Collapsible groups, phone strip

```tsx
const GROUP_KEY = "app.ui.navGroup"

/** Whether this terminal last left a group open; null = never toggled. */
function storedOpen(to: string): boolean | null {
  try {
    const v = localStorage.getItem(`${GROUP_KEY}.${to}`)
    return v === null ? null : v === "1"
  } catch {
    return null
  }
}

/**
 * A page with sub-pages: a header row that folds the sub-pages in and out, and
 * the sub-pages indented under a guide line. Open by default; a fold is
 * remembered per terminal, and the group re-opens by itself whenever one of its
 * sub-pages is the current route, so the active item never hides.
 */
function NavGroup({ entry }: { entry: NavEntry }) {
  const { pathname } = useLocation()
  const { user } = useAuth()
  const children = (entry.children ?? []).filter((c) => canSee(user, c))
  const under = (to: string) => pathname === to || pathname.startsWith(`${to}/`)
  const inside = under(entry.to) || children.some((c) => !!c.to && under(c.to))
  // Open until this terminal folds it — the sub-pages are the point of it.
  const [open, setOpen] = useState(() => storedOpen(entry.to) ?? true)
  useEffect(() => {
    if (inside) setOpen(true)
  }, [inside])

  function toggle() {
    setOpen((o) => {
      try {
        localStorage.setItem(`${GROUP_KEY}.${entry.to}`, o ? "0" : "1")
      } catch {
        // storage unavailable — the group still folds for this session
      }
      return !o
    })
  }

  const Icon = entry.icon
  const listId = `nav-group-${entry.to.replace(/\W+/g, "")}`
  return (
    // A stable anchor per group (a guided tour points at nav-guide, nav-manage).
    <div data-tour={`nav-${entry.to.replace(/\W+/g, "")}`}>
      <button type="button" aria-expanded={open} aria-controls={listId} onClick={toggle}
        className={cn("flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium", inside ? "text-foreground" : "text-muted-foreground hover:bg-secondary/60")}>
        <Icon className="size-4 shrink-0" />
        <span className="flex-1 text-left">{entry.label}</span>
        <ChevronRight className={cn("size-4 shrink-0 text-muted-foreground transition-transform duration-200", open && "rotate-90")} />
      </button>
      {/* Grid-rows 0fr → 1fr animates the fold without measuring heights. */}
      <div id={listId} className={cn("grid transition-[grid-template-rows] duration-200 ease-out", open ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
        <div className="overflow-hidden">
          <div className="relative mt-0.5 space-y-0.5 before:absolute before:top-1 before:bottom-1 before:left-[21px] before:w-px before:bg-border">
            {children.map((c) => <ChildRow key={c.to ?? c.action} c={c} sub />)}
          </div>
        </div>
      </div>
    </div>
  )
}

/** One child of a group, whichever kind it is. */
function ChildRow({ c, sub = false }: { c: NavChild; sub?: boolean }) {
  const { openLauncher } = useTour() // the action's handler (guided-product-tour)
  if (c.action) return <ActionRow label={c.label} icon={c.icon} onClick={openLauncher} sub={sub} />
  return <NavRow to={c.to!} end={false} label={c.label} icon={c.icon} sub={sub} />
}

function NavItems({ strip = false }: {
  /** The phone header strip: one row, no room to fold — a group's sub-pages
   *  become plain items. */
  strip?: boolean
}) {
  const { visible: items } = useOrderedNav()
  const { user } = useAuth()
  return (
    <>
      {items.map((entry) =>
        entry.children?.length ? (
          strip
            ? entry.children.filter((c) => canSee(user, c)).map((c) => <ChildRow key={c.to ?? c.action} c={c} />)
            : <NavGroup key={entry.to} entry={entry} />
        ) : (
          <NavRow key={entry.to} to={entry.to} end={entry.end} label={entry.label} icon={entry.icon}>
            {/* live badges here: a count, the terminal's locked position (§7) */}
          </NavRow>
        ),
      )}
    </>
  )
}
```

`NavRow` is a `NavLink` with the "you are here" indicator from
`ui-motion-system` §9. Desktop: a sticky `w-64` aside with the brand, the nav,
a status row (`system-status-popover`) and the account menu (§5) at the
bottom. Phone (`lg:hidden`): a sticky header with the brand, status dot and a
compact account button, then a horizontally scrolling `NavItems strip`.

---

## 4. Hub pages from a registry — `lib/hub.ts`, `HubPage.tsx`

```ts
import type { LucideIcon } from "lucide-react"
import type { Role } from "@/lib/types"

/** Who sees the hub — the backend gates its endpoints the same. */
export const HUB_ROLES: ReadonlySet<Role> = new Set(["supervisor", "admin"])

export interface HubItem {
  /** `/manage/:slug` — keep stable, it is what a bookmark holds. */
  slug: string
  title: string
  icon: LucideIcon
  /** The page subtitle: what this page answers, in one or two sentences. */
  subtitle: string
  /** Admins only, inside a hub supervisors also see (backend gates it too). */
  adminOnly?: boolean
}

/**
 * The hub's pages, in sidebar order. The sidebar's sub-items and the page both
 * read this list; a new page is one entry here plus its body in HubPage.
 */
export const HUB_ITEMS: HubItem[] = [
  { slug: "performance", title: "Line performance", icon: Timer, subtitle: "…" },
  { slug: "deletions", title: "Deletion log", icon: Trash2, subtitle: "…" },
  { slug: "system-log", title: "System Log", icon: ScrollText, subtitle: "…", adminOnly: true },
]
```

```tsx
/** What each hub page renders, by its slug. */
const BODIES: Record<string, () => ReactNode> = {
  performance: () => <PerformanceTab />,
  deletions: () => <DeletionLogTab />,
  "system-log": () => <SystemLogTab />,
}

export function HubPage() {
  const { slug } = useParams()
  const { user } = useAuth()
  const item = HUB_ITEMS.find((m) => m.slug === slug)

  // A typed URL to a page this role can't open gets a lock card — the page
  // guards itself; the sidebar hiding it is only a courtesy.
  if (!user || !HUB_ROLES.has(user.role)) return <Locked title="Management" what="Management pages are available to supervisors and admins only." />
  if (!item) return <Navigate to={`/manage/${HUB_ITEMS[0].slug}`} replace />
  if (item.adminOnly && user.role !== "admin") return <Locked title={item.title} what={`${item.title} is available to admins only.`} />

  return (
    <>
      <PageHeader title={item.title} subtitle={item.subtitle} />
      <div key={item.slug} className="anim-rise">{BODIES[item.slug]()}</div>
    </>
  )
}

/**
 * `/manage` and the addresses these pages had before they got their own
 * sub-pages (`/manage?report=…`, `/errors`, …) land on the matching
 * `/manage/:slug`, keeping the rest of the query.
 */
export function HubRedirect({ to }: { to?: string }) {
  const [params] = useSearchParams()
  const next = new URLSearchParams(params)
  const slug = to ?? HUB_ITEMS.find((m) => m.slug === params.get("report"))?.slug ?? HUB_ITEMS[0].slug
  next.delete("report")
  const query = next.toString()
  return <Navigate to={`/manage/${slug}${query ? `?${query}` : ""}`} replace />
}

// Routes
<Route path="/manage" element={<HubRedirect />} />
<Route path="/manage/:slug" element={<HubPage />} />
<Route path="/errors" element={<HubRedirect to="system-log" />} /> {/* an old address */}
```

---

## 5. Account menu — hover intent, click-only on touch

```tsx
// Hover intent: long enough that crossing the row on the way to the nav
// doesn't flash the menu open, short enough to feel instant when aimed at.
const OPEN_DELAY_MS = 140
const CLOSE_DELAY_MS = 240

export function AccountMenu({ compact = false }: { compact?: boolean }) {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const timers = useRef<{ open?: number; close?: number }>({})
  const hoverOpened = useRef(false)

  const clearTimers = () => {
    window.clearTimeout(timers.current.open)
    window.clearTimeout(timers.current.close)
    timers.current = {}
  }
  useEffect(() => clearTimers, [])

  // Touch input gets click-only behaviour — a kiosk finger has no "hover".
  const isMouse = (e: React.PointerEvent) => e.pointerType === "mouse"
  const hoverIn = (e: React.PointerEvent) => {
    if (!isMouse(e)) return
    window.clearTimeout(timers.current.close)
    if (open) return
    timers.current.open = window.setTimeout(() => { hoverOpened.current = true; setOpen(true) }, OPEN_DELAY_MS)
  }
  const hoverOut = (e: React.PointerEvent) => {
    if (!isMouse(e)) return
    window.clearTimeout(timers.current.open)
    timers.current.close = window.setTimeout(() => setOpen(false), CLOSE_DELAY_MS)
  }

  const handleLogout = () => {
    // A shared kiosk: wipe this session's local history (notifications,
    // drafts) on sign-out, so the next person doesn't inherit it.
    clearSessionArtifacts()
    void logout()
  }

  return (
    <Popover open={open} onOpenChange={(next) => { clearTimers(); if (!next) hoverOpened.current = false; setOpen(next) }}>
      <PopoverTrigger asChild>
        <button type="button" onPointerEnter={hoverIn} onPointerLeave={hoverOut} aria-label={`Account menu for ${user?.name ?? ""}`}>
          {/* avatar (initials) · name · role · ⋯ */}
        </button>
      </PopoverTrigger>
      <PopoverContent
        side={compact ? "bottom" : "right"}
        onPointerEnter={hoverIn}
        onPointerLeave={hoverOut}
        // A menu that opened itself on hover shouldn't steal the caret from
        // whatever the operator was typing; click/keyboard opens still focus.
        onOpenAutoFocus={(e) => { if (hoverOpened.current) e.preventDefault(); hoverOpened.current = false }}
      >
        {/* identity header (name, role, the terminal's locked position) */}
        {/* settings entries — shown by the SAME rule the backend uses to accept the write */}
        {/* tour · keyboard shortcuts · theme */}
        {/* sign out (destructive) */}
      </PopoverContent>
    </Popover>
  )
}
```

---

## 6. Settings

The two settings stores and the dialog live in [`SETTINGS.md`](SETTINGS.md) — only apps that add runtime-editable settings need them.

---

## 7. Terminal identity — the position a PC is locked to, per-screen views

```ts
// The work position this PC is "locked" to. Stored in localStorage so it
// survives reloads and binds the terminal to one physical place on the floor.
const KEY = "app.terminal.position"
const EVENT = "app-terminal-position-change"

const read = (): string | null => { try { return localStorage.getItem(KEY) } catch { return null } }

export function setLockedPosition(code: string | null) {
  try {
    if (code) localStorage.setItem(KEY, code)
    else localStorage.removeItem(KEY)
  } catch { /* locked-down kiosk profile */ }
  // `storage` fires only in OTHER tabs — this event tells this tab's components.
  window.dispatchEvent(new Event(EVENT))
}

/** Reactive read of the locked position (syncs across tabs + components). */
export function useLockedPosition(): string | null {
  const [code, setCode] = useState<string | null>(read)
  useEffect(() => {
    const sync = () => setCode(read())
    window.addEventListener(EVENT, sync)
    window.addEventListener("storage", sync)
    return () => { window.removeEventListener(EVENT, sync); window.removeEventListener("storage", sync) }
  }, [])
  return code
}
```

The shell shows the locked position as a badge on its nav item and in the
account menu, and announces it for live presence (`socketio-realtime-hooks`).

**A view choice is per screen.** When two screens can draw the same thing two
ways (a compact 2D drawing, a 3D scene), keep one preference per screen,
default to the one that always fits, and read anything but an explicit
opt-in as the default:

```ts
export type View = "2d" | "3d"
export type ViewScope = "picker" | "route" // the question each screen answers

const VIEW_KEY: Record<ViewScope, string> = { picker: "app.view.picker", route: "app.view.route" }
const readView = (s: ViewScope): View => {
  try { return localStorage.getItem(VIEW_KEY[s]) === "3d" ? "3d" : "2d" } // unset, stale or corrupt → 2d
  catch { return "2d" }
}
const views: Record<ViewScope, View> = { picker: readView("picker"), route: readView("route") }
const viewListeners = new Set<() => void>()

export function setView(scope: ViewScope, next: View): void {
  if (next === views[scope]) return
  views[scope] = next
  try { localStorage.setItem(VIEW_KEY[scope], next) } catch { /* the toggle still works this session */ }
  for (const l of viewListeners) l()
}
export const toggleView = (scope: ViewScope) => setView(scope, views[scope] === "3d" ? "2d" : "3d")
export function useView(scope: ViewScope): View {
  return useSyncExternalStore(
    (l) => { viewListeners.add(l); return () => viewListeners.delete(l) },
    () => views[scope],
    () => "2d" as View,
  )
}
```
