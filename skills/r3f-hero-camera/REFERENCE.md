# R3F Hero Camera — Reference

Copy-paste building blocks. Stack: R3F 8, drei 9, three 0.169
(`camera-controls` via drei). Genericize names to your scene; the structure is
the point.

```jsx
import { useEffect, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { CameraControls, OrthographicCamera, PerspectiveCamera } from '@react-three/drei'
import CameraControlsImpl from 'camera-controls'
import * as THREE from 'three'
```

## 1. Rig skeleton

One default camera + one `<CameraControls makeDefault>`; bounds derive from
scene size. Everything else in this file grabs `controlsRef.current`.

```jsx
export default function HeroCameraRig({ sceneSize }) {
  const controlsRef = useRef()
  // d = long side of your content's footprint — every recipe scales from it.
  const d = Math.max(sceneSize.x, sceneSize.z)
  // Zoom-out cap scales with content (+ flat term so tiny scenes don't clamp tight).
  const maxDist = d * 2.5 + 8

  return (
    <>
      <PerspectiveCamera makeDefault fov={50} near={0.1} far={800}
        position={[d * 0.8, d * 0.6, d * 1.1]} />
      <CameraControls ref={controlsRef} makeDefault
        minDistance={2} maxDistance={maxDist} />
      {/* mount shot effects / follow / attract here, passing controlsRef */}
    </>
  )
}
```

## 2. Shot helpers — the vocabulary as pure functions

Each returns nothing; it issues ONE damped `setLookAt`. `true` = camera-controls'
built-in transition (the only animator you need).

```jsx
// Establishing overview of a scene with long side d, centered at origin.
export function shotOverview(controls, d, midY = 0) {
  controls.setLookAt(d * 0.8, midY + d * 0.6, d * 1.1, 0, midY * 0.35, 0, true)
}

// 3/4 frame on any object: `center` (Vector3) + `span` (its footprint size).
// dir is the approach direction; distance scales with span, floored so tiny
// objects don't put the camera inside them.
export function shotFrame(controls, center, span, dir = [1, 0.85, 1.25]) {
  const dist = Math.max(span * 2.2, 2.4)
  const n = Math.hypot(dir[0], dir[1], dir[2])
  controls.setLookAt(
    center.x + (dir[0] / n) * dist,
    center.y + (dir[1] / n) * dist,
    center.z + (dir[2] / n) * dist,
    center.x, center.y, center.z,
    true,
  )
}

// Punch-in on a flat surface (a screen, a sign): eye on its world normal, at
// the fov-derived distance where a surface of height h fills the frame.
export function shotPunchIn(controls, surface, h, fovDeg = 50, margin = 1.1) {
  const pos = surface.getWorldPosition(new THREE.Vector3())
  const normal = new THREE.Vector3(0, 0, 1)
    .applyQuaternion(surface.getWorldQuaternion(new THREE.Quaternion()))
  const dist = ((h / 2) / Math.tan(THREE.MathUtils.degToRad(fovDeg) / 2)) * margin
  const eye = pos.clone().addScaledVector(normal, dist)
  controls.setLookAt(eye.x, eye.y, eye.z, pos.x, pos.y, pos.z, true)
}

// Context shot on the same surface: further out along the normal, offset
// sideways so the shot isn't dead-on, slightly raised.
export function shotContext(controls, surface, far = 2.6, side = 0.8) {
  const pos = surface.getWorldPosition(new THREE.Vector3())
  const normal = new THREE.Vector3(0, 0, 1)
    .applyQuaternion(surface.getWorldQuaternion(new THREE.Quaternion()))
  const lateral = new THREE.Vector3().crossVectors(normal, new THREE.Vector3(0, 1, 0))
  const eye = pos.clone().addScaledVector(normal, far).addScaledVector(lateral, side)
  controls.setLookAt(eye.x, eye.y + 0.5, eye.z, pos.x, pos.y, pos.z, true)
}

// First-person standpoint: stand at `stand` at eye height, look at `focus`,
// with a lateral offset perpendicular to the facing so the shot has depth.
export function shotStandpoint(controls, stand, focus, eyeHeight = 1.62, lateral = 0.55) {
  const dir = new THREE.Vector3().subVectors(focus, stand).setY(0).normalize()
  const px = -dir.z, pz = dir.x // perpendicular unit vector
  controls.setLookAt(
    stand.x + px * lateral, eyeHeight, stand.z + pz * lateral,
    focus.x, focus.y, focus.z,
    true,
  )
}

// Chase engage: one smooth fly-in to a pose beside a (moving) object.
export function shotChaseEngage(controls, obj) {
  const p = obj.position
  controls.setLookAt(p.x + 2.4, p.y + 2.0, p.z + 3.0, p.x, p.y, p.z, true)
}
```

