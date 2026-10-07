# Smart Task Guide: building blocks

Copy, then adapt. The numbering matches `SKILL.md`. Domain nouns from the
source project (skycar, bin, job, ADG) appear only in the examples.

---

## §1 Task catalogue

```js
// guideTasks.js: the single source of truth for the search list and the runner.
import { findVisible, isEnabled } from "./guideEngine";

const g = (name) => `[data-guide="${name}"]`;

export const TASKS = [
  // Linear task: navigate → open → fill → final.
  {
    id: "cycle-stop",
    title: "Cycle stop the cube",
    description: "Let robots finish their current job, then stop",
    icon: "mdi-stop-circle-outline",
    page: "Operation",
    route: "/operation",
    keywords: ["cycle stop", "stop", "pause", "shutdown"],
    steps: [
      { target: g("operation-cube"), text: "Make sure the right cube is selected.", advance: { manual: true } },
      { target: g("cube-stop"), text: "Press Stop.", advance: { appear: g("stop-reason") } },
      { target: g("stop-reason"), text: "Pick the reason.", advance: { when: () => isEnabled(g("stop-confirm")) } },
      { target: g("stop-confirm"), text: "Press Confirm.", advance: { click: true }, final: true },
    ],
  },
  // Skip a step the page already satisfies; re-evaluated on every DOM change.
  // { target: g("view-2d"), text: "Switch to 2D.", advance: { click: true },
  //   skipIf: () => !!findVisible(`${g("view-2d")}[aria-pressed="true"]`) },
];
```

**Step fields:**

| field | meaning |
|---|---|
| `id` | needed for `goto`, `next` and `decide` targets |
| `target` | selector, a list (the first visible one wins: specific first, generic fallback), or `fn(ctx)` |
| `text` / `ask` | string or `fn(ctx, targetEl)`; `ask` turns the step into a question |
| `advance` | `{click:true}` · `{appear:sel}` · `{when:fn}` · `{manual:true}` · `{decide: fn → stepId|null}` |
| `choices` | for `ask`: `{label, goto?, end?: string|fn, set?: {ctx patch}}` |
| `facts` | `fn(ctx) → [[label, value, tone?]]`, where tone is `good`, `bad` or `warn`; null values are hidden |
| `suggest` | `fn(ctx) → choice label`, preselected and tagged "Matches data" |
| `load` | `async fn(ctx)`; runs before the step, and the card shows "Reading data…" |
| `skipIf` | `fn(ctx)`; re-checked continuously; skipped steps stay out of history |
| `route` | navigate to it when the step starts (multi-page tasks list them all in `task.routes`) |
| `dock` | park the card at the right edge (evidence steps, so tables stay readable) |
| `note` | warning line, re-evaluated on a pulse (e.g. a live "field says 88, expected 881") |
| `next` | the step id to continue to (default: the following step) |
| `final` | the last button: the card says the guide won't press it, and the user's click finishes the task |

**Task fields:** `param: "recordId"` lets the search pull a number from the query
into `ctx.recordId`. `needsParam: true` makes the search ask for that number before
starting. `summary: fn(ctx) → lines[]` keeps the done/ended card up with a copyable
summary.

---

## §2 Engine (framework-agnostic)

The state is a plain object. Pass your framework's reactive wrapper so
components re-render on mutation: `Vue.observable` (Vue 2), `reactive` (Vue 3).
For React, use the identity function plus `subscribe` and `useSyncExternalStore`.

