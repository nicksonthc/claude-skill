# Focused Task Flow — reference

Copy-paste building blocks, genericized. Domain nouns from the source (unit,
station, track in/out, step) are kept as *examples*; rename freely. Stack:
React 19 · TypeScript · Tailwind v4 · shadcn/ui. Focus helpers
(`focusFirstIn`, `focusNextIn`, `focusIsAdrift`, `pressPrimary`,
`useFocusGuard`) come from the `keyboard-first-hotkeys` skill.

---

## 1. Bench density tokens (`index.css`)

The station is read from 1–2 m, at an angle, under factory light. Scale the
task, not the page.

```css
/* Desk: supervisors at a monitor. */
:root,
[data-density="desk"] {
  --task-prompt: 1.25rem;
  --task-field-h: 2.25rem;
  --task-field-text: 1rem;
  --task-primary-h: 2.5rem;
  --task-primary-text: 0.95rem;
  --task-target-min: 2.25rem;
}
/* Bench: the station route. Primary 72 px for a scan-first bench with the
   occasional gloved tap; raise to 88–120 px for touch-first. */
[data-density="bench"] {
  --task-prompt: clamp(1.75rem, 1.1rem + 2vw, 3rem);
  --task-field-h: 3.5rem;
  --task-field-text: 1.375rem;
  --task-primary-h: 4.5rem;
  --task-primary-text: 1.25rem;
  --task-target-min: 2.75rem; /* 44 px: nothing tappable smaller */
}
/* One state language. Pair every colour with an icon and a word. */
:root {
  --task-live: var(--color-sky-600);
  --task-done: var(--color-emerald-600);
  --task-attention: var(--color-amber-600);
  --task-blocked: var(--color-rose-600);
}
@media (prefers-reduced-motion: reduce) {
  .task-shake { animation: none !important; }
}
@keyframes task-shake {
  0%, 100% { transform: translateX(0); }
  20%, 60% { transform: translateX(-6px); }
  40%, 80% { transform: translateX(6px); }
}
/* One shot — never a loop (no flashing). */
.task-shake { animation: task-shake 320ms ease-in-out 1; }
```

Tailwind v4 reads them as `h-(--task-primary-h)`, `text-(length:--task-prompt)`.
Set the density on the route's root: `<div data-density="bench">`.

## 2. Task state, derived (`lib/task.ts`)

Never stored: recomputed from the server record on every render, so a socket
update or a second tab can't leave it stale.

```ts
export interface StepLike {
  id: number
  name: string
  required: boolean
  predecessorId: number | null
}

export type Task<S extends StepLike = StepLike> =
  | { kind: "idle" }                                         // nothing open: scan to start
  | { kind: "loading"; subject: string }
  | { kind: "elsewhere"; subject: string; where: string }    // can't be worked here
  | { kind: "blocked"; subject: string; reason: string }     // on hold, quarantined…
  | { kind: "start"; subject: string }                       // open, not started (track in)
  | { kind: "step"; subject: string; step: S; index: number; total: number }
  | { kind: "finish"; subject: string }                      // all required done (track out)
  | { kind: "done"; subject: string }

/** The live step: first required-or-not step whose predecessor is done and
 *  which is not done itself. Domain rules (gates, optional steps) go here. */
export function liveStep<S extends StepLike>(steps: S[], done: Set<number>): S | null {
  return (
    steps.find(
      (s) => !done.has(s.id) && (s.predecessorId == null || done.has(s.predecessorId)),
    ) ?? null
  )
}

/** Example for a scan → start → steps → finish station. Replace the record
 *  shape with yours; keep the order of the checks (most blocking first). */
export function deriveTask<S extends StepLike>(r: {
  subject: string | null
  loaded: boolean
  hereCode: string
  atCode: string | null
  status: "in_progress" | "on_hold" | "completed"
  holdReason?: string
  started: boolean
  steps: S[]
  done: Set<number>
}): Task<S> {
  if (!r.subject) return { kind: "idle" }
  if (!r.loaded) return { kind: "loading", subject: r.subject }
  if (r.status === "completed") return { kind: "done", subject: r.subject }
  if (r.status === "on_hold")
    return { kind: "blocked", subject: r.subject, reason: r.holdReason ?? "On hold" }
  if (r.atCode !== r.hereCode)
    return { kind: "elsewhere", subject: r.subject, where: r.atCode ?? "—" }
  if (!r.started) return { kind: "start", subject: r.subject }
  const step = liveStep(r.steps, r.done)
  const requiredLeft = r.steps.some((s) => s.required && !r.done.has(s.id))
  if (step && requiredLeft) {
    return {
      kind: "step",
      subject: r.subject,
      step,
      index: r.steps.indexOf(step),
      total: r.steps.length,
    }
  }
  return { kind: "finish", subject: r.subject }
}
```

