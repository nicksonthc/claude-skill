---
name: guided-placement
description: Multi-stage drag-to-place choreography for a React Three Fiber scene — click an object → glow + anticipation dip, soft lift, a flowing path, a holographic ring on the candidate slot, gentle camera framing, a magnetic snap with proximity telegraph, then a scale "pop" with a green ripple and a checkmark on success. Placement is object-aware via policies: a fixed single slot, or free placement over any valid position (grid cells, zones) with per-object validity rules. Use when adding guided pick-and-place, "drag this there", drag-to-relocate on a grid, assisted object relocation, tutorial placement hints, or staged visual guidance from grabbing an object to dropping it on a target.
---

# Guided Placement

Turns a draggable R3F object into a guided, game-like **pick → carry → snap → placed**
experience. One small state machine drives a set of **composable stages** — a full default
choreography out of the box; drop or reorder any stage.

Built for **React Three Fiber 8 + drei 9 + three 0.169**. The teaching example is a generic
*object → destination*; the policy system maps it onto bins, robots, or anything else.

**Sibling skills this composes with:**
- `interactive-3d-object` — general hover/click/label/fly-in. This skill re-teaches only the
  glow bit so it stands alone.
- `r3f-hero-camera` — the camera rig. Stage 5 (framing) delegates to it when present; a
  `CameraControls.fitToBox` fallback is included.

## Object-aware placement policies

**What the grabbed object IS decides where it may land.** The hook takes a `policy`, not a
bare target:

| Policy | Meaning | Example |
|---|---|---|
| `fixedTarget([x,y,z])` | One slot; drop commits within `snapRadius` of it | a bin that belongs in one rack cell |
| `freePlacement(resolve)` | `resolve(worldPoint) → { point, valid, ...meta } \| null`; the candidate slot follows the pointer | a robot that may park on **any valid grid cell** |

`resolve` is where per-object constraints live: quantize to a grid cell, check bounds /
occupancy / forbidden zones, return `valid: false` to show the slot as rejected (ring turns
red, drop reverts). The choreography is identical either way — only the candidate source
differs. Different object types = different `resolve` functions, nothing else changes.

## The stages → the state machine

Phases are discrete (React state → which stages render). Position, lift, scale, magnet
weight are **refs** stepped in `useFrame` — dragging never re-renders.

```
 idle ─pointerdown─▶ selected ─move─▶ dragging ─drop on valid candidate─▶ snapping ─▶ placed ─settle─▶ idle
        grab dip,       │                 │                                  pop + ripple + check, rehome
        camera frame    └── glow + lift ──┘              drop invalid/far ─▶ reverting ─▶ idle (descends home)
```

| # | Stage | Active in | Built from |
|---|-------|-----------|-----------|
| 1 | **Glow outline** | selected → snapping | drei `<Outlines>` |
| 1b | **Anticipation dip** | grab (first ~120ms) | scale squash 1→0.95→1 *before* the lift |
| 2 | **Soft lift** | after the dip → drop | damped `y` offset (drops during revert too) |
| 3 | **Flowing path** | dragging · snapping | bezier arc + travelling beads (`home→candidate` or `object→candidate`) |
| 4 | **Holo candidate ring** | selected → snapping | rotating torus at the candidate; **green = valid, red = invalid**; pulse rate + brightness scale with magnet proximity |
| 5 | **Camera framing** | on **grab** (pointer down) | delegate to `r3f-hero-camera` / `fitToBox` — see pitfalls |
| 6 | **Magnetic snap** | dragging (blend pull) · snapping (commit) | proximity-weighted blend **with hysteresis** |
| 7 | **Pop + ripple + check** | placed | asymmetric pop + expanding green ring + checkmark that fades out |

## Workflow (checklist)

1. **Copy the core** — `useGuidedPlacement` + policies from [REFERENCE.md](REFERENCE.md).
   No drag-plane mesh: the object itself is pointer-captured and pointer moves intersect
   `e.ray` with a **math plane** at lift height.
2. **Pick the policy** — `fixedTarget(...)` or `freePlacement(resolve)` with your object's rules.
3. **Wrap your object** with `<GuidedPlacement>` (or spread `bind` yourself) — all stages wire up.
4. **External position owner?** If a sim/fleet/physics system writes the object's transform
   every frame, it must **yield during the gesture** — copy the `placementDrive` pattern
   (REFERENCE §7). Skipping this makes the two writers fight and the object teleports.
