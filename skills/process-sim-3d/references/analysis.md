# Analysis (simulation mode)

All numbers come from headless runs of the same `buildWorld` + `createSim` (`sim/experiment.js`).

## Steady-state measurement (`runSteady`)
- Continuous feed. Push a snapshot (`marks`) on every output event (carrier out, board into the rack).
- Skip `warm` marks, then measure between mark `warm` and `warm + measure`: UPH = Δout / Δclock × 3600,
  utilisation = Δbuckets. Whole cycles only — bursty output (long dwells) averages correctly.
- For long dwells, size the window from the first cycle: K cycles so the window covers ≥ 2 h.
- If the marks never arrive within the time limit, return `null` and show "no steady state" — that is a
  finding (a stall or a starved setup), not something to interpolate.

## Compare + sweep (`runCompare`)
`spec.compare = { option, values, sweep: { key, values } }` → every option value × every sweep value.
Show per row: each option's UPH, its limit (bottleneck), the gain, and a bar. Typical: 1 vs 2 robots × dwell
time. Add the configured value to the sweep so "the current setting" is always a row.
- Bottleneck label from the buckets: cells processing ≥ 80% → "process-bound"; finished cells waiting
  ≥ 20% → "handler-bound"; else "balanced".
- Ceiling = capacity / dwell (e.g. 64 sockets ÷ 6 h = 10.7 UPH): print it next to the measured UPH.

## Where does option B stop paying? (crossover)
From the sweep, find the last value where the gain ≥ threshold (default 5%, editable) followed only by values
below it; bisect between the two with extra paired runs to ~1 minute. Report: "B adds ≥ X% up to T1; from
T2 it adds < X% — A is enough beyond ~T2". Also report the peak gain and where it is.

## Sizing advisor
Inputs: customer dwell time, optional required UPH, editable relative costs (placeholders until the
engineer enters real ones; keep them in localStorage, never in the spec).
- Candidates = every combination of the module options (racks × arms × lanes …). Simulate each at the dwell.
- "No waste" = no cheaper candidate with the same main capacity reaches 98% of its UPH.
- Required UPH given → cheapest candidate meeting it. None meets it → number of cells of the best-value
  candidate. No requirement → lowest cost per UPH among no-waste candidates.
- Explain the pick: what one more arm / lane would add, what one fewer loses; offer "Show this setup in 3D".

## Fill-up + sensitivity
- Fill-up = from an empty machine until every slot has been loaded once; report first-in time, per-slot rate,
  and the time split by what the bottleneck resource was doing (fetch / load / push / waiting).
- Idle after fill = first slot's dwell end − fill time (positive: handling idles that long every cycle).
- Sensitivity: each process param alone at +5 / +10 / +50% faster (durations ÷, speeds ×), plus all together;
  sort by saving. State plainly when the dwell dominates and faster handling barely matters.

## Making experiments fast and safe
- `S.busy = true` → the page stops rendering; work in ~30 ms slices then `await setTimeout(0)`.
- One experiment at a time: a lock shared by every analysis button (they mutate shared module state).
- Save/restore module-level config that `buildWorld` writes (e.g. lane count) around every run.
- Pause the live run during analysis and resume it after.
- Every result block lists its setup and `spec.assumptions`.
