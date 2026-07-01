import Matter from 'matter-js';
import { arenaProgress } from './arenas';
import { batteryCapacity, normalizeDesign } from './robots';
import { encodeFrame, REPLAY_SAMPLE_HZ } from './replay';
import type {
  ArenaDef,
  DrawBodyDesc,
  PartInstance,
  ReplayFrame,
  RobotDesign,
  SimStatus,
  Telemetry,
} from './types';

const { Engine, Composite, Bodies, Body, Constraint, Events } = Matter;

export const TICK_MS = 1000 / 60;
const DT = TICK_MS / 1000;

// Motor and force tuning constants. Angular motors adjust velocity directly
// instead of using Matter's ms²-scaled torque units — this keeps behavior
// stable and unit-testable across step rates.
//
// IMPORTANT: Matter.js body velocities are PER-TICK (per 16.67 ms step), not
// per second. All human-readable rad/s constants below are converted with DT
// at the point of use.
const WHEEL_MAX_SPIN = 15; // rad/s at power = 1
const WHEEL_SPIN_ACCEL = 55; // rad/s² at power = 1
const LEG_GAIN = 11; // proportional gain (rad/s per rad of error)
const LEG_MAX_SPIN = 13; // rad/s ceiling for leg segments
const STABILIZER_K = 30; // rad/s² per rad of tilt at strength = 1
const STABILIZER_D = 12; // rad/s² per rad/s of spin at damping = 1
const THRUST_ACCEL = 2.4; // in gravity units at power = 1
const CRASH_SPEED = 9; // relative collision speed (px/tick) that counts as a crash
const LIMP_FACTOR = 0.35; // power multiplier once the battery is drained
const MAX_REPLAY_FRAMES = REPLAY_SAMPLE_HZ * 160;

export interface SimFrameBody {
  x: number;
  y: number;
  angle: number;
}

export interface ThrusterFx {
  partId: string;
  x: number;
  y: number;
  /** World angle of the thrust direction (force direction, flame is opposite). */
  angle: number;
  firing: boolean;
  power: number;
}

export interface SimFrame {
  t: number;
  status: SimStatus;
  bodies: SimFrameBody[];
  chassis: { x: number; y: number; angle: number; vx: number; vy: number };
  thrusters: ThrusterFx[];
  partActivity: Record<string, number>;
  batteryFrac: number;
  windSample: { x: number; y: number } | null;
}

interface WheelRuntime {
  kind: 'wheel';
  part: PartInstance;
  body: Matter.Body;
}
interface LegRuntime {
  kind: 'leg';
  part: PartInstance;
  upper: Matter.Body;
  lower: Matter.Body;
}
interface SpringRuntime {
  kind: 'spring';
  part: PartInstance;
  foot: Matter.Body;
  strut: Matter.Constraint;
}
interface ThrusterRuntime {
  kind: 'thruster';
  part: PartInstance;
  phaseOffset: number;
  firing: boolean;
  recoveryUntil: number;
}
interface StabilizerRuntime {
  kind: 'stabilizer';
  part: PartInstance;
}

type PartRuntime = WheelRuntime | LegRuntime | SpringRuntime | ThrusterRuntime | StabilizerRuntime;

interface PlatformRuntime {
  body: Matter.Body;
  base: { x: number; y: number };
  def: ArenaDef['movingPlatforms'][number];
}

export interface RunEndResult {
  telemetry: Telemetry;
  replayBodies: DrawBodyDesc[];
  replayFrames: ReplayFrame[];
}

/**
 * One simulation run: builds a Matter.js world from an arena definition and a
 * robot design, steps it at a fixed 60 Hz tick, runs all part controllers,
 * records telemetry and replay frames, and reports completion/failure.
 */
export class SimEngine {
  readonly arena: ArenaDef;
  readonly design: RobotDesign;

  private engine: Matter.Engine;
  private chassis!: Matter.Body;
  private runtimes: PartRuntime[] = [];
  private platforms: PlatformRuntime[] = [];
  private seesawBodies: Matter.Body[] = [];
  private dynamicBodies: Matter.Body[] = [];
  private bodyDescs: DrawBodyDesc[] = [];
  private thrusterRuntimes: ThrusterRuntime[] = [];

