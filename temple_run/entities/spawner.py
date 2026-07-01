"""
The spawner — procedural, *fair* population of the track ahead of the player.

Two properties the original lacked:

1. **Endless.** Features are streamed in ahead of the player and recycled behind,
   using object pools so no per-frame allocation churn.
2. **Fair.** An obstacle "row" never blocks all three lanes, and the open lane is
   always *adjacent-reachable* from the previously open lane — so a perfect run is
   always physically possible. This is what separates a real endless runner from a
   random death generator.

Difficulty is injected as a :class:`SpawnKnobs` bundle (produced by the difficulty
director), so pacing lives in one place and the spawner just obeys it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..config import Cam, Track as TCfg
from ..core.pool import Pool
from ..mathutils import RNG, clamp
from .collectibles import Coin, Gem, PowerupPickup, make_coin, make_gem, make_powerup
from .entity import Entity, PickupKind
from .obstacles import Obstacle, make_obstacle
from .powerup_types import POWERUP_KEYS

LANES = (-1, 0, 1)
SPAWN_AHEAD = Cam.DRAW_DISTANCE * TCfg.SEGMENT_LENGTH * 0.85
RECYCLE_BEHIND = TCfg.SEGMENT_LENGTH * 8


@dataclass
class SpawnKnobs:
    """Difficulty-controlled spawning parameters (one feature "slot" per gap)."""
    feature_gap: float = 2600.0     # world units between feature slots
    obstacle_prob: float = 0.55
    coin_prob: float = 0.30
    gem_prob: float = 0.04
    powerup_prob: float = 0.05
    double_prob: float = 0.18        # chance an obstacle row blocks two lanes
    moving_prob: float = 0.08        # chance an obstacle is a moving roller
    coin_run_len: int = 6            # coins per coin run


def _adjacent(a: int, b: int) -> bool:
    return abs(a - b) <= 1


class Spawner:
    def __init__(self, rng: Optional[RNG] = None):
        self.rng = rng or RNG()
        self.obstacles: Pool[Obstacle] = Pool(make_obstacle, prefill=32)
        self.coins: Pool[Coin] = Pool(make_coin, prefill=96)
        self.gems: Pool[Gem] = Pool(make_gem, prefill=8)
        self.powerups: Pool[PowerupPickup] = Pool(make_powerup, prefill=6)
        self.entities: List[Entity] = []
        self._next_z = 0.0
        self._safe_lane = 0
        self._prev_safe_pose = False

    # ---------------------------------------------------------------- lifecycle
    def reset(self, start_z: float = 0.0) -> None:
        for pool in (self.obstacles, self.coins, self.gems, self.powerups):
            pool.release_all()
        self.entities.clear()
        self._safe_lane = 0
        self._prev_safe_pose = False
        # Leave a calm runway before the first feature.
        self._next_z = start_z + 6000.0

    def prime(self, player, track, knobs: SpawnKnobs) -> None:
        """Fill the initial stretch of track so the world isn't empty at start."""
        self.update(player, track, knobs)

    # ------------------------------------------------------------------- update
    def update(self, player, track, knobs: SpawnKnobs) -> None:
        horizon = player.world_z + SPAWN_AHEAD
        guard = 0
        while self._next_z < horizon:
            self._spawn_feature(self._next_z, track, knobs)
            self._next_z += max(1200.0, knobs.feature_gap)
            guard += 1
            if guard > 500:  # pragma: no cover - runaway guard
                break
        self._recycle(player.world_z)

    def _recycle(self, player_z: float) -> None:
        behind = player_z - RECYCLE_BEHIND
        survivors: List[Entity] = []
        for e in self.entities:
            if e.z < behind or not e.alive:
                self._release(e)
            else:
                survivors.append(e)
        self.entities = survivors

    def _release(self, e: Entity) -> None:
        if isinstance(e, Obstacle):
            self.obstacles.release(e)
        elif isinstance(e, Coin):
            self.coins.release(e)
        elif isinstance(e, Gem):
            self.gems.release(e)
        elif isinstance(e, PowerupPickup):
            self.powerups.release(e)

    # --------------------------------------------------------- feature builders
    def _spawn_feature(self, z: float, track, knobs: SpawnKnobs) -> None:
        roll = self.rng.random()
        tint = track.biome_at_z(z).obstacle_tint
        if roll < knobs.obstacle_prob:
            self._spawn_obstacle_row(z, knobs, tint)
        elif roll < knobs.obstacle_prob + knobs.coin_prob:
            self._spawn_coin_run(z, knobs)
        elif roll < knobs.obstacle_prob + knobs.coin_prob + knobs.gem_prob:
            self._spawn_gem(z)
        elif roll < (knobs.obstacle_prob + knobs.coin_prob + knobs.gem_prob
                     + knobs.powerup_prob):
            self._spawn_powerup(z)
        # else: an intentional empty breather slot

    def _spawn_obstacle_row(self, z: float, knobs: SpawnKnobs, tint) -> None:
        # --- roller row: a solo moving hazard -------------------------------
        # It sweeps the two lanes adjacent to each other; the remaining *outer*
        # lane is a static, guaranteed-safe lane the roller can never reach.
        if self.rng.chance(knobs.moving_prob):
            self._spawn_roller_row(z, tint)
            return

        # Pick the next open (safe) lane, adjacent to the current one.
        candidates = [l for l in LANES if _adjacent(l, self._safe_lane)]
        new_safe = self.rng.choice(candidates)
        self._safe_lane = new_safe

        blocked = [l for l in LANES if l != new_safe]
        # Sometimes only block one lane for a gentler beat.
        if not self.rng.chance(knobs.double_prob):
            blocked = [self.rng.choice(blocked)]

        for lane in blocked:
            ob = self.obstacles.acquire()
            kind = self._pick_obstacle_kind(knobs)
            ob.configure(kind, lane, z, tint)
            ob.phase = self.rng.range(0.0, 6.28)
            ob.data["safe_lane"] = new_safe
            self.entities.append(ob)

        # Reward routing: sometimes place a jumpable/slidable obstacle in the safe
        # lane with a coin arc over it, so a skilled player is tempted to stay.
        # Never two rows in a row (that could demand back-to-back poses with no
        # time to land between them — an unfair combo), so we gate on the flag.
        if not self._prev_safe_pose and self.rng.chance(0.30):
            kind = self.rng.choice(("barrier", "beam"))
            ob = self.obstacles.acquire()
            ob.configure(kind, new_safe, z, tint)
            ob.data["safe_lane"] = new_safe
            self.entities.append(ob)
            self._coin_arc(new_safe, z, kind)
            self._prev_safe_pose = True
        else:
            self._prev_safe_pose = False
            if self.rng.chance(0.5):
                # Drop guiding coins down the guaranteed-safe lane.
                self._coin_line(new_safe, z, 4)

    def _spawn_roller_row(self, z: float, tint) -> None:
        # The safe lane must be an OUTER lane adjacent to the previous safe lane,
        # so the other two lanes form an adjacent pair for the roller to sweep.
        outer = [l for l in (-1, 1) if _adjacent(l, self._safe_lane)]
        new_safe = self.rng.choice(outer)
        self._safe_lane = new_safe
        self._prev_safe_pose = False
        others = [l for l in LANES if l != new_safe]  # guaranteed adjacent pair
        center = (TCfg.lane_x(others[0]) + TCfg.lane_x(others[1])) * 0.5
        amp = abs(TCfg.lane_x(others[0]) - TCfg.lane_x(others[1])) * 0.5

        ob = self.obstacles.acquire()
        ob.configure("roller", 0, z, tint)
        ob.data["center"] = center
        ob.data["amp"] = amp
        ob.data["safe_lane"] = new_safe
        ob.phase = self.rng.range(0.0, 6.28)
        self.entities.append(ob)
        if self.rng.chance(0.6):
            self._coin_line(new_safe, z, 4)

    def _pick_obstacle_kind(self, knobs: SpawnKnobs) -> str:
        # Rollers are handled by their own solo row; static rows use these.
        return self.rng.choices(
            ("barrier", "beam", "block", "spikes"),
            (3.0, 2.5, 2.0, 1.2), 1)[0]

    def _spawn_coin_run(self, z: float, knobs: SpawnKnobs) -> None:
        lane = self.rng.choice(LANES)
        self._coin_line(lane, z, knobs.coin_run_len)

    def _coin_line(self, lane: int, z: float, count: int) -> None:
        step = TCfg.SEGMENT_LENGTH * 2.0
        for i in range(count):
            c = self.coins.acquire()
            c.configure(lane, z + i * step, 1)
            c.phase = self.rng.range(0.0, 6.28)
            self.entities.append(c)

    def _coin_arc(self, lane: int, z: float, over_kind: str) -> None:
        """A coin arc that traces a jump (barrier) or a low crouch (beam)."""
        step = TCfg.SEGMENT_LENGTH * 1.4
        n = 7
        for i in range(n):
            c = self.coins.acquire()
            c.configure(lane, z - step * 2 + i * step, 1)
            t = i / (n - 1)
            if over_kind == "barrier":
                # Parabolic arc up and over.
                c.y_offset = 360.0 + 900.0 * (1 - (2 * t - 1) ** 2)
            else:
                # Low line to reward sliding.
                c.y_offset = 200.0
            c.phase = self.rng.range(0.0, 6.28)
            self.entities.append(c)

    def _spawn_gem(self, z: float) -> None:
        lane = self.rng.choice(LANES)
        g = self.gems.acquire()
        g.configure(lane, z, 25)
        g.phase = self.rng.range(0.0, 6.28)
        self.entities.append(g)

    def _spawn_powerup(self, z: float) -> None:
        lane = self.rng.choice(LANES)
        key = self.rng.choices(POWERUP_KEYS, (3.0, 2.0, 1.5, 2.5), 1)[0]
        p = self.powerups.acquire()
        p.configure(lane, z, key)
        p.phase = self.rng.range(0.0, 6.28)
        self.entities.append(p)

    # -------------------------------------------------------------------- magnet
    def apply_magnet(self, player, dt: float, strength: float = 6.0) -> None:
        """Pull nearby coins toward the player while the magnet is active."""
        pz = player.world_z
        reach = 5200.0
        for e in self.entities:
            if e.pickup_kind != PickupKind.COIN or not e.alive:
                continue
            if abs(e.z - pz) > reach:
                continue
            e.data["magnetised"] = True
            target_x_off = (player.x - TCfg.lane_x(e.lane))
            k = clamp(dt * strength, 0.0, 1.0)
            e.x_offset += (target_x_off - e.x_offset) * k
            # Draw them in along z too so they don't linger behind.
            if e.z > pz:
                e.z += (pz - e.z) * k * 0.5

    def update_entities(self, dt: float) -> None:
        """Advance per-entity animation/motion (rollers sweep, coins spin)."""
        for e in self.entities:
            if e.alive:
                e.update(dt)
