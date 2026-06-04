import { useEffect, useRef } from 'react';

/**
 * Applies magnetic cursor pull to a button/element.
 * Strength 0.4 — element translates toward cursor at 40% of offset.
 * Returns to rest via springy cubic-bezier(0.34, 1.56, 0.64, 1) on mouseleave.
 *
 * Skips on touch devices and reduced-motion.
 */
export function useMagnetic(strength = 0.4) {
  const ref = useRef(null);

  useEffect(() => {
    if (window.matchMedia('(pointer: coarse)').matches) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    const el = ref.current;
    if (!el) return;

    const onMove = (e) => {
      const rect = el.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = e.clientX - cx;
      const dy = e.clientY - cy;
      el.style.transition = 'transform 100ms ease';
      el.style.willChange = 'transform';
      el.style.transform = `translate3d(${dx * strength}px, ${dy * strength}px, 0)`;
    };

    const onLeave = () => {
      el.style.transition = 'transform 400ms cubic-bezier(0.34, 1.56, 0.64, 1)';
      el.style.transform = 'translate3d(0, 0, 0)';
      // Clean up will-change after spring settles.
      setTimeout(() => { el.style.willChange = 'auto'; }, 420);
    };

    el.addEventListener('mousemove', onMove);
    el.addEventListener('mouseleave', onLeave);
    return () => {
      el.removeEventListener('mousemove', onMove);
      el.removeEventListener('mouseleave', onLeave);
    };
  }, [strength]);

  return ref;
}