## 3. The Now prompt (`components/TaskPrompt.tsx`)

Verb first, the object in bold, one line. `describeStep` is the domain's: from
a field's placeholder ("Scan old battery serial"), a step type, or a table.

```tsx
import type { ReactNode } from "react"
import type { StepLike, Task } from "@/lib/task"

export function promptFor<S extends StepLike>(
  t: Task<S>,
  describeStep: (s: S) => ReactNode,
): { text: ReactNode; tone: "live" | "done" | "attention" | "blocked" } {
  switch (t.kind) {
    case "idle": return { text: <>Scan a <b>unit</b> to start</>, tone: "live" }
    case "loading": return { text: <>Opening <b>{t.subject}</b>…</>, tone: "live" }
    case "elsewhere": return { text: <><b>{t.subject}</b> belongs at {t.where}</>, tone: "attention" }
    case "blocked": return { text: <><b>{t.subject}</b> is on hold — {t.reason}</>, tone: "attention" }
    case "start": return { text: <>Press <b>Enter</b> to start {t.subject}</>, tone: "live" }
    case "step": return { text: describeStep(t.step), tone: "live" }
    case "finish": return { text: <>All done — press <b>Enter</b> to send it on</>, tone: "done" }
    case "done": return { text: <><b>{t.subject}</b> is complete — scan the next unit</>, tone: "done" }
  }
}

const TONE = {
  live: "text-(--task-live)",
  done: "text-(--task-done)",
  attention: "text-(--task-attention)",
  blocked: "text-(--task-blocked)",
} as const

export function TaskPrompt({
  text,
  tone,
  progress,
}: {
  text: ReactNode
  tone: keyof typeof TONE
  /** "Step 2 of 3" — small, after the prompt. */
  progress?: string
}) {
  return (
    // aria-live so a screen reader (and the tour) hears each new instruction.
    <div aria-live="polite" className="mb-4">
      <div className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        Now{progress ? ` · ${progress}` : ""}
      </div>
      <h2 className={`text-(length:--task-prompt) leading-tight font-semibold ${TONE[tone]}`}>
        {text}
      </h2>
    </div>
  )
}
```

## 4. Exactly one primary

```tsx
// The one action the station waits on. Exactly one is enabled at any time —
// the gating guarantees it — so Alt+Enter can find it by attribute
// (pressPrimary) without threading refs through every step card.
<Button
  data-primary
  // Remount when it becomes ready, so autoFocus fires: Enter then finishes.
  key={ready ? "ready" : "waiting"}
  autoFocus={ready}
  disabled={!ready || busy}
  aria-busy={busy || undefined}
  className="h-(--task-primary-h) min-w-48 px-6 text-(length:--task-primary-text)"
  onClick={onPrimary}
>
  {busy && <Loader2 className="size-5 animate-spin" />}
  {label} <Kbd>⏎</Kbd>
</Button>
```

Render the Finish primary only in the `finish` state (not disabled-and-visible
throughout): a big grey button above the live step competes with it for
attention. Secondary actions (Back to queue, Trace, Delete) are `variant="ghost"`
in the header corner, each ≥ `--task-target-min` tall.

## 5. Step rows by state (`components/StepRow.tsx`)

