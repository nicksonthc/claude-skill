# Interactive 3D Object — Reference

Copy-paste building blocks. Stack: R3F 8, drei 9, three 0.169. State examples
use zustand; any store with a snapshot getter works.

## 1. `tokens.js` — the feel, in one file

```js
// One source of truth for the interaction layer's colors, motion timings and
// easing. Every FX component reads from here so the "feel" stays coherent and
// tunable from a single file — flip SELECT to blue, retime the whole system.

export const STATUS_COLORS = {
  RUNNING: '#37d67a', // green — moving / working normally
  WARNING: '#ff9d42', // orange — busy at a delicate step
  ALARM:   '#ff4d4f', // red — fault / needs attention
  OFFLINE: '#8a929e', // gray — powered down / unavailable
  NEUTRAL: '#e8edf4', // white — idle, nothing to report
}

// Selection accents: one color for "one", another for "many".
export const SELECT = '#ff9d42'       // single-select (brand accent)
export const SELECT_MULTI = '#4aa3ff' // multi-select + relationship links
export const HOVER = '#bcd4ff'        // soft hover ring (cool white-blue)

// Motion timings (ms). Durations feed one-shot eases; rateFor() converts them
// into per-frame damping rates so useFrame smoothing matches declared timing.
export const TIMING = {
  HOVER: 120,
  SELECT: 250,
  CAMERA: 750,        // cinematic window is 600–900ms
  TOOLTIP_DELAY: 200, // hover intent delay
  RIPPLE: 520,        // one-shot ground ripple on click
}

export const HOVER_SCALE = 1.03 // subtle lift if you also scale the object

// Ground selection ring geometry + breathing.
export const RING = {
  innerRadius: 0.62,  // × object footprint radius
  outerRadius: 0.78,
  spawnScale: 0.4,    // ring expands from this → 1 on select
  breathAmp: 0.14,    // opacity breathing amplitude
  breathHz: 0.5,
  baseOpacity: 0.6,
  busySpinRate: 1.2,  // rad/s while WARNING/busy
}

// ── Easing / smoothing ──────────────────────────────────────────────────────
export const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x)
export const easeOutCubic = (t) => 1 - Math.pow(1 - clamp01(t), 3)
export function easeOutBack(t, s = 1.70158) {
  const x = clamp01(t) - 1
  return 1 + (s + 1) * x * x * x + s * x * x
}
// Frame-rate-independent exponential approach: lerp current→target by damp(rate, dt).
export const damp = (rate, dt) => 1 - Math.exp(-rate * dt)
// Token duration (ms) → decay rate reaching ~95% in that duration.
export const rateFor = (ms) => 3000 / ms
```

## 2. `status.js` — the meaning, as a pure function

```js
import { STATUS_COLORS } from './tokens.js'

// Map any interactive object → a status token. Pure function of a state
// snapshot — no subscriptions, safe inside useFrame. Every visual reads it.
export function objectStatus(kind, id, snap) {
  if (kind === 'robot') {
    const r = snap.robots.find((x) => x.id === id)
    if (!r) return { status: 'OFFLINE', label: 'Offline' } // stale id ≠ running
    const MAP = { IDLE: 'NEUTRAL', MOVING: 'RUNNING', LIFTING: 'WARNING', FAULT: 'ALARM' }
    return { status: MAP[r.state] ?? 'NEUTRAL', label: r.state }
  }
  // ...one branch per kind in your domain
  return { status: 'NEUTRAL', label: '' }
}

export const statusColor = (kind, id, snap) => STATUS_COLORS[objectStatus(kind, id, snap).status]
// "Busy" statuses spin + warm the ring.
export const isBusyStatus = (status) => status === 'WARNING'
```

## 3. `ObjectFX.jsx` — the geometry-agnostic overlay

