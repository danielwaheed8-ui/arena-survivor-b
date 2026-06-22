// render.js (CHILD-1) — ALL visuals for "Arena Survivor".
// The ONLY module that imports three + addons. Consumes the STATE/Enemy/Projectile/
// Powerup/Event shapes defined in CONTRACT.md exactly. Pure browser ESM.

import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { FXAAShader } from 'three/addons/shaders/FXAAShader.js';

const ARENA_HALF = 40;          // must match entities.js ARENA_HALF
const WALL_H = 4;               // boundary wall height

// ---- palette ---------------------------------------------------------------
const COLORS = {
  fog:        0x05060f,
  ground:     0x121726,
  groundHi:   0x1d2740,
  grid:       0x2a3b66,
  accent:     0x35e0ff,
  wall:       0x0c1024,
  wallEdge:   0x2fd4ff,
  player:     0x6ff7ff,
  playerCore: 0xffffff,
  chaser:     0xff5a4d,
  tank:       0x7d8aa6,
  tankTrim:   0xffb347,
  shooter:    0xb46bff,
  shooterEye: 0xff3df0,
  splitter:   0x46ff9c,
  boss:       0xff2d6b,
  bossTrim:   0xffd24a,
  projPlayer: 0x9bffff,
  projEnemy:  0xff7a45,
  pHealth:    0x49ff7a,
  pRapid:     0xffe23d,
  pSpread:    0x34e9ff,
  pSpeed:     0xff4df0,
};

const POWERUP_COLOR = {
  health:    COLORS.pHealth,
  rapidFire: COLORS.pRapid,
  spread:    COLORS.pSpread,
  speed:     COLORS.pSpeed,
};

