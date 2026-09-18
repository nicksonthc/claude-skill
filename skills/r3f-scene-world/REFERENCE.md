# R3F Scene World — reference

Copy-paste building blocks. Every section is independent; take the frame (§1)
first, because everything else imports it.

Naming in here is deliberately neutral: the **spine** is whatever the world runs
along — a canal, a street, a rail line, a conveyor, a ridge. `Z` is the spine
axis, `Y` is up, metres throughout.

---

## 1. The authoring frame

One module, imported by geometry, placements, scatter, routes and checks alike.
Author in the straight frame; the world is the bent image of it.

```ts
// src/world/frame.ts
//
// Conventions (read every magic number in the project against these):
//   metres, Y up, Z along the spine.
//   Ground 0, walkable deck 1.03, water/floor 0.13.
//   Authored spine edges are X ±5.1 whatever the real width is at that Z.

/** Lateral offset of the spine centre at this Z. The whole world bends by it. */
export const center = (z: number) => 11 * Math.sin((z + 7) / 24) - 11 * Math.sin(7 / 24);

/** d(center)/dz — yaw for anything that must lie along the spine (hulls, kerbs). */
export const slope = (z: number) => (11 / 24) * Math.cos((z + 7) / 24);

/** Real half-width varies by district; the authored frame never does. */
export const widthAt = (z: number) => {
  const basin = 4.1 * Math.exp(-(((z - 17) / 17) ** 2));      // opens at the arrival end
  const market = 1.5 * Math.exp(-(((z + 43) / 16) ** 2));     // widens through the market
  const narrowing = 1.25 / (1 + Math.exp((z + 92) / 10));     // closes toward the far end
  return 9.4 + basin + market - narrowing;
};

/**
 * Authored X → world X, *before* the centre is added. Everything beyond the
 * authored edge is pushed out with the bank, so buildings translate with their
 * frontage instead of stretching.
 */
export const lateral = (x: number, z = 0) =>
  x + Math.max(-1, Math.min(1, x / 5.1)) * (widthAt(z) / 2 - 5.1);

/** Authored point → world point. The one function every layer shares. */
export const bend = ([x, y, z]: [number, number, number]): [number, number, number] => [
  lateral(x, z) + center(z),
  y,
  z,
];

/** Side branches do not follow the spine: they are polylines in world metres. */
export const branches: readonly (readonly [number, number])[][] = [
  [[center(-45) + widthAt(-45) / 2 - 0.6, -45], [3, -57], [15, -70]],
];
export const branchWidth = 4.4;

const segmentDistance = (x: number, z: number, a: readonly [number, number], b: readonly [number, number]) => {
  const dx = b[0] - a[0], dz = b[1] - a[1];
  const l2 = dx * dx + dz * dz;
  const t = l2 === 0 ? 0 : Math.max(0, Math.min(1, ((x - a[0]) * dx + (z - a[1]) * dz) / l2));
  return Math.hypot(x - (a[0] + dx * t), z - (a[1] + dz * t));
};

/** The mask: carves the spine out of the ground, keeps scatter and feet out of it. */
export const isSpine = (x: number, z: number, pad = 0) =>
  Math.abs(x - center(z)) < widthAt(z) / 2 + pad ||
  branches.some((points) =>
    points.some((_, i) => i < points.length - 1 && segmentDistance(x, z, points[i], points[i + 1]) < branchWidth / 2 + pad),
  );
```

**Rules.** Pure functions only — the frame is imported by Node checks and by
Blender-side scripts as often as by the renderer. No THREE import. When the
shape changes, the world, the models, the scatter and the camera route all move
together; that is the whole point.

---

## 2. Bulk geometry, batched per material

Imperative on purpose: tens of thousands of primitives that never change should
not each own a React fibre.

