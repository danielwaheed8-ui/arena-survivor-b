import type { SimFrameBody, ThrusterFx } from './engine';
import type { DrawBodyDesc, RobotDesign } from './types';

/**
 * Builds a static rest-pose frame from a design (no physics engine needed).
 * Body ordering MUST mirror SimEngine.registerDynamicBodies: chassis first,
 * then wheel / leg-upper / leg-lower / spring-foot bodies in part order —
 * this keeps the renderer and replay decoding consistent everywhere.
 */
export function staticFrameFromDesign(
  design: RobotDesign,
  originX = 0,
  originY = 0,
): { bodies: SimFrameBody[]; descs: DrawBodyDesc[] } {
  const bodies: SimFrameBody[] = [];
  const descs: DrawBodyDesc[] = [];
  const hue = design.hue;

  bodies.push({ x: originX, y: originY, angle: 0 });
  descs.push({
    role: 'chassis',
    shape: 'rect',
    w: design.chassis.width,
    h: design.chassis.height,
    r: 0,
    hue,
  });

  for (const part of design.parts) {
    const ax = originX + part.anchor.x;
    const ay = originY + part.anchor.y;
    if (part.type === 'wheel') {
      bodies.push({ x: ax, y: ay, angle: 0 });
      descs.push({ role: 'wheel', shape: 'circle', w: 0, h: 0, r: part.tuning.radius, hue });
    } else if (part.type === 'leg') {
      const len = part.tuning.length;
      bodies.push({ x: ax, y: ay + len / 2, angle: 0 });
      descs.push({ role: 'leg-upper', shape: 'rect', w: 7, h: len, r: 0, hue });
      bodies.push({ x: ax, y: ay + len * 1.5, angle: 0 });
      descs.push({ role: 'leg-lower', shape: 'rect', w: 7, h: len, r: 0, hue });
    } else if (part.type === 'spring') {
      bodies.push({ x: ax, y: ay + part.tuning.length, angle: 0 });
      descs.push({ role: 'foot', shape: 'circle', w: 0, h: 0, r: 7, hue });
    }
  }

  return { bodies, descs };
}

/**
 * Reconstructs thruster FX (world position/direction/firing) for a replayed or
 * previewed chassis transform, using the firing bitmask stored per frame.
 * Thruster ordering matches the engine: design.parts order, thrusters only.
 */
export function thrusterFxFromMask(
  design: RobotDesign,
  chassis: SimFrameBody,
  firingMask: number,
): ThrusterFx[] {
  const cos = Math.cos(chassis.angle);
  const sin = Math.sin(chassis.angle);
  const out: ThrusterFx[] = [];
  let index = 0;
  for (const part of design.parts) {
    if (part.type !== 'thruster') continue;
    out.push({
      partId: part.id,
      x: chassis.x + part.anchor.x * cos - part.anchor.y * sin,
      y: chassis.y + part.anchor.x * sin + part.anchor.y * cos,
      angle: chassis.angle + part.angle,
      firing: (firingMask & (1 << index)) !== 0,
      power: part.tuning.power ?? 0.7,
    });
    index += 1;
  }
  return out;
}

/** Robot bounding radius for framing previews. */
export function designRadius(design: RobotDesign): number {
  let r = Math.hypot(design.chassis.width / 2, design.chassis.height / 2);
  for (const p of design.parts) {
    const reach =
      p.type === 'leg'
        ? p.tuning.length * 2
        : p.type === 'spring'
          ? p.tuning.length + 8
          : p.type === 'wheel'
            ? p.tuning.radius
            : 12;
    r = Math.max(r, Math.hypot(p.anchor.x, p.anchor.y) + reach);
  }
  return r;
}
