import { describe, expect, it } from 'vitest';
import { ARENAS, arenaProgress, DEFAULT_ARENA_ID, getArenaById, validateArena } from '@/lib/arenas';

describe('arena definitions', () => {
  it('ships at least six arenas', () => {
    expect(ARENAS.length).toBeGreaterThanOrEqual(6);
  });

  it('has unique ids and resolvable lookups', () => {
    const ids = ARENAS.map((a) => a.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) {
      expect(getArenaById(id)?.id).toBe(id);
    }
    expect(getArenaById('nonexistent')).toBeUndefined();
    expect(getArenaById(DEFAULT_ARENA_ID)).toBeDefined();
  });

  it('every arena passes structural validation', () => {
    for (const arena of ARENAS) {
      const result = validateArena(arena);
      expect(result.errors, `${arena.id}: ${result.errors.join(', ')}`).toEqual([]);
    }
  });

  it('every arena declares the required gameplay metadata', () => {
    for (const arena of ARENAS) {
      expect(arena.name.length).toBeGreaterThan(0);
      expect(arena.objective.length).toBeGreaterThan(10);
      expect(arena.hint.length).toBeGreaterThan(10);
      expect(arena.difficulty).toBeGreaterThanOrEqual(1);
      expect(arena.difficulty).toBeLessThanOrEqual(5);
      expect(arena.timeLimit).toBeGreaterThan(0);
      expect(arena.finish.x).toBeGreaterThan(arena.start.x);
      expect(arena.killY).toBeGreaterThan(arena.start.y);
    }
  });

  it('covers all required hazard mechanics across the set', () => {
    expect(ARENAS.some((a) => a.windZones.length > 0)).toBe(true);
    expect(ARENAS.some((a) => a.gravityZones.length > 0)).toBe(true);
    expect(ARENAS.some((a) => a.movingPlatforms.length > 0)).toBe(true);
    expect(ARENAS.some((a) => a.seesaws.length > 0)).toBe(true);
    expect(ARENAS.some((a) => a.terrain.some((t) => (t.angle ?? 0) !== 0))).toBe(true);
    expect(ARENAS.some((a) => a.terrain.some((t) => (t.restitution ?? 0) > 1))).toBe(true);
  });

  it('computes course progress correctly', () => {
    const arena = ARENAS[0];
    expect(arenaProgress(arena, arena.start.x)).toBe(0);
    expect(arenaProgress(arena, arena.finish.x)).toBe(1);
    expect(arenaProgress(arena, arena.start.x - 500)).toBe(0);
    expect(arenaProgress(arena, arena.finish.x + 500)).toBe(1);
    const mid = arenaProgress(arena, (arena.start.x + arena.finish.x) / 2);
    expect(mid).toBeGreaterThan(0.45);
    expect(mid).toBeLessThan(0.55);
  });

  it('flags broken arena data', () => {
    const broken = {
      ...ARENAS[0],
      terrain: [],
      finish: { x: 0, y: 0, w: 10, h: 10 },
    };
    const result = validateArena(broken);
    expect(result.ok).toBe(false);
    expect(result.errors.length).toBeGreaterThanOrEqual(2);
  });
});
