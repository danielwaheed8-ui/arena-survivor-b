// core.js — three-free deterministic game core shared by main.js (browser) and the
// Node test harness. Owns: seeded RNG, state factory, fixed-timestep step ordering,
// and wave/intermission progression. Importing entities.js + combat.js (both three-free)
// here keeps the browser and the headless test on identical logic.
import { updatePlayer, updateEnemies, startWave, updateSpawner, spawnEnemyAt } from './entities.js';
import { fire, updateProjectiles, resolveCollisions, updatePowerups, applyUpgrade, tickBuffs } from './combat.js';

export const FIXED = 1 / 60;
export const MAX_SUBSTEPS = 8;
export const INTERMISSION = 2.5;
export const START_HEALTH = 100;

export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function createInitialState(seed = 0x9e3779b9) {
  const s = {
    time: 0, score: 0, health: START_HEALTH, maxHealth: START_HEALTH,
    wave: 0, gameOver: false,
    player: {
      pos: { x: 0, z: 0 }, vel: { x: 0, z: 0 }, radius: 0.8,
      fireCooldown: 0, invuln: 0, hitFlash: 0, dashCooldown: 0, aim: { x: 0, z: 1 },
    },
    enemies: [], projectiles: [], powerups: [], events: [],
    upgrades: { damage: 0, fireRate: 0, moveSpeed: 0, maxHealth: 0 },
    buffs: { rapidFire: 0, spread: 0, speed: 0 },
    waveActive: false, betweenWaves: true, enemiesToSpawn: 0, spawnTimer: 0,
    intermission: 0, _interArmed: false,
    nextId: 1,
  };
  s.rng = mulberry32(seed);
  return s;
}

// Advance LOGIC deterministically by one fixed substep. Order per CONTRACT.
export function stepLogic(state, dt, input) {
  if (state.gameOver) return;
  updatePlayer(state, dt, input);
  updateSpawner(state, dt);
  updateEnemies(state, dt);
  updateProjectiles(state, dt);
  resolveCollisions(state);
  updatePowerups(state, dt);
  tickBuffs(state, dt);
  state.time += dt;
}

// Wave/intermission progression. Headless stepping auto-advances waves; real play
// freezes logic and lets the upgrade UI call startWave (so this is gated by caller).
export function manageWaves(state, dt) {
  if (state.gameOver) return;
  if (state.betweenWaves) {
    if (!state._interArmed) { state.intermission = INTERMISSION; state._interArmed = true; }
    state.intermission -= dt;
    if (state.intermission <= 0) startWave(state);
  } else {
    state._interArmed = false;
  }
}

export const NEUTRAL_INPUT = { moveX: 0, moveZ: 0, dash: false, aimX: 0, aimZ: 1 };

// a tiny carrier for the fixed-timestep remainder
export function makeStepper() { return { acc: 0 }; }

// Advance logic by dt seconds in fixed substeps, carrying the remainder on `stepper`.
//  - clamp:true  -> real-time render loop: cap catch-up to avoid the spiral of death.
//  - clamp:false -> window.__game.step(dt): honor the FULL dt deterministically.
//  - autoWave:true lets waves auto-advance (headless); real play drives waves via UI.
export function advanceFixed(state, dt, { stepper, inputFn = null, autoWave = false, clamp = false }) {
  stepper.acc += dt;
  if (clamp && stepper.acc > MAX_SUBSTEPS * FIXED) stepper.acc = MAX_SUBSTEPS * FIXED;
  const cap = clamp ? MAX_SUBSTEPS : 1000000;
  let n = 0;
  while (stepper.acc >= FIXED && n < cap) {
    const input = inputFn ? inputFn() : NEUTRAL_INPUT;
    stepLogic(state, FIXED, input);
    if (autoWave) manageWaves(state, FIXED);
    stepper.acc -= FIXED; n++;
  }
}

// re-export the entity/combat verbs the orchestrator wires to the UI + test hook
export { updatePlayer, updateEnemies, startWave, updateSpawner, spawnEnemyAt };
export { fire, updateProjectiles, resolveCollisions, updatePowerups, applyUpgrade, tickBuffs };
