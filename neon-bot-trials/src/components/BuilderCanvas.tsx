'use client';

import { useCallback, useEffect, useRef } from 'react';
import { Camera } from '@/lib/camera';
import { PART_CATALOG } from '@/lib/parts';
import { designRadius, staticFrameFromDesign } from '@/lib/preview';
import { NeonRenderer } from '@/lib/render';
import type { PartType, RobotDesign } from '@/lib/types';
import { setupCanvas, useElementSize, useRafLoop } from './canvasHooks';

export type BuilderMode = { kind: 'select' } | { kind: 'place'; type: PartType };

const HIT_RADIUS = 16;

/**
 * Interactive assembly canvas. Click to place the armed part, click a part's
 * anchor to select it, drag to reposition. All edits flow through callbacks —
 * this component never owns design state.
 */
export function BuilderCanvas({
  design,
  mode,
  selectedId,
  onPlace,
  onSelect,
  onMovePart,
  className = '',
}: {
  design: RobotDesign;
  mode: BuilderMode;
  selectedId: string | null;
  onPlace: (x: number, y: number) => void;
  onSelect: (partId: string | null) => void;
  onMovePart: (partId: string, x: number, y: number) => void;
  className?: string;
}) {
  const { ref, width, height } = useElementSize<HTMLDivElement>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef(new NeonRenderer());
  const cameraRef = useRef(new Camera());
  const tRef = useRef(0);
  const cursorRef = useRef<{ x: number; y: number } | null>(null);
  const dragRef = useRef<{ partId: string; moved: boolean } | null>(null);

  const toWorld = useCallback(
    (clientX: number, clientY: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return { x: 0, y: 0 };
      const rect = canvas.getBoundingClientRect();
      return cameraRef.current.screenToWorld(
        clientX - rect.left,
        clientY - rect.top,
        rect.width,
        rect.height,
      );
    },
    [],
  );

  const hitTest = useCallback(
    (wx: number, wy: number): string | null => {
      let bestId: string | null = null;
      let bestDist = HIT_RADIUS;
      for (const p of design.parts) {
        const d = Math.hypot(p.anchor.x - wx, p.anchor.y - wy);
        if (d < bestDist) {
          bestDist = d;
          bestId = p.id;
        }
      }
      return bestId;
    },
    [design],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const onPointerDown = (e: PointerEvent) => {
      const w = toWorld(e.clientX, e.clientY);
      if (mode.kind === 'place') {
        onPlace(w.x, w.y);
        return;
      }
      const hit = hitTest(w.x, w.y);
      if (hit) {
        onSelect(hit);
        dragRef.current = { partId: hit, moved: false };
        canvas.setPointerCapture(e.pointerId);
      } else {
        onSelect(null);
      }
    };
    const onPointerMove = (e: PointerEvent) => {
      const w = toWorld(e.clientX, e.clientY);
      cursorRef.current = w;
      if (dragRef.current) {
        dragRef.current.moved = true;
        onMovePart(dragRef.current.partId, w.x, w.y);
      }
    };
    const onPointerUp = (e: PointerEvent) => {
      dragRef.current = null;
      if (canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
    };
    const onLeave = () => {
      cursorRef.current = null;
    };

    canvas.addEventListener('pointerdown', onPointerDown);
    canvas.addEventListener('pointermove', onPointerMove);
    canvas.addEventListener('pointerup', onPointerUp);
    canvas.addEventListener('pointerleave', onLeave);
    return () => {
      canvas.removeEventListener('pointerdown', onPointerDown);
      canvas.removeEventListener('pointermove', onPointerMove);
      canvas.removeEventListener('pointerup', onPointerUp);
      canvas.removeEventListener('pointerleave', onLeave);
    };
  }, [mode, onPlace, onSelect, onMovePart, toWorld, hitTest]);

  useRafLoop((dt) => {
    const ctx = setupCanvas(canvasRef.current, width, height);
    if (!ctx) return;
    tRef.current += dt;

    const radius = Math.max(90, designRadius(design));
    const zoom = Math.min(width, height) / (radius * 2.7);
    cameraRef.current.snapTo(0, 10, zoom);

    const { bodies, descs } = staticFrameFromDesign(design, 0, 0);
    rendererRef.current.render(
      ctx,
      { arena: null, design, bodies, descs, thrusters: [], t: tRef.current, batteryFrac: 1 },
      cameraRef.current,
      width,
      height,
      dt,
    );

    // Overlay: anchor markers, selection ring, placement ghost
    cameraRef.current.applyTo(ctx, width, height);

    // Attachment envelope
    const maxX = design.chassis.width / 2 + 10;
    const maxY = design.chassis.height / 2 + 14;
    ctx.strokeStyle = 'rgba(148,163,184,0.18)';
    ctx.setLineDash([5, 5]);
    ctx.lineWidth = 1;
    ctx.strokeRect(-maxX, -maxY, maxX * 2, maxY * 2);
    ctx.setLineDash([]);

    for (const p of design.parts) {
      const sel = p.id === selectedId;
      ctx.strokeStyle = sel ? 'rgba(34,211,238,0.95)' : 'rgba(148,163,184,0.5)';
      ctx.lineWidth = sel ? 2 : 1;
      if (sel) {
        ctx.shadowColor = '#22d3ee';
        ctx.shadowBlur = 10;
      }
      ctx.beginPath();
      ctx.arc(p.anchor.x, p.anchor.y, sel ? 9 : 6, 0, Math.PI * 2);
      ctx.stroke();
      ctx.shadowBlur = 0;
      ctx.beginPath();
      ctx.moveTo(p.anchor.x - 3, p.anchor.y);
      ctx.lineTo(p.anchor.x + 3, p.anchor.y);
      ctx.moveTo(p.anchor.x, p.anchor.y - 3);
      ctx.lineTo(p.anchor.x, p.anchor.y + 3);
      ctx.stroke();
    }

    if (mode.kind === 'place' && cursorRef.current) {
      const c = cursorRef.current;
      const cx = Math.max(-maxX, Math.min(maxX, c.x));
      const cy = Math.max(-maxY, Math.min(maxY, c.y));
      ctx.strokeStyle = 'rgba(232,121,249,0.9)';
      ctx.shadowColor = '#e879f9';
      ctx.shadowBlur = 12;
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.arc(cx, cy, 10, 0, Math.PI * 2);
      ctx.stroke();
      ctx.shadowBlur = 0;
      ctx.fillStyle = 'rgba(232,121,249,0.95)';
      ctx.font = '10px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(PART_CATALOG[mode.type].label.toUpperCase(), cx, cy - 16);
    }
  }, width > 0 && height > 0);

  return (
    <div ref={ref} className={`relative overflow-hidden ${className}`}>
      <canvas
        ref={canvasRef}
        className={`absolute inset-0 h-full w-full ${mode.kind === 'place' ? 'cursor-crosshair' : 'cursor-default'}`}
        data-testid="builder-canvas"
      />
    </div>
  );
}
