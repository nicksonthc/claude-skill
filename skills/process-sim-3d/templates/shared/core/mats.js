// Shared materials + procedural canvas textures. Created once, reused across world rebuilds.
// Add project colours here; keep names by role (frame, panel, accent, hot, ok) so components stay generic.
import * as THREE from 'three';

function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}
export function canvasTex(w, h, draw, { repeat, srgb = true, aniso = 8 } = {}) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  draw(c.getContext('2d'), w, h);
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  if (repeat) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(repeat[0], repeat[1]); }
  t.anisotropy = aniso;
  return t;
}
// Text on a plane (signs, plates, floor decals). Headless experiments skip it: no canvas needed there.
export function textTexture(text, { w = 1024, h = 256, bg = null, fg = '#ffffff', font = '700 150px system-ui, -apple-system, "Segoe UI", sans-serif', border = null } = {}) {
  return canvasTex(w, h, (g) => {
    if (bg) { g.fillStyle = bg; g.fillRect(0, 0, w, h); }
    if (border) { g.strokeStyle = border; g.lineWidth = 14; g.strokeRect(7, 7, w - 14, h - 14); }
    g.fillStyle = fg; g.font = font; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText(text, w / 2, h / 2 + 6);
  });
}
export function glowTexture() {
  return canvasTex(128, 128, (g, w, h) => {
    const grd = g.createRadialGradient(w / 2, h / 2, 4, w / 2, h / 2, w / 2);
    grd.addColorStop(0, 'rgba(255,255,255,1)'); grd.addColorStop(0.35, 'rgba(255,255,255,0.55)'); grd.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grd; g.fillRect(0, 0, w, h);
  }, { srgb: false });
}
function floorTexture() {
  return canvasTex(1024, 1024, (g, w, h) => {
    const r = rng(7);
    g.fillStyle = '#9fa6aa'; g.fillRect(0, 0, w, h);
    for (let i = 0; i < 9000; i++) {
      const v = 120 + ((r() * 110) | 0);
      g.fillStyle = `rgba(${v},${v + 4},${v + 6},${0.10 + r() * 0.2})`;
      g.fillRect(r() * w, r() * h, 1 + r() * 1.6, 1 + r() * 1.6);
    }
  }, { repeat: [8, 8] });
}

let cache = null;
export function materials() {
  if (cache) return cache;
  const S = (o) => new THREE.MeshStandardMaterial(o);
  const canDraw = typeof document !== 'undefined';
  cache = {
    paint: S({ color: 0xd9dde0, roughness: 0.48, metalness: 0.05 }),
    skin: S({ color: 0xd9dde0, roughness: 0.48, metalness: 0.05 }), // enclosure panels: glass / solid / hidden toggle
    cabinet: S({ color: 0xcfd3d7, roughness: 0.55, metalness: 0.05 }),
    grey: S({ color: 0x8d949b, roughness: 0.55, metalness: 0.1 }),
    alu: S({ color: 0xc3c7cb, roughness: 0.36, metalness: 0.92 }),
    steel: S({ color: 0x9aa0a6, roughness: 0.3, metalness: 1 }),
    dark: S({ color: 0x2a2c30, roughness: 0.48, metalness: 0.65 }),
    black: S({ color: 0x141517, roughness: 0.6, metalness: 0.1 }),
    rubber: S({ color: 0x1a1a1c, roughness: 0.92 }),
    belt: S({ color: 0x202224, roughness: 0.85 }),
    glass: S({ color: 0xc4dbe6, roughness: 0.04, metalness: 0, transparent: true, opacity: 0.13, depthWrite: false, envMapIntensity: 1.6 }),
    white: S({ color: 0xeff1f2, roughness: 0.42, metalness: 0.05 }),
    accent: S({ color: 0x1d5fbf, roughness: 0.4, metalness: 0.2 }),
    yellow: S({ color: 0xe0bf18, roughness: 0.5, metalness: 0.05 }),
    orange: S({ color: 0xe07a22, roughness: 0.5 }),
    red: S({ color: 0xb3121a, roughness: 0.4, metalness: 0.25 }),
    tray: S({ color: 0x2b2c2f, roughness: 0.72, metalness: 0.05 }),
    part: S({ color: 0x1a8a2b, roughness: 0.5, metalness: 0.05 }),
    partLid: S({ color: 0xb6babe, roughness: 0.36, metalness: 0.9 }),
    done: S({ color: 0x06351a, emissive: 0x1dff6a, emissiveIntensity: 3.4, roughness: 0.4 }),
    robotW: S({ color: 0xeceef0, roughness: 0.32, metalness: 0.05 }),
    skinTone: S({ color: 0xe6d3a2, roughness: 0.75 }),
    coat: S({ color: 0xf3f4f5, roughness: 0.85 }),
    pants: S({ color: 0xe3dab8, roughness: 0.85 }),
    shoe: S({ color: 0x1b1c1f, roughness: 0.7 }),
    tape: S({ color: 0xe2b90f, roughness: 0.6 }),
    zoneIn: S({ color: 0x2d8f5a, roughness: 0.65 }),
    zoneOut: S({ color: 0x2f6fb5, roughness: 0.65 }),
    floor: canDraw ? S({ map: floorTexture(), roughness: 0.9, metalness: 0, envMapIntensity: 0.55 }) : S({ color: 0x9fa6aa, roughness: 0.9 }),
    lampG: S({ color: 0x0c3a17, emissive: 0x25ff6a, emissiveIntensity: 3.2, roughness: 0.4 }),
  };
  cache.glow = canDraw ? glowTexture() : null;
  return cache;
}
