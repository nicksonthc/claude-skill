# Verification (`tools/check.mjs`)

Playwright drives the built page through `window.__sim` hooks (same hooks in both stacks).

```bash
npx playwright install chromium            # once per machine
node build.mjs                             # standalone → simulation.html (or: npm run build && npm run preview)
node tools/check.mjs run                   # lot to completion: all out, conserved, no console errors
node tools/check.mjs cont "" 4             # 4 sim-hours continuous: no stall, conserved
node tools/check.mjs rig                   # every view: pinch = dolly, lens pinned, distance + tilt clamped
node tools/check.mjs walk                  # walkthrough: caption shown, sim panels hidden
node tools/check.mjs shots "" shot 300     # screenshot every view after 300 s
SIM_HTML=preview.html node tools/check.mjs run           # check a preview build
SIM_URL=http://localhost:4173/ node tools/check.mjs rig  # check the served React build
```
Queries pass config: `node tools/check.mjs run "nestCols=1&process=600"`.

## Acceptance (all must hold before handing over)
- `run` ok for the default setup **and** for every compare option value (extremes included).
- `cont` ok for ≥ 2 h at the default and at the longest dwell in the sweep.
- `rig` ok in every view; `walk` ok.
- Every screenshot looked at (Read tool): layout matches the deck, nothing floating / intersecting, labels
  readable, no black frame. Close-ups for anything new (pipes, cables, small mechanisms) — they hide in
  wide shots.
- Analysis numbers re-derived once by hand from the buckets (e.g. UPH ≈ capacity ÷ dwell when process-bound).
- A changed default in the spec is reflected in the screenshot and in the analysis captions.

## When a check fails
- Conservation broken → a `take`/`put` mismatch or a unit disposed with its carrier.
- Stall → find the job that is never chosen: print the controller's candidates at the stall time
  (`sim.log`, a temporary `say`), usually an end-of-lot or a supply rule.
- Numbers differ between the live run and the comparison → the fast-forward is skipping a clock-based hold
  (compare stepped vs fast-forwarded runs of the same config).
- Very slow experiments in headless Chromium → the page is still rendering during the runs.
