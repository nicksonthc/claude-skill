# Guided Placement — Reference

Copy-paste building blocks. Stack: R3F 8, drei 9, three 0.169. One file's worth of
components; split as you like.

```jsx
import { useRef, useState, useCallback, useMemo, useEffect } from 'react'
import { useFrame } from '@react-three/fiber'
import { Line, Outlines, Html } from '@react-three/drei'
import * as THREE from 'three'

/* ------------------------------------------------------------------ *
 * easing helpers
 * ------------------------------------------------------------------ */
const damp = THREE.MathUtils.damp                     // frame-rate independent smoothing
const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3)
const distXZ = (a, b) => Math.hypot(a.x - b.x, a.z - b.z)

// Asymmetric pop: FAST attack (peak at 30% of duration), slow settle.
// A symmetric sine reads as a breath, not a pop.
const popScale = (t, dur = 0.45, amp = 0.25) => {
  if (t >= dur) return 1
  const k = t / dur
  return k < 0.3
    ? 1 + amp * easeOutCubic(k / 0.3)
    : 1 + amp * (1 - easeOutCubic((k - 0.3) / 0.7))
}
```

## 0. Placement policies — the object-aware part

```jsx
// What the grabbed object IS decides where it may land. The hook takes a
// policy; per-object constraints live in `resolve`, nothing else changes.

// One slot. Drop commits when the object is within snapRadius of it.
export const fixedTarget = (target) => ({
  mode: 'fixed',
  resolve: (_point, out) => {
    out.point.set(...target)
    out.valid = true
    return out
  },
})

// Any valid position: resolve(worldPoint, out) fills out.point (quantized slot
// center) + out.valid (this object may land there) + any meta (e.g. out.cell),
// or returns null when the pointer is off the placeable area entirely.
export const freePlacement = (resolve) => ({ mode: 'free', resolve })

// Example — a robot may park on any free grid cell:
//   freePlacement((p, out) => {
//     const cell = layout.cellAtPoint(p)
//     if (!cell) return null
//     const [cx, cz] = layout.cellCenter(cell[0], cell[1])
//     out.point.set(cx, deckY, cz)
//     out.cell = cell
//     out.valid = isFreeCell(cell)        // bounds/occupancy/forbidden zones
//     return out
//   })
```

## 1. The hook — FSM + math-plane drag + per-frame stepping

No drag-plane mesh: pointer capture routes ALL events to the captured object, so a
separate plane mesh would go deaf. The object handles its own `onPointerMove` and
intersects `e.ray` with a math plane at lift height.