  status: SimStatus = 'ready';
  private t = 0;
  private tickCount = 0;
  private accumulator = 0;

  private battery: number;
  private energyUsed = 0;
  private maxX = 0;
  private startX = 0;
  private cumRotation = 0;
  private prevAngle = 0;
  private tiltAccum = 0;
  private crashes = 0;
  private crashCooldownUntil = 0;
  private failReason: string | undefined;
  private completed = false;

  private replayFrames: ReplayFrame[] = [];
  private partActivity: Record<string, number> = {};
  private hasSensor = false;
  private sensorSensitivity = 0.6;

  private endListeners: Array<(result: RunEndResult) => void> = [];

  constructor(arena: ArenaDef, design: RobotDesign) {
    this.arena = arena;
    this.design = normalizeDesign(design);
    this.battery = batteryCapacity(this.design);
    this.engine = Engine.create();
    this.buildWorld();
  }

  onEnd(listener: (result: RunEndResult) => void): void {
    this.endListeners.push(listener);
  }

  // -------------------------------------------------------------------------
  // World construction
  // -------------------------------------------------------------------------

  private buildWorld(): void {
    const { arena } = this;
    this.engine = Engine.create();
    this.engine.gravity.y = arena.gravityY;
    this.runtimes = [];
    this.platforms = [];
    this.seesawBodies = [];
    this.dynamicBodies = [];
    this.bodyDescs = [];
    this.thrusterRuntimes = [];
    this.partActivity = {};
    this.replayFrames = [];
    this.t = 0;
    this.tickCount = 0;
    this.accumulator = 0;
    this.energyUsed = 0;
    this.cumRotation = 0;
    this.tiltAccum = 0;
    this.crashes = 0;
    this.crashCooldownUntil = 0;
    this.failReason = undefined;
    this.completed = false;
    this.status = 'ready';

    const world = this.engine.world;

    for (const block of arena.terrain) {
      const body = Bodies.rectangle(block.x, block.y, block.w, block.h, {
        isStatic: true,
        angle: block.angle ?? 0,
        friction: block.friction ?? 0.9,
        restitution: block.restitution ?? 0.05,
        label: 'terrain',
      });
      Composite.add(world, body);
    }

    for (const def of arena.movingPlatforms) {
      const body = Bodies.rectangle(def.x, def.y, def.w, def.h, {
        isStatic: true,
        friction: 1,
        label: 'platform',
      });
      Composite.add(world, body);
      this.platforms.push({ body, base: { x: def.x, y: def.y }, def });
    }

    for (const s of arena.seesaws) {
      const plank = Bodies.rectangle(s.x, s.y, s.w, 12, {
        friction: 0.9,
        frictionAir: 0.04,
        density: 0.006,
        label: 'seesaw',
      });
      const pivot = Constraint.create({
        pointA: { x: s.x, y: s.y },
        bodyB: plank,
        pointB: { x: 0, y: 0 },
        stiffness: 1,
        length: 0,
      });
      Composite.add(world, [plank, pivot]);
      this.seesawBodies.push(plank);
    }

    this.buildRobot();

    // Dynamic body registry: chassis, part bodies, seesaws, platforms — order
    // is stable so replay frames can be decoded against `bodyDescs`.
    this.registerDynamicBodies();
    this.installCollisionHandler();

    this.startX = this.chassis.position.x;
    this.maxX = this.startX;
    this.prevAngle = this.chassis.angle;
  }