```js
// guideEngine.js
const FIND_TIMEOUT_MS = 15000;
const DONE_BANNER_MS = 2500;

// UI adapter: the only library-specific knowledge. Vuetify 2 defaults shown.
export const ui = {
  menuOpen: ".menuable__content__active",           // MUI: ".MuiPopover-root", Radix: "[data-radix-popper-content-wrapper]"
  dialogOpen: ".v-dialog--active",                  // MUI: ".MuiDialog-root", Radix: "[role=dialog][data-state=open]"
  fieldWrapper: (el) => (el.tagName === "INPUT" ? el.closest(".v-input") : null),
  disabledClass: "v-btn--disabled",
  // Attributes whose changes should re-check the step. Add your data-* state flags.
  observedAttributes: ["class", "style", "disabled", "aria-pressed", "aria-expanded", "data-locked", "data-flow"],
};

let reactive = (o) => o;
const listeners = new Set();
export let state;

export function initGuide({ makeReactive, navigate, currentPath }) {
  if (makeReactive) reactive = makeReactive;
  nav = { navigate, currentPath };
  state = reactive({
    task: null, ctx: {}, stepIndex: 0,
    // loading | waiting | active | lost | done | ended
    status: "idle", targetEl: null, history: [], answers: [], endMessage: "",
  });
  return state;
}
let nav = { navigate: () => {}, currentPath: () => location.pathname };

export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
function set(patch) { Object.assign(state, patch); listeners.forEach((fn) => fn(state)); }

// ---- DOM queries --------------------------------------------------------
export function isVisible(el) {
  if (!el || !el.isConnected) return false;
  const r = el.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return false;           // closed dialogs, v-show
  const s = getComputedStyle(el);
  return s.visibility !== "hidden" && s.display !== "none";
}
export function findVisible(selector) {
  for (const el of document.querySelectorAll(selector)) if (isVisible(el)) return el;
  return null;
}
export function isEnabled(selector) {
  const el = findVisible(selector);
  return !!el && !el.disabled && !el.classList.contains(ui.disabledClass);
}
const spotlightTarget = (el) => ui.fieldWrapper(el) || el;

// ---- runner -------------------------------------------------------------
let observer = null, onCheck = null, lostTimer = null, doneTimer = null;
let pollTimer = null, clickCleanup = null, checkQueued = false;
let runToken = 0;
let skippedIndex = -1;   // a step skipped as already done isn't one the user saw

const step = () => (state.task ? state.task.steps[state.stepIndex] : null);
export const currentStep = step;
const resolve = (v) => (typeof v === "function" ? v(state.ctx, state.targetEl) : v);
const indexOf = (id) => {
  const i = state.task.steps.findIndex((s) => s.id === id);
  if (i < 0) throw new Error(`guide: no step "${id}" in ${state.task.id}`);
  return i;
};
const selectors = (s) => {
  const t = typeof s.target === "function" ? s.target(state.ctx) : s.target;
  return (Array.isArray(t) ? t : [t]).filter(Boolean);
};
const findTarget = (s) => { for (const sel of selectors(s)) { const el = findVisible(sel); if (el) return el; } return null; };
const isSkipped = (s) => !!s.skipIf && s.skipIf(state.ctx);
function advanceReady(s) {
  const a = s.advance || {};
  if (a.appear) return !!findVisible(a.appear);
  if (a.when) return a.when(state.ctx);
  return false;
}

function clearWatchers() {
  clearInterval(pollTimer); pollTimer = null;
  clearTimeout(lostTimer); lostTimer = null;
  if (clickCleanup) clickCleanup(); clickCleanup = null;
  onCheck = null;
}
// One shared observer, batched to one check per frame so busy pages stay cheap.
function ensureObserver() {
  if (observer) return;
  observer = new MutationObserver(() => {
    if (checkQueued || !onCheck) return;
    checkQueued = true;
    requestAnimationFrame(() => { checkQueued = false; if (onCheck) onCheck(); });
  });
  observer.observe(document.body, {
    childList: true, subtree: true, attributes: true, attributeFilter: ui.observedAttributes,
  });
}
function dropObserver() { if (observer) observer.disconnect(); observer = null; }
const armLost = () => {
  clearTimeout(lostTimer);
  lostTimer = setTimeout(() => { if (state.status === "waiting") set({ status: "lost" }); }, FIND_TIMEOUT_MS);
};

async function runStep(index, { fromBack = false } = {}) {
  clearWatchers();
  if (!state.task) return;
  if (index >= state.task.steps.length) return finish();
  const s = state.task.steps[index];

  const prev = state.stepIndex;
  if (!fromBack && prev !== index && prev !== skippedIndex && state.status !== "idle"
      && state.history[state.history.length - 1] !== prev) {
    set({ history: [...state.history, prev] });
  }
  skippedIndex = -1;
  set({ stepIndex: index, targetEl: null });
  const token = ++runToken;

  if (s.route && nav.currentPath() !== s.route) nav.navigate(s.route);

  // Read-only facts. A failed load leaves facts empty; the question still works.
  if (s.load) {
    set({ status: "loading" });
    try { await s.load(state.ctx); } catch (e) { console.warn("[guide] facts failed", s.id, e); }
    if (token !== runToken || !state.task) return;   // user moved on while loading
  }

  set({ status: "waiting" });
  ensureObserver();
  if (isSkipped(s)) { skippedIndex = index; return goNext(s, index); }
  if (s.ask && !s.target) { set({ status: "active" }); return; }   // answered on the card
  armLost();

  onCheck = () => {
    // Re-checked on every change: the page may still be loading.
    if (isSkipped(s)) { skippedIndex = index; return goNext(s, index); }
    if (!s.ask && advanceReady(s)) {
      // Already satisfied before the user saw it (a default value): not a step they took.
      if (state.status !== "active") skippedIndex = index;
      return goNext(s, index);
    }
    const branch = s.advance && s.advance.decide && s.advance.decide(state.ctx);
    if (branch) return runStep(indexOf(branch));

    const el = findTarget(s);
    if (el) {
      if (state.targetEl === spotlightTarget(el) && state.status === "active") return;
      attachTarget(s, el);
    } else if (state.status === "active") {
      set({ targetEl: null, status: "waiting" });     // dialog closed, selection cleared
      armLost();
    }
  };
  onCheck();
  // Values set by code (socket replies) change no attribute: poll slowly too.
  pollTimer = setInterval(() => onCheck && onCheck(), 500);
}

function attachTarget(s, el) {
  clearTimeout(lostTimer);
  if (clickCleanup) clickCleanup(); clickCleanup = null;
  set({ targetEl: spotlightTarget(el), status: "active" });
  el.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  if ((s.advance || {}).click) {
    const index = state.stepIndex;
    // Capture phase: seen even if the control stops propagation. setTimeout lets
    // the app's own handler run first.
    const handler = () => setTimeout(() => { if (state.stepIndex === index) goNext(s, index); }, 0);
    el.addEventListener("click", handler, true);
    clickCleanup = () => el.removeEventListener("click", handler, true);
  }
}

function goNext(s, index) {
  if (s.final) return finish();
  if (s.next) return runStep(indexOf(s.next));
  return runStep(index + 1);
}

function finish() {
  clearWatchers(); dropObserver(); clearTimeout(doneTimer);
  set({ targetEl: null, status: "done" });
  if (state.task && state.task.summary) return;          // keep the summary up
  doneTimer = setTimeout(() => { if (state.status === "done") stop(); }, DONE_BANNER_MS);
}
function end(message) {
  clearWatchers(); dropObserver();
  set({ targetEl: null, endMessage: message, status: "ended" });
}

// ---- public API -----------------------------------------------------------
export function start(task, ctx = {}) {
  stop();
  set({ task, ctx: { ...ctx } });
  if (nav.currentPath() !== task.route) nav.navigate(task.route);
  runStep(0);
}
export function stop() {
  clearWatchers(); dropObserver(); clearTimeout(doneTimer); runToken++;
  set({ task: null, ctx: {}, stepIndex: 0, status: "idle", targetEl: null, history: [], answers: [], endMessage: "" });
}
export const next = () => { const s = step(); if (s) goNext(s, state.stepIndex); };
export const retry = () => runStep(state.stepIndex);

function previousAt() {
  const steps = state.task ? state.task.steps : [];
  for (let i = state.history.length - 1; i >= 0; i--) if (!isSkipped(steps[state.history[i]])) return i;
  return -1;
}
export const canGoBack = () => previousAt() >= 0;
export function back() {
  const at = previousAt();
  if (at < 0) return;
  const index = state.history[at];
  set({ history: state.history.slice(0, at) });
  runStep(index, { fromBack: true });
}

export function choose(choice) {
  const s = step();
  if (!s || !s.ask) return;
  const sug = suggestedChoice();
  set({ answers: state.answers.filter((a) => a.stepId !== s.id).concat({
    stepId: s.id, question: resolve(s.ask), answer: choice.label,
    suggested: !!sug && sug.label === choice.label,
  }) });
  if (choice.set) Object.assign(state.ctx, choice.set);
  if (choice.end) return end(resolve(choice.end));
  if (choice.goto) return runStep(indexOf(choice.goto));
  return goNext(s, state.stepIndex);
}

export const taskOwnsRoute = (path) => !!state.task && (state.task.routes || [state.task.route]).includes(path);
export const stepText = () => (step() ? resolve(step().ask || step().text) : "");
export const stepNote = () => (step() && step().note ? resolve(step().note) : "");
export const stepChoices = () => (step() && step().ask ? step().choices : []);
export const isManualStep = () => !!step() && !!(step().advance || {}).manual;
export const stepFacts = () =>
  (step() && step().facts ? step().facts(state.ctx) || [] : []).filter((r) => r && r[1] != null);
export function suggestedChoice() {
  const s = step();
  if (!s || !s.suggest) return null;
  const label = s.suggest(state.ctx);
  return (s.choices || []).find((c) => c.label === label) || null;
}

// Plain-text case record for the ticket.
export function caseSummary({ header = (task) => task.title, matchedTag = "matched data" } = {}) {
  const { task, ctx, answers } = state;
  if (!task) return "";
  const lines = [header(task, ctx)];
  if (task.summary) lines.push(...task.summary(ctx).filter(Boolean));
  for (const a of answers) lines.push(`${a.question} → ${a.answer}${a.suggested ? ` (${matchedTag})` : ""}`);
  if (state.status === "ended") lines.push(`Stopped: ${state.endMessage}`);
  return lines.join("\n");
}
```