```jsx
export const PHASES = ['idle', 'selected', 'dragging', 'snapping', 'placed', 'reverting']

export function useGuidedPlacement({
  home,                       // [x,y,z] resting position
  policy,                     // fixedTarget(...) | freePlacement(resolve)
  liftHeight = 0.5,
  snapRadius = 0.7,           // magnet ENGAGES inside this
  releaseRadius,              // magnet RELEASES outside this (hysteresis); default 1.35×
  magnetStrength = 0.85,      // max pull toward the slot center (0..1)
  snapDur = 0.3,              // commit lerp seconds
  settleDur = 0.9,            // placed celebration seconds
  rehome = true,              // after placement the slot becomes the new home
  driveRef,                   // OPTIONAL external group to drive (fleet/sim-owned object)
  onGrab,                     // (box:THREE.Box3) → camera framing. Fires on pointer DOWN.
  onPlaced,                   // (candidate) → commit to your store
  isStillGrabbable,           // OPTIONAL () => bool — abort mid-drag if owner state changed
}) {
  const relRadius = releaseRadius ?? snapRadius * 1.35
  const groupRef = useRef()
  const getG = () => (driveRef ?? groupRef).current

  const [phase, setPhase] = useState('idle')
  const phaseRef = useRef('idle')
  const go = useCallback((p) => { phaseRef.current = p; setPhase(p) }, [])

  const homeV = useRef(new THREE.Vector3()).current
  useEffect(() => { homeV.set(...home) }, [home.join(',')])   // eslint-disable-line

  // per-frame signals — refs, no re-render
  const intent    = useRef(new THREE.Vector3()).current   // raw pointer intent (XZ)
  const candidate = useRef({ point: new THREE.Vector3(), valid: false, has: false }).current
  const proximity = useRef(0)                             // 0..1 magnet weight — stages read it
  const magnetOn  = useRef(false)
  const lift      = useRef(0)
  const grabT     = useRef(0)                             // anticipation timeline
  const snapT     = useRef(0)
  const placedT   = useRef(0)
  const snapFrom  = useRef(new THREE.Vector3()).current   // captured at drop — single-source lerp
  const plane     = useRef(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)).current
  const hit       = useRef(new THREE.Vector3()).current
  const want      = useRef(new THREE.Vector3()).current

  const resolveAt = (point) => {
    const res = policy.resolve(point, candidate)
    if (res) { candidate.has = true } else { candidate.has = false; candidate.valid = false }
  }

  /* ---- pointer handlers (spread via `bind`) ---- */
  const onPointerDown = useCallback((e) => {
    if (phaseRef.current !== 'idle') return
    const g = getG(); if (!g) return
    e.stopPropagation()
    e.target.setPointerCapture?.(e.pointerId)
    document.body.style.cursor = 'grabbing'
    intent.copy(g.position)
    resolveAt(g.position)
    grabT.current = 0
    go('selected')
    // Camera frames NOW — pointer is down but not yet moving. Never mid-drag.
    if (onGrab) {
      const box = new THREE.Box3().expandByPoint(g.position)
      if (candidate.has) box.expandByPoint(candidate.point)
      box.expandByScalar(liftHeight + 0.5)
      onGrab(box)
    }
  }, [go, onGrab, liftHeight])

  const onPointerMove = useCallback((e) => {
    const p = phaseRef.current
    if (p !== 'selected' && p !== 'dragging') return
    plane.constant = -(homeV.y + liftHeight)              // plane at lift height
    if (!e.ray.intersectPlane(plane, hit)) return
    intent.set(hit.x, homeV.y, hit.z)
    resolveAt(hit)
    if (p === 'selected') go('dragging')
  }, [go, liftHeight])

  const endDrag = useCallback((e) => {
    const p = phaseRef.current
    if (p !== 'selected' && p !== 'dragging') return
    e?.target?.releasePointerCapture?.(e.pointerId)
    document.body.style.cursor = 'auto'
    const g = getG()
    const ok = p === 'dragging' && candidate.has && candidate.valid &&
               g && distXZ(g.position, candidate.point) <= relRadius
    if (ok) { snapFrom.copy(g.position); snapT.current = 0; go('snapping') }
    else { intent.copy(homeV); go('reverting') }
  }, [go, relRadius])

  /* ---- per-frame stepping ---- */
  useFrame((_, dt) => {
    const g = getG(); if (!g) return
    const p = phaseRef.current
    if (p === 'idle') { grabT.current = 0; return }

    // owner state changed under us (robot got a job, slot got taken) → abort
    if ((p === 'selected' || p === 'dragging') && isStillGrabbable && !isStillGrabbable()) {
      document.body.style.cursor = 'auto'
      intent.copy(homeV); go('reverting')
    }

    // 1b. anticipation: squash 1→0.95→1 over 120ms; lift starts after the dip
    grabT.current = Math.min(1, grabT.current + dt / 0.12)
    if (p === 'selected' || p === 'dragging')
      g.scale.setScalar(1 - 0.05 * Math.sin(grabT.current * Math.PI))

    // 2. lift — drops during revert too (so it descends WHILE gliding home)
    const liftTarget = (p === 'reverting' || grabT.current < 0.55) ? 0 : liftHeight
    lift.current = damp(lift.current, liftTarget, 8, dt)

    if (p === 'snapping') {
      snapT.current = Math.min(1, snapT.current + dt / snapDur)
      // single-source lerp from the captured drop pose (includes the lift, so
      // the descent is part of the same curve). Don't ALSO damp — no double-drive.
      g.position.lerpVectors(snapFrom, candidate.point, easeOutCubic(snapT.current))
      if (snapT.current >= 1) { placedT.current = 0; go('placed'); onPlaced?.(candidate) }

    } else if (p === 'placed') {
      placedT.current += dt
      g.position.copy(candidate.point)
      g.scale.setScalar(popScale(placedT.current))
      if (placedT.current > settleDur) {
        g.scale.setScalar(1)
        if (rehome) homeV.copy(candidate.point)   // grab-and-miss now reverts HERE
        proximity.current = 0
        go('idle')
      }

    } else {
      // selected | dragging | reverting — glide XZ toward (blended) intent
      want.copy(p === 'reverting' ? homeV : intent)

      // 6. magnet: hysteresis + proximity-weighted blend of the INTENT
      if (p === 'dragging' && candidate.has && candidate.valid) {
        const d = distXZ(g.position, candidate.point)
        if (!magnetOn.current && d < snapRadius) magnetOn.current = true
        if (magnetOn.current && d > relRadius) magnetOn.current = false
        const w = magnetOn.current
          ? 1 - THREE.MathUtils.smoothstep(d, snapRadius * 0.25, relRadius)
          : 0
        proximity.current = damp(proximity.current, w, 12, dt)
        if (w > 0) {
          want.x += (candidate.point.x - want.x) * w * magnetStrength
          want.z += (candidate.point.z - want.z) * w * magnetStrength
        }
      } else {
        magnetOn.current = false
        proximity.current = damp(proximity.current, 0, 12, dt)
      }

      g.position.x = damp(g.position.x, want.x, 14, dt)
      g.position.z = damp(g.position.z, want.z, 14, dt)
      g.position.y = homeV.y + lift.current

      // revert completes on XZ arrival + lift down — NEVER a 3D check
      // (a 3D distance includes the lift and would wedge the FSM forever)
      if (p === 'reverting' && distXZ(g.position, homeV) < 0.02 && lift.current < 0.01) {
        g.position.copy(homeV)
        g.scale.setScalar(1)
        go('idle')
      }
    }
  })

  const bind = {
    onPointerDown,
    onPointerMove,
    onPointerUp: endDrag,
    onPointerCancel: endDrag,
    onPointerOver: (e) => { e.stopPropagation(); if (phaseRef.current === 'idle') document.body.style.cursor = 'grab' },
    onPointerOut: () => { if (phaseRef.current === 'idle') document.body.style.cursor = 'auto' },
  }
  return { phase, phaseRef, bind, groupRef, candidate, proximity, homeV }
}
```

