// Node harness for the deterministic logic core (the window.__game path).
// Mirrors main.js's advanceLogic + test-hook wiring, importing the REAL modules.
import {
  createInitialState, makeStepper, advanceFixed,
  startWave, spawnEnemyAt, fire, applyUpgrade,
} from './core.js';

let pass = 0;
function check(name, cond) {
  if (!cond) { console.error('FAIL:', name); process.exit(1); }
  console.log('ok:', name); pass++;
}

// --- replicate main.js's window.__game hook EXACTLY (same advanceFixed paths) ---
function makeGame() {
  let state = createInitialState(0x9e3779b9);
  const stepper = makeStepper();
  return {
    get state() { return state; },
    ready: true,
    getState() {
      return {
        score: state.score, health: state.health, wave: state.wave,
        enemies: state.enemies.length, projectiles: state.projectiles.length,
        gameOver: state.gameOver, playerPos: { x: state.player.pos.x, z: state.player.pos.z },
      };
    },
    step(dt) {
      advanceFixed(state, dt, { stepper, autoWave: true, clamp: false });
      state.events.length = 0;
      return this.getState();
    },
    spawnEnemyAt(x, z) { return spawnEnemyAt(state, x, z, 'chaser'); },
    setPlayerPos(x, z) { state.player.pos.x = x; state.player.pos.z = z; },
    fire(dx, dz) { fire(state, dx, dz); },
    restart() { state = createInitialState(0x12345678); stepper.acc = 0; startWave(state); return this.getState(); },
  };
}

// ================= test hook shape =================
const g = makeGame();
check('ready', g.ready === true);
let st = g.getState();
check('getState shape', ['score', 'health', 'wave', 'enemies', 'projectiles', 'gameOver', 'playerPos'].every(k => k in st));
check('playerPos shape', 'x' in st.playerPos && 'z' in st.playerPos);

// ================= restart resets =================
st = g.restart();
check('restart score 0', st.score === 0);
check('restart health full', st.health === 100);
check('restart wave 1', st.wave === 1);
check('restart no enemies yet', st.enemies === 0);
check('restart not gameover', st.gameOver === false);

// ================= spawn + step advances enemy toward player =================
g.restart();
g.setPlayerPos(0, 0);
const e0 = g.spawnEnemyAt(20, 0);
check('spawn returns enemy', e0 && e0.hp > 0 && e0.id > 0);
check('spawn count', g.getState().enemies >= 1);
const d0 = Math.hypot(20 - 0, 0);
g.step(0.5);
const enemyNow = g.state.enemies.find(e => e.id === e0.id);
check('enemy approached player', enemyNow && Math.hypot(enemyNow.pos.x, enemyNow.pos.z) < d0);

// ================= fire creates projectiles; setPlayerPos works =================
g.restart();
g.setPlayerPos(5, -3);
check('setPlayerPos', g.getState().playerPos.x === 5 && g.getState().playerPos.z === -3);
const projBefore = g.getState().projectiles;
g.fire(1, 0);
check('fire adds projectile', g.getState().projectiles > projBefore);

// ================= kill an enemy -> score up, enemy removed =================
g.restart();
g.setPlayerPos(0, 0);
const target = g.spawnEnemyAt(2, 0);   // chaser hp 3
const scoreBefore = g.getState().score;
// fire several shots down +x; step to let them travel & collide
for (let i = 0; i < 6; i++) { g.fire(1, 0); g.step(0.06); }
check('score increased after kill', g.getState().score > scoreBefore);
check('killed enemy removed', !g.state.enemies.some(e => e.id === target.id));

// ================= enemy body contact damages player =================
g.restart();
g.setPlayerPos(0, 0);
g.spawnEnemyAt(0.5, 0);  // overlapping the player
const hpBefore = g.getState().health;
g.step(0.05);
check('contact damages player', g.getState().health < hpBefore);

// ================= upgrades spend score =================
g.restart();
g.state.score = 250;
const okUp = applyUpgrade(g.state, 'damage');
check('applyUpgrade success', okUp === true && g.state.upgrades.damage === 1 && g.state.score === 150);
const okFail = applyUpgrade({ score: 0, upgrades: { damage: 0 } }, 'damage');
check('applyUpgrade fails when broke', okFail === false);

// ================= determinism: same seed + same calls => identical state =================
function run() {
  const h = makeGame(); h.restart();
  h.setPlayerPos(0, 0); h.spawnEnemyAt(10, 5); h.spawnEnemyAt(-8, 3);
  for (let i = 0; i < 40; i++) { h.fire(1, 0.2); h.step(0.05); }
  return JSON.stringify(h.getState());
}
check('deterministic across runs', run() === run());

// ================= step(dt) honors the FULL dt (no anti-spiral clamp) =================
g.restart();
const t0 = g.state.time;
g.step(5);
check('step honors full dt', Math.abs(g.state.time - (t0 + 5)) < 0.02);

// ================= waves auto-advance once a wave is cleared =================
// Helper: empty the current wave so updateSpawner flips betweenWaves, then step past
// the intermission so manageWaves auto-starts the next wave.
function clearAndAdvance(game) {
  game.state.enemies.length = 0;
  game.state.enemiesToSpawn = 0;
  game.state.spawnQueue = [];
  game.step(0.1);          // updateSpawner -> betweenWaves = true
  game.step(3.0);          // > INTERMISSION -> manageWaves -> startWave
}
g.restart();
const w1 = g.getState().wave;
clearAndAdvance(g);
check('wave advances after clear', g.getState().wave === w1 + 1);

// ================= boss wave at every 5th wave =================
g.restart();
let guard = 0;
while (g.state.wave < 5 && guard < 50) { clearAndAdvance(g); guard++; }
check('reached wave 5', g.state.wave === 5);
const hasBoss = (g.state.spawnQueue && g.state.spawnQueue.includes('boss')) ||
  g.state.enemies.some(e => e.type === 'boss');
check('wave 5 is a boss wave', hasBoss);

// ================= gameOver freezes logic =================
g.restart();
g.state.health = 1;
g.setPlayerPos(0, 0);
g.spawnEnemyAt(0.4, 0);
let gsafety = 0;
while (!g.getState().gameOver && gsafety < 200) { g.step(0.1); gsafety++; }
check('player can die -> gameOver', g.getState().gameOver === true);
const frozen = g.getState();
g.step(1.0);
check('gameOver freezes score/wave', g.getState().score === frozen.score && g.getState().wave === frozen.wave);

console.log(`\nALL ${pass} CORE TESTS PASSED`);
