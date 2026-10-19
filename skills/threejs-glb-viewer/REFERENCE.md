# Reference — GLB in three.js and R3F

Copy-paste blocks. [SKILL.md](SKILL.md) has the discipline; this has the code.

- [Vanilla three.js](#vanilla-threejs) — renderer, loader, fit, OrbitControls, composer
- [React Three Fiber](#react-three-fiber) — the same thing in R3F 9 / drei 10
- [Post-processing recipes](#post-processing-recipes)
- [Verifying it rendered](#verifying-it-rendered)

Versions: three 0.186, @react-three/fiber 9, @react-three/drei 10,
@react-three/postprocessing 3. Where an API changed recently it is flagged.

---

## Vanilla three.js

### Renderer — the colour-management contract

Four settings decide whether the model looks like it did in Blender. Set them
together; set two of them and you get a plausible-but-wrong image that people
then "fix" with exposure.

```js
import * as THREE from 'three'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'

const renderer = new THREE.WebGLRenderer({ antialias: true })
renderer.setPixelRatio(Math.min(devicePixelRatio, 2))   // 3+ on a phone costs 2x fill for nothing
renderer.setSize(innerWidth, innerHeight)
renderer.outputColorSpace = THREE.SRGBColorSpace        // default since r152, but be explicit
renderer.toneMapping = THREE.ACESFilmicToneMapping      // HDR lighting → displayable range
renderer.toneMappingExposure = 1
renderer.shadowMap.enabled = true
renderer.shadowMap.type = THREE.PCFShadowMap            // PCFSoftShadowMap deprecated in r186

const scene = new THREE.Scene()

// Image-based lighting. A glTF PBR material with nothing to reflect renders
// black metal and dead roughness — this is lighting, not polish.
const pmrem = new THREE.PMREMGenerator(renderer)
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture
// For a real HDRI instead:
//   new RGBELoader().load('studio.hdr', (t) => {
//     t.mapping = THREE.EquirectangularReflectionMapping
//     scene.environment = t          // lighting
//     scene.background = t           // and visible behind the model, if wanted
//   })
```

### GLTFLoader with every decoder wired

Wire all three once and the loader opens any export. The decoders are fetched at
runtime, so those paths must be served — a 404 on a decoder presents as a broken
model, not as a network error.

```js
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js'
import { KTX2Loader } from 'three/addons/loaders/KTX2Loader.js'
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js'

const BASE = 'https://cdn.jsdelivr.net/npm/three@0.186.0/examples/jsm/libs/'
// In a bundled app, copy node_modules/three/examples/jsm/libs/{draco,basis} into
// /public instead and point at those — a CDN version drift breaks decoding.

const loader = new GLTFLoader()
  .setDRACOLoader(new DRACOLoader().setDecoderPath(`${BASE}draco/gltf/`))
  .setKTX2Loader(new KTX2Loader().setTranscoderPath(`${BASE}basis/`).detectSupport(renderer))
  .setMeshoptDecoder(MeshoptDecoder)

const gltf = await loader.loadAsync(url, (e) => {
  if (e.total) console.log(`${Math.round((e.loaded / e.total) * 100)}%`)
})
gltf.scene.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true } })
scene.add(gltf.scene)
```

`e.total` is 0 when the server sends no `Content-Length` (common with gzip), so
guard the percentage or the UI shows `NaN%`.

### Fit everything to the model's box

The single function the rest of the viewer derives from. Call it after load and
on any model swap.

```js
function fit(object, camera, controls, { fov = camera.fov, margin = 1.25 } = {}) {
  const box = new THREE.Box3().setFromObject(object)
  const size = box.getSize(new THREE.Vector3())
  const centre = box.getCenter(new THREE.Vector3())
  const radius = size.length() / 2 || 1
  const distance = (radius / Math.sin((fov / 2) * THREE.MathUtils.DEG2RAD)) * margin

  // near/far scaled to the subject: a fixed 0.1/1000 z-buffers a 3 cm token into
  // stripes and clips a 40 m building.
  camera.near = distance / 500
  camera.far = distance * 10
  camera.position.set(centre.x + distance * 0.55, centre.y + distance * 0.42, centre.z + distance * 0.72)
  camera.updateProjectionMatrix()

  controls.target.copy(centre)        // the centre, NOT the origin
  controls.minDistance = radius * 0.4
  controls.maxDistance = distance * 5
  controls.update()
  return { box, size, centre, radius, distance }
}
```

`setFromObject` walks world matrices, so it is correct for nested/instanced
models — but it needs the object in the scene graph with matrices updated. After
adding, call it directly; inside a framework, call it after the frame that mounts.

### OrbitControls

```js
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

const controls = new OrbitControls(camera, renderer.domElement)
controls.enableDamping = true        // inertia — REQUIRES controls.update() every frame
controls.dampingFactor = 0.06
controls.screenSpacePanning = true   // pan parallel to the screen; false pans along the ground
controls.maxPolarAngle = Math.PI * 0.495   // stop just above the horizon on a grounded model
controls.autoRotate = false
controls.autoRotateSpeed = 0.9
// controls.minDistance / maxDistance come from fit()

renderer.setAnimationLoop(() => {
  controls.update()
  composer.render()
})
```

Gotchas worth knowing: `controls.update()` is required whenever damping or
autoRotate is on — its absence is the single most common "my OrbitControls does
nothing". Attaching to `document.body` instead of `renderer.domElement` steals
scroll from the whole page. And `controls.addEventListener('change', render)` is
the render-on-demand pattern for a still viewer — but it does not work with
damping, which needs a continuous loop.

### The composer

```js
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js'
import { SMAAPass } from 'three/addons/postprocessing/SMAAPass.js'
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js'

const composer = new EffectComposer(renderer)   // HalfFloat targets by default since r152
composer.addPass(new RenderPass(scene, camera))
composer.addPass(new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), 0.2, 0.45, 1.4))
composer.addPass(new SMAAPass())                // no-arg since r16x; MSAA is unavailable here
composer.addPass(new OutputPass())              // tone mapping + sRGB. Last. Always.

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight
  camera.updateProjectionMatrix()
  renderer.setSize(innerWidth, innerHeight)
  composer.setSize(innerWidth, innerHeight)     // forgetting this blurs the image on resize
})
```

Why `OutputPass` matters: since r152 three applies tone mapping and the output
colour-space conversion **only when rendering to the default framebuffer**. A
composer renders into its own targets, so that work never happens — `OutputPass`
does it at the end of the chain. Drop it and the image is flat and dark; add tone
mapping in a second place and it is applied twice.

### Disposing on model swap

Removing the scene does not free GPU memory. A gallery that skips this dies
around the tenth model.

```js
function disposeModel(object) {
  object.traverse((o) => {
    o.geometry?.dispose()
    for (const m of [o.material].flat().filter(Boolean)) {
      for (const v of Object.values(m)) v?.isTexture && v.dispose()
      m.dispose()
    }
  })
}
scene.remove(model); disposeModel(model)
```

---

## React Three Fiber

Same discipline, different spelling. `<Bounds fit clip observe>` replaces the
manual `fit()`; `<ToneMapping>` plays the role of `OutputPass`.

```tsx
'use client'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Bounds, Environment, ContactShadows, useGLTF, Clone } from '@react-three/drei'
import { EffectComposer, Bloom, SMAA, ToneMapping } from '@react-three/postprocessing'
import { ToneMappingMode } from 'postprocessing'
import { Suspense } from 'react'

function Model({ src }: { src: string }) {
  const { scene } = useGLTF(src)
  // useGLTF caches by URL: mutating `scene` mutates it for every other consumer.
  // <Clone> gives this instance its own nodes and materials.
  return <Clone object={scene} castShadow receiveShadow />
}

export default function Viewer({ src }: { src: string }) {
  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      camera={{ fov: 45 }}                    // position comes from <Bounds>, not from here
      gl={{ antialias: false }}               // the composer owns AA; SMAA does it
    >
      <color attach="background" args={['#454a54']} />
      <Environment preset="studio" />          {/* PBR needs something to reflect */}
      <directionalLight position={[4, 6, 3]} intensity={1.6} castShadow shadow-mapSize={[2048, 2048]} />

      <Suspense fallback={null}>
        {/* observe re-fits when the model or the viewport changes; clip sets near/far */}
        <Bounds fit clip observe margin={1.25}>
          <Model src={src} />
        </Bounds>
        <ContactShadows position={[0, 0, 0]} opacity={0.45} scale={8} blur={2.4} far={4} />
      </Suspense>

      <OrbitControls makeDefault enableDamping dampingFactor={0.06} maxPolarAngle={Math.PI * 0.495} />

      <EffectComposer multisampling={0}>
        <Bloom intensity={0.2} luminanceThreshold={1.0} luminanceSmoothing={0.2} mipmapBlur />
        <SMAA />
        <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
      </EffectComposer>
    </Canvas>
  )
}

useGLTF.preload('/models/object.glb')
```

R3F-specific notes:

- **`makeDefault`** on the controls registers them as `state.controls`, which is
  how drei helpers (and `r3f-hero-camera`) find the camera owner. Without it a
  second driver silently fights OrbitControls.
- **`multisampling={0}`** plus `<SMAA/>`: MSAA does nothing once the composer has
  the frame, and asking for both wastes a buffer.
- **`<ToneMapping>` last.** The composer takes output over from r3f, which would
  otherwise lose its default ACES mapping — the same trap as `OutputPass`.
- **Suspense and size.** A suspended model has no bounds on the first frame, so
  fit *after* it resolves. `<Bounds observe>` handles that; a `useLayoutEffect`
  measuring on mount does not.
- **Draco in drei:** `useGLTF(url, true)` enables the Draco loader with drei's
  hosted decoder; `useGLTF(url, '/draco/')` points at your own copy.
  `useGLTF(url, true, true)` also enables meshopt.
- **Unmount cost.** `useGLTF.clear(url)` drops a cached model when a gallery is
  done with it; otherwise every model ever viewed stays resident.

If the project already has a shared post-processing component, reuse it rather
than adding a second `<EffectComposer>` — two composers in one canvas means two
full-screen passes and the later one wins.

---

## Post-processing recipes

| Want | Pass / effect | The setting that matters |
|---|---|---|
| Emissive glow | `UnrealBloomPass(res, 0.2, 0.45, 1.4)` / `<Bloom mipmapBlur/>` | threshold above 1 — see SKILL.md §3 |
| Antialiasing | `SMAAPass()` / `<SMAA/>` | the renderer's `antialias` is dead once the composer runs |
| Best-quality AA on a still | `SSAARenderPass` (sampleLevel 2–4) | replaces RenderPass; only for a paused/turntable shot |
| Contact darkening | `GTAOPass` / `<N8AO/>` | needs a normal pass; costs a full extra render — off by default |
| Depth of field | `BokehPass` / `<DepthOfField/>` | `focus` must track the orbit target, or the subject blurs when you zoom |
| Edge highlight on select | `OutlinePass` / `<Outline/>` + `<Selection>` | give it the selected objects, not the whole scene |
| Colour grade | `LUTPass` / `<LUT/>` | before `OutputPass`, never after |

Ordering rule: geometry-aware passes (AO, outline, DoF) need the depth buffer, so
they go immediately after `RenderPass`; screen-space beautifiers (bloom, grade)
next; antialiasing near the end; `OutputPass` absolutely last.

---

## Verifying it rendered

A viewer is visual, so the check is a picture — not an assertion about the scene
graph. Expose a handle and drive it headlessly:

```js
window.__viewer = { scene, camera, controls, composer, renderer, model, info, fit }
```

```js
// Playwright. Under SwiftShader, rAF stalls without input — nudge it or the
// screenshot catches a frozen first frame and the HUD never updates.
await page.goto('http://localhost:8080/viewer.html?src=model.glb')
await page.waitForFunction(() => window.__viewer?.info)
for (let i = 0; i < 40; i++) { await page.mouse.move(500 + (i % 7), 320); await page.waitForTimeout(40) }
const info = await page.evaluate(() => window.__viewer.info)
await page.screenshot({ path: 'model.png' })
```

Launch chromium with `--use-gl=angle --use-angle=swiftshader
--enable-unsafe-swiftshader` for WebGL in headless. Then *look at the PNG* — the
numbers confirm the model loaded, only the image confirms it looks right.

`node scripts/glb-report.mjs model.glb` and the viewer's HUD compute the box
independently, so when they agree the measurement is trustworthy; when they
disagree, something in the scene graph is transforming the model.
