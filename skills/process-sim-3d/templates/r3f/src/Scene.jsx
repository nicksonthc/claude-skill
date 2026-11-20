// The 3D side in React Three Fiber. The world and the sim live in refs, NOT React state: they change every
// frame, and putting them in state would re-render React 60x a second. useFrame steps the sim and the rig;
// the panels read a status snapshot a few times a second (see App.jsx).
import { useEffect, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { createRig, createLabels } from './core/rig.js';
import { materials } from './core/mats.js';
import { spec } from './sim/spec.js';
import { buildWorld } from './sim/world.js';
import { createSim } from './sim/sim.js';

export default function Scene({ cfg, S, simRef, rigRef, version, onCaption }) {
  const { scene, camera, gl } = useThree();
  const labelsRef = useRef(() => {});
  useEffect(() => { // environment + lights once
    scene.background = new THREE.Color(0xc9d0d4); scene.fog = new THREE.Fog(0xc9d0d4, 30, 80);
    scene.environment = new THREE.PMREMGenerator(gl).fromScene(new RoomEnvironment(), 0.03).texture; scene.environmentIntensity = 0.34;
    const hemi = new THREE.HemisphereLight(0xffffff, 0x9aa2a9, 0.6), key = new THREE.DirectionalLight(0xfff4e6, 2.6);
    key.position.set(7, 11, -5); key.castShadow = true; key.shadow.mapSize.set(2048, 2048);
    Object.assign(key.shadow.camera, { left: -7, right: 7, top: 6, bottom: -6, near: 2, far: 30 });
    scene.add(hemi, key);
    rigRef.current = createRig(camera, gl.domElement, { ...spec.camera, onUserInput: () => (S.auto = false) });
    rigRef.current.go(spec.views.overview, true);
    return () => { scene.remove(hemi, key); rigRef.current.controls.dispose(); };
  }, []);
  useEffect(() => { // (re)build world + sim when a restart-param changes
    const world = buildWorld(scene, cfg, spec);
    simRef.current = createSim(world, cfg, spec);
    labelsRef.current = createLabels(document.getElementById('labels'), camera, world.labels);
    const M = materials(), m = S.encl;
    M.skin.transparent = m === 'glass'; M.skin.opacity = m === 'glass' ? 0.07 : 1; M.skin.depthWrite = m !== 'glass'; M.skin.needsUpdate = true;
    world.skins.forEach((s) => (s.visible = m !== 'hidden')); world.glass.forEach((s) => (s.visible = m !== 'hidden'));
    simRef.current.world = world;
    return () => world.dispose();
  }, [version]);
  useFrame((_, delta) => {
    const sim = simRef.current, rig = rigRef.current, real = Math.min(0.1, delta);
    if (!sim || !rig) return;
    if (S.playing) { const dt = real * S.speed, n = Math.min(4000, Math.max(1, Math.ceil(dt / 0.05))); for (let i = 0; i < n; i++) sim.sched.step(dt / n); }
    if (S.mode === 'walkthrough' && !rig.flying) {
      S.tourT += real;
      if (S.tourT > 6) { S.tourT = 0; S.tour = (S.tour + 1) % spec.tour.length; const t = spec.tour[S.tour]; rig.go(spec.views[t.view], false, 1.6); onCaption(t.caption); }
    }
    rig.update(real);
    if (S.labels) labelsRef.current(innerWidth, innerHeight);
  });
  // priority 1 = this frame callback owns rendering: skip drawing while headless experiments run (S.busy)
  useFrame(({ gl: r, scene: sc, camera: cam }) => { if (!S.busy) r.render(sc, cam); }, 1);
  return null;
}
