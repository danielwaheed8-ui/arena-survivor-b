import type { ArenaDef } from './types';

/**
 * Arena coordinate system: +x right, +y down (Matter.js convention).
 * Terrain blocks are center-positioned rectangles, matching Bodies.rectangle.
 * The main floor sits around y=600-660; killY is well below every course.
 */

const ARENA_LIST: ArenaDef[] = [
  {
    id: 'first-drive',
    name: 'First Drive',
    tagline: 'Calibration Track 01',
    objective: 'Drive your bot from the spawn pad to the finish gate on a flat test strip.',
    hint: 'Two powered wheels and a stabilizer will cruise this. Watch the small expansion joints.',
    difficulty: 1,
    gravityY: 1,
    timeLimit: 75,
    killY: 900,
    start: { x: 140, y: 552 },
    finish: { x: 2300, y: 500, w: 90, h: 200 },
    terrain: [
      { x: 1250, y: 640, w: 3000, h: 80, kind: 'ground' },
      { x: -230, y: 480, w: 40, h: 400, kind: 'wall' },
      // Low expansion joints: visual texture that even walkers step over.
      { x: 900, y: 599, w: 70, h: 5, kind: 'platform' },
      { x: 1500, y: 599, w: 70, h: 5, kind: 'platform' },
      { x: 1900, y: 599, w: 90, h: 5, kind: 'platform' },
    ],
    movingPlatforms: [],
    windZones: [],
    gravityZones: [],
    seesaws: [],
    theme: {
      skyTop: '#04060f',
      skyBottom: '#0a1228',
      grid: 'rgba(34,211,238,0.08)',
      terrain: '#0e1b33',
      terrainGlow: '#22d3ee',
      accent: '#22d3ee',
    },
  },
  {
    id: 'ramp-lab',
    name: 'Ramp Lab',
    tagline: 'Incline Test Chamber',
    objective: 'Climb the ramp sequence and reach the elevated finish deck.',
    hint: 'High grip and steady power beat raw speed. Legs with offset phase can climb what wheels spin out on.',
    difficulty: 2,
    gravityY: 1,
    timeLimit: 90,
    killY: 900,
    start: { x: 130, y: 552 },
    finish: { x: 2380, y: 360, w: 90, h: 200 },
    terrain: [
      // Surface heights are matched end-to-end: floor top 600 → ramp1 (13°)
      // → plateau top 500 → downslope → ramp2 (14°) → deck top 444.
      { x: 280, y: 640, w: 760, h: 80, kind: 'ground' },
      { x: -80, y: 480, w: 40, h: 400, kind: 'wall' },
      { x: 850, y: 564, w: 434, h: 26, angle: -0.234, friction: 1.4, kind: 'ground' },
      { x: 1240, y: 513, w: 360, h: 26, kind: 'platform' },
      { x: 1590, y: 538, w: 346, h: 26, angle: 0.146, kind: 'ground' },
      { x: 1970, y: 511, w: 434, h: 26, angle: -0.245, friction: 1.4, kind: 'ground' },
      { x: 2390, y: 457, w: 420, h: 26, kind: 'platform' },
    ],
    movingPlatforms: [],
    windZones: [],
    gravityZones: [],
    seesaws: [],
    theme: {
      skyTop: '#070510',
      skyBottom: '#141028',
      grid: 'rgba(232,121,249,0.08)',
      terrain: '#1a1233',
      terrainGlow: '#e879f9',
      accent: '#e879f9',
    },
  },
  {
    id: 'gap-run',
    name: 'Gap Run',
    tagline: 'Void Jump Sector',
    objective: 'Cross the platform chain over the void. Falling means mission failure.',
    hint: 'Springs and a downward thruster burst give air. Time the lift platform — it rises every few seconds.',
    difficulty: 3,
    gravityY: 1,
    timeLimit: 90,
    killY: 820,
    start: { x: 150, y: 552 },
    finish: { x: 2280, y: 540, w: 90, h: 200 },
    terrain: [
      // Gaps widen (62 → 80 → 80 → lift) and each landing sits slightly lower,
      // so fast wheels clear the first jump but later ones want springs or air.
      { x: 200, y: 640, w: 520, h: 80, kind: 'ground' },
      { x: -80, y: 480, w: 40, h: 400, kind: 'wall' },
      { x: 688, y: 649, w: 332, h: 62, kind: 'platform' },
      { x: 1104, y: 657, w: 340, h: 54, kind: 'platform' },
      { x: 1512, y: 663, w: 316, h: 46, kind: 'platform' },
      { x: 2200, y: 648, w: 440, h: 72, kind: 'ground' },
    ],
    movingPlatforms: [
      { id: 'lift-1', x: 1830, y: 655, w: 170, h: 22, dx: 0, dy: -75, period: 4.2 },
    ],
    windZones: [],
    gravityZones: [],
    seesaws: [],
    theme: {
      skyTop: '#03080a',
      skyBottom: '#082017',
      grid: 'rgba(163,230,53,0.08)',
      terrain: '#0c2418',
      terrainGlow: '#a3e635',
      accent: '#a3e635',
    },
  },
  {
    id: 'balance-bridge',
    name: 'Balance Bridge',
    tagline: 'Stability Proving Ground',
    objective: 'Traverse narrow beams and tilting planks without toppling into the abyss.',
    hint: 'A gyro stabilizer is almost mandatory. Cross seesaws slowly — momentum flips them.',
    difficulty: 4,
    gravityY: 1,
    timeLimit: 110,
    killY: 820,
    start: { x: 150, y: 552 },
    finish: { x: 2170, y: 500, w: 90, h: 200 },
    terrain: [
      { x: 190, y: 640, w: 460, h: 80, kind: 'ground' },
      { x: -80, y: 480, w: 40, h: 400, kind: 'wall' },
      { x: 660, y: 612, w: 480, h: 14, kind: 'platform' },
      // Pylon stops under each seesaw end cap the tilt at ~7°, so planks
      // behave like balance ramps rather than trapdoors. Gaps between spans
      // stay under 30px so wheels roll across instead of wedging in.
      { x: 965, y: 618, w: 22, h: 12, kind: 'platform' },
      { x: 1175, y: 618, w: 22, h: 12, kind: 'platform' },
      { x: 1390, y: 616, w: 300, h: 12, kind: 'platform' },
      { x: 1595, y: 614, w: 22, h: 12, kind: 'platform' },
      { x: 1785, y: 614, w: 22, h: 12, kind: 'platform' },
      { x: 2060, y: 634, w: 460, h: 68, kind: 'ground' },
    ],
    movingPlatforms: [],
    windZones: [],
    gravityZones: [],
    seesaws: [
      { x: 1070, y: 600, w: 280 },
      { x: 1690, y: 596, w: 250 },
    ],
    theme: {
      skyTop: '#0a0508',
      skyBottom: '#1c0f1c',
      grid: 'rgba(251,191,36,0.08)',
      terrain: '#2a1626',
      terrainGlow: '#fbbf24',
      accent: '#fbbf24',
    },
  },
  {
    id: 'wind-tunnel',
    name: 'Wind Tunnel',
    tagline: 'Aerodynamic Stress Rig',
    objective: 'Push through alternating crosswind cells and reach the far bulkhead.',
    hint: 'Heavy chassis and high grip resist gusts. The third cell blows upward — light bots get launched.',
    difficulty: 3,
    gravityY: 1,
    timeLimit: 90,
    killY: 900,
    start: { x: 140, y: 552 },
    finish: { x: 2350, y: 500, w: 90, h: 200 },
    terrain: [
      { x: 1250, y: 640, w: 3000, h: 80, kind: 'ground' },
      { x: -230, y: 480, w: 40, h: 400, kind: 'wall' },
    ],
    movingPlatforms: [],
    windZones: [
      // Zone bottoms sit on the floor (y + h/2 = 600) so grounded robots
      // are actually inside the force field.
      { x: 480, y: 430, w: 420, h: 340, fx: -0.32, fy: 0, gust: 0.4, gustPeriod: 2.2 },
      { x: 1150, y: 430, w: 420, h: 340, fx: 0.6, fy: 0, gust: 0.6, gustPeriod: 1.6 },
      { x: 1800, y: 410, w: 440, h: 380, fx: -0.28, fy: -0.5, gust: 0.5, gustPeriod: 2.8 },
    ],
    gravityZones: [],
    seesaws: [],
    theme: {
      skyTop: '#040b12',
      skyBottom: '#0a1c2e',
      grid: 'rgba(96,165,250,0.09)',
      terrain: '#0d2136',
      terrainGlow: '#60a5fa',
      accent: '#60a5fa',
    },
  },
  {
    id: 'neon-gauntlet',
    name: 'Neon Gauntlet',
    tagline: 'Final Certification Course',
    objective: 'Ramps, gaps, a lift, a low-gravity cell and a wind wall — clear them all to certify your bot.',
    hint: 'Bring everything: grip for the ramp, air control for the low-grav cell, mass for the wind wall.',
    difficulty: 5,
    gravityY: 1,
    timeLimit: 150,
    killY: 860,
    start: { x: 150, y: 552 },
    finish: { x: 3080, y: 450, w: 90, h: 340 },
    terrain: [
      // Sequence: gentle ramp → plateau → ferry gap → platform → low-grav
      // jump → bounce pad drop → windy final straight.
      { x: 280, y: 640, w: 760, h: 80, kind: 'ground' },
      { x: -80, y: 480, w: 40, h: 400, kind: 'wall' },
      { x: 3250, y: 460, w: 40, h: 440, kind: 'wall' },
      { x: 840, y: 568, w: 412, h: 26, angle: -0.221, friction: 1.4, kind: 'ground' },
      { x: 1200, y: 522, w: 320, h: 26, kind: 'platform' },
      { x: 1860, y: 530, w: 320, h: 26, kind: 'platform' },
      { x: 2280, y: 550, w: 300, h: 30, kind: 'platform' },
      { x: 2560, y: 626, w: 200, h: 24, restitution: 1.1, kind: 'pad' },
      { x: 2950, y: 640, w: 560, h: 80, kind: 'ground' },
    ],
    movingPlatforms: [
      { id: 'ferry-1', x: 1520, y: 520, w: 160, h: 20, dx: 100, dy: 0, period: 5 },
    ],
    windZones: [
      { x: 2780, y: 400, w: 320, h: 400, fx: -0.5, fy: 0, gust: 0.6, gustPeriod: 2 },
    ],
    gravityZones: [{ x: 2100, y: 330, w: 480, h: 460, scale: 0.3 }],
    seesaws: [],
    theme: {
      skyTop: '#08040f',
      skyBottom: '#160b2b',
      grid: 'rgba(34,211,238,0.07)',
      terrain: '#170f30',
      terrainGlow: '#22d3ee',
      accent: '#e879f9',
    },
  },
];

