import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/globals.css';

// Reduced-motion check runs FIRST before any motion library is touched.
const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// Lazy-init motion only after React has mounted so the DOM is ready.
if (!prefersReducedMotion) {
  import('./lib/canvas').then(({ initCanvas }) => initCanvas());
  import('./lib/cursor').then(({ initCursor }) => initCursor());
  // Motion (Lenis + GSAP) init is deferred further — called inside App
  // after the component tree is painted.
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App reducedMotion={prefersReducedMotion} />
  </React.StrictMode>
);