```ts
// src/world/buildWorld.ts
import * as T from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { bend, center, isSpine, lateral, slope } from './frame';

export type World = { root: T.Group; update: (t: number) => void; dispose: () => void };

export function buildWorld(): World {
  const root = new T.Group();
  // Seeded RNG: the world must be identical for every visitor and every check.
  let seed = 7621;
  const rand = () => ((seed = (seed * 1664525 + 1013904223) >>> 0), seed / 4294967296);

  const materials = {
    plaster: new T.MeshStandardMaterial({ color: '#d4d5cc', roughness: 0.86 }),
    timber: new T.MeshStandardMaterial({ color: '#493a28', roughness: 0.9 }),
    stone: new T.MeshStandardMaterial({ color: '#717d7e', roughness: 0.3 }),
  };
  type Mat = keyof typeof materials;

  // Two batches: one bent onto the spine, one in honest world metres.
  const bent = new Map<Mat, T.BufferGeometry[]>();
  const world = new Map<Mat, T.BufferGeometry[]>();
  const pose = new T.Object3D();

  function add(
    target: Map<Mat, T.BufferGeometry[]>,
    geo: T.BufferGeometry, mat: Mat,
    x = 0, y = 0, z = 0, sx = 1, sy = 1, sz = 1, rx = 0, ry = 0, rz = 0,
  ) {
    pose.position.set(x, y, z); pose.rotation.set(rx, ry, rz); pose.scale.set(sx, sy, sz);
    pose.updateMatrix();
    const g = geo.clone().applyMatrix4(pose.matrix);
    // Batches carry positions and normals only; UVs would double the buffer.
    g.deleteAttribute('uv');
    const flat = g.index ? g.toNonIndexed() : g;
    if (flat !== g) g.dispose();
    (target.get(mat) ?? (target.set(mat, []), target.get(mat)!)).push(flat);
  }

  // … author the world with add(): rows of buildings, decks, kerbs, railings …

  for (const [source, warp] of [[bent, true], [world, false]] as const) {
    for (const [mat, parts] of source) {
      if (!parts.length) continue;
      const merged = mergeGeometries(parts, false)!;
      parts.forEach((p) => p.dispose());
      const mesh = new T.Mesh(merged, materials[mat]);
      mesh.name = `${warp ? 'spine' : 'world'}:${mat}`;
      mesh.castShadow = mesh.receiveShadow = true;
      root.add(mesh);
    }
  }

  return {
    root,
    update(t) { /* shader uniforms, drifting props */ },
    // React unmounts this on hot reload; the GPU resources are ours to free.
    dispose() {
      const geos = new Set<T.BufferGeometry>(); const mats = new Set<T.Material>();
      root.traverse((o) => {
        const m = o as T.Mesh; if (!m.geometry) return;
        geos.add(m.geometry);
        for (const mat of Array.isArray(m.material) ? m.material : [m.material]) mats.add(mat);
      });
      geos.forEach((g) => g.dispose());
      mats.forEach((m) => { (m as T.MeshStandardMaterial).map?.dispose(); m.dispose(); });
    },
  };
}
```

Mount it once:

```tsx
export function World() {
  const world = useMemo(() => buildWorld(), []);
  useEffect(() => () => world.dispose(), [world]);
  useFrame((_, dt) => {
    const { paused, speed } = useAppStore.getState();   // §5: getState, not a selector
    if (!paused) world.update(clock.advance(dt) * speed);
  });
  return <primitive object={world.root} />;
}
```

---

## 3. Placement is data

```ts
// src/world/placements.ts
export interface Placement {
  name: string;                       // stable id: store key, check key, URL fragment
  model: string;
  position: Vec3; rotation: Vec3; scale: Vec3;
  dimensions: Vec3;                   // measured from the GLB; used for labels and probes
  visible: boolean;
  material: { color: string; roughness: number };
}

/** Authored in the straight frame — for anything that follows the spine. */
const place = (name: string, model: string, position: Vec3, scale: Vec3, dimensions: Vec3, yaw = 0): Placement => ({
  name, model: `/models/${model}.glb`,
  position: bend(position), rotation: [0, yaw, 0], scale, dimensions,
  visible: true, material: { color: '#ffffff', roughness: 0.85 },
});

/** Authored in world metres — for anything that does not. Say why, at the call site. */
const placeWorld = (name: string, model: string, position: Vec3, scale: Vec3, dimensions: Vec3, yaw = 0): Placement => ({
  name, model: `/models/${model}.glb`, position, rotation: [0, yaw, 0], scale, dimensions,
  visible: true, material: { color: '#ffffff', roughness: 0.85 },
});

export const placements: Placement[] = [
  // Original opening is 5 m: widened to clear the channel at Z -7.
  // The end tread sits .54 above its origin; .49 seats it on the 1.03 deck.
  place('main-bridge', 'stone-bridge', [0, 0.49, -7], [2.08 * widthAt(-7) / 10.2, 1, 1.25], [30.48, 3.94, 3.06]),
  // Hull runs along local X, so turn it along the spine and immerse the keel.
  place('moored-boat', 'boat', [2.2, 0.015, 12.5], [0.86, 0.86, 0.86], [2.28, 1.72, 5], Math.PI / 2 + Math.atan(slope(12.5))),
  // World metres: the workshop lane follows a branch, not the main spine.
  placeWorld('dye-house', 'dye-house', [-28.85, 1.0, -56.71], [1, 1, 1], [4.2, 3.28, 3.12], 2.009),
];
```