// ---------------------------------------------------------------------------
export function createRenderWorld(container) {
  // ---- renderer ----
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const initW = container.clientWidth || window.innerWidth || 800;
  const initH = container.clientHeight || window.innerHeight || 600;
  renderer.setSize(initW, initH);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  container.appendChild(renderer.domElement);

  // ---- scene + fog ----
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(COLORS.fog);
  scene.fog = new THREE.FogExp2(COLORS.fog, 0.011);
  ACTIVE_SCENE = scene; // builders add freshly-created meshes here via syncGroup

  // ---- camera (high, behind, angled down) ----
  const camera = new THREE.PerspectiveCamera(55, initW / initH, 0.1, 400);
  const CAM_OFFSET = new THREE.Vector3(0, 34, 30); // relative to player target
  camera.position.set(CAM_OFFSET.x, CAM_OFFSET.y, CAM_OFFSET.z);
  camera.lookAt(0, 0, 0);

  // ---- lighting ----
  const hemi = new THREE.HemisphereLight(0x9fc4ff, 0x12182a, 0.55);
  scene.add(hemi);
  const ambient = new THREE.AmbientLight(0x404a66, 0.4);
  scene.add(ambient);

  const sun = new THREE.DirectionalLight(0xfff1d6, 1.65);
  sun.position.set(28, 52, 18);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.camera.near = 1;
  sun.shadow.camera.far = 160;
  sun.shadow.camera.left = -ARENA_HALF - 8;
  sun.shadow.camera.right = ARENA_HALF + 8;
  sun.shadow.camera.top = ARENA_HALF + 8;
  sun.shadow.camera.bottom = -ARENA_HALF - 8;
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.02;
  scene.add(sun);
  scene.add(sun.target);
  sun.target.position.set(0, 0, 0);

  // subtle accent rim light from the opposite side (no shadow)
  const rim = new THREE.DirectionalLight(COLORS.accent, 0.35);
  rim.position.set(-30, 20, -26);
  scene.add(rim);

  // ---- arena ----
  buildArena(scene);

  // ---- post-processing ----
  const composer = new EffectComposer(renderer);
  composer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  composer.setSize(initW, initH);
  const renderPass = new RenderPass(scene, camera);
  composer.addPass(renderPass);

  const bloom = new UnrealBloomPass(new THREE.Vector2(initW, initH), 0.9, 0.6, 0.78);
  bloom.strength = 0.95;
  bloom.radius = 0.55;
  bloom.threshold = 0.72;
  composer.addPass(bloom);

  const fxaa = new ShaderPass(FXAAShader);
  setFxaaResolution(fxaa, initW, initH);
  composer.addPass(fxaa);

  // vignette as a final tasteful pass
  const vignette = new ShaderPass(VignetteShader);
  composer.addPass(vignette);
  fxaa.renderToScreen = false;
  vignette.renderToScreen = true;

  // ---- mesh registries ----
  const enemyMeshes = new Map();      // id -> mesh
  const projectileMeshes = new Map(); // id -> mesh
  const powerupMeshes = new Map();    // id -> mesh

  // shared geometry/material caches for enemies (keyed by type) so we don't rebuild
  const playerMesh = buildPlayer();
  scene.add(playerMesh);

  // ---- particle pool ----
  const particles = new ParticleField(scene);

  // ---- shake + follow state ----
  const camTarget = new THREE.Vector3(0, 0, 0);   // where the player is
  let shake = 0;
  let elapsed = 0;       // total render time for animated shaders/bob

  const world = {
    scene, camera, renderer, composer,

    // ---------------------------------------------------------------
    sync(state, dt) {
      if (!state) return;
      // note: `elapsed` is advanced in render(); sync just reads it for bob/pulse.

      // --- player ---
      if (state.player && state.player.pos) {
        const p = state.player;
        playerMesh.position.set(p.pos.x, 0.9, p.pos.z);
        // face aim direction
        if (p.aim && (p.aim.x !== 0 || p.aim.z !== 0)) {
          playerMesh.rotation.y = Math.atan2(p.aim.x, p.aim.z);
        }
        playerMesh.children.forEach((c) => { if (c.userData.spin) c.rotation.y += dt * c.userData.spin; });
        applyHitFlash(playerMesh, p.hitFlash || 0, COLORS.player);
        // invuln blink
        const blink = (p.invuln > 0) ? (0.45 + 0.55 * Math.abs(Math.sin(elapsed * 22))) : 1;
        setOpacity(playerMesh, blink);
      }

      // --- enemies ---
      syncGroup(state.enemies, enemyMeshes, (e) => buildEnemy(e.type), (e, mesh) => {
        const y = (e.radius || 1) * 0.9;
        mesh.position.set(e.pos.x, y, e.pos.z);
        // face travel/player direction
        if (e.vel && (e.vel.x !== 0 || e.vel.z !== 0)) {
          mesh.rotation.y = Math.atan2(e.vel.x, e.vel.z);
        }
        // idle spin on decorative parts
        mesh.children.forEach((c) => { if (c.userData.spin) c.rotation.y += dt * c.userData.spin; });
        const s = clamp01(e.spawnScale === undefined ? 1 : e.spawnScale);
        const base = mesh.userData.baseScale || 1;
        mesh.scale.setScalar(base * (0.15 + 0.85 * s));
        applyHitFlash(mesh, e.hitFlash || 0, mesh.userData.baseColor);
      });

      // --- projectiles ---
      syncGroup(state.projectiles, projectileMeshes, (pr) => buildProjectile(pr), (pr, mesh) => {
        mesh.position.set(pr.pos.x, 0.9, pr.pos.z);
        const want = pr.fromPlayer ? COLORS.projPlayer : COLORS.projEnemy;
        if (mesh.userData.color !== want) {
          mesh.userData.color = want;
          mesh.material.color.setHex(want);
          if (mesh.material.emissive) mesh.material.emissive.setHex(want);
        }
        // gentle pulse
        const pulse = 0.85 + 0.25 * Math.sin(elapsed * 18 + (pr.id || 0));
        mesh.scale.setScalar(pulse);
      });

      // --- powerups ---
      syncGroup(state.powerups, powerupMeshes, (pu) => buildPowerup(pu.kind), (pu, mesh) => {
        const bob = (pu.bob || 0);
        mesh.position.set(pu.pos.x, 1.1 + Math.sin(elapsed * 2.5 + bob) * 0.35, pu.pos.z);
        mesh.rotation.y += dt * 1.6;
        mesh.children.forEach((c) => { if (c.userData.spin) c.rotation.y += dt * c.userData.spin; });
      });
    },

    // ---------------------------------------------------------------
    handleEvent(evt) {
      if (!evt || !evt.type) return;
      switch (evt.type) {
        case 'muzzle':
          particles.muzzle(evt.x, evt.z, evt.dx || 0, evt.dz || 1);
          break;
        case 'shoot':
          // light spark at the barrel (muzzle usually accompanies, keep subtle)
          break;
        case 'hit':
          particles.sparks(evt.x, evt.z, COLORS.projPlayer, 10, 0.9);
          this.addShake(0.18);
          break;
        case 'explosion': {
          const sc = evt.scale || 1;
          particles.explosion(evt.x, evt.z, sc);
          this.addShake(0.25 + sc * 0.12);
          break;
        }
        case 'enemyDeath':
          particles.sparks(evt.x, evt.z, COLORS.chaser, 14, 1.2);
          break;
        case 'playerHurt':
          particles.sparks(evt.x, evt.z, 0xff4060, 18, 1.4);
          this.addShake(0.55);
          break;
        case 'pickup': {
          const col = POWERUP_COLOR[evt.kind] || COLORS.accent;
          particles.sparkle(evt.x, evt.z, col);
          break;
        }
        case 'gameOver':
          this.addShake(1.2);
          break;
        case 'waveStart':
          // a soft ground pulse could go here; keep cheap
          break;
        default:
          break;
      }
    },

    // ---------------------------------------------------------------
    followPlayer(x, z, dt) {
      camTarget.x = x; camTarget.z = z;
      // frame-rate independent exponential smoothing toward target
      const k = 1 - Math.exp(-6 * (dt || 0.016));
      const desiredX = x + CAM_OFFSET.x;
      const desiredY = CAM_OFFSET.y;
      const desiredZ = z + CAM_OFFSET.z;
      camera.position.x += (desiredX - camera.position.x) * k;
      camera.position.y += (desiredY - camera.position.y) * k;
      camera.position.z += (desiredZ - camera.position.z) * k;
    },

    // ---------------------------------------------------------------
    addShake(amount) {
      shake = Math.min(shake + (amount || 0), 2.5);
    },

    // ---------------------------------------------------------------
    render(dt) {
      const d = dt || 0.016;
      elapsed += d; // advance animation clock even if sync() wasn't called this frame
      // update particles (frame-rate independent)
      particles.update(d);

      // camera shake: apply a TRANSIENT offset to the base position set by followPlayer,
      // render, then remove it so it never accumulates/drifts.
      let ox = 0, oy = 0, oz = 0;
      if (shake > 0.0001) {
        const mag = shake;
        // smooth time-driven jitter (no fixed per-frame constants)
        ox = Math.sin(elapsed * 91.7) * mag;
        oy = Math.sin(elapsed * 67.3 + 1.7) * mag * 0.7;
        oz = Math.sin(elapsed * 78.1 + 3.1) * mag;
        camera.position.x += ox;
        camera.position.y += oy;
        camera.position.z += oz;
        shake = Math.max(0, shake - d * 4.0); // frame-rate independent decay
      }
      camera.lookAt(camTarget.x, 0.5, camTarget.z);

      composer.render();

      camera.position.x -= ox;
      camera.position.y -= oy;
      camera.position.z -= oz;
    },

    // ---------------------------------------------------------------
    resize(w, h) {
      const W = Math.max(1, w | 0);
      const H = Math.max(1, h | 0);
      camera.aspect = W / H;
      camera.updateProjectionMatrix();
      renderer.setSize(W, H);
      composer.setSize(W, H);
      bloom.setSize(W, H);
      setFxaaResolution(fxaa, W, H);
    },

    dispose() {
      renderer.dispose();
      if (renderer.domElement && renderer.domElement.parentNode) {
        renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
    },
  };

  return world;
}

// ===========================================================================
// Generic id->mesh sync helper. Tolerates empty arrays, appearing/disappearing ids.
function syncGroup(list, map, create, update) {
  const arr = Array.isArray(list) ? list : [];
  const seen = new Set();
  for (let i = 0; i < arr.length; i++) {
    const item = arr[i];
    if (!item || item.id === undefined || item.id === null) continue;
    if (!item.pos) continue;
    seen.add(item.id);
    let mesh = map.get(item.id);
    if (!mesh) {
      mesh = create(item);
      if (!mesh) continue;
      map.set(item.id, mesh);
      if (ACTIVE_SCENE) ACTIVE_SCENE.add(mesh);
    }
    try { update(item, mesh); } catch (e) { /* never throw out of sync */ }
  }
  // remove meshes whose id vanished
  for (const [id, mesh] of map) {
    if (!seen.has(id)) {
      disposeMesh(mesh);
      map.delete(id);
    }
  }
}

// ===========================================================================
// ---- arena construction ----
function buildArena(scene) {
  // ground: canvas-generated gradient + grid texture
  const groundTex = makeGroundTexture();
  const groundMat = new THREE.MeshStandardMaterial({
    map: groundTex,
    roughness: 0.85,
    metalness: 0.15,
    emissive: new THREE.Color(COLORS.accent),
    emissiveIntensity: 0.04,
  });
  const groundGeo = new THREE.PlaneGeometry(ARENA_HALF * 2, ARENA_HALF * 2, 1, 1);
  const ground = new THREE.Mesh(groundGeo, groundMat);
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  scene.add(ground);

  // emissive accent border lines on the floor (inner frame)
  const frame = makeFloorFrame();
  scene.add(frame);

  // boundary walls (4) with emissive top edges
  const wallMat = new THREE.MeshStandardMaterial({
    color: COLORS.wall, roughness: 0.6, metalness: 0.35,
    transparent: true, opacity: 0.92,
  });
  const edgeMat = new THREE.MeshStandardMaterial({
    color: COLORS.wallEdge, emissive: new THREE.Color(COLORS.wallEdge),
    emissiveIntensity: 1.4, roughness: 0.4, metalness: 0.2,
  });
  const span = ARENA_HALF * 2 + 1;
  const wallGeo = new THREE.BoxGeometry(span, WALL_H, 0.6);
  const edgeGeo = new THREE.BoxGeometry(span, 0.18, 0.7);
  const placements = [
    { x: 0, z: -ARENA_HALF, ry: 0 },
    { x: 0, z: ARENA_HALF, ry: 0 },
    { x: -ARENA_HALF, z: 0, ry: Math.PI / 2 },
    { x: ARENA_HALF, z: 0, ry: Math.PI / 2 },
  ];
  for (const p of placements) {
    const wall = new THREE.Mesh(wallGeo, wallMat);
    wall.position.set(p.x, WALL_H / 2, p.z);
    wall.rotation.y = p.ry;
    wall.castShadow = true;
    wall.receiveShadow = true;
    scene.add(wall);
    const edge = new THREE.Mesh(edgeGeo, edgeMat);
    edge.position.set(p.x, WALL_H + 0.05, p.z);
    edge.rotation.y = p.ry;
    scene.add(edge);
  }

  // corner emissive pillars
  const pillarGeo = new THREE.CylinderGeometry(0.7, 0.9, WALL_H + 1.4, 12);
  const pillarMat = new THREE.MeshStandardMaterial({
    color: COLORS.wall, emissive: new THREE.Color(COLORS.accent),
    emissiveIntensity: 0.8, roughness: 0.5, metalness: 0.4,
  });
  for (const sx of [-1, 1]) {
    for (const sz of [-1, 1]) {
      const pil = new THREE.Mesh(pillarGeo, pillarMat);
      pil.position.set(sx * ARENA_HALF, (WALL_H + 1.4) / 2, sz * ARENA_HALF);
      pil.castShadow = true;
      scene.add(pil);
    }
  }
}

function makeGroundTexture() {
  const size = 1024;
  const cvs = document.createElement('canvas');
  cvs.width = cvs.height = size;
  const ctx = cvs.getContext('2d');
  // radial gradient: brighter center, darker edges
  const g = ctx.createRadialGradient(size / 2, size / 2, size * 0.05, size / 2, size / 2, size * 0.72);
  g.addColorStop(0, '#1d2740');
  g.addColorStop(0.55, '#141a2c');
  g.addColorStop(1, '#0b0f1c');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);

  // subtle grid
  const cells = 40;
  const step = size / cells;
  ctx.lineWidth = 1;
  ctx.strokeStyle = 'rgba(70,110,190,0.18)';
  ctx.beginPath();
  for (let i = 0; i <= cells; i++) {
    const p = Math.round(i * step) + 0.5;
    ctx.moveTo(p, 0); ctx.lineTo(p, size);
    ctx.moveTo(0, p); ctx.lineTo(size, p);
  }
  ctx.stroke();

  // brighter major grid lines every 8 cells
  ctx.lineWidth = 2;
  ctx.strokeStyle = 'rgba(90,210,255,0.28)';
  ctx.beginPath();
  for (let i = 0; i <= cells; i += 8) {
    const p = Math.round(i * step) + 0.5;
    ctx.moveTo(p, 0); ctx.lineTo(p, size);
    ctx.moveTo(0, p); ctx.lineTo(size, p);
  }
  ctx.stroke();

  const tex = new THREE.CanvasTexture(cvs);
  tex.wrapS = tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.anisotropy = 4;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function makeFloorFrame() {
  const group = new THREE.Group();
  const mat = new THREE.MeshStandardMaterial({
    color: COLORS.accent, emissive: new THREE.Color(COLORS.accent),
    emissiveIntensity: 1.5, roughness: 0.4, metalness: 0.1,
  });
  const inner = ARENA_HALF - 1.2;
  const t = 0.22;
  const long = inner * 2;
  const barX = new THREE.BoxGeometry(long, 0.06, t);
  const barZ = new THREE.BoxGeometry(t, 0.06, long);
  const top = new THREE.Mesh(barX, mat); top.position.set(0, 0.04, -inner); group.add(top);
  const bot = new THREE.Mesh(barX, mat); bot.position.set(0, 0.04, inner); group.add(bot);
  const left = new THREE.Mesh(barZ, mat); left.position.set(-inner, 0.04, 0); group.add(left);
  const right = new THREE.Mesh(barZ, mat); right.position.set(inner, 0.04, 0); group.add(right);
  return group;
}

// ===========================================================================
// ---- entity mesh builders. Each returns a mesh/group already configured.
// (They are added to the scene by the caller via syncGroup's create path:
//  builders below DON'T add to scene; createRenderWorld wires scene-add through
//  closures, so we attach to scene here via the module-level reference.)
//
// syncGroup adds freshly-created meshes to ACTIVE_SCENE (set in createRenderWorld).
let ACTIVE_SCENE = null;

function buildPlayer() {
  const group = new THREE.Group();
  // body: sleek octahedron core
  const coreGeo = new THREE.IcosahedronGeometry(0.85, 1);
  const coreMat = new THREE.MeshStandardMaterial({
    color: COLORS.player, emissive: new THREE.Color(COLORS.player),
    emissiveIntensity: 0.75, roughness: 0.3, metalness: 0.5,
  });
  const core = new THREE.Mesh(coreGeo, coreMat);
  core.castShadow = true;
  group.add(core);

  // bright inner spark
  const spark = new THREE.Mesh(
    new THREE.SphereGeometry(0.32, 12, 12),
    new THREE.MeshStandardMaterial({
      color: 0xffffff, emissive: new THREE.Color(0xffffff), emissiveIntensity: 2.2,
      roughness: 0.2, metalness: 0,
    })
  );
  group.add(spark);

  // forward gun nub (points +z, the aim default)
  const gun = new THREE.Mesh(
    new THREE.CylinderGeometry(0.16, 0.16, 1.1, 10),
    new THREE.MeshStandardMaterial({
      color: COLORS.playerCore, emissive: new THREE.Color(COLORS.accent),
      emissiveIntensity: 1.0, roughness: 0.3, metalness: 0.6,
    })
  );
  gun.rotation.x = Math.PI / 2;
  gun.position.set(0, 0, 0.85);
  gun.castShadow = true;
  group.add(gun);

  // spinning ring
  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(1.15, 0.07, 8, 32),
    new THREE.MeshStandardMaterial({
      color: COLORS.accent, emissive: new THREE.Color(COLORS.accent),
      emissiveIntensity: 1.3, roughness: 0.4, metalness: 0.3,
    })
  );
  ring.rotation.x = Math.PI / 2;
  ring.userData.spin = 1.4;
  group.add(ring);

  group.userData.baseScale = 1;
  group.userData.baseColor = COLORS.player;
  return group;
}

