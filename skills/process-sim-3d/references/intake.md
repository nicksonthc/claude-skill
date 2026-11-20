# Intake: deck / sheet / prompt → spec

Goal: a spec the engineer approves before any code. Every value has a **source**; every gap is a question.

## Read the inputs
| Input | How | What to pull |
|---|---|---|
| PPT / PPTX | the `pptx` skill (or `python-pptx`: text frames, tables, slide images) | layout drawing + dimensions (mm), station list, process-flow slide, index-time / cycle-time breakdown table, capacities (layers, sockets, slots), takt / UPH targets |
| XLSX / CSV | the `xlsx` skill (or `openpyxl` / `pandas`) | timing tables (step → seconds), speeds, quantities, cost / BOM, shift patterns |
| Prompt text | as given | the same fields; ask for the rest |
| Images (layout photos, screenshots) | Read tool | footprint, relative positions; mark dimensions `estimated from image` |

Convert to metres and seconds at intake. Keep the original value + unit in `src` (`"deck p.7: 1,200 mm"`).

## Extract into the spec (order matters)
1. **Product flow** — the unit (part, board, wafer, bundle), its carrier (tray, trolley, tote, board, rack
   layer) and how many per carrier. Write the flow as steps: `from → action → to (time)`.
2. **Stations & equipment** — one entry per physical thing: type (conveyor, robot, lifter, gantry, rack,
   chamber, cart, operator, buffer), position, size, capacity.
3. **Timings** — one `param` per configurable duration or speed. Durations in `s`, speeds in `m/s` — the
   unit decides how "+10% faster" is applied later.
4. **Options to compare** — the decisions the engineer is weighing (1 vs 2 robots, 1 vs 2 racks, lane count).
5. **Targets & costs** — required UPH, relative or real cost per module (for sizing). Placeholders are
   allowed but must be labelled placeholders on screen.

## Question checklist (ask only what is missing; batch them)
- What is one unit, what carries it, how many per carrier?
- Where does material come from (operator trolley, conveyor, AGV) and how often (continuous / lot of N)?
- For each step: duration or speed + distance? Who does it (which machine / person)?
- Shared resources: what can only do one thing at a time (one lifter, one rail, one operator)?
- Priorities: when two jobs compete (load vs unload), which first?
- Holds: does anything wait for a full batch / a fresh carrier, and for how long at most?
- Capacity: slots / layers / sockets per station; how many stations?
- What decision should the sim inform (arm count, rack count, lanes, cycle time target)?
- Walkthrough only: which shots and captions tell the story best?

## Walkthrough first, simulation later
A walkthrough needs only layout + flow order + rough durations (animation pacing). To upgrade, the engineer
supplies component-to-component flow, real timings, capacities and priorities — then rewrite `sim.js`
control logic and switch `spec.mode` to `'simulation'`. The world and the panels stay.

Done when: the spec file exists, every param has `src`, open questions are answered or explicitly
`assumed`, and the engineer has said the spec is right.
