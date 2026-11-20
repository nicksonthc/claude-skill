# Spec schema (`src/sim/spec.js`)

The one machine-specific input. The template's demo spec is a complete, working example — copy its shape.

```js
export const spec = {
  title, subtitle,
  mode: 'walkthrough' | 'simulation',
  units: { item: 'part', carrier: 'carrier', perCarrier: 4 },
  layout: { /* free-form, per machine: positions [x,y,z] m, sizes, counts — read only by world.js */ },
  params: [ /* see below */ ],
  presets: { key: { label, v: { paramKey: value } } },
  steps: [ { id, title, sub, cls?: 'hot' | 'cold' } ],          // id = a status flag name
  views: { overview: [[px,py,pz], [tx,ty,tz]], ... },            // 'overview' is required
  tour: [ { view, caption } ],                                    // walkthrough order
  camera: { minDistance, maxDistance, clampTarget: [[x0,x1],[y0,y1],[z0,z1]] },
  compare: { option, values, label(v), sweep: { key, values } },  // simulation only
  assumptions: [ 'text shown with every analysis result' ],
};
export function makeConfig() { /* cfg = defaults of every param */ }
```

## params
```js
{ key: 'pickPlace', label: 'Robot pick & place / part', unit: 's', min: 1, max: 15, step: 0.1,
  group: 'Robot', def: 4, hint: 'deck: 16 s per 4 units', src: 'deck p.9', restart: false }
```
- `unit` drives speed-ups: `'s'` (duration) is divided by 1.05 / 1.1 / 1.5; `'m/s'` (speed) multiplied.
  Counts (`'cols'`, `'trays'`, `'lanes'`) are never "sped up".
- `restart: true` = changing it rebuilds the world (counts, layout); otherwise it applies to the next motion.
- `src` is mandatory: `deck p.N`, `sheet!B12`, `prompt`, or `assumed`. Show `assumed` ones in the config hint.
- Ranges: wide enough for the questions the engineer will ask (a dwell up to 12 h, not 1 h).

## Conventions
- Metres, seconds, Y up, X = main flow direction, Z = across. One structure width per module so modules
  tile along Z (that is how "add a second rack" became a `rackZ(r)` offset).
- Layout entries describe *positions and sizes*; components turn them into geometry. Never put geometry
  magic numbers in components — derive from the entry (`pitch`, `size`, `count`).
- Steps are user-facing language; flags are sim state. The flag names are the step ids.

## TypeScript option
Name the file `spec.ts` and type it:
```ts
export type Param = { key: string; label: string; unit: string; min: number; max: number; step: number;
  group: string; def: number; src: string; hint?: string; restart?: boolean };
export type View = [[number, number, number], [number, number, number]];
export type Spec = { title: string; subtitle?: string; mode: 'walkthrough' | 'simulation';
  units: { item: string; carrier: string; perCarrier: number }; layout: Record<string, unknown>;
  params: Param[]; presets?: Record<string, { label: string; v: Record<string, number> }>;
  steps: { id: string; title: string; sub?: string; cls?: 'hot' | 'cold' }[];
  views: Record<string, View> & { overview: View }; tour: { view: string; caption: string }[];
  camera: { minDistance: number; maxDistance: number; clampTarget?: [number, number][] };
  compare?: { option: string; values: number[]; label: (v: number) => string; sweep: { key: string; values: number[] } };
  assumptions: string[] };
export type Cfg = Record<string, number | boolean>;
```
Rename the other template files to `.ts` / `.tsx` (esbuild and Vite compile TS with no extra config) and
add types at the module boundaries (spec, cfg, `createSim` return, component handles) — not inside tweens.