**Wiring (Vue 2 + vue-router 3):**

```js
import Vue from "vue";
import { initGuide } from "./guide/guideEngine";
initGuide({
  makeReactive: Vue.observable,
  navigate: (path) => router.push(path).catch(() => {}),   // swallow NavigationDuplicated
  currentPath: () => router.currentRoute.path,
});
```

React: `initGuide({ navigate, currentPath })`, then
`const s = useSyncExternalStore(subscribe, () => ({ ...state }))`. Snapshot
identity must change on each update, so keep a version counter, or return a
fresh object only from `set`.

---

## §3 Search scoring and parameter extraction

```js
// Filler in questions like "how do I add an obstacle".
const STOP_WORDS = new Set(["an", "the", "to", "how", "do", "can", "my", "for", "please", "want", "where", "is"]);

function editDistance(a, b) {
  const row = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let prev = row[0]; row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const tmp = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = tmp;
    }
  }
  return row[b.length];
}
const isSubsequence = (n, h) => { let i = 0; for (const c of h) if (c === n[i]) i++; return i === n.length; };

function tokenScore(t, words) {
  let best = 0;
  for (const w of words) {
    if (w === t) best = Math.max(best, 3);
    else if (w.startsWith(t)) best = Math.max(best, 2.5);
    else if (w.includes(t)) best = Math.max(best, 1.5);
    else if (t.length >= 4 && editDistance(t, w) <= 1) best = Math.max(best, 1.2);           // "obstcle"
    else if (t.length >= 3 && t[0] === w[0] && isSubsequence(t, w)) best = Math.max(best, 1); // "chrg"
  }
  return best;
}

// "revive skycar 12" → { text: "revive skycar", number: 12 }
export function parseQuery(q) {
  const raw = (q || "").toLowerCase();
  const num = raw.match(/\d+/);
  return { text: raw.replace(/\d+/g, " ").replace(/[^a-z\s-]/g, " ").trim(), number: num ? Number(num[0]) : undefined };
}

// Every word typed must match something, so "add parking" doesn't also list
// "add obstacle" on the strength of "add".
export function searchTasks(tasks, query) {
  const parsed = parseQuery(query);
  const tokens = parsed.text.split(/\s+/).filter((t) => t.length > 1 && !STOP_WORDS.has(t));
  const ctxFor = (task) => (task.param && parsed.number !== undefined ? { [task.param]: parsed.number } : {});
  if (!tokens.length) return tasks.map((task) => ({ task, ctx: ctxFor(task) }));
  const out = [];
  for (const task of tasks) {
    const words = [task.title, ...task.keywords].join(" ").toLowerCase().split(/[^a-z-]+/).filter(Boolean);
    let score = 0, missed = false;
    for (const t of tokens) { const s = tokenScore(t, words); if (!s) missed = true; score += s; }
    if (missed) continue;
    if (task.keywords.some((k) => parsed.text.includes(k))) score += 2;   // a whole keyword phrase
    if (task.title.toLowerCase().startsWith(parsed.text)) score += 1;
    out.push({ task, ctx: ctxFor(task), score });
  }
  return out.sort((a, b) => b.score - a.score);
}
```

