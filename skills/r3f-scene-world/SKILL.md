---
name: r3f-scene-world
description: Build and maintain a large hand-authored 3D world in React Three Fiber — one deformable authoring frame shared by procedural geometry, placed GLB models, scattered instances and camera routes; tens of thousands of primitives merged into a few draw calls; an instanced-vegetation triangle budget; a store/useFrame split that keeps per-frame values out of React; a first-person scroll-driven tour with exactly one camera owner; and Playwright checks that screenshot the world instead of trusting it. Use when building a town, landscape, campus, factory or level scene, placing many GLB models from config, scattering trees/props by rule, authoring a guided walkthrough or fly-through, or when a big R3F scene has gone slow, unverifiable or impossible to re-place.
---

# R3F Scene World

A world scene is four things that must agree: **a coordinate frame**, **bulk
geometry**, **placed models**, and **whatever moves through it**. This skill is
the discipline that keeps them agreeing as the world grows past the point where
anyone can hold it in their head.

Proven on React Three Fiber 9 + drei 10 + three 0.180 + Vite + Zustand 5,
TypeScript strict. Copy-paste building blocks: [REFERENCE.md](REFERENCE.md).

**Sibling skills:**
- `r3f-hero-camera` — interactive framing (poses, not paths). Use it for
  click-to-focus, follow and attract. Use §6 here only for a *continuous
  scripted walk*, where the path itself is the content.
- `image-to-3d-blender` — how the GLB studies this skill places get made.
- `interactive-3d-object`, `guided-placement` — hover/select and drag-to-place
  on top of the world.

## The authoring frame — the idea worth stealing

Pick the frame you can *read*, author everything in it, and map to the world
with one pure function that every layer imports.

A canal town is the worked example: the canal is straight in the authoring
frame (banks at X ±5.1, Z along the water) and bent in the world by
`center(z)`. The same applies to a curved street, a rail line, a conveyor, a
ridge — anything with a spine.

| Layer | Authored as | Mapped by |
| --- | --- | --- |
| Bulk geometry | straight-frame primitives | the same `bend()` applied to the batch |
| Placed models | `place(name, model, [x, y, z], …)` | `lateral(x, z) + center(z)` |
| Scattered instances | `(x, z)` on a bank/verge | `bend()`, plus a mask that keeps them off the spine |
| Camera route | keys in the straight frame | `bend()` at module load |

**Exactly one deformation module.** When something genuinely does not follow
the spine — a side branch, a building set back in open ground — it gets a
second constructor (`placeWorld`) in honest world metres, and the reason goes in
a comment at the call site. A world with two competing mental frames is a world
nobody can place anything in.

## Workflow

1. **Fix the conventions first** (REFERENCE §1) — units, up axis, spine axis,
   ground/water/floor heights, the sign of "north". Write them at the top of
   the frame module; every later magic number is read against them.
2. **Author the deformation** — `center`, `width`, `lateral`, and a mask
   (`isSpine(x, z, pad)`) that carves the spine out of the ground and keeps
   scatter out of it.
3. **Build bulk geometry imperatively, batched per material** (§2). Not JSX:
   30 k primitives as React elements is a fibre per brick for geometry that
   never changes. Mount the result as one `<primitive>`.
4. **Make placement data** (§3) — one typed array of `{name, model, position,
   rotation, scale, dimensions}`, each entry carrying a comment saying *why* its
   offset is that offset. Wrap each in a store-backed root so an editor can move
   it without the scene and the panel ever disagreeing.
5. **Scatter by rule with a budget** (§4) — placements from a seeded RNG,
   grouped into one `InstancedMesh` per material per spatial band, with only a
   near subset casting shadows.
6. **Keep per-frame values out of React** (§5) — components that need a value
   every frame call `store.getState()` inside `useFrame`; a scroll/route
   coordinate lives in a module ref, never in state.
7. **Move through it** (§6) — hero shots for interaction, an authored route for
   a scripted walk. One writer per frame, always.
8. **Verify with pictures** (§7) — a Playwright check that gates on a ready
   flag, seeks to fixed coordinates, screenshots each stop, and probes
   clearance and mounting. A world is not verified by a passing type check.