```tsx
// Done: one line, proof of what was recorded. Locked: one dim line, so the
// operator sees what comes next without it competing. Live: the full card.
export function StepRow({ state, name, summary, children }: {
  state: "done" | "live" | "locked"
  name: string
  summary?: string
  children?: React.ReactNode   // the live card body
}) {
  if (state === "done")
    return (
      <div className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm">
        <span className="anim-pop grid size-5 place-items-center rounded-full bg-(--task-done) text-white">
          <Check className="size-3" strokeWidth={3} />
        </span>
        <span className="font-medium">{name}</span>
        {summary && <span className="truncate font-mono text-muted-foreground">{summary}</span>}
      </div>
    )
  if (state === "locked")
    return (
      <div className="px-3 py-1.5 text-sm text-muted-foreground">
        Next: {name}
      </div>
    )
  return <Card className="gap-4 p-5 ring-2 ring-(--task-live)/30">{children}</Card>
}
```

Completed rows keep their Amend / Reprint buttons out of the focus chain
(`data-skip-autofocus`), so "the first focusable in the list" is always the live
step.

## 6. Problems: why + how (`lib/problem.ts`, `components/ProblemBlock.tsx`)

### Backend contract

Raise a stable **code** with the human message and the parameters the remedy
needs. FastAPI example:

```py
from fastapi import HTTPException

class TaskError(HTTPException):
    """A refusal the operator can act on. `code` is stable (the UI keys its
    remedy on it); `message` is the plain-language why."""
    def __init__(self, status_code: int, code: str, message: str, **params):
        super().__init__(status_code, {"code": code, "message": message, "params": params})

# raise TaskError(409, "WRONG_STATION", f"{sn} is at {at}, not {here}", sn=sn, at=at, here=here)
```

Update the client's error parser in the same change — a parser that only reads
string `detail` turns this into "Request failed (409)". Keep the raw `detail`
on the thrown error (e.g. `new ApiError(status, text, detail)`): `toProblem`
below reads `err.detail`.

### Client

```ts
export interface Problem {
  code: string
  /** One plain sentence: what went wrong. */
  why: string
  /** At most three numbered steps, in bench words. */
  how: string[]
  /** What the operator's next normal action does: re-scan the field, repeat the press. */
  retry: "rescan" | "repeat"
  /** What was attempted — "Track out · P21410-006 · ST4". */
  attempted?: string
  /** Server error reference, if the backend logs one, for reporting. */
  ref?: string
}

type Params = Record<string, string | number | undefined>
type Remedy = { how: (p: Params) => string[]; retry: Problem["retry"] }

// Curated, reviewed text — never generated at runtime on a regulated line.
export const REMEDIES: Record<string, Remedy> = {
  WRONG_STATION: {
    how: (p) => [`Take the unit to ${p.at}.`, "Press Back to queue and scan the unit that belongs here."],
    retry: "rescan",
  },
  SERIAL_MISMATCH: {
    how: (p) => [`Check the label on the unit in your hands — it should read ${p.expected}.`, "Scan it again."],
    retry: "rescan",
  },
  ALREADY_BOUND: {
    how: (p) => [`${p.serial} is already on ${p.owner}.`, "Take a new part from the tray and scan it."],
    retry: "rescan",
  },
  BATCH_FULL: {
    how: () => ["Ask a supervisor to set the next batch as processing.", "Then scan the unit again."],
    retry: "rescan",
  },
}

const FALLBACK: Remedy = {
  how: () => ["Check the unit and try again.", "If it happens again, tell your supervisor and quote the reference."],
  retry: "repeat",
}

export function toProblem(err: unknown, attempted?: string): Problem {
  const d = (err as { detail?: unknown })?.detail
  const shaped = d && typeof d === "object" && "code" in d
    ? (d as { code: string; message: string; params?: Params })
    : null
  const message = shaped?.message ?? (err instanceof Error ? err.message : "Something went wrong")
  const remedy = (shaped && REMEDIES[shaped.code]) || FALLBACK
  return {
    code: shaped?.code ?? "UNKNOWN",
    why: message,
    how: remedy.how(shaped?.params ?? {}),
    retry: remedy.retry,
    attempted,
    ref: (err as { ref?: string })?.ref,
  }
}
```

