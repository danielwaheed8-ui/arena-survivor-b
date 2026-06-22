// entities.js (CHILD-2) — player + input physics, enemies + AI + wave spawner + boss.
// PURE data/math over plain objects. NO three, NO window/document/THREE/AudioContext.
// Deterministic: all randomness via state.rng() (never Math.random()).

export const ARENA_HALF = 40;

// ---- tuning constants -------------------------------------------------------
const PLAYER_BASE_SPEED = 12;     // u/s base, scaled by upgrades + speed buff
const PLAYER_ACCEL = 90;          // how fast vel chases the desired velocity
const PLAYER_FRICTION = 10;       // per-second exponential-ish decay when no input
const DASH_SPEED = 38;            // velocity magnitude granted by a dash impulse
const DASH_COOLDOWN = 1.2;        // seconds between dashes
const SPAWN_RAMP = 0.3;           // seconds for spawnScale 0->1

// shooter / boss firing
const SHOOTER_RANGE = 18;         // preferred standoff distance
const SHOOTER_FIRE_CD = 1.5;
const ENEMY_PROJ_SPEED = 14;
const ENEMY_PROJ_RADIUS = 0.35;
const ENEMY_PROJ_TTL = 5;
const BOSS_FIRE_CD = 2.4;
const BOSS_SPREAD = 5;            // number of pellets in the boss spread
const BOSS_SPREAD_ARC = 0.9;      // total arc (radians) of the spread

// ---- small vector helpers ---------------------------------------------------
function len2(x, z) { return Math.sqrt(x * x + z * z); }

function clampArena(pos, radius) {
  const lim = ARENA_HALF - radius;
  if (pos.x > lim) pos.x = lim; else if (pos.x < -lim) pos.x = -lim;
  if (pos.z > lim) pos.z = lim; else if (pos.z < -lim) pos.z = -lim;
}

// ---- player -----------------------------------------------------------------
export function updatePlayer(state, dt, input) {
  const p = state.player;
  input = input || {};
  const moveX = input.moveX || 0;
  const moveZ = input.moveZ || 0;

  // effective top speed
  const upMove = (state.upgrades && state.upgrades.moveSpeed) || 0;
  const speedBuff = (state.buffs && state.buffs.speed > 0) ? 1.5 : 1;
  const topSpeed = PLAYER_BASE_SPEED * (1 + 0.12 * upMove) * speedBuff;

  const mag = len2(moveX, moveZ);
  if (mag > 1e-6) {
    // desired velocity in the input direction (clamp input magnitude to 1)
    const inv = (mag > 1 ? 1 / mag : 1);
    const dx = moveX * inv, dz = moveZ * inv;
    const desX = dx * topSpeed, desZ = dz * topSpeed;
    // accelerate vel toward desired (frame-rate independent)
    const t = Math.min(1, PLAYER_ACCEL * dt / Math.max(topSpeed, 1));
    p.vel.x += (desX - p.vel.x) * t;
    p.vel.z += (desZ - p.vel.z) * t;
    // update aim from movement if no explicit aim given
    if (input.aimX === undefined && input.aimZ === undefined) {
      p.aim.x = dx; p.aim.z = dz;
    }
  } else {
    // friction decay toward zero
    const f = Math.max(0, 1 - PLAYER_FRICTION * dt);
    p.vel.x *= f;
    p.vel.z *= f;
  }

  // explicit aim (mouse) wins when provided
  if (input.aimX !== undefined || input.aimZ !== undefined) {
    const ax = input.aimX || 0, az = input.aimZ || 0;
    const am = len2(ax, az);
    if (am > 1e-6) { p.aim.x = ax / am; p.aim.z = az / am; }
  }

  // dash impulse
  if (input.dash && p.dashCooldown <= 0) {
    // dash along aim if we have one, else along current movement, else current vel
    let dx = p.aim.x, dz = p.aim.z;
    if (mag > 1e-6) { const inv = 1 / mag; dx = moveX * inv; dz = moveZ * inv; }
    const dl = len2(dx, dz);
    if (dl > 1e-6) { dx /= dl; dz /= dl; } else { dx = 0; dz = 1; }
    p.vel.x = dx * DASH_SPEED;
    p.vel.z = dz * DASH_SPEED;
    p.dashCooldown = DASH_COOLDOWN;
  }

  // integrate
  p.pos.x += p.vel.x * dt;
  p.pos.z += p.vel.z * dt;
  clampArena(p.pos, p.radius);

  // decrement timers
  if (p.fireCooldown > 0) p.fireCooldown = Math.max(0, p.fireCooldown - dt);
  if (p.invuln > 0) p.invuln = Math.max(0, p.invuln - dt);
  if (p.hitFlash > 0) p.hitFlash = Math.max(0, p.hitFlash - dt);
  if (p.dashCooldown > 0) p.dashCooldown = Math.max(0, p.dashCooldown - dt);
}

