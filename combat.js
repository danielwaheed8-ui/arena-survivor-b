// combat.js (CHILD-3, part 1) — projectiles + collision + power-ups + upgrades.
// PURE math/data over plain JS objects. NO three, NO window/document/THREE.
// Deterministic: never Math.random(); only state.rng() for any randomness.

const ARENA_HALF = 40; // matches entities.js ARENA_HALF (kept local to avoid cross-import)

// ---- tunables -------------------------------------------------------------
const BASE_FIRE_COOLDOWN = 0.28; // seconds between shots
const PROJ_SPEED = 28;           // world units / second
const PROJ_TTL = 1.2;            // seconds
const PROJ_RADIUS = 0.25;
const PROJ_BASE_DAMAGE = 2;
const DAMAGE_PER_UPGRADE = 1;    // +damage per upgrades.damage level
const SPREAD_ANGLE = 0.22;       // radians between spread shots
const PLAYER_INVULN = 0.6;       // i-frames after taking a hit
const PLAYER_HITFLASH = 0.15;
const ENEMY_HITFLASH = 0.1;
const KNOCKBACK_ENEMY = 6;       // impulse applied to enemy on hit
const KNOCKBACK_PLAYER = 5;      // impulse applied to player on hit
const POWERUP_DROP_CHANCE = 0.15;
const POWERUP_TTL = 12;
const BUFF_SECONDS = 6;
const HEALTH_PICKUP_HEAL = 30;
const MUZZLE_OFFSET = 1.0;       // spawn projectile this far ahead of player

// score reward per enemy type
const REWARD = { chaser: 10, shooter: 15, tank: 25, splitter: 15, boss: 200 };
const POWERUP_KINDS = ['health', 'rapidFire', 'spread', 'speed'];

// ---- helpers --------------------------------------------------------------
function normalize(x, z) {
  const len = Math.hypot(x, z);
  if (len < 1e-6) return { x: 0, z: 1 };
  return { x: x / len, z: z / len };
}

function makeProjectile(state, x, z, vx, vz, damage) {
  return {
    id: state.nextId++,
    pos: { x, z },
    vel: { x: vx, z: vz },
    radius: PROJ_RADIUS,
    damage,
    fromPlayer: true,
    ttl: PROJ_TTL,
    dead: false,
  };
}

// Inline enemy creation for splitter death spawns (avoids importing entities.js).
function makeChaser(state, x, z) {
  return {
    id: state.nextId++,
    type: 'chaser',
    pos: { x, z },
    vel: { x: 0, z: 0 },
    hp: 3,
    maxHp: 3,
    radius: 0.9,
    speed: 6,
    damage: 10,
    hitFlash: 0,
    fireCooldown: 0,
    spawnScale: 0,
    dead: false,
  };
}

function clampArena(v) {
  if (v > ARENA_HALF) return ARENA_HALF;
  if (v < -ARENA_HALF) return -ARENA_HALF;
  return v;
}

// ---- exports --------------------------------------------------------------

export function fire(state, dirX, dirZ) {
  const p = state.player;
  if (p.fireCooldown > 0) return;

  const dir = normalize(dirX, dirZ);
  p.aim.x = dir.x;
  p.aim.z = dir.z;

  const damage = PROJ_BASE_DAMAGE + (state.upgrades.damage || 0) * DAMAGE_PER_UPGRADE;
  const ox = p.pos.x + dir.x * MUZZLE_OFFSET;
  const oz = p.pos.z + dir.z * MUZZLE_OFFSET;

  // spread (3 shots) while buffs.spread>0, else single shot
  const angles = state.buffs.spread > 0 ? [-SPREAD_ANGLE, 0, SPREAD_ANGLE] : [0];
  for (const a of angles) {
    const cos = Math.cos(a);
    const sin = Math.sin(a);
    // rotate dir by angle a in XZ plane
    const rx = dir.x * cos - dir.z * sin;
    const rz = dir.x * sin + dir.z * cos;
    state.projectiles.push(
      makeProjectile(state, ox, oz, rx * PROJ_SPEED, rz * PROJ_SPEED, damage)
    );
  }

  // cooldown: reduced by fireRate upgrade, halved while rapidFire buff active
  let cd = BASE_FIRE_COOLDOWN / (1 + (state.upgrades.fireRate || 0) * 0.25);
  if (state.buffs.rapidFire > 0) cd *= 0.5;
  p.fireCooldown = cd;

  state.events.push({ type: 'shoot', x: ox, z: oz });
  state.events.push({ type: 'muzzle', x: ox, z: oz, dx: dir.x, dz: dir.z });
}

export function updateProjectiles(state, dt) {
  for (const pr of state.projectiles) {
    pr.pos.x += pr.vel.x * dt;
    pr.pos.z += pr.vel.z * dt;
    pr.ttl -= dt;
    if (pr.ttl <= 0 || Math.abs(pr.pos.x) > ARENA_HALF || Math.abs(pr.pos.z) > ARENA_HALF) {
      pr.dead = true;
    }
  }
}