Write keywords in the user's vocabulary and synonyms ("emergency", "e-stop",
"freeze" for halt). Keep look-alike tasks apart with distinct words. In the source,
"charge out" (to a maintenance dock) and "charge" (to a charger) were different
operations, and mixing them up was a real bug.

---

## §4 Spotlight overlay

The geometry and tracking are framework-agnostic. The Vue 2 component below is the
proven shape; port its template to JSX for React.

**Rules:**
- **Layer:** a fixed full-screen layer at z-index above modals (≥1000) with
  `pointer-events: none`. Only the card takes pointer events.
- **Dim:** a hole around the target: `box-shadow: 0 0 0 200vmax rgba(...)` on a div sized to the
  target rect plus padding. One element, and no click blocking.
- **Ring:** a pulsing outline on a second div with the same rect.
- **Tracking:** `requestAnimationFrame` loop. Read `getBoundingClientRect()` on the
  target and write the rect only when it changed. Every frame also compute:
  - `menuOpen = !!querySelector(ui.menuOpen)`: hide the dim **and** the card.
  - `blocked = target && dialogOpen && !target.closest(ui.dialogOpen)`: render the
    compact corner card ("Close the open window first").
  - `pulse++` every ~15 frames: recompute `note` (live value checks).
- **Card placement:** below the target if it fits, else above, else pinned
  to the bottom of the viewport (for targets taller than the screen). Clamp horizontally to
  16 px. `step.dock` pins it to the right edge; with no target it docks at bottom centre.