## Core principles

1. **One frame, one deformation.** Every layer imports the same functions.
2. **Merge before you mount.** Bulk geometry is one mesh per material; the
   scene graph is for things that move or get clicked.
3. **Placement is data, with reasons.** A transform without a comment is a
   number nobody may ever touch again.
4. **Budget the scatter.** Detailed vegetation is a triangle budget, not a
   count: decide the allowance, then spend it in bands.
5. **Per-frame belongs to the renderer.** Anything changing at 60 Hz that
   passes through React state re-renders the canvas subtree at 60 Hz.
6. **One camera writer per frame.** Unmount the controllers you are not using —
   disabled damping still writes.
7. **Measure before you author.** Read real bounding boxes out of the running
   scene before writing a camera key or a placement against them.
8. **Verified means photographed.** Stills at fixed coordinates, committed to
   an artifacts directory, reviewed by eye.

## Pitfalls

- **Two camera owners.** `OrbitControls` (or any damped controller) keeps
  writing after you "disable" it. Do not mount it on a page that drives the
  camera itself; the check should assert the controls handle is null.
- **A check that loads the wrong page still passes.** Multi-page dev servers
  fall back to the root document, so a route check can screenshot the *other*
  page and go green. Assert something only the page under test has.
- **Authoring a camera against guessed geometry.** Deck heights, overhangs and
  lane widths are never what you assume. Dump bounding boxes from the live
  scene first (§7.2); a 2.6 m lane and a 10 m building over a 9 m channel change
  what shots are even possible.
- **Range boundaries that land on the next range.** `t >= a` chapter/zone lookup
  plus a stop authored exactly at the next boundary labels every stop one late.
  Park stops strictly inside their range.
- **Instanced foliage as collision.** Exclude `InstancedMesh` from clearance and
  walk probes — a branch through the lens is scenery; a wall is not.
- **Trees planted where people walk.** Scatter rules and walking routes both
  want the same strip of bank. Give the walk its own lane in the frame and
  assert the gap, or the opening shot is inside a crown.
- **Shadow maps re-rendered every frame** for a sun that never moves. Cache
  (`shadowMap.autoUpdate = false`) and refresh on load, on edit, on chapter
  change. It is usually the single biggest cost in the scene.
- **Shadow camera smaller than the world.** Anything outside the ortho box is
  flat-lit; either extend the box, accept it, or keep the route inside it.
- **Near plane tuned for an overview.** At eye height, 0.3 clips walls open; use
  ~0.12 and re-check depth precision on distant landmarks.
- **Content scanners crawling the asset directory.** A committed `public/models`
  of 50 MB+ will stall Tailwind v4 (or any scanner) on autodetection. Use
  explicit sources and add a line whenever a page is added.
- **Editor transforms are session-only.** A store-backed editor is not
  persistence; copying the exported JSON into the config is a manual step, and
  it needs saying out loud in the docs or placements silently regress.
- **Dead code that is actually a parts library.** If an unused module is kept on
  purpose, say so where someone would delete it as cleanup.
- **Software-rendered CI frames are slow.** Playwright on swiftshader can need
  60–180 s for one frame of a heavy scene; set the timeouts, seek by an exposed
  handle instead of scrolling and hoping, and keep viewports modest.
- **Disposal on hot reload.** A memoised imperative world outlives the component
  unless it disposes its own geometry, materials and maps.

## Related public skills

[MengTo/Skills · agent-skills/3d](https://github.com/MengTo/Skills/tree/main/agent-skills/3d)
is a good companion set, written for vanilla three.js in a single file — take
the reasoning, not the code, and never a second `requestAnimationFrame` loop.
`3d-virtual-tour` informed §6 here (route authoring, one camera owner, stop
registry, inspection handoff). `3d-high-poly-models` (LOD) and `3d-four-seasons`
pair well with §4. `3d-retina-resolution` conflicts with any scene that caps DPR
and runs `AdaptiveDpr`: at four times the fragment cost, a fill-bound world
cannot pay for it.