```tsx
// Inline, under the live step — where the operator is already looking.
// role="alert" announces it; the one-shot shake draws the eye without flashing.
// Key it per failure at the call site (`key={n}` bumped on each failure) so the
// shake replays when the same problem happens twice in a row.
export function ProblemBlock({ problem }: { problem: Problem }) {
  return (
    <div
      role="alert"
      className="task-shake mt-3 rounded-xl border-2 border-(--task-blocked) bg-(--task-blocked)/8 p-4"
    >
      <div className="flex items-center gap-2 font-semibold text-(--task-blocked)">
        <OctagonX className="size-5" /> Not done — {problem.why}
      </div>
      <ol className="mt-2 list-decimal space-y-1 pl-6 text-base">
        {problem.how.map((h) => <li key={h}>{h}</li>)}
      </ol>
      <div className="mt-2 text-xs text-muted-foreground">
        {problem.retry === "rescan" ? "Scanning again clears this." : "Pressing it again clears this."}
        {problem.attempted && ` · ${problem.attempted}`}
        {problem.ref && ` · ref ${problem.ref}`}
      </div>
    </div>
  )
}
```

**Auto-clear rules:** clear on the next successful action, and on the first
change to the field the problem is about (the operator has started fixing it).
No Dismiss button.

## 7. Sound cues (`lib/cues.ts`)

```ts
// Generated tones — no audio files to ship, cache or license. The context may
// only start after a user gesture; a keydown (the scan gun) counts, so unlock
// it on the first one.
let ctx: AudioContext | null = null
const MUTE_KEY = "task.cues.muted"

export function cuesMuted(): boolean {
  try { return localStorage.getItem(MUTE_KEY) === "1" } catch { return false }
}
export function setCuesMuted(m: boolean) {
  try { localStorage.setItem(MUTE_KEY, m ? "1" : "0") } catch { /* private mode */ }
}

export function unlockCues() {
  const unlock = () => {
    ctx ??= new AudioContext()
    if (ctx.state === "suspended") void ctx.resume()
  }
  window.addEventListener("keydown", unlock, { once: true, capture: true })
  window.addEventListener("pointerdown", unlock, { once: true, capture: true })
}

const TONES = {
  ok: { wave: "sine", notes: [[1046, 0.07]] },                     // short, high: "got it"
  error: { wave: "square", notes: [[330, 0.16], [220, 0.24]] },    // low, falling: "stop"
  attention: { wave: "triangle", notes: [[660, 0.09], [660, 0.09]] },
} as const

/** Play for THIS terminal's own actions only — never for another operator's
 *  socket event. Never the only signal: pair with the visual state. */
export function cue(kind: keyof typeof TONES, volume = 0.18) {
  if (!ctx || cuesMuted()) return
  let at = ctx.currentTime
  for (const [freq, dur] of TONES[kind].notes) {
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.type = TONES[kind].wave
    osc.frequency.value = freq
    gain.gain.setValueAtTime(0.0001, at)
    gain.gain.exponentialRampToValueAtTime(volume, at + 0.01)
    gain.gain.exponentialRampToValueAtTime(0.0001, at + dur)
    osc.connect(gain).connect(ctx.destination)
    osc.start(at)
    osc.stop(at + dur + 0.02)
    at += dur + 0.04
  }
}
```

Call `unlockCues()` once at app start. Put the mute switch in the terminal's
own preferences, not a line-wide setting: one noisy bench shouldn't silence all.

## 8. One action wrapper (`hooks/useTaskAction.ts`)