- **Card content by status:**

  | status | card shows |
  |---|---|
  | `loading` | spinner + "Reading data…" |
  | `waiting` | spinner + step text |
  | `active` | text, facts `<dl>`, note, choices (suggested one tagged), "The guide won't press this for you" on `final` |
  | `lost` | "Can't find the next control…" + Try again |
  | `done` / `ended` | reason + `<pre>` case summary + Copy summary + Close |
- **Footer:** Back (when `canGoBack()`), Exit (Esc), Next (manual steps).
- **Esc:** a capture-phase keydown that ignores Esc while `ui.menuOpen` or `ui.dialogOpen` is open.
- **Route watcher:** `if (state.task && !taskOwnsRoute(to.path)) stop()`.
- **Step label:** "Step N of M" for linear tasks; "Step {history.length+1}" when any step `ask`s.
- **Type:** ≥14 px. A support audience rejected 11–13 px.

```vue
<template>
  <div v-if="s.task" class="guide-layer">
    <div v-if="rect && !menuOpen" class="guide-spotlight" :style="box" />
    <div v-if="rect" class="guide-ring" :style="box" />
    <div ref="card" class="guide-card" :style="side || compact ? {} : cardStyle"
         :class="{ 'is-docked': !rect && !side && !compact, 'is-side': side && !compact,
                   'is-compact': compact, 'is-hidden': menuOpen }" role="dialog" aria-live="polite">
      <header><span class="title">{{ s.task.title }}</span><span v-if="!finished" class="count">{{ count }}</span></header>
      <p v-if="compact" class="warn">Close the open window first: it's covering this.</p>
      <template v-else>
        <p>{{ bodyText }}</p>
        <dl v-if="!finished && facts.length" class="facts">
          <template v-for="r in facts"><dt :key="r[0]+'k'">{{ r[0] }}</dt><dd :key="r[0]+'v'" :class="r[2]">{{ r[1] }}</dd></template>
        </dl>
        <p v-if="!finished && note" class="warn">{{ note }}</p>
        <div v-if="s.status === 'active' && choices.length" class="choices">
          <button v-for="c in choices" :key="c.label" type="button" @click="choose(c)"
                  :class="{ suggested: suggested && suggested.label === c.label }">
            {{ c.label }}<span v-if="suggested && suggested.label === c.label" class="tag">Matches data</span>
          </button>
        </div>
        <p v-if="isFinal && s.status === 'active'" class="muted">The guide won't press this for you.</p>
        <pre v-if="finished && summary" class="summary">{{ summary }}</pre>
        <footer><!-- Back / Try again / Exit / Next, or Copy summary / Close when finished --></footer>
      </template>
    </div>
  </div>
</template>
```

