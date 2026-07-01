"""
Collision resolution.

One system, one source of truth. Every collidable :class:`Entity` lives in world
space; the player lives in world space; collisions are decided by comparing world
positions — never by the ad-hoc, drift-prone "lane index == lane index plus a
magic Y threshold" the original used.

For each entity in range we ask:

* **Pickup?** If the player overlaps it laterally, collect it (coins/gems are
  grabbed whether you're grounded or airborne — they float at mid-height).
* **Obstacle?** If the player overlaps it laterally and their *pose* doesn't beat
  it (jumping over a low barrier, sliding under a high beam), it's a hit. Invincible
  players (shield/boost) smash through instead of dying.
* **Near miss?** An obstacle you slip past in an adjacent lane, close but not
  touching, pays a small style bonus — once per obstacle.

Outcomes are published as events; the collision system also drives ``player.kill``
on a fatal hit so the death is unambiguous and centralised here.
"""

from __future__ import annotations

from typing import Callable, List

from ..config import Gameplay, Track as TCfg
from ..core.events import Event, EventBus, EventType
from .entity import Entity, HitKind, PickupKind

# Player collision volume (world units).
PLAYER_HALF_WIDTH = 300.0
PLAYER_RADIUS_Z = 130.0


class CollisionSystem:
    def __init__(self, bus: EventBus):
        self.bus = bus
        # Per-run scratch so we only award one near-miss per obstacle.
        self._near_missed: set = set()

    def reset(self) -> None:
        self._near_missed.clear()

    def resolve(
        self,
        player,
        entities: List[Entity],
        invincible: bool = False,
        coin_multiplier: int = 1,
    ) -> None:
        pz = player.world_z
        px = player.x

        for e in entities:
            if not e.alive or not e.collidable:
                continue

            dz = e.z - pz
            reach_z = e.radius_z + PLAYER_RADIUS_Z
            if dz > reach_z:
                continue  # still ahead, not yet in range
            if dz < -reach_z:
                continue  # already behind

            dx = abs(px - e.world_x())
            overlaps_x = dx < (e.half_width + PLAYER_HALF_WIDTH)

            if e.pickup_kind != PickupKind.NONE:
                if overlaps_x:
                    self._collect(e, player, coin_multiplier)
                continue

            # --- obstacle ---
            if overlaps_x:
                if e.hit_kind in (HitKind.JUMP, HitKind.SLIDE) and \
                        _pose_beats(e, player):
                    continue  # cleared it cleanly
                if invincible:
                    e.alive = False
                    e.collidable = False
                    self.bus.publish(Event(EventType.OBSTACLE_HIT,
                                           {"entity": e, "fatal": False, "smashed": True}))
                    self.bus.publish(Event(EventType.SCREEN_SHAKE, {"magnitude": 220.0}))
                else:
                    self._fatal(e, player)
                    return
            else:
                # Near miss: close pass in an adjacent lane.
                if id(e) not in self._near_missed and \
                        dx < Gameplay.NEAR_MISS_RADIUS and abs(dz) < reach_z:
                    self._near_missed.add(id(e))
                    self.bus.publish(Event(EventType.NEAR_MISS,
                                           {"entity": e, "distance": dx}))

    # ------------------------------------------------------------------ helpers
    def _collect(self, e: Entity, player, coin_multiplier: int) -> None:
        e.alive = False
        e.collidable = False
        e.collected = True
        if e.pickup_kind == PickupKind.COIN:
            self.bus.publish(Event(EventType.COIN_COLLECTED,
                                   {"entity": e, "value": e.value * coin_multiplier}))
        elif e.pickup_kind == PickupKind.GEM:
            self.bus.publish(Event(EventType.GEM_COLLECTED,
                                   {"entity": e, "value": e.value * coin_multiplier}))
        elif e.pickup_kind == PickupKind.POWERUP:
            self.bus.publish(Event(EventType.POWERUP_COLLECTED,
                                   {"entity": e, "power": e.data.get("power")}))

    def _fatal(self, e: Entity, player) -> None:
        player.kill()
        self.bus.publish(Event(EventType.OBSTACLE_HIT,
                               {"entity": e, "fatal": True, "smashed": False}))
        self.bus.publish(Event(EventType.SCREEN_SHAKE, {"magnitude": 420.0}))


def _pose_beats(e: Entity, player) -> bool:
    if e.hit_kind == HitKind.JUMP:
        return player.clears_low_obstacle()
    if e.hit_kind == HitKind.SLIDE:
        return player.is_sliding
    return False