// ---- enemy stat table -------------------------------------------------------
const ENEMY_STATS = {
  chaser:   { hp: 3,   speed: 6,   radius: 0.9, damage: 10 },
  tank:     { hp: 12,  speed: 2.5, radius: 1.6, damage: 18 },
  shooter:  { hp: 4,   speed: 3.5, radius: 1.0, damage: 8  },
  splitter: { hp: 5,   speed: 4,   radius: 1.1, damage: 10 },
  boss:     { hp: 120, speed: 2,   radius: 3.0, damage: 30 },
};

export function spawnEnemyAt(state, x, z, type = 'chaser') {
  const s = ENEMY_STATS[type] || ENEMY_STATS.chaser;
  const e = {
    id: state.nextId++,
    type,
    pos: { x, z },
    vel: { x: 0, z: 0 },
    hp: s.hp,
    maxHp: s.hp,
    radius: s.radius,
    speed: s.speed,
    damage: s.damage,
    hitFlash: 0,
    fireCooldown: type === 'shooter' ? SHOOTER_FIRE_CD : (type === 'boss' ? BOSS_FIRE_CD : 0),
    spawnScale: 0,
    dead: false,
  };
  state.enemies.push(e);
  return e;
}

// fire one enemy projectile from (x,z) toward a unit direction (dx,dz)
function fireEnemyProjectile(state, x, z, dx, dz, damage) {
  state.projectiles.push({
    id: state.nextId++,
    pos: { x, z },
    vel: { x: dx * ENEMY_PROJ_SPEED, z: dz * ENEMY_PROJ_SPEED },
    radius: ENEMY_PROJ_RADIUS,
    damage,
    fromPlayer: false,
    ttl: ENEMY_PROJ_TTL,
    dead: false,
  });
  state.events.push({ type: 'muzzle', x, z, dx, dz });
}

export function updateEnemies(state, dt) {
  const player = state.player;
  const enemies = state.enemies;
  for (let i = 0; i < enemies.length; i++) {
    const e = enemies[i];
    if (e.dead) continue;

    // ramp spawn pop
    if (e.spawnScale < 1) e.spawnScale = Math.min(1, e.spawnScale + dt / SPAWN_RAMP);
    if (e.hitFlash > 0) e.hitFlash = Math.max(0, e.hitFlash - dt);

    // vector toward player
    let toX = player.pos.x - e.pos.x;
    let toZ = player.pos.z - e.pos.z;
    const dist = len2(toX, toZ);
    const nX = dist > 1e-6 ? toX / dist : 0;
    const nZ = dist > 1e-6 ? toZ / dist : 1;

    // desired velocity per type
    let desX, desZ;
    if (e.type === 'shooter') {
      // approach to preferred range, then strafe/hold
      if (dist > SHOOTER_RANGE + 1.5) {
        desX = nX * e.speed; desZ = nZ * e.speed;          // close in
      } else if (dist < SHOOTER_RANGE - 1.5) {
        desX = -nX * e.speed; desZ = -nZ * e.speed;        // back off
      } else {
        // strafe perpendicular to keep distance (deterministic direction by id parity)
        const side = (e.id & 1) ? 1 : -1;
        desX = -nZ * e.speed * side * 0.6;
        desZ = nX * e.speed * side * 0.6;
      }
      // fire on cooldown
      if (e.fireCooldown > 0) e.fireCooldown = Math.max(0, e.fireCooldown - dt);
      if (e.fireCooldown <= 0 && dist <= SHOOTER_RANGE + 6) {
        fireEnemyProjectile(state, e.pos.x, e.pos.z, nX, nZ, e.damage);
        e.fireCooldown = SHOOTER_FIRE_CD;
      }
    } else if (e.type === 'boss') {
      desX = nX * e.speed; desZ = nZ * e.speed;            // grind toward player
      if (e.fireCooldown > 0) e.fireCooldown = Math.max(0, e.fireCooldown - dt);
      if (e.fireCooldown <= 0) {
        // spread of pellets centered on the player direction
        const base = Math.atan2(nZ, nX);
        const start = base - BOSS_SPREAD_ARC / 2;
        const stepA = BOSS_SPREAD > 1 ? BOSS_SPREAD_ARC / (BOSS_SPREAD - 1) : 0;
        for (let k = 0; k < BOSS_SPREAD; k++) {
          const a = start + stepA * k;
          fireEnemyProjectile(state, e.pos.x, e.pos.z, Math.cos(a), Math.sin(a), e.damage);
        }
        e.fireCooldown = BOSS_FIRE_CD;
      }
    } else {
      // chaser / tank / splitter: steer straight at player
      desX = nX * e.speed; desZ = nZ * e.speed;
    }

    // accelerate vel toward desired velocity (lerp), frame-rate independent
    const accel = 8; // steering responsiveness
    const t = Math.min(1, accel * dt);
    e.vel.x += (desX - e.vel.x) * t;
    e.vel.z += (desZ - e.vel.z) * t;

    // integrate
    e.pos.x += e.vel.x * dt;
    e.pos.z += e.vel.z * dt;
    clampArena(e.pos, e.radius);
  }
}

