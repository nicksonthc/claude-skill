---
name: process-sim-3d
description: Build a 3D process simulation or visual walkthrough of a machine, production cell, line or station from a deck (PPT), a spreadsheet (Excel) or a text description — layout, moving equipment (conveyors, robots, lifters, gantries, racks, carts, operators), timed process steps, throughput / bottleneck / utilisation, setup comparison (1 vs 2 robots), sizing and fill-up time — delivered as one standalone HTML file or a React + three.js app. Use when asked to "simulate this machine / cell / line in 3D", "make a 3D walkthrough of the process", "turn this deck / Excel into a 3D sim", "how many UPH / where is the bottleneck / do we need a second arm", or to bring STEP / GLB equipment models into such a scene.
---

# Process Sim 3D

Turns an engineer's input (deck, sheet, prompt) into a browser 3D scene of their process: a **walkthrough**
(visual story, quick) or a **simulation** (timing-accurate, with analysis). Harvested from a burn-in cell
simulator (trolleys → handler → SCARA → lifter → 2 test racks); the machine-specific parts became the
**spec** and the **process logic**, everything else is reusable template code.

**The one idea: everything flows through one reviewed spec.** `sim/spec.js` holds layout, components,
params (every timing with unit, range and source), flow steps, camera views, tour and compare options.
Panels, config, views and analysis are generated from it; only the world builder and the process logic are
written per machine. Every value carries its source (`deck p.7`, `sheet B12`, `assumed`) so the engineer
can see what is real.

## Step 0 — ask once, at trigger (AskUserQuestion, all in one call)
1. **Mode**: Walkthrough (visual tour, no metrics; fastest) · Simulation (timing-accurate DES + analysis).
   A walkthrough upgrades to a simulation later once the engineer supplies component-to-component flow + timings.
2. **Stack**: Standalone HTML (one file, double-click, email, offline) · React + three.js (hosted, embeddable).
3. **Language**: JavaScript · TypeScript.
4. **Geometry**: Procedural from dimensions (default) · STEP files · GLB files — any other format is refused
   with the reason and the export to ask for ([references/cad.md](references/cad.md)).
5. **Hosting** (React only): static folder on any web server · S3/CloudFront · GitHub Pages · Netlify/Vercel · single-file build.

## Workflow (each step ends on its done-criterion)
1. **Intake → spec** — [references/intake.md](references/intake.md), schema in
   [references/spec-schema.md](references/spec-schema.md). Done when every param has a value **and** a source,
   gaps are listed as questions, and the engineer has approved the spec. No code before this.
2. **Scaffold** — copy `templates/shared/*` into `src/`, the chosen shell (`templates/standalone` or
   `templates/r3f`) into the project root, `templates/tools/check.mjs` into `tools/`
   ([references/stacks.md](references/stacks.md)). Done when the untouched demo builds and `check run` passes.
3. **Layout & geometry** — map each spec component to `components/index.js`; add new ones the same way;
   STEP/GLB via [references/cad.md](references/cad.md); look rules in [references/visuals.md](references/visuals.md).
   Done when a screenshot of every view matches the deck's layout and dimensions.
4. **Behaviour** — [references/engine.md](references/engine.md). Walkthrough: looping motions + `spec.tour`.
   Simulation: one generator process per moving thing; control rules written for this machine. Done when
   `check run` (lot to completion, parts conserved) and `check cont` (no stall) both pass.
5. **Panels** — generated from the spec ([references/ui.md](references/ui.md)); add machine-specific status only.
6. **Analysis** (simulation only) — compare, sweep, sizing, fill-up + sensitivity
   ([references/analysis.md](references/analysis.md)). Done when every number on screen came from a run and
   its assumptions are listed beside it.
7. **Verify** — every `check` mode green, every view screenshotted and looked at
   ([references/verification.md](references/verification.md)).
8. **Deliver** — build a preview to a new path first; overwrite the file the engineer has open only when they say so.

## Principles
- **Measure, then show.** Throughput, idle time, crossover points and proposals come from simulated runs
  (steady-state windows), never from arithmetic on the deck.
- **Spec is the single source of truth.** Layout constants, params and steps live in the spec; components
  derive sizes from it; panels read it. Changing a timing is a spec edit, never a hunt.
- **Patterns, not a solver.** Arrivals, conveyor moves, pick/place, timed dwells, holds, hand-overs and
  metrics are reusable; *which job goes first* is this machine's control logic — write it, then test it.
- **Conservation is the canary.** Every unit created is in exactly one place (carrier, cell, gripper, out).
  A broken count is a logic bug, whatever the screen shows.
- **Engineer owns the file.** Previews go to a scratch path; rebuilds of the delivered file wait for a yes.

## Pitfalls (the expensive ones — full list in [references/pitfalls.md](references/pitfalls.md))
- Fast-forward (`quietFor`) must return 0 while anything waits on the **clock** (a hold-with-timeout loop),
  or a 150 s hold silently becomes a wait for the next process finish and results halve.
- Experiments must stop the page drawing (`S.busy`) and work in ~30 ms slices — otherwise each yield pays
  for a frame and a 0.1 s run takes 30 s.
- A module-level constant changed per experiment (lane count, layer count) must be saved and restored.
- Two robots on one rail never pass each other: hand over (park + take over lanes/sockets) or reserve.
- End-of-lot: the supply rule that feeds the last empty carrier must not depend on inbound still having parts.
- Movable layout parts move only after right-click → "Drag to reposition…", never on a plain drag.

Worked examples: the template demo (pick · process · place cell) and `examples/burn-in-cell/`.
Compose with `threejs-glb-viewer` (inspect a GLB before placing it), `threejs-realism` (look pass),
`r3f-hero-camera` (cinematic shots), `interactive-3d-object` (hover/select on stations), `dataviz` (charts).
