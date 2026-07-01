import { describe, expect, it } from 'vitest';
import { PART_CATALOG, defaultTuning, sanitizeTuning } from '@/lib/parts';
import {
  addPart,
  batteryCapacity,
  canAddPart,
  cloneDesign,
  clampAnchor,
  createEmptyRobot,
  MAX_TOTAL_PARTS,
  normalizeDesign,
  PRESET_ROBOTS,
  removePart,
  totalMass,
  updatePart,
  validateDesign,
} from '@/lib/robots';

describe('robot configuration', () => {
  it('creates a valid empty robot', () => {
    const robot = createEmptyRobot('Test Bot');
    expect(validateDesign(robot).ok).toBe(true);
    expect(robot.parts).toHaveLength(0);
    expect(robot.name).toBe('Test Bot');
  });

  it('adds parts with default tuning and clamped anchors', () => {
    const robot = createEmptyRobot();
    const { design, part } = addPart(robot, 'wheel', { x: 999, y: -999 });
    expect(part).not.toBeNull();
    expect(design.parts).toHaveLength(1);
    expect(part!.tuning).toEqual(defaultTuning('wheel'));
    // Anchor clamped to attachment envelope
    expect(Math.abs(part!.anchor.x)).toBeLessThanOrEqual(design.chassis.width / 2 + 10);
    expect(Math.abs(part!.anchor.y)).toBeLessThanOrEqual(design.chassis.height / 2 + 14);
  });

  it('enforces per-type and total part limits', () => {
    let robot = createEmptyRobot();
    const limit = PART_CATALOG.stabilizer.maxCount;
    for (let i = 0; i < limit; i++) {
      robot = addPart(robot, 'stabilizer', { x: 0, y: 0 }).design;
    }
    expect(canAddPart(robot, 'stabilizer').ok).toBe(false);
    const blocked = addPart(robot, 'stabilizer', { x: 0, y: 0 });
    expect(blocked.part).toBeNull();
    expect(blocked.design.parts).toHaveLength(limit);

    // Total cap
    let full = createEmptyRobot();
    const fillTypes = ['wheel', 'leg', 'spring', 'glow'] as const;
    let guard = 0;
    while (full.parts.length < MAX_TOTAL_PARTS && guard < 50) {
      const t = fillTypes[guard % fillTypes.length];
      full = addPart(full, t, { x: 0, y: 0 }).design;
      guard += 1;
    }
    expect(full.parts.length).toBe(MAX_TOTAL_PARTS);
    expect(canAddPart(full, 'glow').ok).toBe(false);
  });

  it('removes and updates parts immutably', () => {
    const base = createEmptyRobot();
    const { design, part } = addPart(base, 'leg', { x: 10, y: 5 });
    const updated = updatePart(design, part!.id, { tuning: { frequency: 99 }, angle: 1 });
    expect(updated).not.toBe(design);
    const p = updated.parts[0];
    // Tuning clamped to catalog bounds
    expect(p.tuning.frequency).toBe(PART_CATALOG.leg.params.find((x) => x.key === 'frequency')!.max);
    expect(p.angle).toBe(1);
    const removed = removePart(updated, part!.id);
    expect(removed.parts).toHaveLength(0);
    expect(updated.parts).toHaveLength(1);
  });

  it('sanitizes malformed tuning values', () => {
    const t = sanitizeTuning('wheel', { radius: NaN, power: 500, grip: -3 });
    expect(t.radius).toBe(PART_CATALOG.wheel.params[0].default);
    expect(t.power).toBe(1);
    expect(t.grip).toBe(0.4);
  });

  it('validates and rejects malformed designs', () => {
    expect(validateDesign(null).ok).toBe(false);
    expect(validateDesign({}).ok).toBe(false);
    expect(validateDesign({ ...createEmptyRobot(), version: 2 }).ok).toBe(false);
    const bad = createEmptyRobot();
    (bad.parts as unknown[]).push({ type: 'laser-cannon', anchor: { x: 0, y: 0 }, angle: 0 });
    expect(validateDesign(bad).ok).toBe(false);
  });

  it('normalizes out-of-range designs instead of rejecting them', () => {
    const robot = createEmptyRobot();
    robot.chassis.width = 9999;
    robot.hue = -30;
    const fixed = normalizeDesign(robot);
    expect(fixed.chassis.width).toBeLessThanOrEqual(130);
    expect(fixed.hue).toBeGreaterThanOrEqual(0);
    expect(fixed.hue).toBeLessThan(360);
  });

  it('ships valid, movable presets', () => {
    expect(PRESET_ROBOTS.length).toBeGreaterThanOrEqual(3);
    for (const preset of PRESET_ROBOTS) {
      expect(validateDesign(preset).ok, preset.name).toBe(true);
      const movable = preset.parts.some((p) =>
        ['wheel', 'leg', 'spring', 'thruster'].includes(p.type),
      );
      expect(movable, `${preset.name} can move`).toBe(true);
    }
  });

  it('computes mass and battery from the design', () => {
    const empty = createEmptyRobot();
    const withWheel = addPart(empty, 'wheel', { x: 0, y: 0 }).design;
    expect(totalMass(withWheel)).toBeGreaterThan(totalMass(empty));
    expect(batteryCapacity(empty)).toBeGreaterThan(90);
  });

  it('clones designs with fresh identities', () => {
    const original = PRESET_ROBOTS[0];
    const copy = cloneDesign(original);
    expect(copy.id).not.toBe(original.id);
    expect(copy.parts.map((p) => p.id)).not.toEqual(original.parts.map((p) => p.id));
    expect(copy.parts.length).toBe(original.parts.length);
  });

  it('clamps anchors to the chassis envelope', () => {
    const robot = createEmptyRobot();
    const a = clampAnchor(robot, 10000, -10000);
    expect(a.x).toBe(robot.chassis.width / 2 + 10);
    expect(a.y).toBe(-(robot.chassis.height / 2 + 14));
  });
});
