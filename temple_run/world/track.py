"""
The endless track.

The original monolith generated a *finite* list of segments and then merely
deleted the ones behind the player — so the run literally ended when you reached
the last segment. This version is genuinely endless: the track keeps a rolling
window of live segments, generates fresh road ahead of the player on demand, and
prunes road behind. Absolute segment indices only ever increase (Python ints
don't overflow), so ``segment_index = floor(z / SEGMENT_LENGTH)`` is always
valid and collision/rendering never has to reason about wrap-around.

Road shape is assembled from *pieces* (straights, eased curves, hills, s-curves)
in the classic OutRun/Jake-Gordon style: each segment carries a ``curve`` value
that the renderer accumulates horizontally, and near/far elevations that let the
road roll over hills. Biomes are stamped per absolute index and cross-fade at the
seams, independent of piece boundaries, so themes cycle smoothly forever.
"""

from __future__ import annotations

from typing import List, Optional

from ..config import Track as TCfg, Cam
from ..core.events import Event, EventBus, EventType
from ..mathutils import RNG, ease_in_out_quad, lerp
from .biomes import Biome, biome_at_index, blend_biomes, default_biome, DECOR_KINDS
from .segment import Decoration, Segment

# How many absolute segments one biome occupies before cycling to the next.
BIOME_SEGMENTS = 460
# Fraction of a biome span (at its end) spent cross-fading into the next biome.
BIOME_BLEND_BAND = 0.12

# Curvature magnitudes for the three curve intensities.
CURVE_EASY = 2.2
CURVE_MEDIUM = 4.0
CURVE_HARD = 6.5
# Elevation deltas (world units) for hills.
HILL_LOW = 900.0
HILL_MEDIUM = 2200.0
HILL_HIGH = 4200.0


def _ease(a: float, b: float, t: float) -> float:
    """Ease-in-out interpolation used for both curve and elevation ramps."""
    return a + (b - a) * ease_in_out_quad(0.0 if t < 0 else 1.0 if t > 1 else t)


