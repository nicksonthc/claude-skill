# Component library (`components/index.js`)

Every component: `(M, batch | root, opts) → handles`. Static parts go into a `Batch` (merged into one mesh
per material); moving parts get their own `Group` returned as a handle. Sizes come from `opts`, which come
from the spec layout.

| Component | Static / handles | Use for |
|---|---|---|
| `floorZone(b, M, {at,size,mat})` | tape rectangle | zones, aisles, staging areas |
| `frame(b, skin, glass, M, {at,size,open,glassSides,base})` | posts, rails, feet, skins / glass | machine enclosures, cells |
| `conveyor(b, M, {x0,x1,z,h,width})` | belt, rails, rollers, legs → `pos(k)` | belts, roller lines, lanes |
| `slotRack(b, M, root, own, {at,cols,rows,pitch,...})` | shelves → `slots[] {pos, set(state)}` | racks, layered buffers, storage |
| `nestPlate(b, M, root, own, {at,cols,rows,pitch,h})` | table, nests → `nests[] {pos, lid, up, down, set(state)}` | test sockets, presses, hot plates, oven cells |
| `scara(M, root, {at,L1,L2,h})` | → `{base,l1,l2,quill, ik(dx,dz,sgn), set(t1,t2,tipY), TIP}` | pick & place robots (base can ride a slider) |
| `gantry(b, M, root, {x0,x1,z0,z1,h})` | frame → `{bridge, head, set(x,z,y)}` | overhead XYZ pickers, stacker cranes |
| `carrierProtos(M, {cols,rows,pitch,part})` + `makePart` | prototypes → instances | trays, totes, boards, fixtures, parts |
| `cartProto(M, {w,d,h})` | prototype | trolleys, carts (push with an operator) |
| `operator(M)` | → `{group, legL, legR, armL, armR}` | people: dock carts, load stations |
| `towerLight`, `foot`, `plate(text)` | decor | stack lights, levelling feet, signs |

## Adding a component (the recipe)
1. Name it by what it *is* (lifter, turntable, buffer stacker), not by the project.
2. Parameters = the dimensions on the drawing + counts. Derive every other size from them.
3. Static geometry → the batch you were given. One `Group` per independently moving part, nested by
   kinematic chain (mast → carriage → shuttle; base → link1 → link2 → quill).
4. Return the handles the sim needs and a `set(...)` that poses them from sim state (angles, heights).
5. Per-instance state colour (LED, glow) = its own material pushed to `own` (disposed on rebuild);
   shared look = a material from `mats.js`.
6. Place it in `world.js` from a spec layout entry; add its label there.

Kinematics worth reusing:
- **2-link planar IK** (`scara.ik`): clamp the cosine; choose the elbow sign by target side; when two arms
  share a board, point the elbows away from each other.
- **Lifter**: a mast group moving along the rack row, a carriage moving in Y inside it, a telescopic shuttle
  in X (mid stage at half the shuttle travel). Combined lift + travel = one tween, duration of the slower axis.
- **Swept angle**: normalise both angles into the same 2π window before lerping, or the arm swings the long way.

## Imported models
STEP / GLB equipment replaces a procedural component's *static* part; moving parts must be separate nodes
in the GLB (or kept procedural). See [cad.md](cad.md).