Each placement mounts inside a store-backed root, so an editor panel and the
scene cannot disagree:

```tsx
export function PlacedRoot({ name, children }: { name: string; children: ReactNode }) {
  const state = useAppStore((s) => s.objects[name]);      // transform overrides
  const visible = useAppStore((s) => isVisible(name, s));
  const editing = useAppStore((s) => s.editing);
  return (
    <group
      name={name}
      position={state.position} rotation={state.rotation} scale={state.scale} visible={visible}
      // Raycasting this much geometry is only worth paying for inside the editor.
      onClick={editing ? (e) => { e.stopPropagation(); select(name); } : undefined}
    >
      {children}
    </group>
  );
}
```

**Say it in the docs:** editor changes are session-only; persisting a placement
means pasting the exported JSON back into this file.

---

## 4. Instanced scatter on a budget

Decide the triangle allowance first, then spend it. One detailed tree can be
278 k triangles against 800 for a procedural blob — forty of them can cost four
times the rest of the world.

```ts
// Placements from a seeded RNG + the frame's mask.
const place = (species: Species, x: number, z: number, scale: number, clearance = 0.5) => {
  if (isSpine(x, z, clearance)) return;                 // roots stay out of the water
  placements.push({ species, position: [lateral(x, z) + center(z), 1.02, z], yaw: rand() * Math.PI * 2, scale,
    // Only the near band pays for shadows.
    casts: Math.abs(x) < 52 && z > -108 });
};

/** Group key = species | shadow class | spatial band. One InstancedMesh per material per group. */
export const band = (z: number) => Math.floor(z / 80);
const groups = new Map<string, { species: Species; items: Placement[] }>();
for (const p of placements) {
  const key = `${p.species}|${p.casts}|${band(p.position[2])}`;
  (groups.get(key) ?? (groups.set(key, { species: p.species, items: [] }), groups.get(key)!)).items.push(p);
}
```

```tsx
function Grove({ species, items }: { species: Species; items: Placement[] }) {
  const { scene } = useGLTF(modelFor(species));
  const grove = useMemo(() => {
    const root = new Group();
    scene.updateMatrixWorld(true);
    const stands = items.map((p) => new Matrix4().compose(
      new Vector3(...p.position), new Quaternion().setFromEuler(new Euler(0, p.yaw, 0)), new Vector3(p.scale, p.scale, p.scale)));
    scene.traverse((o) => {
      if (!(o instanceof Mesh)) return;
      // Geometry and material stay the loader cache's: an instance adds a matrix.
      const im = new InstancedMesh(o.geometry, o.material, stands.length);
      stands.forEach((stand, i) => im.setMatrixAt(i, new Matrix4().multiplyMatrices(stand, o.matrixWorld)));
      im.instanceMatrix.needsUpdate = true;
      im.castShadow = items[0].casts; im.receiveShadow = true;
      im.computeBoundingSphere();                        // per-band frustum culling
      root.add(im);
    });
    return root;
  }, [scene, species, items]);
  // The instance matrices are ours; the geometry behind them is not.
  useEffect(() => () => grove.traverse((o) => { if (o instanceof InstancedMesh) o.dispose(); }), [grove]);
  return <primitive object={grove} />;
}
```

Banding is what makes a close camera cheap: the bands behind the viewer cull as
whole objects. Keep the counts in one file — that file is the dial.

---

## 5. Per-frame discipline

```ts
// Values the overlay re-renders on live in the store.
interface AppState { paused: boolean; mist: number; chapter: string; /* … */ }

// Values that change every frame do not.
export const clock = { t: 0, target: 0 };        // module ref, read in useFrame
```

