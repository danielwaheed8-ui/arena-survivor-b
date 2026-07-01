'use client';

import { useRef } from 'react';
import type { ArenaDef } from '@/lib/types';
import { setupCanvas, useElementSize, useRafLoop } from './canvasHooks';

/** Minimap-style terrain preview for arena cards. */
export function ArenaPreview({ arena, className = '' }: { arena: ArenaDef; className?: string }) {
  const { ref, width, height } = useElementSize<HTMLDivElement>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const tRef = useRef(0);

  useRafLoop((dt) => {
    const ctx = setupCanvas(canvasRef.current, width, height);
    if (!ctx) return;
    tRef.current += dt;
    const t = tRef.current;

    // World bounds
    let minX = Infinity;
    let maxX = -Infinity;
    for (const b of arena.terrain) {
      minX = Math.min(minX, b.x - b.w / 2);
      maxX = Math.max(maxX, b.x + b.w / 2);
    }
    maxX = Math.max(maxX, arena.finish.x + arena.finish.w);
    const worldW = maxX - minX;
    const scale = (width - 24) / worldW;
    const oy = height * 0.72;
    const wy = 620; // typical floor line

    const grad = ctx.createLinearGradient(0, 0, 0, height);
    grad.addColorStop(0, arena.theme.skyTop);
    grad.addColorStop(1, arena.theme.skyBottom);
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, width, height);

    const toX = (x: number) => 12 + (x - minX) * scale;
    const toY = (y: number) => oy + (y - wy) * scale;

    for (const b of arena.terrain) {
      if (b.kind === 'wall') continue;
      ctx.save();
      ctx.translate(toX(b.x), toY(b.y));
      if (b.angle) ctx.rotate(b.angle);
      ctx.fillStyle = arena.theme.terrain;
      ctx.shadowColor = arena.theme.terrainGlow;
      ctx.shadowBlur = 6;
      ctx.fillRect((-b.w / 2) * scale, (-b.h / 2) * scale, b.w * scale, Math.max(2, b.h * scale));
      ctx.restore();
    }
    for (const p of arena.movingPlatforms) {
      const off = Math.sin((t / p.period) * Math.PI * 2);
      ctx.fillStyle = arena.theme.accent;
      ctx.globalAlpha = 0.8;
      ctx.fillRect(
        toX(p.x + p.dx * off) - (p.w * scale) / 2,
        toY(p.y + p.dy * off) - 2,
        p.w * scale,
        3,
      );
      ctx.globalAlpha = 1;
    }
    for (const z of arena.windZones) {
      ctx.fillStyle = 'rgba(96,165,250,0.12)';
      ctx.fillRect(toX(z.x - z.w / 2), toY(z.y - z.h / 2), z.w * scale, z.h * scale);
    }
    for (const z of arena.gravityZones) {
      ctx.fillStyle = 'rgba(232,121,249,0.12)';
      ctx.fillRect(toX(z.x - z.w / 2), toY(z.y - z.h / 2), z.w * scale, z.h * scale);
    }
    // Start + finish markers
    ctx.fillStyle = '#38bdf8';
    ctx.beginPath();
    ctx.arc(toX(arena.start.x), toY(arena.start.y) - 4, 3, 0, Math.PI * 2);
    ctx.fill();
    const pulse = 0.6 + 0.4 * Math.sin(t * 3);
    ctx.strokeStyle = `rgba(74,222,128,${pulse})`;
    ctx.lineWidth = 2;
    ctx.shadowColor = '#4ade80';
    ctx.shadowBlur = 8;
    ctx.beginPath();
    ctx.moveTo(toX(arena.finish.x), toY(arena.finish.y) - 14);
    ctx.lineTo(toX(arena.finish.x), toY(arena.finish.y) + 10);
    ctx.stroke();
    ctx.shadowBlur = 0;
  }, width > 0 && height > 0);

  return (
    <div ref={ref} className={`relative overflow-hidden ${className}`}>
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" data-testid="arena-preview" />
    </div>
  );
}
