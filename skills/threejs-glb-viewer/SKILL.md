---
name: threejs-glb-viewer
description: Show a Blender-exported GLB on a web page with three.js or React Three Fiber — a zero-dependency GLB report (bounding box, triangles, draw calls, required loader extensions), a self-contained single-file viewer, and the discipline that makes them right: frame the camera from the model's measured box, load through GLTFLoader with DRACO/KTX2/Meshopt, orbit with OrbitControls, and post-process with EffectComposer where OutputPass is what keeps the colours matching Blender. Use whenever a .glb/.gltf has to be displayed, inspected, previewed, framed or debugged in the browser — "show this model in three.js", "load a GLB with GLTFLoader", "add OrbitControls", "add bloom / post-processing / DoF", "build a model viewer or turntable", a gallery of models from a manifest, or when a model comes out black, washed out, invisible, tiny, off-centre or upside down.
---

# three.js GLB Viewer

A GLB is a black box until something draws it. This skill is the short path from
`object.glb` to a page that shows it honestly — and the discipline that keeps the
viewer correct when the model changes underneath it.

**The one idea: measure the model, then derive everything from the measurement.**
Camera distance, near/far, orbit target, orbit limits, light position, shadow
frustum, ground plane and grid step all come out of one `Box3`. Hardcode a camera
position instead and the viewer works for exactly one asset — swap in a model
twice the size and you are staring at the inside of a wheel.

Built against **three 0.186** (and R3F 9 / drei 10 / @react-three/postprocessing 3).
Copy-paste code for both runtimes is in [REFERENCE.md](REFERENCE.md).

**Sibling skills:**
- `image-to-3d-blender` — makes the GLBs this skill displays, and writes the
  `manifest.json` the gallery mode reads.
- `r3f-hero-camera` — when the camera has to *act* (fly to, follow, tour), not just
  orbit. OrbitControls is the right tool for inspecting one object; swap to
  CameraControls the moment you want scripted shots.
- `interactive-3d-object` — hover/select feedback once the model is on screen.
- `r3f-scene-world` — many models placed in a world, rather than one under a light.

## 1. Measure before you render

```bash
node <skill>/scripts/glb-report.mjs model.glb          # add --json for machine output
```

No dependencies — it reads the GLB's JSON chunk directly, so it runs in any repo.
It prints the world bounding box, whether the model sits on Y=0, triangle and
primitive counts, materials, texture payload, animations, which extensions force
which loader, and the camera/grid numbers derived from the box. Most "the model
doesn't show up" reports are answered here without opening a browser: wrong units,
minY miles below zero, an empty export, or a `KHR_draco_mesh_compression` file
being handed to a bare GLTFLoader.

## 2. Look at it

```bash
cp <skill>/scripts/viewer.html .          # next to the .glb
python3 -m http.server 8080
open "http://localhost:8080/viewer.html?src=model.glb"
```

Self-contained, no build step, three.js from a pinned CDN. It auto-fits from the
box, lights with a PMREM environment, orbits with damping, runs the full
post-processing stack, and puts the measurements plus any warnings in a HUD.
Drag a `.glb` onto the page to swap models. Keys: `r` turntable, `p` post on/off,
`b` bloom, `g` grid, `w` wireframe, `f` refit, `s` save PNG, `h` hide HUD.

Bloom starts off on purpose — SMAA and `OutputPass` are correctness, bloom is
taste, and glow hides the seams and inverted normals an inspector is for. Press
`b` or pass `?bloom=0.4` when the job turns from inspecting to presenting.

Gallery mode reads an `image-to-3d-blender` manifest:
`?manifest=manifest.json`. Other params: `bg`, `bloom`, `threshold`, `exposure`,
`env=none`, `rotate=1`, `post=0`.

`window.__viewer` exposes `{ scene, camera, controls, composer, renderer, model,
info, fit }` so a Playwright or browser session can drive and assert on it instead
of clicking.

## 3. The three pieces, and what actually goes wrong

**GLTFLoader.** Plain `.glb` needs nothing. Compressed ones do, and the file says
which: `KHR_draco_mesh_compression` → `DRACOLoader`, `KHR_texture_basisu` →
`KTX2Loader` (needs `.detectSupport(renderer)`), `EXT_meshopt_compression` →
`MeshoptDecoder`. Wire all three once and you can open anything. Decoder files are
fetched at runtime, so the path has to be served — a 404 there reads as "the model
is broken".