class Track:
    def __init__(self, rng: Optional[RNG] = None, event_bus: Optional[EventBus] = None):
        self.rng = rng or RNG()
        self.event_bus = event_bus
        self.segments: List[Segment] = []
        # Absolute index of ``segments[0]``.
        self.offset = 0
        # Rolling elevation state used while appending segments.
        self._y = 0.0
        # Player's current segment index (updated in :meth:`update`).
        self.player_index = 0
        # Biome-change detection.
        self._last_biome_key: Optional[str] = None
        self.reset()

    # ------------------------------------------------------------------ setup
    def reset(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            self.rng.reseed(seed)
        self.segments.clear()
        self.offset = 0
        self._y = 0.0
        self.player_index = 0
        self._last_biome_key = None
        # Seed the world with a calm opening straight so the player can settle,
        # then a healthy buffer of road ahead.
        self._add_road(60, 120, 60, 0.0, 0.0, decorate=False)
        self._fill_to(self.total_generated + TCfg.CHUNK_SEGMENTS * TCfg.CHUNKS_AHEAD)

    # -------------------------------------------------------------- accessors
    @property
    def total_generated(self) -> int:
        """One past the highest absolute index generated so far."""
        return self.offset + len(self.segments)

    def seg_at(self, index: int) -> Optional[Segment]:
        i = index - self.offset
        if 0 <= i < len(self.segments):
            return self.segments[i]
        return None

    def segment_at_z(self, z: float) -> Segment:
        idx = int(z // TCfg.SEGMENT_LENGTH)
        seg = self.seg_at(idx)
        if seg is None:
            # Should not happen if update() ran, but degrade gracefully.
            self._fill_to(idx + TCfg.CHUNK_SEGMENTS)
            seg = self.seg_at(idx)
            assert seg is not None
        return seg

    def elevation_at(self, z: float) -> float:
        return self.segment_at_z(z).elevation_at(z)

    def biome_at_z(self, z: float) -> Biome:
        idx = int(z // TCfg.SEGMENT_LENGTH)
        seg = self.seg_at(idx)
        if seg is not None:
            return seg.biome
        return self._biome_for(idx)

    # ---------------------------------------------------------- per-frame tick
    def update(self, player_z: float) -> None:
        """Advance the streaming window to follow the player."""
        self.player_index = int(player_z // TCfg.SEGMENT_LENGTH)
        # Generate enough road ahead to cover the draw distance plus a margin.
        needed = self.player_index + Cam.DRAW_DISTANCE + TCfg.CHUNK_SEGMENTS
        if self.total_generated < needed:
            self._fill_to(needed)
        # Prune road well behind the player to bound memory.
        keep_from = self.player_index - TCfg.CHUNK_SEGMENTS * TCfg.CHUNKS_BEHIND
        if keep_from > self.offset:
            drop = keep_from - self.offset
            if drop > 0:
                del self.segments[:drop]
                self.offset += drop
        # Emit a biome-change event when the player crosses into a new theme.
        biome = self.biome_at_z(player_z)
        base_key = biome.key.split("->")[0]
        if base_key != self._last_biome_key:
            self._last_biome_key = base_key
            if self.event_bus is not None:
                self.event_bus.publish(Event(
                    EventType.BIOME_CHANGED, {"biome": biome, "key": base_key}))

    # -------------------------------------------------------- biome selection
    def _biome_for(self, index: int) -> Biome:
        pos = index / BIOME_SEGMENTS
        i = int(pos)
        frac = pos - i
        a = biome_at_index(i)
        threshold = 1.0 - BIOME_BLEND_BAND
        if frac <= threshold:
            return a
        b = biome_at_index(i + 1)
        t = (frac - threshold) / BIOME_BLEND_BAND
        return blend_biomes(a, b, t)

    # ------------------------------------------------------- segment assembly
    def _add_segment(self, curve: float, y_far: float, decorate: bool = True) -> None:
        n = self.total_generated
        light = (n // TCfg.RUMBLE_LENGTH) % 2 == 0
        seg = Segment(n, self._y, y_far, curve, light, self._biome_for(n))
        if decorate:
            self._decorate(seg)
        self.segments.append(seg)
        self._y = y_far

    def _add_road(self, enter: int, hold: int, leave: int, curve: float,
                  height: float, decorate: bool = True) -> None:
        start_y = self._y
        end_y = start_y + height
        total = enter + hold + leave
        step = 0
        for n in range(enter):
            step += 1
            self._add_segment(_ease(0.0, curve, n / max(1, enter)),
                              _ease(start_y, end_y, step / total), decorate)
        for _ in range(hold):
            step += 1
            self._add_segment(curve, _ease(start_y, end_y, step / total), decorate)
        for n in range(leave):
            step += 1
            self._add_segment(_ease(curve, 0.0, n / max(1, leave)),
                              _ease(start_y, end_y, step / total), decorate)

    # ---------------------------------------------------------- piece library
    def _piece_straight(self) -> None:
        self._add_road(10, self.rng.int_range(30, 70), 10, 0.0, 0.0)

    def _piece_curve(self) -> None:
        mag = self.rng.choice((CURVE_EASY, CURVE_MEDIUM, CURVE_HARD))
        curve = mag * self.rng.sign()
        length = self.rng.int_range(20, 40)
        self._add_road(length, length, length, curve, 0.0)

    def _piece_hill(self) -> None:
        mag = self.rng.choice((HILL_LOW, HILL_MEDIUM, HILL_HIGH))
        height = mag * self.rng.sign()
        # Do not let the world drift too low/high; gently pull back toward 0.
        if self._y > 6000:
            height = -abs(height)
        elif self._y < -6000:
            height = abs(height)
        length = self.rng.int_range(24, 44)
        self._add_road(length, length, length, 0.0, height)

    def _piece_scurve(self) -> None:
        mag = self.rng.choice((CURVE_MEDIUM, CURVE_HARD))
        length = self.rng.int_range(18, 28)
        self._add_road(length, length // 2, length, mag, 0.0)
        self._add_road(length, length // 2, length, -mag, 0.0)

    def _piece_hilly_curve(self) -> None:
        curve = self.rng.choice((CURVE_EASY, CURVE_MEDIUM)) * self.rng.sign()
        height = self.rng.choice((HILL_LOW, HILL_MEDIUM)) * self.rng.sign()
        length = self.rng.int_range(24, 40)
        self._add_road(length, length, length, curve, height)

    def _generate_piece(self) -> None:
        """Append one randomly chosen road piece."""
        kind = self.rng.weighted_key({
            "straight": 3.0,
            "curve": 3.0,
            "hill": 2.0,
            "scurve": 1.5,
            "hilly_curve": 2.0,
        })
        {
            "straight": self._piece_straight,
            "curve": self._piece_curve,
            "hill": self._piece_hill,
            "scurve": self._piece_scurve,
            "hilly_curve": self._piece_hilly_curve,
        }[kind]()

    def _fill_to(self, target_index: int) -> None:
        """Generate road pieces until at least ``target_index`` segments exist."""
        guard = 0
        while self.total_generated < target_index:
            self._generate_piece()
            guard += 1
            if guard > 100000:  # pragma: no cover - runaway guard
                break

    # -------------------------------------------------------------- scenery
    def _decorate(self, seg: Segment) -> None:
        table = seg.biome.decor_table()
        if not table:
            return
        kinds = [k for k, _ in table]
        weights = [w for _, w in table]
        for side in (-1, 1):
            # Sparse placement so scenery reads as landmarks, not a wall.
            if not self.rng.chance(0.16):
                continue
            kind = self.rng.choices(kinds, weights, 1)[0]
            offset = self.rng.range(1.15, 3.4)
            scale = self.rng.range(0.8, 1.8)
            phase = self.rng.range(0.0, 6.28)
            seg.add_decoration(Decoration(kind, side, offset, scale,
                                          seg.biome.obstacle_tint, phase))
