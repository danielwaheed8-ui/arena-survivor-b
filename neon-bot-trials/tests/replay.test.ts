import { describe, expect, it } from 'vitest';
import { getArenaById } from '@/lib/arenas';
import { SimEngine } from '@/lib/engine';
import { decodeFrame, encodeFrame, lerpFrames, REPLAY_SAMPLE_HZ, validateReplay } from '@/lib/replay';
import { PRESET_ROBOTS } from '@/lib/robots';

describe('replay codec', () => {
  it('round-trips body transforms within quantization tolerance', () => {
    const bodies = [
      { x: 512.34, y: -20.7, angle: 2.5 },
      { x: 0.04, y: 640, angle: -0.001 },
    ];
    const { bodies: decoded, firingMask } = decodeFrame(encodeFrame(bodies, 0b11), 2);
    expect(firingMask).toBe(3);
    for (let i = 0; i < bodies.length; i++) {
      expect(decoded[i].x).toBeCloseTo(bodies[i].x, 1);
      expect(decoded[i].y).toBeCloseTo(bodies[i].y, 1);
      expect(decoded[i].angle).toBeCloseTo(bodies[i].angle, 2);
    }
  });

  it('interpolates between frames, taking the short way around angles', () => {
    const a = [{ x: 0, y: 0, angle: Math.PI - 0.1 }];
    const b = [{ x: 10, y: 20, angle: -Math.PI + 0.1 }];
    const mid = lerpFrames(a, b, 0.5);
    expect(mid[0].x).toBeCloseTo(5);
    expect(mid[0].y).toBeCloseTo(10);
    // Short path crosses π, not zero
    expect(Math.abs(mid[0].angle)).toBeGreaterThan(3);
  });

  it('records replay frames during a live engine run', () => {
    const engine = new SimEngine(getArenaById('first-drive')!, PRESET_ROBOTS[0]);
    const shortArena = { ...getArenaById('first-drive')!, timeLimit: 2, id: 'short' };
    const e = new SimEngine(shortArena, PRESET_ROBOTS[0]);
    let frames: number[][] = [];
    let bodyCount = 0;
    e.onEnd((result) => {
      frames = result.replayFrames;
      bodyCount = result.replayBodies.length;
    });
    e.start();
    for (let i = 0; i < 200 && !e.isOver(); i++) e.tick();
    expect(frames.length).toBeGreaterThan(REPLAY_SAMPLE_HZ); // >1s of samples
    expect(frames[0].length).toBe(bodyCount * 3 + 1);
    // Decoded first frame chassis should be near the spawn
    const first = decodeFrame(frames[0], bodyCount);
    expect(first.bodies[0].x).toBeGreaterThan(0);
    expect(first.bodies[0].x).toBeLessThan(600);
    expect(engine.status).toBe('ready'); // untouched control engine
  });

  it('validates replay payload structure', () => {
    expect(validateReplay(null)).toBe(false);
    expect(validateReplay({ version: 1 })).toBe(false);
    const valid = {
      version: 1,
      runId: 'r1',
      arenaId: 'first-drive',
      robotName: 'X',
      design: PRESET_ROBOTS[0],
      bodies: [{ role: 'chassis', shape: 'rect', w: 10, h: 10, r: 0, hue: 0 }],
      frames: [[1, 2, 3, 0]],
      sampleHz: 30,
      duration: 1,
    };
    expect(validateReplay(valid)).toBe(true);
    expect(validateReplay({ ...valid, frames: [[1, 2]] })).toBe(false);
  });
});
