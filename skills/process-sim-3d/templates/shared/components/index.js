// Parametric component library. Every component is built from primitives (Batch), sized from its
// parameters - never from one project's magic numbers - and returns the handles the sim animates.
// Static parts go into the batch you pass (merged later); moving parts get their own Groups.
// Extend by copying the shape of any function here: (M, b|root, opts) -> handles.
import * as THREE from 'three';
import { Batch, instantiate } from '../core/batch.js';
import { textTexture } from '../core/mats.js';

const lerp = (a, b, k) => a + (b - a) * k;
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

export function foot(b, M, x, z) { b.cyl(M.steel, 0.012, 0.06, x, 0.04, z).cyl(M.yellow, 0.035, 0.014, x, 0.007, z); }

export function towerLight(b, M, x, y, z) {
  b.cyl(M.steel, 0.012, 0.22, x, y + 0.11, z).cyl(M.dark, 0.03, 0.03, x, y + 0.015, z);
  b.cyl(M.red, 0.026, 0.045, x, y + 0.34, z).cyl(M.yellow, 0.026, 0.045, x, y + 0.292, z).cyl(M.lampG, 0.026, 0.045, x, y + 0.244, z);
}

// Floor tape rectangle (zones, aisles, staging areas). size = [x, z].
export function floorZone(b, M, { at = [0, 0, 0], size = [1, 1], mat = M.tape, w = 0.06 }) {
  const [x0, , z0] = at, [sx, sz] = size, xa = x0 - sx / 2, xb = x0 + sx / 2, za = z0 - sz / 2, zb = z0 + sz / 2;
  b.box(mat, sx, 0.003, w, x0, 0.0015, za).box(mat, sx, 0.003, w, x0, 0.0015, zb);
  b.box(mat, w, 0.003, sz + w, xa, 0.0015, z0).box(mat, w, 0.003, sz + w, xb, 0.0015, z0);
}

// Aluminium frame enclosure with optional skins (solid/glass panels toggled by the UI) and feet.
// size = [x, y, z]; open = sides left open, e.g. ['+x'] for an operator side.
export function frame(b, skin, glass, M, { at = [0, 0, 0], size = [1, 2, 1], open = [], glassSides = [], post = 0.05, base = 0.9 }) {
  const [cx, , cz] = at, [sx, sy, sz] = size, hx = sx / 2 - post / 2, hz = sz / 2 - post / 2;
  for (const x of [-hx, hx]) for (const z of [-hz, hz]) { b.box(M.alu, post, sy, post, cx + x, sy / 2, cz + z); foot(b, M, cx + x, cz + z); }
  for (const y of [post / 2 + 0.06, sy - post / 2]) {
    for (const z of [-hz, hz]) b.box(M.alu, sx, post, post, cx, y, cz + z);
    for (const x of [-hx, hx]) b.box(M.alu, post, post, sz, cx + x, y, cz);
  }
  if (base > 0) b.rbox(M.cabinet, sx - 0.02, base, sz - 0.02, cx, base / 2 + 0.02, cz, 0.012);
  const panel = (side) => {
    const tgt = glassSides.includes(side) ? glass : skin, mat = glassSides.includes(side) ? M.glass : M.skin;
    const h = sy - base - 0.06, y = base + h / 2;
    if (side === '+x' || side === '-x') tgt.box(mat, 0.008, h, sz - 0.1, cx + (side === '+x' ? sx / 2 : -sx / 2), y, cz);
    else tgt.box(mat, sx - 0.1, h, 0.008, cx, y, cz + (side === '+z' ? sz / 2 : -sz / 2));
  };
  for (const side of ['+x', '-x', '+z', '-z']) if (!open.includes(side)) panel(side);
  skin.box(M.skin, sx, 0.012, sz, cx, sy, cz);
}

// Belt conveyor along X from x0 to x1 at z, top surface at height h. Returns pos(k) along the belt.
export function conveyor(b, M, { x0, x1, z = 0, h = 0.85, width = 0.4 }) {
  const len = Math.abs(x1 - x0), cx = (x0 + x1) / 2;
  b.box(M.belt, len, 0.02, width, cx, h - 0.01, z);
  for (const s of [-1, 1]) b.box(M.alu, len + 0.06, 0.08, 0.03, cx, h - 0.03, z + s * (width / 2 + 0.02));
  for (let x = Math.min(x0, x1) + 0.1; x < Math.max(x0, x1); x += 0.6) for (const s of [-1, 1]) { b.box(M.alu, 0.04, h - 0.06, 0.04, x, (h - 0.06) / 2, z + s * (width / 2 + 0.02)); foot(b, M, x, z + s * (width / 2 + 0.02)); }
  for (const x of [x0, x1]) b.cyl(M.steel, 0.04, width, x, h - 0.04, z, 'z');
  return { pos: (k) => new THREE.Vector3(lerp(x0, x1, k), h, z), h };
}

