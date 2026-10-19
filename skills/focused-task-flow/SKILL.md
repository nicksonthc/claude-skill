---
name: focused-task-flow
description: Focused one-task screen for an operator terminal, shop-floor station or kiosk in React — the screen always answers "what do I do now?" with one big prompt, exactly one primary action, bench-distance sizing, and inline error remediation (why it failed + how to fix it, cleared by the retry itself) with sound cues. Use when building or reviewing a station / kiosk / scan-then-act workflow screen, when operators miss errors or don't know what to do next, when asked for "kiosk mode", "focused flow", one task at a time, glove- or touch-friendly targets, actionable error messages, or audio feedback on success and failure.
---

# Focused Task Flow

Harvested from a production shop-floor console (AED assembly line: scan a unit,
track in, record steps, track out), plus the upgrades a UI/UX review of it
called for. Proven on React 19 · Tailwind v4 · shadcn/ui (Radix) · sonner.
**Proven in production:** the single primary, the scan-first Enter chain,
inline mismatch with select-for-rescan, the wrong-place card with a focused way
out, busy spinners, per-unit state reset. **Built and tested in the same app,
not yet on the floor:** the Now prompt, bench density tokens, coded refusals
with the remediation block, sound cues, verdict buttons, collapsed step rows,
the in-flight guard (AED station console, 19-10-2026: backend
`app/core/errors.StationError`, frontend `lib/remedies.ts`,
`lib/stationTask.ts`, `lib/cues.ts`, `VerdictButtons`, `ProblemBlock`,
`TaskPrompt`, with a test that every raised code has a remedy). Still to prove
at a real bench: cue volume on floor speakers, gloved taps on 72 px targets.

## The idea in one line

**One question on screen, one answer expected.** At any moment the station shows
what to do now (in words readable from two metres), exactly one action that does
it, and — when it fails — why, and what to do, right where the eyes already are.

## Decide the input model first

| | Scan-first (gun / keyboard) | Touch-first (gloves / tablet) |
|---|---|---|
| The big thing | the **prompt + the focused input** | the **primary button** |
| The action | the gun's trailing Enter | a tap on an 80–120 px target |
| Recovery | next scan replaces the bad value | next tap retries |

Most lines are mixed: design scan-first, then make every target ≥ 44 px and the
primary ≥ 72 px so a gloved tap also works. Keyboard plumbing (Alt-chord
shortcuts, focus chain, focus guard) is the `keyboard-first-hotkeys` skill — this
skill assumes it.

## Moving parts

1. **Task state, derived** — `deriveTask(serverData)` returns one of `idle ·
   loading · elsewhere · blocked · start · step(k of n) · finish · done`. Never
   store it; recompute from the record, so a socket update can't desync it.
2. **Now prompt** — one line, verb first ("Scan the **old battery** serial"),
   `--task-prompt` size, above the work. Built from the live step by a
   domain-supplied `describeStep`.
3. **Exactly one primary** — Start / Record / Finish carry `data-primary`;
   gating guarantees one is enabled; `pressPrimary()` finds it for Alt+Enter.
   Secondary actions shrink to corners in ghost style.
4. **Step rows by state** — done = one-line row (check + recorded value), live
   = the expanded card, locked = one dim "Next: …" line. Only the live step is
   big.
5. **Bench density** — `[data-density="bench"]` CSS variables scale the prompt,
   inputs and primary; desk density stays for supervisors' screens.
6. **Remediation block** — every failed action becomes a `Problem {code, why,
   how[], retry}` shown inline under the live step (`role="alert"`), not in a
   corner toast. Codes map to curated how-to steps; unknown codes fall back to
   the server message. Cleared by the retry itself, never by a Dismiss button.
7. **Cues** — WebAudio tones (no files): short tick on success, low two-tone on
   a blocking error. Own actions only; mute per terminal; never the only signal.
8. **Busy feedback** — within one frame of the press: button spinner, inputs
   disabled, `aria-busy`; an in-flight ref so a double Enter can't fire twice.