> **Touch:** set `style={{ touchAction: 'none' }}` on the `<Canvas>` or touch drags
> scroll the page instead of moving the object.

## 3. Stage — glow outline (stage 1)

```jsx
// Child of the mesh you want to glow. thickness is WORLD units (drei default
// 0.05) — a pixel-sized number like 3 inflates the shell into a giant blob.
// For proximity feedback, feed color from phase (blue while carrying) — or
// lerp toward the valid green via a material ref for the per-frame shift.
function GlowOutline({ show, color = '#4ea3ff' }) {
  return show ? <Outlines thickness={0.05} color={color} transparent opacity={0.9} /> : null
}
```

## 4. Stage — flowing path (stage 3)

```jsx
// Travelling beads along a bezier arc — beads alone read as "flow"; the faint
// track line is optional. `anchor` picks the arc start: 'object' (live position,
// fixed-target mode) or 'home' (free-placement: shows the displacement).
// All temps hoisted — zero per-frame allocation.
function FlowPath({ show, anchor = 'object', fromRef, homeV, candidate, color = '#4ea3ff', beads = 5, speed = 2 }) {
  const beadRefs = useRef([])
  const t0 = useRef(0)
  const curve = useRef(new THREE.QuadraticBezierCurve3(
    new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3())).current
  const mid = useRef(new THREE.Vector3()).current

  useFrame((_, dt) => {
    if (!show || !candidate.has) return
    const a = anchor === 'home' ? homeV : fromRef.current?.position
    if (!a) return
    const b = candidate.point
    mid.lerpVectors(a, b, 0.5)
    const len = Math.max(a.distanceTo(b), 0.001)
    mid.y += len * 0.35                                  // arc upward
    curve.v0.copy(a); curve.v1.copy(mid); curve.v2.copy(b)
    t0.current = (t0.current + (dt * speed) / len) % 1   // world-speed, not per-loop
    beadRefs.current.forEach((m, i) => {
      if (!m) return
      const t = (t0.current + i / beads) % 1
      curve.getPoint(t, m.position)
      m.material.opacity = 0.25 + 0.75 * Math.sin(t * Math.PI)  // fade at both ends
    })
  })

  if (!show) return null
  return (
    <group>
      {Array.from({ length: beads }).map((_, i) => (
        <mesh key={i} ref={(r) => (beadRefs.current[i] = r)}>
          <sphereGeometry args={[0.06, 12, 12]} />
          <meshBasicMaterial color={color} transparent toneMapped={false} depthWrite={false} />
        </mesh>
      ))}
    </group>
  )
}
```

