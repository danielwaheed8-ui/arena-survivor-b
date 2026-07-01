'use client';

import { useEffect, useRef } from 'react';
import { Camera } from '@/lib/camera';
import { designRadius, staticFrameFromDesign } from '@/lib/preview';
import { NeonRenderer } from '@/lib/render';
import type { RobotDesign } from '@/lib/types';
import { setupCanvas, useElementSize, useRafLoop } from './canvasHooks';

/**
 * Static (gently animated) rest-pose preview of a robot design.
 * Used in the garage, results modal, and landing feature cards.
 */
export function RobotPreview({
  design,
  className = '',
  animate = true,
}: {
  design: RobotDesign;
  className?: string;
  animate?: boolean;
}) {
  const { ref, width, height } = useElementSize<HTMLDivElement>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef(new NeonRenderer());
  const cameraRef = useRef(new Camera());
  const tRef = useRef(0);

  useEffect(() => {
    rendererRef.current.reset();
  }, [design]);

  useRafLoop((dt) => {
    const ctx = setupCanvas(canvasRef.current, width, height);
    if (!ctx) return;
    tRef.current += dt;
    const { bodies, descs } = staticFrameFromDesign(design, 0, 0);
    const radius = designRadius(design);
    const zoom = Math.min(width, height) / (radius * 2.6);
    cameraRef.current.snapTo(0, 6, zoom);
    rendererRef.current.render(
      ctx,
      {
        arena: null,
        design,
        bodies,
        descs,
        thrusters: [],
        t: animate ? tRef.current : 0,
        batteryFrac: 1,
      },
      cameraRef.current,
      width,
      height,
      dt,
    );
  }, width > 0 && height > 0);

  return (
    <div ref={ref} className={`relative overflow-hidden ${className}`}>
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" data-testid="robot-preview" />
    </div>
  );
}
