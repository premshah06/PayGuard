/**
 * Custom cursor — 6px filled dot + 64px lagging ring.
 *
 * Dot: direct style.transform writes on mousemove — zero lag.
 * Ring: 0.15 lerp factor in one requestAnimationFrame loop.
 * Ring grows on :hover over interactive elements.
 * Falls back to native cursor on (pointer: coarse) or reduced-motion.
 */

const LERP = 0.15;

let dot, ring;
let mouseX = -9999, mouseY = -9999;
let ringX = -9999, ringY = -9999;
let rafId = null;
let hovering = false;

const INTERACTIVE = 'a, button, [role="button"], input, select, textarea, label, .mag-btn, .pg-tab';

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function tick() {
  ringX = lerp(ringX, mouseX, LERP);
  ringY = lerp(ringY, mouseY, LERP);
  ring.style.transform = `translate3d(${ringX}px, ${ringY}px, 0)`;
  rafId = requestAnimationFrame(tick);
}

export function initCursor() {
  // Skip on touch devices or reduced motion.
  if (window.matchMedia('(pointer: coarse)').matches) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  dot = document.getElementById('pg-cursor-dot');
  ring = document.getElementById('pg-cursor-ring');
  if (!dot || !ring) return;

  document.addEventListener('mousemove', (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;
    // Dot is written directly — no lerp, no RAF delay.
    dot.style.transform = `translate3d(${mouseX}px, ${mouseY}px, 0)`;
  });

  // Interactive hover: grow ring.
  document.addEventListener('mouseover', (e) => {
    if (e.target.closest(INTERACTIVE)) {
      hovering = true;
      ring.classList.add('hover');
    }
  });
  document.addEventListener('mouseout', (e) => {
    if (e.target.closest(INTERACTIVE)) {
      hovering = false;
      ring.classList.remove('hover');
    }
  });

  rafId = requestAnimationFrame(tick);
}

export function destroyCursor() {
  if (rafId) cancelAnimationFrame(rafId);
}
