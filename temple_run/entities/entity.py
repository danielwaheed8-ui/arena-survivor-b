"""
Entity base class and the shared taxonomy of what lives on the track.

Everything that scrolls toward the player — obstacles, coins, gems, powerup
pickups — is an :class:`Entity`. An entity is defined purely in *world*
coordinates (lane + z + height offset); the renderer projects it to the screen
using the same camera as the road, so what you see is exactly what you collide
with. That equivalence was broken in the original (lane-index collision vs.
ad-hoc sprite projection); keeping a single source of world position fixes it.

Entities are poolable: ``reset`` returns them to a blank state so the spawner can
recycle them instead of allocating.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any, Dict, Optional

from ..config import Config, Track as TCfg


def w_px(scale: float, world_len: float) -> float:
    """Convert a world lateral length to screen pixels at the given scale."""
    return scale * world_len * Config.WIDTH * 0.5


def h_px(scale: float, world_len: float) -> float:
    """Convert a world vertical length to screen pixels at the given scale."""
    return scale * world_len * Config.HEIGHT * 0.5


class HitKind(Enum):
    """How an obstacle can be beaten (or not)."""
    NONE = auto()      # not an obstacle
    JUMP = auto()      # low: jump over it
    SLIDE = auto()     # high: slide under it
    SOLID = auto()     # full height: must be in another lane
    MOVING = auto()    # patrols lanes; solid


class PickupKind(Enum):
    NONE = auto()
    COIN = auto()
    GEM = auto()
    POWERUP = auto()


class Entity:
    __slots__ = (
        "kind", "lane", "z", "y_offset", "x_offset",
        "hit_kind", "pickup_kind", "radius_z", "half_width",
        "alive", "collidable", "collected", "value",
        "data", "phase", "anim",
    )

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.kind = "none"
        self.lane = 0
        self.z = 0.0
        self.y_offset = 0.0          # height above the road surface
        self.x_offset = 0.0          # small lateral nudge within a lane
        self.hit_kind = HitKind.NONE
        self.pickup_kind = PickupKind.NONE
        self.radius_z = TCfg.SEGMENT_LENGTH * 0.9
        self.half_width = TCfg.ROAD_WIDTH * TCfg.LANE_FRACTION * 0.5
        self.alive = True
        self.collidable = True
        self.collected = False
        self.value = 0
        self.data: Dict[str, Any] = {}
        self.phase = 0.0
        self.anim = 0.0

    # ------------------------------------------------------------------ world
    def world_x(self) -> float:
        return TCfg.lane_x(self.lane) + self.x_offset

    def update(self, dt: float) -> None:
        """Per-frame animation / motion. Overridden by moving entities."""
        self.anim += dt

    # ---------------------------------------------------------------- drawing
    def render(self, surface, sx: float, sy: float, scale: float,
               dim: float, t: float) -> None:  # pragma: no cover - overridden
        """Draw the entity given its projected screen anchor.

        ``sx, sy`` is the projected road-surface point the entity stands on,
        ``scale`` the perspective scale (multiply world sizes by it),
        ``dim`` a 0..1 fog/brightness factor, ``t`` the global time in seconds.
        """
        raise NotImplementedError