```css
.guide-layer { position: fixed; inset: 0; z-index: 1000; pointer-events: none; }
.guide-spotlight { position: fixed; border-radius: 10px; box-shadow: 0 0 0 200vmax rgba(5,10,20,.55);
  transition: top .15s, left .15s, width .15s, height .15s; }
.guide-ring { position: fixed; border-radius: 10px; border: 2px solid #38bdf8; animation: pulse 1.6s ease-out infinite; }
@keyframes pulse { from { box-shadow: 0 0 0 0 rgba(56,189,248,.6) } to { box-shadow: 0 0 0 14px rgba(56,189,248,0) } }
.guide-card { position: fixed; z-index: 1001; pointer-events: auto; font-size: 15px; transition: opacity .12s; }
.guide-card.is-hidden { opacity: 0; pointer-events: none; }
.guide-card.is-side { right: 16px; top: 80px; width: min(400px, calc(100vw - 32px)); max-height: calc(100vh - 100px); overflow-y: auto; }
.guide-card.is-compact { right: 16px; bottom: 16px; width: min(320px, calc(100vw - 32px)); }
.guide-card.is-docked { left: 50%; bottom: 24px; transform: translateX(-50%); width: min(380px, calc(100vw - 32px)); }
@media (prefers-reduced-motion: reduce) { .guide-ring { animation: none; } }
```

Keep the compact warning **outside** the `v-else` / `!compact` block. In the
source it was first nested inside it and so never rendered.

---

## §5 Search box

**Vue 2 + Vuetify (`v-autocomplete`):**
- `:items` comes from `searchTasks(TASKS, query)`; set `no-filter`, `return-object`, and `:search-input.sync="query"`.
- Item slot: icon, title, a param chip ("skycar 12"), "+ id no." when `needsParam`
  is unmet, a description, and a page chip.
- Global `keydown`: Ctrl/Cmd+K → `preventDefault()`, then `this.$refs.search.$refs.input.focus()`.
  A focus-trapping modal blocks this; that is acceptable, so say so in the docs.
- `@change(item)` runs one of two paths:

