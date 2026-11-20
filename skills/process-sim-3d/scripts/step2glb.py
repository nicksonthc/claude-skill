# STEP -> GLB for a three.js scene.  python step2glb.py in.step out.glb [tolerance_mm=0.5]
# Proven on cadquery 2.5.2 (pip install cadquery, Python 3.9+): a 3-solid assembly -> 3 nodes, metres, Y-up.
#  - one glTF node per solid (solid_000, solid_001, ...) so moving parts can be animated separately
#  - millimetres -> metres (STEP is mm, three.js scenes are m)
#  - Z-up -> Y-up is done by the glTF exporter (root node rotated -90 deg about X)
#  - colours / part names from the STEP are NOT kept: re-colour in three.js by node name
import sys, cadquery as cq
src, dst = sys.argv[1], sys.argv[2]
tol = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
shape = cq.importers.importStep(src).val()
solids = shape.Solids() or [shape]
assy = cq.Assembly(name='model')
for i, s in enumerate(solids):
    assy.add(s.scale(0.001), name=f'solid_{i:03d}')
assy.export(dst, tolerance=tol / 1000, angularTolerance=0.2)
print('wrote', dst, len(solids), 'solids')
