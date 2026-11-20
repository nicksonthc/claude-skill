# Worked example: automated burn-in cell

The project this skill was harvested from. Use it as the reference for a large simulation.

## Machine (from the deck)
- 8 trolley lanes (16 JEDEC trays × 2 GPU units per trolley) → handler with 1 or 2 SCARA arms on one rail →
  lifter (vertical + rack-to-rack travel + telescopic push arm) → 1 or 2 test racks × 8 layers × 4 sockets.
- Per layer: burn-in board (BIB, 4 sockets), 4 thermal heads that press down, CDU coolant loop to every layer.
- Timings: deck "index time breakdown" (SCARA 6.5 s/unit, lifter 0.3 m/s, push/pull 5 s, burn-in 20 min–12 h).

## How it maps to the skill
| Spec | Value |
|---|---|
| unit / carrier | GPU unit / JEDEC tray (2) / trolley (16 trays) / board (4 sockets) |
| options compared | arms 1·2, test racks 1·2, lanes in use 4–16, lane block position (left/center/right) |
| sweep | burn-in 5 min … 12 h |
| components | trolley cart, singulator lanes, SCARA ×1–2 on a shared slider, lifter mast + carriage + shuttle, rack with thermal head assemblies, CDU + piping, operator |
| control logic | board job choice (load empty first when units available, else oldest tested), per-arm lane/socket split with hand-over, 150 s hold for a fresh trolley, operator dock-before-take |

## Results it produced (2 racks, 1 arm, 8 lanes, 16 trays, default deck timings)
- Fill all 64 sockets: 15 min 22 s; 192 units still waiting in the trolleys.
- 2nd arm: +29.6% at 5 min burn-in, +6% at 20 min, ≤ 1.5% from 30 min, +0.2% at 6 h → 1 arm beyond ~20 min.
- 6 h burn-in: 10.6 UPH (rack ceiling 10.7); arm and lifter idle ~5 h 45 min per cycle → capacity scales
  with racks, not arms.

## Lessons it contributed
Every row of [../../references/pitfalls.md](../../references/pitfalls.md) up to the debug-print one.
