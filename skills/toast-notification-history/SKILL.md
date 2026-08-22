---
name: toast-notification-history
description: Toasts with an audit trail for a React app — a drop-in wrapper around sonner's toast that also records every notification into a capped, localStorage-backed history, stamps on WHO did it (the signed-in user) automatically, and shows the log in a floating-bell slide-over panel with an unread badge. Use when adding a notification center / notification history / bell icon to a React app, when toasts disappear before anyone reads them ("what did that error say?"), when a shared kiosk or multi-operator terminal needs actions attributed to a person, or when wiring toast notifications that must also be reviewable later.
---

# Toast Notification History

Harvested from a production shared-kiosk app. Proven on React 19 · sonner ·
Tailwind v4 · lucide icons. The motivating insight: on a shared terminal a
toast is testimony that vanishes — "it worked" is not enough; the record has
to say *what* it applied to and *who* did it, and still be there when the
next shift asks.

## Moving parts

1. **`notifications` store** (`lib/notifications.ts`) — a module-level store
   (not React context) exposed via `useSyncExternalStore`, so it is writable
   from non-component code (API flows, socket handlers). Capped list,
   persisted to localStorage, `lastSeenTs` watermark for unread counts.
2. **`notify` wrapper** (`lib/notify.ts`) — drop-in replacement for sonner's
   `toast` (success/error/warning/info). Shows the toast AND pushes it into
   the history. Call sites supply the *what* (`description`: the record id,
   station, batch…); the *who* is stamped on automatically from a
   module-level actor installed at sign-in.
3. **`NotificationCenter`** — floating bell (bottom corner, unread badge) →
   slide-over history panel: level icons, relative timestamps, staggered
   entry animation, mark-all-read on open, clear button.

## Workflow

1. Read `REFERENCE.md` — blocks numbered as above.
2. Drop in the store and wrapper; define the app's `NotifyActor` shape
   (extension point — name/role/terminal, whatever attribution means here).
3. App shell: `setNotifyActor(user)` on sign-in, `setNotifyActor(null)` AND
   `notifications.clear()` on sign-out — shared-terminal hygiene: the next
   user must not read the last user's history.
4. Migrate call sites with the import alias:
   `import { notify as toast } from "@/lib/notify"` — existing
   `toast.success(...)` call sites work unchanged.
5. Make descriptions carry the *what*: a bare "Saved" is useless in a log;
   "Saved · SN 12345 · ST3" is the point of having one.
6. Mount `NotificationCenter` once in the shell; keep sonner's `<Toaster>`
   where it was (they render independently).
7. For toasts reporting *someone else's* action (a socket event from another
   terminal), pass `self: false` and name the real actor in `description`.

## Principles

- **Module-level store, context-free.** Toasts fire from API wrappers and
  socket handlers, which live outside React; `useSyncExternalStore` gives
  components reactivity without making the store a component concern.
- **The history is a courtesy log, not a database.** Capped (20 in the
  source), localStorage-backed, cleared on logout. Anything that must
  survive belongs in the backend, not here.
- **Attribution is automatic or it won't happen.** No call site threads the
  user through — the actor is installed once and stamped on everything.
- **Unread is a watermark, not per-item state**: one `lastSeenTs`, unread =
  items newer than it. Mark-all-read = set it to the newest item's ts.

## Pitfalls (each already paid for once)

- **Wrap every localStorage read AND write in try/catch** — storage can be
  full, disabled, or hold malformed JSON from an old version. The store must
  degrade to in-memory, never crash the app for a notification.
- **Validate on load**: `Array.isArray(parsed.items)` and re-cap with
  `.slice(0, MAX)` — an older build's shape or a hand-edited value
  otherwise poisons every render.
- **`self: false` exists because the actor line lies otherwise** — a toast
  triggered by a socket event would credit the action to *this* terminal's
  signed-in user. Any toast not caused by a local action must opt out.
- **Merge, don't clobber, the description**: the call site's *what* and the
  stamped *who* are joined (`"…" · "…"`), so neither hides the other.
- **Unique ids need a sequence**: two pushes in the same millisecond collide
  on `Date.now()` alone — suffix a module counter (`${Date.now()}-${++seq}`).
- **Exit animation needs a `closing` state** — unmounting on close kills the
  slide-out mid-frame; keep the panel mounted, swap to the `-out` animation
  class, remove after the duration.
- **`key={unread}` on the badge** re-mounts it per count change so the pop
  animation replays — without it the number changes silently.
- **Place the bell away from the toasts** (bell bottom-right, toasts
  top-right in the source) or the live toast covers the entry point to its
  own history.
- **Mark-all-read on open, not on close** — closing paths are many (Esc,
  overlay click, X, navigation); opening is one.
- **Reduced motion**: the panel/overlay/stagger animations must all be under
  `prefers-reduced-motion: reduce` — kiosk PCs often have animations off.