```js
onPick(item) {
  if (!item) return;
  const task = TASKS.find((t) => t.id === item.key);
  if (task.needsParam && item.ctx[task.param] === undefined) {
    // Vuetify resets the search text after a selection: clear the model, then
    // prefill on a timer ($nextTick loses the race).
    this.selected = null;
    setTimeout(() => {
      this.query = `${task.title.toLowerCase()} `;
      this.$refs.search.$refs.input.focus();
      this.$refs.search.activateMenu();
    }, 100);
    return;
  }
  this.$nextTick(() => { this.selected = null; this.query = ""; this.$refs.search.blur(); });
  start(task, item.ctx);
}
```

Elsewhere, use any combobox (cmdk, Headless UI, Downshift) with the same scoring.
Mount the box in the app bar and hide it below phone width if the bar is crowded.

---

## §6 Troubleshooting tasks and the facts layer

**Facts layer:** the guide's only API access. Every call is a read. A query that the
backend exposes only as POST gets explicit permission in a code comment.

```js
// guideFacts.js
async function api(ctx, path, { params, body } = {}) {
  const url = new URL(baseUrl(ctx) + path);                 // extension point
  Object.entries(params || {}).forEach(([k, v]) => url.searchParams.set(k, v));
  const res = await fetch(url, { method: body ? "POST" : "GET", headers: authHeaders(), body: body && JSON.stringify(body) });
  const json = await res.json();
  if (!res.ok || json.status === false) throw new Error(json.message || `HTTP ${res.status}`);
  return json;
}
const quietly = async (fn) => { try { await fn(); } catch (e) { console.warn("[guide] lookup failed", e); } };

// One load per case, at the first step: each fact is independent, and one failure
// leaves only that fact empty.
export async function loadCase(ctx) {
  await quietly(async () => { ctx.record = (await api(ctx, "/records", { params: { id: ctx.recordId } })).data[0]; });
  await quietly(async () => { ctx.job = newest((await api(ctx, "/jobs", { params: { status: "ERROR" } })).data
                                          .filter((j) => j.record_id === ctx.recordId), "updated_at"); });
  await quietly(async () => { ctx.log = (await api(ctx, "/messages", { body: { ids: [ctx.recordId] } })).data.map(parseMsg); });
  await quietly(async () => { ctx.report = (await api(ctx, "/device-status", { params: { id: ctx.recordId } })).model; });
}
```

