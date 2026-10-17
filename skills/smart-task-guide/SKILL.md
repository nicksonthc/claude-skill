---
name: smart-task-guide
description: In-app smart guide for a web dashboard. A "What do you want to do?" search box (Ctrl+K) lists tasks; picking one navigates to the right page and spotlights each control in turn until the user presses the final button themselves. Troubleshooting runbooks branch on evidence: the guide reads backend data read-only, suggests answers, stops with a reason when the evidence says "don't", and leaves a copyable case summary. Use when users can't find where an action lives ("how do I add X", "guide the user to the button"), when building a spotlight / coach-mark / highlight-the-button feature that waits for the user's own click, or when turning a support SOP or runbook (diagnose, then fix) into a guided flow inside the app. A narrated, chaptered tour of the whole app is guided-product-tour.
---

# Smart Task Guide

Harvested from an operator dashboard for a warehouse robot cube, where support staff
needed to find actions like "add obstacle", "revive robot" and "halt cube",
and to diagnose cases like "TC says empty but the robot holds a bin → flag
picked". Framework-free: the engine and the overlay are plain JS and DOM, and
they bind to any front end through `subscribe`. Proven in production with a
component-library UI, with Playwright driving a Python mock backend.

## The idea in one line

**The guide points, and the user presses.** It never clicks anything, and it never calls a
write endpoint. That one rule makes it safe to put on destructive
screens (emergency stop, irreversible flags). It also teaches the flow, because the
user's own hands do every step. (A narrated tour that drives itself through
every page — chapters, roles, a sandbox finale — is the sibling
`guided-product-tour`; both share the box-shadow spotlight.)

## Moving parts

1. **Task catalogue** (`guideTasks.js`): one array that is the single source
   of truth for the search list and the step runner. A task is
   `{id, title, description, icon, page, route, routes?, keywords, param?,
   needsParam?, summary?, steps}`.
2. **Steps.** Each step points at a `target` selector and moves on when an `advance`
   condition fires: `click` the target, `appear: sel`, `when: fn`, `manual`
   (a Next button), or `decide: fn → stepId` (branch on an outcome). It can also carry
   `skipIf`, `route`, `load` (read facts), `dock`, `note`, `final`.
   An **`ask` step** is a question with `choices`. Each choice continues, moves with `goto` a step
   id, or ends with `end` and a reason. Add `facts(ctx)` rows and `suggest(ctx)` to
   preselect the answer the data supports.
3. **Engine** (`guideEngine.js`): one shared MutationObserver, batched to one
   check per frame, plus a 500 ms poll. It waits for the target, hands it to the
   overlay, and advances on the user's action. It keeps history so Back works across
   branches, and it records answers for the case summary.
4. **Spotlight overlay** (plain DOM, mounted once): a dim layer cut out around
   the target (a huge box-shadow around a hole, `pointer-events: none`), a pulsing
   ring, and a step card. It tracks the target every animation frame.
5. **Search box**: the app's own combobox in the app bar with a Ctrl/Cmd+K shortcut. It scores
   matches by prefix, then word, then edit-distance ≤1, then subsequence. It pulls a number out
   of the query ("revive 12") into the task's `param`.
