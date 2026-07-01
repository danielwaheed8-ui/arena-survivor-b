import type { PartDef, PartInstance, PartType } from './types';

/**
 * The modular part catalog. Tuning params are surfaced 1:1 in the builder's
 * tuning panel, so every param needs sane bounds and a human hint.
 */
export const PART_CATALOG: Record<PartType, PartDef> = {
  wheel: {
    type: 'wheel',
    label: 'Drive Wheel',
    icon: '◎',
    description: 'Motorized wheel. The workhorse of ground locomotion.',
    mass: 4,
    maxCount: 6,
    params: [
      { key: 'radius', label: 'Radius', min: 10, max: 26, step: 1, default: 16, unit: 'px', hint: 'Bigger wheels clear bumps but are slower to spin up.' },
      { key: 'power', label: 'Motor Power', min: 0, max: 1, step: 0.05, default: 0.6, hint: 'Torque applied by the hub motor. Costs energy.' },
      { key: 'grip', label: 'Grip', min: 0.4, max: 1.6, step: 0.1, default: 1.0, hint: 'Tire friction. High grip climbs, low grip drifts.' },
      { key: 'direction', label: 'Direction', min: -1, max: 1, step: 2, default: 1, hint: '+1 rolls right, -1 rolls left.' },
    ],
  },
  leg: {
    type: 'leg',
    label: 'Piston Leg',
    icon: '⌖',
    description: 'Two-segment leg driven by rhythmic joint motors.',
    mass: 5,
    maxCount: 6,
    params: [
      { key: 'length', label: 'Segment Length', min: 18, max: 44, step: 1, default: 34, unit: 'px', hint: 'Longer legs stride further but wobble more.' },
      { key: 'power', label: 'Joint Power', min: 0, max: 1, step: 0.05, default: 0.85, hint: 'Strength of hip and knee motors.' },
      { key: 'frequency', label: 'Gait Frequency', min: 0.3, max: 2.5, step: 0.05, default: 0.9, unit: 'Hz', hint: 'How fast the leg cycles.' },
      { key: 'phase', label: 'Gait Phase', min: 0, max: 6.28, step: 0.1, default: 0, unit: 'rad', hint: 'Offset legs against each other for a stable gait.' },
      { key: 'swing', label: 'Swing Arc', min: 0.2, max: 1.4, step: 0.05, default: 0.8, unit: 'rad', hint: 'Angular range of the stride.' },
      { key: 'kneeBias', label: 'Knee Bias', min: -0.6, max: 0.6, step: 0.05, default: -0.4, unit: 'rad', hint: 'Resting knee bend. Negative bends backward (bird-leg) and drives forward.' },
      { key: 'kneeLag', label: 'Knee Lag', min: -2, max: 2, step: 0.1, default: 1.5, unit: 'rad', hint: 'Phase delay between hip and knee. Shapes the foot path.' },
    ],
  },
  spring: {
    type: 'spring',
    label: 'Shock Spring',
    icon: '⌇',
    description: 'Damped spring strut with a contact foot. Absorbs landings.',
    mass: 3,
    maxCount: 4,
    params: [
      { key: 'length', label: 'Rest Length', min: 20, max: 60, step: 1, default: 38, unit: 'px', hint: 'Natural length of the strut.' },
      { key: 'stiffness', label: 'Stiffness', min: 0.02, max: 0.2, step: 0.01, default: 0.08, hint: 'Spring constant. Stiffer = bouncier response.' },
      { key: 'damping', label: 'Damping', min: 0, max: 0.2, step: 0.01, default: 0.05, hint: 'Suppresses oscillation after impact.' },
    ],
  },
  thruster: {
    type: 'thruster',
    label: 'Pulse Thruster',
    icon: '▲',
    description: 'Micro thruster that fires on a rhythm — or on tilt if a sensor is mounted.',
    mass: 3,
    maxCount: 4,
    params: [
      { key: 'power', label: 'Thrust', min: 0.2, max: 1.5, step: 0.05, default: 0.7, hint: 'Impulse strength per burn. Heavy energy cost.' },
      { key: 'interval', label: 'Cycle Time', min: 0.5, max: 4, step: 0.1, default: 1.6, unit: 's', hint: 'Seconds between automatic burns.' },
      { key: 'burn', label: 'Burn Length', min: 0.1, max: 1, step: 0.05, default: 0.3, unit: 's', hint: 'How long each burn lasts.' },
    ],
  },
  stabilizer: {
    type: 'stabilizer',
    label: 'Gyro Stabilizer',
    icon: '◈',
    description: 'Reaction gyro that fights chassis tilt. Drains energy under load.',
    mass: 4,
    maxCount: 2,
    params: [
      { key: 'strength', label: 'Correction', min: 0.1, max: 1, step: 0.05, default: 0.5, hint: 'How hard the gyro rights the chassis.' },
      { key: 'damping', label: 'Damping', min: 0, max: 1, step: 0.05, default: 0.4, hint: 'Resists spin. Prevents overcorrection wobble.' },
    ],
  },
  sensor: {
    type: 'sensor',
    label: 'Tilt Sensor',
    icon: '◉',
    description: 'Feedback dome. Lets thrusters auto-fire to recover from tips.',
    mass: 1,
    maxCount: 2,
    params: [
      { key: 'sensitivity', label: 'Sensitivity', min: 0.2, max: 1, step: 0.05, default: 0.6, hint: 'Lower trigger threshold = earlier recovery burns.' },
    ],
  },
  glow: {
    type: 'glow',
    label: 'Glow Fin',
    icon: '✦',
    description: 'Decorative light fin. Pure style, near-zero mass.',
    mass: 0.4,
    maxCount: 8,
    params: [
      { key: 'size', label: 'Size', min: 6, max: 18, step: 1, default: 10, unit: 'px', hint: 'Fin length.' },
      { key: 'pulse', label: 'Pulse Rate', min: 0.2, max: 3, step: 0.1, default: 1, unit: 'Hz', hint: 'Glow animation speed.' },
    ],
  },
};

export const PART_TYPES = Object.keys(PART_CATALOG) as PartType[];

export function defaultTuning(type: PartType): Record<string, number> {
  const def = PART_CATALOG[type];
  const tuning: Record<string, number> = {};
  for (const p of def.params) tuning[p.key] = p.default;
  return tuning;
}

/** Clamp a tuning object to catalog bounds, filling gaps with defaults. */
export function sanitizeTuning(type: PartType, tuning: Record<string, number> | undefined): Record<string, number> {
  const def = PART_CATALOG[type];
  const clean: Record<string, number> = {};
  for (const p of def.params) {
    const raw = tuning?.[p.key];
    const v = typeof raw === 'number' && Number.isFinite(raw) ? raw : p.default;
    clean[p.key] = Math.min(p.max, Math.max(p.min, v));
  }
  return clean;
}

export function partMass(part: PartInstance): number {
  return PART_CATALOG[part.type].mass;
}

export function isPartType(v: unknown): v is PartType {
  return typeof v === 'string' && v in PART_CATALOG;
}