**OrbitControls.** `target` belongs at the bounding-box *centre*, not the origin,
or an off-centre model swings around a point outside itself. With
`enableDamping` or `autoRotate`, `controls.update()` must run every frame — leave
it out and the model simply will not move. Clamp `maxPolarAngle` just under π/2
for a grounded model so the camera cannot crawl under the floor.

**Post-processing.** The stack is `RenderPass → bloom → SMAAPass → OutputPass`,
and the last one is not optional: three applies tone mapping and the sRGB
conversion only when rendering to the screen, so the moment a composer renders
into a target that work has to be done by `OutputPass` instead. Without it
everything comes back flat and dark, and people then "fix" it by raising exposure
until the highlights clip. Note also that `antialias: true` on the renderer is
dead once the composer owns the frame — that is what `SMAAPass` is for.

## 4. Colour management — the four lines that decide whether it matches Blender

```js
renderer.outputColorSpace = THREE.SRGBColorSpace
renderer.toneMapping = THREE.ACESFilmicToneMapping
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture
composer.addPass(new OutputPass())   // last, always
```

A PBR export with no `scene.environment` renders metals black and roughness flat,
because there is nothing for them to reflect; that alone explains most "my model
is black" reports. An environment is lighting, not decoration.

## 5. The gate — what to look at before calling it done

Open the model and check, in this order. Each failure points at Blender, not at
the viewer:

| Symptom | Cause |
|---|---|
| Nothing on screen | empty export, or the camera is inside the model — read the report's box |
| Wrong size in the HUD | scene units (mm/cm exported raw); fix in Blender, never with a scale factor in the viewer |
| Floats or sinks | origin not on the floor — everything downstream (shadows, grids, placement) inherits this |
| Swings when orbiting | off-centre origin |
| Lying on its face | Blender Z-up written through; glTF is Y-up |
| Black / mirror-like | no environment map |
| Washed out or dark | missing `OutputPass`, or tone mapping set twice |
| Magenta or untextured | texture failed to load, or KTX2 without the transcoder |
| Facets dark from one side | inverted normals — `w` for wireframe, and turn off double-sided to see them |
| Fine but slow | check draw calls in the HUD, not triangles; 3,000 primitives means 3,000 calls |

## 6. In a React app

Same discipline, different spelling: `useGLTF` for the loader, drei's
`<OrbitControls makeDefault>`, `<Bounds fit clip observe>` in place of the manual
fit, and `@react-three/postprocessing` for the stack — where `<ToneMapping>` as the
last effect plays the role `OutputPass` plays in vanilla. Full component in
[REFERENCE.md](REFERENCE.md#react-three-fiber).

Two R3F-only traps: `useGLTF` caches by URL, so mutating the returned scene mutates
every other user of that model — clone it (`<Clone>` or `useGraph`) before touching
materials. And a model inside `<Suspense>` has no size on the first frame, so fit
after it resolves (`<Bounds observe>`) rather than in a layout effect.

## Pitfalls that each cost an iteration

- **Quantized bounds.** `KHR_mesh_quantization` stores POSITION as normalized
  integers, so the accessor's own min/max are raw ints — decode them or a 1 m
  trolley measures 34,539 units. three.js handles this; anything reading the JSON
  yourself must not forget it.
- **Bloom threshold below 1.** Bloom runs on the linear HDR buffer *before* tone
  mapping, where a white surface lit by an environment already sits near 1.0. At
  0.85 an untextured CAD model turns to fog and its real colours wash pink. Start
  at 1.4 and lower only until genuine emissives glow.
- **Swapping models leaks the GPU.** Removing a scene does not free its buffers;
  traverse and dispose geometries, materials and textures, or the tab dies on the
  tenth model.
- **`THREE.Clock` and `PCFSoftShadowMap` are deprecated** in r183/r186. Take `dt`
  from the `setAnimationLoop(time)` argument — that also avoids depending on which
  three version is installed.
- **Headless verification stalls.** Under Playwright + SwiftShader, rAF stops
  without input; nudge with a few `page.mouse.move()` calls before screenshotting,
  or the HUD and any animation will look frozen.