6. **Facts layer** (`guideFacts.js`): read-only loaders that fill `ctx` (the
   record, its job, the message log, the device's own report). This is the only
   file that talks to the API.
7. **Anchors**: `data-guide="…"` attributes on the real controls, and
   `data-*` state flags (`data-locked`, `data-flow`) that the steps can read.

## Workflow

1. **Inventory.** For each task, find the route, the component and line of
   every control on the path, and what must happen first (a dialog, a tab, a
   selection, a role gate). A subagent sweep works well here. This list *is* the
   step list.
2. **Anchor.** Add `data-guide` attributes only, with no behaviour change. For table rows
   use the table's row-class hook to tag `guide-<kind>-<id>`.
   For state the guide must read, bind a `data-*` attribute.
3. **Drop in** the engine, search, overlay and catalogue from
   `REFERENCE.md` §1–§5. Then fill in the **UI adapter** (§2) by inspecting
   the app's markup: which selectors mean "menu open" and "dialog open", how to go
   from an input to its field wrapper, and what "disabled" looks like.
4. **Author linear tasks** first (navigate → open → fill → final). Every
   path ends on a `final` step.
5. **Author troubleshooting tasks** (§6), one evidence step per check, ordered from
   cheapest to most decisive. Each `ask` has an `end` choice for every
   "don't". `suggest` comes only from data, never for a physical check.
   Confirm the evidence rules with a domain owner before shipping.
6. **Verify** (§7). Run a Playwright walk per task and per branch against a mock
   backend whose shapes are copied from the real API source. Assert the ring sits on
   the expected anchor at every step, and that the guide sent no writes. Screenshot every
   step into a proof page.

## Principles

- **Wait, don't sleep.** Every transition is driven by an observed DOM
  condition, never by a timer. Pages load late, dialogs animate, sockets answer late.
- **Re-check `skipIf` on every DOM change, not once.** It is evaluated
  before the page has rendered, so "already in 2D view" reads false the first time.
- **A satisfied step is a skipped step.** If the advance condition is already true
  before the user saw the step (a default value), leave it out of history
  and the step count.
- **Branching tasks count steps taken** ("Step 7"), not "7 of 16".
- **Suggest, don't decide.** The data preselects an answer; the human confirms it.
  Physical checks ("is the bin really there?") are never preselected.
- **Every "don't" ends with a reason and a summary.** An `end` keeps the card open
  with the reason, the facts and every answer (marked when it matched the data),
  plus a Copy button for the ticket.
- **Find the right row by the data's own clock.** When a log has no timestamp
  column, look for one embedded in the id (hex epoch, sequence counter). Pick the
  newest entry *for the record in question*, not just the last row.
- **Plain words on the card**, matching what the user sees on screen. A raw enum
  token appears only where the UI itself shows it.

## Pitfalls (each one bit once)

- **Wrappers drop the attribute on an inner node.** Component libraries often
  pass `data-guide` through to the bare `<input>` of a field or select. Spotlight
  `el.closest(<field wrapper>)` instead. A combobox's input can be 0 px tall,
  so check visibility on the wrapper, not the input.
- **Closed dialogs and `v-show` stay in the DOM.** "Exists" is not "visible".
  Check that the rect is non-zero and that the element is not `display:none` or `visibility:hidden`.
- **A dropdown opens under the overlay.** While a menu is open, hide the dim
  layer *and* the card, or the card covers the options and swallows the clicks.
- **A dialog covers the target.** When the target is under an open dialog it
  doesn't belong to, shrink the card to a corner note ("Close the open window
  first"). Otherwise the card sits on that dialog's own Close button.
- **Esc belongs to the topmost thing.** While a menu or dialog is open, Esc closes
  that, not the guide.
- **Values set by code fire no mutation.** A field filled from a socket reply
  changes `.value`, not an attribute. The 500 ms poll catches it, and the card
  recomputes notes on a slow pulse so a live mismatch warning updates as the user types.
- **The combobox clears its search text after a pick.** To prefill "flag pick
  " and wait for the number, clear the selection first, then set the text in a
  `setTimeout` (~100 ms). A same-tick or next-tick write loses the race.
- **Rebuilding the card on a timer swallows clicks.** If nodes are replaced
  between mousedown and mouseup, the click is lost. Re-render only when the shown content changes.
- **Enter in a form may submit before the "press Confirm" step.** Advance on the
  outcome (`appear` of the results), not on the click.
- **Routes:** a task may visit several pages (`routes: [...]`). End the guide
  only when the user leaves *all* of them. Navigation done by the guide itself must not end it.
- **The real API is not what the UI code assumes.** Read the backend handler
  for each shape the facts layer uses. A typical example is an HTTP 200 with
  `data: []`, where the result arrives later over a socket. Write the mock from
  the backend source, not from the frontend's guesses.
- **Pick the row, then point at it.** For an action in a list (one button per
  record), ask "which record?" first, listing only those whose state allows the
  action, then spotlight that row's button alone. Place the card *beside* it:
  below it, the card covers the same button on the next rows.
- **Batch targets.** When a panel sends to every selected item, expose the
  selection as a `data-*` attribute. The step advances only when exactly the
  intended item is selected, and otherwise points at the extra one to deselect.
- **Move it for real, then record it.** When a flow both moves something
  physically and records it in the system, record last. A failure midway then
  leaves the record still true, and every "stop" message can say so.
- **Domain model drift.** Ask what is still true before modelling options the
  UI still carries. In the source project a whole "winch side A/B" step had to
  be removed once it turned out every robot now carries one bin.

## Extension points a new repo fills in

- **UI adapter:** the menu-open selector, dialog-open selector, field wrapper,
  disabled-button class, and the list of state attributes to observe.
- **Navigation:** `navigate(path)`, `currentPath()`, and a route-change hook that calls `stop()`.
- **Task catalogue and anchors.**
- **Facts loaders:** the read-only API calls, the auth headers, and how to parse the
  domain's log or message format.
- **Card copy and the summary header line** (which ctx param names the case).
