# Reference: the study route

Everything here was proven on Blender 4.2–5.2 (`--background --factory-startup`),
three.js 0.180 via drei `useGLTF`, and twenty-five assets (buildings, boats, a bridge,
trees, five human figures, street props).

## 1. `scripts/studio.py` API

Import by path (the module is not on `sys.path`, so `from studio import x` fails; bind
names from the module object):

```python
import importlib.util
spec=importlib.util.spec_from_file_location('studio','/abs/path/studio.py')
studio=importlib.util.module_from_spec(spec); spec.loader.exec_module(studio)
```

| Call | Use |
| --- | --- |
| `clear_scene()` | First line of every generator. |
| `mat(name,color,kind='plain'\|'stone'\|'wood'\|'plaster',rough=.8,emission=0,metallic=0,grain_scale=1,flat=False,alpha=1)` | One material = one draw call. `flat=True` for masonry, timber, tiles; smooth for organic and turned forms. `emission` .2–.4 for paper lanterns. `alpha<1` for oil-paper. |
| `Builder()` → `b.add(m,verts,faces)`, `b.emit()` | Accumulates geometry per material; `emit()` creates one mesh object per material, recalculates normals, writes planar UVs for grain. |
| `box(b,m,center,size,rot_z=0)` | Crisp-edged block. |
| `tube(b,m,pts,radii,sides=8,cap=True)` | Polyline sweep with per-point radius: limbs, ropes, poles, rails, sleeves. |
| `rod(b,m,a,c,r,sides=8)` | Two-point tube. |
| `lathe(b,m,profile,sides=16,center,rot_z)` | Revolve `(r,z)` pairs: pots, lantern bodies, finials, columns, torsos, hats. |
| `sphere(b,m,center,radius,scale,detail=2,rng,jitter)` | Icosphere; jitter roughens for foliage, moss, produce. |
| `quad`, `polygon` | Single faces: leaf cards, cloth panels, flagstones, stain decals. |
| `extrude(b,m,outline,z0,z1,center,rot_z)` | Prism from a 2D outline: walls, plinths, gable profiles. |
| `text_banner(b,m,text,center,size,rot_z,font)` | Real glyphs as mesh. CJK on macOS: `/System/Library/Fonts/Supplemental/Songti.ttc`. |
| `export(slug,title,chinese,description,source,method,light,view,margin,out_dir,ref_dir,units)` | Grounds at Z=0, exports GLB + .blend, renders 800×640 transparent Cycles preview, copies the reference, writes `<slug>.entry.json`, returns the entry. |
| `merge_manifest(out_dir)` / `scripts/merge_manifest.py` | Folds entry files into `manifest.json`, replacing same ids in place. |

Output dirs: `out_dir`/`ref_dir` args → `STUDIO_OUT_DIR`/`STUDIO_REF_DIR` env → `./public/models`
and `./public/references`. Entry URLs are written relative to the working directory with a
leading `/public` stripped, matching a Vite-style static folder.

## 2. Entry schema

```json
{ "id": "slug", "title": "…", "chinese": "…", "description": "…",
  "glb": "/models/slug.glb", "preview": "/models/slug.png", "blend": "/models/slug.blend",
  "reference": "/references/slug.png", "source": "images/…png",
  "dimensions": [W, H, D], "triangles": 0, "bytes": 0,
  "method": "Reference-guided procedural modeling; unseen geometry interpreted",
  "units": "meters (artistic scale)" }
```

`dimensions` is W×H×D in the consumer's Y-up frame (Blender X, Z, Y).

## 3. Recipes that worked

**Roofs.** Lay individual pan and cover tiles as short curved sheets in overlapping rows
(~30 mm row step), with round cover-tile ends and pointed drip tiles at the eave, rafters
and a fascia under them, a stacked-tile ridge and upturned ridge ends built as tapered fins.
Three tile shades, near-charcoal albedo (~.12–.14), or they render mid-grey.

**Masonry.** Every block a slightly chamfered, corner-jittered box over a dark mortar core so
joints read as grooves; a darker, glossier tide band on the lowest courses; moss as thin
irregular patches in the joints. Randomise per-block tint from a small palette.

**Timber frames and lattice.** Posts, beams and rails as `box`; lattice as thin `box` grids
(回 or ice-crack patterns) inside a frame; folding board doors as panelled boxes swung open.

**Cloth.** Awnings as quads with a sine sag between props and a jittered ragged hem; folds as
low-frequency radius modulation on tubes (sleeves, trousers) rather than simulation.

**Human figures.** Head ≈ 1/7.5 of height, shoulders ≈ 2 head widths. Torso from a lathe
or stacked cross-sections, limbs as tapered tubes with joint spheres, two-bone IK for elbows
when hands must grip a prop. Face stylised but proportioned (eyes at mid-head, nose, mouth,
ears); a hair cap following a real hairline. Costume colours read from the photo, deepened a
step for the studio light.

**Trees.** One recursive branching routine (tapered tubes, children sharing azimuths evenly,
a droop floor, a root flare, a soil patch) with a per-species foliage pass: whorls of 5–8
small oval leaf cards at every twig tip over a dark shade core for broadleaf evergreens;
pendulous leafy strands stepping under gravity for willows; blossom octahedra along bare
twigs for peach and plum. Foliage albedos dark (.1–.3) because both studio and overcast
lighting lift greens.

**Weathering.** Damp bands low on walls, rain streaks under sills, peeled render patches,
moss in joints, wet darker courses at the waterline. Decal polygons a few millimetres proud
read well at inspector distance.

## 4. Preview framing

`export()` places an orthographic camera at `center + view*size` with `ortho_scale =
margin*size`. Defaults suit props and figures. Adjust:

| Subject | `view` | `margin` | `light` |
| --- | --- | --- | --- |
| Prop, figure, boat | `(.95,-1.2,.83)` | 1.586 | 1.0 |
| Tree, whitewashed wall | default | 1.586 | .5–.7 |
| Building (facade matters) | `(.75–.9, -1.45–-1.7, .4–.55)` | 1.6–1.9 | .7–1.0 |
| Tall or cubic mass that clips | default | 1.8–2.0 | |

Read the preview PNG after every run. Render a rear and a low view from the saved `.blend`
before declaring unseen sides closed.

## 5. Consumer integration

A GLB alone proves nothing. Check the loader (drei `useGLTF` needs no decoder for these
GLBs since textures are embedded PNGs), that the manifest schema matches the consumer's type,
that the asset appears in any asset list, and run the consumer's browser check. In the
originating project that was a Playwright script iterating every manifest id, fetching each
GLB and asserting the `glTF` magic bytes.

## 6. Budgets observed

| Asset class | Triangles | GLB |
| --- | --- | --- |
| Figure with props | 12k–21k | .5–.9 MB |
| Street prop, steps, stall | 11k–50k | .8–1.5 MB |
| Boat, bridge | 48k–53k | 3–4 MB |
| Tree with leaf-scale foliage | 45k–150k | 1.7–7.6 MB |
| Two-storey building with laid tiles | 85k–162k | 5–7.6 MB |