## 5. Stage — holographic candidate ring (stage 4)

```jsx
// Follows the live candidate; green = valid, red = invalid. Pulse rate and
// brightness scale with the magnet `proximity` — the user SEES "you're in the
// zone" before releasing. Size from the slot footprint, never hardcoded.
// toneMapped=false keeps it saturated; add selective bloom (or an additive
// gradient sprite underneath) if you want a true halo.
function HoloRing({ show, candidate, proximity, radius = 0.55,
                    validColor = '#37e0a0', invalidColor = '#ff6b6b' }) {
  const root = useRef()
  const spin = useRef()
  const pulse = useRef()
  const t = useRef(0)
  useFrame((_, dt) => {
    if (!show || !root.current) return
    const w = proximity?.current ?? 0
    root.current.visible = candidate.has
    if (!candidate.has) return
    root.current.position.copy(candidate.point)
    root.current.position.y += 0.015                     // z-fighting guard
    const c = candidate.valid ? validColor : invalidColor
    spin.current.material.color.set(c)
    pulse.current.material.color.set(c)
    t.current += dt * (1 + 2.5 * w)                      // pulse speeds up near lock
    spin.current.rotation.z += dt * (1.2 + 2.0 * w)
    const s = 1 + 0.22 * (0.5 + 0.5 * Math.sin(t.current * 3))
    pulse.current.scale.setScalar(s)
    pulse.current.material.opacity = (0.3 + 0.5 * w) * (1 - (s - 1) / 0.22)
  })
  if (!show) return null
  return (
    <group ref={root} rotation-x={-Math.PI / 2}>
      <mesh ref={spin} renderOrder={10}>
        <torusGeometry args={[radius, 0.03, 8, 48]} />
        <meshBasicMaterial toneMapped={false} depthWrite={false} transparent />
      </mesh>
      <mesh ref={pulse} renderOrder={10}>
        <ringGeometry args={[radius, radius * 1.12, 48]} />
        <meshBasicMaterial transparent toneMapped={false} depthWrite={false} side={THREE.DoubleSide} />
      </mesh>
    </group>
  )
}
```

## 6. Stage — success burst: ripple + checkmark (stage 7)