## 3. Selection framing — click-to-focus, gated on the ladder

```jsx
// Gate on EVERYTHING above it in the priority ladder, so a beat shot, a manual
// override or an active follow can't be stomped by a stale selection.
function SelectionFraming({ controlsRef, selected, beatActive, override, followId }) {
  useEffect(() => {
    const controls = controlsRef.current
    if (!controls || !selected || beatActive || override || followId != null) return
    shotFrame(controls, selected.center, selected.span)
  }, [selected, beatActive, override, followId])
  return null
}
```

## 4. Follow cam — ONE smoothing stage, correct frame order

The two bugs this encodes: per-frame smooth `moveTo` double-lags (stutter), and
sampling before the mover ran reads last frame's position (jitter).

```jsx
// getTargetObj: () => Object3D | null — the followed thing's live group.
function FollowCam({ controlsRef, followId, getTargetObj }) {
  const smoothed = useRef(null)

  // Engage: fly to a chase pose; null the smoother so it re-seeds.
  useEffect(() => {
    smoothed.current = null
    const controls = controlsRef.current
    const obj = getTargetObj()
    if (!controls || !obj || followId == null) return
    shotChaseEngage(controls, obj)
  }, [followId])

  // PRIORITY 1: run AFTER the systems that move the target (default priority 0)
  // and BEFORE anything that renders manually (priority 2+). Left at 0, the
  // relative order is subscription-order-dependent → intermittent 1-frame lag.
  useFrame((_, dt) => {
    const controls = controlsRef.current
    const obj = getTargetObj()
    if (!controls || !obj || followId == null) return
    // Seed from wherever the camera was looking → engaging glides, never snaps.
    if (!smoothed.current) smoothed.current = controls.getTarget(new THREE.Vector3())
    const k = 1 - Math.exp(-12 * dt) // frame-rate independent, ~90% in 0.19s
    smoothed.current.lerp(obj.position, k)
    const t = smoothed.current
    controls.moveTo(t.x, t.y, t.z, false) // smooth=false — WE are the smoother
  }, 1)
  return null
}
```

Tension without re-aiming — dolly on a state change:

```jsx
useEffect(() => {
  controlsRef.current?.dollyTo(busy ? 3.6 : 4.0, true)
}, [busy])
```

## 5. Attract orbit + input interrupt

```jsx
function AttractOrbit({ controlsRef, active, beatKey }) {
  const broken = useRef(false)
  useEffect(() => { broken.current = false }, [beatKey]) // re-arm per beat

  useEffect(() => {
    const controls = controlsRef.current
    if (!controls) return
    const onStart = () => { broken.current = true } // any drag/wheel/touch
    controls.addEventListener('controlstart', onStart)
    return () => controls.removeEventListener('controlstart', onStart)
  }, [])

  useFrame((_, dt) => {
    const controls = controlsRef.current
    if (controls && active && !broken.current) controls.azimuthAngle += 0.05 * dt
  })
  return null
}
```

## 6. Perspective ↔ ortho top view