// ---- waves ------------------------------------------------------------------
export function startWave(state) {
  state.wave++;
  const w = state.wave;
  const roster = [];

  if (w % 5 === 0) {
    // BOSS wave: 1 boss + a handful of adds that scale with wave
    roster.push('boss');
    const adds = 3 + Math.floor(w / 5);
    for (let i = 0; i < adds; i++) {
      roster.push(i % 2 === 0 ? 'chaser' : 'shooter');
    }
  } else {
    // normal wave: count grows with wave, mix of types
    const count = 4 + Math.floor(w * 1.5);
    for (let i = 0; i < count; i++) {
      // weave a deterministic-ish mix that gets meaner with wave number
      const r = state.rng();
      let type = 'chaser';
      if (r < 0.15 + w * 0.01 && w >= 2) type = 'tank';
      else if (r < 0.4 && w >= 3) type = 'shooter';
      else if (r < 0.55 && w >= 2) type = 'splitter';
      else type = 'chaser';
      roster.push(type);
    }
  }

  state.spawnQueue = roster;          // private queue of types to drip-spawn
  state.enemiesToSpawn = roster.length;
  state.spawnTimer = 0;               // first one comes out promptly
  state.waveActive = true;
  state.betweenWaves = false;
  state.events.push({ type: 'waveStart', wave: state.wave });
}

const SPAWN_INTERVAL = 0.6; // seconds between drip spawns

export function updateSpawner(state, dt) {
  if (state.enemiesToSpawn > 0) {
    state.spawnTimer -= dt;
    while (state.spawnTimer <= 0 && state.enemiesToSpawn > 0) {
      // pick a random point on the arena edge
      const queue = state.spawnQueue || [];
      const type = queue.length ? queue.shift() : 'chaser';
      const { x, z } = randomEdgePoint(state);
      spawnEnemyAt(state, x, z, type);
      state.enemiesToSpawn--;
      state.spawnTimer += SPAWN_INTERVAL;
    }
    if (state.spawnTimer < 0) state.spawnTimer = 0;
  }

  // wave fully cleared?
  if (state.waveActive && state.enemiesToSpawn === 0) {
    let alive = false;
    for (let i = 0; i < state.enemies.length; i++) {
      if (!state.enemies[i].dead) { alive = true; break; }
    }
    if (!alive) {
      state.waveActive = false;
      state.betweenWaves = true;
    }
  }
}

function randomEdgePoint(state) {
  const r = state.rng();
  const edge = Math.floor(state.rng() * 4) % 4; // 0..3
  const span = (r * 2 - 1) * (ARENA_HALF - 1);  // position along the chosen edge
  const e = ARENA_HALF - 1;
  if (edge === 0) return { x: span, z: -e };
  if (edge === 1) return { x: e, z: span };
  if (edge === 2) return { x: span, z: e };
  return { x: -e, z: span };
}
