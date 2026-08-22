---
name: keyboard-first-hotkeys
description: Keyboard-first interaction system for a kiosk / scan-gun / operator-terminal React app — one hotkey catalogue that drives the bindings, the key-cap hints on buttons, and the cheatsheet dialog so they can never drift; a focus chain that always keeps focus on "the next thing the operator will touch"; and a focus guard that recovers focus when re-renders drop it. Use when adding keyboard shortcuts / hotkeys to a React app, building a scan-gun or barcode-scanner driven UI, a kiosk where the workflow is Enter-to-advance, a shortcuts cheatsheet ("press ? to see shortcuts"), or when focus keeps getting lost after re-renders / socket updates and scans go nowhere.
---

# Keyboard-First Hotkeys

Harvested from a production shop-floor kiosk worked with a barcode scan gun.
Proven on React 19 · shadcn/ui (Radix Dialog/Select) · a Windows floor kiosk
and macOS dev machines. Nothing here needs the scan gun — the same system
carries any keyboard-first app; the gun is just the harshest test of it.

## The threat model (why the design is what it is)

A scan gun is a keyboard: it types its payload into whatever has focus and
ends with Enter. Two failure modes drive everything:

- **Misfire** — focus sits on a button, a scan arrives, its letters land as
  bare keypresses and trigger single-letter shortcuts. Cure: every shortcut
  takes **Alt**, so a stray scan can never fire one and no "is the user
  typing?" guard is needed anywhere.
- **Focus adrift** — a re-render (socket event, poll, an action disabling the
  field it was fired from) removes the focused element; the browser drops
  focus to `<body>`, and from there a scan goes nowhere and Enter does
  nothing. Cure: a **focus chain** (one selector defining "the next thing")
  plus a **focus guard** that only acts when focus is genuinely adrift.

## Moving parts

1. **`HOTKEYS` catalogue** (`lib/hotkeys.ts`) — one `Record<id, HotkeySpec>`
   (`code`, `label`, `description`, `scope`). Bindings, `<Kbd>` hints, and
   the cheatsheet all read from it, so they cannot disagree.
2. **`useHotkey(id, handler, {enabled, inModal})`** — binds a catalogued
   chord while the calling component is mounted; mounting is the scoping.
   Plus `useQueuePickHotkeys` for `Alt+1…9` → pick(0…8) list selection.
3. **Focus chain** (`lib/focus.ts`) — `FOCUSABLE` selector (single definition
   of "next thing"), `focusFirstIn`, `focusNextIn`, `focusIsAdrift`,
   `focusIsInside`, `pressPrimary` (fires the one enabled `[data-primary]`
   button, wherever focus is).
4. **`useFocusGuard(target, deps)`** — refocuses `target` after the renders
   named in `deps`, only when focus is adrift.
5. **`<Kbd>`** — key-cap chip printed on the buttons themselves, so the
   keyboard path is discoverable from the bench, not from training.
6. **`ShortcutsDialog`** — cheatsheet rendered *from the catalogue*, grouped
   by scope, opened by its own hotkey and via `openShortcuts()` (a window
   event, so no context/store for one dialog).

## Workflow

1. Read `REFERENCE.md` — building blocks numbered as above.
2. Define the app's catalogue: id → `{code, label, description, scope}`.
   Scopes are the app's screens/modes; the cheatsheet groups by them.
3. Drop in `useHotkey` + the modal guard; bind in the component that owns
   each action (mount = scope), `enabled:` for conditional ones.
4. Adapt `FOCUSABLE` to the app's widgets (extension point: which elements
   count as "the next thing"; keep checkboxes and opt-outs excluded).
5. Wire the chain: autofocus effects call `focusFirstIn` guarded by
   `focusIsAdrift() || focusIsInside(card)`; picked dropdowns hand off via
   `requestAnimationFrame(() => focusNextIn(...))`; mount `useFocusGuard` in
   each screen for the places nothing else claims.
6. Mount `ShortcutsDialog` once in the app shell; print `<Kbd>` hints on the
   most-hit buttons; link the cheatsheet from a menu too — an operator who
   doesn't know shortcuts exist can't guess the one that lists them.
7. Verify on both platforms: macOS (Option mangling) and Windows (kiosk).

## Pitfalls (each already paid for once)

- **Match on `event.code`, never `event.key`** — on macOS Alt is Option and
  `key` arrives pre-mangled (Option+Q → "œ"). `code` ("KeyQ") is stable.
- **Always `preventDefault()` on a match** — it's also what stops macOS
  inserting the Option character into a focused text field.
- **Plain Alt only**: require `altKey && !ctrlKey && !metaKey && !repeat`, so
  browser/OS chords (Ctrl+Alt, Cmd+Alt, AltGr) pass through untouched.
- **Keep letters off Firefox's menu mnemonics** (F E V H B T) — Alt+those
  open browser menus on Windows.
- **Window listeners pierce dialogs.** Without a `modalIsOpen()` guard an
  Alt chord reaches past an open dialog and acts on the screen behind it.
  Detect via the dialog's DOM marker (`[data-slot="dialog-content"]` for
  shadcn). The cheatsheet itself opts in with `inModal: true` so the chord
  that opened it can close it.
- **No dep array on the `useHotkey` effect — on purpose.** The handler is a
  fresh closure over current state every render; re-attaching one listener
  is cheaper than making every call site memoize correctly.
- **The guard must never steal focus the user placed deliberately** — act
  only when `focusIsAdrift()`, and re-check inside a `requestAnimationFrame`:
  Radix restores focus asynchronously on unmount and should win.
- **"Focus pass-through" places count as adrift.** A hidden print iframe (or
  similar) gets focused on the way to a browser dialog; treated as a real
  focus position, the Enter chain stalls there. Mark such elements with an
  attribute and include them in `focusIsAdrift`.
- **One selector, shared.** The autofocus effect and the focus guard must
  read the same `FOCUSABLE` definition or they fight over where focus goes.
- **`data-skip-autofocus`** opts an element out when DOM order and workflow
  order disagree (buttons above the field the scan belongs in).
- **`pressPrimary` works by invariant**: every primary action button carries
  `[data-primary]` and app gating guarantees at most one is enabled — finding
  it by attribute beats threading refs through every card. Keep the
  invariant or the shortcut fires the wrong action.
- **Dropdown hand-off is deferred**: after a pick, queue `focusNextIn` behind
  `requestAnimationFrame` — behind Radix's focus-restore to the trigger *and*
  the re-render that may have just disabled the next field, so a Pass lands
  on the confirm button and a Fail lands on the now-enabled detail field.
