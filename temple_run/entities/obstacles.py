"""
Obstacles.

Each obstacle is an :class:`Entity` with a :class:`HitKind` describing how the
player beats it, plus a ``render`` that draws it from a projected road-surface
anchor. World dimensions are converted to pixels through the shared
:func:`w_px`/:func:`h_px` helpers so obstacles scale *exactly* with the road they
sit on.

Obstacle catalogue
------------------
* ``barrier``   — low; **jump** over it.
* ``beam``      — high overhead bar; **slide** under it.
* ``block``     — full height; you must be in another lane.
* ``spikes``    — full height hazard variant (visual flavour of block).
* ``roller``    — a moving block that sweeps across the lanes.
"""

from __future__ import annotations

import math

import pygame

from ..config import Config, Palette, Track as TCfg, shade_color
from ..mathutils import clamp
from .entity import Entity, HitKind, PickupKind, h_px, w_px

# World-space sizes.
BARRIER_W = 980.0
BARRIER_H = 520.0
BEAM_W = 1180.0
BEAM_H = 360.0
BEAM_GAP = 560.0          # clear space under the beam (slide height)
BLOCK_W = 900.0
BLOCK_H = 1500.0


def _stripes(surface, rect, base, warn=(250, 210, 40)):
    """Draw hazard warning stripes across the top band of ``rect``."""
    band = max(3, int(rect.height * 0.22))
    stripe_w = max(6, int(rect.width * 0.18))
    top = rect.top
    clip = surface.get_clip()
    surface.set_clip(pygame.Rect(rect.left, top, rect.width, band))
    x = rect.left - band
    while x < rect.right + band:
        pts = [(x, top + band), (x + stripe_w, top),
               (x + stripe_w * 2, top), (x + stripe_w, top + band)]
        pygame.draw.polygon(surface, warn, pts)
        x += stripe_w * 2
    surface.set_clip(clip)


