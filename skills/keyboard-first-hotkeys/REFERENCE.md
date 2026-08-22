# keyboard-first-hotkeys — building blocks

Genericized from the source project. `@/` is a Vite alias to `src/`; `cn` is
clsx+tailwind-merge; Dialog is shadcn/ui — swap for the target's primitives.
Sections numbered to match SKILL.md's "Moving parts".

## 1 + 2. Hotkey catalogue + `useHotkey`

```ts
// src/lib/hotkeys.ts
import { useEffect } from "react"

/**
 * The app's keyboard shortcuts — one catalogue, so the `<Kbd>` hints printed
 * on buttons and the cheatsheet dialog both read from the binding itself and
 * can never drift from it.
 *
 * ---- why every shortcut is Alt-modified -----------------------------------
 * A scan gun (or any auto-typing device) types its payload into whatever
 * element has focus and ends with Enter. Focus routinely sits on a *button*,
 * where bare letters would arrive as keypresses. Alt on every binding makes a
 * misfire impossible and means no "is the user typing?" guard is needed
 * anywhere.
 *
 * Two platform details fall out of that:
 *  - Matching is on `event.code` ("KeyQ"), never `event.key`: on macOS Alt is
 *    Option and `key` is already the mangled character (Option+Q -> "œ").
 *  - A match always calls `preventDefault()`, which is what stops that same
 *    character being inserted when focus is in a text field.
 *
 * Letters are also kept off Firefox's menu mnemonics (F E V H B T).
 */

/** Where a shortcut applies — the cheatsheet groups by this.
 *  Rename the scopes to the app's own screens/modes. */
export type HotkeyScope = "main" | "list" | "detail" | "global"

export interface HotkeySpec {
  /** `event.code` of the key, pressed with Alt. */
  code: string
  /** Rendered in `<Kbd>` and the cheatsheet, e.g. "Alt K". */
  label: string
  /** What it does, in the user's words. */
  description: string
  scope: HotkeyScope
}

export const SCOPE_LABEL: Record<HotkeyScope, string> = {
  global: "Anywhere",
  main: "Main screen",
  list: "In the list",
  detail: "In a record",
}

// ── The catalogue. Example entries — replace with the app's own. ──────────
export const HOTKEYS = {
  focusScan: {
    code: "KeyK",
    label: "Alt K",
    description: "Jump to the input, ready to scan",
    scope: "main",
  },
  primaryAction: {
    code: "Enter",
    label: "Alt ⏎",
    description: "Fire the primary action — whichever is next",
    scope: "detail",
  },
  shortcuts: {
    code: "Slash",
    label: "Alt /",
    description: "Show this list",
    scope: "global",
  },
} as const satisfies Record<string, HotkeySpec>

export type HotkeyId = keyof typeof HOTKEYS

/** `Alt+1`…`Alt+9` open the Nth item — listed once, not nine times. */
export const LIST_PICK_HINT: HotkeySpec = {
  code: "Digit1",
  label: "Alt 1…9",
  description: "Open the 1st…9th item in the list",
  scope: "list",
}

/** True when `e` is this terminal's Alt chord for `code` — plain Alt only, so
 *  browser and OS chords (Ctrl+Alt, Cmd+Alt, AltGr) are left alone. */
function matches(e: KeyboardEvent, code: string): boolean {
  return e.altKey && !e.ctrlKey && !e.metaKey && !e.repeat && e.code === code
}

/**
 * True while a modal dialog is up.
 *
 * These listeners are on `window`, so without this an Alt chord would reach
 * straight past an open dialog and act on the screen behind it. A dialog is
 * modal, and that has to include the keyboard.
 * `[data-slot="dialog-content"]` is shadcn's marker — adapt to the target's
 * dialog primitive.
 */
function modalIsOpen(): boolean {
  return !!document.querySelector('[data-slot="dialog-content"]')
}

/**
 * Bind one catalogued shortcut for as long as the calling component is
 * mounted, which is what scopes it: a screen's keys exist only while that
 * screen is up. `enabled` turns a binding off without unmounting.
 */
export function useHotkey(
  id: HotkeyId,
  handler: () => void,
  {
    enabled = true,
    inModal = false,
  }: {
    enabled?: boolean
    /** Let this one through while a dialog is open. Only the cheatsheet needs
     *  it, so the same chord that opened it can close it again. */
    inModal?: boolean
  } = {},
): void {
  const { code } = HOTKEYS[id]
  useEffect(() => {
    if (!enabled) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (!matches(e, code)) return
      if (!inModal && modalIsOpen()) return
      // Also what stops macOS inserting the Option character into a field.
      e.preventDefault()
      handler()
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  })
  // No dep array on purpose: `handler` is a fresh closure over the screen's
  // current state every render, and re-attaching one listener is cheaper
  // than asking every call site to memoise.
}

/** `Alt+1`…`Alt+9` → `pick(0)`…`pick(8)`. Out-of-range picks are the
 *  caller's to ignore, since only it knows how long the list is. */
export function useListPickHotkeys(
  pick: (index: number) => void,
  { enabled = true }: { enabled?: boolean } = {},
): void {
  useEffect(() => {
    if (!enabled) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.metaKey || e.repeat) return
      if (modalIsOpen()) return
      const m = /^Digit([1-9])$/.exec(e.code)
      if (!m) return
      e.preventDefault()
      pick(Number(m[1]) - 1)
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  })
}
```

