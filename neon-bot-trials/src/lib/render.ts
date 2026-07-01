import type { Camera } from './camera';
import type { SimFrameBody, ThrusterFx } from './engine';
import type { ArenaDef, DrawBodyDesc, RobotDesign } from './types';

/**
 * Neon canvas renderer. Draws arenas and robots from plain data so the same
 * code path renders live simulation, replays, the builder and menu previews.
 * All state held here (particles, trails) is visual-only.
 */

export interface RenderView {
  arena: ArenaDef | null;
  design: RobotDesign | null;
  bodies: SimFrameBody[];
  descs: DrawBodyDesc[];
  thrusters: ThrusterFx[];
  t: number;
  batteryFrac: number;
  cinematic?: boolean;
}

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  maxLife: number;
  size: number;
  hue: number;
  kind: 'flame' | 'spark' | 'dust' | 'ambient';
}

const TAU = Math.PI * 2;

export class NeonRenderer {
  private particles: Particle[] = [];
  private trail: Array<{ x: number; y: number; t: number }> = [];
  private lastSpawnT = 0;
  private ambientSeeded = false;

  reset(): void {
    this.particles = [];
    this.trail = [];
    this.ambientSeeded = false;
  }

  render(
    ctx: CanvasRenderingContext2D,
    view: RenderView,
    camera: Camera,
    viewW: number,
    viewH: number,
    dt: number,
  ): void {
    const theme = view.arena?.theme ?? DEFAULT_THEME;

    // Preserve the caller's base (device-pixel-ratio) transform — all drawing
    // below uses CSS-pixel coordinates composed on top of it.
    const base = ctx.getTransform();
    this.drawBackground(ctx, theme, camera, viewW, viewH, view.t);

    camera.applyTo(ctx, viewW, viewH, base);

    if (view.arena) {
      this.drawZones(ctx, view.arena, view.t);
      this.drawTerrain(ctx, view.arena, view.t);
      this.drawFinish(ctx, view.arena, view.t);
    }

    this.updateEffects(view, dt);
    this.drawTrail(ctx, view);
    this.drawParticles(ctx);
    this.drawBodies(ctx, view);
    if (view.design && view.bodies.length > 0) {
      this.drawDecorations(ctx, view);
    }

    ctx.setTransform(base);
    if (view.cinematic) this.drawVignette(ctx, viewW, viewH);
  }

  // -------------------------------------------------------------------------
  // Background
  // -------------------------------------------------------------------------

