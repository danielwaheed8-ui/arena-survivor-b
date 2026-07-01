'use client';

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
} from 'react';
import { Camera } from '@/lib/camera';
import { SimEngine, type RunEndResult } from '@/lib/engine';
import { NeonRenderer } from '@/lib/render';
import type { ArenaDef, RobotDesign, SimStatus, Telemetry } from '@/lib/types';

export interface StageHandle {
  start: () => void;
  pause: () => void;
  resume: () => void;
  reset: () => void;
  getStatus: () => SimStatus;
}

export interface FrameSample {
  status: SimStatus;
  telemetry: Telemetry;
  batteryFrac: number;
  partActivity: Record<string, number>;
  windActive: boolean;
}

/**
 * Owns the SimEngine lifecycle, the render loop and the camera for one
 * arena+design pair. Controls are exposed imperatively; HUD data flows out
 * through `onSample` at ~10 Hz to keep React re-renders cheap.
 */
export const SimulationStage = forwardRef<
  StageHandle,
  {
    arena: ArenaDef;
    design: RobotDesign;
    speed: number;
    cinematic: boolean;
    onSample?: (sample: FrameSample) => void;
    onRunEnd?: (result: RunEndResult, engine: SimEngine) => void;
    className?: string;
  }
>(function SimulationStage(
  { arena, design, speed, cinematic, onSample, onRunEnd, className = '' },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<SimEngine | null>(null);
  const rendererRef = useRef(new NeonRenderer());
  const cameraRef = useRef(new Camera());
  const speedRef = useRef(speed);
  const cinematicRef = useRef(cinematic);
  const prevCrashes = useRef(0);
  const lastSample = useRef(0);
  const onSampleRef = useRef(onSample);
  const onRunEndRef = useRef(onRunEnd);
  onSampleRef.current = onSample;
  onRunEndRef.current = onRunEnd;
  speedRef.current = speed;
  cinematicRef.current = cinematic;

  // (Re)build engine when arena or design changes.
  useEffect(() => {
    const engine = new SimEngine(arena, design);
    engine.onEnd((result) => onRunEndRef.current?.(result, engine));
    engineRef.current = engine;
    rendererRef.current.reset();
    prevCrashes.current = 0;
    const f = engine.getFrame();
    cameraRef.current.snapTo(f.chassis.x + 120, f.chassis.y - 60, 0.95);
    emitSample(engine);
    return () => {
      engineRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [arena, design]);

  function emitSample(engine: SimEngine): void {
    const frame = engine.getFrame();
    onSampleRef.current?.({
      status: engine.status,
      telemetry: engine.getTelemetry(),
      batteryFrac: frame.batteryFrac,
      partActivity: frame.partActivity,
      windActive: frame.windSample !== null,
    });
  }

  useImperativeHandle(ref, () => ({
    start: () => {
      const e = engineRef.current;
      if (!e) return;
      if (e.isOver()) e.reset();
      e.start();
      emitSample(e);
    },
    pause: () => {
      engineRef.current?.pause();
      if (engineRef.current) emitSample(engineRef.current);
    },
    resume: () => {
      engineRef.current?.resume();
      if (engineRef.current) emitSample(engineRef.current);
    },
    reset: () => {
      const e = engineRef.current;
      if (!e) return;
      e.reset();
      rendererRef.current.reset();
      prevCrashes.current = 0;
      const f = e.getFrame();
      cameraRef.current.snapTo(f.chassis.x + 120, f.chassis.y - 60, cameraRef.current.zoom);
      emitSample(e);
    },
    getStatus: () => engineRef.current?.status ?? 'ready',
  }));

  // Render + step loop.
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;

      const canvas = canvasRef.current;
      const container = containerRef.current;
      const engine = engineRef.current;
      if (!canvas || !container || !engine) return;

      const rect = container.getBoundingClientRect();
      if (rect.width < 2 || rect.height < 2) return;
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const pw = Math.round(rect.width * dpr);
      const ph = Math.round(rect.height * dpr);
      if (canvas.width !== pw || canvas.height !== ph) {
        canvas.width = pw;
        canvas.height = ph;
      }
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      engine.step(dt * 1000, speedRef.current);

      const frame = engine.getFrame();
      const cine = cinematicRef.current;
      const speedPx = Math.hypot(frame.chassis.vx, frame.chassis.vy) * 60;
      const baseZoom = Math.min(1.05, Math.max(0.55, rect.width / 1150));
      cameraRef.current.follow(
        frame.chassis.x + (cine ? 60 : 110),
        frame.chassis.y - (cine ? 30 : 55),
        cine ? undefined : baseZoom,
      );
      cameraRef.current.update(dt, cine, speedPx);

      // Impact shake
      const tel = engine.getTelemetry();
      if (tel.crashes > prevCrashes.current) {
        cameraRef.current.addShake(8);
        prevCrashes.current = tel.crashes;
      }

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
          cinematic: cine,
        },
        cameraRef.current,
        rect.width,
        rect.height,
        dt,
      );

      if (now - lastSample.current > 100) {
        lastSample.current = now;
        emitSample(engine);
      }
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div ref={containerRef} className={`relative overflow-hidden ${className}`}>
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" data-testid="sim-canvas" />
    </div>
  );
});
