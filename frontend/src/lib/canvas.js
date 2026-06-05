/**
 * BackgroundCanvas — sparse drifting geometric primitives.
 *
 * Density: ~1 shape per 20,000px² (halved on mobile).
 * Cursor repulsion within 140px (smooth falloff).
 * Drift velocity decays at 0.985 per frame.
 * Shapes wrap at edges.
 * Strokes read --current-accent live each frame.
 */

const REPULSION_RADIUS = 140;
const REPULSION_RADIUS_SQ = REPULSION_RADIUS * REPULSION_RADIUS;
const DECAY = 0.985;
const DENSITY = 20_000; // px² per shape
const MOBILE_BREAKPOINT = 1100;

let shapes = [];
let canvas, ctx;
let rafId = null;
let cursor = { x: -9999, y: -9999 };
let isMobile = false;
let cachedAccent = '#00ff88';
let lastAccentCheck = 0;

function readAccent() {
  const now = performance.now();
  // Cache accent for 200ms to avoid getComputedStyle every frame.
  if (now - lastAccentCheck > 200) {
    lastAccentCheck = now;
    cachedAccent = getComputedStyle(document.documentElement)
      .getPropertyValue('--current-accent')
      .trim() || '#00ff88';
  }
  return cachedAccent;
}

function makeShape(w, h) {
  const type = ['triangle', 'circle', 'hexagon'][Math.floor(Math.random() * 3)];
  const size = 6 + Math.random() * 14;
  return {
    type,
    x: Math.random() * w,
    y: Math.random() * h,
    vx: (Math.random() - 0.5) * 0.4,
    vy: (Math.random() - 0.5) * 0.4,
    size,
    alpha: 0.06 + Math.random() * 0.1,
    rot: Math.random() * Math.PI * 2,
    vrot: (Math.random() - 0.5) * 0.002,
  };
}

function buildShapes(w, h) {
  const count = Math.min(Math.round((w * h) / DENSITY) / (isMobile ? 2 : 1), 80);
  shapes = Array.from({ length: count }, () => makeShape(w, h));
}

function drawTriangle(ctx, s) {
  const r = s.size;
  ctx.beginPath();
  ctx.moveTo(0, -r);
  ctx.lineTo(r * 0.866, r * 0.5);
  ctx.lineTo(-r * 0.866, r * 0.5);
  ctx.closePath();
  ctx.stroke();
}

function drawHexagon(ctx, s) {
  const r = s.size;
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const a = (Math.PI / 3) * i - Math.PI / 6;
    i === 0 ? ctx.moveTo(Math.cos(a) * r, Math.sin(a) * r)
            : ctx.lineTo(Math.cos(a) * r, Math.sin(a) * r);
  }
  ctx.closePath();
  ctx.stroke();
}

function frame() {
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const accent = readAccent();

  for (const s of shapes) {
    // Cursor repulsion — squared-distance check before sqrt.
    const dx = s.x - cursor.x;
    const dy = s.y - cursor.y;
    const distSq = dx * dx + dy * dy;

    if (!isMobile && distSq < REPULSION_RADIUS_SQ) {
      const dist = Math.sqrt(distSq);
      const strength = (REPULSION_RADIUS - dist) / REPULSION_RADIUS;
      s.vx += (dx / dist) * strength * 0.6;
      s.vy += (dy / dist) * strength * 0.6;
    }

    // Velocity decay
    s.vx *= DECAY;
    s.vy *= DECAY;
    s.vrot *= DECAY;

    // Position update
    s.x += s.vx;
    s.y += s.vy;
    s.rot += s.vrot;

    // Edge wrap
    if (s.x < -s.size * 2) s.x = w + s.size;
    if (s.x > w + s.size * 2) s.x = -s.size;
    if (s.y < -s.size * 2) s.y = h + s.size;
    if (s.y > h + s.size * 2) s.y = -s.size;

    // Draw
    ctx.save();
    ctx.translate(s.x, s.y);
    ctx.rotate(s.rot);
    ctx.globalAlpha = s.alpha * 0.6;   // even more subtle on light bg
    ctx.strokeStyle = accent;
    ctx.lineWidth = 1.0;

    if (s.type === 'circle') {
      ctx.beginPath();
      ctx.arc(0, 0, s.size, 0, Math.PI * 2);
      ctx.stroke();
    } else if (s.type === 'triangle') {
      drawTriangle(ctx, s);
    } else {
      drawHexagon(ctx, s);
    }

    ctx.restore();
  }

  rafId = requestAnimationFrame(frame);
}

function resize() {
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const w = window.innerWidth;
  const h = window.innerHeight;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;
  ctx.scale(dpr, dpr);
  isMobile = w < MOBILE_BREAKPOINT;
  buildShapes(w, h);
}

let resizeTimer;
function debouncedResize() {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(resize, 150);
}

export function initCanvas() {
  // Skip if reduced motion is preferred.
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  canvas = document.getElementById('pg-canvas-bg');
  if (!canvas) return;
  ctx = canvas.getContext('2d');

  isMobile = window.innerWidth < MOBILE_BREAKPOINT;
  resize();

  window.addEventListener('mousemove', (e) => {
    cursor.x = e.clientX;
    cursor.y = e.clientY;
  });

  // Touch — cursor repulsion disabled on touch, just track for completeness.
  window.addEventListener('touchmove', (e) => {
    const t = e.touches[0];
    cursor.x = t.clientX;
    cursor.y = t.clientY;
  }, { passive: true });

  window.addEventListener('resize', debouncedResize);

  rafId = requestAnimationFrame(frame);
}

export function destroyCanvas() {
  if (rafId) cancelAnimationFrame(rafId);
  window.removeEventListener('resize', debouncedResize);
}
