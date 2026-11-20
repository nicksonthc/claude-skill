// Camera rig shared by both stacks: OrbitControls + the rules every process scene needs.
//  - macOS trackpad pinch arrives as ctrl+wheel: swallow it and re-dispatch a plain wheel (dolly) with gain,
//    so the lens (camera.zoom / fov) never changes and min/maxDistance keep working
//  - lens pinned (minZoom = maxZoom = 1), tilt clamped so the camera never flips or goes under the floor
//  - Cmd/Ctrl-drag pans; OrbitControls swaps ROTATE<->PAN itself while a modifier is held, so LEFT stays ROTATE
//  - views fly with smoothstep; any user input cancels the flight
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

export const PINCH_DOLLY_GAIN = 3;

export function createRig(camera, canvas, { minDistance = 0.6, maxDistance = 20, clampTarget = null, onUserInput = () => {} } = {}) {
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true; controls.dampingFactor = 0.09;
  controls.minDistance = minDistance; controls.maxDistance = maxDistance;
  controls.minPolarAngle = 0.08; controls.maxPolarAngle = Math.PI / 2 - 0.04;
  controls.minZoom = 1; controls.maxZoom = 1;
  camera.zoom = 1; camera.updateProjectionMatrix();
  canvas.addEventListener('wheel', (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault(); e.stopImmediatePropagation();
    canvas.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, clientX: e.clientX, clientY: e.clientY, deltaY: e.deltaY * PINCH_DOLLY_GAIN, deltaMode: e.deltaMode }));
  }, { capture: true, passive: false });
  canvas.addEventListener('pointerdown', () => { controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE; fly.on = false; onUserInput(); }, { capture: true });
  canvas.addEventListener('wheel', () => { fly.on = false; onUserInput(); }, { passive: true });
  if (clampTarget) controls.addEventListener('change', () => {
    const t = controls.target, [x, y, z] = clampTarget;
    t.x = THREE.MathUtils.clamp(t.x, x[0], x[1]); t.y = THREE.MathUtils.clamp(t.y, y[0], y[1]); t.z = THREE.MathUtils.clamp(t.z, z[0], z[1]);
  });

  const fly = { on: false, t: 0, dur: 1, p0: new THREE.Vector3(), p1: new THREE.Vector3(), t0: new THREE.Vector3(), t1: new THREE.Vector3() };
  return {
    controls,
    go([p, t], instant = false, dur = 1.1) {
      if (instant) { camera.position.set(...p); controls.target.set(...t); controls.update(); fly.on = false; return; }
      fly.p0.copy(camera.position); fly.t0.copy(controls.target); fly.p1.set(...p); fly.t1.set(...t);
      fly.t = 0; fly.dur = dur; fly.on = true;
    },
    get flying() { return fly.on; },
    update(dt) {
      if (fly.on) {
        fly.t = Math.min(1, fly.t + dt / fly.dur);
        const k = fly.t * fly.t * (3 - 2 * fly.t);
        camera.position.lerpVectors(fly.p0, fly.p1, k); controls.target.lerpVectors(fly.t0, fly.t1, k);
        if (fly.t >= 1) fly.on = false;
      }
      controls.update();
    },
    dist: () => camera.position.distanceTo(controls.target),
  };
}

// Project world-anchored labels to screen each frame. labels: [{ p: Vector3, text, cls }] from the world.
export function createLabels(host, camera, labels, { near = 1.2, far = 9, farBig = 26 } = {}) {
  host.innerHTML = '';
  const v3 = new THREE.Vector3();
  const els = labels.map((l) => { const e = document.createElement('div'); e.className = 'tag ' + (l.cls || ''); e.textContent = l.text; host.appendChild(e); return { e, l, on: false }; });
  return function update(w, h, offset = null) {
    for (const x of els) {
      v3.copy(x.l.p); if (offset && x.l.cell) v3.add(offset);
      const d = camera.position.distanceTo(v3);
      v3.project(camera);
      const vis = v3.z < 1 && Math.abs(v3.x) < 1.02 && Math.abs(v3.y) < 1.02 && d < (x.l.cls === 'big' ? farBig : far) && d > near;
      if (vis) x.e.style.transform = `translate(${((v3.x + 1) / 2) * w}px,${((1 - v3.y) / 2) * h}px) translate(-50%,-100%) translateY(-10px)`;
      if (vis !== x.on) { x.on = vis; x.e.style.display = vis ? '' : 'none'; }
    }
  };
}