  private buildRobot(): void {
    const { design, arena } = this;
    const world = this.engine.world;
    const group = Body.nextGroup(true); // robot bodies never self-collide

    const groundTop = this.groundTopAt(arena.start.x);
    const extent = this.lowestExtent();
    const spawnX = arena.start.x;
    const spawnY = groundTop - extent - 6;

    const chassisArea = design.chassis.width * design.chassis.height;
    this.chassis = Bodies.rectangle(spawnX, spawnY, design.chassis.width, design.chassis.height, {
      chamfer: { radius: 6 },
      friction: 0.6,
      restitution: 0.1,
      collisionFilter: { group },
      label: 'chassis',
      mass: chassisArea / 180,
    });

    // Fixed-mount parts (thruster/sensor/stabilizer/glow) add mass to the hull.
    let fixedMass = 0;
    this.hasSensor = false;
    for (const part of design.parts) {
      if (part.type === 'thruster' || part.type === 'sensor' || part.type === 'stabilizer' || part.type === 'glow') {
        fixedMass += part.type === 'glow' ? 0.4 : part.type === 'sensor' ? 1 : 3.5;
      }
      if (part.type === 'sensor') {
        this.hasSensor = true;
        this.sensorSensitivity = part.tuning.sensitivity ?? 0.6;
      }
    }
    Body.setMass(this.chassis, this.chassis.mass + fixedMass);
    Composite.add(world, this.chassis);

    let thrusterIndex = 0;
    for (const part of design.parts) {
      const ax = spawnX + part.anchor.x;
      const ay = spawnY + part.anchor.y;
      switch (part.type) {
        case 'wheel': {
          const r = part.tuning.radius;
          const wheel = Bodies.circle(ax, ay, r, {
            friction: part.tuning.grip,
            frictionStatic: part.tuning.grip * 1.4,
            restitution: 0.08,
            density: 0.0035,
            collisionFilter: { group },
            label: 'wheel',
          });
          const axle = Constraint.create({
            bodyA: this.chassis,
            pointA: { x: part.anchor.x, y: part.anchor.y },
            bodyB: wheel,
            pointB: { x: 0, y: 0 },
            stiffness: 0.9,
            length: 0,
          });
          Composite.add(world, [wheel, axle]);
          this.runtimes.push({ kind: 'wheel', part, body: wheel });
          break;
        }
        case 'leg': {
          const len = part.tuning.length;
          // Segments carry real mass so the constraint solver doesn't fold
          // them under the chassis weight.
          const upper = Bodies.rectangle(ax, ay + len / 2, 7, len, {
            friction: 0.4,
            density: 0.012,
            collisionFilter: { group },
            chamfer: { radius: 3 },
            label: 'leg-upper',
          });
          const lower = Bodies.rectangle(ax, ay + len * 1.5, 7, len, {
            friction: 1.3,
            frictionStatic: 1.6,
            density: 0.012,
            collisionFilter: { group },
            chamfer: { radius: 3 },
            label: 'leg-lower',
          });
          const hip = Constraint.create({
            bodyA: this.chassis,
            pointA: { x: part.anchor.x, y: part.anchor.y },
            bodyB: upper,
            pointB: { x: 0, y: -len / 2 },
            stiffness: 1,
            length: 0,
          });
          const knee = Constraint.create({
            bodyA: upper,
            pointA: { x: 0, y: len / 2 },
            bodyB: lower,
            pointB: { x: 0, y: -len / 2 },
            stiffness: 1,
            length: 0,
          });
          Composite.add(world, [upper, lower, hip, knee]);
          this.runtimes.push({ kind: 'leg', part, upper, lower });
          break;
        }
        case 'spring': {
          const len = part.tuning.length;
          const foot = Bodies.circle(ax, ay + len, 7, {
            friction: 1.2,
            frictionStatic: 1.5,
            restitution: 0.15,
            density: 0.004,
            frictionAir: 0.02,
            collisionFilter: { group },
            label: 'foot',
          });
          const strut = Constraint.create({
            bodyA: this.chassis,
            pointA: { x: part.anchor.x, y: part.anchor.y },
            bodyB: foot,
            pointB: { x: 0, y: 0 },
            stiffness: part.tuning.stiffness,
            damping: part.tuning.damping,
            length: len,
          });
          Composite.add(world, [foot, strut]);
          this.runtimes.push({ kind: 'spring', part, foot, strut });
          break;
        }
        case 'thruster': {
          const rt: ThrusterRuntime = {
            kind: 'thruster',
            part,
            phaseOffset: thrusterIndex * 0.45,
            firing: false,
            recoveryUntil: 0,
          };
          thrusterIndex += 1;
          this.runtimes.push(rt);
          this.thrusterRuntimes.push(rt);
          break;
        }
        case 'stabilizer': {
          this.runtimes.push({ kind: 'stabilizer', part });
          break;
        }
        default:
          break; // sensor and glow have no runtime behavior beyond flags/visuals
      }
    }
  }