function buildEnemy(type) {
  let group;
  switch (type) {
    case 'tank':     group = buildTank(); break;
    case 'shooter':  group = buildShooter(); break;
    case 'splitter': group = buildSplitter(); break;
    case 'boss':     group = buildBoss(); break;
    case 'chaser':
    default:         group = buildChaser(); break;
  }
  return group;
}

function emissiveStd(color, intensity, opts) {
  const o = opts || {};
  return new THREE.MeshStandardMaterial({
    color,
    emissive: new THREE.Color(color),
    emissiveIntensity: intensity === undefined ? 0.6 : intensity,
    roughness: o.roughness === undefined ? 0.45 : o.roughness,
    metalness: o.metalness === undefined ? 0.4 : o.metalness,
  });
}

function buildChaser() {
  const group = new THREE.Group();
  const mat = emissiveStd(COLORS.chaser, 0.7, { metalness: 0.5 });
  // small spiky tetra-ish body
  const body = new THREE.Mesh(new THREE.TetrahedronGeometry(0.95, 0), mat);
  body.castShadow = true;
  body.userData.spin = 2.2;
  group.add(body);
  // outer spikes
  const spikeMat = emissiveStd(0xffd0c0, 0.5);
  const spike = new THREE.Mesh(new THREE.OctahedronGeometry(0.55, 0), spikeMat);
  spike.userData.spin = -3.0;
  group.add(spike);
  group.userData.baseScale = 0.95;
  group.userData.baseColor = COLORS.chaser;
  return group;
}

