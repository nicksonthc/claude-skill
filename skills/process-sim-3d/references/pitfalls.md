# Pitfalls (each one was a real bug)

| Symptom | Cause | Fix |
|---|---|---|
| 2 robots measured *slower* than 1 at one dwell time (e.g. −50% at 20 min) while the live run looked fine | the fast-forward skipped a robot's *hold for a fresh carrier* (a `yield null` loop checking `clock − t0 < 150`) — the 150 s hold became a wait for the next process finish (up to ~20 min) | `quietFor()` returns 0 while any resource is at the board / in a clock-based hold; compare stepped vs fast-forwarded runs once |
| 2 robots dip below 1 robot in a narrow band | each robot owned half the lanes; when its trolleys were swapped together it held the board while the other robot's half was full of work | hand-over: a starving robot parks at its rail end, the other takes all lanes and sockets until the next cycle |
| Robots collide / pass through each other | two robots on one rail with independent targets | keep base ranges apart (≥ 0.38 m gap) and recompute ranges from the parked robot's position |
| Comparison never finishes in headless Chromium (> 15 min) | the page kept rendering the full scene between experiment slices | `S.busy` skips rendering; experiments work in ~30 ms slices |
| Live scene wrong after running a comparison | an experiment changed a module-level count (lanes) used by the live world | save/restore around every run |
| Last parts of a lot never finish | the empty-carrier supply rule required the inbound carrier to still hold parts | supply empties whenever finished parts wait and no outbound carrier exists |
| A board was sent into the rack half filled | a returning robot waited to reclaim its half *before* claiming the board, so the lifter saw "nobody at the board" | claim (`atBoard = true`) before any wait |
| Pinch-zoom on a Mac warped the view and ignored min/max distance | ctrl+wheel mapped to lens zoom | re-dispatch as plain wheel (dolly) × 3, pin `minZoom = maxZoom = 1` |
| Users dragged the layout by accident | layout block moved on any left-drag | right-click → "Drag to reposition…" arms one drag; plain drag orbits |
| Dialog content cut off, no scrollbar | `max-height: 100%` inside an auto-sized grid row | `max-height: calc(100dvh − 36px)` on the box, `flex: 1; min-height: 0; overflow: auto` on the body |
| A toolbar group sat 5 px low | new `.grp` class collided with an existing `.grp { margin-top }` | feature-prefixed class names |
| A pipe ran through a frame post | routing checked in a wide shot only | close-up screenshots of new geometry; check clearances numerically against posts and moving envelopes |
| The engineer's open HTML changed under them | rebuilding the delivered file during checks | build previews to a scratch path; rebuild the delivered file only when asked |
| "Insight" numbers were arithmetic, not simulation | quoting deck math | every number on screen comes from a run, with its setup and assumptions printed beside it |
| Debug print showed two robots at the same position | string concat `'-' + '-0.62'` | print structured values (JSON), not concatenated flags |
