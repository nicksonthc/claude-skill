#!/usr/bin/env node
/**
 * glb-report — what is actually inside a .glb/.gltf, with no dependencies.
 *
 *   node glb-report.mjs model.glb [--json]
 *
 * Prints the numbers a viewer has to agree with: world bounding box, whether the
 * model sits on the ground, triangle and draw-call counts, texture payload,
 * materials, animations, and which loader extensions the file requires. Ends with
 * the camera/grid values derived from the box, so the viewer is framed from the
 * model's own measurements instead of guessed numbers.
 *
 * Why not @gltf-transform: this has to run in any repo, including one that has
 * never installed a node dependency. A GLB is a JSON chunk in a trivial binary
 * container, so reading it costs less than adding a toolchain.
 */
import { readFileSync, statSync } from 'node:fs'
import { basename, extname } from 'node:path'

// ---------------------------------------------------------------- container

function parse(file) {
  const buf = readFileSync(file)
  if (extname(file).toLowerCase() === '.gltf') return { json: JSON.parse(buf.toString('utf8')), bin: null }
  if (buf.readUInt32LE(0) !== 0x46546c67) throw new Error(`${file} is not a GLB (bad magic)`)
  let off = 12, json = null, bin = null
  while (off < buf.length) {
    const len = buf.readUInt32LE(off), type = buf.readUInt32LE(off + 4)
    const body = buf.subarray(off + 8, off + 8 + len)
    if (type === 0x4e4f534a) json = JSON.parse(body.toString('utf8'))
    else if (type === 0x004e4942) bin = body
    off += 8 + len // chunkLength already includes the 4-byte padding, per the GLB spec
  }
  if (!json) throw new Error('no JSON chunk')
  return { json, bin }
}

// ------------------------------------------------------------ matrix helpers
// Column-major 4x4, same convention as glTF and three.js.

const IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]

function multiply(a, b) {
  const o = new Array(16)
  for (let c = 0; c < 4; c++)
    for (let r = 0; r < 4; r++)
      o[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3]
  return o
}

function fromTRS(t = [0, 0, 0], r = [0, 0, 0, 1], s = [1, 1, 1]) {
  const [x, y, z, w] = r
  const x2 = x + x, y2 = y + y, z2 = z + z
  const xx = x * x2, xy = x * y2, xz = x * z2
  const yy = y * y2, yz = y * z2, zz = z * z2
  const wx = w * x2, wy = w * y2, wz = w * z2
  return [
    (1 - (yy + zz)) * s[0], (xy + wz) * s[0], (xz - wy) * s[0], 0,
    (xy - wz) * s[1], (1 - (xx + zz)) * s[1], (yz + wx) * s[1], 0,
    (xz + wy) * s[2], (yz - wx) * s[2], (1 - (xx + yy)) * s[2], 0,
    t[0], t[1], t[2], 1,
  ]
}

const applyPoint = (m, [x, y, z]) => [
  m[0] * x + m[4] * y + m[8] * z + m[12],
  m[1] * x + m[5] * y + m[9] * z + m[13],
  m[2] * x + m[6] * y + m[10] * z + m[14],
]

const nodeMatrix = (n) => (n.matrix ? n.matrix.slice() : fromTRS(n.translation, n.rotation, n.scale))

/**
 * KHR_mesh_quantization stores POSITION as normalized integers and leaves the
 * dequantisation to the node's scale. The accessor's own min/max are then RAW
 * integers, so they have to be decoded the same way the GPU decodes the data —
 * otherwise a 1 m trolley measures 34,539 units. Costs one division; skipping it
 * makes every derived camera number wrong.
 */
const NORMALIZE = { 5120: 127, 5121: 255, 5122: 32767, 5123: 65535 }

function decodeBounds(a) {
  const d = a.normalized ? NORMALIZE[a.componentType] : null
  const dec = (v) => (d ? Math.max(v / d, a.componentType === 5120 || a.componentType === 5122 ? -1 : 0) : v)
  return { min: a.min?.map(dec), max: a.max?.map(dec) }
}

// ------------------------------------------------------------------ analysis