// Grid of slots (rack layers, chamber cells, buffer positions). Each slot gets its own state material so
// the sim can colour it (idle / busy / hot / done). slot.pos = world position of the slot's top surface.
const SLOT_STATE = { idle: [0x000000, 0], loading: [0xffb300, 2.5], busy: [0xff2a12, 3.2], done: [0x25ff6a, 3], cool: [0x18c8ff, 3] };
export function slotRack(b, M, root, own, { at = [0, 0, 0], cols = 2, rows = 3, pitch = [0.45, 0.35], slot = [0.36, 0.3], y0 = 0.5, depth = 0.5 }) {
  const [cx, , cz] = at, W = cols * pitch[0], H = y0 + rows * pitch[1] + 0.1, slots = [];
  for (const s of [-1, 1]) for (const zz of [-1, 1]) { b.box(M.alu, 0.05, H, 0.05, cx + s * (W / 2 + 0.03), H / 2, cz + zz * depth / 2); foot(b, M, cx + s * (W / 2 + 0.03), cz + zz * depth / 2); }
  b.box(M.alu, W + 0.1, 0.05, depth, cx, H, cz);
  for (let r = 0; r < rows; r++) {
    const y = y0 + r * pitch[1];
    b.box(M.grey, W + 0.06, 0.02, depth, cx, y - 0.01, cz);
    for (let c = 0; c < cols; c++) {
      const x = cx + (c - (cols - 1) / 2) * pitch[0];
      const mat = new THREE.MeshStandardMaterial({ color: 0x1d2024, emissive: 0, emissiveIntensity: 0, roughness: 0.4 });
      own.push(mat);
      const led = new THREE.Mesh(new THREE.BoxGeometry(slot[0], 0.012, 0.02), mat);
      led.position.set(x, y + 0.006, cz + depth / 2 - 0.01); led.userData.own = true;
      root.add(led);
      b.box(M.dark, slot[0], 0.01, slot[1], x, y + 0.005, cz);
      slots.push({ i: slots.length, row: r, col: c, pos: new THREE.Vector3(x, y + 0.01, cz), state: 'idle', item: null,
        set(state) { this.state = state; const v = SLOT_STATE[state] || SLOT_STATE.idle; mat.emissive.setHex(v[0]); mat.emissiveIntensity = v[1]; } });
    }
  }
  return { slots, top: H };
}

// SCARA arm on a fixed base (or a slider: move base.position along an axis). ik(dx, dz, elbowSign)
// gives joint angles; set(t1, t2, quillY) poses it. Reach = L1 + L2.
export function scara(M, root, { at = [0, 0, 0], L1 = 0.4, L2 = 0.35, h = 1.0, quillLen = 0.62 }) {
  const base = new THREE.Group();
  base.position.set(...at);
  const b = new Batch();
  b.rbox(M.robotW, 0.18, h - 0.05, 0.2, 0, (h - 0.05) / 2, 0, 0.02).cyl(M.accent, 0.062, 0.022, 0, h, 0);
  b.build(base);
  const l1 = new THREE.Group(); l1.position.y = h + 0.02;
  b.rbox(M.robotW, L1 + 0.12, 0.055, 0.115, L1 / 2, 0.0275, 0, 0.022).cyl(M.accent, 0.058, 0.012, L1, -0.004, 0);
  b.build(l1);
  const l2 = new THREE.Group(); l2.position.set(L1, 0.062, 0);
  b.rbox(M.robotW, L2 + 0.11, 0.055, 0.105, L2 / 2, 0.0275, 0, 0.022).rbox(M.robotW, 0.2, 0.15, 0.1, L2 - 0.16, 0.13, 0, 0.02);
  b.build(l2);
  const quill = new THREE.Group(); quill.position.set(L2, 0, 0);
  b.cyl(M.steel, 0.011, quillLen, 0, quillLen / 2 - 0.05, 0).box(M.dark, 0.055, 0.022, 0.055, 0, -0.05, 0).cyl(M.rubber, 0.02, 0.013, 0, -0.066, 0);
  b.build(quill);
  l2.add(quill); l1.add(l2); base.add(l1); root.add(base);
  const top = h + 0.02 + 0.062; // quill origin height (world y = base.y + top + quill.position.y)
  const TIP = 0.073; // quill origin -> bottom of the suction cup; a held item hangs at quill-local y = -TIP
  return {
    base, l1, l2, quill, L1, L2, top, TIP,
    ik(dx, dz, sgn = 1) { // planar 2-link IK; clamps when the target is out of reach
      const c = clamp((dx * dx + dz * dz - L1 * L1 - L2 * L2) / (2 * L1 * L2), -1, 1), t2 = sgn * Math.acos(c);
      return { t1: Math.atan2(dz, dx) - Math.atan2(L2 * Math.sin(t2), L1 + L2 * Math.cos(t2)), t2 };
    },
    set(t1, t2, tipY) { l1.rotation.y = -t1; l2.rotation.y = -t2; quill.position.y = tipY - (base.position.y + top) + TIP; },
  };
}

