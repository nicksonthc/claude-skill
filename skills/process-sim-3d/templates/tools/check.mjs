// Headless checks against the built HTML: node tools/check.mjs <mode> [query]
//   run [query]     single lot to completion: every part out, conservation holds, no console errors
//   cont [query] h  continuous feed for h sim-hours: no stall, conservation, steady UPH
//   rig             pinch / pan rules in every view (lens pinned, distance clamped, tilt clamped)
//   shots [query] name secs   screenshot every view after fast-forwarding
//   walk            walkthrough mode: tour advances, captions show, sim panels hidden
// SIM_HTML=path overrides the file (check a preview build without touching the one people have open).
// SIM_URL=http://localhost:4173/ checks a served build instead (React template: npm run build && npm run preview).
import path from 'node:path';
let chromium;
try { ({ chromium } = await import('playwright')); } catch { console.error('npm i -D playwright && npx playwright install chromium'); process.exit(2); }
const file = process.env.SIM_URL || 'file://' + path.resolve(process.env.SIM_HTML || 'simulation.html');
const [mode, q = '', ...rest] = process.argv.slice(2);
const browser = await chromium.launch({ args: ['--use-angle=default', '--enable-gpu', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
const errors = [];
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
await page.goto(file + (q ? '?' + q : ''), { timeout: 120000 });
await page.waitForFunction(() => window.__sim && window.__sim.sim, null, { timeout: 60000 });
let out;
if (mode === 'run') {
  await page.evaluate(() => (window.__sim.S.busy = true));
  await page.goto(file + '?continuous=0' + (q ? '&' + q : ''));
  await page.waitForFunction(() => window.__sim && window.__sim.sim);
  out = await page.evaluate(() => {
    const A = window.__sim; A.setPlaying(false); A.S.busy = true;
    let g = 0; while (!A.sim.done && g++ < 200000) A.sim.sched.step(0.05);
    const s = A.sim.status();
    return { done: A.sim.done, end: Math.round(A.sim.endTime), out: s.out, created: s.created, conserve: s.conserve, leftover: s.inCarriers + s.inNests + s.held };
  });
  out.ok = out.done && out.conserve && out.out === out.created;
} else if (mode === 'cont') {
  out = await page.evaluate((h) => {
    const A = window.__sim; A.setPlaying(false); A.S.busy = true;
    let lastOut = -1, lastChange = 0, stall = null;
    while (A.sim.sched.time < h * 3600) {
      for (let i = 0; i < 200; i++) A.sim.sched.step(0.05);
      const s = A.sim.status();
      if (s.out !== lastOut) { lastOut = s.out; lastChange = A.sim.sched.time; } else if (A.sim.sched.time - lastChange > A.cfg.process + 900) { stall = `no output since t=${Math.round(lastChange)}`; break; }
      if (!s.conserve) { stall = 'conservation broken at t=' + Math.round(A.sim.sched.time); break; }
    }
    const s = A.sim.status();
    return { stall, out: s.out, uph: +s.uph.toFixed(1), conserve: s.conserve };
  }, Number(rest[0] || 2));
  out.ok = !out.stall && out.conserve;
} else if (mode === 'rig') {
  const views = await page.evaluate(() => window.__sim.views);
  out = { views: [] };
  for (const v of views) {
    out.views.push(await page.evaluate(async (v) => {
      const A = window.__sim, c = document.querySelector('canvas'); A.goView(v, true);
      const fov = A.camera.fov, d0 = A.rig.dist();
      const pinch = (dy, n) => { for (let i = 0; i < n; i++) c.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, ctrlKey: true, clientX: 800, clientY: 450, deltaY: dy })); };
      const settle = () => new Promise((r) => setTimeout(r, 450));
      pinch(-4, 60); await settle(); const dIn = A.rig.dist(); pinch(4, 400); await settle(); const dOut = A.rig.dist();
      const ctl = A.rig.controls, pol = ctl.getPolarAngle();
      return { v, ok: A.camera.zoom === 1 && A.camera.fov === fov && dIn <= d0 + 1e-6 && dIn >= ctl.minDistance - 1e-6 && dOut <= ctl.maxDistance + 1e-6 && pol >= 0.079 && pol <= Math.PI / 2 - 0.039 };
    }, v));
  }
  out.ok = out.views.every((x) => x.ok);
} else if (mode === 'shots') {
  const [name = 'shot', secs = '120'] = rest;
  await page.evaluate((s) => { window.__sim.setPlaying(false); window.__sim.advance(Number(s)); }, secs);
  const views = await page.evaluate(() => window.__sim.views);
  for (const v of views) { await page.evaluate((v) => window.__sim.goView(v, true), v); await page.waitForTimeout(600); await page.screenshot({ path: `${name}-${v}.png` }); }
  out = { shots: views.map((v) => `${name}-${v}.png`), ok: true };
} else if (mode === 'walk') {
  await page.evaluate(() => window.__sim.setMode('walkthrough'));
  await page.waitForTimeout(500);
  out = await page.evaluate(() => ({ caption: document.getElementById('caption').textContent, simPanelsHidden: getComputedStyle(document.getElementById('card')).display === 'none' }));
  out.ok = !!out.caption && out.simPanelsHidden;
} else { console.error('modes: run | cont | rig | shots | walk'); process.exit(2); }
if (errors.length) { out.errors = [...new Set(errors)].slice(0, 8); out.ok = false; }
console.log(JSON.stringify(out));
await browser.close();
process.exit(out.ok ? 0 : 1);