  private groundTopAt(x: number): number {
    let top = Infinity;
    for (const t of this.arena.terrain) {
      if (Math.abs(t.angle ?? 0) > 0.01) continue;
      if (x >= t.x - t.w / 2 && x <= t.x + t.w / 2) {
        top = Math.min(top, t.y - t.h / 2);
      }
    }
    return Number.isFinite(top) ? top : this.arena.start.y + 48;
  }

  /** Distance from chassis center to the lowest part tip at spawn. */
  private lowestExtent(): number {
    let extent = this.design.chassis.height / 2;
    for (const p of this.design.parts) {
      if (p.type === 'wheel') extent = Math.max(extent, p.anchor.y + p.tuning.radius);
      if (p.type === 'leg') extent = Math.max(extent, p.anchor.y + p.tuning.length * 2 + 4);
      if (p.type === 'spring') extent = Math.max(extent, p.anchor.y + p.tuning.length + 8);
    }
    return extent;
  }

  private registerDynamicBodies(): void {
    const hue = this.design.hue;
    const push = (body: Matter.Body, desc: DrawBodyDesc) => {
      this.dynamicBodies.push(body);
      this.bodyDescs.push(desc);
    };
    push(this.chassis, {
      role: 'chassis',
      shape: 'rect',
      w: this.design.chassis.width,
      h: this.design.chassis.height,
      r: 0,
      hue,
    });
    for (const rt of this.runtimes) {
      if (rt.kind === 'wheel') {
        push(rt.body, { role: 'wheel', shape: 'circle', w: 0, h: 0, r: rt.part.tuning.radius, hue });
      } else if (rt.kind === 'leg') {
        push(rt.upper, { role: 'leg-upper', shape: 'rect', w: 7, h: rt.part.tuning.length, r: 0, hue });
        push(rt.lower, { role: 'leg-lower', shape: 'rect', w: 7, h: rt.part.tuning.length, r: 0, hue });
      } else if (rt.kind === 'spring') {
        push(rt.foot, { role: 'foot', shape: 'circle', w: 0, h: 0, r: 7, hue });
      }
    }
    for (const s of this.seesawBodies) {
      push(s, { role: 'seesaw', shape: 'rect', w: s.bounds.max.x - s.bounds.min.x, h: 12, r: 0, hue: -1 });
    }
    for (const p of this.platforms) {
      push(p.body, { role: 'platform', shape: 'rect', w: p.def.w, h: p.def.h, r: 0, hue: -1 });
    }
  }

  private installCollisionHandler(): void {
    Events.on(this.engine, 'collisionStart', (event) => {
      if (this.status !== 'running') return;
      if (this.t < 0.5) return; // ignore the spawn settle
      for (const pair of event.pairs) {
        const isChassis = pair.bodyA === this.chassis || pair.bodyB === this.chassis;
        if (!isChassis) continue;
        const other = pair.bodyA === this.chassis ? pair.bodyB : pair.bodyA;
        const rvx = this.chassis.velocity.x - other.velocity.x;
        const rvy = this.chassis.velocity.y - other.velocity.y;
        const speed = Math.hypot(rvx, rvy);
        if (speed > CRASH_SPEED && this.t >= this.crashCooldownUntil) {
          this.crashes += 1;
          this.crashCooldownUntil = this.t + 0.6;
        }
      }
    });
  }

  // -------------------------------------------------------------------------
  // Lifecycle
  // -------------------------------------------------------------------------

  start(): void {
    if (this.status === 'ready') this.status = 'running';
  }

  pause(): void {
    if (this.status === 'running') this.status = 'paused';
  }

  resume(): void {
    if (this.status === 'paused') this.status = 'running';
  }

  reset(): void {
    this.buildWorld();
  }

  isOver(): boolean {
    return this.status === 'finished' || this.status === 'failed';
  }

  /** Advance by real elapsed ms at the given speed. Steps fixed 60 Hz ticks. */
  step(realDtMs: number, speed = 1): void {
    if (this.status !== 'running') return;
    this.accumulator += Math.min(realDtMs, 100) * speed;
    let safety = 0;
    while (this.accumulator >= TICK_MS && safety < 20) {
      this.tick();
      this.accumulator -= TICK_MS;
      safety += 1;
      if (this.status !== 'running') {
        this.accumulator = 0;
        break;
      }
    }
  }