## 3. Focus chain

```ts
// src/lib/focus.ts
/**
 * Where the keyboard chain puts focus.
 *
 * The app is driven keyboard-first: as each part unlocks, focus is pulled
 * into the thing the user will touch next — the field a scanner fills in, or
 * the button that confirms a fieldless action. This selector is the single
 * definition of "next thing", shared by every autofocus effect and the focus
 * guard, so they can never disagree about what to focus.
 *
 * Checkboxes are excluded (they are options, never the main event), and
 * `data-skip-autofocus` opts an element out by hand — for when DOM order and
 * workflow order disagree.
 * `[data-slot="select-trigger"]` is shadcn's Select — adapt to the target.
 */
const FOCUSABLE = [
  'input:not([type="checkbox"]):not(:disabled)',
  "textarea:not(:disabled)",
  '[data-slot="select-trigger"]:not(:disabled)',
  "button:not(:disabled):not([data-skip-autofocus])",
].join(", ")

/** Marks elements focus only passes *through* (e.g. a hidden print iframe
 *  that must be focused for the browser's print dialog to target it). Never a
 *  place focus belongs — see focusIsAdrift. */
export const FOCUS_PASSTHROUGH_ATTR = "data-focus-passthrough"

/** The first thing worth typing into inside `container`, or null. */
export function firstFocusableIn(
  container: HTMLElement | null,
): HTMLElement | null {
  return container?.querySelector<HTMLElement>(FOCUSABLE) ?? null
}

/** Focus the first thing worth typing into inside `container`. */
export function focusFirstIn(container: HTMLElement | null): boolean {
  const target = firstFocusableIn(container)
  if (!target) return false
  target.focus()
  return true
}

/**
 * Move focus one step along inside `container`, from whatever holds it now.
 *
 * This is what a picked dropdown hands off to. Walking the DOM rather than
 * jumping straight to the confirm button matters when a pick just disabled
 * the fields between here and there: disabled stops simply aren't in the
 * list, so the next *live* stop gets the focus.
 */
export function focusNextIn(container: HTMLElement | null): boolean {
  if (!container) return false
  const stops = [...container.querySelectorAll<HTMLElement>(FOCUSABLE)]
  const here = stops.indexOf(document.activeElement as HTMLElement)
  const next = stops[here + 1]
  if (!next) return false
  next.focus()
  return true
}

/**
 * True when focus is nowhere the user put it — so it is ours to move.
 *
 * That is `<body>` (the browser's fallback once the focused element is
 * removed: a card re-rendering to a completed state, a dialog closing) and
 * any pass-through element, which arrives *between* one action and the next
 * unlock: read as a real focus position it looks deliberate, and the whole
 * Enter chain stalls there.
 */
export function focusIsAdrift(): boolean {
  const active = document.activeElement
  if (!active || active === document.body) return true
  return !!active.closest(`[${FOCUS_PASSTHROUGH_ATTR}]`)
}

/** True when focus is currently inside `container` — used to avoid stealing
 *  focus the user placed somewhere deliberately. */
export function focusIsInside(container: HTMLElement | null): boolean {
  const active = document.activeElement
  return !!container && !!active && container.contains(active)
}

/**
 * Fire the one action the screen is waiting on, wherever focus happens to be.
 *
 * Primary action buttons carry `data-primary`, and the app's own gating must
 * guarantee exactly one is enabled at any moment — then "the enabled one" is
 * unambiguous, and finding it by attribute beats threading a ref up through
 * every component.
 */
export function pressPrimary(container: HTMLElement | null): boolean {
  const button = container?.querySelector<HTMLElement>(
    "[data-primary]:not(:disabled)",
  )
  if (!button) return false
  button.click()
  return true
}
```

## 4. useFocusGuard

