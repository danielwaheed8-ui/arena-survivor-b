'use client';

import { useEffect, useRef, useState, type RefObject } from 'react';

/** Tracks an element's CSS pixel size via ResizeObserver. */
export function useElementSize<T extends HTMLElement>(): {
  ref: RefObject<T>;
  width: number;
  height: number;
} {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const rect = el.getBoundingClientRect();
      setSize((prev) =>
        prev.width !== rect.width || prev.height !== rect.height
          ? { width: rect.width, height: rect.height }
          : prev,
      );
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return { ref, width: size.width, height: size.height };
}

/**
 * Prepares a canvas 2D context at device-pixel-ratio resolution.
 * Returns null until the canvas is mounted and sized.
 */
export function setupCanvas(
  canvas: HTMLCanvasElement | null,
  cssW: number,
  cssH: number,
): CanvasRenderingContext2D | null {
  if (!canvas || cssW <= 0 || cssH <= 0) return null;
  const dpr = Math.min(2, typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1);
  const pw = Math.round(cssW * dpr);
  const ph = Math.round(cssH * dpr);
  if (canvas.width !== pw || canvas.height !== ph) {
    canvas.width = pw;
    canvas.height = ph;
  }
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

/** requestAnimationFrame loop with delta seconds, auto-cleanup. */
export function useRafLoop(callback: (dt: number) => void, active = true): void {
  const cbRef = useRef(callback);
  cbRef.current = callback;

  useEffect(() => {
    if (!active) return;
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      // Re-arm BEFORE the callback so an exception can't kill the loop, and
      // clamp dt ≥ 0 — the first rAF timestamp can precede performance.now().
      raf = requestAnimationFrame(loop);
      const dt = Math.max(0, Math.min(0.1, (now - last) / 1000));
      last = now;
      cbRef.current(dt);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [active]);
}