```tsx
// Per-frame component: read, never subscribe.
useFrame((_, delta) => {
  const { paused, mist } = useAppStore.getState();
  material.uniforms.uFog.value = fogDensity(mist);
  if (!paused) elapsed.current += Math.min(delta, 0.05);
});

// Overlay progress bar: write the DOM directly rather than re-render at 60 Hz.
useEffect(() => {
  let frame = 0;
  const tick = () => { el.current!.style.transform = `scaleX(${clock.t / length})`; frame = requestAnimationFrame(tick); };
  frame = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(frame);
}, []);
```

A new `useAppStore(s => …)` inside a per-frame component re-renders the whole
canvas subtree every frame. It is the most common way a smooth scene goes slow.

---

## 6. An authored route, and one camera owner

For a continuous scripted walk. (For click-to-focus, follow and attract, use
`r3f-hero-camera` instead — poses beat paths whenever the viewer is driving.)

```ts
// src/tour/route.ts — keys in the authoring frame, bent at module load.
const K = (t: number, pos: Vec3, look: Vec3, fov: number, note?: string) => ({
  t, fov, note, pos: new Vector3(...bend(pos)), look: new Vector3(...bend(look)),
});
const W = (t: number, pos: Vec3, look: Vec3, fov: number, note?: string) => ({
  t, fov, note, pos: new Vector3(...pos), look: new Vector3(...look),
});

export const KEYS = [
  // Eye heights: deck 1.03 + 1.62 = 2.65 walking, 0.63 + 1.10 = 1.73 seated in a boat.
  K(0.0, [7.6, 2.65, 30.0], [7.0, 2.4, 24.0], 46, 'the opening frame'),
  K(19.4, [-0.4, 1.73, 0.5], [0.0, 1.9, -5.0], 54, 'the arch ahead'),
  W(38.8, [-25.03, 2.65, -56.81], [-29.8, 3.0, -63.4], 52, 'the dye house'),
];

const hermite = (p0: number, p1: number, m0: number, m1: number, s: number) => {
  const s2 = s * s, s3 = s2 * s;
  return (2 * s3 - 3 * s2 + 1) * p0 + (s3 - 2 * s2 + s) * m0 + (-2 * s3 + 3 * s2) * p1 + (s3 - s2) * m1;
};

/** Nonuniform timed Hermite over position, gaze and fov. A Catmull-Rom spline
 *  cuts the corner between two collision-free keys and puts the near plane
 *  through a wall. */
export function sampleRoute(t: number, out: { pos: Vector3; look: Vector3; fov: number }) {
  const n = KEYS.length;
  if (t <= KEYS[0].t || t >= KEYS[n - 1].t) { const k = t <= KEYS[0].t ? KEYS[0] : KEYS[n - 1];
    out.pos.copy(k.pos); out.look.copy(k.look); out.fov = k.fov; return out; }
  let i = 0; while (i < n - 2 && t >= KEYS[i + 1].t) i++;
  const k0 = KEYS[i], k1 = KEYS[i + 1], km = KEYS[Math.max(0, i - 1)], kp = KEYS[Math.min(n - 1, i + 2)];
  const h = k1.t - k0.t, s = (t - k0.t) / h;
  const axis = (g: (k: typeof k0) => number) =>
    hermite(g(k0), g(k1), ((g(k1) - g(km)) / (k1.t - km.t)) * h, ((g(kp) - g(k0)) / (kp.t - k0.t)) * h, s);
  out.pos.set(axis((k) => k.pos.x), axis((k) => k.pos.y), axis((k) => k.pos.z));
  out.look.set(axis((k) => k.look.x), axis((k) => k.look.y), axis((k) => k.look.z));
  out.fov = axis((k) => k.fov);
  return out;
}
```

