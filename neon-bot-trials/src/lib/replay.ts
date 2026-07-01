import type { DrawBodyDesc, ReplayData, ReplayFrame } from './types';

/**
 * Replay frames store [x*10, y*10, angle*1000] per dynamic body (ints), with a
 * trailing thruster-firing bitmask. Quantized to keep localStorage small.
 */

export const REPLAY_SAMPLE_HZ = 30;

export interface DecodedBody {
  x: number;
  y: number;
  angle: number;
}

export function encodeFrame(
  bodies: Array<{ x: number; y: number; angle: number }>,
  firingMask: number,
): ReplayFrame {
  const frame: number[] = new Array(bodies.length * 3 + 1);
  for (let i = 0; i < bodies.length; i++) {
    frame[i * 3] = Math.round(bodies[i].x * 10);
    frame[i * 3 + 1] = Math.round(bodies[i].y * 10);
    frame[i * 3 + 2] = Math.round(bodies[i].angle * 1000);
  }
  frame[bodies.length * 3] = firingMask;
  return frame;
}

export function decodeFrame(frame: ReplayFrame, bodyCount: number): { bodies: DecodedBody[]; firingMask: number } {
  const bodies: DecodedBody[] = new Array(bodyCount);
  for (let i = 0; i < bodyCount; i++) {
    bodies[i] = {
      x: (frame[i * 3] ?? 0) / 10,
      y: (frame[i * 3 + 1] ?? 0) / 10,
      angle: (frame[i * 3 + 2] ?? 0) / 1000,
    };
  }
  return { bodies, firingMask: frame[bodyCount * 3] ?? 0 };
}

/** Linear interpolation between two decoded frames for smooth playback. */
export function lerpFrames(a: DecodedBody[], b: DecodedBody[], t: number): DecodedBody[] {
  const out: DecodedBody[] = new Array(a.length);
  for (let i = 0; i < a.length; i++) {
    const bb = b[i] ?? a[i];
    out[i] = {
      x: a[i].x + (bb.x - a[i].x) * t,
      y: a[i].y + (bb.y - a[i].y) * t,
      angle: a[i].angle + shortestAngle(a[i].angle, bb.angle) * t,
    };
  }
  return out;
}

function shortestAngle(from: number, to: number): number {
  let d = (to - from) % (Math.PI * 2);
  if (d > Math.PI) d -= Math.PI * 2;
  if (d < -Math.PI) d += Math.PI * 2;
  return d;
}

export function validateReplay(input: unknown): input is ReplayData {
  const r = input as Partial<ReplayData> | null;
  if (!r || typeof r !== 'object') return false;
  if (r.version !== 1) return false;
  if (typeof r.runId !== 'string' || typeof r.arenaId !== 'string') return false;
  if (!Array.isArray(r.bodies) || !Array.isArray(r.frames)) return false;
  if (typeof r.sampleHz !== 'number' || r.sampleHz <= 0) return false;
  if (!r.design || typeof r.design !== 'object') return false;
  const stride = (r.bodies as DrawBodyDesc[]).length * 3 + 1;
  return (r.frames as ReplayFrame[]).every((f) => Array.isArray(f) && f.length === stride);
}