```jsx
import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import {
  STATUS_COLORS, SELECT, SELECT_MULTI, HOVER, RING, TIMING,
  clamp01, easeOutCubic, easeOutBack, damp, rateFor,
} from './tokens.js'
import { isBusyStatus } from './status.js'

// Soft radial glow texture, built once and shared across every instance —
// a composer-free stand-in for a bloom pass.
let GLOW_TEX = null
function glowTexture() {
  if (GLOW_TEX) return GLOW_TEX
  const c = document.createElement('canvas')
  c.width = c.height = 128
  const ctx = c.getContext('2d')
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64)
  g.addColorStop(0, 'rgba(255,255,255,0.9)')
  g.addColorStop(0.35, 'rgba(255,255,255,0.35)')
  g.addColorStop(1, 'rgba(255,255,255,0)')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, 128, 128)
  GLOW_TEX = new THREE.CanvasTexture(c)
  GLOW_TEX.colorSpace = THREE.SRGBColorSpace
  return GLOW_TEX
}

// Mount as a child of any interactive object's group, at its footprint center.
// All FX animate in ONE useFrame via envelope tweens in refs — zero per-frame
// React state. Props: hovered, selected, multi, status (STATUS_COLORS key),
// label, radius (footprint), groundY (ring height), labelY (label height).
export default function ObjectFX({
  hovered = false, selected = false, multi = false,
  status = 'NEUTRAL', label = '',
  radius = 0.5, groundY = 0.03, labelY = 1.4, glowY,
}) {
  const selRing = useRef(), selMat = useRef()
  const hovRing = useRef(), hovMat = useRef()
  const ripple = useRef(), rippleMat = useRef()
  const glow = useRef(), glowMat = useRef()
  const burst = useRef(), burstMat = useRef()
  const labelRef = useRef()
  const glowCenter = glowY ?? labelY * 0.42

  // Burst particle buffers: stable typed arrays so the GPU attribute never
  // reallocates.
  const BURST_N = 16
  const burstPos = useMemo(() => new Float32Array(BURST_N * 3), [])
  const burstVel = useMemo(() => new Float32Array(BURST_N * 3), [])

  // Envelope clocks. sel/hov ramp 0→1 and back; ripple/burst are one-shots
  // re-armed on the select rising edge.
  const t = useRef({ sel: 0, lab: 0, hov: 0, ripple: 1, wasSelected: false, spin: 0 })

  const statusHex = STATUS_COLORS[status] ?? STATUS_COLORS.NEUTRAL
  const busy = isBusyStatus(status)
  const active = selected || multi
  const accent = multi && !selected ? SELECT_MULTI
    : statusHex === STATUS_COLORS.NEUTRAL ? SELECT : statusHex

  useFrame((_, dtRaw) => {
    const dt = Math.min(dtRaw, 0.05) // clamp tab-switch frames
    const s = t.current

    // Rising edge of selection → re-arm ripple + burst.
    if (selected && !s.wasSelected) {
      s.ripple = 0
      s.burst = 0
      for (let i = 0; i < BURST_N; i++) {
        burstPos.set([0, 0, 0], i * 3)
        const ang = (i / BURST_N) * Math.PI * 2 + Math.random() * 0.5
        const sp = 0.8 + Math.random() * 1.1
        burstVel[i * 3] = Math.cos(ang) * sp
        burstVel[i * 3 + 1] = 1.4 + Math.random() * 1.6 // pop upward
        burstVel[i * 3 + 2] = Math.sin(ang) * sp
      }
      if (burst.current) burst.current.geometry.attributes.position.needsUpdate = true
    }
    s.wasSelected = selected

    // Ease envelopes toward their targets (frame-rate independent).
    s.sel = clamp01(s.sel + ((active ? 1 : 0) - s.sel) * damp(rateFor(TIMING.SELECT), dt))
    s.lab = clamp01(s.lab + ((selected ? 1 : 0) - s.lab) * damp(rateFor(TIMING.SELECT), dt))
    s.hov = clamp01(s.hov + ((hovered ? 1 : 0) - s.hov) * damp(rateFor(TIMING.HOVER), dt))

    // SELECT ring: spawn-expand with overshoot, breathe, spin while busy.
    if (selRing.current && selMat.current) {
      const grow = RING.spawnScale + (1 - RING.spawnScale) * easeOutBack(s.sel)
      selRing.current.scale.setScalar(grow)
      s.spin += dt * (busy ? RING.busySpinRate : 0)
      selRing.current.rotation.z = s.spin
      s.clock = (s.clock ?? 0) + dt
      const breath = 1 + RING.breathAmp * Math.sin(s.clock * RING.breathHz * Math.PI * 2)
      selMat.current.opacity = RING.baseOpacity * s.sel * breath
      selMat.current.color.set(accent)
      selRing.current.visible = s.sel > 0.01
    }

    // HOVER ring: quick fade, hands over to the select ring (× (1 − sel)).
    if (hovMat.current && hovRing.current) {
      const h = s.hov * (1 - s.sel)
      hovMat.current.opacity = 0.5 * h
      hovRing.current.visible = h > 0.01
    }

    // RIPPLE: single 0→1 shot — scale out + fade.
    if (s.ripple < 1) {
      s.ripple = clamp01(s.ripple + dt * (1000 / TIMING.RIPPLE))
      if (ripple.current && rippleMat.current) {
        const e = easeOutCubic(s.ripple)
        ripple.current.scale.setScalar(0.6 + e * 1.9)
        rippleMat.current.opacity = 0.55 * (1 - e)
        ripple.current.visible = true
      }
    } else if (ripple.current) ripple.current.visible = false

    // GLOW halo: brightens on hover, blooms on select, breathes while busy.
    if (glow.current && glowMat.current) {
      const env = Math.max(s.hov * 0.5, s.sel)
      const breath = busy ? 1 + 0.12 * Math.sin((s.clock ?? 0) * RING.breathHz * Math.PI * 2) : 1
      glowMat.current.opacity = 0.6 * env * breath
      const scl = radius * (2.4 + s.sel * 0.9)
      glow.current.scale.set(scl, scl, scl)
      glowMat.current.color.set(accent)
      glow.current.visible = env > 0.01
    }

    // BURST: integrate outward + gravity, fade over ~600ms.
    if (s.burst != null && s.burst < 1 && burst.current && burstMat.current) {
      s.burst = clamp01(s.burst + dt / 0.6)
      for (let i = 0; i < BURST_N; i++) {
        burstVel[i * 3 + 1] -= 4.5 * dt // gravity
        burstPos[i * 3]     += burstVel[i * 3] * dt * radius
        burstPos[i * 3 + 1] += burstVel[i * 3 + 1] * dt * radius
        burstPos[i * 3 + 2] += burstVel[i * 3 + 2] * dt * radius
      }
      burst.current.geometry.attributes.position.needsUpdate = true
      burstMat.current.opacity = 1 - easeOutCubic(s.burst)
      burstMat.current.color.set(accent)
      burst.current.visible = true
    } else if (burst.current && s.burst >= 1) burst.current.visible = false

    // Label fades/slides in on single-select only.
    if (labelRef.current) {
      labelRef.current.style.opacity = String(easeOutCubic(s.lab))
      labelRef.current.style.transform = `translateY(${(1 - s.lab) * 6}px)`
    }
  })

  return (
    <group>
      {/* GLOW halo — additive billboard, composer-free bloom stand-in */}
      <sprite ref={glow} position={[0, glowCenter, 0]} visible={false}>
        <spriteMaterial ref={glowMat} map={glowTexture()} transparent opacity={0}
          depthWrite={false} blending={THREE.AdditiveBlending} toneMapped={false} />
      </sprite>

      {/* Select particle burst */}
      <points ref={burst} position={[0, groundY + radius * 0.4, 0]} visible={false}>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" count={BURST_N} array={burstPos} itemSize={3} />
        </bufferGeometry>
        <pointsMaterial ref={burstMat} size={radius * 0.16} sizeAttenuation transparent
          opacity={0} depthWrite={false} toneMapped={false} blending={THREE.AdditiveBlending} />
      </points>

      {/* HOVER ring */}
      <mesh ref={hovRing} rotation={[-Math.PI / 2, 0, 0]} position={[0, groundY, 0]} visible={false}>
        <ringGeometry args={[radius * 0.9, radius * 1.02, 48]} />
        <meshBasicMaterial ref={hovMat} color={HOVER} transparent opacity={0}
          depthWrite={false} toneMapped={false} />
      </mesh>

      {/* SELECT ring */}
      <mesh ref={selRing} rotation={[-Math.PI / 2, 0, 0]} position={[0, groundY, 0]} visible={false}>
        <ringGeometry args={[radius * RING.innerRadius, radius * RING.outerRadius, 64]} />
        <meshBasicMaterial ref={selMat} color={SELECT} transparent opacity={0}
          depthWrite={false} toneMapped={false} />
      </mesh>

      {/* CLICK ripple */}
      <mesh ref={ripple} rotation={[-Math.PI / 2, 0, 0]} position={[0, groundY, 0]} visible={false}>
        <ringGeometry args={[radius * 0.7, radius * 0.86, 48]} />
        <meshBasicMaterial ref={rippleMat} color={SELECT} transparent opacity={0}
          depthWrite={false} toneMapped={false} />
      </mesh>

      {/* Floating name label — constant screen size; NEVER interactive */}
      {label && (
        <Html position={[0, labelY, 0]} center pointerEvents="none" zIndexRange={[20, 0]}>
          <div ref={labelRef} className="fx-label" style={{ opacity: 0 }}>
            <span className="fx-label__dot" style={{ background: statusHex }} />
            {label}
          </div>
        </Html>
      )}
    </group>
  )
}
```