## Workflow

1. Pick the input model (table above); install `keyboard-first-hotkeys` first if scan-first.
2. Write `deriveTask` + `describeStep` for the domain; render the Now prompt from them.
3. Mark the primaries `data-primary`; prove only one is ever enabled.
4. Collapse done/locked steps to rows; keep only the live step expanded.
5. Add bench tokens; apply `data-density="bench"` on the station route.
6. Give the API stable error **codes**; write the remedy catalogue in bench words.
7. Route every action through `useTaskAction` (busy, in-flight guard, problem, cue, refocus).
8. Review with `REVIEW.md` at bench distance (screenshot at 50 %, read it from across the room).

Code for each part: `REFERENCE.md`. Audit rubric for an existing screen: `REVIEW.md`.

## Principles

- **The screen is a question, not a dashboard.** Context (unit header, route
  rail, people) is small and above; the question is big and central.
- **Words beat colour.** Every state has an icon + a word + a colour; glare and
  colour-blindness erase colour alone.
- **Errors are instructions.** Why (one plain sentence) + How (≤ 3 numbered
  steps) + what retry does. Remedies are curated text keyed by code — never
  generated at runtime on a regulated line.
- **Recovery is the next normal action.** A re-scan, a re-tap, a corrected value
  clears the problem. Nothing to dismiss.
- **Toasts are history, not messages.** Keep them for the log
  (`toast-notification-history`); the operator reads the block.

## Pitfalls (each already paid for once)

- **A mismatch is a mis-scan, not a defect.** Reject it inline, keep the bad value
  visible and **selected**, so the next scan replaces it instead of appending.
  Don't route it into the failure/quarantine flow.
- **Never autofocus a verdict.** A stray Enter would record a Pass nobody gave.
  Arrows move focus only; selecting is Space/Enter on a focused option.
- **Enter on a Radix Select trigger reopens the list.** A picked value must move
  focus one stop along, or the chain dead-ends. Prefer verdict buttons.
- **Per-subject choices reset per subject.** A "send to inspection" tick
  remembered across units once sent every following unit. Reset on the subject
  id — not on polled objects, which re-fetch and would wipe a serial mid-scan.
- **Disabled is not a guard.** Two Enters in one tick both see `busy=false`;
  guard with a ref.
- **A truly disabled button drops focus to `<body>`.** At a limit, use
  `aria-disabled` and ignore the press, so focus (and the next Enter) stays.
- **Wrong-place states need a focused exit** ("Not at this station" → Back to
  queue, autofocused), or a keyboard-only bench is stranded.
- **Remount to re-fire autofocus.** `key={ready ? "ready" : "wait"}` on the
  Finish button makes `autoFocus` fire when it becomes enabled.
- **Server strings leak internals** ("expected at station id 7"). Audit them;
  the catalogue speaks bench words.
- **`detail` as an object** breaks a client that only parses strings — update
  the error parser with the backend in the same change.
- **Audio autoplay:** the context only starts after a user gesture (a keydown
  counts) — create/resume it there. Cue only this terminal's own actions; a
  socket event from another operator must stay silent and must not move focus.
- **No flashing.** A one-shot shake or pulse; > 3 flashes/s is a seizure risk.
- **Floating UI over the primary.** A notification bell or chat bubble covering
  Record on a narrow screen; keep a bottom safe area on the station route.
- **Don't zoom the page for bench size.** Scale the task tokens; let the shell
  collapse its sidebar (`console-app-shell`) instead.

## Extension points a new repo fills in

- `deriveTask(record)` and `describeStep(step)` — the domain's states and verbs.
- `REMEDIES` — error code → why/how text; the backend raises those codes.
- Density choice per route, the cue on/off preference, primary sizes for touch.

Composes with `keyboard-first-hotkeys` (focus chain, Alt chords),
`ui-motion-system` (pop/shake tokens, skeletons), `toast-notification-history`
(the log behind the block) and `console-app-shell` (kiosk chrome).