  /** One fixed 60 Hz tick. Public for headless tests and auto-run loops. */
  tick(): void {
    if (this.status !== 'running') return;

    this.updatePlatforms();
    this.applyControllers();
    this.applyZones();

    Engine.update(this.engine, TICK_MS);

    this.t += DT;
    this.tickCount += 1;
    this.updateTelemetry();
    if (this.tickCount % 2 === 0 && this.replayFrames.length < MAX_REPLAY_FRAMES) {
      this.captureReplayFrame();
    }
    this.checkEndConditions();
  }

  // -------------------------------------------------------------------------
  // Per-tick systems
  // -------------------------------------------------------------------------

  private updatePlatforms(): void {
    for (const p of this.platforms) {
      const phase = ((this.t / p.def.period) * Math.PI * 2) + (p.def.phase ?? 0);
      const nextPhase = (((this.t + DT) / p.def.period) * Math.PI * 2) + (p.def.phase ?? 0);
      const off = Math.sin(phase);
      const offNext = Math.sin(nextPhase);
      const x = p.base.x + p.def.dx * off;
      const y = p.base.y + p.def.dy * off;
      const vx = (p.def.dx * (offNext - off)) / DT;
      const vy = (p.def.dy * (offNext - off)) / DT;
      Body.setPosition(p.body, { x, y });
      Body.setVelocity(p.body, { x: vx * DT, y: vy * DT });
    }
  }

  private limp(): number {
    return this.energyUsed < this.battery ? 1 : LIMP_FACTOR;
  }

  private applyControllers(): void {
    const limp = this.limp();
    const chassisTilt = wrapAngle(this.chassis.angle);

    for (const rt of this.runtimes) {
      switch (rt.kind) {
        case 'wheel': {
          const { power, direction } = rt.part.tuning;
          // Convert rad/s targets to Matter's per-tick angular velocity.
          const target = direction * power * WHEEL_MAX_SPIN * limp * DT;
          const current = rt.body.angularVelocity;
          const maxDelta = WHEEL_SPIN_ACCEL * Math.max(0.2, power) * DT * DT;
          const delta = clamp(target - current, -maxDelta, maxDelta);
          Body.setAngularVelocity(rt.body, current + delta);
          this.energyUsed += (Math.abs(delta) / DT) * 0.05 * (rt.part.tuning.radius / 16) * DT;
          this.partActivity[rt.part.id] = Math.min(
            1,
            Math.abs(rt.body.angularVelocity) / (WHEEL_MAX_SPIN * DT),
          );
          break;
        }
        case 'leg': {
          const { power, frequency, phase, swing } = rt.part.tuning;
          const kneeBias = rt.part.tuning.kneeBias ?? -0.25;
          const kneeLag = rt.part.tuning.kneeLag ?? 1.15;
          const cycle = Math.PI * 2 * frequency * this.t + phase;
          const upperTarget = this.chassis.angle + swing * Math.sin(cycle);
          // Knee lags the hip so the leg is extended on the back-swing
          // (stance push) and folded on the forward swing (recovery step).
          const lowerTarget = rt.upper.angle + kneeBias + swing * 0.65 * Math.sin(cycle - kneeLag);
          this.driveSegment(rt.upper, upperTarget, power * limp);
          this.driveSegment(rt.lower, lowerTarget, power * limp);
          this.partActivity[rt.part.id] = Math.abs(Math.sin(cycle));
          break;
        }
        case 'spring': {
          const dx = rt.foot.position.x - this.chassis.position.x;
          const dy = rt.foot.position.y - this.chassis.position.y;
          const stretch = Math.abs(Math.hypot(dx, dy) - rt.strut.length) / rt.strut.length;
          this.partActivity[rt.part.id] = Math.min(1, stretch * 3);
          break;
        }
        case 'thruster': {
          const { power, interval, burn } = rt.part.tuning;
          const cycleT = (this.t + rt.phaseOffset) % interval;
          const scheduled = cycleT < burn;
          // Sensor feedback: recovery burns on excessive tilt OR free-fall
          // (auto-jump). Without a sensor, thrusters run open-loop rhythm only.
          const tilted = Math.abs(chassisTilt) > 1.25 - this.sensorSensitivity;
          const falling = this.chassis.velocity.y > 5.5 - this.sensorSensitivity * 2.5;
          if (this.hasSensor && (tilted || falling) && this.t > rt.recoveryUntil + 0.7) {
            rt.recoveryUntil = this.t + 0.35;
          }
          const recovering = this.t < rt.recoveryUntil;
          const hasCharge = this.energyUsed < this.battery;
          rt.firing = hasCharge && (scheduled || recovering);
          if (rt.firing) {
            const dir = this.chassis.angle + rt.part.angle;
            // Part angle 0 = thrust straight up (chassis frame); positive
            // tilts the thrust toward +x. Force is gimballed through the
            // center of mass so burns translate instead of tumbling the hull.
            const fx = Math.sin(dir);
            const fy = -Math.cos(dir);
            const mag = power * THRUST_ACCEL * this.chassis.mass * 0.001;
            Body.applyForce(this.chassis, this.chassis.position, { x: fx * mag, y: fy * mag });
            this.energyUsed += 7 * power * DT;
          }
          this.partActivity[rt.part.id] = rt.firing ? 1 : 0;
          break;
        }
        case 'stabilizer': {
          const { strength, damping } = rt.part.tuning;
          const omegaTick = this.chassis.angularVelocity; // rad/tick
          const omega = omegaTick / DT; // rad/s
          const accel = -(strength * STABILIZER_K * chassisTilt) - damping * STABILIZER_D * omega;
          Body.setAngularVelocity(this.chassis, omegaTick + accel * DT * DT * limp);
          this.energyUsed += Math.abs(accel) * DT * 0.06;
          this.partActivity[rt.part.id] = Math.min(1, Math.abs(accel) / STABILIZER_K);
          break;
        }
      }
    }
  }

