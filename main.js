// Arena Survivor — orchestrator integration: state, fixed-timestep loop, input,
// HUD/menus, event draining, and the window.__game test hook.
import * as THREE from 'three';
import { createRenderWorld } from './render.js';
import { initAudio, resumeAudio, playSound, setMuted } from './audio.js';
import {
  createInitialState, makeStepper, advanceFixed,
  startWave, spawnEnemyAt, fire, applyUpgrade,
} from './core.js';

// ---------------------------------------------------------------- module state
let state = createInitialState();
let world = null;
const stepper = makeStepper();
let phase = 'menu';   // 'menu' | 'playing' | 'paused' | 'upgrade' | 'gameover'
let lastT = 0;
const raycaster = new THREE.Raycaster();
const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
const tmpV = new THREE.Vector3();
const ndc = new THREE.Vector2();
const mouse = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
const keys = Object.create(null);
let firing = false, dashQueued = false;

// score reward per enemy type (mirror of combat.js REWARD, for floating numbers)
const REWARD = { chaser: 10, shooter: 15, tank: 25, splitter: 15, boss: 200 };

// ---------------------------------------------------------------- input
function computeAim() {
  if (!world) return { x: 0, z: 1 };
  ndc.x = (mouse.x / window.innerWidth) * 2 - 1;
  ndc.y = -(mouse.y / window.innerHeight) * 2 + 1;
  raycaster.setFromCamera(ndc, world.camera);
  if (raycaster.ray.intersectPlane(groundPlane, tmpV)) {
    const dx = tmpV.x - state.player.pos.x;
    const dz = tmpV.z - state.player.pos.z;
    const len = Math.hypot(dx, dz) || 1;
    return { x: dx / len, z: dz / len };
  }
  return state.player.aim;
}

function liveInput() {
  let mx = 0, mz = 0;
  if (keys['w'] || keys['arrowup']) mz -= 1;
  if (keys['s'] || keys['arrowdown']) mz += 1;
  if (keys['a'] || keys['arrowleft']) mx -= 1;
  if (keys['d'] || keys['arrowright']) mx += 1;
  const aim = computeAim();
  const input = { moveX: mx, moveZ: mz, dash: dashQueued, aimX: aim.x, aimZ: aim.z };
  dashQueued = false;
  // continuous fire while held (fire() self-gates on cooldown)
  if (firing || keys[' ']) fire(state, aim.x, aim.z);
  return input;
}

// ---------------------------------------------------------------- events -> juice
function worldToScreen(x, z, y = 1) {
  tmpV.set(x, y, z).project(world.camera);
  return {
    x: (tmpV.x * 0.5 + 0.5) * window.innerWidth,
    y: (-tmpV.y * 0.5 + 0.5) * window.innerHeight,
  };
}
function floater(x, z, text, color) {
  if (!world) return;
  const el = document.createElement('div');
  el.className = 'floater';
  el.textContent = text;
  el.style.color = color;
  const p = worldToScreen(x, z, 1.4);
  el.style.left = p.x + 'px';
  el.style.top = p.y + 'px';
  document.getElementById('floaters').appendChild(el);
  setTimeout(() => el.remove(), 900);
}
function drainEvents() {
  const evs = state.events;
  for (let i = 0; i < evs.length; i++) {
    const e = evs[i];
    if (world) world.handleEvent(e);
    switch (e.type) {
      case 'shoot': playSound('shoot'); break;
      case 'hit': playSound('hit'); break;
      case 'explosion': playSound('explosion'); break;
      case 'enemyDeath':
        floater(e.x, e.z, '+' + (REWARD[e.etype] || 10), '#38e8ff'); break;
      case 'playerHurt': playSound('playerHurt'); floater(state.player.pos.x, state.player.pos.z, '!', '#ff5a5a'); break;
      case 'pickup': playSound('pickup'); floater(e.x, e.z, (e.kind || 'pickup').toUpperCase(), '#4dff9e'); break;
      case 'waveStart': playSound('waveStart'); break;
      case 'gameOver': playSound('gameOver'); break;
    }
  }
  evs.length = 0;
}

// ---------------------------------------------------------------- HUD
const el = (id) => document.getElementById(id);
function updateHUD() {
  el('scoreVal').textContent = state.score;
  el('waveVal').textContent = state.wave;
  el('highVal').textContent = getHighScore();
  const pct = Math.max(0, Math.min(1, state.health / state.maxHealth)) * 100;
  el('healthFill').style.width = pct + '%';
  el('healthLabel').textContent = Math.max(0, Math.round(state.health)) + ' / ' + state.maxHealth;
  const cd = state.player.fireCooldown;
  el('cooldownFill').style.width = (cd > 0 ? 0 : 100) + '%';
  const buffRow = el('buffRow');
  const active = [];
  if (state.buffs.rapidFire > 0) active.push(['RAPID', state.buffs.rapidFire]);
  if (state.buffs.spread > 0) active.push(['SPREAD', state.buffs.spread]);
  if (state.buffs.speed > 0) active.push(['SPEED', state.buffs.speed]);
  buffRow.innerHTML = active.map(([n, t]) => `<span class="buff">${n} ${t.toFixed(0)}s</span>`).join('');
}

// ---------------------------------------------------------------- high score
function getHighScore() { try { return parseInt(localStorage.getItem('arena_high') || '0', 10) || 0; } catch { return 0; } }
function setHighScore(v) { try { localStorage.setItem('arena_high', String(v)); } catch {} }

