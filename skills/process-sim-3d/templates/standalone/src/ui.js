// Panels generated from the spec: flow steps, status card, utilisation, Timing & configuration, bottom bar.
// Nothing here knows the machine - it reads spec.steps / spec.params / spec.views and sim.status().
const $ = (s) => document.querySelector(s);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
export const fmtTime = (s) => { s = Math.max(0, Math.floor(s)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60; return (h ? h + ':' : '') + String(m).padStart(2, '0') + ':' + String(x).padStart(2, '0'); };
const pct = (a) => { const s = a.reduce((x, y) => x + y, 0) || 1; return a.map((v) => Math.round((100 * v) / s)); };

export function buildUI(spec, cfg, on) {
  $('#h1').textContent = spec.title; $('#subtitle').textContent = spec.subtitle || ''; document.title = spec.title;
  const stepEls = {};
  spec.steps.forEach((s, i) => { const li = el('li', s.cls || '', `<span class="n">${i + 1}</span><div><b>${s.title}</b><small>${s.sub || ''}</small></div><span class="pill"></span>`); $('#steps').appendChild(li); stepEls[s.id] = li; });

  const card = $('#card');
  card.innerHTML = `<h3><span>Machine</span><span class="phase"></span></h3>
    <div class="counts"><div><b>0</b><small>waiting</small></div><div><b>0</b><small>in process</small></div><div><b>0</b><small>finished</small></div><div><b>0</b><small>UPH</small></div></div>
    <div class="eyebrow">Process cells</div><div class="cells"></div>
    <div class="eyebrow">Utilisation</div><div class="ut"><span>Robot</span><span class="ub"><i></i><i></i><i></i></span></div><div class="ut"><span>Cells</span><span class="ub"><i></i><i></i><i></i><i></i></span></div>
    <div class="kpi"></div>`;
  const cnt = card.querySelectorAll('.counts b'), cells = card.querySelector('.cells'), bars = card.querySelectorAll('.ub');

  // Timing & configuration from spec.params (grouped). restart:true params rebuild the world.
  const body = $('#cfgBody'), inputs = {};
  if (spec.presets) {
    const pre = el('div', 'seg');
    for (const p of Object.values(spec.presets)) { const b = el('button', 'btn', p.label); b.onclick = () => { Object.assign(cfg, p.v); sync(); on.restart(); }; pre.appendChild(b); }
    body.appendChild(pre);
  }
  let grp = null;
  for (const p of spec.params) {
    if (p.group !== grp) { grp = p.group; body.appendChild(el('div', 'eyebrow grp', grp)); }
    const row = el('div', 'row', `<label>${p.label} <span style="color:var(--dim)">${p.unit}</span>${p.hint ? `<small>${p.hint}</small>` : ''}</label><input type="number" min="${p.min}" max="${p.max}" step="${p.step}"><input type="range" min="${p.min}" max="${p.max}" step="${p.step}">`);
    const [num, rng] = row.querySelectorAll('input');
    const set = (v, commit) => { v = Math.min(p.max, Math.max(p.min, Number(v))); if (!isFinite(v)) return; cfg[p.key] = v; num.value = v; rng.value = v; if (commit && p.restart) on.restart(); };
    num.onchange = () => set(num.value, true); rng.oninput = () => set(rng.value, false); rng.onchange = () => set(rng.value, true);
    inputs[p.key] = { num, rng }; body.appendChild(row);
  }
  const sync = () => { for (const p of spec.params) { inputs[p.key].num.value = cfg[p.key]; inputs[p.key].rng.value = cfg[p.key]; } };
  sync();

  const seg = (host, items, cur, cb) => {
    const btns = items.map(([v, label]) => { const b = el('button', 'btn', label); b.onclick = () => { api(v); cb(v); }; $(host).appendChild(b); return [v, b]; });
    const api = (v) => btns.forEach(([x, b]) => b.classList.toggle('on', x === v)); api(cur); return api;
  };
  const setSpeed = seg('#speeds', [[1, '1×'], [5, '5×'], [20, '20×'], [100, '100×']], 1, on.speed);
  const setView = seg('#views', Object.keys(spec.views).map((k) => [k, k[0].toUpperCase() + k.slice(1)]), 'overview', on.view);
  const setMode = seg('#mode', [['walkthrough', 'Walkthrough'], ['simulation', 'Simulation']], spec.mode, on.mode);
  seg('#encl', [['solid', 'Solid'], ['glass', 'Glass'], ['hidden', 'Off']], 'glass', on.encl);
  const toggle = (id, cb) => { const b = $(id); b.onclick = () => { const v = !b.classList.contains('on'); b.classList.toggle('on', v); cb(v); }; return (v) => b.classList.toggle('on', v); };
  toggle('#tLabels', on.labels); const setAuto = toggle('#tAuto', on.auto);
  $('#play').onclick = on.play; $('#restart').onclick = on.restart; $('#compareBtn').onclick = on.compare;

  let lastLog = -1;
  return {
    setSpeed, setView, setMode, setAuto, sync,
    setPlaying(p) { $('#play').textContent = p ? 'Pause' : 'Play'; },
    caption(text) { $('#caption').textContent = text || ''; $('#caption').classList.toggle('show', !!text); },
    update(sim) {
      $('#clock').textContent = fmtTime(sim.sched.time);
      const s = sim.status();
      for (const sp of spec.steps) stepEls[sp.id].classList.toggle('on', !!s.flags[sp.id]);
      card.querySelector('.phase').textContent = s.phase;
      cnt[0].textContent = s.inCarriers; cnt[1].textContent = s.inNests + s.held; cnt[2].textContent = s.out; cnt[3].textContent = s.uph.toFixed(0);
      if (cells.children.length !== s.nests.length) { cells.innerHTML = ''; s.nests.forEach(() => cells.appendChild(el('i'))); }
      s.nests.forEach((n, i) => (cells.children[i].className = n.state));
      [s.m.robot, s.m.nests].forEach((arr, k) => pct(arr).forEach((v, i) => (bars[k].children[i].style.width = v + '%')));
      card.querySelector('.kpi').innerHTML = `robot busy <b>${pct(s.m.robot)[0]}%</b> · cells processing <b>${pct(s.m.nests)[0]}%</b> · parts conserved <b>${s.conserve ? 'yes' : 'NO'}</b>`;
      if (sim.log.length !== lastLog) { lastLog = sim.log.length; $('#log').innerHTML = sim.log.slice(-5).reverse().map((e) => `<div><span class="t">${fmtTime(e.t)}</span>${e.msg}</div>`).join(''); }
      return s;
    },
  };
}
