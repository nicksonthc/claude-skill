// Tiny cooperative scheduler: each process is a generator that yields waits.
//   yield wait(sec, fn?, ease?)  -> timed tween, fn(k) with k in 0..1
//   yield until(() => bool)      -> block until predicate holds
//   yield null                   -> resume on the next step
// Left-over time from a finished wait carries into the next one, so configured
// durations add up exactly regardless of frame rate or time scale.

export const ease = {
  lin: (k) => k,
  io: (k) => (k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2),
  // trapezoid velocity profile (servo axis): 22% accel, cruise, 22% decel
  trap: (k) => {
    const a = 0.22, v = 1 / (1 - a);
    if (k < a) return (0.5 * v * k * k) / a;
    if (k < 1 - a) return v * (k - a / 2);
    const r = 1 - k;
    return 1 - (0.5 * v * r * r) / a;
  },
};

export const wait = (dur, fn, e) => ({ kind: 'time', dur: Math.max(0, dur), t: 0, fn, ease: e });
export const until = (fn) => ({ kind: 'cond', fn });

export class Sched {
  constructor() {
    this.time = 0;
    this.dt = 0;
    this.tasks = [];
  }
  spawn(gen) {
    const t = { gen, w: null, done: false };
    this.tasks.push(t);
    this._run(t, 0);
    return t;
  }
  step(dt) {
    this.dt = dt;
    this.time += dt;
    const list = this.tasks.slice();
    for (const t of list) if (!t.done) this._run(t, dt);
    if (this.tasks.some((t) => t.done)) this.tasks = this.tasks.filter((t) => !t.done);
  }
  _run(t, rem) {
    for (let guard = 0; guard < 500; guard++) {
      const w = t.w;
      if (w) {
        if (w.kind === 'time') {
          w.t += rem;
          if (w.t < w.dur) {
            if (w.fn) { const k = w.t / w.dur; w.fn(w.ease ? w.ease(k) : k); }
            return;
          }
          if (w.fn) w.fn(1);
          rem = w.t - w.dur;
        } else if (w.kind === 'cond') {
          if (!w.fn()) return;
        } else if (w.kind === 'tick') {
          if (!w.seen) { w.seen = true; return; }
          rem = 0;
        }
      }
      const r = t.gen.next();
      if (r.done) { t.done = true; t.w = null; return; }
      const v = r.value;
      t.w = v == null ? { kind: 'tick', seen: false } : typeof v === 'number' ? wait(v) : v;
    }
  }
}