export function resolveCollisions(state) {
  const player = state.player;
  const splitterSpawns = [];

  // --- PLAYER projectiles vs enemies ---
  for (const pr of state.projectiles) {
    if (pr.dead || !pr.fromPlayer) continue;
    for (const e of state.enemies) {
      if (e.dead) continue;
      const dx = e.pos.x - pr.pos.x;
      const dz = e.pos.z - pr.pos.z;
      const rr = e.radius + pr.radius;
      if (dx * dx + dz * dz > rr * rr) continue;

      // hit
      e.hp -= pr.damage;
      e.hitFlash = ENEMY_HITFLASH;
      pr.dead = true;

      // knockback along projectile travel direction
      const pdir = normalize(pr.vel.x, pr.vel.z);
      e.vel.x += pdir.x * KNOCKBACK_ENEMY;
      e.vel.z += pdir.z * KNOCKBACK_ENEMY;

      state.events.push({ type: 'hit', x: pr.pos.x, z: pr.pos.z });

      if (e.hp <= 0) {
        e.dead = true;
        const reward = REWARD[e.type] || 10;
        state.score += reward;
        state.events.push({ type: 'enemyDeath', x: e.pos.x, z: e.pos.z, etype: e.type });
        state.events.push({ type: 'explosion', x: e.pos.x, z: e.pos.z, scale: e.radius });

        // powerup drop (boss always drops)
        const drops = e.type === 'boss' || state.rng() < POWERUP_DROP_CHANCE;
        if (drops) {
          const kind = POWERUP_KINDS[Math.floor(state.rng() * POWERUP_KINDS.length) % POWERUP_KINDS.length];
          state.powerups.push({
            id: state.nextId++,
            kind,
            pos: { x: e.pos.x, z: e.pos.z },
            ttl: POWERUP_TTL,
            bob: 0,
          });
        }

        // splitter -> 2 chasers near its position (deterministic offsets via rng)
        if (e.type === 'splitter') {
          for (let i = 0; i < 2; i++) {
            const ang = state.rng() * Math.PI * 2;
            const ox = clampArena(e.pos.x + Math.cos(ang) * 1.2);
            const oz = clampArena(e.pos.z + Math.sin(ang) * 1.2);
            splitterSpawns.push(makeChaser(state, ox, oz));
          }
        }
      }
      break; // projectile consumed
    }
  }

  for (const s of splitterSpawns) state.enemies.push(s);

  // --- ENEMY projectiles vs player ---
  for (const pr of state.projectiles) {
    if (pr.dead || pr.fromPlayer) continue;
    const dx = player.pos.x - pr.pos.x;
    const dz = player.pos.z - pr.pos.z;
    const rr = player.radius + pr.radius;
    if (dx * dx + dz * dz > rr * rr) continue;
    pr.dead = true;
    damagePlayer(state, pr.damage, normalize(pr.vel.x, pr.vel.z));
    if (state.gameOver) break;
  }

  // --- enemy-body vs player ---
  if (!state.gameOver) {
    for (const e of state.enemies) {
      if (e.dead) continue;
      const dx = player.pos.x - e.pos.x;
      const dz = player.pos.z - e.pos.z;
      const rr = player.radius + e.radius;
      if (dx * dx + dz * dz > rr * rr) continue;
      // knock the enemy back a touch too (deterministic)
      const away = normalize(dx, dz);
      e.vel.x -= away.x * (KNOCKBACK_ENEMY * 0.5);
      e.vel.z -= away.z * (KNOCKBACK_ENEMY * 0.5);
      damagePlayer(state, e.damage, away);
      if (state.gameOver) break;
    }
  }

  // --- remove dead projectiles & enemies ---
  if (state.projectiles.some((p) => p.dead)) {
    state.projectiles = state.projectiles.filter((p) => !p.dead);
  }
  if (state.enemies.some((e) => e.dead)) {
    state.enemies = state.enemies.filter((e) => !e.dead);
  }
}

function damagePlayer(state, damage, awayDir) {
  const player = state.player;
  if (player.invuln > 0) return;
  state.health -= damage;
  player.invuln = PLAYER_INVULN;
  player.hitFlash = PLAYER_HITFLASH;
  // knockback player away from the hit source
  player.vel.x += awayDir.x * KNOCKBACK_PLAYER;
  player.vel.z += awayDir.z * KNOCKBACK_PLAYER;
  state.events.push({ type: 'playerHurt', x: player.pos.x, z: player.pos.z });
  if (state.health <= 0) {
    state.health = 0;
    state.gameOver = true;
    state.events.push({ type: 'gameOver' });
  }
}

export function updatePowerups(state, dt) {
  const player = state.player;
  for (const pu of state.powerups) {
    pu.bob += dt;
    pu.ttl -= dt;
    if (pu.ttl <= 0) {
      pu._picked = true; // expired
      continue;
    }
    const dx = player.pos.x - pu.pos.x;
    const dz = player.pos.z - pu.pos.z;
    const rr = player.radius + 0.8;
    if (dx * dx + dz * dz > rr * rr) continue;

    // pickup
    if (pu.kind === 'health') {
      state.health = Math.min(state.maxHealth, state.health + HEALTH_PICKUP_HEAL);
    } else if (pu.kind === 'rapidFire') {
      state.buffs.rapidFire = BUFF_SECONDS;
    } else if (pu.kind === 'spread') {
      state.buffs.spread = BUFF_SECONDS;
    } else if (pu.kind === 'speed') {
      state.buffs.speed = BUFF_SECONDS;
    }
    state.events.push({ type: 'pickup', x: pu.pos.x, z: pu.pos.z, kind: pu.kind });
    pu._picked = true;
  }
  if (state.powerups.some((p) => p._picked)) {
    state.powerups = state.powerups.filter((p) => !p._picked);
  }
}

export function applyUpgrade(state, kind) {
  if (!(kind in state.upgrades)) return false;
  const level = state.upgrades[kind];
  const cost = (level + 1) * 100;
  if (state.score < cost) return false;
  state.score -= cost;
  state.upgrades[kind]++;
  if (kind === 'maxHealth') {
    state.maxHealth += 20;
    state.health = Math.min(state.maxHealth, state.health + 20);
  }
  return true;
}

export function tickBuffs(state, dt) {
  const b = state.buffs;
  b.rapidFire = Math.max(0, b.rapidFire - dt);
  b.spread = Math.max(0, b.spread - dt);
  b.speed = Math.max(0, b.speed - dt);
}
