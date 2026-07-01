"""
Screen-space particle system.

Particles are the cheap, high-impact garnish that makes an arcade runner *feel*
expensive: coins pop into a spray of gold, a hit throws sparks, footfalls kick up
dust, powerups bloom a coloured ring. None of it is simulated in the pseudo-3D
world — every particle lives in flat screen pixels and is composited on top of the
rendered scene by the game each frame. That keeps the system decoupled from the
projection maths and dirt-cheap to run.

Design notes and rationale
---------------------------
* **Pooling, not allocation.** A busy frame can spawn a couple hundred particles;
  doing that with fresh objects and letting them fall out of scope would churn the
  garbage collector and cause visible frame hitches. Instead we lease flyweight
  :class:`Particle` objects from :class:`temple_run.core.pool.Pool` and hand them
  back on death, so steady-state play allocates essentially nothing.

* **Data-driven kinds.** Each visual "kind" (dust, spark, coin, ...) is a row in
  :data:`KINDS` describing its physics (gravity, drag), its look (shape, colour,
  glow) and its life-curve (how size and alpha fade). :meth:`ParticleSystem.emit`
  reads that row and randomises within the given ranges. Adding a new effect is a
  dict entry, not new code.

* **No per-particle surface allocation in the hot path.** Glowing particles are
  the only ones that need an SRCALPHA surface, and those are drawn from a *cache*
  of pre-rendered radial-gradient sprites keyed by (radius, colour), scaled on
  blit. Everything else is a hardware-cheap ``pygame.draw`` primitive. The draw
  loop never calls ``Surface(...)`` per particle.

* **Bounded and self-healing.** The live count is capped; if a burst would exceed
  the cap we recycle the oldest particles first so the newest, most relevant
  effect always survives. Nothing here ever raises into the game loop — update and
  draw are wrapped so a bad value degrades to "no particle" rather than a crash.

The public surface is deliberately small: construct one :class:`ParticleSystem`,
call the ``burst_*`` / ``dust`` / ``sparkle`` / ``ring`` / ``powerup_burst``
presets (or the raw :meth:`~ParticleSystem.emit`) when something happens, then
:meth:`~ParticleSystem.update` and :meth:`~ParticleSystem.draw` once per frame.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pygame

from ..config import Color, Palette
from ..core.pool import Pool
from ..mathutils import RNG, clamp, clamp01

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------
#: Hard ceiling on simultaneously-live particles. Beyond a couple of hundred the
#: screen is a wall of colour anyway, so capping here protects the frame budget
#: without any visible loss. When exceeded we drop the *oldest* particles.
MAX_PARTICLES = 800

#: Shapes a particle can be drawn as.
SHAPE_CIRCLE = "circle"
SHAPE_SQUARE = "square"
SHAPE_STREAK = "streak"   # a motion-blur line along the velocity vector
SHAPE_RING = "ring"       # an expanding hollow annulus (shockwaves)

#: How large the cached glow sprites can get before we just clamp; keeps the
#: glow-surface cache from ballooning if something asks for a giant particle.
_MAX_GLOW_RADIUS = 64


# ---------------------------------------------------------------------------
# The particle flyweight
# ---------------------------------------------------------------------------
@dataclass
class Particle:
    """A single pooled particle.

    Instances are leased from a :class:`Pool`; :meth:`reset` wipes one back to a
    neutral state so a recycled particle never inherits stale motion. All fields
    are plain floats/ints so the object is cheap to churn through in a tight loop.
    """

    # -- kinematics (screen pixels) --
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    gravity: float = 0.0          # px/s^2 added to vy each step
    drag: float = 0.0             # per-second velocity damping (0 = none)

    # -- life --
    age: float = 0.0              # seconds since emission
    life: float = 1.0             # total lifetime in seconds
    alive: bool = False

    # -- appearance --
    color: Color = (255, 255, 255)
    size: float = 3.0             # base radius/half-extent in pixels
    end_size: float = 0.0         # radius the particle shrinks/grows toward
    shape: str = SHAPE_CIRCLE
    glow: bool = False            # draw an additive-ish halo underneath
    spin: float = 0.0             # radians/s (squares & streaks rotate)
    angle: float = 0.0            # current rotation in radians
    fade_pow: float = 1.0         # >1 = stays bright then drops off late

    def reset(self) -> None:
        """Return the particle to a neutral, dead state (called by the pool)."""
        self.x = self.y = 0.0
        self.vx = self.vy = 0.0
        self.gravity = 0.0
        self.drag = 0.0
        self.age = 0.0
        self.life = 1.0
        self.alive = False
        self.color = (255, 255, 255)
        self.size = 3.0
        self.end_size = 0.0
        self.shape = SHAPE_CIRCLE
        self.glow = False
        self.spin = 0.0
        self.angle = 0.0
        self.fade_pow = 1.0

    # -- derived helpers ----------------------------------------------------
    @property
    def t(self) -> float:
        """Normalised life progress in ``[0, 1]`` (0 = born, 1 = dead)."""
        if self.life <= 0.0:
            return 1.0
        return clamp01(self.age / self.life)

    def current_size(self) -> float:
        """Interpolated radius/half-extent for the current life fraction."""
        return self.size + (self.end_size - self.size) * self.t

    def current_alpha(self) -> int:
        """Opacity 0..255 for the current life fraction.

        ``fade_pow`` shapes the curve: 1.0 is a plain linear fade, values >1
        keep the particle bright for most of its life and then drop quickly.
        """
        remaining = 1.0 - self.t
        a = remaining ** self.fade_pow if self.fade_pow != 1.0 else remaining
        return int(clamp(a, 0.0, 1.0) * 255)


# ---------------------------------------------------------------------------
# Kind table: the "recipe" for each visual effect.
# ---------------------------------------------------------------------------
# Every value is either a scalar (used as-is) or a ``(lo, hi)`` range that
# :meth:`ParticleSystem.emit` samples per particle. Keeping the recipes as data
# means the emit code is a single generic loop and new effects are one dict row.
_Range = Tuple[float, float]

KINDS: Dict[str, dict] = {
    # Kicked-up ground dust for footfalls / landings — soft, drifts up, fades.
    "dust": {
        "speed": (40.0, 130.0),
        "angle": (200.0, 340.0),        # degrees; mostly up-and-out
        "life": (0.30, 0.55),
        "size": (3.0, 7.0),
        "end_size": (0.5, 1.5),
        "gravity": (60.0, 140.0),
        "drag": 2.6,
        "color": (Palette.LIGHT_GREY, Palette.GREY),
        "shape": SHAPE_CIRCLE,
        "glow": False,
        "fade_pow": 1.0,
    },
    # Lazy rising smoke — slow, buoyant, grows as it thins.
    "smoke": {
        "speed": (12.0, 55.0),
        "angle": (240.0, 300.0),
        "life": (0.7, 1.4),
        "size": (5.0, 11.0),
        "end_size": (16.0, 26.0),
        "gravity": (-40.0, -12.0),      # negative = buoyant
        "drag": 1.8,
        "color": (Palette.DARK_GREY, Palette.GREY),
        "shape": SHAPE_CIRCLE,
        "glow": False,
        "fade_pow": 0.8,
    },
    # Gold spray from a collected coin — bright, glowing, gravity-pulled.
    "coin": {
        "speed": (140.0, 340.0),
        "angle": (0.0, 360.0),
        "life": (0.35, 0.7),
        "size": (2.0, 4.5),
        "end_size": (0.0, 1.0),
        "gravity": (520.0, 720.0),
        "drag": 0.8,
        "color": (Palette.GOLD, Palette.GOLD_DARK),
        "shape": SHAPE_CIRCLE,
        "glow": True,
        "fade_pow": 1.4,
    },
    # Impact sparks — fast streaks that shoot out and burn quickly.
    "spark": {
        "speed": (260.0, 620.0),
        "angle": (0.0, 360.0),
        "life": (0.18, 0.42),
        "size": (2.0, 4.0),
        "end_size": (0.0, 0.5),
        "gravity": (300.0, 520.0),
        "drag": 1.2,
        "color": (Palette.WARNING, Palette.DANGER),
        "shape": SHAPE_STREAK,
        "glow": True,
        "fade_pow": 1.6,
    },
    # Twinkle — near-static glints (magnet pickups, sparkle trails).
    "sparkle": {
        "speed": (10.0, 70.0),
        "angle": (0.0, 360.0),
        "life": (0.4, 0.9),
        "size": (1.5, 3.5),
        "end_size": (0.0, 0.5),
        "gravity": (-30.0, 30.0),
        "drag": 3.0,
        "color": (Palette.WHITE, Palette.INFO),
        "shape": SHAPE_CIRCLE,
        "glow": True,
        "fade_pow": 2.0,
    },
    # Celebration confetti — spinning squares that flutter down.
    "confetti": {
        "speed": (160.0, 380.0),
        "angle": (200.0, 340.0),
        "life": (0.9, 1.8),
        "size": (3.0, 6.0),
        "end_size": (3.0, 6.0),         # confetti keeps its size, just tumbles
        "gravity": (240.0, 380.0),
        "drag": 1.4,
        "color": None,                  # sentinel: pick a vivid palette hue
        "shape": SHAPE_SQUARE,
        "glow": False,
        "spin": (6.0, 16.0),
        "fade_pow": 1.0,
    },
    # Expanding shockwave ring (powerups, big pickups).
    "ring": {
        "speed": (0.0, 0.0),            # rings do not translate; they expand
        "angle": (0.0, 0.0),
        "life": (0.32, 0.5),
        "size": (6.0, 10.0),
        "end_size": (60.0, 96.0),
        "gravity": (0.0, 0.0),
        "drag": 0.0,
        "color": (Palette.UI_ACCENT, Palette.UI_ACCENT),
        "shape": SHAPE_RING,
        "glow": True,
        "fade_pow": 1.2,
    },
    # Coloured energy motes for a powerup burst — glow hard, drift outward.
    "energy": {
        "speed": (120.0, 300.0),
        "angle": (0.0, 360.0),
        "life": (0.4, 0.85),
        "size": (3.0, 6.0),
        "end_size": (0.0, 1.0),
        "gravity": (-60.0, 60.0),
        "drag": 1.5,
        "color": (Palette.UI_ACCENT, Palette.UI_ACCENT),
        "shape": SHAPE_CIRCLE,
        "glow": True,
        "fade_pow": 1.5,
    },
}

#: A handful of saturated hues confetti draws from at random.
_CONFETTI_COLORS: Tuple[Color, ...] = (
    Palette.GOLD,
    Palette.GEM,
    Palette.DANGER,
    Palette.SUCCESS,
    Palette.INFO,
    Palette.WARNING,
    Palette.UI_ACCENT,
    Palette.WHITE,
)


class ParticleSystem:
    """Owns, updates and draws every live particle in screen space.

    Construct once and share it across the game. Producers call the preset
    helpers (or :meth:`emit`) when something visual happens; the game calls
    :meth:`update` and :meth:`draw` once per frame and :meth:`clear` on restart.
    """

    def __init__(self, rng: Optional[RNG] = None, enabled: bool = True) -> None:
        # Deterministic randomness where a seed is provided (reproducible demos);
        # otherwise a fresh, time-seeded stream.
        self._rng: RNG = rng if rng is not None else RNG()

        # When disabled (e.g. the "particles" setting is off) emits become
        # no-ops but update/draw stay safe, so toggling never leaks live objects.
        self.enabled = enabled

        # The pool: build blank particles, reset on release. ``max_size`` bounds
        # the *free* list so we never hoard idle objects after a big burst.
        self._pool: Pool[Particle] = Pool(
            factory=Particle,
            reset=lambda p: p.reset(),
            prefill=128,
            max_size=MAX_PARTICLES,
        )

        # Live particles, kept newest-last so trimming the oldest is a cheap
        # slice from the front.
        self._particles: List[Particle] = []

        # Cache of pre-rendered radial glow sprites, keyed by (radius, colour).
        # Rendering a soft halo pixel-by-pixel is expensive; we do it once per
        # distinct look and thereafter just blit (optionally scaled).
        self._glow_cache: Dict[Tuple[int, Color], pygame.Surface] = {}

    # ------------------------------------------------------------------ counts
    @property
    def count(self) -> int:
        """Number of currently live particles."""
        return len(self._particles)

    def __len__(self) -> int:
        return len(self._particles)

    # ------------------------------------------------------------------ emit
    def emit(self, kind: str, x: float, y: float, count: int = 1, **kw) -> None:
        """Spawn ``count`` particles of ``kind`` at ``(x, y)``.

        ``kind`` names a row in :data:`KINDS`. Keyword overrides let a caller
        tweak a single spawn without inventing a new kind — the most useful being
        ``color`` (force a specific hue), ``speed_scale`` (multiply the emission
        speed) and ``spread`` (an emission cone override in degrees). Unknown
        kinds and disabled systems are silent no-ops so call-sites need no guards.
        """
        if not self.enabled or count <= 0:
            return
        recipe = KINDS.get(kind)
        if recipe is None:
            return

        # Optional per-emit overrides.
        forced_color: Optional[Color] = kw.get("color")
        speed_scale: float = float(kw.get("speed_scale", 1.0))
        angle_lo, angle_hi = recipe["angle"]
        if "spread" in kw and "direction" in kw:
            # Emit within ``spread`` degrees either side of ``direction``.
            d = float(kw["direction"])
            half = float(kw["spread"]) * 0.5
            angle_lo, angle_hi = d - half, d + half

        # Optional positional scatter so a burst doesn't spawn from one pixel.
        jitter: float = float(kw.get("jitter", 0.0))

        rng = self._rng
        for _ in range(count):
            p = self._acquire()
            if p is None:
                break  # at the cap and nothing recyclable; stop early

            speed = self._sample(recipe["speed"]) * speed_scale
            ang = math.radians(rng.range(angle_lo, angle_hi))
            p.x = x + (rng.range(-jitter, jitter) if jitter > 0.0 else 0.0)
            p.y = y + (rng.range(-jitter, jitter) if jitter > 0.0 else 0.0)
            p.vx = math.cos(ang) * speed
            p.vy = math.sin(ang) * speed
            p.gravity = self._sample(recipe["gravity"])
            p.drag = float(recipe["drag"])
            p.life = max(0.01, self._sample(recipe["life"]))
            p.age = 0.0
            p.size = self._sample(recipe["size"])
            p.end_size = self._sample(recipe["end_size"])
            p.shape = recipe["shape"]
            p.glow = bool(recipe["glow"])
            p.fade_pow = float(recipe.get("fade_pow", 1.0))
            p.spin = self._sample(recipe["spin"]) if "spin" in recipe else 0.0
            p.angle = rng.range(0.0, math.tau)
            p.color = self._pick_color(recipe, forced_color)
            p.alive = True
            self._particles.append(p)

    # ------------------------------------------------------------- presets
    def burst_coins(self, x: float, y: float, count: int = 12) -> None:
        """Gold spray for a collected coin, topped with a couple of glints."""
        self.emit("coin", x, y, count)
        self.emit("sparkle", x, y, max(1, count // 4), color=Palette.GOLD)

    def burst_hit(self, x: float, y: float, count: int = 22) -> None:
        """Violent spark + smoke burst for an obstacle collision."""
        self.emit("spark", x, y, count)
        self.emit("smoke", x, y, max(3, count // 4))

    def dust(self, x: float, y: float, count: int = 8) -> None:
        """Ground puff for footfalls, landings and slides."""
        self.emit("dust", x, y, count)

    def smoke(self, x: float, y: float, count: int = 6) -> None:
        """Standalone rising smoke plume."""
        self.emit("smoke", x, y, count)

    def sparkle(self, x: float, y: float, color: Color, count: int = 6) -> None:
        """Twinkling glints in ``color`` (magnet pulls, shiny pickups)."""
        self.emit("sparkle", x, y, count, color=color)

    def confetti(self, x: float, y: float, count: int = 40) -> None:
        """A shower of spinning multicoloured squares for celebrations."""
        self.emit("confetti", x, y, count)

    def ring(self, x: float, y: float, color: Color, count: int = 1) -> None:
        """One (or a few) expanding shockwave ring(s) in ``color``."""
        self.emit("ring", x, y, count, color=color)

    def powerup_burst(self, x: float, y: float, color: Color) -> None:
        """The full powerup fanfare: a ring, an energy spray and some sparkle."""
        self.ring(x, y, color)
        self.emit("energy", x, y, 26, color=color)
        self.emit("sparkle", x, y, 10, color=color)

    # --------------------------------------------------------------- lifecycle
    def update(self, dt: float) -> None:
        """Integrate every particle and recycle the dead ones.

        Robust by construction: a rogue ``dt`` (a debugger pause, a stutter)
        cannot teleport particles because we clamp it, and any per-particle error
        is swallowed so the game loop never sees an exception from here.
        """
        if dt <= 0.0:
            return
        # Clamp so a hitch can't fling everything off-screen in one step.
        dt = min(dt, 0.1)

        survivors: List[Particle] = []
        pool = self._pool
        for p in self._particles:
            p.age += dt
            if p.age >= p.life:
                p.alive = False
                pool.release(p)
                continue

            # Semi-implicit Euler: apply gravity, then exponential drag, then move.
            p.vy += p.gravity * dt
            if p.drag > 0.0:
                damp = math.exp(-p.drag * dt)
                p.vx *= damp
                p.vy *= damp
            p.x += p.vx * dt
            p.y += p.vy * dt
            if p.spin:
                p.angle += p.spin * dt
            survivors.append(p)

        self._particles = survivors

    def draw(self, surface: pygame.Surface) -> None:
        """Composite every live particle onto ``surface``.

        Draw errors are caught per-particle so one bad value can never abort the
        frame; the worst case is a single missing speck.
        """
        blit = surface.blit
        for p in self._particles:
            try:
                self._draw_one(surface, p, blit)
            except (ValueError, TypeError, pygame.error):
                # Degenerate geometry (e.g. zero radius, NaN) — skip this speck.
                continue

    def clear(self) -> None:
        """Recycle every live particle (called on restart / scene change)."""
        for p in self._particles:
            p.alive = False
            self._pool.release(p)
        self._particles.clear()

    # ------------------------------------------------------------ internals
    def _acquire(self) -> Optional[Particle]:
        """Lease a particle, enforcing the live cap by dropping the oldest.

        Returns ``None`` only in the pathological case where the cap is zero.
        """
        if len(self._particles) >= MAX_PARTICLES:
            # Recycle the oldest so the freshest effect always wins the budget.
            oldest = self._particles.pop(0)
            oldest.alive = False
            self._pool.release(oldest)
        if MAX_PARTICLES <= 0:
            return None
        return self._pool.acquire()

    def _sample(self, spec) -> float:
        """Resolve a scalar-or-``(lo, hi)`` recipe field to a concrete float."""
        if isinstance(spec, (tuple, list)):
            lo, hi = spec
            return self._rng.range(float(lo), float(hi)) if lo != hi else float(lo)
        return float(spec)

    def _pick_color(self, recipe: dict, forced: Optional[Color]) -> Color:
        """Choose a particle colour: forced override > confetti hue > recipe pair."""
        if forced is not None:
            return forced
        spec = recipe.get("color")
        if spec is None:
            # Confetti sentinel — draw a vivid random hue.
            return self._rng.choice(_CONFETTI_COLORS)
        # ``color`` is a (base, dark) pair; blend randomly between the two so a
        # burst reads as a family of shades rather than one flat colour.
        base, dark = spec
        t = self._rng.random()
        return (
            int(base[0] + (dark[0] - base[0]) * t),
            int(base[1] + (dark[1] - base[1]) * t),
            int(base[2] + (dark[2] - base[2]) * t),
        )

    # -- rendering primitives ------------------------------------------------
    def _draw_one(self, surface: pygame.Surface, p: Particle, blit) -> None:
        """Dispatch a single particle to the right primitive drawer."""
        size = p.current_size()
        if size < 0.5 and p.shape != SHAPE_STREAK:
            return
        alpha = p.current_alpha()
        if alpha <= 0:
            return

        # Glow underlay first so the crisp core sits on top of the halo.
        if p.glow:
            self._blit_glow(surface, p, size, alpha, blit)

        if p.shape == SHAPE_CIRCLE:
            self._draw_circle(surface, p, size, alpha)
        elif p.shape == SHAPE_SQUARE:
            self._draw_square(surface, p, size, alpha, blit)
        elif p.shape == SHAPE_STREAK:
            self._draw_streak(surface, p, size, alpha)
        elif p.shape == SHAPE_RING:
            self._draw_ring(surface, p, size, alpha)

    def _draw_circle(self, surface: pygame.Surface, p: Particle, size: float, alpha: int) -> None:
        r = max(1, int(size))
        if alpha >= 250:
            # Fully (or near) opaque: draw straight to the target, no temp surf.
            pygame.draw.circle(surface, p.color, (int(p.x), int(p.y)), r)
            return
        # Translucent: use a tiny cached alpha surface so we never alloc per draw.
        surf = self._solid_disc(r, p.color)
        surf.set_alpha(alpha)
        surface.blit(surf, (int(p.x) - r, int(p.y) - r))

    def _draw_square(self, surface: pygame.Surface, p: Particle, size: float, alpha: int, blit) -> None:
        half = max(1.0, size)
        # Corners of an axis-aligned square, rotated by the particle's spin.
        c, s = math.cos(p.angle), math.sin(p.angle)
        pts = []
        for dx, dy in ((-half, -half), (half, -half), (half, half), (-half, half)):
            pts.append((p.x + dx * c - dy * s, p.y + dx * s + dy * c))
        if alpha >= 250:
            pygame.draw.polygon(surface, p.color, pts)
            return
        # Rotated + translucent: render into a small SRCALPHA surface, then blit.
        span = int(math.ceil(half * 2.9)) + 2
        tmp = pygame.Surface((span, span), pygame.SRCALPHA)
        cx = cy = span / 2.0
        local = [(px - p.x + cx, py - p.y + cy) for px, py in pts]
        pygame.draw.polygon(tmp, (*p.color, alpha), local)
        blit(tmp, (int(p.x - cx), int(p.y - cy)))

    def _draw_streak(self, surface: pygame.Surface, p: Particle, size: float, alpha: int) -> None:
        # A streak is a short line trailing back along the velocity vector, its
        # length scaled by speed so fast sparks read as longer smears.
        speed = math.hypot(p.vx, p.vy)
        if speed < 1e-3:
            self._draw_circle(surface, p, max(1.0, size), alpha)
            return
        length = clamp(speed * 0.03, 4.0, 34.0)
        ux, uy = p.vx / speed, p.vy / speed
        tail = (p.x - ux * length, p.y - uy * length)
        head = (p.x, p.y)
        width = max(1, int(size))
        if alpha >= 250:
            pygame.draw.line(surface, p.color, tail, head, width)
            return
        # Translucent streak: draw onto a bounding SRCALPHA surface, then blit.
        min_x = int(min(head[0], tail[0])) - width - 1
        min_y = int(min(head[1], tail[1])) - width - 1
        w = int(abs(head[0] - tail[0])) + width * 2 + 2
        h = int(abs(head[1] - tail[1])) + width * 2 + 2
        tmp = pygame.Surface((max(1, w), max(1, h)), pygame.SRCALPHA)
        pygame.draw.line(
            tmp, (*p.color, alpha),
            (tail[0] - min_x, tail[1] - min_y),
            (head[0] - min_x, head[1] - min_y),
            width,
        )
        surface.blit(tmp, (min_x, min_y))

    def _draw_ring(self, surface: pygame.Surface, p: Particle, size: float, alpha: int) -> None:
        r = max(1, int(size))
        # Ring thickness thins as it expands, mimicking a dissipating shockwave.
        thickness = max(1, int(clamp(r * 0.18, 1.0, 6.0) * (1.0 - p.t) + 1.0))
        thickness = min(thickness, r)
        if alpha >= 250:
            pygame.draw.circle(surface, p.color, (int(p.x), int(p.y)), r, thickness)
            return
        span = r * 2 + thickness * 2 + 2
        tmp = pygame.Surface((span, span), pygame.SRCALPHA)
        centre = span // 2
        pygame.draw.circle(tmp, (*p.color, alpha), (centre, centre), r, thickness)
        surface.blit(tmp, (int(p.x) - centre, int(p.y) - centre))

    def _blit_glow(self, surface: pygame.Surface, p: Particle, size: float, alpha: int, blit) -> None:
        """Blit a soft radial halo under the particle for an additive-ish bloom."""
        glow_r = min(_MAX_GLOW_RADIUS, max(2, int(size * 2.2)))
        sprite = self._glow_sprite(glow_r, p.color)
        # Scale the halo's own alpha with the particle's fade so it dies with it.
        sprite.set_alpha(int(alpha * 0.6))
        blit(sprite, (int(p.x) - glow_r, int(p.y) - glow_r),
             special_flags=pygame.BLEND_RGBA_ADD)

    # -- cached sprite factories --------------------------------------------
    def _glow_sprite(self, radius: int, color: Color) -> pygame.Surface:
        """Return a cached soft radial-gradient halo of ``radius`` in ``color``.

        Built once per distinct (radius, colour) pair. The gradient is drawn as a
        stack of concentric translucent circles — cheap, and only paid once.
        """
        key = (radius, color)
        cached = self._glow_cache.get(key)
        if cached is not None:
            return cached

        diameter = radius * 2
        surf = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        centre = radius
        # Draw from outside in so inner (brighter) rings overwrite outer ones.
        steps = max(4, radius)
        for i in range(steps, 0, -1):
            frac = i / steps
            rr = int(radius * frac)
            # Falloff: quadratic so the core stays punchy and the edge feathers.
            a = int(90 * (1.0 - frac) ** 2 + 12 * (1.0 - frac))
            if rr <= 0 or a <= 0:
                continue
            pygame.draw.circle(surf, (*color, a), (centre, centre), rr)
        self._glow_cache[key] = surf
        return surf

    def _solid_disc(self, radius: int, color: Color) -> pygame.Surface:
        """Return a cached opaque disc used for translucent circle blits.

        Reusing one surface per (radius, colour) and adjusting ``set_alpha`` on
        blit keeps the translucent-circle path allocation-free after warm-up.
        """
        key = (-radius, color)  # negative radius namespace: distinct from glow cache
        cached = self._glow_cache.get(key)
        if cached is not None:
            return cached
        diameter = max(1, radius * 2)
        surf = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        pygame.draw.circle(surf, (*color, 255), (radius, radius), radius)
        self._glow_cache[key] = surf
        return surf
