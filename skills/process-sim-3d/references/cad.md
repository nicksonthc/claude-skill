# Equipment models: procedural, STEP or GLB

Ask at trigger. Procedural (built from the drawing's dimensions with the component library) is the default
and always works. Supported model files: **STEP** (`.step`, `.stp`) and **GLB** (`.glb`, binary glTF).

## STEP → GLB (`scripts/step2glb.py`)
```bash
python3 -m venv .cq && .cq/bin/pip install cadquery          # once (~200 MB, OpenCascade)
.cq/bin/python ~/.claude/skills/process-sim-3d/scripts/step2glb.py machine.step public/models/machine.glb 0.5
```
- One node per solid (`solid_000`…), so a moving part can be animated: find it by name in three.js and
  give it its own Group. Note which solid is which with the engineer (screenshot with node names as labels).
- Millimetres → metres; Z-up → Y-up (root node rotation). STEP colours and part names are not kept —
  re-colour by node name in the scene.
- Tolerance 0.5 mm is a good default; raise to 1–2 mm for big machines (triangle count), lower for small
  mechanisms. Report triangles + file size after conversion (`threejs-glb-viewer` has a GLB report).
- Huge assemblies (> ~1–2 M triangles): convert only the visible / moving parts, keep frames procedural.

## GLB
- Inspect first with `threejs-glb-viewer` (bounding box, units, up axis, decoders needed). Many CAD exports
  arrive in millimetres — scale 0.001 if the box is ~1000× too big.
- Load with `GLTFLoader` (+ DRACO / KTX2 / Meshopt decoders if the report says so). For the standalone
  single file, inline the GLB as a base64 data URI or an ArrayBuffer in the bundle; for React, put it in
  `public/models/`.
- Place by the spec layout: position the model so its measured box sits where the procedural component was.
- Moving parts must be separate nodes; a single merged mesh can only be shown, not animated.

## Other formats — refuse, explain, ask for STEP or GLB
| Format | Why it is not supported | Ask for |
|---|---|---|
| SolidWorks `.sldprt` / `.sldasm`, Inventor `.ipt` / `.iam`, Creo `.prt`, CATIA `.CATPart`, NX `.prt` | proprietary native formats; no open, reliable reader | File → Save As → STEP AP214/AP242 (or GLB if their CAD has it) |
| `.dwg` / `.dxf` | 2D drawings (or AutoCAD solids that do not export cleanly) | the 3D model as STEP; the drawing is still useful for dimensions |
| `.iges` / `.igs` | legacy surface format; usually arrives as open, unjoined surfaces (holes, flipped faces) | STEP from the same CAD |
| `.stl` | triangles only: no units, no parts, no colours, often millions of facets | STEP, or GLB with parts separated |
| `.obj` / `.fbx` / `.dae` / `.3ds` | mesh formats with unreliable units/axes and no assembly structure for CAD | GLB (export from Blender) |
| `.x_t` (Parasolid), `.jt`, `.3dxml` | need commercial kernels to read | STEP |
| `.pdf` / images | not 3D | use them as dimension references for procedural geometry |
Say it in one line, e.g. "`.sldasm` is SolidWorks' native format and can't be read outside SolidWorks —
please export it as STEP (File → Save As → STEP AP242)."
