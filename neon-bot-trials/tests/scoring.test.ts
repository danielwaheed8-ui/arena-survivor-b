import { describe, expect, it } from 'vitest';
import { ARENAS } from '@/lib/arenas';
import { computeScore, gradeFor } from '@/lib/scoring';
import type { Telemetry } from '@/lib/types';

const arena = ARENAS[0];

function tel(overrides: Partial<Telemetry> = {}): Telemetry {
  return {
    t: 30,
    distance: 1000,
    maxX: 1140,
    progress: 0.5,
    energyUsed: 60,
    batteryCapacity: 150,
    flips: 0,
    crashes: 0,
    avgTilt: 0.15,
    completed: false,
    failed: false,
    ...overrides,
  };
}

describe('scoring', () => {
  it('rewards completion far above partial progress', () => {
    const done = computeScore(tel({ completed: true, progress: 1 }), arena);
    const half = computeScore(tel({ progress: 0.5 }), arena);
    expect(done.total).toBeGreaterThan(half.total + 300);
    expect(done.completionPoints).toBe(1000);
    expect(half.completionPoints).toBe(300);
  });

  it('grants time bonus only on completion, scaled by speed', () => {
    const fast = computeScore(tel({ completed: true, t: arena.timeLimit * 0.2 }), arena);
    const slow = computeScore(tel({ completed: true, t: arena.timeLimit * 0.9 }), arena);
    const dnf = computeScore(tel({ t: 10 }), arena);
    expect(fast.timeBonus).toBeGreaterThan(slow.timeBonus);
    expect(dnf.timeBonus).toBe(0);
  });

  it('penalizes flips and crashes with caps', () => {
    const clean = computeScore(tel(), arena);
    const messy = computeScore(tel({ flips: 3, crashes: 5 }), arena);
    expect(messy.total).toBeLessThan(clean.total);
    expect(messy.flipPenalty).toBe(120);
    const chaos = computeScore(tel({ flips: 100, crashes: 100 }), arena);
    expect(chaos.flipPenalty).toBe(200);
    expect(chaos.crashPenalty).toBe(150);
  });

  it('rewards stability and energy efficiency', () => {
    const stable = computeScore(tel({ avgTilt: 0.02 }), arena);
    const wobbly = computeScore(tel({ avgTilt: 0.7 }), arena);
    expect(stable.stabilityBonus).toBeGreaterThan(wobbly.stabilityBonus);

    const thrifty = computeScore(tel({ energyUsed: 10 }), arena);
    const hungry = computeScore(tel({ energyUsed: 150 }), arena);
    expect(thrifty.energyBonus).toBeGreaterThan(hungry.energyBonus);
    expect(hungry.energyBonus).toBe(0);
  });

  it('never returns a negative total', () => {
    const disaster = computeScore(
      tel({ progress: 0, flips: 50, crashes: 50, avgTilt: 3, energyUsed: 400 }),
      arena,
    );
    expect(disaster.total).toBe(0);
  });

  it('is deterministic', () => {
    const t = tel({ completed: true, progress: 1 });
    expect(computeScore(t, arena)).toEqual(computeScore(t, arena));
  });

  it('assigns grades on sensible boundaries', () => {
    expect(gradeFor(1600, true)).toBe('S');
    expect(gradeFor(1300, true)).toBe('A');
    expect(gradeFor(1100, true)).toBe('B');
    expect(gradeFor(600, false)).toBe('B');
    expect(gradeFor(300, false)).toBe('C');
    expect(gradeFor(100, false)).toBe('D');
  });
});
