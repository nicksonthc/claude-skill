---
name: r3f-hero-camera
description: Cinematic camera rig for a React Three Fiber scene, built on drei CameraControls — a reusable shot vocabulary (overview, 3/4 object framing, screen punch-in, first-person standpoint, chase engage), a stutter-free follow cam, an idle attract orbit that breaks on user input, perspective↔orthographic mode switching, and a writer-priority ladder so competing camera drivers never fight. Use when adding camera fly-to / framing on selection, a follow or chase camera for a moving object, cinematic tour or demo beats, a "focus on X" button, an idle attract loop, or a top-down ortho editor view to a three.js / R3F project.
---

# R3F Hero Camera

One rig, one discipline: **every cinematic move is a single damped
`setLookAt(..., true)`** on one drei `<CameraControls>`; the only per-frame camera
code is one exponential smoother feeding `moveTo(..., false)` for following. No
scripted per-frame paths, no timeline library — camera-controls' own damping is
the animator, and the user keeps orbit/zoom through every shot.

Built for **React Three Fiber 8 + drei 9 + three 0.169** (`camera-controls` under
drei). Copy-paste building blocks live in [REFERENCE.md](REFERENCE.md).

**Sibling skills this composes with:**
- `interactive-3d-object` — hover/select FX on the objects the camera frames.
- `guided-placement` — delegates its grab-framing stage to this rig.

## The shot vocabulary

Every shot is a pure recipe → one `setLookAt`. `d` = the scene's long side —
recipes scale with content, never hardcode world units.

| Shot | Recipe | Use for |
|---|---|---|
| **Overview** | eye `(d·0.8, d·0.6, d·1.1)` → scene center | establishing, reset, "complete" beat |
| **3/4 object frame** | eye = center + normalize(dir)·max(span·2.2, min) from `[1, 0.85, 1.25]` | click-to-focus on any object |
| **Screen punch-in** | eye = surface point + normal·((h/2)/tan(fov/2) + margin) | reading a diegetic screen full-frame |
| **Screen context** | eye = point + normal·far + cross(normal, up)·side | screen + its stand/surroundings |
| **First-person standpoint** | eye at ~1.6 world-height near a work point, slight lateral offset so the shot isn't dead-on | operator/visitor vantage |
| **Chase engage** | eye = object + `(2.4, 2.0, 3.0)` → object | entering follow mode |
| **Dolly beat** | `controls.dollyTo(dist, true)` only | tension change without re-aiming |

## The writer-priority ladder

Multiple systems want the camera. Gate every pose effect on everything above it
so exactly **one writer acts per event** — the follow smoother is the only
per-frame writer and yields to all of them:

```
manual user override (explicit view pick)
  > tour / scripted beat shots
    > selection framing (click-to-focus)
      > follow cam (per-frame)
        > idle attract orbit
```

## Workflow (checklist)

1. **Mount the rig** — one `<HeroCameraRig>` (REFERENCE §1): default camera +
   `<CameraControls makeDefault>` + scale-aware `maxDistance` (≈2.5× scene long
   side + a small flat term so tiny scenes don't clamp tight).
2. **Add shots as effects** — each trigger (selection, beat, button nonce) is a
   `useEffect` that computes one recipe and calls `setLookAt(..., true)`
   (REFERENCE §2–3). Gate each on the ladder above it.
3. **Follow cam** (moving objects) — the single-smoothing-stage `useFrame`
   (REFERENCE §4). Engage with a chase-pose `setLookAt`; seed the smoother from
   `controls.getTarget()` so the view glides over instead of snapping.
4. **Attract orbit** — `azimuthAngle += rate·dt` in `useFrame`, broken by a
   `controlstart` listener, re-armed on beat change (REFERENCE §5).
5. **Mode switch** (optional ortho top view) — swap `makeDefault` cameras; guard
   every pose effect with `camera.isPerspectiveCamera` / `isOrthographicCamera`
   and keep `camera` in the deps (REFERENCE §6).
6. **ESC ladder** — one keydown handler releasing the most specific state first:
   tour → beat step-back → stop follow (REFERENCE §7).

## Core principles

1. **Poses, not paths.** One damped `setLookAt` per beat. Sequenced shots =
   sequenced state changes, each firing its own pose. If a shot needs a curve,
   you almost always actually need two poses.
2. **Guided vantage, never lockout.** Every shot leaves rotate/zoom live; ESC
   always releases. Lockouts read as broken, not cinematic.
3. **One smoothing stage.** Per-frame `moveTo(..., smooth=true)` restarts the
   damped transition every frame on top of the target's own motion — double lag
   that reads as stutter. Smooth the target yourself
   (`k = 1 − e^(−rate·dt)`, ~12/s) and hand it over with `smooth=false`.
4. **User input cancels ambient motion, never intent.** `controlstart` breaks
   attract/auto-orbit for the rest of that cycle; it never interrupts a pose the
   user themselves triggered.
5. **Frame from live world transforms.** `getWorldPosition` / `getWorldQuaternion`
   on the actual object (via a ref registry), never from layout math that can
   drift from what's rendered.
6. **Recipes scale with content.** Distances derive from scene size, object
   span, or fov math — a rig full of magic constants breaks on the next scene.

## Pitfalls

- **Per-frame smooth `moveTo` = stutter** (principle 3). The #1 follow-cam bug.
- **Follow sampling order.** The follow `useFrame` must run AFTER whatever moves
  the target (movers at priority 0 → camera at priority 1), or it intermittently
  samples last frame's position — a one-frame lag that reads as jitter and
  churns with subscription order.
- **Pose fired at the wrong camera.** After a `makeDefault` swap there's a render
  where the old camera is still default. Guard with
  `camera.isPerspectiveCamera` and depend on `camera` so the effect re-fires
  once the right one is live.
- **"Focus" button pressed from the wrong mode.** Store a pending flag (or
  nonce + `pendingRef`), force the mode switch, and let the effect land the pose
  when the right camera arrives — don't `setLookAt` immediately and lose it.
- **Runaway zoom-out.** Derive `maxDistance` from scene size; a fixed constant
  lets a trackpad fling dolly into deep space (or clamps a big scene too tight).
- **Ortho top view must not rotate.** Zero `azimuthRotateSpeed`/`polarRotateSpeed`
  (tilt breaks click accuracy) and remap left-drag / one-finger to TRUCK so
  navigation stays one-handed.
- **Ortho frustum is yours.** With a `manual` OrthographicCamera, set
  left/right/top/bottom from content + margin, call `updateProjectionMatrix()`
  before framing, and `zoomTo(1)` — stale zoom from the last session skews the fit.
- **Two writers, one frame.** A pose effect and the follow smoother both writing
  = the pose loses silently. Gate the pose on `followId == null` or make
  engaging follow the pose (chase engage).
- **Punch-in distance is fov math**, not taste: `dist ≈ (h/2)/tan(fov/2)` for a
  screen of height `h` to fill the frame; add ~10% margin.
- **Never move the camera mid-drag** of a scene object — it shifts the
  pointer→world mapping under a stationary pointer (see `guided-placement`).
- **Timers for rides need a hard cap.** A "linger then return" ride (following a
  handed-off object) must also time out absolutely, or a blocked target parks
  the camera forever.