// Overhead XZ gantry with a Z-lift (pick head). set(x, z, y) moves carriage, trolley and head.
export function gantry(b, M, root, { x0 = -1, x1 = 1, z0 = -0.6, z1 = 0.6, h = 2.0 }) {
  for (const x of [x0, x1]) for (const z of [z0, z1]) { b.box(M.alu, 0.06, h, 0.06, x, h / 2, z); foot(b, M, x, z); }
  for (const z of [z0, z1]) b.box(M.dark, x1 - x0 + 0.06, 0.08, 0.08, (x0 + x1) / 2, h, z);
  const bridge = new THREE.Group(), head = new THREE.Group(), gb = new Batch();
  gb.box(M.accent, 0.1, 0.1, z1 - z0, 0, h + 0.09, (z0 + z1) / 2); gb.build(bridge);
  gb.box(M.dark, 0.16, 0.14, 0.16, 0, 0, 0).cyl(M.steel, 0.02, 0.5, 0, -0.3, 0).box(M.dark, 0.08, 0.04, 0.08, 0, -0.56, 0); gb.build(head);
  bridge.add(head); root.add(bridge);
  head.position.set(0, h + 0.02, (z0 + z1) / 2);
  return { bridge, head, h, set(x, z, y) { bridge.position.x = x; head.position.z = z; head.position.y = y + 0.58; } };
}

// Process nests on a table (hotplate / press / test socket / oven cell): cols x rows nests with a press lid
// each. nest.lid moves down during processing; nest.set(state) colours its LED and lid glow.
export function nestPlate(b, M, root, own, { at = [0, 0, 0], cols = 3, rows = 2, pitch = 0.16, h = 0.85, nest = 0.11 }) {
  const [cx, , cz] = at, W = cols * pitch + 0.12, D = rows * pitch + 0.12, nests = [];
  b.rbox(M.cabinet, W, h - 0.02, D, cx, (h - 0.02) / 2, cz, 0.012);
  b.box(M.grey, W + 0.02, 0.03, D + 0.02, cx, h - 0.015, cz);
  for (const s of [-1, 1]) { b.box(M.alu, 0.04, 0.5, 0.04, cx + s * (W / 2 - 0.03), h + 0.25, cz - D / 2 + 0.03); }
  b.box(M.alu, W, 0.04, 0.04, cx, h + 0.5, cz - D / 2 + 0.03);
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const x = cx + (c - (cols - 1) / 2) * pitch, z = cz + (r - (rows - 1) / 2) * pitch;
    b.box(M.black, nest, 0.02, nest, x, h + 0.01, z);
    const mat = new THREE.MeshStandardMaterial({ color: 0x3a1a14, emissive: 0, emissiveIntensity: 0, roughness: 0.4 });
    own.push(mat);
    const lid = new THREE.Group(), lb = new Batch();
    lb.box(M.dark, nest * 0.9, 0.03, nest * 0.9, 0, 0.015, 0).cyl(M.steel, 0.01, 0.14, 0, 0.1, 0);
    lb.build(lid);
    const glow = new THREE.Mesh(new THREE.BoxGeometry(nest * 0.8, 0.008, nest * 0.8), mat);
    glow.position.y = -0.002; glow.userData.own = true; lid.add(glow);
    const up = h + 0.14, down = h + 0.035;
    lid.position.set(x, up, z); root.add(lid);
    nests.push({ i: nests.length, pos: new THREE.Vector3(x, h + 0.02, z), lid, up, down, state: 'idle', item: null, remain: 0,
      set(state, k = 1) { this.state = state; const v = SLOT_STATE[state] || SLOT_STATE.idle; mat.emissive.setHex(v[0]); mat.emissiveIntensity = v[1] * k; } });
  }
  return { nests, h };
}