export const ARENAS: ReadonlyArray<ArenaDef> = ARENA_LIST;

export function getArenaById(id: string): ArenaDef | undefined {
  return ARENAS.find((a) => a.id === id);
}

export const DEFAULT_ARENA_ID = ARENAS[0].id;

export interface ArenaValidation {
  ok: boolean;
  errors: string[];
}

/** Structural sanity checks — exercised by tests and the /qa self-check page. */
export function validateArena(arena: ArenaDef): ArenaValidation {
  const errors: string[] = [];
  if (!arena.id) errors.push('missing id');
  if (!arena.name) errors.push('missing name');
  if (!arena.objective) errors.push('missing objective');
  if (!arena.hint) errors.push('missing hint');
  if (arena.difficulty < 1 || arena.difficulty > 5) errors.push('difficulty out of range');
  if (arena.terrain.length === 0) errors.push('no terrain');
  if (arena.timeLimit <= 0) errors.push('bad time limit');
  if (arena.finish.x <= arena.start.x) errors.push('finish must be ahead of start');
  if (arena.killY <= arena.start.y) errors.push('killY must be below the start');
  const startSupported = arena.terrain.some(
    (t) =>
      Math.abs((t.angle ?? 0)) < 0.01 &&
      arena.start.x > t.x - t.w / 2 &&
      arena.start.x < t.x + t.w / 2 &&
      t.y > arena.start.y,
  );
  if (!startSupported) errors.push('start position has no ground beneath it');
  return { ok: errors.length === 0, errors };
}

/** 0..1 course progress for a given chassis x. */
export function arenaProgress(arena: ArenaDef, x: number): number {
  const span = arena.finish.x - arena.start.x;
  if (span <= 0) return 0;
  return Math.max(0, Math.min(1, (x - arena.start.x) / span));
}
