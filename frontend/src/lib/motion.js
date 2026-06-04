/**
 * Motion orchestration.
 *
 * Initialises Lenis smooth scroll + syncs it to GSAP's ticker (single
 * RAF loop). Sets up ScrollTrigger-based per-section accent shift.
 * Wires kinetic mask reveals via IntersectionObserver.
 * Wires counter IntersectionObserver.
 */

import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

// Accent colours per section (data-accent attribute on section elements).
const ACCENT_MAP = {
  header:    '#00ff88',
  feed:      '#38bdf8',
  flagged:   '#ef4444',
  histogram: '#a855f7',
  stats:     '#f59e0b',
};

let lenis = null;

export async function initMotion() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  // ── Lenis ──
  try {
    const { default: Lenis } = await import('@studio-freight/lenis');
    lenis = new Lenis({
      duration: 1.2,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)), // exponential
      orientation: 'vertical',
      smoothWheel: true,
    });

    // Single RAF — GSAP ticker drives Lenis, not a separate loop.
    gsap.ticker.add((time) => {
      lenis.raf(time * 1000);
    });
    gsap.ticker.lagSmoothing(0);

    // Keep ScrollTrigger in sync with Lenis scroll position.
    lenis.on('scroll', ScrollTrigger.update);
  } catch {
    // Lenis unavailable — degrade gracefully.
  }

  // ── Section accent shift ──
  setupAccentShift();

  // ── Mask reveals ──
  setupMaskReveals();
}

function setAccent(color) {
  document.documentElement.style.setProperty('--current-accent', color);
}

function setupAccentShift() {
  const sections = document.querySelectorAll('[data-accent]');
  if (!sections.length) return;

  sections.forEach((section) => {
    const accent = ACCENT_MAP[section.dataset.accent] || '#00ff88';
    ScrollTrigger.create({
      trigger: section,
      start: 'top 55%',
      end: 'bottom 45%',
      onEnter: () => setAccent(accent),
      onEnterBack: () => setAccent(accent),
    });
  });
}

function setupMaskReveals() {
  const masks = document.querySelectorAll('.mask-outer');
  if (!masks.length) return;

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('revealed');
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.3 }
  );

  masks.forEach((el) => observer.observe(el));
}

export function destroyMotion() {
  lenis?.destroy();
  ScrollTrigger.getAll().forEach((t) => t.kill());
}
