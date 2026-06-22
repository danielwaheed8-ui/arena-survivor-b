# Arena Survivor — SHARED MODULE CONTRACT (read in full, obey exactly)

All three child workers and the orchestrator share THIS contract. It pins down the
data shapes, coordinate conventions, module file names, and export signatures so the
independently-built modules merge cleanly. DO NOT invent different field names or
shapes. If something is unspecified, pick the simplest thing consistent with this doc.

## Tech / environment
- Pure browser ESM. NO build step, NO bundler, NO npm. Runs by opening index.html.
- three.js + addons load from CDN via an import map THE ORCHESTRATOR puts in index.html:
    "three"          -> https://unpkg.com/three@0.160.0/build/three.module.js
    "three/addons/"  -> https://unpkg.com/three@0.160.0/examples/jsm/
  So in modules that need three:  `import * as THREE from 'three';`
  and addons:  `import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';`
- NO network calls during the BUILD (you write code only; the CDN loads at runtime in a browser).
- NO servers, NO irreversible/external tools.

## CRITICAL split rule (keeps modules orthogonal + testable)
- LOGIC modules (entities.js, combat.js, audio.js) MUST NOT `import` three or any addon
  and MUST NOT reference `window`, `document`, `THREE`, `AudioContext` at module top
  level. They are PURE data/math over plain JS objects so they can be unit-tested in
  Node with `node --input-type=module`. (audio.js may reference AudioContext ONLY lazily
  inside functions, guarded by `typeof`.)
- RENDER module (render.js) is the ONLY module that imports three/addons.
- The orchestrator owns index.html, the main loop, fixed-timestep, input, HUD/menus,
  state creation, and window.__game.

## Coordinate system & constants
- World is the XZ ground plane, Y is up. Player & enemies live at y≈0 (logic uses only x,z).
- Arena is a square centered at origin. `ARENA_HALF = 40` (playable region x,z ∈ [-40, 40]).
  Export this constant from entities.js as `export const ARENA_HALF = 40;` and import it
  where needed (combat.js may re-declare its own const 40 if it prefers not to import).
- Distances/speeds are in world units and units/second.

## Determinism (MANDATORY for the test hook)
- NO `Math.random()` anywhere in logic. Use the seeded RNG carried on state:
  `state.rng()` returns a float in [0,1). It is a mulberry32 PRNG. The orchestrator
  creates it in createInitialState; YOU just call `state.rng()`.
- All logic update functions are pure functions of (state, dt, input) — same inputs ->
  same state mutations. Side-effects for visuals/audio go through `state.events` only.

## THE STATE OBJECT (created by orchestrator; you read/write these exact fields)
```js
state = {
  time: 0,            // seconds of logic advanced
  score: 0,
  health: 100,
  maxHealth: 100,
  wave: 0,            // 0 before first wave; becomes 1,2,3...
  gameOver: false,
  player: {
    pos:{x:0,z:0}, vel:{x:0,z:0},
    radius: 0.8,
    fireCooldown: 0,  // s until can fire again
    invuln: 0,        // i-frame seconds remaining
    hitFlash: 0,      // >0 means flash white (render reads; decay in logic)
    dashCooldown: 0,
    aim:{x:0,z:1},    // last aim direction (unit-ish)
  },
  enemies: [],        // see Enemy
  projectiles: [],    // see Projectile
  powerups: [],       // see Powerup
  events: [],         // side-effect queue; orchestrator DRAINS each frame (you only push)
  upgrades: { damage:0, fireRate:0, moveSpeed:0, maxHealth:0 },  // purchased levels (ints)
  buffs: { rapidFire:0, spread:0, speed:0 },                     // seconds remaining
  // wave control:
  waveActive: false,  // true while enemies of the current wave still live/spawn
  betweenWaves: true, // true during the upgrade intermission
  enemiesToSpawn: 0,  // remaining to drip-spawn this wave
  spawnTimer: 0,      // countdown to next drip spawn
  rng: fn,            // () => float [0,1)  (provided)
  nextId: 1,          // id allocator; use `state.nextId++` for new entity ids
}
```

### Enemy
```js
{ id, type, pos:{x,z}, vel:{x,z}, hp, maxHp, radius, speed, damage,
  hitFlash:0, fireCooldown:0, spawnScale:0, dead:false }
// type ∈ 'chaser' | 'tank' | 'shooter' | 'splitter' | 'boss'
// spawnScale ramps 0->1 over ~0.3s for spawn pop (logic increments; render uses for mesh scale)
```
### Projectile
```js
{ id, pos:{x,z}, vel:{x,z}, radius, damage, fromPlayer:bool, ttl, dead:false }
```
### Powerup
```js
{ id, kind, pos:{x,z}, ttl, bob:0 }   // kind ∈ 'health'|'rapidFire'|'spread'|'speed'
```
### Event (pushed to state.events; orchestrator drains -> particles + audio + shake)
```js
{ type:'shoot',       x, z }
{ type:'muzzle',      x, z, dx, dz }
{ type:'hit',         x, z }
{ type:'explosion',   x, z, scale }     // scale ~ enemy radius
{ type:'enemyDeath',  x, z, etype }
{ type:'playerHurt',  x, z }
{ type:'pickup',      x, z, kind }
{ type:'waveStart',   wave }
{ type:'gameOver' }
```

