'use client';

import { useEffect, useRef, useState } from 'react';
import { Camera } from '@/lib/camera';
import { getArenaById } from '@/lib/arenas';
import { decodeFrame, lerpFrames } from '@/lib/replay';
import { thrusterFxFromMask } from '@/lib/preview';
import { NeonRenderer } from '@/lib/render';
import type { ReplayData } from '@/lib/types';
import { Button } from './ui';
import { setupCanvas, useElementSize, useRafLoop } from './canvasHooks';

/** Scrubbing playback of a recorded run, rendered with the live-sim renderer. */
export function ReplayViewer({ replay, className = '' }: { replay: ReplayData; className?: string }) {
  const { ref, width, height } = useElementSize<HTMLDivElement>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef(new NeonRenderer());
  const cameraRef = useRef(new Camera());
  const playheadRef = useRef(0);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [scrub, setScrub] = useState(0); // mirrored playhead for the UI

  const arena = getArenaById(replay.arenaId) ?? null;
  const duration = Math.max(0.001, (replay.frames.length - 1) / replay.sampleHz);

  useEffect(() => {
    playheadRef.current = 0;
    setScrub(0);
    setPlaying(true);
    rendererRef.current.reset();
    const first = decodeFrame(replay.frames[0] ?? [], replay.bodies.length);
    if (first.bodies[0]) {
      cameraRef.current.snapTo(first.bodies[0].x + 100, first.bodies[0].y - 50, 0.9);
    }
  }, [replay]);

  useRafLoop((dt) => {
    const ctx = setupCanvas(canvasRef.current, width, height);
    if (!ctx || replay.frames.length === 0) return;

    if (playing) {
      playheadRef.current = Math.max(0, Math.min(duration, playheadRef.current + dt * speed));
      if (playheadRef.current >= duration) setPlaying(false);
      setScrub(playheadRef.current);
    }

    const ft = playheadRef.current * replay.sampleHz;
    const i0 = Math.max(0, Math.min(replay.frames.length - 1, Math.floor(ft)));
    const i1 = Math.min(replay.frames.length - 1, i0 + 1);
    const frac = ft - i0;
    const a = decodeFrame(replay.frames[i0], replay.bodies.length);
    const b = decodeFrame(replay.frames[i1], replay.bodies.length);
    const bodies = lerpFrames(a.bodies, b.bodies, frac);
    const chassis = bodies[0] ?? { x: 0, y: 0, angle: 0 };
    const thrusters = thrusterFxFromMask(replay.design, chassis, a.firingMask);

    const baseZoom = Math.min(1.0, Math.max(0.55, width / 1150));
    cameraRef.current.follow(chassis.x + 90, chassis.y - 50, baseZoom);
    cameraRef.current.update(dt, false, 0);

    rendererRef.current.render(
      ctx,
      {
        arena,
        design: replay.design,
        bodies,
        descs: replay.bodies,
        thrusters,
        t: playheadRef.current,
        batteryFrac: 1,
      },
      cameraRef.current,
      width,
      height,
      dt,
    );
  }, width > 0 && height > 0);

  return (
    <div className="flex h-full flex-col">
      <div ref={ref} className={`relative flex-1 overflow-hidden ${className}`}>
        <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" data-testid="replay-canvas" />
        <div className="pointer-events-none absolute left-3 top-3 rounded-md border border-white/10 bg-black/50 px-2.5 py-1 backdrop-blur">
          <span className="hud-label">Replay · {replay.robotName}</span>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-3" data-testid="replay-controls">
        <Button
          size="sm"
          onClick={() => {
            if (!playing && playheadRef.current >= duration) {
              playheadRef.current = 0;
              setScrub(0);
            }
            setPlaying(!playing);
          }}
          className="min-w-[84px]"
          data-testid="replay-play"
        >
          {playing ? '❚❚ Pause' : '▶ Play'}
        </Button>
        <input
          type="range"
          className="flex-1"
          min={0}
          max={duration}
          step={0.01}
          value={scrub}
          style={{ ['--fill' as string]: `${(scrub / duration) * 100}%` }}
          onChange={(e) => {
            const v = Number(e.target.value);
            playheadRef.current = v;
            setScrub(v);
            setPlaying(false);
          }}
          data-testid="replay-scrub"
        />
        <span className="mono-value w-24 text-right text-xs text-slate-400">
          {scrub.toFixed(1)}s / {duration.toFixed(1)}s
        </span>
        <div className="flex gap-1">
          {[0.5, 1, 2].map((s) => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                speed === s ? 'bg-neon-cyan/25 text-cyan-100' : 'text-slate-500 hover:text-white'
              }`}
            >
              {s}×
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
