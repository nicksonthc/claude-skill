# Engine: scheduler + process patterns

`core/sched.js` is a cooperative scheduler: every moving thing is a generator.
```js
yield wait(sec, (k) => {...}, ease.trap)  // timed tween, k 0..1; leftover time carries into the next wait
yield until(() => cond)                    // block until a predicate holds (event-driven)
yield null                                 // resume next step (polling loops)
sched.spawn(gen()); sched.step(dt)
```
Leftover-time carry makes configured durations add up exactly at any speed (1× or 100×) and any frame rate.
`ease.trap` is a servo trapezoid (22% accel / cruise / 22% decel) — use it for axes; `ease.io` for arms.

## Patterns (all in the template's `sim.js`)
| Pattern | Shape |
|---|---|
| **Arrivals** | loop: `until(room)` → spawn carrier → travel → `wait(arrivalGap)`. `continuous` vs lot of N. |
| **Axis / conveyor move** | `wait(dist / speed (+ settle), set position, ease.trap)` |
| **Combined axes** | one wait, duration = max(each axis' distance / speed) + settle (lift + travel together) |
| **Pick & place** | goto(from) → down → take → up → goto(to) → down → put → up; fractions of one `pickPlace` time |
| **Timed process (dwell)** | press/clamp tween → **`while (remain > 0) { yield null; remain -= dt }`** → release. The loop + `remain` lets `quietFor()` skip to the next finish |
| **Resource / mutex** | a flag + `until(() => !res.busy)`; one owner at a time (one lifter, one operator) |
| **Job choice** | a controller loop picks the next job from state each time it is free (unload-first, oldest-first, nearest-first) |
| **Hold with timeout** | `if (!work && clock - t0 < hold) yield null` — waits for a fresh carrier, then gives up. **Clock-based: `quietFor` must not skip it** |
| **Hand-over** | two robots on one rail: a starving one parks at its end, the other works all lanes/sockets until the next cycle ([pitfalls](pitfalls.md)) |
| **Operator** | a task queue (`dock`, `take`) with walking time = distance / walkSpeed; feeding the machine first |
| **Metrics** | one loop adds `dt` to buckets per resource: `[work, wait, idle]`; cells `[process, done-waiting, empty, handling]` |
| **Status flags** | `sim.status().flags[stepId]` booleans → light the flow steps and drive auto-cam |
| **Snapshot / marks** | `sim.snapshot()` pushed on every output event; experiments diff two marks |
| **Conservation** | `status().conserve`: created = in carriers + in cells + held + out |

## Writing the control logic
1. List every job type and what blocks it (needs a free slot, a free carrier pocket, the lifter).
2. Decide priority when several are possible; write it as the order of `if` blocks in the controller loop.
3. Check for **deadlock** on paper: a cycle where A waits for B and B for A (classic: finished parts
   waiting for an outbound carrier that only comes from emptying the inbound one). Give one side an
   independent supply (empty-carrier stack) or a timeout.
4. Check the **end of a lot**: the last carrier must finish with no new arrivals.
5. Run `check run` (lot) and `check cont` (continuous) before any visuals polish.

## quietFor (fast-forward)
```js
sim.quietFor = () => {
  if (sched.tasks.some((t) => t.w && t.w.kind === 'time')) return 0; // something is moving
  if (anyHoldOnTheClock) return 0;                                   // e.g. arm holding a board up to 150 s
  return min(remain of every dwelling cell) || 0;
};
```
Experiments step `q > 2 ? q - 1 : 0.25`. Anything that compares `sched.time` against a deadline inside a
`yield null` loop is invisible to the scheduler — list those states in the second line.