```jsx
function CameraModes({ controlsRef, isTop, content }) {
  const size = useThree((s) => s.size)
  const camera = useThree((s) => s.camera)

  // Auto-fit ortho frustum: content + margin fits any canvas aspect.
  const aspect = size.width / size.height
  const needW = content.w * 1.15, needH = content.d * 1.15
  const halfW = Math.max(needW / 2, (needH / 2) * aspect)
  const halfH = halfW / aspect

  // Fly into place on mode change. `camera` is a dep so this re-runs after the
  // makeDefault swap; the is*Camera guards skip the render where the OLD camera
  // is still default.
  useEffect(() => {
    const controls = controlsRef.current
    if (!controls) return
    if (isTop) {
      if (!camera.isOrthographicCamera) return
      camera.updateProjectionMatrix() // apply the manual frustum before framing
      controls.setLookAt(0, content.topY + 40, 0.01, 0, 0, 0, true) // z≈0.01: avoid gimbal-degenerate straight-down
      controls.zoomTo(1, false) // reset stale zoom or the fit is skewed
    } else {
      if (!camera.isPerspectiveCamera) return
      shotOverview(controls, Math.max(content.w, content.d), content.topY)
    }
  }, [camera, isTop, content.w, content.d, halfW, halfH])

  // Top view: rotation off (tilt breaks click accuracy), left-drag pans.
  useEffect(() => {
    const controls = controlsRef.current
    if (!controls) return
    controls.mouseButtons.left = isTop
      ? CameraControlsImpl.ACTION.TRUCK : CameraControlsImpl.ACTION.ROTATE
    controls.touches.one = isTop
      ? CameraControlsImpl.ACTION.TOUCH_TRUCK : CameraControlsImpl.ACTION.TOUCH_ROTATE
  }, [isTop, camera])

  return isTop ? (
    <OrthographicCamera makeDefault manual position={[0, content.topY + 40, 0]}
      near={0.1} far={400} left={-halfW} right={halfW} top={halfH} bottom={-halfH} />
  ) : (
    <PerspectiveCamera makeDefault fov={50} near={0.1} far={800} />
  )
}
```

Pose requested from the wrong mode (a "focus on X" button pressed in top view):
store a pending flag, force the mode, land when the right camera arrives.

```jsx
const pendingFocus = useRef(false)
useEffect(() => { if (focusNonce > 0) pendingFocus.current = true }, [focusNonce])
useEffect(() => {
  const controls = controlsRef.current
  if (!controls || !pendingFocus.current || isTop || !camera.isPerspectiveCamera) return
  shotPunchIn(controls, screenRef.current, 0.62)
  pendingFocus.current = false
}, [focusNonce, isTop, camera]) // re-fires after the ortho→perspective swap
```

## 7. ESC ladder

Release the most specific state first — one handler, one ladder.

```jsx
useEffect(() => {
  const onKey = (e) => {
    if (e.key !== 'Escape') return
    if (tourActive) endTour()
    else if (beatActive) stepBack()
    else stopFollow()
  }
  window.addEventListener('keydown', onKey)
  return () => window.removeEventListener('keydown', onKey)
}, [tourActive, beatActive])
```

## 8. Handoff ride (optional)

Temporarily retarget the follow smoother at another object (a package handed to
a conveyor, a ball passed), linger, then let go — the smoother itself glides the
view back, no extra shot needed. Both timers are mandatory: linger for the beat,
an absolute cap so a blocked target can't park the camera forever.

```jsx
const HANDOFF_LINGER_MS = 1500
const HANDOFF_MAX_MS = 9000

// Inside the follow useFrame, before smoothing:
let rideObj = null
if (handoff) {
  const meta = handoffMeta.current // { t0, arrivedAt } set when the handoff began
  const now = performance.now()
  if (!handoffObj || now - meta.t0 > HANDOFF_MAX_MS) endHandoff()
  else {
    if (handoffArrived && meta.arrivedAt == null) meta.arrivedAt = now
    if (meta.arrivedAt != null && now - meta.arrivedAt > HANDOFF_LINGER_MS) endHandoff()
    else rideObj = handoffObj
  }
}
const p = (rideObj ?? followedObj).position
```
