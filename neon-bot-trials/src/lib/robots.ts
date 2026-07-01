import { PART_CATALOG, defaultTuning, isPartType, sanitizeTuning } from './parts';
import type { PartInstance, PartType, RobotDesign } from './types';

export const CHASSIS_LIMITS = {
  minWidth: 50,
  maxWidth: 130,
  minHeight: 18,
  maxHeight: 50,
};

export const MAX_TOTAL_PARTS = 14;

let idCounter = 0;
export function freshId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${Date.now().toString(36)}-${idCounter.toString(36)}`;
}

export function createEmptyRobot(name = 'Unnamed Bot'): RobotDesign {
  const now = Date.now();
  return {
    version: 1,
    id: freshId('bot'),
    name,
    hue: 190,
    chassis: { width: 84, height: 28 },
    parts: [],
    createdAt: now,
    updatedAt: now,
  };
}

/** Clamp an anchor so parts stay attached near the chassis hull. */
export function clampAnchor(design: RobotDesign, x: number, y: number): { x: number; y: number } {
  const maxX = design.chassis.width / 2 + 10;
  const maxY = design.chassis.height / 2 + 14;
  return {
    x: Math.max(-maxX, Math.min(maxX, Math.round(x))),
    y: Math.max(-maxY, Math.min(maxY, Math.round(y))),
  };
}

export function countParts(design: RobotDesign, type: PartType): number {
  return design.parts.filter((p) => p.type === type).length;
}

export function canAddPart(design: RobotDesign, type: PartType): { ok: boolean; reason?: string } {
  if (design.parts.length >= MAX_TOTAL_PARTS) {
    return { ok: false, reason: `Frame is full (${MAX_TOTAL_PARTS} parts max).` };
  }
  const limit = PART_CATALOG[type].maxCount;
  if (countParts(design, type) >= limit) {
    return { ok: false, reason: `Max ${limit}× ${PART_CATALOG[type].label}.` };
  }
  return { ok: true };
}

/** Pure add — returns a new design, or the same design if the part is not allowed. */
export function addPart(
  design: RobotDesign,
  type: PartType,
  anchor: { x: number; y: number },
  angle = 0,
): { design: RobotDesign; part: PartInstance | null; reason?: string } {
  const check = canAddPart(design, type);
  if (!check.ok) return { design, part: null, reason: check.reason };
  const part: PartInstance = {
    id: freshId(type),
    type,
    anchor: clampAnchor(design, anchor.x, anchor.y),
    angle,
    tuning: defaultTuning(type),
  };
  return {
    design: { ...design, parts: [...design.parts, part], updatedAt: Date.now() },
    part,
  };
}

export function removePart(design: RobotDesign, partId: string): RobotDesign {
  const parts = design.parts.filter((p) => p.id !== partId);
  if (parts.length === design.parts.length) return design;
  return { ...design, parts, updatedAt: Date.now() };
}

export function updatePart(
  design: RobotDesign,
  partId: string,
  patch: Partial<Pick<PartInstance, 'anchor' | 'angle'>> & { tuning?: Record<string, number> },
): RobotDesign {
  let changed = false;
  const parts = design.parts.map((p) => {
    if (p.id !== partId) return p;
    changed = true;
    return {
      ...p,
      anchor: patch.anchor ? clampAnchor(design, patch.anchor.x, patch.anchor.y) : p.anchor,
      angle: patch.angle !== undefined ? patch.angle : p.angle,
      tuning: patch.tuning ? sanitizeTuning(p.type, { ...p.tuning, ...patch.tuning }) : p.tuning,
    };
  });
  if (!changed) return design;
  return { ...design, parts, updatedAt: Date.now() };
}

export function totalMass(design: RobotDesign): number {
  const chassisMass = (design.chassis.width * design.chassis.height) / 180;
  return chassisMass + design.parts.reduce((sum, p) => sum + PART_CATALOG[p.type].mass, 0);
}

/** Battery grows with chassis size; parts draw from it during a run. */
export function batteryCapacity(design: RobotDesign): number {
  return Math.round(110 + (design.chassis.width * design.chassis.height) / 32);
}

export interface ValidationResult {
  ok: boolean;
  errors: string[];
}

/** Structural validation used by save/load and before simulation. */
export function validateDesign(input: unknown): ValidationResult {
  const errors: string[] = [];
  const d = input as Partial<RobotDesign> | null;
  if (!d || typeof d !== 'object') return { ok: false, errors: ['Design is not an object.'] };
  if (d.version !== 1) errors.push('Unsupported design version.');
  if (typeof d.id !== 'string' || !d.id) errors.push('Missing id.');
  if (typeof d.name !== 'string' || !d.name.trim()) errors.push('Missing name.');
  if (typeof d.hue !== 'number') errors.push('Missing hue.');
  const c = d.chassis;
  if (
    !c ||
    typeof c.width !== 'number' ||
    typeof c.height !== 'number' ||
    c.width < CHASSIS_LIMITS.minWidth ||
    c.width > CHASSIS_LIMITS.maxWidth ||
    c.height < CHASSIS_LIMITS.minHeight ||
    c.height > CHASSIS_LIMITS.maxHeight
  ) {
    errors.push('Chassis dimensions out of range.');
  }
  if (!Array.isArray(d.parts)) {
    errors.push('Parts must be an array.');
  } else {
    if (d.parts.length > MAX_TOTAL_PARTS) errors.push('Too many parts.');
    const counts: Record<string, number> = {};
    for (const p of d.parts) {
      if (!p || !isPartType(p.type)) {
        errors.push('Unknown part type.');
        continue;
      }
      counts[p.type] = (counts[p.type] ?? 0) + 1;
      if (counts[p.type] > PART_CATALOG[p.type].maxCount) errors.push(`Too many ${p.type} parts.`);
      if (!p.anchor || typeof p.anchor.x !== 'number' || typeof p.anchor.y !== 'number') {
        errors.push(`Part ${p.type} has a bad anchor.`);
      }
      if (typeof p.angle !== 'number' || !Number.isFinite(p.angle)) {
        errors.push(`Part ${p.type} has a bad angle.`);
      }
    }
  }
  return { ok: errors.length === 0, errors };
}

/** Repair a loaded design in place of rejecting it outright (tuning drift, etc.). */
export function normalizeDesign(design: RobotDesign): RobotDesign {
  return {
    ...design,
    hue: ((design.hue % 360) + 360) % 360,
    chassis: {
      width: Math.min(CHASSIS_LIMITS.maxWidth, Math.max(CHASSIS_LIMITS.minWidth, design.chassis.width)),
      height: Math.min(CHASSIS_LIMITS.maxHeight, Math.max(CHASSIS_LIMITS.minHeight, design.chassis.height)),
    },
    parts: design.parts.slice(0, MAX_TOTAL_PARTS).map((p) => ({
      ...p,
      anchor: clampAnchor(design, p.anchor.x, p.anchor.y),
      tuning: sanitizeTuning(p.type, p.tuning),
    })),
  };
}

// ---------------------------------------------------------------------------
// Preset robots — instantly playable machines
// ---------------------------------------------------------------------------

function preset(
  name: string,
  hue: number,
  chassis: { width: number; height: number },
  parts: Array<{ type: PartType; x: number; y: number; angle?: number; tuning?: Record<string, number> }>,
): RobotDesign {
  const base = createEmptyRobot(name);
  return normalizeDesign({
    ...base,
    id: `preset-${name.toLowerCase().replace(/\s+/g, '-')}`,
    hue,
    chassis,
    parts: parts.map((p, i) => ({
      id: `preset-${name}-${i}`,
      type: p.type,
      anchor: { x: p.x, y: p.y },
      angle: p.angle ?? 0,
      tuning: { ...defaultTuning(p.type), ...p.tuning },
    })),
  });
}

export const PRESET_ROBOTS: RobotDesign[] = [
  preset('Volt Roller', 195, { width: 96, height: 26 }, [
    { type: 'wheel', x: -36, y: 16, tuning: { radius: 18, power: 0.75, grip: 1.2 } },
    { type: 'wheel', x: 36, y: 16, tuning: { radius: 18, power: 0.75, grip: 1.2 } },
    { type: 'stabilizer', x: 0, y: -8, tuning: { strength: 0.45, damping: 0.5 } },
    { type: 'glow', x: 0, y: -16, tuning: { size: 12, pulse: 1.2 } },
  ]),
  preset('Strider MK-II', 285, { width: 80, height: 24 }, [
    { type: 'leg', x: -28, y: 12, tuning: { length: 34, power: 1, frequency: 0.9, phase: 0, swing: 0.8, kneeBias: -0.4, kneeLag: 1.5 } },
    { type: 'leg', x: 28, y: 12, tuning: { length: 34, power: 1, frequency: 0.9, phase: 3.14, swing: 0.8, kneeBias: -0.4, kneeLag: 1.5 } },
    { type: 'stabilizer', x: 0, y: -6, tuning: { strength: 0.5, damping: 0.4 } },
    { type: 'sensor', x: 0, y: -14 },
    { type: 'glow', x: -30, y: -12, tuning: { size: 9, pulse: 0.8 } },
    { type: 'glow', x: 30, y: -12, tuning: { size: 9, pulse: 0.8 } },
  ]),
  // Thruster angle convention: 0 = thrust straight up; positive tilts the
  // thrust vector toward +x (forward).
  preset('Hopper X', 45, { width: 72, height: 26 }, [
    { type: 'spring', x: -24, y: 14, tuning: { length: 40, stiffness: 0.09, damping: 0.04 } },
    { type: 'spring', x: 24, y: 14, tuning: { length: 40, stiffness: 0.09, damping: 0.04 } },
    { type: 'thruster', x: 0, y: 12, angle: 0.5, tuning: { power: 0.6, interval: 1.5, burn: 0.3 } },
    { type: 'sensor', x: 0, y: -14, tuning: { sensitivity: 0.7 } },
    { type: 'stabilizer', x: 0, y: -4, tuning: { strength: 0.8, damping: 0.6 } },
    { type: 'glow', x: 0, y: -16, tuning: { size: 14, pulse: 2 } },
  ]),
  preset('Trailblazer', 150, { width: 110, height: 30 }, [
    { type: 'wheel', x: -44, y: 18, tuning: { radius: 20, power: 0.85, grip: 1.4 } },
    { type: 'wheel', x: 0, y: 18, tuning: { radius: 16, power: 0.7, grip: 1.3 } },
    { type: 'wheel', x: 44, y: 18, tuning: { radius: 20, power: 0.85, grip: 1.4 } },
    { type: 'stabilizer', x: 0, y: -10, tuning: { strength: 0.6, damping: 0.6 } },
    { type: 'thruster', x: -46, y: -8, angle: 1.1, tuning: { power: 0.8, interval: 2, burn: 0.3 } },
    { type: 'sensor', x: 10, y: -16 },
    { type: 'glow', x: -20, y: -16, tuning: { size: 10, pulse: 1.5 } },
    { type: 'glow', x: 20, y: -16, tuning: { size: 10, pulse: 1.5 } },
  ]),
  // Sensor + big thruster = closed-loop auto-jump. Built for gaps and the
  // Gauntlet; proof that every arena in the campaign is beatable.
  preset('Skyhopper', 320, { width: 96, height: 26 }, [
    { type: 'wheel', x: -38, y: 16, tuning: { radius: 18, power: 0.9, grip: 1.4 } },
    { type: 'wheel', x: 38, y: 16, tuning: { radius: 18, power: 0.9, grip: 1.4 } },
    { type: 'thruster', x: 0, y: -10, angle: 0.5, tuning: { power: 1.3, interval: 1.5, burn: 0.35 } },
    { type: 'stabilizer', x: 0, y: 0, tuning: { strength: 0.8, damping: 0.6 } },
    { type: 'sensor', x: 10, y: -14, tuning: { sensitivity: 0.9 } },
    { type: 'glow', x: -30, y: -14, tuning: { size: 11, pulse: 2.2 } },
    { type: 'glow', x: 30, y: -14, tuning: { size: 11, pulse: 2.2 } },
  ]),
];

export function getPresetById(id: string): RobotDesign | undefined {
  return PRESET_ROBOTS.find((r) => r.id === id);
}

/** Deep-clone a design with a fresh identity (for "duplicate" / editing presets). */
export function cloneDesign(design: RobotDesign, name?: string): RobotDesign {
  const copy: RobotDesign = JSON.parse(JSON.stringify(design));
  copy.id = freshId('bot');
  copy.name = name ?? `${design.name} Copy`;
  copy.createdAt = Date.now();
  copy.updatedAt = Date.now();
  copy.parts = copy.parts.map((p) => ({ ...p, id: freshId(p.type) }));
  return copy;
}