```jsx
// Sequenced to the pop (peak ~0.14s): ripple immediately, check pops in at
// 0.22s, check FADES OUT from 0.65s — the ending resolves, it never hard-cuts.
// Html is non-diegetic (floats over the scene); swap for a sprite in scenes
// with in-fiction screens.
function PlacementBurst({ show, candidate, color = '#37e0a0', settleDur = 0.9 }) {
  const ring = useRef()
  const t = useRef(0)
  const [check, setCheck] = useState(0)   // 0 hidden · 1 in · 2 leaving
  useFrame((_, dt) => {
    if (!show) { t.current = 0; if (check) setCheck(0); return }
    t.current += dt
    if (ring.current) {
      const k = Math.min(1, t.current / 0.55)
      ring.current.scale.setScalar(0.3 + easeOutCubic(k) * 1.7)
      ring.current.material.opacity = Math.max(0, 0.7 * (1 - k))
    }
    if (check === 0 && t.current > 0.22) setCheck(1)
    if (check === 1 && t.current > settleDur - 0.25) setCheck(2)
  })
  if (!show || !candidate.has) return null
  return (
    <group position={candidate.point}>
      <mesh ref={ring} rotation-x={-Math.PI / 2} position-y={0.02} renderOrder={10}>
        <ringGeometry args={[0.4, 0.5, 48]} />
        <meshBasicMaterial color={color} transparent opacity={0.7} toneMapped={false}
                           depthWrite={false} side={THREE.DoubleSide} />
      </mesh>
      {check > 0 && (
        <Html center position={[0, 0.9, 0]} distanceFactor={8} zIndexRange={[10, 0]}>
          <div style={{
            width: 34, height: 34, borderRadius: '50%', background: color,
            display: 'grid', placeItems: 'center', color: '#04140d', fontWeight: 800,
            fontSize: 20, boxShadow: `0 0 16px ${color}`,
            transition: 'transform .2s ease, opacity .2s ease',
            transform: check === 2 ? 'scale(0.6)' : 'scale(1)',
            opacity: check === 2 ? 0 : 1,
            animation: check === 1 ? 'gp-pop .22s cubic-bezier(.2,1.6,.4,1)' : 'none',
          }}>✓</div>
          <style>{`@keyframes gp-pop{from{transform:scale(0)}to{transform:scale(1)}}`}</style>
        </Html>
      )}
    </group>
  )
}
```

## 7. External position owner — fleet/sim-driven objects

When another system writes the object's transform every frame (a robot fleet, physics,
a sim tick), guided placement must **own the transform for the whole gesture** and hand
it back cleanly:

```jsx
// module-level side-channel (same pattern as a robot-api registry)
export const placementDrive = { activeId: null, resetRuntime: null }

// in the OWNER's per-frame writer — yield while guided:
//   if (placementDrive.activeId === robot.id) continue
// and expose a runtime invalidator (owner component):
//   useEffect(() => { placementDrive.resetRuntime = (id) => rt.current.delete(id) }, [])

// in the placement code:
//   on pointer down:  placementDrive.activeId = obj.id   (+ pass driveRef: ownerGroupRef)
//   in onPlaced:      commit to the store, then placementDrive.resetRuntime?.(obj.id)
//                     — the owner re-seeds its cached runtime from the NEW location,
//                     so it resumes writing exactly where the object landed (no snap-back)
//   on settle/revert/unmount:  placementDrive.activeId = null
```

Guard against mid-gesture invalidation with `isStillGrabbable` (e.g. `() =>
store.robots.find(r => r.id === id)?.state === 'IDLE'`) — if the owner dispatches the
object a job mid-drag, the hook aborts into `reverting` on its own.

## 8. Camera framing (stage 5)

```jsx
// Delegate onGrab(box) to your r3f-hero-camera rig, or fall back to raw
// CameraControls. Fires on pointer DOWN (before any movement) — moving the
// camera MID-DRAG shifts the pointer→world mapping and the object slides on
// its own. Skip entirely if both points are already in frustum, and ALWAYS
// skip in an ortho top-down editor view — the user already chose that framing.
//   onGrab: (box) => cam.current?.fitToBox(box, true, { paddingTop: .6, paddingBottom: .6, paddingLeft: .6, paddingRight: .6 })
```