```tsx
// src/tour/Director.tsx — the ONLY thing that writes the camera on this page.
export function Director() {
  const camera = useThree((s) => s.camera) as PerspectiveCamera;

  useEffect(() => {
    // Capture mode: ?t=19 pins the coordinate so a still can be taken exactly.
    const pinned = Number(new URLSearchParams(location.search).get('t'));
    window.tour = { seek: (t) => { clock.t = clock.target = t; }, get t() { return clock.t; },
                    sample: (t) => { sampleRoute(t, probe); return { pos: probe.pos.toArray(), fov: probe.fov }; } };
    if (Number.isFinite(pinned) && location.search.includes('t=')) { clock.t = clock.target = pinned; return; }

    clock.t = clock.target = tFromScroll();          // a reload mid-page must not snap to 0
    const onScroll = () => { clock.target = tFromScroll(); };
    const onResize = () => window.scrollTo({ top: scrollFor(clock.target), behavior: 'instant' as ScrollBehavior });
    addEventListener('scroll', onScroll, { passive: true });
    addEventListener('resize', onResize);
    return () => { removeEventListener('scroll', onScroll); removeEventListener('resize', onResize); delete window.tour; };
  }, []);

  useFrame((_, delta) => {
    const dt = Math.min(delta, 0.05);
    // Reduced motion: track the scroll exactly — the viewer's gesture is the only movement.
    clock.t = reducedMotion() ? clock.target : clock.t + (clock.target - clock.t) * (1 - Math.exp(-dt * 6));
    sampleRoute(clock.t, pose);
    camera.position.copy(pose.pos);
    camera.lookAt(pose.look);
    if (Math.abs(camera.fov - pose.fov) > 0.01) { camera.fov = pose.fov; camera.updateProjectionMatrix(); }

    const chapter = chapterAt(clock.t);
    if (chapter.id !== useTourStore.getState().chapter) {
      useTourStore.getState().setChapter(chapter.id);
      history.replaceState(null, '', `#${chapter.id}`);   // meaningful navigation, not every frame
    }
  });
  return null;
}
```

**Scroll is the spine of a tour page.** A tall sizer element behind a fixed
canvas maps `scrollY → t`; the written sections scroll over the canvas as real
HTML, so touch scrolling, keyboard paging and screen readers all keep working,
and the copy exists without WebGL.

Chapters are `{ id, label, a, b, at }`; `chapterAt` takes the last `a <= t`.
**Author `at` strictly inside `(a, b)`** or a stop lands on the next chapter.

---

## 7. Verification

### 7.1 The shape of the check

```js
const page = await browser.newPage({ viewport: { width: 1200, height: 750 }, deviceScaleFactor: 1 });
page.setDefaultTimeout(120_000);                       // swiftshader frames are slow
await page.goto(`${base}/tour?t=0`);
await page.waitForFunction(() => window.town?.store.getState().ready === true, { timeout: 180_000 });

// One camera owner: the page must not mount a damped controller at all.
assert.equal(await page.evaluate(() => window.town.controls), null);

