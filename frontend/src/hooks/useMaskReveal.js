import { useEffect, useRef } from 'react';

/**
 * Attaches kinetic mask-reveal IntersectionObserver to a container ref.
 * All .mask-outer children inside the container are observed.
 * Threshold 0.3 — triggers when 30% of the element is visible.
 * One-shot: unobserves after revealing.
 */
export function useMaskReveal(deps = []) {
  const ref = useRef(null);

  useEffect(() => {
    const container = ref.current;
    if (!container) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      // Instantly reveal all masks.
      container.querySelectorAll('.mask-outer').forEach((el) => {
        el.classList.add('revealed');
      });
      return;
    }

    const masks = container.querySelectorAll('.mask-outer');
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
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return ref;
}
