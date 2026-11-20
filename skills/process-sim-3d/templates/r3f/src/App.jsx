// React shell: Canvas + panels. Panels come from the spec (steps, params, views) and a status snapshot
// polled ~9x a second - the same panels as the standalone template, as React components.
import { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import * as THREE from 'three';
import Scene from './Scene.jsx';
import { spec, makeConfig } from './sim/spec.js';
import { runCompare } from './sim/experiment.js';

const fmtTime = (s) => { s = Math.max(0, Math.floor(s)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60; return (h ? h + ':' : '') + String(m).padStart(2, '0') + ':' + String(x).padStart(2, '0'); };
const pct = (a) => { const s = a.reduce((x, y) => x + y, 0) || 1; return a.map((v) => Math.round((100 * v) / s)); };

export default function App() {
  const qs = new URLSearchParams(location.search);
  const cfg = useMemo(() => { const c = makeConfig(); for (const [k, v] of qs) if (k in c && isFinite(Number(v))) c[k] = Number(v); if (qs.get('continuous') === '0') c.continuous = false; return c; }, []);
  const S = useMemo(() => ({ playing: true, speed: 1, mode: qs.get('mode') || spec.mode, tour: 0, tourT: 0, auto: false, labels: true, encl: 'glass', busy: false }), []);
  const simRef = useRef(null), rigRef = useRef(null);
  const [version, setVersion] = useState(0), [status, setStatus] = useState(null), [caption, setCaption] = useState(''), [, force] = useState(0), [cmp, setCmp] = useState(null);
  const restart = () => setVersion((v) => v + 1);
  const setMode = (m) => { S.mode = m; S.tour = 0; S.tourT = 0; setCaption(m === 'walkthrough' ? spec.tour[0].caption : ''); if (m === 'walkthrough' && rigRef.current) rigRef.current.go(spec.views[spec.tour[0].view]); force((x) => x + 1); };
  useEffect(() => { const id = setInterval(() => simRef.current && setStatus({ ...simRef.current.status(), time: simRef.current.sched.time, log: simRef.current.log.slice(-5).reverse() }), 110); return () => clearInterval(id); }, []);
  useEffect(() => { setMode(S.mode); }, []);
  useEffect(() => { // same hooks as the standalone template, so tools/check.mjs runs unchanged against `vite preview`
    window.__sim = { get sim() { return simRef.current; }, get world() { return simRef.current && simRef.current.world; }, cfg, S, get rig() { return rigRef.current; },
      get camera() { return rigRef.current && rigRef.current.controls.object; }, restart, setMode, views: Object.keys(spec.views),
      advance: (dt) => { const n = Math.max(1, Math.ceil(dt / 0.05)); for (let i = 0; i < n; i++) simRef.current.sched.step(dt / n); },
      setPlaying: (p) => { S.playing = p; force((x) => x + 1); }, goView: (v, i) => rigRef.current.go(spec.views[v], i) };
  }, []);
  async function compare() {
    S.busy = true; const was = S.playing; S.playing = false; setCmp({ note: 'Simulating…', rows: null });
    const rows = await runCompare(spec, { ...cfg }, spec.compare, (f) => setCmp({ note: `Simulating… ${Math.round(f * 100)}%`, rows: null }));
    setCmp({ note: 'Steady state, continuous feed, same timings as the live run.', rows }); S.playing = was; S.busy = false;
  }
  const c = spec.compare, walk = S.mode === 'walkthrough';
  return (
    <div className={walk ? 'walk' : ''}>
      <Canvas style={{ position: 'fixed', inset: 0 }} shadows camera={{ fov: 38, near: 0.05, far: 120 }} gl={{ antialias: true, toneMapping: THREE.NeutralToneMapping }} frameloop="always">
        <Scene cfg={cfg} S={S} simRef={simRef} rigRef={rigRef} version={version} onCaption={setCaption} />
      </Canvas>
      <div id="left">
        <div id="title" className="panel"><div className="eyebrow">Process simulation</div><h1>{spec.title}</h1><p>{spec.subtitle}</p></div>
        <div id="flow" className="panel"><div className="eyebrow">End-to-end flow</div><ol id="steps">
          {spec.steps.map((s, i) => <li key={s.id} className={(s.cls || '') + (status && status.flags[s.id] ? ' on' : '')}><span className="n">{i + 1}</span><div><b>{s.title}</b><small>{s.sub}</small></div><span className="pill" /></li>)}
        </ol></div>
        {status && <div id="log" className="panel simOnly">{status.log.map((e, i) => <div key={i}><span className="t">{fmtTime(e.t)}</span>{e.msg}</div>)}</div>}
      </div>
      {status && <div id="right"><section className="st panel simOnly" id="card">
        <h3><span>Machine</span><span className="phase">{status.phase}</span></h3>
        <div className="counts"><div><b>{status.inCarriers}</b><small>waiting</small></div><div><b>{status.inNests + status.held}</b><small>in process</small></div><div><b>{status.out}</b><small>finished</small></div><div><b>{status.uph.toFixed(0)}</b><small>UPH</small></div></div>
        <div className="cells">{status.nests.map((n, i) => <i key={i} className={n.state} />)}</div>
        <div className="kpi">robot busy <b>{pct(status.m.robot)[0]}%</b> · cells processing <b>{pct(status.m.nests)[0]}%</b> · parts conserved <b>{status.conserve ? 'yes' : 'NO'}</b></div>
      </section></div>}
      {caption && <div id="caption" className="panel show">{caption}</div>}
      <div id="bar" className="panel">
        <button className="btn pri" onClick={() => { S.playing = !S.playing; force((x) => x + 1); }}>{S.playing ? 'Pause' : 'Play'}</button>
        <button className="btn" onClick={restart}>Restart</button><span id="clock">{status ? fmtTime(status.time) : '00:00'}</span>
        <div className="seg">{Object.keys(spec.views).map((v) => <button key={v} className="btn" onClick={() => rigRef.current.go(spec.views[v])}>{v}</button>)}</div>
        <span className="bgrp"><span className="lbl">Mode</span><div className="seg">{['walkthrough', 'simulation'].map((m) => <button key={m} className={'btn' + (S.mode === m ? ' on' : '')} onClick={() => setMode(m)}>{m}</button>)}</div></span>
        <button className="btn pri simOnly" onClick={compare}>Compare</button>
      </div>
      {cmp && <div id="cmp" className="show"><div id="cmpBox" className="panel"><div id="cmpHead"><div><div className="eyebrow">Setup comparison</div><p id="cmpNote">{cmp.note}</p></div><button className="btn pri" onClick={() => setCmp(null)}>Close</button></div>
        <div id="cmpBody">{cmp.rows && <table className="ct"><thead><tr><th>{c.sweep.key}</th>{c.values.map((v) => <th key={v}>{c.label(v)} UPH</th>)}</tr></thead><tbody>
          {cmp.rows.map((r) => <tr key={r.x}><th>{r.x}</th>{c.values.map((v) => <td key={v}>{r[v] ? r[v].uph.toFixed(1) : 'no steady state'}</td>)}</tr>)}</tbody></table>}</div></div></div>}
    </div>
  );
}