for (const [i, chapter] of chapters.entries()) {
  await page.evaluate((t) => window.tour.seek(t), chapter.at);
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  await page.screenshot({ path: `artifacts/tour-${String(i).padStart(2, '0')}-${chapter.id}.png` });
}
```

Expose a read-only handle from the renderer (`window.<app> = { renderer, scene,
camera, controls, store }`) and a route handle (`seek`, `t`, `sample`,
`clearance`). Checks that drive the app through its own handle beat checks that
scroll and hope.

### 7.2 Measure before authoring

Dump real world boxes, then write camera keys against the numbers:

```js
const box = await page.evaluate((names) => Object.fromEntries(names.map((n) => {
  const o = window.town.scene.getObjectByName(n); if (!o) return [n, null];
  const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
  o.updateWorldMatrix(true, true);
  o.traverse((c) => { const g = c.geometry; if (!g?.attributes?.position) return;
    const p = g.attributes.position, m = c.matrixWorld.elements;
    for (let i = 0; i < p.count; i += Math.max(1, Math.floor(p.count / 400))) {
      const x = p.getX(i), y = p.getY(i), z = p.getZ(i);
      const w = [m[0]*x+m[4]*y+m[8]*z+m[12], m[1]*x+m[5]*y+m[9]*z+m[13], m[2]*x+m[6]*y+m[10]*z+m[14]];
      for (let k = 0; k < 3; k++) { min[k] = Math.min(min[k], w[k]); max[k] = Math.max(max[k], w[k]); }
    }});
  return [n, { min, max }];
})), ['main-bridge', 'tea-pavilion', 'covered-walkway']);
```

This is how you learn the deck is at 2.26 and the lane is 2.6 m wide — before
authoring a walk that assumed otherwise.

### 7.3 Clearance sweep

Sample the interpolated path without rendering it:

```ts
clearance: (t: number) => {
  sampleRoute(t, probe);
  const solids: Object3D[] = [];
  // Instanced foliage is scenery, not collision.
  scene.traverse((o) => { if (o instanceof Mesh && !(o as InstancedMesh).isInstancedMesh) solids.push(o); });
  let nearest = Infinity;
  for (const dir of PROBES) {                            // ±X, ±Z unit vectors
    ray.set(probe.pos, dir);
    const hit = ray.intersectObjects(solids, false)[0];
    if (hit && hit.distance < nearest) nearest = hit.distance;
  }
  return Number.isFinite(nearest) ? nearest : null;
}
```

Assert the eye never drops below its floor, and that no more than a couple of
samples come closer than ~0.6 m. Print the tight ones with their `t` so they can
be re-framed.

---

## 8. Lighting, shadows and quality

```tsx
// The sun never moves: render the shadow map on demand, not every frame.
useEffect(() => { gl.shadowMap.autoUpdate = false; gl.shadowMap.needsUpdate = true; }, [gl, ready, objects]);
useFrame(() => { if (useAppStore.getState().editing) gl.shadowMap.needsUpdate = true; });
```

- Size the directional light's ortho box to the part of the world the camera
  visits; everything outside is flat-lit.
- Cap DPR (`dpr={[1, 1.75]}`) and mount `AdaptiveDpr`. Fixed high-resolution
  rendering is the wrong trade for a fill-bound world.
- At eye height set `near` ≈ 0.12 and re-check depth precision on far landmarks.
- Preload by route proximity rather than preloading every model at once, and
  keep a failed optional asset from trapping navigation (error boundary around
  the suspense boundary).
- A quality tier chosen from a first-second frame-time probe is worth more than
  any single micro-optimisation: tier down to no DoF, no bloom, no scatter
  shadows, DPR 1.

---

## 9. Weather and shed particles

One weather state, layered wind, and particle fields that belong to the objects
they come from. The engine-neutral craft rules for these live in the `3d`
specialist guides (`rainfall-effects`, `falling-leaves`, `sky-cloud-systems`);
this section is the R3F shape.

### 9.1 One state, one clock

```ts
// src/weather/state.ts — parameters in the store (the overlay re-renders on
// these), simulation time in a module ref (it changes every frame).
export interface Weather {
  rainIntensity: number;   // 0 drizzle-off … 1 downpour
  wetness: number;         // 0 dry … 1 soaked; rises with rain, dries on a curve
  fogDensity: number;
  skyBrightness: number;
  cloudiness: number;
  windStrength: number;    // base vector magnitude
  gustStrength: number;    // swell amplitude
  turbulence: number;      // small-scale noise amplitude
  leafCount: number;       // live budget, not a per-frame count
  leafFallSpeed: number;
  seed: number;
}

export const sim = { t: 0 };   // seconds. Advanced by ONE useFrame, below.

/**
 * Advance once per frame, from the clock the host's pause and capture modes
 * control. Everything else reads `sim.t` — never performance.now(), or a still
 * pinned at a given scene time differs between runs and comparison shots are
 * worthless.
 */
export function WeatherClock() {
  useFrame((_, delta) => {
    const { paused } = useAppStore.getState();
    if (!paused) sim.t += Math.min(delta, 0.05);
  });
  return null;
}
```

### 9.2 Layered wind

```ts
// Global direction + gusts (seconds) + turbulence (per-position noise).
// Same function for leaves, rain slant, foliage sway and banners.
const dir = new Vector3(0.82, 0, 0.57).normalize();