## 4. Wiring an object

```jsx
function Robot({ robotId, selected, onSelect }) {
  // Subscribe NARROWLY: this robot's hover flag + its own state, not the whole
  // hover object — or every pointer move re-renders the entire fleet.
  const hovered = useStore((s) => s.hovered?.kind === 'robot' && s.hovered.id === robotId)
  const multi = useStore((s) => s.multiSelectIds.includes(robotId))
  const state = useStore((s) => s.robots.find((r) => r.id === robotId)?.state)
  const setHovered = useStore((s) => s.setHovered)
  const { status } = objectStatus('robot', robotId, { robots: [{ id: robotId, state }] })

  return (
    <group
      onClick={(e) => { e.stopPropagation(); onSelect?.(robotId) }}
      onPointerOver={(e) => {
        e.stopPropagation()
        document.body.style.cursor = 'pointer'
        setHovered({ kind: 'robot', id: robotId })
      }}
      onPointerOut={() => {
        document.body.style.cursor = 'auto'
        setHovered(null)
      }}
    >
      {/* ...the object's own meshes... */}
      <ObjectFX
        hovered={hovered} selected={selected} multi={multi} status={status}
        label={`Robot #${robotId}`}
        radius={footprintRadius}         // from the object's REAL footprint
        labelY={objectHeight + 0.5}
      />
    </group>
  )
}
```

Store shape (zustand): `hovered: {kind, id} | null` in ONE shared slot — a
single source of truth survives fast pointer jumps between adjacent objects.

## 5. `HoverTooltip.jsx` — one scene-level instance

```jsx
import { useEffect, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import { objectStatus } from './status.js'
import { STATUS_COLORS, TIMING } from './tokens.js'

// One instance in the scene. Reads the shared hover slot; after TOOLTIP_DELAY
// of continuous hover shows a card anchored beside the object; a single
// useFrame keeps the anchor glued even while the object moves.
// You supply: anchorFor(kind, id, snap) → [x, y, z] | null (the object's live
// upper area) and rowsFor(kind, id, snap) → [[key, value], ...].
export default function HoverTooltip({ anchorFor, rowsFor, titleFor }) {
  const hovered = useStore((s) => s.hovered)
  const groupRef = useRef()
  const [shown, setShown] = useState(false)

  // Intent delay: re-arms on every hover change, so flicking across a crowd
  // shows nothing.
  useEffect(() => {
    setShown(false)
    if (!hovered) return
    const t = setTimeout(() => setShown(true), TIMING.TOOLTIP_DELAY)
    return () => clearTimeout(t)
  }, [hovered?.kind, hovered?.id])

  // Glue the anchor to the (possibly moving) object every frame.
  useFrame(() => {
    if (!hovered || !groupRef.current) return
    const a = anchorFor(hovered.kind, hovered.id, useStore.getState())
    if (a) groupRef.current.position.set(a[0], a[1], a[2])
    groupRef.current.visible = !!a
  })

  if (!hovered || !shown) return null
  const snap = useStore.getState()
  const { status, label } = objectStatus(hovered.kind, hovered.id, snap)
  const color = STATUS_COLORS[status]

  return (
    <group ref={groupRef}>
      <Html pointerEvents="none" zIndexRange={[30, 0]}
        style={{ transform: 'translate(16px, -50%)' }}>
        <div className="fx-tooltip">
          <div className="fx-tooltip__title">
            <span className="fx-tooltip__dot" style={{ background: color }} />
            {titleFor(hovered.kind, hovered.id)}
          </div>
          <div className="fx-tooltip__row"><span>Status</span><span style={{ color }}>{label}</span></div>
          {rowsFor(hovered.kind, hovered.id, snap).map(([k, v]) => (
            <div key={k} className="fx-tooltip__row"><span>{k}</span><span>{v}</span></div>
          ))}
        </div>
      </Html>
    </group>
  )
}
```

## 6. `useActionPreview.js` — telegraph before commit

```js
// "Show me what this verb would do before I click it." A HUD/menu button
// spreads these handlers; hovering writes a transient intent into the store;
// in-scene consumers (path overlays, ObjectFX, ghosts) read it to telegraph
// the effect. Falsy intent → no-op handlers, so callers spread unconditionally.
export function useActionPreview(intent) {
  const setPreviewIntent = useStore((s) => s.setPreviewIntent)
  if (!intent) return {}
  return {
    onPointerEnter: () => setPreviewIntent(intent),
    onPointerLeave: () => setPreviewIntent(null),
    // Clear on click too — the action commits, a lingering preview is stale UI.
    onClick: () => setPreviewIntent(null),
  }
}
// Intent shapes are yours, e.g. { kind: 'path', robotId } → a route overlay.
```

## 7. X-ray / ghost materials

```jsx
// GLTF materials are shared across clones — mutating one ghosts EVERY
// instance. Clone per mesh, stash the original, restore + dispose after.
useEffect(() => {
  root.traverse((o) => {
    if (!o.isMesh) return
    if (xray) {
      if (!o.userData.solidMat) {
        o.userData.solidMat = o.material
        const ghost = o.material.clone()
        ghost.transparent = true
        ghost.opacity = 0.15
        ghost.depthWrite = false
        o.material = ghost
      }
    } else if (o.userData.solidMat) {
      o.material.dispose()
      o.material = o.userData.solidMat
      delete o.userData.solidMat
    }
  })
}, [xray, root])
```

## 8. CSS for the Html pieces

```css
.fx-label {
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(16, 20, 28, 0.78);
  border: 1px solid rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(6px);
  color: #e8edf4;
  font: 600 11px/1.6 system-ui, sans-serif;
  white-space: nowrap;
  display: flex; align-items: center; gap: 6px;
  transition: none; /* ObjectFX drives opacity/transform per frame */
}
.fx-label__dot { width: 7px; height: 7px; border-radius: 50%; }

.fx-tooltip {
  min-width: 168px;
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(16, 20, 28, 0.86);
  border: 1px solid rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(8px);
  color: #e8edf4;
  font: 500 11px/1.7 system-ui, sans-serif;
}
.fx-tooltip__title { font-weight: 700; display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.fx-tooltip__dot { width: 7px; height: 7px; border-radius: 50%; }
.fx-tooltip__row { display: flex; justify-content: space-between; gap: 16px; opacity: 0.9; }
.fx-tooltip__row span:first-child { opacity: 0.6; }
```
