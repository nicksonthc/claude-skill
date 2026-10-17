---
name: guided-product-tour
description: Guided product tour for a React web app — a spotlight card walks the real screens stop by stop, navigating between pages and opening the menus, dialogs and settings panes it points at; stops are filtered to what the user's role can open, grouped into chapters picked from a launcher with per-terminal progress ticks, auto-run once on a fresh terminal, and the tour ends in a hands-on sandbox built from the app's real components where nothing is saved. Use when adding an onboarding or first-run tour, a guided tour / product walkthrough / tour guide of the whole app, a "Take the tour" menu item, per-role or per-chapter tours, a tour that must point inside a menu or dialog, or a safe practice mode that mirrors a real workflow.
---

# Guided Product Tour

Harvested from a production shop-floor app, where operators, supervisors and
admins each needed their own walk through the same console. Proven on React 19
· react-router 7 · Radix primitives via shadcn/ui · Tailwind v4 · TypeScript 5.8.

## The idea in one line

**The tour drives, and it only shows.** It navigates, opens UI and spotlights
the real control, and the layer is modal; nothing it touches changes data. The
hands-on part happens in a sandbox where nothing is saved. Its sibling
`smart-task-guide` is the other model: it waits for the user's own click on
the highlighted control. Pick by who advances — the card's Next button (this
skill) or the user's action (that one).

## Moving parts

1. **Script** (`tourSteps.ts`) — chapters `{id, title, blurb}` and stops
   `{id, chapter, title, body, route?, scene?, target?, placement?, roles?, finale?}`;
   `stepsFor(role, chapter?)` is the one filter. Anchors are `data-tour="…"`.
2. **Provider** — run state `{steps, index, chapter}`: navigates to a stop's
   route, publishes its scene, auto-starts once per terminal, and on finish
   marks progress, then opens the sandbox (after a finale) or the launcher
   (one chapter done → offer the next).
3. **Overlay** — a portal'd modal layer. The scrim is the spotlight's own
   200vmax box-shadow; the target is the first *visible* match, tracked every
   animation frame; the card takes the first side with room; keys are captured.
4. **Scenes** (`tourScene.ts`) — a tiny external store holding a string like
   `"account-menu"` or `"settings:line:shifts"`. The component that owns that
   UI opens it while its scene is current and closes it after — only what the
   tour opened. The dialog/popover primitives stay open while a scene is up.
5. **Launcher** — full tour (stop count, ~15 s a stop) or one chapter (only
   chapters this role has stops in), per-terminal ticks, "hands-on demo only".
   Opened from a Guide nav group and from the account menu.
6. **Sandbox finale** (`SANDBOX.md`) — the core workflow replicated in a
   dialog from the real components, driven by local state and typed fixtures,
   with a simulated input device (scan gun / keyboard wedge) and a coach line.
7. **Flow sandbox** (optional, `SANDBOX.md`) — a scripted walkthrough of a flow
   the real screens can't show (needs a second person, an outside directory, a
   fresh account): stage stepper, coach line, "Fill demo" buttons, a checklist
   revealed line by line in the backend's real order of checks.
8. **Guide hub** (optional) — framed static help pages beside the tour action.

## Workflow

1. **Inventory per role.** For every page, setting and dialog: its route, who
   can open it (frontend guard *and* backend gate), what must be open first.
   That table is the script.
2. **Write chapters and stops** (REFERENCE §1). A stop's `roles` copy the guard
   of what it shows; its body uses the words on the screen.
3. **Anchor** with `data-tour` attributes only. Generic anchors (`page`, `nav`)
   serve many stops; a table-column stop anchors row 0.
4. **Mount** the provider inside the router and auth boundary around the shell
   (§2), plus the overlay (§3) and the launcher with its two entry points (§5).
5. **Scenes** (§4): an owner effect for every stop inside a menu, dialog or
   settings section; `fromTourOverlay` wired into the dialog and popover
   primitives once. If the app has global hotkeys, add `[data-tour-overlay]`
   to their "modal open?" guard (§3) — a dialog-only selector misses the
   overlay (see `keyboard-first-hotkeys`).
6. **Sandbox** (`SANDBOX.md`) from the real components, with typed fixture
   builders; its own pitfalls sit at the top of that file.
7. **Make it a convention** in the repo's CLAUDE.md / PR checklist: a new page
   or setting gets a stop with the right `roles`; a stop inside a menu or
   dialog gets a scene and an anchor.
8. **Verify** (§9): walk every chapter as every role — the ring lands on each
   anchor, nothing skips by accident, every scene closes what it opened, and
   the sandbox sends zero requests.

## Principles

- **Real screens, not pictures.** Point at the live control and open the menu
  or dialog it lives in. A stale screenshot misleads quietly; a broken anchor
  skips loudly in the verify walk.
- **Role-honest.** A stop exists only for roles that can open what it shows;
  otherwise it points at a refusal.
- **Chapters for re-entry.** The whole tour once, automatically; later, the one
  chapter someone needs. Ticks show what this terminal has walked.
- **End with hands.** The finale puts the real components in the user's hands,
  then offers a button to the real page.
- **Per terminal on a kiosk** — the seen flag and ticks live in localStorage, so
  a shared terminal tours once; key them per user on personal devices.

## Pitfalls (each already paid for once)

- **An open Radix dialog sets `pointer-events: none` on `<body>`** — give the
  overlay root `pointer-events: auto`, or its buttons die over a dialog the
  tour opened.
- **Keys on the window's bubble phase reach a dialog first**: Enter submitted
  it, Escape closed it. Listen in the capture phase, `preventDefault` +
  `stopPropagation` the keys the tour owns, and swallow Tab.
- **Pressing Next is an outside click** for the dialog the tour opened, which
  would close it. `fromTourOverlay(e)` in `onInteractOutside` /
  `onEscapeKeyDown` keeps it open while a scene is set.
- **Hover-intent menus close** as the pointer travels to the card — hover
  handlers stand down while a scene is set.
- **The same menu is often mounted twice** (sidebar + phone header); only the
  visible one (`getClientRects().length > 0`) may answer the scene.
- **Close only what the tour opened** — a `tourOpened` ref per owner leaves a
  menu the user opened alone.
- **A scene must be a store, not an event**: the page the tour just navigated
  to mounts after the event and misses it; `useSyncExternalStore` reads the
  current value at mount.
- **A guessed card height** (260 px) misplaced the card whenever its copy ran
  longer. Measure it (ResizeObserver), try sides in preference order, never
  cover the target, pin a page-sized target's card bottom-centre.
- **Desktop and phone twins of one anchor coexist** and the first match is often
  hidden — take the first with a non-zero rect.
- **Measure only after the route renders**, then allow a grace period before
  skipping: 1.6 s, and 3 s for scene stops (menus animate in, lists load).
- **Scroll the target into view once per stop** (a per-stop flag); doing it
  every frame fights the user's own scrolling.
- **Progress dots stop scaling** past a dozen stops — a bar reads at thirty.

## Extension points a new repo fills in

- **Identity:** the role union and how to read the current user's role.
- **Router:** `navigate(path)` and the current pathname (react-router here).
- **Script:** chapters, stops, anchors, the finale stop, chapter icons.
- **Scenes:** the vocabulary and each owner component's open/close effect; the
  dialog library's outside-interaction and Escape hooks.
- **Storage keys:** namespace `app.tourSeen` / `app.tourChapters`; per terminal
  or per user.
- **Sandbox:** which workflow to replicate, its real components, fixture
  builders, the simulated input, the "go to the real page" route.
- **Look:** card colours, a brand mark on centered cards.