function buildTank() {
  const group = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(1.9, 1.4, 1.9),
    emissiveStd(COLORS.tank, 0.25, { roughness: 0.6, metalness: 0.55 }));
  body.castShadow = true;
  group.add(body);
  // armor plates / trim
  const trimMat = emissiveStd(COLORS.tankTrim, 1.0);
  const trim = new THREE.Mesh(new THREE.BoxGeometry(2.05, 0.28, 2.05), trimMat);
  trim.position.y = 0.55;
  group.add(trim);
  const trim2 = new THREE.Mesh(new THREE.BoxGeometry(2.05, 0.28, 2.05), trimMat);
  trim2.position.y = -0.55;
  group.add(trim2);
  // turret
  const turret = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.7, 0.7, 8),
    emissiveStd(COLORS.tank, 0.3, { metalness: 0.6 }));
  turret.position.y = 0.9;
  turret.castShadow = true;
  group.add(turret);
  group.userData.baseScale = 1.0;
  group.userData.baseColor = COLORS.tank;
  return group;
}

function buildShooter() {
  const group = new THREE.Group();
  const body = new THREE.Mesh(new THREE.ConeGeometry(0.95, 1.8, 6),
    emissiveStd(COLORS.shooter, 0.55, { metalness: 0.5 }));
  body.castShadow = true;
  body.userData.spin = 1.0;
  group.add(body);
  // glowing eye
  const eye = new THREE.Mesh(new THREE.SphereGeometry(0.42, 16, 16),
    new THREE.MeshStandardMaterial({
      color: COLORS.shooterEye, emissive: new THREE.Color(COLORS.shooterEye),
      emissiveIntensity: 2.4, roughness: 0.2, metalness: 0,
    }));
  eye.position.set(0, 0.25, 0.6);
  group.add(eye);
  // orbiting ring
  const ring = new THREE.Mesh(new THREE.TorusGeometry(1.1, 0.06, 6, 24),
    emissiveStd(COLORS.shooterEye, 1.2));
  ring.rotation.x = Math.PI / 2.4;
  ring.userData.spin = -2.2;
  group.add(ring);
  group.userData.baseScale = 1.0;
  group.userData.baseColor = COLORS.shooter;
  return group;
}