  /**
   * Servo-style joint motor for a leg segment: velocity tracking plus a small
   * direct position correction. Position-controlled servos are what let legs
   * hold the chassis weight; contacts and collisions still resolve normally.
   */
  private driveSegment(seg: Matter.Body, targetAngle: number, power: number): void {
    const err = wrapAngle(targetAngle - seg.angle);
    const desired = clamp(err * LEG_GAIN, -LEG_MAX_SPIN, LEG_MAX_SPIN) * DT;
    const blend = clamp(0.25 + 0.65 * power, 0, 0.92);
    const prev = seg.angularVelocity;
    const next = prev + (desired - prev) * blend;
    Body.setAngularVelocity(seg, next);
    const holdBlend = 0.06 + 0.12 * power;
    Body.setAngle(seg, seg.angle + err * holdBlend);
    this.energyUsed += ((Math.abs(next - prev) / DT) * 0.008 + Math.abs(err) * holdBlend * 0.2) * DT;
  }

  private applyZones(): void {
    const g = this.arena.gravityY;
    for (let i = 0; i < this.dynamicBodies.length; i++) {
      const body = this.dynamicBodies[i];
      if (body.isStatic) continue;
      const { x, y } = body.position;
      for (const z of this.arena.windZones) {
        if (x < z.x - z.w / 2 || x > z.x + z.w / 2 || y < z.y - z.h / 2 || y > z.y + z.h / 2) continue;
        const gustFactor = z.gust
          ? 1 + z.gust * Math.sin((Math.PI * 2 * this.t) / (z.gustPeriod ?? 2))
          : 1;
        Body.applyForce(body, body.position, {
          x: body.mass * 0.001 * z.fx * gustFactor,
          y: body.mass * 0.001 * z.fy * gustFactor,
        });
      }
      for (const z of this.arena.gravityZones) {
        if (x < z.x - z.w / 2 || x > z.x + z.w / 2 || y < z.y - z.h / 2 || y > z.y + z.h / 2) continue;
        // Counteract a fraction of gravity: scale=0.3 means bodies feel 30% g.
        Body.applyForce(body, body.position, {
          x: 0,
          y: -body.mass * 0.001 * g * (1 - z.scale),
        });
      }
    }
  }

  private updateTelemetry(): void {
    const angle = this.chassis.angle;
    this.cumRotation += wrapAngle(angle - this.prevAngle);
    this.prevAngle = angle;
    this.tiltAccum += Math.abs(wrapAngle(angle));
    this.maxX = Math.max(this.maxX, this.chassis.position.x);
  }