## MODULE FILES & REQUIRED EXPORTS (named exports)

### entities.js  (CHILD-2)  — no three import
```
export const ARENA_HALF = 40;
export function updatePlayer(state, dt, input)
   // input = { moveX, moveZ, dash }  (moveX/moveZ in [-1,1], dash:bool)
   // accel toward desired dir, friction, integrate pos, clamp to ±ARENA_HALF,
   // honor moveSpeed upgrade + speed buff, handle dash (impulse + dashCooldown),
   // decrement player.fireCooldown/invuln/hitFlash/dashCooldown; update player.aim
   //   only when an aim is provided via input.aimX/aimZ (optional fields).
export function updateEnemies(state, dt)
   // steering toward player; per-type behavior (see below); integrate vel->pos;
   // ramp spawnScale->1; decrement hitFlash; SHOOTER enemies decrement fireCooldown
   //   and when ready push an ENEMY projectile into state.projectiles (fromPlayer:false)
   //   aimed at player (use shape above; id = state.nextId++); reset their fireCooldown.
   // BOSS may also periodically fire. Enemies do NOT handle their own death/collision
   //   (combat.js does). Keep enemies inside arena (soft clamp ok).
export function startWave(state)
   // called when betweenWaves->false to begin a wave: state.wave++, compute this wave's
   // roster (count grows with wave; mix of types; BOSS when state.wave % 5 === 0),
   // set enemiesToSpawn, spawnTimer, waveActive=true, betweenWaves=false,
   // push {type:'waveStart', wave:state.wave}.
export function updateSpawner(state, dt)
   // drip-spawn queued enemies over time at random arena-edge positions (use state.rng);
   // when enemiesToSpawn==0 AND no enemies remain -> waveActive=false, betweenWaves=true
   //   (orchestrator shows the upgrade screen during betweenWaves).
export function spawnEnemyAt(state, x, z, type='chaser')
   // create one enemy of `type` at (x,z), push to state.enemies, return it.
   // Stat table by type (tune as you like but keep distinct):
   //   chaser : hp~3,  speed~6,  radius~0.9, damage~10, fast & weak
   //   tank   : hp~12, speed~2.5,radius~1.6, damage~18, slow & tanky
   //   shooter: hp~4,  speed~3.5,radius~1.0, damage~8,  keeps distance + fires
   //   splitter:hp~5,  speed~4,  radius~1.1, damage~10  (on death combat spawns 2 chasers)
   //   boss   : hp~120,speed~2,  radius~3.0, damage~30
```

### combat.js  (CHILD-3, part 1)  — no three import
```
export function fire(state, dirX, dirZ)
   // if player.fireCooldown>0 -> return. Normalize (dirX,dirZ); set player.aim.
   // spawn projectile(s) from player.pos slightly forward: 1 normally, 3 in a spread
   //   when buffs.spread>0. damage scales with upgrades.damage. fromPlayer:true.
   // set player.fireCooldown = baseCooldown reduced by upgrades.fireRate and
   //   halved while buffs.rapidFire>0. push {type:'shoot',...} and {type:'muzzle',...}.
export function updateProjectiles(state, dt)
   // integrate pos += vel*dt; ttl -= dt; mark dead if ttl<=0 or outside arena.
export function resolveCollisions(state)
   // PLAYER projectiles vs enemies (circle overlap by radii): apply damage, knockback
   //   (push enemy along projectile dir), enemy.hitFlash=~0.1, projectile.dead=true,
   //   push {type:'hit',...}. On enemy.hp<=0: enemy.dead=true, state.score += reward,
   //   push {type:'enemyDeath',...} and {type:'explosion', scale:enemy.radius}; chance
   //   (use state.rng) to drop a powerup at enemy.pos (push to state.powerups); a
   //   'splitter' on death spawns 2 'chaser' enemies near its pos (use spawnEnemyAt via
   //   import from entities.js OR inline-create per Enemy shape — your call).
   // ENEMY projectiles vs player AND enemy-body vs player (circle overlap): if
   //   player.invuln<=0 -> health -= damage, player.invuln=~0.6, knockback player,
   //   player.hitFlash=~0.15, push {type:'playerHurt',...}; enemy-body contact may also
   //   damage the touching enemy lightly or just knockback (your call, keep deterministic).
   //   If health<=0 -> health=0, gameOver=true, push {type:'gameOver'}.
   // Remove dead projectiles & dead enemies from the arrays at the end.
export function updatePowerups(state, dt)
   // bob/ttl update; if player overlaps a powerup -> apply: 'health'-> heal ~30 (cap
   //   maxHealth); 'rapidFire'/'spread'/'speed' -> set the matching buffs.<x> = ~6s;
   //   push {type:'pickup', kind,...}; remove the picked/expired powerups.
export function applyUpgrade(state, kind)
   // kind ∈ 'damage'|'fireRate'|'moveSpeed'|'maxHealth'. Cost = (level+1)*100 (or your
   //   curve). If score >= cost: score -= cost, upgrades[kind]++ (maxHealth also raises
   //   state.maxHealth by ~20 and heals that much). return true; else return false.
export function tickBuffs(state, dt)
   // decrement buffs.rapidFire/spread/speed toward 0 (used by orchestrator each step).
```

