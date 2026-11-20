// Headless experiments: build worlds without drawing, run the same sim logic fast, measure steady state.
// Rules that make the numbers trustworthy (see references/analysis.md):
//  - measure between two marks a whole number of output events apart, after a warm-up - never from a cold start
//  - fast-forward only through quietFor() (event-driven waits); everything else steps at DT
//  - work in ~30 ms slices and yield, and have the page stop rendering meanwhile (S.busy), or each yield
//    pays for a full frame and a 1 s run takes a minute
import * as THREE from 'three';
import { buildWorld } from './world.js';
import { createSim } from './sim.js';

const pct = (a) => { const s = a.reduce((x, y) => x + y, 0) || 1; return a.map((v) => (100 * v) / s); };
const diff = (a, b) => a.map((v, i) => b[i] - v);
const DT = 0.25;

export async function runSteady(spec, base, over = {}, { warm = 3, measure = 10, limitH = 48 } = {}) {
  const cfg = { ...base, ...over, continuous: true };
  const world = buildWorld(new THREE.Scene(), cfg, spec, { headless: true });
  const sim = createSim(world, cfg, spec), marks = sim.st.marks;
  try {
    while (marks.length < warm + measure + 1 && sim.sched.time < limitH * 3600) {
      const stop = performance.now() + 30;
      while (performance.now() < stop && marks.length < warm + measure + 1) { const q = sim.quietFor(); sim.sched.step(q > 2 ? q - 1 : DT); }
      await new Promise((r) => setTimeout(r, 0));
    }
    if (marks.length < warm + measure + 1) return null; // never reached steady state: report it, don't guess
    const a = marks[warm], b = marks[warm + measure], dt = b.clock - a.clock;
    return { uph: ((b.out - a.out) / dt) * 3600, robot: pct(diff(a.robot, b.robot)), nests: pct(diff(a.nests, b.nests)), window: dt };
  } finally { world.dispose(); }
}

// Every value of `option` x every value of the sweep param -> rows[{ x, [optionValue]: result }]
export async function runCompare(spec, base, { option, values, sweep }, onProgress) {
  const rows = [], total = sweep.values.length * values.length;
  let n = 0;
  for (const x of sweep.values) {
    const row = { x };
    for (const v of values) { row[v] = await runSteady(spec, base, { [option]: v, [sweep.key]: x }); onProgress && onProgress(++n / total); }
    rows.push(row);
  }
  return rows;
}
