// Demo process logic: every machine behaviour is a generator process on the shared scheduler.
// The PATTERNS are the reusable part (arrivals, conveyor move, robot pick/place, timed process with a
// fast-forwardable dwell, outbound, metrics buckets, status flags, snapshot, quietFor). The concrete
// rules (who goes first, what blocks what) are this project's control logic - rewrite them per machine.
import { Sched, wait, until, ease } from '../core/sched.js';

const lerp = (a, b, k) => a + (b - a) * k;
const TAU = Math.PI * 2;
const norm = (a, lo) => a - Math.floor((a - lo) / TAU) * TAU;

export function createSim(world, cfg, spec) {
  const sched = new Sched(), log = [];
  const st = { phase: 'idle', pick: null, place: null, inMoving: null, outMoving: 0, created: 0, carriersIn: 0,
    stats: { loaded: 0, out: 0, carriersOut: 0 }, marks: [] };
  const sim = { sched, cfg, world, log, st, done: false, endTime: 0 };
  const say = (msg) => { log.push({ t: sched.time, msg }); if (log.length > 300) log.shift(); };
  const L = spec.layout, R = world.robot, nests = world.nests, P = world.P;
  const per = spec.units.perCarrier, lot = cfg.lot || 6; // lot = carriers in a single-lot run

  // ---------------------------------------------------------------- arrivals + inbound conveyor
  function* arrivals() {
    for (;;) {
      if (!cfg.continuous && st.carriersIn >= lot) return;
      yield until(() => !st.pick && !st.inMoving); // one carrier at the pick position, one on the belt
      const c = world.spawnCarrier(true);
      st.created += per; st.carriersIn++;
      st.inMoving = c;
      const { x0, x1, z, h } = L.inbound, T = Math.abs(x1 - x0) / cfg.beltSpeed;
      say(`Carrier ${st.carriersIn} on the inbound conveyor`);
      yield wait(T, (k) => c.group.position.set(lerp(x0, x1, k), h, z), ease.lin);
      st.inMoving = null; st.pick = c;
      if (cfg.arrivalGap > 0) yield wait(cfg.arrivalGap);
    }
  }

  // ---------------------------------------------------------------- robot (pick & place)
  const S = { t1: 0, t2: 0, y: 1.0, holding: null };
  const apply = () => { R.set(S.t1, S.t2, S.y); };
  function* goto(x, z, dur) {
    const dx = x - R.base.position.x, dz = z - R.base.position.z, sgn = dz >= 0 ? 1 : -1;
    const s = R.ik(dx, dz, sgn), lo = -Math.PI, a0 = norm(S.t1, lo), a1 = norm(s.t1, lo), q0 = S.t2;
    yield wait(dur, (k) => { S.t1 = lerp(a0, a1, k); S.t2 = lerp(q0, s.t2, k); apply(); }, ease.io);
  }
  function* quill(y, dur) { const y0 = S.y; yield wait(dur, (k) => { S.y = lerp(y0, y, k); apply(); }, ease.io); }
  const TRAVEL = 1.0, PART_H = 0.012;
  function* move(from, to) { // from/to: { pos: Vector3 (surface), take(), put(part) }
    const T = cfg.pickPlace;
    yield* goto(from.pos.x, from.pos.z, T * 0.25);
    yield* quill(from.pos.y + PART_H, T * 0.1);
    const d = from.take();
    R.quill.add(d.group); d.group.position.set(0, -R.TIP - PART_H, 0); d.group.rotation.set(0, 0, 0);
    S.holding = d;
    yield wait(T * 0.05);
    yield* quill(TRAVEL, T * 0.1);
    yield* goto(to.pos.x, to.pos.z, T * 0.25);
    yield* quill(to.pos.y + PART_H, T * 0.1);
    S.holding = null; to.put(d);
    yield wait(T * 0.05);
    yield* quill(TRAVEL, T * 0.1);
  }
  const carrierLoc = (c, i) => ({
    pos: c.group.position.clone().add({ x: c.pockets[i][0], y: c.pockets[i][1], z: c.pockets[i][2] }),
    take: () => { const d = c.slots[i]; c.slots[i] = null; return d; },
    put: (d) => { c.slots[i] = d; c.group.add(d.group); d.group.position.set(...c.pockets[i]); },
  });
  const nestLoc = (n) => ({
    pos: n.pos,
    take: () => { const d = n.item; n.item = null; n.set('idle'); n.state = 'idle'; return d; },
    put: (d) => { n.item = d; world.root.add(d.group); d.group.position.copy(n.pos); },
  });
  const R0 = { mode: null };
  function* robot() {
    for (;;) {
      const done = nests.find((n) => n.state === 'done');
      const pi = st.place ? st.place.slots.findIndex((s) => !s) : -1;
      if (done && pi >= 0) { // unloading first keeps nests turning over
        R0.mode = 'unload'; st.phase = 'unload';
        yield* move(nestLoc(done), carrierLoc(st.place, pi));
        st.stats.unloaded = (st.stats.unloaded || 0) + 1;
        continue;
      }
      const free = nests.find((n) => n.state === 'idle' && !n.item);
      const ui = st.pick ? st.pick.slots.findIndex((d) => d && d.state === 'new') : -1;
      if (free && ui >= 0) {
        R0.mode = 'load'; st.phase = 'load'; free.state = 'loading'; free.set('loading');
        yield* move(carrierLoc(st.pick, ui), nestLoc(free));
        st.stats.loaded++;
        sched.spawn(processNest(free));
        continue;
      }
      R0.mode = null; st.phase = 'idle';
      yield null;
    }
  }

  // ---------------------------------------------------------------- timed process (fast-forwardable)
  function* processNest(n) {
    yield wait(cfg.press, (k) => { n.lid.position.y = lerp(n.up, n.down, k); }, ease.io);
    n.state = 'busy'; n.remain = cfg.process; n.item.state = 'processing';
    // dwell as a yield-null loop with `remain`, so quietFor() can skip straight to the next finish
    while (n.remain > 0) { yield null; n.remain = Math.max(0, n.remain - sched.dt); n.set('busy', 0.85 + 0.15 * Math.sin(sched.time * 6 + n.i)); }
    n.set('cool');
    yield wait(cfg.press, (k) => { n.lid.position.y = lerp(n.down, n.up, k); }, ease.io);
    n.item.state = 'done'; n.item.mark.visible = true;
    n.state = 'done'; n.set('done');
  }

  // ---------------------------------------------------------------- carrier logistics
  const inPos = () => ({ x: L.inbound.x1, z: L.inbound.z }), outPos = () => ({ x: L.outbound.x0, z: L.outbound.z });
  function* logistics() {
    for (;;) {
      // emptied inbound carrier crosses over to become the outbound carrier, else it is removed
      if (st.pick && st.pick.slots.every((d) => !d) && !st.transferring) {
        const c = st.pick; st.pick = null; st.transferring = true;
        if (!st.place) {
          st.phase = 'transfer';
          const a = inPos(), b = outPos();
          yield wait(cfg.transfer, (k) => c.group.position.set(lerp(a.x, b.x, k), L.inbound.h, lerp(a.z, b.z, k)), ease.io);
          st.place = c;
        } else c.dispose();
        st.transferring = false;
        continue;
      }
      // finished parts waiting and no outbound carrier (the inbound one is still being emptied, or the lot
      // has ended): take an empty from the stack. Without this the last parts of a lot wait forever.
      if (!st.place && nests.some((n) => n.state === 'done') && !st.transferring) {
        st.transferring = true;
        const c = world.spawnCarrier(false), b = outPos();
        yield wait(cfg.transfer, (k) => c.group.position.set(b.x + 0.6 * (1 - k), L.outbound.h, b.z), ease.io);
        st.place = c; st.transferring = false;
        continue;
      }
      // full of finished parts: send out
      if (st.place && st.place.slots.every((d) => d && d.state === 'done')) {
        const c = st.place; st.place = null; st.outMoving++;
        sched.spawn(leave(c));
        continue;
      }
      yield null;
    }
  }
  function* leave(c) {
    const { x0, x1, z, h } = L.outbound, T = Math.abs(x1 - x0) / cfg.beltSpeed;
    yield wait(T, (k) => c.group.position.set(lerp(x0, x1, k), h, z), ease.lin);
    st.stats.out += per; st.stats.carriersOut++; st.outMoving--;
    st.marks.push(sim.snapshot());
    say(`Carrier out — ${st.stats.out} parts finished`);
    c.dispose();
    if (!cfg.continuous && st.stats.carriersOut >= lot) { sim.done = true; sim.endTime = sched.time; say('Lot complete'); }
  }

  // ---------------------------------------------------------------- metrics + status
  st.m = { t: 0, robot: [0, 0, 0], nests: [0, 0, 0, 0] }; // robot: work / wait (parts processing) / idle; nests: process / done waiting / empty / loading
  function* metrics() {
    for (;;) {
      yield null;
      const dt = sched.dt, m = st.m;
      if (sim.done) continue;
      m.t += dt;
      m.robot[R0.mode ? 0 : nests.some((n) => n.state === 'busy') ? 1 : 2] += dt;
      for (const n of nests) m.nests[n.state === 'busy' ? 0 : n.state === 'done' ? 1 : n.state === 'idle' ? 2 : 3] += dt;
    }
  }
  sim.status = () => {
    let inCarriers = 0;
    for (const c of world.carriers) for (const d of c.slots) if (d) inCarriers++;
    const inNests = nests.filter((n) => n.item).length, held = S.holding ? 1 : 0;
    const flags = {
      arrive: !!st.inMoving, load: R0.mode === 'load', process: nests.some((n) => n.state === 'busy' || (n.state === 'loading' && n.item)),
      unload: R0.mode === 'unload', transfer: !!st.transferring, leave: st.outMoving > 0,
    };
    return { flags, phase: st.phase, m: st.m, out: st.stats.out, created: st.created, inCarriers, inNests, held,
      // conservation: every part created is in a carrier, a nest, the gripper, or out (carriers still count their finished parts)
      conserve: inCarriers + inNests + held + st.stats.out === st.created,
      uph: st.m.t > 30 ? (st.stats.out / st.m.t) * 3600 : 0,
      nests: nests.map((n) => ({ state: n.state, remain: n.remain })) };
  };
  sim.snapshot = () => ({ clock: sched.time, out: st.stats.out, loaded: st.stats.loaded, robot: st.m.robot.slice(), nests: st.m.nests.slice(), t: st.m.t });
  // Seconds of pure waiting ahead (0 if anything timed is running): lets experiments jump to the next finish.
  // Only skip when every waiting task is event-driven - a hold that checks the CLOCK must return 0 here.
  sim.quietFor = () => {
    if (sched.tasks.some((t) => t.w && t.w.kind === 'time')) return 0;
    let r = Infinity;
    for (const n of nests) if (n.state === 'busy') r = Math.min(r, n.remain);
    return isFinite(r) ? r : 0;
  };

  // ---------------------------------------------------------------- init
  S.t1 = Math.PI; S.t2 = 0.4; apply();
  sched.spawn(arrivals()); sched.spawn(robot()); sched.spawn(logistics()); sched.spawn(metrics());
  return sim;
}
