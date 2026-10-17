# guided-product-tour — sandboxes

The hands-on part of the tour (SKILL.md moving parts 6–7), disclosed here
because only tours that end in practice need it. Same conventions as
REFERENCE.md: `@/` is a Vite alias to `src/`, `Card` / `Dialog*` are
shadcn/ui, and source domain nouns appear only as examples.

**Pitfalls (each already paid for once):**

- **Fixtures use the real DTO types.** A new required field breaks the
  sandbox's typecheck on purpose — update the builder, keep the type. Loosening
  it to `Partial<…>` lets the sandbox drift from the real page silently.
- **Timers leak into the next run** — a half-typed simulated scan fired into a
  fresh run. Track every timeout/interval; clear on close and on reset.
- **React-controlled inputs ignore `el.value = …`** — set through the native
  value setter and dispatch a bubbling `input` event.
- **Demo toasts land in the notification history** — suffix them "· demo"
  (see `toast-notification-history`). Fixture entities get negative ids.
- **Seed-mirrored values are copied by hand** — say which seed file at the top
  of the fixtures, and keep them in step.
- **"Fill demo" values are fake** — never a seeded or default credential: the
  sandbox sends nothing, and everything in it ships in the JS bundle.

---

## 6. Sandbox finale — `TourDemoDialog.tsx`

Domain-specific by nature, so this is the skeleton plus the parts that carry
over. In the source it replicated the station console: pick a station → scan
a serial → track in → record each step → track out.

```tsx
import { notify as toast } from "@/lib/notify" // the app's toast wrapper (toast-notification-history), or sonner's toast

// ---- fixtures -------------------------------------------------------------
// Mirrors the seeded process (name the seed file here) so the sandbox reads
// like the real thing — but everything below is local state: no API call is
// ever made from this dialog. Values copied from the seed are kept in step
// by hand.
//
// Builders return the REAL DTO types. A required field added to the DTO
// breaks this file's typecheck — that is the point: update the builder.
// Ids are negative, so no shared cache or key lookup can mistake a sandbox
// entity for a real row.
function field(id: number, title: string, over: Partial<StepField> = {}): StepField {
  return {
    id: -id, title, input_type: "text", unit: null, options: null, sequence: 0, required: true,
    /* …every remaining required key, with its neutral default… */
    ...over,
  }
}

type Phase = "pick" | "scan" | "console"

export function TourDemoDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const navigate = useNavigate()
  const [phase, setPhase] = useState<Phase>("pick")
  const [working, setWorking] = useState(false)
  // …the rest of the workflow's local state…

  // Pending timeouts/intervals — cleared on close and on reset, so a
  // half-typed "scan" never fires into a fresh run.
  const timers = useRef<number[]>([])
  const clearTimers = () => {
    for (const id of timers.current) { window.clearTimeout(id); window.clearInterval(id) }
    timers.current = []
  }
  const later = (ms: number, fn: () => void) => { timers.current.push(window.setTimeout(fn, ms)) }

  const reset = () => { clearTimers(); setPhase("pick"); setWorking(false) /* …every field back to start… */ }
  useEffect(() => {
    if (open) reset()
    return clearTimers
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // Same beats as the real page, minus the API: a short fake latency so the
  // real components show their own working state.
  const doPrimary = () => {
    setWorking(true)
    later(600, () => {
      setWorking(false)
      /* advance local state */
      toast.success("Done", { description: "SN-DEMO-0042 · demo" }) // "· demo" marks it in the notification history
    })
  }

  // A failing answer explains what production would do, and lets them retry.
  const onFail = () =>
    toast.warning("Failed test — in production this opens a rework ticket and parks the unit. Pick Pass to continue the demo.")

  // One coach line, derived from phase + state: what the operator does next.
  const coach = phase === "pick" ? "Pick where you're standing." : phase === "scan" ? "Scan the unit's serial — or press Simulate scan." : "…"

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-3xl">
        {/* header: "Hands-on demo" + "A sandbox that mirrors the real page. Nothing you do here is saved." */}
        {/* coach line + Simulate button */}
        {/* the REAL components, fed fixtures and local handlers; omit any
            callback that would reach the backend, with a comment saying so */}
        {/* min-w-0 on a wide child: a min-w-max rail must scroll inside the
            dialog grid, not widen it past the dialog's edge */}
        {/* done card: Replay (reset) + "Go to the real page" → onOpenChange(false); navigate("/real-page") */}
      </DialogContent>
    </Dialog>
  )
}
```

**Simulated input device** — a scan gun is a keyboard wedge: it types into
whatever input has the caret, then sends Enter. Type character by character:

```ts
// React controlled inputs ignore `input.value = …`; set through the native
// setter and dispatch a bubbling `input` event so onChange fires.
function typeInto(input: HTMLInputElement, text: string, track: (id: number) => void, msPerChar = 28) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set
  if (!setter) return
  input.focus()
  let i = 0
  const id = window.setInterval(() => {
    i++
    setter.call(input, text.slice(0, i))
    input.dispatchEvent(new Event("input", { bubbles: true }))
    if (i >= text.length) window.clearInterval(id)
  }, msPerChar)
  track(id) // into the timers ref, so closing mid-scan stops it
}
```

When the sandbox's own state holds the input (the scan box), animate the
state instead: `setSn(DEMO_SN.slice(0, i))` per tick, then submit after a beat.

**Focus.** If a real component steals focus (a print frame, a dialog), put it
back on the live element when it settles, so the sandbox teaches the same
uninterrupted keyboard chain as the real page (see `keyboard-first-hotkeys`).

---

## 7. Flow sandbox — stepper, coach line, checklist reveal

For a flow the tour can't show on real screens: it needs a second person (an
approver), an outside directory, or a brand-new account. In the source:
first sign-in through the company directory → "no role yet" → profile + role →
an admin authorizes with their own password → done; launched from the login
screen's "See how sign-up works".

```tsx
type Phase = "signin" | "checking" | "register" | "adminpw" | "approving" | "done"

// The journey as a stepper across the top. A stage that applies only on one
// branch (here: a new admin also sets a local password) is filtered in or out.
const ALL_STAGES: { key: Phase; label: string }[] = [
  { key: "signin", label: "Sign in" }, { key: "checking", label: "Verify" }, { key: "register", label: "Set role" },
  { key: "adminpw", label: "Set password" }, { key: "approving", label: "Approve" }, { key: "done", label: "Done" },
]
const stages = useMemo(() => ALL_STAGES.filter((s) => s.key !== "adminpw" || isAdmin), [isAdmin])

interface Check {
  label: string
  /** "warn" = an expected gap ("no role on file yet"), not a failure. */
  tone?: "ok" | "warn"
}

// Lines revealed during a "the server is checking" beat. List them in the
// order the backend really performs them, so the sandbox teaches the truth.
const VERIFY_CHECKS: Check[] = [
  { label: "Contacting the directory" },
  { label: "Identity verified" },
  { label: "Looking up a role in the user table" },
  { label: "No role on file yet — needs setup", tone: "warn" },
]

const REVEAL_MS = 780 // per line
const HOLD_MS = 950 // the last line sits on screen before the next phase

// Reveal a checklist line by line, then run `onDone`. Timers go through the
// same tracked `later` as §6, cleared on close/reset.
const runChecklist = (count: number, onDone: () => void) => {
  setRevealed(0)
  for (let i = 1; i <= count; i++) later(i * REVEAL_MS, () => setRevealed(i))
  later(count * REVEAL_MS + HOLD_MS, onDone)
}

/** Reveals a checklist one line at a time: the active (last revealed) line
 *  spins, earlier lines settle to a check, or an amber dot for an expected gap. */
function ChecklistCard({ title, checks, revealed }: { title: string; checks: Check[]; revealed: number }) {
  return (
    <Card className="anim-rise gap-4 p-6">
      <div className="font-medium">{title}</div>
      <ul className="space-y-2.5">
        {checks.map((c, i) => {
          const shown = i < revealed
          const active = i === revealed - 1 && revealed < checks.length
          return (
            <li key={c.label} className={cn("flex items-center gap-3 text-sm transition-opacity duration-300", shown ? "opacity-100" : "opacity-30")}>
              {!shown ? <span className="size-4 shrink-0 rounded-full border border-dashed border-border" />
                : active ? <Loader2 className="size-4 shrink-0 animate-spin text-sky-500" />
                : c.tone === "warn" ? <span className="size-4 shrink-0 rounded-full bg-amber-500/20 ring-2 ring-amber-500/60" />
                : <CircleCheck className="size-4 shrink-0 text-emerald-500" />}
              <span className={cn(c.tone === "warn" && shown && "text-amber-600 dark:text-amber-400")}>{c.label}</span>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}
```

- **Coach line per phase** narrates *why* each beat happens ("the approver is
  checked against the app's own user table, not the directory").
- **"Fill demo …" buttons** on every form, so nobody has to invent values. Use
  obviously fake values: the sandbox sends nothing, so they only need to look
  right — never a real seeded or default credential, which would ship in the
  JS bundle.
- **End card:** what is now true ("next sign-in skips straight to the app"),
  Replay, and Got it.
