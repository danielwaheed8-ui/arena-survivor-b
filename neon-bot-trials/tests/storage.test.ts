import { describe, expect, it } from 'vitest';
import { cloneDesign, createEmptyRobot, PRESET_ROBOTS } from '@/lib/robots';
import {
  bestRuns,
  createMemoryStore,
  deleteRobot,
  deleteRun,
  getRobotById,
  loadDraft,
  loadReplay,
  loadRobots,
  loadRuns,
  MAX_SAVED_ROBOTS,
  saveDraft,
  saveReplay,
  saveRobot,
  saveRun,
} from '@/lib/storage';
import type { ReplayData, RunRecord } from '@/lib/types';

function makeRun(id: string, arenaId: string, total: number, hasReplay = false): RunRecord {
  return {
    id,
    arenaId,
    robotName: 'Test Bot',
    robotId: 'bot-1',
    date: 1700000000000,
    telemetry: {
      t: 12,
      distance: 500,
      maxX: 640,
      progress: 0.4,
      energyUsed: 20,
      batteryCapacity: 150,
      flips: 0,
      crashes: 0,
      avgTilt: 0.1,
      completed: false,
      failed: true,
      failReason: 'test',
    },
    score: {
      completionPoints: total,
      timeBonus: 0,
      stabilityBonus: 0,
      energyBonus: 0,
      flipPenalty: 0,
      crashPenalty: 0,
      total,
      grade: 'C',
    },
    hasReplay,
  };
}

function makeReplay(runId: string): ReplayData {
  return {
    version: 1,
    runId,
    arenaId: 'first-drive',
    robotName: 'Test Bot',
    design: PRESET_ROBOTS[0],
    bodies: [{ role: 'chassis', shape: 'rect', w: 80, h: 28, r: 0, hue: 190 }],
    frames: [[100, 200, 0, 0], [110, 200, 5, 1]],
    sampleHz: 30,
    duration: 0.066,
  };
}

describe('robot persistence', () => {
  it('saves, loads, updates and deletes robots', () => {
    const store = createMemoryStore();
    const robot = cloneDesign(PRESET_ROBOTS[0], 'Saver');
    expect(saveRobot(robot, store).ok).toBe(true);
    expect(loadRobots(store)).toHaveLength(1);
    expect(getRobotById(robot.id, store)?.name).toBe('Saver');

    // Update in place, not duplicate
    expect(saveRobot({ ...robot, name: 'Saver v2' }, store).ok).toBe(true);
    const robots = loadRobots(store);
    expect(robots).toHaveLength(1);
    expect(robots[0].name).toBe('Saver v2');

    deleteRobot(robot.id, store);
    expect(loadRobots(store)).toHaveLength(0);
  });

  it('rejects invalid designs', () => {
    const store = createMemoryStore();
    const bad = createEmptyRobot('Bad');
    (bad as { chassis: { width: number; height: number } }).chassis.width = 100000;
    // normalizeDesign is not applied on save of invalid raw data
    const result = saveRobot(bad, store);
    expect(result.ok).toBe(false);
    expect(loadRobots(store)).toHaveLength(0);
  });

  it('drops corrupted storage payloads instead of throwing', () => {
    const store = createMemoryStore();
    store.setItem('nbt:robots', '{not json');
    expect(loadRobots(store)).toEqual([]);
    store.setItem('nbt:robots', JSON.stringify([{ hello: 'world' }, null, 42]));
    expect(loadRobots(store)).toEqual([]);
  });

  it('caps the garage size', () => {
    const store = createMemoryStore();
    for (let i = 0; i < MAX_SAVED_ROBOTS + 5; i++) {
      saveRobot(cloneDesign(PRESET_ROBOTS[0], `Bot ${i}`), store);
    }
    expect(loadRobots(store).length).toBe(MAX_SAVED_ROBOTS);
  });

  it('persists and restores the builder draft', () => {
    const store = createMemoryStore();
    expect(loadDraft(store)).toBeNull();
    const draft = cloneDesign(PRESET_ROBOTS[1], 'WIP');
    saveDraft(draft, store);
    expect(loadDraft(store)?.name).toBe('WIP');
  });
});

describe('run + replay persistence', () => {
  it('saves runs and ranks best per arena', () => {
    const store = createMemoryStore();
    saveRun(makeRun('r1', 'first-drive', 300), store);
    saveRun(makeRun('r2', 'first-drive', 900), store);
    saveRun(makeRun('r3', 'ramp-lab', 500), store);
    expect(loadRuns(store)).toHaveLength(3);
    const best = bestRuns(store);
    expect(best.get('first-drive')?.id).toBe('r2');
    expect(best.get('ramp-lab')?.id).toBe('r3');
  });

  it('stores and validates replays', () => {
    const store = createMemoryStore();
    saveRun(makeRun('r1', 'first-drive', 100, true), store);
    expect(saveReplay(makeReplay('r1'), store)).toBe(true);
    const loaded = loadReplay('r1', store);
    expect(loaded).not.toBeNull();
    expect(loaded!.frames).toHaveLength(2);
    expect(loadReplay('missing', store)).toBeNull();
  });

  it('rejects malformed replay payloads on load', () => {
    const store = createMemoryStore();
    store.setItem('nbt:replay:evil', JSON.stringify({ version: 1, frames: 'nope' }));
    expect(loadReplay('evil', store)).toBeNull();
  });

  it('deleting a run also deletes its replay', () => {
    const store = createMemoryStore();
    saveRun(makeRun('r1', 'first-drive', 100, true), store);
    saveReplay(makeReplay('r1'), store);
    deleteRun('r1', store);
    expect(loadRuns(store)).toHaveLength(0);
    expect(loadReplay('r1', store)).toBeNull();
  });
});
