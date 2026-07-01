'use client';

import { useEffect, useRef } from 'react';
import { getArenaById } from '@/lib/arenas';
import { Camera } from '@/lib/camera';
import { SimEngine } from '@/lib/engine';
import { PRESET_ROBOTS } from '@/lib/robots';
import { NeonRenderer } from '@/lib/render';
import { setupCanvas, useElementSize, useRafLoop } from './canvasHooks';

/**
 * Self-running demo simulation for the landing hero: cycles preset robots
 * through the First Drive arena, restarting whenever a run ends.
 */
export function HeroSim({ className = '' }: { className?: string }) {
  const { ref, width, height } = useElementSize<HTMLDivElement>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<SimEngine | null>(null);
  const rendererRef = useRef(new NeonRenderer());
  const cameraRef = useRef(new Camera());
  const presetIdx = useRef(0);
  const restartAt = useRef<number | null>(null);

  useEffect(() => {
    const arena = getArenaById('first-drive')!;
    const engine = new SimEngine(arena, PRESET_ROBOTS[0]);
    engine.start();
    engineRef.current = engine;
    const frame = engine.getFrame();
    cameraRef.current.snapTo(frame.chassis.x + 140, frame.chassis.y - 40, 1.1);
    return () => {
      engineRef.current = null;
    };
  }, []);

  useRafLoop((dt) => {
    const ctx = setupCanvas(canvasRef.current, width, height);
    const engine = engineRef.current;
    if (!ctx || !engine) return;

    engine.step(dt * 1000, 1);

    if (engine.isOver()) {
      if (restartAt.current === null) {
        restartAt.current = performance.now() + 1400;
      } else if (performance.now() > restartAt.current) {
        presetIdx.current = (presetIdx.current + 1) % PRESET_ROBOTS.length;
        const arena = getArenaById('first-drive')!;
        const next = new SimEngine(arena, PRESET_ROBOTS[presetIdx.current]);
        next.start();
        engineRef.current = next;
        rendererRef.current.reset();
        const f = next.getFrame();
        cameraRef.current.snapTo(f.chassis.x + 140, f.chassis.y - 40, 1.1);
        restartAt.current = null;
        return;
      }
    }

    const frame = engine.getFrame();
    const speed = Math.hypot(frame.chassis.vx, frame.chassis.vy) * 60;
    cameraRef.current.follow(frame.chassis.x + 120, frame.chassis.y - 50, Math.min(1.15, width / 900));
    cameraRef.current.update(dt, true, speed);

    rendererRef.current.render(
      ctx,
      {
        arena: engine.arena,
        design: engine.design,
        bodies: frame.bodies,
        descs: engine.getBodyDescs(),
        thrusters: frame.thrusters,
        t: frame.t,
        batteryFrac: frame.batteryFrac,
        cinematic: true,
      },
      cameraRef.current,
      width,
      height,
      dt,
    );
  }, width > 0 && height > 0);

  return (
    <div ref={ref} className={`relative overflow-hidden ${className}`}>
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" data-testid="hero-sim" />
    </div>
  );
}
