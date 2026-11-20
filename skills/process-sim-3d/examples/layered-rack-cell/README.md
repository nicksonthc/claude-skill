# Worked example: layered-rack process cell

The kind of machine this skill was harvested from, described generically. Use it as the reference shape for a
large simulation: material in carts, a handler with robot arms, a lifter, and racks of layers that each hold a
work board for a long timed process (burn-in, soak, cure, test).

## Machine shape
- Trolley lanes: carts of stacked trays arrive at a handler; a singulator presents one tray per lane.
- Handler: 1 or 2 SCARA arms on one shared rail move units between trays and a work board (N sockets).
- Lifter: vertical axis + travel between racks + a telescopic push arm that slides boards in and out of layers.
- Racks: 1 or more racks × M layers; each layer clamps its board under process heads for the dwell time, with a
  coolant loop to every layer.

## How it maps to the skill
| Spec | Shape |
|---|---|
| unit / carrier | unit / tray / trolley / board (N sockets) |
| options compared | arms 1·2, racks 1·2, lanes in use, lane block position |
| sweep | process dwell, minutes to hours |
| components | cart, lane singulators, SCARA × 1–2 on a shared slider, lifter mast + carriage + shuttle, rack with head assemblies, coolant piping, operator |
| control logic | board job choice (load an empty board when units are available, else the oldest finished one), per-arm lane / socket split with hand-over, a bounded hold for a fresh trolley, operator docks before collecting |

## What the analysis answered (shape of the findings, not the numbers)
- How long one fill of every socket takes, and how much stock is still waiting in the trolleys at that point.
- The dwell time beyond which a second arm stops paying, found by bisecting the sweep.
- For long dwells: throughput sits at the rack ceiling (sockets ÷ dwell), the handler and lifter idle most of
  each cycle, so capacity scales with racks, not arms or lanes.

## Lessons it contributed
Every row of [../../references/pitfalls.md](../../references/pitfalls.md).