**Finding the right log row when there is no timestamp column.** In the source,
TC message strings were `SC,{sid},I,{msg_id},{qty},{action},{axis},{x},{y},{z},{storage},{dest},{weight};`
with `msg_id = S{sid}-{unix_ms:011x}{count:04x}`. Parse the time from the id, filter by
action kind **and** by the record in question (here, the errored job's bin), then take the newest:

```js
export function parseMsg(row) {
  const f = String(row.msg).replace(/;$/, "").split(",");
  const hex = (f[3] || "").split("-")[1] || "";
  const kids = row.children_list || [];
  const done = kids.filter((c) => c.is_completed).length;
  return { row, msgId: f[3], sentMs: parseInt(hex.slice(0, -4), 16) || 0, seq: parseInt(hex.slice(-4), 16) || 0,
           action: f[5], storage: f[10] ? Number(f[10]) : null,
           completed: kids.length > 0 && done === kids.length, nodesDone: done, nodesTotal: kids.length };
}
export function latest(messages, letters, forRecord) {
  const ofKind = messages.filter((m) => letters.includes(m.action)).sort((a, b) => a.sentMs - b.sentMs || a.seq - b.seq);
  const pool = forRecord ? ofKind.filter((m) => m.storage === forRecord) : [];
  return (pool.length ? pool : ofKind).at(-1) || null;
}
```

Tag rows in the log table with the parsed id (e.g. `item-class` returns
`guide-msg-${id}`), so the step targets exactly `.guide-msg-<id>`.

**Evidence chain.** One `ask` per check, ordered cheapest first, each with an
`end` for every "don't":

```js
{ id: "log-row", dock: true,
  target: (ctx) => [ctx.lastPick && `.guide-msg-${ctx.lastPick.msgId}`, ".dialog .table"],
  ask: (ctx) => `This is the latest pick for item ${ctx.lastPick.storage}. What state is it in?`,
  facts: (ctx) => [["Sent", yesNo(ctx.lastPick.row.msg_sent)],
                   ["Completed", `${ctx.lastPick.completed ? "yes" : "no"} (${ctx.lastPick.nodesDone}/${ctx.lastPick.nodesTotal})`,
                    ctx.lastPick.completed ? "good" : "bad"]],
  suggest: (ctx) => (ctx.lastPick.completed ? "Completed" : "Sent, but not completed"),
  choices: [
    { label: "Sent, but not completed" },
    { label: "Completed", end: () => "The system already recorded it. This isn't a missed report. Escalate." },
    { label: "No such message", end: () => "It was never sent. Don't flag; escalate." },
  ] },
{ id: "physical",
  ask: (ctx) => `Is item ${ctx.job.storage} physically at ${destination(ctx)}?`,
  note: "Someone has to see it. This can't be read from the system.",          // never suggested
  choices: [{ label: "Yes, it's there" }, { label: "No / not checked", end: () => "Location unconfirmed. Escalate." }] },
```

**Guard the irreversible screen.** Before its steps, check the screen agrees
with the evidence. Bind a `data-flow` attribute in the component, and use an `ask` with
`skipIf: el.dataset.flow === kind` whose only choice is `end` ("the screen and
the evidence disagree"). Then check the typed value with a live `note`, and
advance only when it equals the expected value.

**Socket-delivered results** (e.g. a scan answered over websocket): the HTTP
call returns at once with empty data, and the fields go blank and then fill. Use
`advance.decide`: remember blank, then branch to `ok` once both values are numeric,
or to `manual` when the component unlocks its fields (`data-locked="false"`).

---

## §7 Verification: mock backend + Playwright proof

**Mock backend** (Python `aiohttp` + `python-socketio` in a throwaway venv):
- Copy every response shape **from the backend source** (handler + serializer),
  including the envelope, error codes (400 vs 200 with `status:false`), non-standard
  envelopes, and the socket event payloads. Have an agent extract them with file:line references.
- Tell **one consistent story** across endpoints: a list row, its errored job, its
  message log, and its device report all agree. Put an older, *completed*
  message of the same kind before the newest, so "newest for this record" is actually tested.
- Record every non-GET request in `/__writes`; the test asserts there are no flag or confirm writes.
- `cors` middleware for non-socket paths; `sio.attach(app)`; a catch-all route records
  unmocked paths so missing shapes surface.
- Point the dev build at it: `VUE_APP_*`/`VITE_*` API and socket URLs → the mock port.

**Playwright walk** (one script per task and per branch):

```python
def ring_on(page, selector):          # is the pulsing ring around this element?
    return page.evaluate("""(sel) => { const ring = document.querySelector('.guide-ring');
      if (!ring) return false; const r = ring.getBoundingClientRect();
      return [...document.querySelectorAll(sel)].some(el => {
        const t = el.tagName === 'INPUT' ? (el.closest('.v-input') || el) : el;
        const b = t.getBoundingClientRect();
        return b.width && Math.abs(b.left - 6 - r.left) < 3 && Math.abs(b.top - 6 - r.top) < 3; }); }""", selector)
```

- Per step: screenshot, card text, suggested choice, and `ring_on(expected)`.
  The test acts like a user: it clicks the real control, then asserts the next anchor.
- Click with `>> visible=true`, because hidden duplicates (closed tabs/dialogs) resolve first.
  For a 0-px combobox input, click its `.v-input` wrapper.
- Close the app's own popups the way a user would. They are part of the real flow,
  and the guide must cope with them.
- Fresh page per run: a leftover focus-trapping dialog blocks Ctrl+K.
- Also print which log row the ring sits on, and compare it to the expected id.
- Assemble the screenshots into a proof page (a grid per task: step caption, card
  text, suggestion), so a human can review every step without rerunning anything.
