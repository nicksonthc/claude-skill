// Standalone shell: renderer + lighting + post, camera rig, world/sim lifecycle, walkthrough tour,
// auto-cam, compare dialog, and window.__sim hooks for tools/check.mjs. Machine-agnostic.
import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { materials } from './core/mats.js';
import { createRig, createLabels } from './core/rig.js';
import { spec, makeConfig } from './sim/spec.js';
import { buildWorld } from './sim/world.js';
import { createSim } from './sim/sim.js';
import { runCompare } from './sim/experiment.js';
import { buildUI } from './ui.js';

const qs = new URLSearchParams(location.search);
const canvas = document.getElementById('c');

function boot() {
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' }); }
  catch (e) { document.getElementById('err').style.display = 'grid'; return; }
  const DPR = Math.min(window.devicePixelRatio || 1, 2);
  renderer.setPixelRatio(DPR);
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.NeutralToneMapping;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xc9d0d4); scene.fog = new THREE.Fog(0xc9d0d4, 30, 80);
  scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.03).texture;
  scene.environmentIntensity = 0.34;
  const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 120);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x9aa2a9, 0.6));
  const key = new THREE.DirectionalLight(0xfff4e6, 2.6);
  key.position.set(7, 11, -5); key.castShadow = true; key.shadow.mapSize.set(2048, 2048);
  Object.assign(key.shadow.camera, { left: -7, right: 7, top: 6, bottom: -6, near: 2, far: 30 });
  key.shadow.bias = -0.00025; key.shadow.normalBias = 0.02;
  scene.add(key);

  // bloom keys on SATURATED light (hot cells, LEDs), not luminance, so white paint never hazes
  const composer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(4, 4, { type: THREE.HalfFloatType, samples: 4 }));
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(4, 4), 0.55, 0.5, 1.5);
  bloom.materialHighPassFilter.fragmentShader = `uniform sampler2D tDiffuse; uniform vec3 defaultColor; uniform float defaultOpacity; uniform float luminosityThreshold; uniform float smoothWidth; varying vec2 vUv;
    void main(){ vec4 t=texture2D(tDiffuse,vUv); float mx=max(t.r,max(t.g,t.b)), mn=min(t.r,min(t.g,t.b)); float sat=mx>1e-4?(mx-mn)/mx:0.0;
    gl_FragColor=mix(vec4(defaultColor,defaultOpacity),t,smoothstep(luminosityThreshold,luminosityThreshold+smoothWidth,mx*(0.35+0.65*sat))); }`;
  bloom.materialHighPassFilter.needsUpdate = true;
  composer.addPass(bloom); composer.addPass(new OutputPass());

  const S = { playing: true, speed: 1, view: 'overview', encl: 'glass', labels: true, auto: false, busy: false, mode: qs.get('mode') || spec.mode, tour: 0, tourT: 0 };
  const rig = createRig(camera, canvas, { ...spec.camera, onUserInput: () => { if (S.auto) { S.auto = false; ui.setAuto(false); } } });

  const cfg = makeConfig();
  for (const [k, v] of qs) if (k in cfg && isFinite(Number(v))) cfg[k] = Number(v);
  if (qs.get('continuous') === '0') cfg.continuous = false;
  const M = materials();
  let world = null, sim = null, labels = () => {};
  function applyEncl() {
    const m = S.encl;
    M.skin.transparent = m === 'glass'; M.skin.opacity = m === 'glass' ? 0.07 : 1; M.skin.depthWrite = m !== 'glass'; M.skin.needsUpdate = true;
    world.skins.forEach((s) => { s.visible = m !== 'hidden'; s.renderOrder = m === 'glass' ? 9 : 0; });
    world.glass.forEach((s) => (s.visible = m !== 'hidden'));
  }
  function restart() {
    if (world) world.dispose();
    world = buildWorld(scene, cfg, spec);
    sim = createSim(world, cfg, spec);
    labels = createLabels(document.getElementById('labels'), camera, world.labels);
    applyEncl(); ui.update(sim);
  }
  function setMode(m) {
    S.mode = m; document.body.classList.toggle('walk', m === 'walkthrough');
    S.tour = 0; S.tourT = 0; ui.caption(m === 'walkthrough' ? spec.tour[0].caption : '');
    if (m === 'walkthrough') rig.go(spec.views[spec.tour[0].view]);
  }

  const cmp = { rows: null, running: false };
  async function runCmp() {
    if (cmp.running) return;
    cmp.running = true; S.busy = true; const was = S.playing; S.playing = false;
    const c = spec.compare, body = document.getElementById('cmpBody');
    document.getElementById('cmpTitle').textContent = `${c.values.map(c.label).join(' vs ')} — ${spec.params.find((p) => p.key === c.sweep.key).label}`;
    cmp.rows = await runCompare(spec, { ...cfg }, c, (f) => (document.getElementById('cmpNote').textContent = `Simulating… ${Math.round(f * 100)}%`));
    document.getElementById('cmpNote').textContent = 'Steady state, continuous feed, same timings as the live run.';
    const f1 = (r) => (r ? r.uph.toFixed(1) : 'no steady state');
    body.innerHTML = `<table class="ct"><thead><tr><th>${c.sweep.key}</th>${c.values.map((v) => `<th>${c.label(v)} UPH</th>`).join('')}<th>Gain</th></tr></thead><tbody>${cmp.rows.map((r) => {
      const a = r[c.values[0]], b = r[c.values[c.values.length - 1]], g = a && b ? ((b.uph / a.uph - 1) * 100).toFixed(1) + '%' : '—';
      return `<tr><th>${r.x}</th>${c.values.map((v) => `<td>${f1(r[v])}</td>`).join('')}<td>${g}</td></tr>`;
    }).join('')}</tbody></table>`;
    S.playing = was; S.busy = false; cmp.running = false;
  }

  const ui = buildUI(spec, cfg, {
    play: () => { S.playing = !S.playing; ui.setPlaying(S.playing); },
    restart, speed: (v) => (S.speed = v),
    view: (v) => { S.view = v; rig.go(spec.views[v]); },
    mode: setMode, encl: (m) => { S.encl = m; applyEncl(); },
    labels: (v) => { S.labels = v; document.getElementById('labels').style.display = v ? '' : 'none'; },
    auto: (v) => (S.auto = v),
    compare: () => { document.getElementById('cmp').classList.add('show'); if (!cmp.rows) runCmp(); },
  });
  document.getElementById('cmpClose').onclick = () => document.getElementById('cmp').classList.remove('show');
  document.getElementById('cmpRun').onclick = runCmp;
  restart();
  setMode(S.mode);
  rig.go(spec.views.overview, true);

  function resize() { const w = innerWidth, h = innerHeight; renderer.setSize(w, h, false); composer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); }
  addEventListener('resize', resize); resize();
  addEventListener('keydown', (e) => { if (e.target.tagName === 'INPUT') return; if (e.code === 'Space') { e.preventDefault(); S.playing = !S.playing; ui.setPlaying(S.playing); } });

  const advance = (dt) => { if (dt <= 0) return; const n = Math.min(4000, Math.max(1, Math.ceil(dt / 0.05))); for (let i = 0; i < n; i++) sim.sched.step(dt / n); };
  let last = performance.now(), hudAt = 0, lastCut = 0;
  function frame(now) {
    const real = Math.min(0.1, (now - last) / 1000); last = now;
    if (S.playing) advance(real * S.speed);
    if (S.mode === 'walkthrough' && !rig.flying) { // tour: hold each shot ~6 s, then fly to the next
      S.tourT += real;
      if (S.tourT > 6) { S.tourT = 0; S.tour = (S.tour + 1) % spec.tour.length; const t = spec.tour[S.tour]; rig.go(spec.views[t.view], false, 1.6); ui.caption(t.caption); }
    }
    rig.update(real);
    if (!S.busy) composer.render(); // experiments: skip drawing, or every yield pays for a frame
    if (now - hudAt > 110) {
      hudAt = now; const s = ui.update(sim);
      if (S.auto && S.mode === 'simulation' && now - lastCut > 3500) {
        const want = s.flags.load || s.flags.unload ? 'robot' : s.flags.process ? 'nests' : s.flags.arrive || s.flags.leave ? 'conveyors' : 'overview';
        if (want !== S.view) { lastCut = now; S.view = want; ui.setView(want); rig.go(spec.views[want]); }
      }
    }
    if (S.labels) labels(innerWidth, innerHeight);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  window.__sim = { get sim() { return sim; }, get world() { return world; }, cfg, S, camera, rig, renderer, restart, advance, setMode, runCmp, cmp,
    setPlaying(p) { S.playing = p; ui.setPlaying(p); }, goView: (v, i) => rig.go(spec.views[v], i), views: Object.keys(spec.views) };
}
boot();