function buildSplitter() {
  const group = new THREE.Group();
  const mat = emissiveStd(COLORS.splitter, 0.6, { metalness: 0.45 });
  // cluster of spheres
  const positions = [
    [0, 0, 0, 0.8],
    [0.55, 0.2, 0.2, 0.5],
    [-0.45, 0.25, -0.3, 0.5],
    [0.1, -0.4, 0.5, 0.45],
    [-0.2, -0.3, -0.5, 0.45],
  ];
  for (const [x, y, z, r] of positions) {
    const s = new THREE.Mesh(new THREE.SphereGeometry(r, 12, 12), mat);
    s.position.set(x, y, z);
    s.castShadow = true;
    group.add(s);
  }
  group.userData.spin = 1.6;
  // make whole group wobble-spin
  group.children.forEach((c) => { c.userData.spin = 0; });
  const halo = new THREE.Mesh(new THREE.IcosahedronGeometry(1.15, 0),
    new THREE.MeshStandardMaterial({
      color: COLORS.splitter, emissive: new THREE.Color(COLORS.splitter),
      emissiveIntensity: 0.7, transparent: true, opacity: 0.18, roughness: 0.5, metalness: 0.2,
    }));
  halo.userData.spin = -1.4;
  group.add(halo);
  group.userData.baseScale = 1.0;
  group.userData.baseColor = COLORS.splitter;
  return group;
}

