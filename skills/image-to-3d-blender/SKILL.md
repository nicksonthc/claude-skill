---
name: image-to-3d-blender
description: Turn a reference image into a GLB 3D asset with headless Blender, plus transparent preview render, editable .blend and a manifest entry. Two routes — flat/transparent images (logos, signs, tokens, icons) become an extruded silhouette; volumetric subjects on opaque backgrounds (buildings, boats, trees, figures, furniture, street props) become reference-guided procedural studies built from a shared helper library. Use when asked to "craft a 3D object from this image", "make a GLB/model from this picture", "image to 3D", "build this in Blender", batch-model a folder of reference images, or add assets to a GLB inspector/manifest. Never claims faithful single-image reconstruction of unseen geometry.
---

# Image to 3D with Blender

Produce a reproducible Blender-generated asset from one reference image: `object.glb`
(web-ready), a transparent preview PNG, the editable `.blend`, and a JSON entry.
Preserve the source image; write only into the output directories.

Blender runs headless: `--background --factory-startup --python <script>`. Use
`$BLENDER_BIN`, `blender` on PATH, or `/Applications/Blender.app/Contents/MacOS/Blender`.

## Choose the route

Read the image first (the Read tool shows it). Then:

- **Transparent PNG, or near-white background, and the object is essentially flat**
  (logo, badge, sign, token, control panel): the **silhouette route**.
- **Volumetric subject on an opaque background** (a building, boat, tree, person,
  stall, bridge, lantern): the **study route**. The extruder would give a cardboard
  cut-out; a study interprets the unseen sides plausibly and says so.
- **A mesh supplied by a reconstruction service**: Blender only for cleanup, scaling,
  orientation, material repair, preview and GLB export. Never run the extruder on it.
- **A photoreal object whose back and depth matter**: say that one image is
  underconstrained, ask for more angles or an authorised reconstruction backend, then
  validate in Blender.

## Silhouette route

```bash
<skill>/scripts/run.sh /abs/reference.png /abs/output-dir [--thickness .16 --size 2 --resolution 192 --background alpha|white]
```

Writes `object.glb`, `preview.png`, `object.blend`, `manifest.json`. Settings and the
iteration order (mask → contour → thickness/bevel → scale/origin) are in
[reference/silhouette-quality.md](reference/silhouette-quality.md).

## Study route

1. Read [REFERENCE.md](REFERENCE.md) for the `studio.py` API, the generator shape, and
   the pitfalls. Copy `scripts/generator_template.py` to `craft_<slug>.py` next to the
   other generators in the consuming project; import `studio.py` by absolute path (or
   copy it into the project once and import that).
2. **Scale and orientation first.** Metres, Z up, ground or waterline at Z=0, the side the
   reference shows facing −Y. Pick real-world sizes (people 1.6–1.7 m, doors ~2 m, a
   storey ~3 m, a small boat 5–6 m) and write the reason for every magic number as a
   why-comment.
3. **Build coarse to fine.** Massing → structure → cladding at element scale (individual
   tiles, planks, voussoirs, leaves, blossoms) → props and weathering (damp bands, moss,
   stains, rope). Materials come from `studio.mat`, which bakes a small grain texture per
   material so per-material draw calls stay few.
4. **Run, then compare the preview side by side with the reference.** Iterate at least
   three times: proportions and silhouette, then colour and contrast, then small-scale
   detail. The preview is the acceptance test; a successful export proves nothing.
5. **Gate before you stop:** grounded at Z=0; plausible scale; every unseen side closed
   (render a rear view from the saved `.blend` to check); legible characters in the image
   reproduced with `text_banner` and a real font, blank plaques left blank, no invented
   pseudo-text; budget met (figures and props under ~80k triangles / 3 MB, buildings under
   ~200k / 8 MB unless told otherwise).
6. `python3 <skill>/scripts/merge_manifest.py [out_dir]` folds the entry files into
   `manifest.json`. Then check the consuming loader actually renders the GLB.

**Parallel batches.** One generator per image and one agent per generator; generators
write `<slug>.entry.json` and never the manifest, so agents cannot collide. Review each
preview against its reference yourself and send weak ones back with specific fixes
(framing, contrast, a missing element). A coordinator that only forwards reports ships
weak assets.

## Language

Describe results as reference-guided artistic studies with interpreted unseen sides,
never as accurate reconstructions or scans.

## Pitfalls (each cost an iteration once)

- **Factory cube.** `clear_scene()` before building, or a 2 m cube ships in the GLB.
- **Two colour spaces.** Grain textures were sRGB while plain colours are linear, so plain
  materials rendered several times brighter than textured neighbours. This copy writes grain
  pixels sRGB-encoded so both decode to the same linear value; the studio light still lifts
  every albedo, so pick colours a step darker than the photo reads.
- **Coplanar overlaps render black in Cycles.** Sink overlapping faces a centimetre into
  their neighbour or meet them edge to edge.
- **Framing.** Tall or cubic subjects clip in the default orthographic frame: raise
  `margin` or lower `view`. Buildings need a low `view` (Z ≈ .4–.55) or the roof fills
  the thumbnail and the facade, which is the point, disappears.
- **Studio light lifts everything.** Foliage and whitewash need `light` .5–.7; deep porches
  still go dark, so lift timber albedo rather than adding lights the GLB cannot carry.
- **Scale drift in foliage.** Leaves that look right as spheres look like balloons next to
  a trunk; model leaf-scale elements (whorls, cards, strands) at their real 5–20 cm size.
- **Props widen the bounding box.** An oar or pole adds a metre and shrinks the subject in
  the preview; accept it or trim the prop.
