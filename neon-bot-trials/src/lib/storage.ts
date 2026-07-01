import { normalizeDesign, validateDesign } from './robots';
import { validateReplay } from './replay';
import type { ReplayData, RobotDesign, RunRecord } from './types';

/**
 * localStorage persistence. All keys are namespaced under `nbt:`.
 * Every read validates and repairs; corrupted entries are dropped, never thrown.
 * A storage backend can be injected for tests (Node has no localStorage).
 */

export interface KVStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
  key(index: number): string | null;
  readonly length: number;
}

const KEYS = {
  robots: 'nbt:robots',
  runs: 'nbt:runs',
  draft: 'nbt:draft',
  replayPrefix: 'nbt:replay:',
};

export const MAX_SAVED_ROBOTS = 24;
export const MAX_RUNS = 100;
export const MAX_REPLAYS = 10;

function defaultStore(): KVStore | null {
  if (typeof window === 'undefined' || !window.localStorage) return null;
  return window.localStorage;
}

function readJson<T>(store: KVStore, key: string): T | null {
  try {
    const raw = store.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function writeJson(store: KVStore, key: string, value: unknown): boolean {
  try {
    store.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false; // quota exceeded or storage disabled
  }
}

// ---------------------------------------------------------------------------
// Robots
// ---------------------------------------------------------------------------

export function loadRobots(store: KVStore | null = defaultStore()): RobotDesign[] {
  if (!store) return [];
  const list = readJson<unknown[]>(store, KEYS.robots);
  if (!Array.isArray(list)) return [];
  const robots: RobotDesign[] = [];
  for (const item of list) {
    if (validateDesign(item).ok) robots.push(normalizeDesign(item as RobotDesign));
  }
  return robots;
}

export function saveRobot(
  design: RobotDesign,
  store: KVStore | null = defaultStore(),
): { ok: boolean; error?: string } {
  if (!store) return { ok: false, error: 'Storage unavailable.' };
  const check = validateDesign(design);
  if (!check.ok) return { ok: false, error: check.errors.join(' ') };
  const robots = loadRobots(store);
  const idx = robots.findIndex((r) => r.id === design.id);
  const clean = normalizeDesign({ ...design, updatedAt: Date.now() });
  if (idx >= 0) robots[idx] = clean;
  else robots.unshift(clean);
  const trimmed = robots.slice(0, MAX_SAVED_ROBOTS);
  return writeJson(store, KEYS.robots, trimmed)
    ? { ok: true }
    : { ok: false, error: 'Storage is full.' };
}

export function deleteRobot(id: string, store: KVStore | null = defaultStore()): void {
  if (!store) return;
  const robots = loadRobots(store).filter((r) => r.id !== id);
  writeJson(store, KEYS.robots, robots);
}

export function getRobotById(id: string, store: KVStore | null = defaultStore()): RobotDesign | undefined {
  return loadRobots(store).find((r) => r.id === id);
}

// ---------------------------------------------------------------------------
// Builder draft (auto-persisted work in progress)
// ---------------------------------------------------------------------------

export function saveDraft(design: RobotDesign, store: KVStore | null = defaultStore()): void {
  if (!store) return;
  writeJson(store, KEYS.draft, design);
}

export function loadDraft(store: KVStore | null = defaultStore()): RobotDesign | null {
  if (!store) return null;
  const raw = readJson<unknown>(store, KEYS.draft);
  if (!raw || !validateDesign(raw).ok) return null;
  return normalizeDesign(raw as RobotDesign);
}

// ---------------------------------------------------------------------------
// Runs (leaderboard)
// ---------------------------------------------------------------------------

function isRunRecord(v: unknown): v is RunRecord {
  const r = v as Partial<RunRecord> | null;
  return Boolean(
    r &&
      typeof r === 'object' &&
      typeof r.id === 'string' &&
      typeof r.arenaId === 'string' &&
      typeof r.robotName === 'string' &&
      typeof r.date === 'number' &&
      r.telemetry &&
      typeof r.telemetry.t === 'number' &&
      r.score &&
      typeof r.score.total === 'number',
  );
}

export function loadRuns(store: KVStore | null = defaultStore()): RunRecord[] {
  if (!store) return [];
  const list = readJson<unknown[]>(store, KEYS.runs);
  if (!Array.isArray(list)) return [];
  return list.filter(isRunRecord);
}

export function saveRun(run: RunRecord, store: KVStore | null = defaultStore()): boolean {
  if (!store) return false;
  const runs = loadRuns(store);
  runs.unshift(run);
  return writeJson(store, KEYS.runs, runs.slice(0, MAX_RUNS));
}

export function deleteRun(id: string, store: KVStore | null = defaultStore()): void {
  if (!store) return;
  writeJson(store, KEYS.runs, loadRuns(store).filter((r) => r.id !== id));
  store.removeItem(KEYS.replayPrefix + id);
}

/** Best run per arena, by score. */
export function bestRuns(store: KVStore | null = defaultStore()): Map<string, RunRecord> {
  const best = new Map<string, RunRecord>();
  for (const run of loadRuns(store)) {
    const cur = best.get(run.arenaId);
    if (!cur || run.score.total > cur.score.total) best.set(run.arenaId, run);
  }
  return best;
}

// ---------------------------------------------------------------------------
// Replays
// ---------------------------------------------------------------------------

function replayKeys(store: KVStore): string[] {
  const keys: string[] = [];
  for (let i = 0; i < store.length; i++) {
    const k = store.key(i);
    if (k && k.startsWith(KEYS.replayPrefix)) keys.push(k);
  }
  return keys;
}

export function saveReplay(replay: ReplayData, store: KVStore | null = defaultStore()): boolean {
  if (!store) return false;
  // Prune oldest replays beyond the cap (runs list is newest-first).
  const runs = loadRuns(store);
  const withReplay = runs.filter((r) => r.hasReplay);
  const existing = new Set(replayKeys(store));
  let kept = 0;
  for (const run of withReplay) {
    const key = KEYS.replayPrefix + run.id;
    if (!existing.has(key)) continue;
    kept += 1;
    if (kept >= MAX_REPLAYS) store.removeItem(key);
  }
  const ok = writeJson(store, KEYS.replayPrefix + replay.runId, replay);
  if (!ok) {
    // Quota pressure: drop all other replays and retry once.
    for (const key of replayKeys(store)) {
      if (key !== KEYS.replayPrefix + replay.runId) store.removeItem(key);
    }
    return writeJson(store, KEYS.replayPrefix + replay.runId, replay);
  }
  return true;
}

export function loadReplay(runId: string, store: KVStore | null = defaultStore()): ReplayData | null {
  if (!store) return null;
  const raw = readJson<unknown>(store, KEYS.replayPrefix + runId);
  return raw && validateReplay(raw) ? raw : null;
}

/** In-memory KV store for tests and SSR fallbacks. */
export function createMemoryStore(): KVStore {
  const map = new Map<string, string>();
  return {
    getItem: (k) => (map.has(k) ? map.get(k)! : null),
    setItem: (k, v) => {
      map.set(k, v);
    },
    removeItem: (k) => {
      map.delete(k);
    },
    key: (i) => Array.from(map.keys())[i] ?? null,
    get length() {
      return map.size;
    },
  };
}