function analyse(json) {
  const acc = json.accessors || [], meshes = json.meshes || [], nodes = json.nodes || []
  const box = { min: [Infinity, Infinity, Infinity], max: [-Infinity, -Infinity, -Infinity] }
  let triangles = 0, primitives = 0, positioned = 0
  const missingBounds = []

  const expand = (p) => {
    for (let i = 0; i < 3; i++) { if (p[i] < box.min[i]) box.min[i] = p[i]; if (p[i] > box.max[i]) box.max[i] = p[i] }
  }

  const visitMesh = (meshIndex, world) => {
    const mesh = meshes[meshIndex]
    if (!mesh) return
    for (const prim of mesh.primitives || []) {
      primitives++
      const mode = prim.mode ?? 4
      const idx = prim.indices != null ? acc[prim.indices] : null
      const pos = prim.attributes?.POSITION != null ? acc[prim.attributes.POSITION] : null
      const verts = idx ? idx.count : pos ? pos.count : 0
      if (mode === 4) triangles += verts / 3
      else if (mode === 5 || mode === 6) triangles += Math.max(0, verts - 2)
      if (pos?.min && pos?.max) {
        positioned++
        const bounds = decodeBounds(pos)
        const [ax, ay, az] = bounds.min, [bx, by, bz] = bounds.max
        for (const corner of [[ax, ay, az], [bx, ay, az], [ax, by, az], [ax, ay, bz], [bx, by, az], [bx, ay, bz], [ax, by, bz], [bx, by, bz]])
          expand(applyPoint(world, corner))
      } else missingBounds.push(mesh.name || `mesh ${meshIndex}`)
    }
  }

  const walk = (nodeIndex, parent, depth, seen) => {
    if (seen.has(nodeIndex)) return
    const n = nodes[nodeIndex]
    if (!n) return
    const world = multiply(parent, nodeMatrix(n))
    if (n.mesh != null) visitMesh(n.mesh, world)
    for (const child of n.children || []) walk(child, world, depth + 1, new Set([...seen, nodeIndex]))
  }

  const sceneIndex = json.scene ?? 0
  const roots = json.scenes?.[sceneIndex]?.nodes ?? nodes.map((_, i) => i)
  for (const r of roots) walk(r, IDENTITY, 0, new Set())

  if (!positioned) { box.min = [0, 0, 0]; box.max = [0, 0, 0] }
  const size = box.max.map((v, i) => v - box.min[i])
  const center = box.max.map((v, i) => (v + box.min[i]) / 2)
  const radius = Math.hypot(...size) / 2

  // textures
  const images = json.images || []
  let textureBytes = 0, largest = null, externalImages = 0
  for (const img of images) {
    let bytes = 0
    if (img.bufferView != null) bytes = json.bufferViews?.[img.bufferView]?.byteLength ?? 0
    else if (img.uri?.startsWith('data:')) bytes = Math.floor((img.uri.length - img.uri.indexOf(',') - 1) * 0.75)
    else if (img.uri) externalImages++
    textureBytes += bytes
    if (!largest || bytes > largest.bytes) largest = { name: img.name || img.uri || `image ${images.indexOf(img)}`, bytes, mime: img.mimeType || '' }
  }

  const materials = json.materials || []
  return {
    box, size, center, radius, triangles: Math.round(triangles), primitives, missingBounds,
    nodes: nodes.length, meshes: meshes.length,
    materials: materials.map((m) => ({
      name: m.name || '(unnamed)',
      doubleSided: !!m.doubleSided,
      alphaMode: m.alphaMode || 'OPAQUE',
      emissive: !!(m.emissiveFactor?.some((v) => v > 0) || m.emissiveTexture),
      unlit: !!m.extensions?.KHR_materials_unlit,
    })),
    images: images.length, textureBytes, largestImage: largest, externalImages,
    animations: (json.animations || []).map((a, i) => a.name || `animation ${i}`),
    skins: (json.skins || []).length,
    used: json.extensionsUsed || [], required: json.extensionsRequired || [],
    generator: json.asset?.generator || 'unknown',
  }
}

// ------------------------------------------------------------------- report

const LOADERS = {
  KHR_draco_mesh_compression: 'DRACOLoader — loader.setDRACOLoader(...), decoder path three/examples/jsm/libs/draco/gltf/',
  KHR_texture_basisu: 'KTX2Loader — loader.setKTX2Loader(ktx2.detectSupport(renderer)), transcoder path .../libs/basis/',
  EXT_meshopt_compression: 'MeshoptDecoder — loader.setMeshoptDecoder(MeshoptDecoder)',
}

const fmt = (n, d = 3) => Number(n.toFixed(d)).toString()
const mb = (b) => `${(b / 1e6).toFixed(2)} MB`