function buildBoss() {
  const group = new THREE.Group();
  // huge menacing core
  const body = new THREE.Mesh(new THREE.DodecahedronGeometry(2.6, 0),
    emissiveStd(COLORS.boss, 0.6, { roughness: 0.4, metalness: 0.6 }));
  body.castShadow = true;
  body.userData.spin = 0.5;
  group.add(body);
  // armored spikes ring
  const spikeMat = emissiveStd(COLORS.bossTrim, 1.1);
  const spikeCount = 8;
  for (let i = 0; i < spikeCount; i++) {
    const a = (i / spikeCount) * Math.PI * 2;
    const spike = new THREE.Mesh(new THREE.ConeGeometry(0.5, 1.6, 6), spikeMat);
    spike.position.set(Math.cos(a) * 2.7, 0, Math.sin(a) * 2.7);
    spike.rotation.z = -Math.PI / 2;
    spike.rotation.y = -a;
    spike.castShadow = true;
    group.add(spike);
  }
  // glowing crown ring
  const ring = new THREE.Mesh(new THREE.TorusGeometry(3.1, 0.18, 10, 40),
    emissiveStd(COLORS.boss, 1.4));
  ring.rotation.x = Math.PI / 2;
  ring.userData.spin = -0.9;
  group.add(ring);
  // inner eye
  const eye = new THREE.Mesh(new THREE.SphereGeometry(0.9, 18, 18),
    new THREE.MeshStandardMaterial({
      color: 0xffffff, emissive: new THREE.Color(COLORS.bossTrim), emissiveIntensity: 2.6,
      roughness: 0.2, metalness: 0,
    }));
  eye.position.set(0, 0, 0);
  group.add(eye);
  group.userData.baseScale = 1.0;
  group.userData.baseColor = COLORS.boss;
  return group;
}

function buildProjectile(pr) {
  const col = pr && pr.fromPlayer ? COLORS.projPlayer : COLORS.projEnemy;
  const r = (pr && pr.radius) ? Math.max(0.18, pr.radius) : 0.25;
  const mat = new THREE.MeshStandardMaterial({
    color: col, emissive: new THREE.Color(col), emissiveIntensity: 2.2,
    roughness: 0.25, metalness: 0.1,
  });
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(r, 12, 12), mat);
  // trail glow shell
  const glow = new THREE.Mesh(new THREE.SphereGeometry(r * 1.9, 10, 10),
    new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.22 }));
  mesh.add(glow);
  mesh.userData.color = col;
  return mesh;
}

function buildPowerup(kind) {
  const col = POWERUP_COLOR[kind] || COLORS.accent;
  const group = new THREE.Group();
  const mat = new THREE.MeshStandardMaterial({
    color: col, emissive: new THREE.Color(col), emissiveIntensity: 1.4,
    roughness: 0.3, metalness: 0.4,
  });
  // shape varies a little by kind for readability
  let geo;
  switch (kind) {
    case 'health':    geo = new THREE.OctahedronGeometry(0.6, 0); break;
    case 'rapidFire': geo = new THREE.ConeGeometry(0.5, 1.0, 8); break;
    case 'spread':    geo = new THREE.DodecahedronGeometry(0.55, 0); break;
    case 'speed':     geo = new THREE.TetrahedronGeometry(0.7, 0); break;
    default:          geo = new THREE.BoxGeometry(0.8, 0.8, 0.8); break;
  }
  const core = new THREE.Mesh(geo, mat);
  core.castShadow = true;
  core.userData.spin = 2.0;
  group.add(core);
  // halo ring
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.85, 0.06, 8, 24),
    new THREE.MeshStandardMaterial({
      color: col, emissive: new THREE.Color(col), emissiveIntensity: 1.6,
      transparent: true, opacity: 0.85, roughness: 0.4, metalness: 0.2,
    }));
  ring.rotation.x = Math.PI / 2;
  ring.userData.spin = -2.4;
  group.add(ring);
  group.userData.baseColor = col;
  return group;
}