  private drawBackground(
    ctx: CanvasRenderingContext2D,
    theme: ArenaDef['theme'],
    camera: Camera,
    w: number,
    h: number,
    t: number,
  ): void {
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, theme.skyTop);
    grad.addColorStop(1, theme.skyBottom);
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, h);

    const cam = camera.effective();
    // Parallax grid
    ctx.strokeStyle = theme.grid;
    ctx.lineWidth = 1;
    const grid = 90 * cam.zoom;
    const ox = (-cam.x * cam.zoom * 0.55) % grid;
    const oy = (-cam.y * cam.zoom * 0.55) % grid;
    ctx.beginPath();
    for (let x = ox; x < w; x += grid) {
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
    }
    for (let y = oy; y < h; y += grid) {
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
    }
    ctx.stroke();

    // Distant glow orbs (parallax layer 2)
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    for (let i = 0; i < 5; i++) {
      const px = ((i * 467 + 130 - cam.x * 0.18) % (w + 400)) - 200;
      const py = (i * 173 + 60 + Math.sin(t * 0.3 + i * 2) * 18) % h;
      const r = 60 + i * 22;
      const orb = ctx.createRadialGradient(px, py, 0, px, py, r);
      orb.addColorStop(0, hexWithAlpha(theme.terrainGlow, 0.05));
      orb.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = orb;
      ctx.fillRect(px - r, py - r, r * 2, r * 2);
    }
    ctx.restore();
  }

  // -------------------------------------------------------------------------
  // Arena
  // -------------------------------------------------------------------------

  private drawTerrain(ctx: CanvasRenderingContext2D, arena: ArenaDef, t: number): void {
    for (const block of arena.terrain) {
      ctx.save();
      ctx.translate(block.x, block.y);
      if (block.angle) ctx.rotate(block.angle);

      const isPad = block.kind === 'pad';
      const glow = isPad ? '#f472b6' : arena.theme.terrainGlow;

      ctx.fillStyle = arena.theme.terrain;
      ctx.beginPath();
      ctx.roundRect(-block.w / 2, -block.h / 2, block.w, block.h, 3);
      ctx.fill();

      // Neon top edge
      ctx.shadowColor = glow;
      ctx.shadowBlur = isPad ? 18 : 10;
      ctx.strokeStyle = hexWithAlpha(glow, isPad ? 0.9 : 0.6);
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(-block.w / 2 + 2, -block.h / 2 + 1);
      ctx.lineTo(block.w / 2 - 2, -block.h / 2 + 1);
      ctx.stroke();
      ctx.shadowBlur = 0;

      if (isPad) {
        // Bounce pad chevrons
        ctx.strokeStyle = hexWithAlpha('#f472b6', 0.5 + 0.3 * Math.sin(t * 5));
        ctx.lineWidth = 2;
        for (let x = -block.w / 2 + 16; x < block.w / 2 - 8; x += 26) {
          ctx.beginPath();
          ctx.moveTo(x, 2);
          ctx.lineTo(x + 8, -4);
          ctx.lineTo(x + 16, 2);
          ctx.stroke();
        }
      } else {
        // Subtle inner strata
        ctx.strokeStyle = hexWithAlpha(glow, 0.08);
        ctx.lineWidth = 1;
        for (let y = -block.h / 2 + 12; y < block.h / 2 - 4; y += 14) {
          ctx.beginPath();
          ctx.moveTo(-block.w / 2 + 6, y);
          ctx.lineTo(block.w / 2 - 6, y);
          ctx.stroke();
        }
      }
      ctx.restore();
    }
  }

  private drawZones(ctx: CanvasRenderingContext2D, arena: ArenaDef, t: number): void {
    for (const z of arena.windZones) {
      ctx.save();
      ctx.fillStyle = 'rgba(96,165,250,0.05)';
      ctx.fillRect(z.x - z.w / 2, z.y - z.h / 2, z.w, z.h);
      ctx.strokeStyle = 'rgba(96,165,250,0.18)';
      ctx.setLineDash([10, 8]);
      ctx.strokeRect(z.x - z.w / 2, z.y - z.h / 2, z.w, z.h);
      ctx.setLineDash([]);
      // Streaks flowing along the force direction
      const mag = Math.hypot(z.fx, z.fy) || 1;
      const ux = z.fx / mag;
      const uy = z.fy / mag;
      ctx.strokeStyle = 'rgba(147,197,253,0.35)';
      ctx.lineWidth = 1.5;
      for (let i = 0; i < 14; i++) {
        const seed = i * 137.5;
        const prog = ((t * 130 * mag + seed * 7) % (z.w + 60)) - 30;
        const px = z.x - z.w / 2 + (ux >= 0 ? prog : z.w - prog);
        const py = z.y - z.h / 2 + ((seed * 3.7) % z.h);
        const len = 20 + (i % 4) * 8;
        ctx.beginPath();
        ctx.moveTo(px, py);
        ctx.lineTo(px + ux * len, py + uy * len);
        ctx.stroke();
      }
      ctx.restore();
    }

    for (const z of arena.gravityZones) {
      ctx.save();
      const pulse = 0.05 + 0.02 * Math.sin(t * 1.5);
      ctx.fillStyle = `rgba(232,121,249,${pulse})`;
      ctx.fillRect(z.x - z.w / 2, z.y - z.h / 2, z.w, z.h);
      ctx.strokeStyle = 'rgba(232,121,249,0.25)';
      ctx.setLineDash([4, 10]);
      ctx.strokeRect(z.x - z.w / 2, z.y - z.h / 2, z.w, z.h);
      ctx.setLineDash([]);
      // Slowly rising motes
      ctx.fillStyle = 'rgba(240,171,252,0.5)';
      for (let i = 0; i < 16; i++) {
        const seed = i * 97.3;
        const px = z.x - z.w / 2 + ((seed * 5.1) % z.w);
        const py = z.y + z.h / 2 - ((t * 26 + seed * 11) % z.h);
        ctx.beginPath();
        ctx.arc(px, py, 1.6 + (i % 3) * 0.7, 0, TAU);
        ctx.fill();
      }
      ctx.restore();
    }
  }

  private drawFinish(ctx: CanvasRenderingContext2D, arena: ArenaDef, t: number): void {
    const f = arena.finish;
    const pulse = 0.55 + 0.35 * Math.sin(t * 3);
    ctx.save();
    const grad = ctx.createLinearGradient(f.x - f.w / 2, 0, f.x + f.w / 2, 0);
    grad.addColorStop(0, 'rgba(74,222,128,0)');
    grad.addColorStop(0.5, `rgba(74,222,128,${0.12 * pulse})`);
    grad.addColorStop(1, 'rgba(74,222,128,0)');
    ctx.fillStyle = grad;
    ctx.fillRect(f.x - f.w / 2, f.y - f.h / 2, f.w, f.h);

    ctx.shadowColor = '#4ade80';
    ctx.shadowBlur = 16;
    ctx.strokeStyle = `rgba(74,222,128,${pulse})`;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(f.x - f.w / 2, f.y - f.h / 2);
    ctx.lineTo(f.x - f.w / 2, f.y + f.h / 2);
    ctx.moveTo(f.x + f.w / 2, f.y - f.h / 2);
    ctx.lineTo(f.x + f.w / 2, f.y + f.h / 2);
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Checkered banner
    ctx.fillStyle = `rgba(74,222,128,${0.5 + 0.3 * pulse})`;
    const bw = 8;
    for (let i = 0; i < Math.floor(f.w / bw); i++) {
      for (let j = 0; j < 2; j++) {
        if ((i + j) % 2 === 0) {
          ctx.fillRect(f.x - f.w / 2 + i * bw, f.y - f.h / 2 - 14 + j * bw, bw, bw);
        }
      }
    }
    ctx.restore();
  }

  // -------------------------------------------------------------------------
  // Robot bodies
  // -------------------------------------------------------------------------

  private drawBodies(ctx: CanvasRenderingContext2D, view: RenderView): void {
    for (let i = 0; i < view.bodies.length && i < view.descs.length; i++) {
      const b = view.bodies[i];
      const d = view.descs[i];
      ctx.save();
      ctx.translate(b.x, b.y);
      ctx.rotate(b.angle);
      switch (d.role) {
        case 'chassis':
          this.drawChassis(ctx, d, view);
          break;
        case 'wheel':
          this.drawWheel(ctx, d);
          break;
        case 'leg-upper':
        case 'leg-lower':
          this.drawLegSegment(ctx, d);
          break;
        case 'foot':
          this.drawFoot(ctx, d);
          break;
        case 'seesaw':
        case 'platform':
          this.drawPlank(ctx, d, view);
          break;
      }
      ctx.restore();
    }
  }

  private drawChassis(ctx: CanvasRenderingContext2D, d: DrawBodyDesc, view: RenderView): void {
    const w = d.w;
    const h = d.h;
    const hue = d.hue;
    const body = ctx.createLinearGradient(0, -h / 2, 0, h / 2);
    body.addColorStop(0, `hsl(${hue}, 30%, 16%)`);
    body.addColorStop(1, `hsl(${hue}, 40%, 8%)`);
    ctx.fillStyle = body;
    ctx.beginPath();
    ctx.roundRect(-w / 2, -h / 2, w, h, 7);
    ctx.fill();

    ctx.shadowColor = `hsl(${hue}, 90%, 60%)`;
    ctx.shadowBlur = 14;
    ctx.strokeStyle = `hsla(${hue}, 90%, 65%, 0.9)`;
    ctx.lineWidth = 1.6;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Panel seams
    ctx.strokeStyle = `hsla(${hue}, 60%, 60%, 0.22)`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(-w / 2 + 10, -h / 2 + 5);
    ctx.lineTo(-w / 2 + 10, h / 2 - 5);
    ctx.moveTo(w / 2 - 10, -h / 2 + 5);
    ctx.lineTo(w / 2 - 10, h / 2 - 5);
    ctx.stroke();

    // Energy core — dims as the battery drains
    const battery = Math.max(0.12, view.batteryFrac);
    const coreR = Math.min(h * 0.34, 9);
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    const pulse = 0.7 + 0.3 * Math.sin(view.t * 4);
    const core = ctx.createRadialGradient(0, 0, 0, 0, 0, coreR * 2.4);
    core.addColorStop(0, `hsla(${hue}, 100%, 75%, ${0.95 * battery * pulse})`);
    core.addColorStop(0.45, `hsla(${hue}, 100%, 60%, ${0.4 * battery})`);
    core.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = core;
    ctx.beginPath();
    ctx.arc(0, 0, coreR * 2.4, 0, TAU);
    ctx.fill();
    ctx.restore();
    ctx.fillStyle = `hsla(${hue}, 100%, ${60 + battery * 25}%, ${0.5 + battery * 0.5})`;
    ctx.beginPath();
    ctx.arc(0, 0, coreR * 0.55, 0, TAU);
    ctx.fill();
  }

  private drawWheel(ctx: CanvasRenderingContext2D, d: DrawBodyDesc): void {
    const r = d.r;
    const hue = d.hue;
    ctx.fillStyle = `hsl(${hue}, 25%, 10%)`;
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, TAU);
    ctx.fill();

    ctx.shadowColor = `hsl(${hue}, 90%, 60%)`;
    ctx.shadowBlur = 10;
    ctx.strokeStyle = `hsla(${hue}, 85%, 62%, 0.9)`;
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Spokes reveal rotation
    ctx.strokeStyle = `hsla(${hue}, 70%, 65%, 0.55)`;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < 3; i++) {
      const a = (i * TAU) / 3;
      ctx.moveTo(Math.cos(a) * r * 0.2, Math.sin(a) * r * 0.2);
      ctx.lineTo(Math.cos(a) * r * 0.82, Math.sin(a) * r * 0.82);
    }
    ctx.stroke();
    ctx.fillStyle = `hsla(${hue}, 90%, 70%, 0.9)`;
    ctx.beginPath();
    ctx.arc(0, 0, 2.5, 0, TAU);
    ctx.fill();
  }

  private drawLegSegment(ctx: CanvasRenderingContext2D, d: DrawBodyDesc): void {
    const hue = d.hue;
    ctx.fillStyle = `hsl(${hue}, 25%, 13%)`;
    ctx.beginPath();
    ctx.roundRect(-d.w / 2, -d.h / 2, d.w, d.h, 3);
    ctx.fill();
    ctx.strokeStyle = `hsla(${hue}, 80%, 60%, 0.7)`;
    ctx.lineWidth = 1.2;
    ctx.shadowColor = `hsl(${hue}, 90%, 60%)`;
    ctx.shadowBlur = 6;
    ctx.stroke();
    ctx.shadowBlur = 0;
    // Glowing joints at both ends
    ctx.fillStyle = `hsla(${hue}, 95%, 70%, 0.9)`;
    ctx.beginPath();
    ctx.arc(0, -d.h / 2, 2.6, 0, TAU);
    ctx.arc(0, d.h / 2, 2.6, 0, TAU);
    ctx.fill();
  }

  private drawFoot(ctx: CanvasRenderingContext2D, d: DrawBodyDesc): void {
    ctx.fillStyle = `hsl(${d.hue}, 40%, 18%)`;
    ctx.beginPath();
    ctx.arc(0, 0, d.r, 0, TAU);
    ctx.fill();
    ctx.strokeStyle = `hsla(${d.hue}, 90%, 65%, 0.85)`;
    ctx.lineWidth = 1.6;
    ctx.shadowColor = `hsl(${d.hue}, 90%, 60%)`;
    ctx.shadowBlur = 8;
    ctx.stroke();
    ctx.shadowBlur = 0;
  }

  private drawPlank(ctx: CanvasRenderingContext2D, d: DrawBodyDesc, view: RenderView): void {
    const accent = view.arena?.theme.accent ?? '#22d3ee';
    ctx.fillStyle = view.arena?.theme.terrain ?? '#0e1b33';
    ctx.beginPath();
    ctx.roundRect(-d.w / 2, -d.h / 2, d.w, d.h, 3);
    ctx.fill();
    ctx.strokeStyle = hexWithAlpha(accent, 0.75);
    ctx.lineWidth = 1.6;
    ctx.shadowColor = accent;
    ctx.shadowBlur = 9;
    ctx.stroke();
    ctx.shadowBlur = 0;
    if (d.role === 'platform') {
      // Hazard ticks on moving platforms
      ctx.strokeStyle = hexWithAlpha(accent, 0.35);
      ctx.lineWidth = 1;
      for (let x = -d.w / 2 + 8; x < d.w / 2 - 4; x += 12) {
        ctx.beginPath();
        ctx.moveTo(x, -d.h / 2 + 3);
        ctx.lineTo(x + 6, d.h / 2 - 3);
        ctx.stroke();
      }
    } else {
      // Seesaw pivot marker
      ctx.fillStyle = hexWithAlpha(accent, 0.9);
      ctx.beginPath();
      ctx.arc(0, 0, 3, 0, TAU);
      ctx.fill();
    }
  }

  // -------------------------------------------------------------------------
  // Fixed decorations (drawn from the design, relative to the chassis body)
  // -------------------------------------------------------------------------

  private drawDecorations(ctx: CanvasRenderingContext2D, view: RenderView): void {
    const design = view.design!;
    const chassis = view.bodies[0];
    const hue = design.hue;
    const firingIds = new Set(view.thrusters.filter((th) => th.firing).map((th) => th.partId));

    ctx.save();
    ctx.translate(chassis.x, chassis.y);
    ctx.rotate(chassis.angle);

    for (const part of design.parts) {
      const { x, y } = part.anchor;
      switch (part.type) {
        case 'glow': {
          const size = part.tuning.size;
          const pulse = 0.55 + 0.45 * Math.sin(view.t * TAU * part.tuning.pulse + x);
          ctx.save();
          ctx.translate(x, y);
          ctx.rotate(part.angle);
          ctx.globalCompositeOperation = 'lighter';
          ctx.fillStyle = `hsla(${(hue + 40) % 360}, 100%, 70%, ${0.8 * pulse})`;
          ctx.shadowColor = `hsl(${(hue + 40) % 360}, 100%, 65%)`;
          ctx.shadowBlur = 12;
          ctx.beginPath();
          ctx.moveTo(0, -size);
          ctx.lineTo(size * 0.3, 0);
          ctx.lineTo(0, size * 0.4);
          ctx.lineTo(-size * 0.3, 0);
          ctx.closePath();
          ctx.fill();
          ctx.restore();
          break;
        }
        case 'sensor': {
          ctx.save();
          ctx.translate(x, y);
          ctx.rotate(part.angle);
          ctx.fillStyle = `hsl(${hue}, 30%, 14%)`;
          ctx.beginPath();
          ctx.arc(0, 0, 6, Math.PI, 0);
          ctx.fill();
          const sweep = (view.t * 2.2) % Math.PI;
          ctx.strokeStyle = `hsla(${(hue + 120) % 360}, 95%, 65%, 0.9)`;
          ctx.lineWidth = 1.6;
          ctx.shadowColor = `hsl(${(hue + 120) % 360}, 95%, 60%)`;
          ctx.shadowBlur = 8;
          ctx.beginPath();
          ctx.arc(0, 0, 5, Math.PI + sweep - 0.35, Math.PI + sweep);
          ctx.stroke();
          ctx.restore();
          break;
        }
        case 'stabilizer': {
          ctx.save();
          ctx.translate(x, y);
          ctx.strokeStyle = `hsla(${hue}, 80%, 65%, 0.8)`;
          ctx.lineWidth = 1.6;
          ctx.shadowColor = `hsl(${hue}, 90%, 60%)`;
          ctx.shadowBlur = 8;
          ctx.beginPath();
          ctx.arc(0, 0, 7, 0, TAU);
          ctx.stroke();
          const spin = view.t * 5;
          ctx.beginPath();
          for (let i = 0; i < 3; i++) {
            const a = spin + (i * TAU) / 3;
            ctx.moveTo(Math.cos(a) * 3, Math.sin(a) * 3);
            ctx.lineTo(Math.cos(a) * 6.4, Math.sin(a) * 6.4);
          }
          ctx.stroke();
          ctx.restore();
          break;
        }
        case 'thruster': {
          ctx.save();
          ctx.translate(x, y);
          ctx.rotate(part.angle);
          ctx.fillStyle = `hsl(${hue}, 25%, 15%)`;
          ctx.beginPath();
          ctx.moveTo(-5, -6);
          ctx.lineTo(5, -6);
          ctx.lineTo(7, 7);
          ctx.lineTo(-7, 7);
          ctx.closePath();
          ctx.fill();
          ctx.strokeStyle = `hsla(${hue}, 85%, 62%, 0.85)`;
          ctx.lineWidth = 1.4;
          ctx.stroke();
          if (firingIds.has(part.id)) {
            ctx.globalCompositeOperation = 'lighter';
            const flare = ctx.createRadialGradient(0, 10, 0, 0, 10, 16);
            flare.addColorStop(0, 'rgba(255,220,150,0.95)');
            flare.addColorStop(0.4, 'rgba(251,146,60,0.6)');
            flare.addColorStop(1, 'rgba(0,0,0,0)');
            ctx.fillStyle = flare;
            ctx.beginPath();
            ctx.arc(0, 10, 16, 0, TAU);
            ctx.fill();
          }
          ctx.restore();
          break;
        }
        default:
          break;
      }
    }
    ctx.restore();
  }

  // -------------------------------------------------------------------------
  // Effects
  // -------------------------------------------------------------------------

  private updateEffects(view: RenderView, dt: number): void {
    if (view.bodies.length > 0) {
      const c = view.bodies[0];
      const last = this.trail[this.trail.length - 1];
      if (!last || Math.hypot(c.x - last.x, c.y - last.y) > 4) {
        this.trail.push({ x: c.x, y: c.y, t: view.t });
        if (this.trail.length > 90) this.trail.shift();
      }
    }

    // Thruster flames
    for (const th of view.thrusters) {
      if (!th.firing) continue;
      if (view.t - this.lastSpawnT > 0.01) {
        for (let i = 0; i < 2; i++) {
          const spread = (Math.random() - 0.5) * 0.5;
          const a = th.angle + Math.PI + spread; // exhaust opposite of thrust
          const speed = 140 + Math.random() * 120;
          this.particles.push({
            x: th.x,
            y: th.y,
            vx: Math.sin(a) * speed,
            vy: -Math.cos(a) * speed,
            life: 0,
            maxLife: 0.3 + Math.random() * 0.25,
            size: 2.2 + Math.random() * 2,
            hue: 30 + Math.random() * 20,
            kind: 'flame',
          });
        }
      }
    }
    if (view.thrusters.some((th) => th.firing)) this.lastSpawnT = view.t;

    for (const p of this.particles) {
      p.life += dt;
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.vy += p.kind === 'flame' ? 60 * dt : 160 * dt;
      p.vx *= 1 - dt * 1.5;
    }
    this.particles = this.particles.filter((p) => p.life < p.maxLife);
    if (this.particles.length > 320) this.particles.splice(0, this.particles.length - 320);
  }

  private drawTrail(ctx: CanvasRenderingContext2D, view: RenderView): void {
    if (this.trail.length < 3 || !view.design) return;
    const hue = view.design.hue;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.lineCap = 'round';
    for (let i = 1; i < this.trail.length; i++) {
      const a = this.trail[i - 1];
      const b = this.trail[i];
      const f = i / this.trail.length;
      ctx.strokeStyle = `hsla(${hue}, 95%, 60%, ${f * 0.28})`;
      ctx.lineWidth = 1 + f * 3;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }
    ctx.restore();
  }

  private drawParticles(ctx: CanvasRenderingContext2D): void {
    if (this.particles.length === 0) return;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    for (const p of this.particles) {
      const f = 1 - p.life / p.maxLife;
      ctx.fillStyle = `hsla(${p.hue}, 100%, ${55 + f * 25}%, ${f * 0.85})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size * (0.5 + f * 0.5), 0, TAU);
      ctx.fill();
    }
    ctx.restore();
  }

  private drawVignette(ctx: CanvasRenderingContext2D, w: number, h: number): void {
    const grad = ctx.createRadialGradient(w / 2, h / 2, h * 0.4, w / 2, h / 2, h * 0.95);
    grad.addColorStop(0, 'rgba(0,0,0,0)');
    grad.addColorStop(1, 'rgba(0,0,0,0.55)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, w, h);
  }
}

const DEFAULT_THEME: ArenaDef['theme'] = {
  skyTop: '#04060f',
  skyBottom: '#0a1228',
  grid: 'rgba(34,211,238,0.08)',
  terrain: '#0e1b33',
  terrainGlow: '#22d3ee',
  accent: '#22d3ee',
};

function hexWithAlpha(hex: string, alpha: number): string {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!m) return hex;
  return `rgba(${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)},${alpha})`;
}