### audio.js  (CHILD-3, part 2)  — browser Web Audio, must be import-safe in Node
```
export function initAudio()      // lazily create AudioContext on first call; safe to call repeatedly
export function resumeAudio()    // resume context (call on first user gesture)
export function playSound(name)  // name ∈ 'shoot'|'hit'|'explosion'|'waveStart'|'playerHurt'|'gameOver'|'pickup'|'upgrade'
export function setMuted(m)
// All functions MUST no-op safely if AudioContext is unavailable (Node): guard with
// `if (typeof AudioContext === 'undefined' && typeof webkitAudioContext === 'undefined') return;`
// Use only oscillators/gain/noise buffers (synth). No external files.
```

### render.js  (CHILD-1)  — imports three + addons; the ONLY visual module
```
export function createRenderWorld(container)
  // builds renderer (antialias, shadowMap enabled, ACESFilmic, sRGB), scene with fog
  //   and a cohesive palette, a polished arena (large ground with gradient/!flat color,
  //   grid/emissive accents, boundary walls), directional light WITH shadows +
  //   hemisphere/ambient light, a perspective camera angled down at the arena, and an
  //   EffectComposer with RenderPass + UnrealBloomPass (+ optional FXAA/vignette).
  // Returns an object `world` with AT LEAST:
  //   world.scene, world.camera, world.renderer, world.composer
  //   world.sync(state, dt)      // create/update/remove meshes to match state by id:
  //        player mesh, enemy meshes (distinct look per type, emissive, hitFlash->white,
  //        spawnScale for pop-in, death handled by removal), projectile meshes (glow),
  //        powerup meshes (distinct color per kind, bob/spin). Maintain id->mesh Maps.
  //   world.handleEvent(evt)     // spawn the matching particle burst for a logic event
  //        (muzzle flash, hit sparks, explosion, pickup sparkle) and trigger screen shake
  //        on hit/explosion/playerHurt/gameOver via world.addShake(amt).
  //   world.followPlayer(x, z, dt) // eased/smoothed camera follow of the player
  //   world.addShake(amount)     // accumulate screen-shake intensity
  //   world.render(dt)           // apply shake decay to camera, update particles, composer.render()
  //   world.resize(w, h)         // camera aspect + renderer/composer setSize
  // Particle systems: use THREE.Points or small mesh pools; frame-rate independent (dt).
```

## ORCHESTRATOR-OWNED (do NOT build these; for your awareness only)
- index.html: import map, canvas/container, HUD DOM (health bar, score, wave, cooldown),
  crosshair, main menu / pause / game-over / between-wave UPGRADE overlay, CSS.
- main.js (or inline): createInitialState() (incl. mulberry32 rng + step order),
  fixed-timestep accumulator main loop, input (WASD + mouse aim + click/space fire + dash),
  drains state.events -> world.handleEvent + audio.playSound, calls world.sync/render/follow,
  HUD updates, localStorage high score, and window.__game wiring:
    window.__game.ready === true
    getState() -> {score,health,wave,enemies,projectiles,gameOver,playerPos:{x,z}}
    step(dt), spawnEnemyAt(x,z), setPlayerPos(x,z), fire(dx,dz), restart()
- The orchestrator's stepLogic order each fixed substep:
    apply input -> updatePlayer -> updateSpawner -> updateEnemies -> updateProjectiles
    -> resolveCollisions -> updatePowerups -> tickBuffs -> (wave/intermission mgmt) -> time+=dt
  Build your functions so THIS ordering works.

## Self-test expectation (each child verifies its own slice)
- LOGIC children: write a throwaway `node --input-type=module` script that fabricates a
  minimal state (you can stub rng=()=>0.5, events=[], nextId=1, etc.), calls your
  functions, and asserts sane mutations. Delete the temp script after. `node --check` is
  NOT enough for logic — actually execute it.
- RENDER child: you cannot open a browser. Run `node --check render.js` for syntax, and
  carefully self-review against three r0.160 APIs. Keep imports to real addon paths.
