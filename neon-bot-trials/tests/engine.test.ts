import { describe, expect, it } from 'vitest';
import { ARENAS, getArenaById } from '@/lib/arenas';
import { SimEngine, wrapAngle } from '@/lib/engine';
import { addPart, createEmptyRobot, PRESET_ROBOTS } from '@/lib/robots';

const firstDrive = getArenaById('first-drive')!;

function runTicks(engine: SimEngine, ticks: number): void {
  for (let i = 0; i < ticks && !engine.isOver(); i++) engine.tick();
}

describe('simulation state transitions', () => {
  it('follows ready → running → paused → running', () => {
    const engine = new SimEngine(firstDrive, PRESET_ROBOTS[0]);
    expect(engine.status).toBe('ready');
    engine.tick();
    expect(engine.getTelemetry().t).toBe(0); // ticking while not running is a no-op

    engine.start();
    expect(engine.status).toBe('running');
    runTicks(engine, 10);
    expect(engine.getTelemetry().t).toBeGreaterThan(0.1);

    engine.pause();
    expect(engine.status).toBe('paused');
    const t = engine.getTelemetry().t;
    engine.tick();
    expect(engine.getTelemetry().t).toBe(t);

    engine.resume();
    expect(engine.status).toBe('running');
    runTicks(engine, 5);
    expect(engine.getTelemetry().t).toBeGreaterThan(t);
  });

  it('reset rebuilds the world back to ready', () => {
    const engine = new SimEngine(firstDrive, PRESET_ROBOTS[0]);
    engine.start();
    runTicks(engine, 120);
    const moved = engine.getTelemetry().distance;
    expect(moved).toBeGreaterThan(0);
    engine.reset();
    expect(engine.status).toBe('ready');
    expect(engine.getTelemetry().t).toBe(0);
    expect(engine.getTelemetry().distance).toBe(0);
  });

  it('step() respects speed multipliers with a fixed tick', () => {
    const engine = new SimEngine(firstDrive, PRESET_ROBOTS[0]);
    engine.start();
    engine.step(100, 1);
    const t1 = engine.getTelemetry().t;
    const engine2 = new SimEngine(firstDrive, PRESET_ROBOTS[0]);
    engine2.start();
    engine2.step(100, 2);
    const t2 = engine2.getTelemetry().t;
    expect(t2).toBeGreaterThan(t1 * 1.5);
  });
});

describe('physics-driven movement', () => {
  it('a wheeled preset drives forward on flat ground', () => {
    const engine = new SimEngine(firstDrive, PRESET_ROBOTS[0]);
    engine.start();
    runTicks(engine, 600); // 10 simulated seconds
    const tel = engine.getTelemetry();
    expect(tel.distance).toBeGreaterThan(150);
    expect(tel.progress).toBeGreaterThan(0.05);
    expect(tel.failed).toBe(false);
  });

  it('a motorless frame goes nowhere', () => {
    const brick = createEmptyRobot('Brick');
    const engine = new SimEngine(firstDrive, brick);
    engine.start();
    runTicks(engine, 300);
    expect(Math.abs(engine.getTelemetry().distance)).toBeLessThan(30);
  });

  it('higher motor power covers more ground', () => {
    const weak = createEmptyRobot('Weak');
    let w = addPart(weak, 'wheel', { x: -30, y: 14 }).design;
    w = addPart(w, 'wheel', { x: 30, y: 14 }).design;
    w = {
      ...w,
      parts: w.parts.map((p) => ({ ...p, tuning: { ...p.tuning, power: 0.15 } })),
    };
    const strong = {
      ...w,
      id: 'strong',
      parts: w.parts.map((p) => ({ ...p, tuning: { ...p.tuning, power: 1 } })),
    };

    const e1 = new SimEngine(firstDrive, w);
    const e2 = new SimEngine(firstDrive, strong);
    e1.start();
    e2.start();
    runTicks(e1, 420);
    runTicks(e2, 420);
    expect(e2.getTelemetry().distance).toBeGreaterThan(e1.getTelemetry().distance);
  });

  it('burns battery while driving', () => {
    const engine = new SimEngine(firstDrive, PRESET_ROBOTS[0]);
    engine.start();
    runTicks(engine, 300);
    const tel = engine.getTelemetry();
    expect(tel.energyUsed).toBeGreaterThan(0);
    expect(tel.batteryCapacity).toBeGreaterThan(0);
  });
});

describe('end conditions', () => {
  it('completes when the chassis reaches the finish zone', () => {
    // Finish placed immediately ahead of the spawn for a fast, robust test.
    const shortArena = {
      ...firstDrive,
      id: 'short',
      finish: { x: firstDrive.start.x + 160, y: 540, w: 120, h: 240 },
    };
    const engine = new SimEngine(shortArena, PRESET_ROBOTS[0]);
    let ended = false;
    engine.onEnd((result) => {
      ended = true;
      expect(result.telemetry.completed).toBe(true);
      expect(result.replayFrames.length).toBeGreaterThan(0);
    });
    engine.start();
    runTicks(engine, 1200);
    expect(ended).toBe(true);
    expect(engine.status).toBe('finished');
  });

  it('fails when the robot falls below killY', () => {
    const pitArena = {
      ...firstDrive,
      id: 'pit',
      terrain: [{ x: 140, y: 640, w: 200, h: 80, kind: 'ground' as const }],
      killY: 800,
    };
    const engine = new SimEngine(pitArena, PRESET_ROBOTS[0]);
    engine.start();
    runTicks(engine, 1200);
    expect(engine.status).toBe('failed');
    expect(engine.getTelemetry().failReason).toBe('Fell into the void');
  });

  it('fails on timeout', () => {
    const timedArena = { ...firstDrive, id: 'timed', timeLimit: 0.5 };
    const brick = createEmptyRobot('Brick');
    const engine = new SimEngine(timedArena, brick);
    engine.start();
    runTicks(engine, 120);
    expect(engine.status).toBe('failed');
    expect(engine.getTelemetry().failReason).toBe('Time limit exceeded');
  });

  it('is a stable simulation in every shipped arena', () => {
    for (const arena of ARENAS) {
      const engine = new SimEngine(arena, PRESET_ROBOTS[0]);
      engine.start();
      runTicks(engine, 240);
      const tel = engine.getTelemetry();
      expect(Number.isFinite(tel.distance), `${arena.id} stays finite`).toBe(true);
      expect(tel.failReason).not.toBe('Simulation destabilized');
    }
  });
});

describe('frames and helpers', () => {
  it('exposes render frames matching the body registry', () => {
    const engine = new SimEngine(firstDrive, PRESET_ROBOTS[0]);
    const frame = engine.getFrame();
    expect(frame.bodies.length).toBe(engine.getBodyDescs().length);
    expect(engine.getBodyDescs()[0].role).toBe('chassis');
    expect(frame.batteryFrac).toBe(1);
  });

  it('wrapAngle normalizes to (-π, π]', () => {
    expect(wrapAngle(0)).toBe(0);
    expect(wrapAngle(Math.PI * 2)).toBeCloseTo(0);
    expect(wrapAngle(Math.PI * 3)).toBeCloseTo(Math.PI);
    expect(wrapAngle(-Math.PI * 2.5)).toBeCloseTo(-Math.PI / 2);
  });
});
