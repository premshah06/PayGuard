import { useState, useEffect, useRef } from 'react';

const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

/**
 * Animates a number from 0 → target over duration ms.
 * Triggered by IntersectionObserver at 0.5 threshold (one-shot).
 * Falls back to instant value on prefers-reduced-motion.
 *
 * @param {number} target   Final value
 * @param {number} duration Animation duration in ms (default 1200)
 * @param {number} decimals Decimal places to display
 */
export function useCounter(target, duration = 1200, decimals = 0) {
  const [value, setValue] = useState(0);
  const nodeRef = useRef(null);
  const rafRef = useRef(null);

  useEffect(() => {
    if (target === undefined || target === null) return;

    const node = nodeRef.current;
    if (!node) return;

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setValue(target);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        observer.unobserve(node);

        const start = performance.now();
        const animate = (now) => {
          const elapsed = now - start;
          const progress = Math.min(elapsed / duration, 1);
          const eased = easeOutCubic(progress);
          setValue(parseFloat((target * eased).toFixed(decimals)));
          if (progress < 1) {
            rafRef.current = requestAnimationFrame(animate);
          } else {
            setValue(target);
          }
        };
        rafRef.current = requestAnimationFrame(animate);
      },
      { threshold: 0.5 }
    );

    observer.observe(node);
    return () => {
      observer.disconnect();
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [target, duration, decimals]);

  return { value, nodeRef };
}