export function windAt(p: Vector3, t: number, w: Weather, out: Vector3) {
  // Base: direction turns slowly, so the shot's drift is never quite constant.
  const turn = Math.sin(t * 0.017) * 0.35;
  out.set(dir.x * Math.cos(turn) - dir.z * Math.sin(turn), 0, dir.x * Math.sin(turn) + dir.z * Math.cos(turn));
  out.multiplyScalar(w.windStrength);

  // Gusts: two detuned slow waves, travelling across the world along the wind
  // axis (the phase depends on position) so the field does not surge as one.
  const travel = (p.x * dir.x + p.z * dir.z) * 0.04;
  const gust = (Math.sin(t * 0.21 - travel) * 0.6 + Math.sin(t * 0.09 - travel * 0.7) * 0.4);
  out.addScaledVector(out.clone().normalize(), Math.max(0, gust) * w.gustStrength);

  // Turbulence: cheap curl-ish noise. This is what makes a leaf spiral and
  // occasionally lift instead of tracking a clean parabola.
  const n = (a: number, b: number, c: number) => Math.sin(a * 1.7 + t * 0.9) * Math.cos(b * 1.3 - t * 0.7) * Math.sin(c * 2.1 + t * 0.5);
  out.x += n(p.z * 0.3, p.y * 0.4, p.x * 0.2) * w.turbulence;
  out.y += n(p.x * 0.25, p.z * 0.35, p.y * 0.3) * w.turbulence * 0.8;
  out.z += n(p.y * 0.2, p.x * 0.3, p.z * 0.25) * w.turbulence;
  return out;
}
```

### 9.3 The leaf belongs to its tree

Resolve the shed profile from the species the scatter already placed (§4), and
emit from real crowns — never a box over the camera.

```ts
// src/weather/leafProfiles.ts
export interface LeafProfile {
  kind: 'leaf' | 'petal' | 'strand';
  colors: string[];          // per-leaf pick, not one tint for the field
  size: [number, number];    // metres, at world scale
  drag: number;              // higher = slower terminal fall
  flutter: [number, number]; // Hz band
  spin: [number, number];    // rad/s band, applied on two axes
  rate: number;              // releases per crown per second at windStrength 1
  season?: (t: number) => number;   // 0..1 gate; blossom only in its window
}

// Keyed by the SAME species id the placements use. Unknown key throws — a silent
// generic-leaf fallback is invisible in review and obvious on screen.
export const LEAF_PROFILES: Record<string, LeafProfile> = {
  'weeping-willow':      { kind: 'strand', colors: ['#8fa06a', '#9fae7c'], size: [0.10, 0.20], drag: 0.7, flutter: [1.2, 2.2], spin: [0.6, 1.8], rate: 0.10 },
  'camphor-tree':        { kind: 'leaf',   colors: ['#6f8a5a', '#87a06b'], size: [0.07, 0.13], drag: 1.5, flutter: [0.5, 1.1], spin: [0.8, 2.4], rate: 0.16 },
  'osmanthus-tree':      { kind: 'petal',  colors: ['#e8c877', '#f0d89a'], size: [0.02, 0.04], drag: 2.2, flutter: [1.6, 2.8], spin: [1.2, 3.0], rate: 0.22, season: autumnWindow },
  'peach-blossom-tree':  { kind: 'petal',  colors: ['#f2c2cc', '#f7d7de'], size: [0.03, 0.05], drag: 2.4, flutter: [1.4, 2.6], spin: [1.0, 2.6], rate: 0.30, season: springWindow },
  'plum-blossom-tree':   { kind: 'petal',  colors: ['#f6e3ea', '#ffffff'], size: [0.025, 0.045], drag: 2.4, flutter: [1.5, 2.7], spin: [1.0, 2.6], rate: 0.26, season: earlySpringWindow },
};

export const profileFor = (species: string) => {
  const p = LEAF_PROFILES[species];
  if (!p) throw new Error(`No leaf profile for species "${species}" — add one or exclude it from shedding.`);
  return p;
};
```

```ts
// Emitters are the trees themselves: crown centre and radius from the placement.
export const emitters = placements
  .filter((p) => p.species in LEAF_PROFILES)
  .map((p) => ({
    species: p.species,
    // Crown sits in the upper third of the tree; radius scales with the instance.
    origin: new Vector3(p.position[0], p.position[1] + p.height * p.scale * 0.72, p.position[2]),
    radius: p.crownRadius * p.scale,
    rate: profileFor(p.species).rate,
  }));

