# Visuals: renderer, look, camera, labels

## Renderer + look (template `main.js`)
- `NeutralToneMapping`, `RoomEnvironment` at ~0.34 intensity, hemisphere fill + one shadow-casting key
  light whose shadow frustum covers the footprint (resize it when the layout grows — a second rack moved
  the footprint by 2.6 m).
- **Bloom keyed on saturation**, not luminance: hot cells, LEDs and stack lights glow; white paint and
  metal highlights never haze. The high-pass shader is in the template.
- Enclosure modes: Solid / Glass (skin material 7% opacity, depthWrite off, renderOrder above glass) / Off.
  Skins and glass are separate merged meshes so the toggle is two loops.
- State colours: emissive on a per-slot material (`idle` off, `loading` amber, `busy` red, `cool` cyan,
  `done` green). The same colours label the flow steps (`cls: 'hot' | 'cold'`).
- For a photoreal pass (HDRI, AgX, GTAO, baked light) hand the scene to `threejs-realism`.

## Camera rig (`core/rig.js`, both stacks)
- macOS trackpad pinch = ctrl+wheel → swallowed and re-dispatched as a plain wheel × 3 (dolly), so the lens
  never changes and min/maxDistance hold. `minZoom = maxZoom = 1`.
- Tilt clamped `0.08 … π/2 − 0.04`; target clamped to the scene box (`spec.camera.clampTarget`).
- Cmd/Ctrl-drag pans (OrbitControls swaps itself while the modifier is held — keep LEFT = ROTATE).
- Views from `spec.views` fly with smoothstep over ~1.1 s; any pointer or wheel input cancels the flight
  and turns auto-cam off.
- Auto-cam: pick the view from the active status flags (handling → robot view, dwell start → cells,
  transport → conveyors), at most one cut every ~3.5 s.
- Views that follow a movable part (lanes block, a carriage) compute their target from its current position.
- Cinematic shot language (3/4 framing, punch-in, follow) → `r3f-hero-camera`.

## Labels
World-anchored DOM tags (`createLabels`): projected each frame, hidden behind the camera, off-screen, too
close (< 1.2 m) or too far (9 m small / 26 m big). Labels of a movable group store `cell: true` and get the
group offset added. Keep labels short ("SCARA arm 1", "Test rack 2 · 8 layers").

## Performance
- Merge static geometry (Batch) — a whole cell is a handful of draw calls.
- Prototype + `instantiate` for repeated items (parts, trays, carts): shared geometry.
- DPR ≤ 2; a perf watchdog can drop to DPR 1 and disable AO if frames average > 36 ms after warm-up.
- Skip `composer.render()` while headless experiments run (`S.busy`).
