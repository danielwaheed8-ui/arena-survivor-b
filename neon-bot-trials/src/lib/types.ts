/**
 * Shared domain types for Neon Bot Trials.
 * Everything here is plain serializable data — the physics engine consumes
 * these definitions and never leaks Matter.js objects into the UI layer.
 */

export type PartType =
  | 'wheel'
  | 'leg'
  | 'spring'
  | 'thruster'
  | 'stabilizer'
  | 'sensor'
  | 'glow';

/** A single tunable parameter on a part. */
export interface TuningParam {
  key: string;
  label: string;
  min: number;
  max: number;
  step: number;
  default: number;
  unit?: string;
  hint: string;
}

/** Static catalog entry describing a part type. */
export interface PartDef {
  type: PartType;
  label: string;
  icon: string;
  description: string;
  mass: number;
  maxCount: number;
  params: TuningParam[];
}

/** One placed part on a robot. Anchor is relative to the chassis center (px). */
export interface PartInstance {
  id: string;
  type: PartType;
  anchor: { x: number; y: number };
  /** Orientation of the part in radians (relative to chassis). */
  angle: number;
  tuning: Record<string, number>;
}

export interface ChassisConfig {
  width: number;
  height: number;
}

export interface RobotDesign {
  version: 1;
  id: string;
  name: string;
  hue: number;
  chassis: ChassisConfig;
  parts: PartInstance[];
  createdAt: number;
  updatedAt: number;
}

// ---------------------------------------------------------------------------
// Arenas
// ---------------------------------------------------------------------------

export interface TerrainBlock {
  x: number;
  y: number;
  w: number;
  h: number;
  /** Rotation in radians — used for ramps. */
  angle?: number;
  /** Bounciness override (bounce pads). */
  restitution?: number;
  friction?: number;
  /** Render tint role. */
  kind?: 'ground' | 'platform' | 'pad' | 'wall';
}

export interface MovingPlatform {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Motion axis + amplitude in px. */
  dx: number;
  dy: number;
  /** Seconds for a full back-and-forth cycle. */
  period: number;
  phase?: number;
}

export interface ForceZone {
  x: number;
  y: number;
  w: number;
  h: number;
  /** Constant force applied per unit mass (an acceleration, px/s²). */
  fx: number;
  fy: number;
  /** Sinusoidal gust multiplier amplitude, 0 = steady. */
  gust?: number;
  gustPeriod?: number;
}

export interface GravityZone {
  x: number;
  y: number;
  w: number;
  h: number;
  /** 0..1 — fraction of normal gravity inside the zone (0.25 = low gravity). */
  scale: number;
}

export interface ArenaTheme {
  /** Background gradient stops. */
  skyTop: string;
  skyBottom: string;
  grid: string;
  terrain: string;
  terrainGlow: string;
  accent: string;
}

export interface ArenaDef {
  id: string;
  name: string;
  tagline: string;
  objective: string;
  hint: string;
  difficulty: 1 | 2 | 3 | 4 | 5;
  gravityY: number;
  /** Hard time limit in seconds — run fails when exceeded. */
  timeLimit: number;
  /** Bodies falling below this y fail the run. */
  killY: number;
  start: { x: number; y: number };
  finish: { x: number; y: number; w: number; h: number };
  terrain: TerrainBlock[];
  movingPlatforms: MovingPlatform[];
  windZones: ForceZone[];
  gravityZones: GravityZone[];
  /** Dynamic tilting planks: [pivotX, pivotY, width]. */
  seesaws: Array<{ x: number; y: number; w: number }>;
  theme: ArenaTheme;
}

// ---------------------------------------------------------------------------
// Simulation, scoring, replays
// ---------------------------------------------------------------------------

export type SimStatus = 'ready' | 'running' | 'paused' | 'finished' | 'failed';

export interface Telemetry {
  /** Elapsed simulated seconds. */
  t: number;
  /** Horizontal displacement of the chassis from the start (px). */
  distance: number;
  maxX: number;
  /** 0..1 progress toward the finish zone. */
  progress: number;
  energyUsed: number;
  batteryCapacity: number;
  flips: number;
  crashes: number;
  /** Mean absolute chassis tilt in radians. */
  avgTilt: number;
  completed: boolean;
  failed: boolean;
  failReason?: string;
}

export interface ScoreBreakdown {
  completionPoints: number;
  timeBonus: number;
  stabilityBonus: number;
  energyBonus: number;
  flipPenalty: number;
  crashPenalty: number;
  total: number;
  grade: 'S' | 'A' | 'B' | 'C' | 'D';
}

export interface RunRecord {
  id: string;
  arenaId: string;
  robotName: string;
  robotId: string;
  date: number;
  telemetry: Telemetry;
  score: ScoreBreakdown;
  hasReplay: boolean;
}

/** Static visual descriptor for a drawable body, captured once per run. */
export interface DrawBodyDesc {
  role:
    | 'chassis'
    | 'wheel'
    | 'leg-upper'
    | 'leg-lower'
    | 'foot'
    | 'platform'
    | 'seesaw';
  shape: 'rect' | 'circle';
  w: number;
  h: number;
  r: number;
  hue: number;
}

/** Per-frame transform: x, y, angle (quantized in storage). */
export type ReplayFrame = number[];

export interface ReplayData {
  version: 1;
  runId: string;
  arenaId: string;
  robotName: string;
  /** Snapshot of the design so replays survive later edits. */
  design: RobotDesign;
  bodies: DrawBodyDesc[];
  /** Frames sampled at `sampleHz`; each frame is bodies.length * 3 numbers. */
  frames: ReplayFrame[];
  sampleHz: number;
  duration: number;
}