## 9. Default choreography — wire it all

```jsx
export function GuidedPlacement({
  home, policy, onPlaced, onGrab,
  color = '#4ea3ff', ringColor = '#37e0a0', ringRadius = 0.55,
  children,                  // mesh(es); function-children receive (phase)
  ...opts
}) {
  const gp = useGuidedPlacement({ home, policy, onPlaced, onGrab, ...opts })
  const { phase, bind, groupRef, candidate, proximity, homeV } = gp
  const carrying = phase === 'selected' || phase === 'dragging' || phase === 'snapping'

  return (
    <>
      <group ref={groupRef} position={home} {...bind}>
        {typeof children === 'function' ? children(phase) : children}
        <GlowOutline show={carrying} color={color} />
      </group>
      <FlowPath show={phase === 'dragging' || phase === 'snapping'}
                anchor={opts.pathAnchor ?? (policy.mode === 'free' ? 'home' : 'object')}
                fromRef={groupRef} homeV={homeV} candidate={candidate} color={color} />
      <HoloRing show={carrying} candidate={candidate} proximity={proximity}
                radius={ringRadius} validColor={ringColor} />
      <PlacementBurst show={phase === 'placed'} candidate={candidate} color={ringColor}
                      settleDur={opts.settleDur ?? 0.9} />
    </>
  )
}
```

## Minimal usage — fixed target

```jsx
function Demo() {
  const cam = useRef()
  return (
    <>
      <CameraControls ref={cam} makeDefault />
      <GuidedPlacement
        home={[0, 0.25, 0]}
        policy={fixedTarget([4, 0.25, -2])}
        ringRadius={0.6}
        onGrab={(box) => cam.current?.fitToBox(box, true)}
        onPlaced={() => console.log('placed!')}
      >
        {(phase) => (
          <mesh castShadow>
            <boxGeometry args={[0.5, 0.5, 0.5]} />
            <meshStandardMaterial color={phase === 'placed' ? '#37e0a0' : '#c9d4e3'} />
          </mesh>
        )}
      </GuidedPlacement>
    </>
  )
}
```

## Free placement — object-aware (robot on a grid)

```jsx
// A robot may park on ANY valid cell; a bin would use fixedTarget instead.
// The constraint set is the resolve function — nothing else changes.
const robotPolicy = freePlacement((p, out) => {
  const cell = layout.cellAtPoint(p)
  if (!cell) return null
  const [cx, cz] = layout.cellCenter(cell[0], cell[1])
  out.point.set(cx, deckY, cz)
  out.cell = cell
  out.valid = inBounds(cell) && !voidCells.has(key(cell)) && !occupiedByOther(cell)
  return out
})

<GuidedPlacement
  home={[hx, deckY, hz]}
  policy={robotPolicy}
  ringRadius={cellSize * 0.42}
  snapRadius={cellSize * 0.6}
  driveRef={fleetGroupRef}            // fleet owns the transform → see §7
  onPlaced={(c) => { store.relocate(id, ...c.cell); placementDrive.resetRuntime?.(id) }}
  // no onGrab: ortho top view — never move the user's editor camera
/>
```

## Adapting to your app

- **Sim/fleet-owned movers** (a robot, a vehicle): proxy hit-mesh over each grabbable
  object, `driveRef` into the owner's group, the §7 side-channel making the owner yield,
  and `isStillGrabbable` bound to the owner's state (only IDLE objects grab). Validity in
  `resolve` = in-bounds ∧ cell not forbidden ∧ no body-overlap with peers.
- **Item → single slot** (a part into its fixture, a piece onto its square):
  `fixedTarget` on the slot's world center; commit via your store in `onPlaced` so the
  data model matches the visual.
- **Camera**: perspective view → delegate `onGrab` to your `r3f-hero-camera` rig or
  `fitToBox`; ortho top-down editor view → omit `onGrab` entirely.