/** Only crowns near the camera emit; count and emitters are both capped. */
export function activeEmitters(camera: Vector3, budget = 12) {
  return emitters
    .map((e) => ({ e, d: e.origin.distanceToSquared(camera) }))
    .filter(({ d }) => d < 45 * 45)
    .sort((a, b) => a.d - b.d)
    .slice(0, budget)
    .map(({ e }) => e);
}
```

### 9.4 One instanced field per species

```tsx
function LeafField({ species }: { species: string }) {
  const profile = profileFor(species);
  const cap = Math.round(useAppStore.getState().weather.leafCount * shareFor(species));
  const mesh = useRef<InstancedMesh>(null);

  // Pool: plain typed arrays, allocated once. No object churn, no per-leaf node.
  const pool = useMemo(() => ({
    pos: new Float32Array(cap * 3), vel: new Float32Array(cap * 3),
    spin: new Float32Array(cap * 3), quat: new Float32Array(cap * 4),
    size: new Float32Array(cap), phase: new Float32Array(cap),
    age: new Float32Array(cap), life: new Float32Array(cap),
    alive: new Uint8Array(cap), head: 0, births: 0,
  }), [cap]);

  useFrame((_, delta) => {
    const dt = Math.min(delta, 0.05);
    const w = useAppStore.getState().weather;
    if (useAppStore.getState().paused) return;

    // Fractional births: accumulate a rate, never spawn a fixed count per frame.
    // Poisson-ish irregularity comes from the random threshold, not a jittered cadence.
    for (const e of activeEmitters(cameraPos)) {
      pool.births += e.rate * (0.6 + w.windStrength * 0.8) * gustNow(w) * dt;
      while (pool.births > 1) { pool.births -= 1; if (rand() < 0.85) spawn(pool, e, profile, w); }
    }

    // Integrate. Broadside drag slows a leaf; edge-on it slips — that asymmetry
    // is most of what separates a leaf from a falling coin.
    for (let i = 0; i < cap; i++) {
      if (!pool.alive[i]) continue;
      p.fromArray(pool.pos, i * 3); v.fromArray(pool.vel, i * 3);
      windAt(p, sim.t, w, wind);
      const face = Math.abs(Math.sin(pool.phase[i] + sim.t * pool.spin[i * 3 + 1]));   // 0 edge-on … 1 broadside
      const drag = profile.drag * (0.45 + face) * (1 + w.wetness * 0.6);               // wet leaves fall heavier
      v.addScaledVector(gravity, dt * (1 - w.wetness * 0.05));
      v.addScaledVector(wind.sub(v), Math.min(1, drag * dt));
      v.y -= v.y * face * drag * dt * 0.5;                                             // stall on the broadside
      p.addScaledVector(v, dt * w.leafFallSpeed);
      // … write back, advance the two spin axes, age, recycle on contact/lifetime …
    }
    // One buffer upload for the whole species.
    mesh.current!.instanceMatrix.needsUpdate = true;
  });

  return (
    <instancedMesh ref={mesh} args={[leafGeometry(profile), leafMaterial(profile), cap]} frustumCulled={false}>
    </instancedMesh>
  );
}
```

At high counts move the whole integration into the vertex shader: upload seed,
birth time, size and profile constants once per instance, evaluate position and
orientation from `uTime` plus the wind uniforms, and accept that collision and
settling are no longer available.

### 9.5 Drizzle that reads by contrast

```ts
// Streaks are one instanced field in a camera-following volume; drops keep
// world motion so rotating the camera never drags the rain with it.
// Fragment: fade the streak toward the sky and hold it against dark geometry.
const fragment = /* glsl */ `
  varying float vDepthFade;
  varying float vSeed;
  uniform float uIntensity;
  void main() {
    // Sparse and fine: opacity is low, length is short, and the streak all but
    // disappears against a bright background. Legibility comes from what is
    // BEHIND it, not from raising the count.
    float core = smoothstep(1.0, 0.0, abs(vUv.x - 0.5) * 2.0);
    float alpha = core * 0.18 * uIntensity * vDepthFade;
    gl_FragColor = vec4(vec3(0.86, 0.90, 0.94), alpha);
  }
`;
```

- Bias the spawn volume toward the darker half of the shot rather than raising
  global density — a drizzle that reads everywhere is no longer a drizzle.
- Drive `uIntensity` from `rainIntensity` modulated a few percent by a slow
  `sim.t` wave, so the fall breathes.
- Ripples, darkened stone and eave drips carry the read at this intensity; build
  them before the streaks.
- Keep bloom thresholds high (this project's is 0.82); check the brightest sky
  region with the effect on and off.

### 9.6 What this must not break

- `paused` freezes weather with the rest of the scene.
- The existing fog/mist control stays the single source of `fogDensity`; weather
  rides it rather than adding a second fog.
- Particle fields do not need shadow-map refreshes — keep the cached shadow map
  (§8) and exclude them from `castShadow`.
- Clearance and walk probes already skip `InstancedMesh` (§7.3), which is what
  keeps a leaf field from reading as a wall.