// Carrier (tray/fixture) with cols x rows pockets, and the part prototype that sits in a pocket.
export function carrierProtos(M, { cols = 2, rows = 2, pitch = 0.09, part = 0.07 }) {
  const b = new Batch(), W = cols * pitch + 0.04, D = rows * pitch + 0.04;
  b.box(M.tray, W, 0.008, D, 0, 0.004, 0);
  for (const s of [-1, 1]) { b.box(M.tray, W, 0.02, 0.006, 0, 0.01, s * D / 2); b.box(M.tray, 0.006, 0.02, D, s * W / 2, 0.01, 0); }
  const carrier = b.proto();
  b.box(M.part, part, 0.006, part, 0, 0.003, 0).rbox(M.partLid, part * 0.75, 0.006, part * 0.75, 0, 0.009, 0, 0.002);
  const partP = b.proto();
  const pockets = [];
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) pockets.push([(c - (cols - 1) / 2) * pitch, 0.008, (r - (rows - 1) / 2) * pitch]);
  return { carrier, part: partP, pockets, size: [W, D] };
}
export function makePart(P, M) {
  const group = instantiate(P.part, { cast: false });
  const mark = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.002, 12), M.done);
  mark.position.set(0.02, 0.014, 0.02); mark.visible = false; group.add(mark);
  return { group, mark, state: 'new' };
}

// Push cart / trolley that carries a stack of carriers. Handle on +x.
export function cartProto(M, { w = 0.5, d = 0.25, h = 0.9 }) {
  const b = new Batch();
  b.box(M.alu, w, 0.03, d, 0, 0.135, 0);
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) b.cyl(M.rubber, 0.04, 0.026, sx * (w / 2 - 0.05), 0.04, sz * (d / 2 - 0.03), 'z');
  for (const s of [-1, 1]) b.box(M.cabinet, w, h - 0.15, 0.012, 0, (h + 0.15) / 2, s * d / 2);
  b.box(M.cabinet, 0.012, h - 0.15, d, -w / 2, (h + 0.15) / 2, 0);
  b.cyl(M.steel, 0.012, d - 0.04, w / 2 + 0.06, h - 0.05, 0, 'z');
  return b.proto();
}

// Simple operator figure (faces -X). Animate legL/legR/armL/armR rotation.z and group position.
export function operator(M) {
  const group = new THREE.Group(), b = new Batch();
  const limb = (mat, r, len, x, y, z) => b.add(mat, new THREE.CapsuleGeometry(r, len, 6, 14), x, y, z);
  b.rbox(M.coat, 0.23, 0.6, 0.4, 0, 1.19, 0, 0.09).rbox(M.coat, 0.25, 0.2, 0.36, 0, 0.93, 0, 0.08);
  b.cyl(M.skinTone, 0.045, 0.08, 0, 1.52, 0).add(M.skinTone, new THREE.SphereGeometry(0.105, 20, 14), 0, 1.63, 0);
  b.build(group);
  const mk = (x, y, z, fn) => { const g = new THREE.Group(); g.position.set(x, y, z); fn(); b.build(g); group.add(g); return g; };
  const leg = (z) => mk(0, 0.9, z, () => { limb(M.pants, 0.068, 0.7, 0, -0.42, 0); b.rbox(M.shoe, 0.25, 0.075, 0.1, -0.045, -0.863, 0, 0.03); });
  const arm = (z) => mk(0, 1.42, z, () => { limb(M.coat, 0.05, 0.46, 0, -0.26, 0); });
  return { group, legL: leg(-0.095), legR: leg(0.095), armL: arm(-0.245), armR: arm(0.245), phase: 0 };
}

// Flat text plate (signs, decals). Returns a mesh that owns its material + texture.
export function plate(text, { w = 1.2, h = 0.15, fg = '#1b2430', bg = '#f4f5f6', font = '700 84px system-ui, sans-serif' } = {}) {
  const tex = textTexture(text, { w: 1024, h: Math.round(1024 * h / w), bg, fg, font });
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex, transparent: !bg }));
  m.userData.own = true; m.userData.ownMat = true;
  return m;
}