```ts
import { useCallback, useRef, useState } from "react"
import { cue } from "@/lib/cues"
import { type Problem, toProblem } from "@/lib/problem"

export function useTaskAction() {
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<Problem | null>(null)
  // State lags a render: two Enters in one tick would both see busy=false.
  const inflight = useRef(false)

  const run = useCallback(
    async <T,>(
      attempted: string,
      fn: () => Promise<T>,
      opts?: { ok?: (r: T) => void; retryTarget?: () => HTMLElement | null },
    ) => {
      if (inflight.current) return
      inflight.current = true
      setBusy(true)
      try {
        const r = await fn()
        setProblem(null)
        cue("ok")
        opts?.ok?.(r)
        return r
      } catch (err) {
        const p = toProblem(err, attempted)
        setProblem(p)
        cue("error")
        // Put the operator back where the retry happens; select a field's text
        // so the next scan replaces the bad value instead of appending to it.
        requestAnimationFrame(() => {
          const el = opts?.retryTarget?.()
          el?.focus()
          if (el instanceof HTMLInputElement) el.select()
        })
      } finally {
        inflight.current = false
        setBusy(false)
      }
    },
    [],
  )

  return { run, busy, problem, clearProblem: () => setProblem(null) }
}
```

Keep the toast too if the app has a notification history — as the log entry,
not the message.

## 9. Verdict buttons instead of a dropdown (`components/VerdictButtons.tsx`)

A two- or three-option verdict as a Select costs open → arrow → Enter and dead-ends
the Enter chain. Big buttons, with the hazards handled:

```tsx
// Never autofocused: a stray Enter would select a verdict nobody gave.
// Arrows move focus only (not the ARIA select-on-move), Space/Enter selects,
// and picking hands focus one stop along so the next Enter records the step.
export function VerdictButtons({ label, options, value, onChange, onAdvance, disabled }: {
  label: string
  options: { value: string; tone: "done" | "blocked" | "attention" }[]
  value: string
  onChange: (v: string) => void
  onAdvance?: () => void
  disabled?: boolean
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const checked = options.findIndex((o) => o.value === value)
  return (
    <div role="radiogroup" aria-label={label} className="grid auto-cols-fr grid-flow-col gap-3">
      {options.map((o, i) => (
        <button
          key={o.value}
          ref={(el) => { refs.current[i] = el }}
          type="button"
          role="radio"
          aria-checked={i === checked}
          // One tab stop for the group: the checked one, else the first.
          tabIndex={i === (checked >= 0 ? checked : 0) ? 0 : -1}
          data-skip-autofocus
          disabled={disabled}
          onKeyDown={(e) => {
            const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0
            if (!d) return
            e.preventDefault()
            refs.current[(i + d + options.length) % options.length]?.focus()
          }}
          onClick={() => {
            onChange(o.value)
            requestAnimationFrame(() => onAdvance?.())
          }}
          className={cn(
            "h-(--task-primary-h) rounded-xl border-2 text-(length:--task-primary-text) font-semibold",
            i === checked
              ? `border-(--task-${o.tone}) bg-(--task-${o.tone}) text-white`
              : "border-border hover:bg-secondary",
          )}
        >
          {o.value}
        </button>
      ))}
    </div>
  )
}
```

Tailwind can't see `border-(--task-${o.tone})` built at runtime — list the
three classes in a lookup object in real code (shown inline here for brevity).
For a scan-only bench, a laminated card with PASS / FAIL barcodes scanned into
a text field is the zero-reach alternative.

## 10. Layout skeleton

```
┌ header: Station ST4 · who's here ·················· [Change station] ┐
│ ← Queue / P21410-006          P2 · LTE · JO-0418        (small)      │
│ route rail (small, one line)                                          │
│                                                                       │
│ NOW · step 1 of 2                                                     │
│ Scan the OLD battery serial                     (--task-prompt)       │
│ ┌ live step card ───────────────────────────────────────────────┐    │
│ │ [ field, --task-field-h ]                    [ Record ⏎ ]     │    │
│ │ ┌ problem block (only when a press failed) ┐                  │    │
│ └───────────────────────────────────────────────────────────────┘    │
│ ✓ done row · value                                                    │
│ Next: Validation                                                      │
│                                  (bottom safe area: no floating UI)  │
└──────────────────────────────────────────────────────────────────────┘
```
