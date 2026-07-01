"""
Collectibles: coins, gems and powerup pickups.

Collectibles float above the road, bob gently and spin so they read as pickups
rather than hazards. Coins are the bread-and-butter currency; gems are rarer and
worth far more; powerup pickups grant a timed ability. All three are
:class:`Entity` subclasses and honour the same projected-anchor ``render``
contract as obstacles.

Coins support being *magnetised*: when the magnet powerup is active the game
nudges each coin's ``x_offset``/``y_offset``/``z`` toward the player, and the
coin animates a little brighter to show it's homing in.
"""

from __future__ import annotations

import math

import pygame

from ..config import Config, Palette, Track as TCfg, shade_color
from ..mathutils import clamp
from .entity import Entity, HitKind, PickupKind, h_px, w_px
from .powerup_types import PowerupType, get_powerup

COIN_HOVER = 360.0     # world height coins float at
COIN_SIZE = 260.0
GEM_SIZE = 300.0
POWERUP_SIZE = 420.0


class Coin(Entity):
    def configure(self, lane: int, z: float, value: int = 1) -> "Coin":
        self.kind = "coin"
        self.lane = lane
        self.z = z
        self.y_offset = COIN_HOVER
        self.pickup_kind = PickupKind.COIN
        self.hit_kind = HitKind.NONE
        self.collidable = True
        self.alive = True
        self.collected = False
        self.value = value
        self.half_width = COIN_SIZE
        self.radius_z = TCfg.SEGMENT_LENGTH * 0.75
        self.data["magnetised"] = False
        return self

    def render(self, surface, sx, sy, scale, dim, t):
        r = w_px(scale, COIN_SIZE) * 0.5
        if r < 1:
            return
        cy = sy - h_px(scale, self.y_offset) - math.sin(t * 3.0 + self.phase) * r * 0.25
        # Spin: squash horizontally on a sine to fake a rotating disc.
        squash = abs(math.sin(t * 4.0 + self.phase))
        rw = max(1, int(r * (0.25 + 0.75 * squash)))
        gold = shade_color(Palette.GOLD, dim)
        edge = shade_color(Palette.GOLD_DARK, dim)
        rect = pygame.Rect(0, 0, rw * 2, int(r * 2))
        rect.center = (int(sx), int(cy))
        pygame.draw.ellipse(surface, gold, rect)
        pygame.draw.ellipse(surface, edge, rect, max(1, int(r * 0.15)))
        if self.data.get("magnetised"):
            pygame.draw.ellipse(surface, shade_color((255, 255, 200), dim), rect,
                                max(1, int(r * 0.08)))


class Gem(Entity):
    def configure(self, lane: int, z: float, value: int = 25) -> "Gem":
        self.kind = "gem"
        self.lane = lane
        self.z = z
        self.y_offset = COIN_HOVER
        self.pickup_kind = PickupKind.GEM
        self.hit_kind = HitKind.NONE
        self.collidable = True
        self.alive = True
        self.collected = False
        self.value = value
        self.half_width = GEM_SIZE
        self.radius_z = TCfg.SEGMENT_LENGTH * 0.75
        return self

    def render(self, surface, sx, sy, scale, dim, t):
        s = w_px(scale, GEM_SIZE) * 0.5
        if s < 1:
            return
        cy = sy - h_px(scale, self.y_offset) - math.sin(t * 2.5 + self.phase) * s * 0.3
        spin = math.sin(t * 3.0 + self.phase)
        wx = max(1.0, s * (0.4 + 0.6 * abs(spin)))
        col = shade_color(Palette.GEM, dim)
        dark = shade_color(Palette.GEM_DARK, dim)
        cx = int(sx)
        icy = int(cy)
        pts = [(cx, icy - int(s)), (cx + int(wx), icy),
               (cx, icy + int(s)), (cx - int(wx), icy)]
        pygame.draw.polygon(surface, col, pts)
        pygame.draw.polygon(surface, shade_color((255, 255, 255), dim),
                            [(cx, icy - int(s)), (cx + int(wx), icy), (cx, icy)])
        pygame.draw.polygon(surface, dark, pts, max(1, int(s * 0.12)))


class PowerupPickup(Entity):
    def configure(self, lane: int, z: float, power_key: str) -> "PowerupPickup":
        spec = get_powerup(power_key)
        self.kind = "powerup"
        self.lane = lane
        self.z = z
        self.y_offset = COIN_HOVER + 40.0
        self.pickup_kind = PickupKind.POWERUP
        self.hit_kind = HitKind.NONE
        self.collidable = True
        self.alive = True
        self.collected = False
        self.half_width = POWERUP_SIZE
        self.radius_z = TCfg.SEGMENT_LENGTH * 0.9
        self.data["power"] = power_key
        self.data["color"] = spec.color
        self.data["symbol"] = spec.symbol
        return self

    def render(self, surface, sx, sy, scale, dim, t):
        s = w_px(scale, POWERUP_SIZE) * 0.5
        if s < 1:
            return
        cy = sy - h_px(scale, self.y_offset) - math.sin(t * 2.0 + self.phase) * s * 0.25
        col = shade_color(self.data.get("color", Palette.INFO), dim)
        cx, icy = int(sx), int(cy)
        # Pulsing halo, then the solid orb and a bright rim.
        halo = int(s * (1.25 + 0.15 * math.sin(t * 5.0)))
        pygame.draw.circle(surface, shade_color(col, 0.5), (cx, icy), halo, max(1, int(s * 0.1)))
        pygame.draw.circle(surface, col, (cx, icy), int(s))
        pygame.draw.circle(surface, shade_color((255, 255, 255), dim), (cx, icy),
                           int(s), max(1, int(s * 0.12)))


def make_coin() -> Coin:
    return Coin()


def make_gem() -> Gem:
    return Gem()


def make_powerup() -> PowerupPickup:
    return PowerupPickup()
