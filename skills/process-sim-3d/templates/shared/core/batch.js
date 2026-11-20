// Geometry batching: collect primitives per material, merge them into ONE mesh per material.
// A whole machine frame built from hundreds of boxes renders in a handful of draw calls.
//   const b = new Batch();             // optional origin matrix: new Batch(matrix) or b.origin = matrix
//   b.box(M.alu, sx, sy, sz, x, y, z)  // centred box
//   b.rbox(M.paint, sx, sy, sz, x, y, z, radius)
//   b.cyl(M.steel, r, h, x, y, z, 'x'|'y'|'z')
//   b.build(parentGroup)               // static scenery: merged meshes added to the parent
//   const proto = b.proto(); instantiate(proto)  // reusable prototype for many dynamic copies
import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js';

const UNIT_BOX = new THREE.BoxGeometry(1, 1, 1).toNonIndexed();
const UNIT_CYL = new THREE.CylinderGeometry(1, 1, 1, 24).toNonIndexed();
const rcache = new Map();
function rgeo(sx, sy, sz, r) {
  const key = [sx, sy, sz, r].join('|');
  let g = rcache.get(key);
  if (!g) { g = new RoundedBoxGeometry(sx, sy, sz, 3, r); if (g.index) g = g.toNonIndexed(); rcache.set(key, g); }
  return g;
}
const _m = new THREE.Matrix4(), _q = new THREE.Quaternion(), _e = new THREE.Euler(), _p = new THREE.Vector3(), _s = new THREE.Vector3();

export class Batch {
  constructor(origin) { this.map = new Map(); this.origin = origin || null; }
  add(mat, geo, x = 0, y = 0, z = 0, rx = 0, ry = 0, rz = 0, sx = 1, sy = 1, sz = 1) {
    _e.set(rx, ry, rz); _q.setFromEuler(_e);
    _m.compose(_p.set(x, y, z), _q, _s.set(sx, sy, sz));
    if (this.origin) _m.premultiply(this.origin);
    const g = (geo.index ? geo.toNonIndexed() : geo.clone()).applyMatrix4(_m);
    let l = this.map.get(mat);
    if (!l) { l = []; this.map.set(mat, l); }
    l.push(g);
    return this;
  }
  box(mat, sx, sy, sz, x, y, z, ry = 0) { return this.add(mat, UNIT_BOX, x, y, z, 0, ry, 0, sx, sy, sz); }
  rbox(mat, sx, sy, sz, x, y, z, r = 0.01, ry = 0) { return this.add(mat, rgeo(sx, sy, sz, r), x, y, z, 0, ry, 0); }
  cyl(mat, r, h, x, y, z, axis = 'y') {
    return this.add(mat, UNIT_CYL, x, y, z, axis === 'z' ? Math.PI / 2 : 0, 0, axis === 'x' ? Math.PI / 2 : 0, r, h, r);
  }
  proto() {
    const out = [];
    for (const [mat, list] of this.map) { out.push({ geo: mergeGeometries(list, false), mat }); list.forEach((g) => g.dispose()); }
    this.map.clear();
    return out;
  }
  build(parent, { cast = true, receive = true } = {}) {
    const out = [];
    for (const p of this.proto()) {
      const mesh = new THREE.Mesh(p.geo, p.mat);
      mesh.castShadow = cast; mesh.receiveShadow = receive; mesh.userData.own = true; // own = geometry disposed with the world
      parent.add(mesh); out.push(mesh);
    }
    return out;
  }
}

// Many copies of one prototype share geometry; `remap` swaps a material per copy (e.g. a per-slot glow).
export function instantiate(proto, { cast = true, receive = true, remap = null } = {}) {
  const g = new THREE.Group();
  for (const p of proto) {
    const mesh = new THREE.Mesh(p.geo, (remap && remap.get(p.mat)) || p.mat);
    mesh.castShadow = cast; mesh.receiveShadow = receive;
    g.add(mesh);
  }
  return g;
}

// Dispose everything a world created: merged geometries (userData.own) and per-world materials/textures.
export function disposeTree(root, extra = []) {
  root.traverse((o) => {
    if (o.isMesh && o.userData.own) o.geometry.dispose();
    if (o.isMesh && o.userData.ownMat) { o.material.map && o.material.map.dispose(); o.material.dispose(); }
  });
  extra.forEach((m) => m.dispose());
}