5. **Camera** — pass `onGrab(box)`; delegate to your rig. **Skip it entirely in an ortho
   top-down editor view** — the user already has the framing they chose.
6. **Tune the feel** — `liftHeight`, `snapRadius` (magnet engage), `releaseRadius` (magnet
   let-go, default 1.35× — the hysteresis gap), `magnetStrength`, pop/settle durations.

## Core principles

1. **Phases in state, motion in refs.** setState only on phase edges; everything per-frame is refs.
2. **Capture on the object, raycast a math plane.** Pointer capture routes all events to the
   captured object — a separate plane *mesh* goes deaf the moment capture succeeds. So the
   object handles its own `onPointerMove` and intersects `e.ray` with a `THREE.Plane`.
3. **The magnet is felt AND seen.** Blend weight grows nonlinearly toward the slot center
   (gravity-well, not constant tug), engages/releases at different radii (hysteresis — no
   boundary flicker), and the same weight drives the ring's pulse rate/brightness so the user
   *sees* "you're in the zone" before releasing.
4. **Anticipation before action.** ~120ms squash on grab, then lift. That beat is what makes
   it feel picked up instead of switched on.
5. **Endings resolve, don't cut.** Asymmetric pop (fast attack, slow settle), ripple, check
   pops in *after* the pop peak and fades out before the settle — no dead air, no hard unmount.
6. **The user's pointer always wins.** Magnet blends the *intent*, never overrides it; camera
   never moves while the pointer is down and dragging.
7. **Rehome on success.** The slot becomes the new `home` so a later grab-and-miss reverts to
   where the object now lives, not where it was born.

## Pitfalls

- **Pointer capture + separate drag-plane mesh = dead drag.** Captured events go only to the
  capture target. Use the math-plane pattern (REFERENCE §1); never a raycastable plane mesh.
- **Revert must drop the lift.** If lift stays up during `reverting`, a 3D distance-to-home
  check never passes (it includes the lift!) and the FSM wedges. Descend during revert, check
  XZ distance + lift ≈ 0.
- **Never move the camera mid-drag.** It shifts the pointer→world mapping under a stationary
  pointer — the object slides on its own. Frame on grab (pointer down), or not at all.
- **Scene camera controls ride along with the drag.** OrbitControls/CameraControls listen on
  the canvas DOM — R3F `stopPropagation` cannot stop a left-drag pan/orbit from ALSO firing
  (runaway feedback: the world shifts under the pointer, the object chases it off-map). Set
  `controls.enabled = false` on grab, restore on settle/revert/unmount.
- **DOM overlays over the object swallow the grab.** A drei `<Html>` label/chip floating on
  the object eats `pointerdown` before the canvas sees it — and it often appears only after
  the first interaction (selection chip), so the SECOND grab mysteriously dies. Put
  `style={{ pointerEvents: 'none' }}` on every display-only overlay.
- **Two position writers fight.** Any per-frame driver (fleet, physics) must check
  `placementDrive.activeId` and yield; on commit, invalidate its cached runtime so it re-seeds
  from the new location (no snap-back).
- **Emissive rings wash out under tone mapping** — `toneMapped={false}`; and saturated ≠
  glowing: for a real halo add selective bloom or an additive gradient sprite.
- **Z-fighting on ground rings** — lift `+0.015`, `depthWrite={false}`, set `renderOrder`.
- **Ring must read as a slot, not a decoration** — size it from the object/cell footprint
  (~1.1–1.3×), never a hardcoded radius.
- **`Html` checkmark is non-diegetic** — it floats over the scene, ignores occlusion. Fine for
  most apps; swap for a sprite in scenes with diegetic screens.
- **Cursor + touch**: `grab` on hover, `grabbing` while carrying, restore on release; set
  `touchAction: 'none'` on the canvas or touch drags scroll the page instead.
- **Mid-gesture invalidation**: if the object's owner state changes under the drag (a robot
  gets dispatched a job), abort → `reverting`. Check it in the hook's `useFrame`.