function print(file, r) {
  const fileBytes = statSync(file).size
  const [sx, sy, sz] = r.size
  const maxDim = Math.max(sx, sy, sz)
  const fov = 45
  const distance = (r.radius / Math.sin((fov / 2) * Math.PI / 180)) * 1.25
  const grounded = Math.abs(r.box.min[1]) < Math.max(0.01, maxDim * 0.01)
  const offCentre = Math.hypot(r.center[0], r.center[2]) > maxDim * 0.1

  const L = []
  L.push(`${basename(file)}  ${mb(fileBytes)}  ·  ${r.generator}`)
  L.push('')
  L.push(`  size (X×Y×Z)   ${fmt(sx)} × ${fmt(sy)} × ${fmt(sz)}     footprint ${fmt(sx)} × ${fmt(sz)}, height ${fmt(sy)}`)
  L.push(`  centre         ${r.center.map((v) => fmt(v)).join(', ')}        bounding radius ${fmt(r.radius)}`)
  L.push(`  ground (minY)  ${fmt(r.box.min[1])} ${grounded ? '— sits on the floor' : '— NOT on the floor'}`)
  L.push(`  geometry       ${r.triangles.toLocaleString()} triangles · ${r.primitives} primitives (≈ draw calls) · ${r.nodes} nodes`)
  L.push(`  materials      ${r.materials.length}${r.materials.length ? ': ' + r.materials.map((m) => m.name).slice(0, 6).join(', ') + (r.materials.length > 6 ? ' …' : '') : ''}`)
  L.push(`  textures       ${r.images} images, ${mb(r.textureBytes)}${r.largestImage && r.images ? ` (largest ${r.largestImage.name} ${mb(r.largestImage.bytes)})` : ''}`)
  if (r.animations.length) L.push(`  animations     ${r.animations.length}: ${r.animations.join(', ')}${r.skins ? ` · ${r.skins} skin(s)` : ''}`)
  if (r.used.length) L.push(`  extensions     ${r.used.join(', ')}${r.required.length ? `  (required: ${r.required.join(', ')})` : ''}`)

  const warn = []
  if (!r.triangles) warn.push('No triangles — the export is empty. Check the Blender selection / export filter.')
  if (maxDim === 0) warn.push('Zero-size bounding box — nothing has POSITION bounds.')
  else if (maxDim < 0.01) warn.push(`Largest dimension is ${fmt(maxDim)} units — likely a unit mistake (mm exported as m). Scale in Blender, not in the viewer.`)
  else if (maxDim > 1000) warn.push(`Largest dimension is ${fmt(maxDim)} units — likely a unit mistake (cm/mm scene exported raw).`)
  if (!grounded && maxDim) warn.push(`Model floats/sinks: minY = ${fmt(r.box.min[1])}. Ground it at Y=0 in Blender so shadow catchers and grids line up everywhere it is used.`)
  if (offCentre) warn.push(`Model is off-centre (centre X,Z = ${fmt(r.center[0])}, ${fmt(r.center[2])}). Orbit around the bounding-box centre, not the origin, or it will swing.`)
  if (sy > 0 && sz > sy * 3 && sx < sz * 0.5) warn.push('Very deep and flat — if this should be upright, the Blender exporter may have written Z-up. glTF is Y-up.')
  if (r.primitives > 200) warn.push(`${r.primitives} primitives means ~${r.primitives} draw calls; join meshes by material in Blender before shipping.`)
  if (r.textureBytes > 8e6) warn.push(`${mb(r.textureBytes)} of textures — resize or move to KTX2 before putting this on a page.`)
  if (r.externalImages) warn.push(`${r.externalImages} texture(s) reference external files — serve them next to the .gltf or re-export as .glb.`)
  if (r.missingBounds.length) warn.push(`No POSITION min/max on: ${[...new Set(r.missingBounds)].slice(0, 3).join(', ')} — the box below is incomplete.`)
  for (const ext of r.required) if (LOADERS[ext]) warn.push(`Requires ${ext} → wire up ${LOADERS[ext]}`)
  const blended = r.materials.filter((m) => m.alphaMode === 'BLEND')
  if (blended.length) warn.push(`${blended.length} BLEND material(s) (${blended.map((m) => m.name).slice(0, 3).join(', ')}) — transparency sorts badly on rotation; prefer alphaMode MASK where it is really a cutout.`)
  const doubleSided = r.materials.filter((m) => m.doubleSided)
  if (doubleSided.length === r.materials.length && r.materials.length) warn.push('Every material is double-sided — flipped normals stay invisible until something needs backface culling or shadows.')

  if (warn.length) { L.push(''); L.push('  ⚠ ' + warn.join('\n  ⚠ ')) }

  L.push('')
  L.push('  viewer settings derived from the box:')
  L.push(`    camera.fov        ${fov}`)
  L.push(`    camera.position   [${fmt(r.center[0] + distance * 0.55)}, ${fmt(r.center[1] + distance * 0.42)}, ${fmt(r.center[2] + distance * 0.72)}]   (3/4 view)`)
  L.push(`    controls.target   [${r.center.map((v) => fmt(v)).join(', ')}]`)
  L.push(`    camera.near/far   ${fmt(Math.max(distance / 500, 1e-4), 5)} / ${fmt(distance * 10)}`)
  L.push(`    min/maxDistance   ${fmt(r.radius * 0.6)} / ${fmt(distance * 4)}`)
  L.push(`    grid size / step  ${fmt(Math.ceil(maxDim * 3))} / ${fmt(Math.max(0.01, 10 ** Math.round(Math.log10(maxDim / 10))))}`)
  L.push(`    bloom threshold   0.85  (raise until only genuinely emissive surfaces glow)`)
  return L.join('\n')
}

// ---------------------------------------------------------------------- main

const args = process.argv.slice(2)
const file = args.find((a) => !a.startsWith('--'))
if (!file) { console.error('usage: node glb-report.mjs <model.glb|model.gltf> [--json]'); process.exit(1) }
const { json } = parse(file)
const r = analyse(json)
if (args.includes('--json')) console.log(JSON.stringify({ file, ...r }, null, 2))
else console.log(print(file, r))
