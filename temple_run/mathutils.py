"""
Math helpers shared across the whole engine.

Kept dependency-free (only the standard library) so it can be imported by any
module, including the projection code that the renderer and collision system
must agree on to the last decimal.
"""

from __future__ import annotations

import math
import random
from typing import Iterable, List, Sequence, Tuple

TAU = math.tau
PI = math.pi


# ---------------------------------------------------------------------------
# Scalar helpers
# ---------------------------------------------------------------------------
def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation from ``a`` to ``b`` by ``t`` (unclamped)."""
    return a + (b - a) * t


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def inv_lerp(a: float, b: float, v: float) -> float:
    """Inverse lerp: where does ``v`` sit between ``a`` and ``b`` (0..1)."""
    if a == b:
        return 0.0
    return clamp01((v - a) / (b - a))


def remap(v: float, in_lo: float, in_hi: float, out_lo: float, out_hi: float) -> float:
    return lerp(out_lo, out_hi, inv_lerp(in_lo, in_hi, v))


def approach(current: float, target: float, delta: float) -> float:
    """Move ``current`` toward ``target`` by at most ``delta`` (never past it)."""
    if current < target:
        return min(current + delta, target)
    return max(current - delta, target)


def damp(current: float, target: float, smoothing: float, dt: float) -> float:
    """Frame-rate independent exponential smoothing toward ``target``.

    ``smoothing`` is roughly "how much of the gap remains after one second".
    """
    return lerp(current, target, 1.0 - math.pow(clamp01(smoothing), dt))


def sign(v: float) -> float:
    return (v > 0) - (v < 0)


def wrap(v: float, size: float) -> float:
    """Wrap ``v`` into ``[0, size)``."""
    return v - math.floor(v / size) * size


def ping_pong(t: float, length: float) -> float:
    """Bounce ``t`` back and forth in ``[0, length]``."""
    t = wrap(t, length * 2.0)
    return length - abs(t - length)


# ---------------------------------------------------------------------------
# Easing curves (Robert Penner family, normalised to t in [0, 1])
# ---------------------------------------------------------------------------
def ease_in_quad(t: float) -> float:
    return t * t


def ease_out_quad(t: float) -> float:
    return 1.0 - (1.0 - t) * (1.0 - t)


def ease_in_out_quad(t: float) -> float:
    return 2.0 * t * t if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 2 / 2.0


def ease_in_cubic(t: float) -> float:
    return t * t * t


def ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    return 4.0 * t * t * t if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


def ease_out_back(t: float, overshoot: float = 1.70158) -> float:
    c3 = overshoot + 1.0
    return 1.0 + c3 * (t - 1.0) ** 3 + overshoot * (t - 1.0) ** 2


def ease_out_elastic(t: float) -> float:
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    c4 = TAU / 3.0
    return math.pow(2.0, -10.0 * t) * math.sin((t * 10.0 - 0.75) * c4) + 1.0


def ease_out_bounce(t: float) -> float:
    n1, d1 = 7.5625, 2.75
    if t < 1.0 / d1:
        return n1 * t * t
    if t < 2.0 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    if t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    t -= 2.625 / d1
    return n1 * t * t + 0.984375


def smoothstep(edge0: float, edge1: float, x: float) -> float:
    t = clamp01((x - edge0) / (edge1 - edge0)) if edge1 != edge0 else 0.0
    return t * t * (3.0 - 2.0 * t)


# ---------------------------------------------------------------------------
# 2D vector (lightweight; we avoid pygame.Vector2 in pure-logic modules)
# ---------------------------------------------------------------------------
class Vec2:
    __slots__ = ("x", "y")

    def __init__(self, x: float = 0.0, y: float = 0.0):
        self.x = x
        self.y = y

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Vec2({self.x:.2f}, {self.y:.2f})"

    def copy(self) -> "Vec2":
        return Vec2(self.x, self.y)

    def set(self, x: float, y: float) -> "Vec2":
        self.x, self.y = x, y
        return self

    def add(self, o: "Vec2") -> "Vec2":
        return Vec2(self.x + o.x, self.y + o.y)

    def sub(self, o: "Vec2") -> "Vec2":
        return Vec2(self.x - o.x, self.y - o.y)

    def scale(self, s: float) -> "Vec2":
        return Vec2(self.x * s, self.y * s)

    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def length_sq(self) -> float:
        return self.x * self.x + self.y * self.y

    def normalized(self) -> "Vec2":
        n = self.length()
        return Vec2(0.0, 0.0) if n == 0 else Vec2(self.x / n, self.y / n)

    def dot(self, o: "Vec2") -> float:
        return self.x * o.x + self.y * o.y

    def rotate(self, radians: float) -> "Vec2":
        c, s = math.cos(radians), math.sin(radians)
        return Vec2(self.x * c - self.y * s, self.x * s + self.y * c)

    def as_tuple(self) -> Tuple[float, float]:
        return (self.x, self.y)


def distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(bx - ax, by - ay)


# ---------------------------------------------------------------------------
# Random helpers with a deterministic, seedable stream
# ---------------------------------------------------------------------------
class RNG:
    """A thin wrapper around ``random.Random`` with game-friendly helpers.

    Using an explicit instance (rather than the module-level ``random``) means
    the whole world can be reproduced from a seed, which matters for the daily
    challenge mode and for debugging spawn layouts.
    """

    def __init__(self, seed: int | None = None):
        self._r = random.Random(seed)
        self.seed_value = seed

    def reseed(self, seed: int) -> None:
        self._r.seed(seed)
        self.seed_value = seed

    def random(self) -> float:
        return self._r.random()

    def range(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self._r.random()

    def int_range(self, lo: int, hi: int) -> int:
        return self._r.randint(lo, hi)

    def chance(self, p: float) -> bool:
        return self._r.random() < p

    def choice(self, seq: Sequence):
        return self._r.choice(seq)

    def choices(self, seq: Sequence, weights: Sequence[float], k: int = 1) -> List:
        return self._r.choices(seq, weights=weights, k=k)

    def shuffle(self, seq: List) -> None:
        self._r.shuffle(seq)

    def sign(self) -> int:
        return 1 if self._r.random() < 0.5 else -1

    def weighted_key(self, weights: dict):
        """Pick a dict key with probability proportional to its value."""
        keys = list(weights.keys())
        vals = list(weights.values())
        return self._r.choices(keys, weights=vals, k=1)[0]


# ---------------------------------------------------------------------------
# Perspective projection — the single source of truth for world -> screen.
# ---------------------------------------------------------------------------
class Projected:
    """Result of projecting one world point to the screen for this frame."""

    __slots__ = ("x", "y", "w", "scale")

    def __init__(self, x: float, y: float, w: float, scale: float):
        self.x = x      # screen x (pixels)
        self.y = y      # screen y (pixels)
        self.w = w      # projected road half-width (pixels)
        self.scale = scale  # perspective scale factor (>0 nearer)


def project(
    world_x: float,
    world_y: float,
    world_z: float,
    cam_x: float,
    cam_y: float,
    cam_z: float,
    cam_depth: float,
    width: int,
    height: int,
    road_width: float,
) -> Projected:
    """Project a world point to screen space.

    This is the canonical pin-hole perspective used by the renderer *and* by any
    system that needs to know where something will appear (e.g. the magnet
    effect, floating score text). Keep the maths here and nowhere else.
    """
    dz = world_z - cam_z
    if dz < 1.0:
        dz = 1.0  # never divide by <=0; clamp to just in front of the eye
    scale = cam_depth / dz
    sx = (width * 0.5) + (scale * (world_x - cam_x) * width * 0.5)
    sy = (height * 0.5) - (scale * (world_y - cam_y) * height * 0.5)
    sw = scale * road_width * width * 0.5
    return Projected(sx, sy, sw, scale)


def polygon_visible(y1: float, y2: float, height: int) -> bool:
    """Cheap vertical clip: is a road quad within the viewport at all?"""
    top = min(y1, y2)
    bottom = max(y1, y2)
    return bottom >= 0 and top <= height


def catmull_rom(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    """1D Catmull-Rom spline used to smooth procedural hill/curve keyframes."""
    t2 = t * t
    t3 = t2 * t
    return 0.5 * (
        (2.0 * p1)
        + (-p0 + p2) * t
        + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2
        + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
    )


def moving_average(values: Iterable[float], window: int) -> List[float]:
    """Simple smoothing used by the difficulty director for readouts."""
    vals = list(values)
    if window <= 1 or not vals:
        return vals
    out: List[float] = []
    acc = 0.0
    q: List[float] = []
    for v in vals:
        q.append(v)
        acc += v
        if len(q) > window:
            acc -= q.pop(0)
        out.append(acc / len(q))
    return out
