// Builds the 3D world from the spec layout using the component library. Returns the handles the sim
// animates plus world.labels / skins / glass for the UI, and dispose() for rebuilds.
// headless: true = no canvas textures (experiments run thousands of worlds without drawing).
import * as THREE from 'three';
import { Batch, instantiate, disposeTree } from '../core/batch.js';
import { materials } from '../core/mats.js';
import { conveyor, frame, floorZone, nestPlate, scara, carrierProtos, makePart, operator, towerLight, plate } from '../components/index.js';

export function buildWorld(scene, cfg, spec, { headless = false } = {}) {
  const M = materials(), L = spec.layout;
  const root = new THREE.Group();
  scene.add(root);
  const own = [], labels = [];
  const world = { root, labels, skins: [], glass: [], carriers: [] };
  const lbl = (text, p, cls = '') => labels.push({ p: new THREE.Vector3(...p), text, cls });

  // floor + zones
  if (!headless) {
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(40, 30).rotateX(-Math.PI / 2), M.floor);
    floor.position.set(2, 0, 0); floor.receiveShadow = true; floor.userData.own = true; root.add(floor);
  }
  const b = new Batch(), skin = new Batch(), glass = new Batch();
  floorZone(b, M, { at: [1.6, 0, 0], size: [5.6, 2.6], w: 0.08 });
  floorZone(b, M, { at: L.staging.inAt, size: [0.7, 0.6], mat: M.zoneIn });
  floorZone(b, M, { at: L.staging.outAt, size: [0.7, 0.6], mat: M.zoneOut });

  // equipment
  const cin = conveyor(b, M, { x0: L.inbound.x0, x1: L.inbound.x1, z: L.inbound.z, h: L.inbound.h });
  const cout = conveyor(b, M, { x0: L.outbound.x0, x1: L.outbound.x1, z: L.outbound.z, h: L.outbound.h });
  const np = nestPlate(b, M, root, own, { at: L.nests.at, cols: cfg.nestCols, rows: 2, pitch: L.nests.pitch, h: L.nests.h });
  frame(b, skin, glass, M, { at: L.enclosure.at, size: L.enclosure.size, open: L.enclosure.open, glassSides: L.enclosure.glassSides, base: 0 });
  towerLight(b, M, L.enclosure.at[0] - 0.6, L.enclosure.size[1], L.enclosure.at[2] - 0.6);
  const robot = scara(M, root, L.robot);

  b.build(root);
  world.skins = skin.build(root, { cast: true });
  world.glass = glass.build(root, { cast: false, receive: false });
  world.glass.forEach((m) => (m.renderOrder = 10));

  // carriers + parts (prototypes shared by every copy)
  const P = carrierProtos(M, { cols: 2, rows: 2, pitch: 0.09 });
  world.spawnCarrier = (withParts) => {
    const group = instantiate(P.carrier);
    const c = { group, slots: P.pockets.map(() => null), pockets: P.pockets };
    if (withParts) c.slots = P.pockets.map((pk) => { const d = makePart(P, M); d.group.position.set(...pk); group.add(d.group); return d; });
    root.add(group); world.carriers.push(c);
    c.dispose = () => { root.remove(group); const i = world.carriers.indexOf(c); if (i >= 0) world.carriers.splice(i, 1); };
    return c;
  };
  world.P = P;

  // operator at the HMI corner (decor; animate if the process needs a person)
  const op = operator(M);
  op.group.position.set(L.enclosure.at[0] + L.enclosure.size[0] / 2 + 0.6, 0, L.outbound.z + 0.9); // clear of the belts
  op.group.rotation.y = 0.5;
  root.add(op.group);

  if (!headless) {
    const sign = plate(spec.title.toUpperCase(), { w: 1.4, h: 0.14 });
    sign.position.set(L.enclosure.at[0], L.enclosure.size[1] + 0.25, L.enclosure.at[2] - L.enclosure.size[2] / 2);
    root.add(sign);
  }
  lbl('Inbound conveyor', [cin.pos(0.5).x, 1.3, L.inbound.z], 'big');
  lbl('Outbound conveyor', [cout.pos(0.5).x, 1.3, L.outbound.z]);
  lbl('SCARA robot', [L.robot.at[0], 1.75, L.robot.at[2]]);
  lbl(`Process nests ×${np.nests.length}`, [L.nests.at[0], 1.5, L.nests.at[2]], 'big');

  Object.assign(world, { M, robot, nests: np.nests, cin, cout, operator: op });
  world.dispose = () => { world.carriers.slice().forEach((c) => c.dispose()); scene.remove(root); disposeTree(root, own); };
  return world;
}