class Obstacle(Entity):
    def __init__(self) -> None:
        super().__init__()
        self.pickup_kind = PickupKind.NONE

    # -- factory configuration ----------------------------------------------
    def configure(self, kind: str, lane: int, z: float, tint=(60, 55, 50)) -> "Obstacle":
        self.kind = kind
        self.lane = lane
        self.z = z
        self.collidable = True
        self.alive = True
        self.data["tint"] = tint
        self.x_offset = 0.0
        if kind == "barrier":
            self.hit_kind = HitKind.JUMP
            self.half_width = BARRIER_W * 0.5
            self.radius_z = TCfg.SEGMENT_LENGTH * 0.8
        elif kind == "beam":
            self.hit_kind = HitKind.SLIDE
            self.half_width = BEAM_W * 0.5
            self.radius_z = TCfg.SEGMENT_LENGTH * 0.7
        elif kind == "roller":
            self.hit_kind = HitKind.MOVING
            self.half_width = BLOCK_W * 0.5
            self.radius_z = TCfg.SEGMENT_LENGTH * 0.8
            self.data["sweep"] = TCfg.ROAD_WIDTH * TCfg.LANE_FRACTION
        else:  # block / spikes
            self.hit_kind = HitKind.SOLID
            self.half_width = BLOCK_W * 0.5
            self.radius_z = TCfg.SEGMENT_LENGTH * 0.9
        return self

    def update(self, dt: float) -> None:
        super().update(dt)
        if self.kind == "roller":
            # Sweep between two adjacent lanes about a fixed centre. The spawner
            # supplies ``center``/``amp`` so the roller can never reach the row's
            # guaranteed safe lane (keeping the row fair).
            center = self.data.get("center", 0.0)
            amp = self.data.get("amp", self.data.get("sweep", 0.0))
            self.x_offset = center + math.sin(self.anim * 1.8 + self.phase) * amp

    # -- collision profile ---------------------------------------------------
    def passes_over_under(self, player) -> bool:
        """True if the player's pose lets them clear this obstacle."""
        if self.hit_kind == HitKind.JUMP:
            return player.clears_low_obstacle()
        if self.hit_kind == HitKind.SLIDE:
            return player.is_sliding
        return False  # SOLID / MOVING: pose can't save you

    # -- rendering -----------------------------------------------------------
    def render(self, surface, sx, sy, scale, dim, t):
        tint = self.data.get("tint", (60, 55, 50))
        if self.kind == "barrier":
            self._draw_box(surface, sx, sy, scale, dim, BARRIER_W, BARRIER_H, 0.0,
                           shade_color(tint, 1.0), warn_top=True)
        elif self.kind == "beam":
            self._draw_box(surface, sx, sy, scale, dim, BEAM_W, BEAM_H, BEAM_GAP,
                           shade_color(tint, 0.9), warn_bottom=True, legs=True)
        elif self.kind == "roller":
            self._draw_roller(surface, sx, sy, scale, dim, tint)
        elif self.kind == "spikes":
            self._draw_spikes(surface, sx, sy, scale, dim, tint)
        else:
            self._draw_box(surface, sx, sy, scale, dim, BLOCK_W, BLOCK_H, 0.0,
                           shade_color(tint, 1.1))

    def _draw_box(self, surface, sx, sy, scale, dim, wl, hl, base_gap,
                  color, warn_top=False, warn_bottom=False, legs=False):
        w = w_px(scale, wl)
        h = h_px(scale, hl)
        gap = h_px(scale, base_gap)
        if w < 1 or h < 1:
            return
        bottom = sy - gap
        rect = pygame.Rect(0, 0, int(w), int(h))
        rect.midbottom = (int(sx), int(bottom))
        col = shade_color(color, dim)
        # A little fake shading: darker right face for solidity.
        pygame.draw.rect(surface, col, rect, border_radius=max(1, int(w * 0.04)))
        face = pygame.Rect(rect.right - int(w * 0.18), rect.top, int(w * 0.18), rect.height)
        pygame.draw.rect(surface, shade_color(col, 0.75), face)
        pygame.draw.rect(surface, shade_color(col, 0.5), rect, max(1, int(w * 0.02)),
                         border_radius=max(1, int(w * 0.04)))
        if warn_top:
            _stripes(surface, rect, col)
        if warn_bottom:
            band = pygame.Rect(rect.left, rect.bottom - int(h * 0.24), rect.width, int(h * 0.24))
            _stripes(surface, band, col)
        if legs:
            leg_w = max(2, int(w * 0.08))
            for lx in (rect.left + leg_w, rect.right - leg_w * 2):
                pygame.draw.rect(surface, shade_color(col, 0.7),
                                 (lx, rect.bottom, leg_w, int(gap)))

    def _draw_roller(self, surface, sx, sy, scale, dim, tint):
        w = w_px(scale, BLOCK_W)
        h = h_px(scale, BLOCK_H * 0.7)
        if w < 1:
            return
        col = shade_color(shade_color(tint, 1.2), dim)
        rect = pygame.Rect(0, 0, int(w), int(h))
        rect.midbottom = (int(sx), int(sy))
        pygame.draw.rect(surface, col, rect, border_radius=int(w * 0.5))
        pygame.draw.rect(surface, shade_color(Palette.WARNING, dim), rect,
                         max(1, int(w * 0.05)), border_radius=int(w * 0.5))
        # A spinning highlight to sell the rolling motion.
        cx, cy = rect.center
        ang = self.anim * 6.0
        r = w * 0.28
        pygame.draw.circle(surface, shade_color((255, 255, 255), dim),
                           (int(cx + math.cos(ang) * r), int(cy + math.sin(ang) * r)),
                           max(1, int(w * 0.06)))

    def _draw_spikes(self, surface, sx, sy, scale, dim, tint):
        w = w_px(scale, BLOCK_W)
        h = h_px(scale, BLOCK_H)
        if w < 1:
            return
        base = shade_color(shade_color(tint, 0.9), dim)
        rect = pygame.Rect(0, 0, int(w), int(h * 0.35))
        rect.midbottom = (int(sx), int(sy))
        pygame.draw.rect(surface, base, rect)
        n = 5
        tip = shade_color(Palette.LIGHT_GREY, dim)
        for i in range(n):
            x0 = rect.left + rect.width * i / n
            x1 = rect.left + rect.width * (i + 1) / n
            xm = (x0 + x1) * 0.5
            pygame.draw.polygon(surface, tip,
                                [(x0, rect.top), (x1, rect.top), (xm, rect.top - h * 0.6)])


# Which obstacle kinds each biome favours is left to the spawner; the factory
# simply builds a configured instance (used with the object pool).
OBSTACLE_KINDS = ("barrier", "beam", "block", "spikes", "roller")


def make_obstacle() -> Obstacle:
    return Obstacle()