  private captureReplayFrame(): void {
    let mask = 0;
    for (let i = 0; i < this.thrusterRuntimes.length && i < 30; i++) {
      if (this.thrusterRuntimes[i].firing) mask |= 1 << i;
    }
    this.replayFrames.push(
      encodeFrame(
        this.dynamicBodies.map((b) => ({ x: b.position.x, y: b.position.y, angle: b.angle })),
        mask,
      ),
    );
  }

  private checkEndConditions(): void {
    const pos = this.chassis.position;
    if (!Number.isFinite(pos.x) || !Number.isFinite(pos.y)) {
      this.finishRun(false, 'Simulation destabilized');
      return;
    }
    const f = this.arena.finish;
    if (Math.abs(pos.x - f.x) < f.w / 2 && Math.abs(pos.y - f.y) < f.h / 2) {
      this.completed = true;
      this.finishRun(true);
      return;
    }
    if (pos.y > this.arena.killY) {
      this.finishRun(false, 'Fell into the void');
      return;
    }
    if (this.t >= this.arena.timeLimit) {
      this.finishRun(false, 'Time limit exceeded');
    }
  }

  private finishRun(completed: boolean, failReason?: string): void {
    this.status = completed ? 'finished' : 'failed';
    this.failReason = failReason;
    const result: RunEndResult = {
      telemetry: this.getTelemetry(),
      replayBodies: this.bodyDescs,
      replayFrames: this.replayFrames,
    };
    for (const l of this.endListeners) l(result);
  }

  // -------------------------------------------------------------------------
  // Read APIs
  // -------------------------------------------------------------------------

  getTelemetry(): Telemetry {
    return {
      t: round2(this.t),
      distance: round2(this.chassis.position.x - this.startX),
      maxX: round2(this.maxX),
      progress: round3(arenaProgress(this.arena, this.maxX)),
      energyUsed: round2(Math.min(this.energyUsed, this.battery * 2)),
      batteryCapacity: this.battery,
      flips: Math.floor(Math.abs(this.cumRotation) / (Math.PI * 2)),
      crashes: this.crashes,
      avgTilt: this.tickCount > 0 ? round3(this.tiltAccum / this.tickCount) : 0,
      completed: this.completed,
      failed: this.status === 'failed',
      failReason: this.failReason,
    };
  }

  getFrame(): SimFrame {
    let wind: { x: number; y: number } | null = null;
    const { x, y } = this.chassis.position;
    for (const z of this.arena.windZones) {
      if (x > z.x - z.w / 2 && x < z.x + z.w / 2 && y > z.y - z.h / 2 && y < z.y + z.h / 2) {
        wind = { x: z.fx, y: z.fy };
        break;
      }
    }
    return {
      t: this.t,
      status: this.status,
      bodies: this.dynamicBodies.map((b) => ({ x: b.position.x, y: b.position.y, angle: b.angle })),
      chassis: {
        x: this.chassis.position.x,
        y: this.chassis.position.y,
        angle: this.chassis.angle,
        vx: this.chassis.velocity.x,
        vy: this.chassis.velocity.y,
      },
      thrusters: this.thrusterRuntimes.map((rt) => {
        const p = this.chassisPoint(rt.part.anchor.x, rt.part.anchor.y);
        return {
          partId: rt.part.id,
          x: p.x,
          y: p.y,
          angle: this.chassis.angle + rt.part.angle,
          firing: rt.firing,
          power: rt.part.tuning.power,
        };
      }),
      partActivity: { ...this.partActivity },
      batteryFrac: Math.max(0, 1 - this.energyUsed / this.battery),
      windSample: wind,
    };
  }

  getBodyDescs(): DrawBodyDesc[] {
    return this.bodyDescs;
  }

  private chassisPoint(localX: number, localY: number): { x: number; y: number } {
    const cos = Math.cos(this.chassis.angle);
    const sin = Math.sin(this.chassis.angle);
    return {
      x: this.chassis.position.x + localX * cos - localY * sin,
      y: this.chassis.position.y + localX * sin + localY * cos,
    };
  }
}

// ---------------------------------------------------------------------------

export function wrapAngle(a: number): number {
  let r = a % (Math.PI * 2);
  if (r > Math.PI) r -= Math.PI * 2;
  if (r < -Math.PI) r += Math.PI * 2;
  return r;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}

function round3(v: number): number {
  return Math.round(v * 1000) / 1000;
}