// ===========================================================================
// ---- particle field: a single pooled THREE.Points buffer ----
class ParticleField {
  constructor(scene) {
    this.max = 1200;
    this.count = this.max;
    const geo = new THREE.BufferGeometry();
    this.positions = new Float32Array(this.max * 3);
    this.colors = new Float32Array(this.max * 3);
    this.alphas = new Float32Array(this.max);   // packed into a custom attribute
    // particle runtime data
    this.vel = new Float32Array(this.max * 3);
    this.life = new Float32Array(this.max);
    this.maxLife = new Float32Array(this.max);
    this.active = new Uint8Array(this.max);

    geo.setAttribute('position', new THREE.BufferAttribute(this.positions, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(this.colors, 3));
    this.geo = geo;

    const mat = new THREE.PointsMaterial({
      size: 0.5,
      vertexColors: true,
      transparent: true,
      opacity: 1.0,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
    });
    this.mat = mat;
    this.points = new THREE.Points(geo, mat);
    this.points.frustumCulled = false;
    // park unused particles far below
    for (let i = 0; i < this.max; i++) this.positions[i * 3 + 1] = -1000;
    scene.add(this.points);
    this.cursor = 0;
  }

  _spawn(x, y, z, vx, vy, vz, r, g, b, life) {
    // find a slot starting at cursor
    let idx = -1;
    for (let n = 0; n < this.max; n++) {
      const i = (this.cursor + n) % this.max;
      if (!this.active[i]) { idx = i; break; }
    }
    if (idx === -1) idx = this.cursor; // overwrite oldest-ish
    this.cursor = (idx + 1) % this.max;

    const p3 = idx * 3;
    this.positions[p3] = x; this.positions[p3 + 1] = y; this.positions[p3 + 2] = z;
    this.vel[p3] = vx; this.vel[p3 + 1] = vy; this.vel[p3 + 2] = vz;
    this.colors[p3] = r; this.colors[p3 + 1] = g; this.colors[p3 + 2] = b;
    this.life[idx] = life;
    this.maxLife[idx] = life;
    this.active[idx] = 1;
  }

  _burst(x, z, hexColor, n, speed, opts) {
    const o = opts || {};
    const c = new THREE.Color(hexColor);
    const yBase = o.y === undefined ? 0.9 : o.y;
    const up = o.up === undefined ? 0.4 : o.up;
    const life = o.life === undefined ? 0.6 : o.life;
    const spread = o.spread === undefined ? 1 : o.spread;
    for (let i = 0; i < n; i++) {
      // pseudo-random directions without Math.random dependency on logic determinism;
      // visuals may use Math.random freely (only LOGIC must be deterministic).
      const ang = Math.random() * Math.PI * 2;
      const elev = (Math.random() * 0.8 + 0.1);
      const sp = speed * (0.5 + Math.random() * 0.9) * spread;
      const vx = Math.cos(ang) * sp;
      const vz = Math.sin(ang) * sp;
      const vy = up * sp * elev + Math.random() * 1.5;
      // slight color variance toward white
      const t = Math.random() * 0.35;
      this._spawn(
        x, yBase, z,
        vx, vy, vz,
        c.r + (1 - c.r) * t, c.g + (1 - c.g) * t, c.b + (1 - c.b) * t,
        life * (0.7 + Math.random() * 0.6)
      );
    }
  }

  muzzle(x, z, dx, dz) {
    const len = Math.hypot(dx, dz) || 1;
    const ux = dx / len, uz = dz / len;
    const c = new THREE.Color(0xfff0c0);
    for (let i = 0; i < 8; i++) {
      const spreadA = (Math.random() - 0.5) * 0.7;
      const ca = Math.cos(spreadA), sa = Math.sin(spreadA);
      const rx = ux * ca - uz * sa;
      const rz = ux * sa + uz * ca;
      const sp = 6 + Math.random() * 6;
      this._spawn(
        x + ux * 0.8, 0.9, z + uz * 0.8,
        rx * sp, 0.5 + Math.random() * 1.5, rz * sp,
        c.r, c.g, c.b,
        0.18 + Math.random() * 0.12
      );
    }
  }

  sparks(x, z, hexColor, n, speed) {
    this._burst(x, z, hexColor, n || 10, speed || 1, { up: 0.6, life: 0.5, spread: 4 });
  }

  explosion(x, z, scale) {
    const s = scale || 1;
    const n = Math.min(60, Math.round(22 + s * 10));
    this._burst(x, z, 0xffb347, n, 1.2 + s * 0.4, { up: 0.7, life: 0.8 + s * 0.1, spread: 5 + s });
    this._burst(x, z, 0xff4d3a, Math.round(n * 0.6), 1.0 + s * 0.3, { up: 0.5, life: 0.6, spread: 4 + s });
    // a few bright white core sparks
    this._burst(x, z, 0xffffff, 8, 2 + s * 0.5, { up: 0.9, life: 0.4, spread: 6 + s });
  }

  sparkle(x, z, hexColor) {
    const c = new THREE.Color(hexColor);
    for (let i = 0; i < 16; i++) {
      const ang = Math.random() * Math.PI * 2;
      const sp = 1.5 + Math.random() * 2.5;
      this._spawn(
        x + (Math.random() - 0.5) * 0.6, 0.6 + Math.random() * 1.4, z + (Math.random() - 0.5) * 0.6,
        Math.cos(ang) * sp, 2 + Math.random() * 3, Math.sin(ang) * sp,
        c.r, c.g, c.b,
        0.7 + Math.random() * 0.5
      );
    }
  }

  update(dt) {
    const posAttr = this.geo.getAttribute('position');
    const colAttr = this.geo.getAttribute('color');
    const grav = 9.0;
    let anyAlive = false;
    for (let i = 0; i < this.max; i++) {
      if (!this.active[i]) continue;
      anyAlive = true;
      this.life[i] -= dt;
      if (this.life[i] <= 0) {
        this.active[i] = 0;
        const p3 = i * 3;
        this.positions[p3 + 1] = -1000; // park out of view
        continue;
      }
      const p3 = i * 3;
      // integrate
      this.vel[p3 + 1] -= grav * dt;
      this.positions[p3] += this.vel[p3] * dt;
      this.positions[p3 + 1] += this.vel[p3 + 1] * dt;
      this.positions[p3 + 2] += this.vel[p3 + 2] * dt;
      // simple ground bounce
      if (this.positions[p3 + 1] < 0.05) {
        this.positions[p3 + 1] = 0.05;
        this.vel[p3 + 1] *= -0.35;
        this.vel[p3] *= 0.6;
        this.vel[p3 + 2] *= 0.6;
      }
      // fade color toward black as life ends (cheap fade since PointsMaterial has 1 opacity)
      const f = this.life[i] / this.maxLife[i];
      // store base color separately? we just scale current — acceptable visual decay
      // (multiplicative fade each frame would compound; instead recompute from life)
      // We keep colors constant and rely on additive blend + size; fade via shrinking life only.
      void f;
    }
    posAttr.needsUpdate = true;
    colAttr.needsUpdate = true;
    return anyAlive;
  }
}

// ===========================================================================
// ---- small utilities ----
function clamp01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }

const _flashColor = new THREE.Color();
const _baseColor = new THREE.Color();
function applyHitFlash(obj, flash, baseHex) {
  const t = clamp01(flash / 0.15); // hitFlash ~0.1-0.15 in contract
  obj.traverse((node) => {
    const mat = node.material;
    if (!mat || !mat.emissive) return;
    if (node.userData.__baseEmissive === undefined) {
      node.userData.__baseEmissive = mat.emissive.getHex();
      node.userData.__baseEmissiveI = mat.emissiveIntensity;
    }
    if (t > 0.001) {
      _baseColor.setHex(node.userData.__baseEmissive);
      _flashColor.setHex(0xffffff);
      mat.emissive.copy(_baseColor).lerp(_flashColor, t);
      mat.emissiveIntensity = node.userData.__baseEmissiveI + t * 2.5;
    } else if (node.userData.__flashed) {
      mat.emissive.setHex(node.userData.__baseEmissive);
      mat.emissiveIntensity = node.userData.__baseEmissiveI;
    }
    node.userData.__flashed = t > 0.001;
  });
}

function setOpacity(obj, o) {
  obj.traverse((node) => {
    const mat = node.material;
    if (!mat) return;
    if (o < 0.999) {
      mat.transparent = true;
      mat.opacity = o;
    } else if (node.userData.__wasFaded) {
      mat.opacity = node.userData.__origOpacity === undefined ? 1 : node.userData.__origOpacity;
    }
    if (o < 0.999 && node.userData.__origOpacity === undefined) {
      node.userData.__origOpacity = 1;
    }
    node.userData.__wasFaded = o < 0.999;
  });
}

function disposeMesh(obj) {
  if (!obj) return;
  if (obj.parent) obj.parent.remove(obj);
  obj.traverse((node) => {
    if (node.geometry) node.geometry.dispose();
    if (node.material) {
      if (Array.isArray(node.material)) node.material.forEach((m) => m.dispose());
      else node.material.dispose();
    }
  });
}

function setFxaaResolution(pass, w, h) {
  const pr = Math.min(window.devicePixelRatio || 1, 2);
  pass.material.uniforms['resolution'].value.set(1 / (w * pr), 1 / (h * pr));
}

// ---- vignette shader (tasteful darkened corners) ----
const VignetteShader = {
  uniforms: {
    tDiffuse: { value: null },
    offset:   { value: 1.05 },
    darkness: { value: 1.15 },
  },
  vertexShader: /* glsl */`
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: /* glsl */`
    uniform sampler2D tDiffuse;
    uniform float offset;
    uniform float darkness;
    varying vec2 vUv;
    void main() {
      vec4 texel = texture2D(tDiffuse, vUv);
      vec2 uv = (vUv - 0.5) * vec2(offset);
      float vig = clamp(1.0 - dot(uv, uv) * darkness, 0.0, 1.0);
      gl_FragColor = vec4(texel.rgb * vig, texel.a);
    }
  `,
};