```ts
// src/hooks/useFocusGuard.ts
import { useEffect } from "react"
import { focusIsAdrift } from "@/lib/focus"

/**
 * Keeps the keyboard pointed at something.
 *
 * The screen re-renders under the user: a socket event, a poll landing, an
 * action disabling the field it was fired from. Whenever that removes or
 * disables the focused element, the browser drops focus to `<body>` — and
 * from there a scan goes nowhere and Enter does nothing.
 *
 * `target` names what should hold focus in that situation. The guard only
 * acts when focus is genuinely adrift, so it can never take focus away from
 * somewhere the user deliberately put it. Component-local autofocus effects
 * cover their own widgets; this covers the places nothing else claims.
 *
 * `deps` are the renders worth re-checking after.
 */
export function useFocusGuard(
  target: () => HTMLElement | null,
  deps: unknown[],
  { enabled = true }: { enabled?: boolean } = {},
): void {
  useEffect(() => {
    if (!enabled || !focusIsAdrift()) return
    // One frame's grace: React has committed, but Radix and friends restore
    // focus asynchronously as they unmount, and they should win.
    const id = requestAnimationFrame(() => {
      if (focusIsAdrift()) target()?.focus()
    })
    return () => cancelAnimationFrame(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, ...deps])
}
```

Call-site patterns from the source project:

```tsx
// Autofocus on unlock — never steal focus the user already placed elsewhere,
// but pass-through places don't count (see focusIsAdrift), or the chain
// would stall on every print step the moment the print frame takes focus.
useEffect(() => {
  if (!editable || !working) return
  if (!focusIsAdrift() && !focusIsInside(card)) return
  focusFirstIn(card)
}, [editable, working])

// Hand the keyboard chain on after a picked field (a dropdown, Yes/No),
// which has no Enter of its own — Enter on a select trigger reopens the
// list. Queued behind Radix's own focus restore to the trigger, and behind
// the re-render that disables the fields the pick just cleared.
const handOff = () =>
  requestAnimationFrame(() => {
    if (!focusNextIn(cardRef.current)) submitRef.current?.focus()
  })
```

## 5. Kbd

```tsx
// src/components/ui/kbd.tsx
import { cn } from "@/lib/utils"

/**
 * A key cap. Printed on the buttons the user hits most so the keyboard path
 * is visible from the screen rather than something you have to be told about.
 * `border-current/20 bg-current/10` inherits the button's own text color, so
 * one component works on any button variant.
 */
export function Kbd({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <kbd
      className={cn(
        "pointer-events-none inline-block select-none rounded border border-current/20 bg-current/10 px-1.5 py-0.5 font-mono text-[10px] leading-none tracking-wide opacity-70",
        className,
      )}
    >
      {children}
    </kbd>
  )
}
```

## 6. ShortcutsDialog

```tsx
// src/components/ShortcutsDialog.tsx
import { useEffect, useState } from "react"
import { Keyboard } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Kbd } from "@/components/ui/kbd"
import {
  HOTKEYS,
  LIST_PICK_HINT,
  SCOPE_LABEL,
  type HotkeyScope,
  type HotkeySpec,
  useHotkey,
} from "@/lib/hotkeys"

/**
 * The shortcut list, rendered from the `HOTKEYS` catalogue so it can never
 * disagree with what is actually bound.
 *
 * Mounted once by the app shell: its hotkey opens it from anywhere, and a
 * menu item opens it too — a user who doesn't know the shortcuts exist has
 * no way to guess the one that shows them.
 */

const EVENT = "app-open-shortcuts"

/** Open the cheatsheet from anywhere — a window event, so no context or
 *  store is needed for one dialog. */
export function openShortcuts(): void {
  window.dispatchEvent(new Event(EVENT))
}

const ORDER: HotkeyScope[] = ["main", "list", "detail", "global"]

export function ShortcutsDialog() {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const show = () => setOpen(true)
    window.addEventListener(EVENT, show)
    return () => window.removeEventListener(EVENT, show)
  }, [])

  // `inModal` so the chord that opened this can close it again.
  useHotkey("shortcuts", () => setOpen((o) => !o), { inModal: true })

  const all: HotkeySpec[] = [...Object.values(HOTKEYS), LIST_PICK_HINT]

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Keyboard className="size-4" /> Keyboard shortcuts
          </DialogTitle>
          <DialogDescription>
            {/* Say WHY the modifier exists, in the user's words — e.g. "every
                shortcut takes Alt so a stray scan can never trigger one". */}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {ORDER.map((scope) => {
            const rows = all.filter((h) => h.scope === scope)
            if (rows.length === 0) return null
            return (
              <div key={scope}>
                <div className="mb-2 font-mono text-[10px] tracking-widest text-muted-foreground uppercase">
                  {SCOPE_LABEL[scope]}
                </div>
                <div className="space-y-1.5">
                  {rows.map((h) => (
                    <div
                      key={h.label}
                      className="flex items-baseline justify-between gap-4"
                    >
                      <span className="text-sm">{h.description}</span>
                      <Kbd className="shrink-0">{h.label}</Kbd>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </DialogContent>
    </Dialog>
  )
}
```