// ---------------------------------------------------------------- overlays
const UPGRADE_DEFS = [
  { key: 'damage', ic: '💥', name: 'Damage' },
  { key: 'fireRate', ic: '⚡', name: 'Fire Rate' },
  { key: 'moveSpeed', ic: '🏃', name: 'Move Speed' },
  { key: 'maxHealth', ic: '❤️', name: 'Max Health' },
];
function show(id) { el(id).classList.remove('hidden'); }
function hide(id) { el(id).classList.add('hidden'); }
function setHud(v) { el('hud').classList.toggle('hidden', !v); }

function renderUpgradeCards() {
  el('upWaveNum').textContent = state.wave;
  el('upScore').textContent = state.score;
  const wrap = el('upgradeCards');
  wrap.innerHTML = '';
  for (const def of UPGRADE_DEFS) {
    const lvl = state.upgrades[def.key];
    const cost = (lvl + 1) * 100;
    const afford = state.score >= cost;
    const card = document.createElement('div');
    card.className = 'card' + (afford ? '' : ' disabled');
    card.innerHTML = `<div class="ic">${def.ic}</div><div class="cname">${def.name}</div>` +
      `<div class="clvl">Lv ${lvl}</div><div class="ccost">${cost}</div>`;
    if (afford) card.onclick = () => {
      if (applyUpgrade(state, def.key)) { playSound('upgrade'); renderUpgradeCards(); updateHUD(); }
    };
    wrap.appendChild(card);
  }
}

function enterUpgrade() {
  phase = 'upgrade';
  renderUpgradeCards();
  show('upgradeOverlay');
}
function enterGameOver() {
  phase = 'gameover';
  if (state.score > getHighScore()) setHighScore(state.score);
  el('finalScore').textContent = state.score;
  el('overMsg').textContent = `You reached wave ${state.wave}. Best: ${getHighScore()}.`;
  show('overOverlay');
}

function beginGame() {
  state = createInitialState((Date.now ? (Date.now() & 0xffffffff) : 12345) >>> 0);
  stepper.acc = 0;
  startWave(state);          // wave -> 1, begin spawning
  phase = 'playing';
  setHud(true);
  ['menuOverlay', 'pauseOverlay', 'upgradeOverlay', 'overOverlay'].forEach(hide);
  resumeAudio();
  updateHUD();
}
function nextWave() {
  hide('upgradeOverlay');
  state.betweenWaves = false; state._interArmed = false;
  startWave(state);
  phase = 'playing';
}

// ---------------------------------------------------------------- main loop
function frame(t) {
  requestAnimationFrame(frame);
  const now = t / 1000;
  let dt = now - lastT;
  lastT = now;
  if (!isFinite(dt) || dt < 0) dt = 0;
  if (dt > 0.1) dt = 0.1;

  if (phase === 'playing') {
    advanceFixed(state, dt, { stepper, inputFn: liveInput, clamp: true, autoWave: false });
    drainEvents();
    updateHUD();
    if (state.gameOver) { setHud(true); enterGameOver(); }
    else if (state.betweenWaves && state.enemies.length === 0 && state.enemiesToSpawn === 0) enterUpgrade();
  }

  if (world) {
    world.followPlayer(state.player.pos.x, state.player.pos.z, dt);
    world.sync(state, dt);
    world.render(dt);
    el('crosshair').style.left = mouse.x + 'px';
    el('crosshair').style.top = mouse.y + 'px';
  }
}

// ---------------------------------------------------------------- bootstrap
function init() {
  exposeTestHook();   // expose deterministic logic API first (independent of WebGL)
  try {
    world = createRenderWorld(el('app'));
  } catch (err) {
    console.error('renderer init failed; logic still available via window.__game', err);
    world = null;
  }
  initAudio();

  window.addEventListener('resize', () => {
    if (world) world.resize(window.innerWidth, window.innerHeight);
  });
  window.addEventListener('mousemove', (e) => { mouse.x = e.clientX; mouse.y = e.clientY; });
  window.addEventListener('mousedown', (e) => {
    if (e.button === 0 && phase === 'playing') { firing = true; resumeAudio(); }
  });
  window.addEventListener('mouseup', (e) => { if (e.button === 0) firing = false; });
  window.addEventListener('keydown', (e) => {
    const k = e.key.toLowerCase();
    keys[k] = true;
    if (k === 'shift') dashQueued = true;
    if (k === 'escape') togglePause();
    if (k === ' ' && phase === 'playing') { e.preventDefault(); resumeAudio(); }
  });
  window.addEventListener('keyup', (e) => { keys[e.key.toLowerCase()] = false; });

  el('playBtn').onclick = beginGame;
  el('resumeBtn').onclick = togglePause;
  el('quitBtn').onclick = quitToMenu;
  el('nextWaveBtn').onclick = nextWave;
  el('restartBtn').onclick = beginGame;
  el('highVal').textContent = getHighScore();

  requestAnimationFrame((t) => { lastT = t / 1000; frame(t); });
}
function togglePause() {
  if (phase === 'playing') { phase = 'paused'; show('pauseOverlay'); }
  else if (phase === 'paused') { phase = 'playing'; hide('pauseOverlay'); }
}
function quitToMenu() {
  phase = 'menu'; hide('pauseOverlay'); setHud(false); show('menuOverlay');
}

// ---------------------------------------------------------------- window.__game
function exposeTestHook() {
  window.__game = {
    ready: true,
    getState() {
      return {
        score: state.score, health: state.health, wave: state.wave,
        enemies: state.enemies.length, projectiles: state.projectiles.length,
        gameOver: state.gameOver,
        playerPos: { x: state.player.pos.x, z: state.player.pos.z },
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
    restart() {
      state = createInitialState(0x12345678);   // fixed seed -> deterministic for tests
      stepper.acc = 0;
      startWave(state);   // wave -> 1, spawning armed
      return this.getState();
    },
  };
}

init();
