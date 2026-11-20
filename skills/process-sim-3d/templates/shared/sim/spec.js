// The sim spec: the ONE machine-specific input. Everything below is the demo cell
// (inbound conveyor -> SCARA -> process nests -> SCARA -> outbound conveyor). Replace it per project;
// keep the shape. Every value notes where it came from (deck page, sheet cell, or "assumed").
// See references/spec-schema.md for the full schema.

export const spec = {
  title: 'Pick · process · place cell',
  subtitle: 'Carrier in → robot loads nests → timed process → robot unloads → carrier out',
  mode: 'simulation', // 'walkthrough' (visual tour, no metrics) | 'simulation' (timing-accurate + analysis)
  units: { item: 'part', carrier: 'carrier', perCarrier: 4 }, // source: assumed

  // Layout (metres, Y up, X = flow direction). World code reads these; the UI never does.
  layout: {
    inbound: { x0: 4.2, x1: 1.3, z: -0.45, h: 0.85 }, // conveyor: x0 -> x1, carriers stop at x1
    outbound: { x0: 1.3, x1: 4.2, z: 0.45, h: 0.85 },
    robot: { at: [0.85, 0, 0], L1: 0.45, L2: 0.4, h: 1.05 },
    nests: { at: [0.25, 0, 0], pitch: 0.16, h: 0.85 },
    enclosure: { at: [0.55, 0, 0], size: [1.6, 2.0, 1.6], open: ['+x'], glassSides: ['-z', '+z', '-x'] },
    staging: { inAt: [4.6, 0, -0.45], outAt: [4.6, 0, 0.45] },
  },

  // Configurable values -> the Timing & configuration panel. unit 'm/s' = speed (faster = bigger),
  // 's' = duration (faster = smaller). restart: true = the world must be rebuilt.
  params: [
    { key: 'nestCols', label: 'Nest columns (× 2 rows)', unit: 'cols', min: 1, max: 4, step: 1, group: 'Layout', restart: true, def: 3, src: 'assumed' },
    { key: 'arrivalGap', label: 'Next carrier arrival delay', unit: 's', min: 0, max: 600, step: 5, group: 'Load', def: 0, hint: '0 = a carrier is always waiting', src: 'assumed' },
    { key: 'beltSpeed', label: 'Conveyor speed', unit: 'm/s', min: 0.05, max: 1, step: 0.05, group: 'Transport', def: 0.3, src: 'assumed' },
    { key: 'transfer', label: 'Empty carrier cross-transfer', unit: 's', min: 1, max: 20, step: 0.5, group: 'Transport', def: 4, src: 'assumed' },
    { key: 'pickPlace', label: 'Robot pick & place / part', unit: 's', min: 1, max: 15, step: 0.1, group: 'Robot', def: 4, src: 'assumed' },
    { key: 'press', label: 'Press lid stroke', unit: 's', min: 0.2, max: 5, step: 0.1, group: 'Process', def: 1, src: 'assumed' },
    { key: 'process', label: 'Process dwell', unit: 's', min: 1, max: 7200, step: 1, group: 'Process', def: 60, src: 'assumed' },
  ],
  presets: { demo: { label: 'Quick demo', v: { process: 20, pickPlace: 2.5, beltSpeed: 0.6 } } },

  // Flow steps -> left panel; `flag` names the sim status flag that lights the step.
  steps: [
    { id: 'arrive', title: 'Carrier arrives', sub: 'Inbound conveyor to the pick position' },
    { id: 'load', title: 'Robot loads a nest', sub: 'Carrier → process nest' },
    { id: 'process', title: 'Press down · process', sub: 'Timed dwell, nest glows while hot', cls: 'hot' },
    { id: 'unload', title: 'Robot unloads', sub: 'Finished part → outbound carrier' },
    { id: 'transfer', title: 'Empty carrier transfers', sub: 'Pick side → place side' },
    { id: 'leave', title: 'Full carrier leaves', sub: 'Outbound conveyor' },
  ],

  // Camera shots [position, target]; the walkthrough tour visits them with the step captions.
  views: {
    overview: [[5.2, 3.2, -4.4], [1.2, 0.8, 0]],
    robot: [[2.0, 1.9, -1.6], [0.6, 0.95, 0]],
    nests: [[0.9, 1.6, -1.1], [0.25, 0.9, 0]],
    conveyors: [[5.6, 1.6, -1.8], [2.8, 0.8, 0]],
    top: [[1.3, 7.5, 0.01], [1.3, 0, 0]],
  },
  tour: [
    { view: 'overview', caption: 'The whole cell: carriers come in on the near conveyor and leave on the far one.' },
    { view: 'conveyors', caption: 'Carriers of 4 parts arrive at the pick position.' },
    { view: 'robot', caption: 'One SCARA robot loads and unloads every nest.' },
    { view: 'nests', caption: 'Each nest presses down and processes its part for the dwell time.' },
    { view: 'overview', caption: 'Finished parts are packed back into carriers and leave.' },
  ],
  camera: { minDistance: 0.6, maxDistance: 18, clampTarget: [[-2, 6], [0, 2.5], [-3, 3]] },

  // Analysis: which discrete option to compare and which numeric param to sweep.
  compare: { option: 'nestCols', values: [2, 3], label: (v) => `${v * 2} nests`, sweep: { key: 'process', values: [10, 30, 60, 120, 300, 900] } },
  assumptions: ['A carrier is always waiting at the inbound (arrivalGap 0).', 'No faults, retests or maintenance.'],
};

export function makeConfig() {
  const cfg = { continuous: true };
  for (const p of spec.params) cfg[p.key] = p.def;
  return cfg;
}
