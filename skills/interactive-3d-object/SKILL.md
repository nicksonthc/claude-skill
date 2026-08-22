---
name: interactive-3d-object
description: AAA hover/select feedback for interactive objects in a React Three Fiber scene — a design-token file so the whole feel is coherent and tunable from one place, a status→color language, a geometry-agnostic ObjectFX overlay (soft hover ring, breathing status-tinted select ring, click ripple, additive glow halo, select particle burst, floating label), a delayed hover tooltip that stays glued to moving objects, and action-preview telegraphing for HUD buttons. Use when making 3D objects hoverable/clickable, adding selection rings, glow or highlight effects, status color coding, object labels or tooltips, or "show what this button will do" previews in a three.js / R3F project.
---

# Interactive 3D Object

Turns any mesh/group in an R3F scene into a premium interactive object:
hover → soft ring + glow + cursor; click → ripple + burst + breathing select
ring + floating label; live status tints everything. Three layers, each a
single source of truth:

```
tokens.js    the FEEL   — colors, timings, easings; retune the whole system here
status.js    the MEANING — pure fn (kind, id, snapshot) → { status, label }
ObjectFX     the RENDER — geometry-agnostic overlay, all FX in ONE useFrame
```

Built for **React Three Fiber 8 + drei 9 + three 0.169**. Copy-paste code in
[REFERENCE.md](REFERENCE.md).

**Sibling skills this composes with:**
- `r3f-hero-camera` — flies the camera to the object this skill makes selectable.
- `guided-placement` — drag choreography on top of the same hover/select layer.

## The FX pieces

All mounted by one `<ObjectFX>` child at the object's footprint center; every
piece is driven by envelope tweens in refs — **zero per-frame React state**.

| Piece | Behaviour | Reads |
|---|---|---|
| **Hover ring** | thin cool ring, 120ms fade, hidden once selected | `hovered` |
| **Select ring** | expands `0.4→1` with easeOutBack overshoot (250ms), breathes, spins while busy, tints to status | `selected`, `status` |
| **Click ripple** | one-shot expanding ring, re-armed on select rising edge | edge of `selected` |
| **Glow halo** | additive billboard sprite (composer-free bloom stand-in): brightens on hover, blooms on select, breathes while busy | `hovered`, `selected`, `status` |
| **Particle burst** | ~16 points fly out + fall + fade (~600ms) on select | edge of `selected` |
| **Floating label** | drei `Html`, constant screen size, fades/slides in on single-select, `pointerEvents: none` | `selected`, `label` |

Single vs multi select get different accents (brand color vs blue) so "one" vs
"many" read at a glance.

## Workflow (checklist)

1. **Copy the three layers** — `tokens.js`, `status.js`, `ObjectFX.jsx`
   (REFERENCE §1–3). Map your domain's states into `STATUS_COLORS` keys
   (RUNNING / WARNING / ALARM / OFFLINE / NEUTRAL) in `status.js`.
2. **Wire each object** (REFERENCE §4): pointer handlers on its group
   (`stopPropagation`, cursor swap, hovered `{kind, id}` into shared state),
   `<ObjectFX>` as a child sized from the object's real footprint.
3. **Mount ONE `<HoverTooltip>`** at scene level (REFERENCE §5) — intent delay,
   anchor glued to the object every frame, content resolved per kind.
4. **Action previews** (optional, REFERENCE §6): HUD buttons spread
   `useActionPreview(intent)`; in-scene consumers telegraph the effect on hover.
5. **Tune in tokens only.** If a change needs edits outside `tokens.js`, the
   knob is missing from the token file — add it there.

## Core principles

1. **Discrete in state, continuous in refs.** React state changes only on
   hover/select/status *edges*; every per-frame value (envelopes, scales,
   opacities) lives in refs inside one `useFrame`. Dragging a slider through
   your scene should show zero re-renders from FX.
2. **Envelopes, not booleans.** Each signal drives a 0→1 envelope eased with
   frame-rate-independent damping (`k = 1 − e^(−rate·dt)`, rate derived from the
   token duration). Visuals multiply envelopes — hover ring × `(1 − sel)` hands
   over to the select ring with no pop.
3. **One-shots re-arm on rising edges.** Ripple and burst fire when `selected`
   flips false→true (tracked in a ref), never on re-render.
4. **Status is a pure function** of a state snapshot — no subscriptions, safe in
   `useFrame`, and every visual (ring, glow, tooltip, label dot) reads the same
   answer. Unknown object → OFFLINE, so a stale id never renders as "running".
5. **Geometry-agnostic overlay.** ObjectFX takes `radius` / `labelY` props from
   the object's real footprint — the same component serves a robot, a crate, a
   station. Never bake one object's dimensions in.
6. **Tooltip waits for intent.** 200ms delay, re-armed on every hover change —
   flicking the pointer across a crowd shows nothing.
7. **Subscribe narrowly.** Each object selects only *its own* hover flag and
   status from the store (`s.hovered?.id === myId`), not the whole hover object
   — or every pointer move re-renders the entire fleet.
8. **Previews telegraph, clicks commit.** Hovering a verb shows its effect
   (route, target, ghost); leaving clears it; clicking clears it too — the
   action commits, so a lingering preview is stale UI.

## Pitfalls

- **Emissive/FX colors wash out under tone mapping** — `toneMapped={false}` on
  every ring/glow/burst material. And saturated ≠ glowing: real halo = additive
  blending on a radial-gradient sprite (or selective bloom), not a brighter hex.
- **Ground rings z-fight the floor** — lift slightly (+0.01–0.03),
  `depthWrite={false}`, set `renderOrder` if stacked.
- **Html overlays swallow clicks** — every display-only `Html`
  (label, tooltip) needs `pointerEvents: none` or it eats the object's next
  `pointerdown` (often only after first selection — the "second click dies" bug).
- **Clamp dt** (`Math.min(dt, 0.05)`) in the FX `useFrame` — a tab-switch frame
  otherwise teleports every tween to its end.
- **`stopPropagation` on hover/click** or objects behind the pointer also fire;
  restore `document.body.style.cursor` on pointer-out and unmount.
- **Share one glow texture** (module-level CanvasTexture) — one per object leaks
  GPU memory across a fleet.
- **Stable typed arrays for particles** — allocate `Float32Array` once
  (`useMemo`), mutate + `needsUpdate`; recreating the attribute every burst
  reallocates GPU buffers.
- **X-ray/ghosting must clone materials.** GLTF materials are shared across
  clones — mutate one and every instance ghosts. Clone per mesh, stash the
  original in `userData`, restore AND `dispose()` the clone after
  (REFERENCE §7).
- **Cap live `Html` instances.** Labels on select-only (not hover-all) and one
  scene-level tooltip keep the DOM overlay count ~O(selection), not O(objects).
- **Hover state must survive fast object swaps** — key the hover as
  `{kind, id}` in one shared slot; per-object local `useState` strands a stuck
  ring when the pointer jumps between adjacent objects in one frame.
