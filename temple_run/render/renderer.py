"""
The pseudo-3D renderer.

This is the module the original monolith got wrong (mismatched projection
signatures, undefined variables, no working curve accumulation). Here it is done
faithfully in the OutRun / Jake-Gordon style:

* The world is *straight*; curves are faked by accumulating a horizontal offset
  (``x``/``dx``) as we march segments from near to far, shifting the camera x per
  segment. The road bends, hills roll, and — crucially — **sprites and the player
  are anchored to the very same accumulated offset**, so an obstacle "in the left
  lane" hugs the curving road instead of floating off it.
* Hill occlusion falls out of the classic ``maxy`` trick: a far segment whose top
  is already below a nearer segment's crest is skipped.
* Distance fog blends road, rumble, grass and sprites toward the biome fog colour,
  and each biome's ambient tint colours the whole scene.

The renderer draws the *world* (sky → road → scenery → entities → player). HUD,
particles and screen overlays are composited by the game on top.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import pygame

from ..config import Cam, Config, Palette, Track as TCfg, lerp_color, shade_color
from ..entities.entity import Entity, h_px, w_px
from ..mathutils import clamp, project

RUMBLE_RATIO = 0.13         # rumble strip width as a fraction of road half-width
LANE_MARKER_RATIO = 0.028   # lane marker width fraction
LANE_DIVIDER_POS = 1.0 / 3.0  # divider world-x as a fraction of road half-width


class _Anchor:
    """Cached per-frame projection of a segment's near edge (with curve offset)."""
    __slots__ = ("sx", "sy", "w", "scale", "dim", "clip", "seg")

    def __init__(self, sx, sy, w, scale, dim, clip, seg):
        self.sx = sx
        self.sy = sy
        self.w = w
        self.scale = scale
        self.dim = dim
        self.clip = clip
        self.seg = seg


class Renderer:
    def __init__(self):
        self.W = Config.WIDTH
        self.H = Config.HEIGHT
        self._sky: Optional[pygame.Surface] = None
        self._sky_key: Tuple = ()
        # Per-frame anchor cache keyed by absolute segment index.
        self._anchors: Dict[int, _Anchor] = {}

    # ---------------------------------------------------------------- fog model
    def _fog(self, ratio: float, density: float) -> float:
        """Exponential fog: 1.0 = fully clear (near), →0 = lost in fog (far)."""
        return 1.0 / math.pow(math.e, ratio * ratio * density)

    # -------------------------------------------------------------------- sky
    def _ensure_sky(self, biome) -> None:
        key = (biome.sky_top, biome.sky_bottom)
        if key == self._sky_key and self._sky is not None:
            return
        self._sky_key = key
        surf = pygame.Surface((self.W, self.H))
        if pygame.display.get_surface() is not None:
            surf = surf.convert()
        top, bottom = biome.sky_top, biome.sky_bottom
        horizon = int(self.H * Config.HORIZON_RATIO)
        for y in range(self.H):
            t = y / max(1, horizon) if y < horizon else 1.0
            surf.fill(lerp_color(top, bottom, clamp(t, 0, 1)), (0, y, self.W, 1))
        self._sky = surf

    def _draw_sky(self, surface, biome, camera) -> None:
        self._ensure_sky(biome)
        surface.blit(self._sky, (0, 0))
        # A soft sun/moon disc and a haze band at the horizon for depth.
        horizon = int(self.H * Config.HORIZON_RATIO)
        sun_x = int(self.W * 0.72 - camera.x * 0.02)
        pygame.draw.circle(surface, shade_color(biome.sky_bottom, 1.25),
                           (sun_x, int(horizon * 0.55)), int(self.H * 0.06))
        haze = pygame.Surface((self.W, int(self.H * 0.10)), pygame.SRCALPHA)
        haze.fill((*biome.fog, 90))
        surface.blit(haze, (0, horizon - int(self.H * 0.05)))

    # ------------------------------------------------------------------- world
    def render_world(self, surface, track, player, camera, entities, t) -> None:
        biome = track.biome_at_z(camera.z)
        self._draw_sky(surface, biome, camera)
        self._render_road(surface, track, camera)
        self._draw_decorations(surface, t)
        self._draw_entities(surface, entities, camera, t)
        self._draw_player(surface, player, camera, t)

    # -------------------------------------------------------------------- road
    def _render_road(self, surface, track, camera) -> None:
        self._anchors.clear()
        cam_x = camera.render_x
        cam_y = camera.render_y
        cam_z = camera.z
        depth = camera.depth

        base_index = int(cam_z // TCfg.SEGMENT_LENGTH)
        base_seg = track.seg_at(base_index)
        if base_seg is None:
            return
        base_percent = (cam_z - base_seg.z_near) / TCfg.SEGMENT_LENGTH

        x = 0.0
        dx = -(base_seg.curve * base_percent)
        maxy = float(self.H)

        prev = None  # previous projected (screen x, y, w)
        for n in range(Cam.DRAW_DISTANCE):
            seg = track.seg_at(base_index + n)
            if seg is None:
                break
            camx1 = cam_x - x
            camx2 = cam_x - x - dx
            p1 = project(0.0, seg.y_near, seg.z_near, camx1, cam_y, cam_z,
                         depth, self.W, self.H, TCfg.ROAD_WIDTH)
            p2 = project(0.0, seg.y_far, seg.z_far, camx2, cam_y, cam_z,
                         depth, self.W, self.H, TCfg.ROAD_WIDTH)

            x += dx
            dx += seg.curve

            ratio = n / Cam.DRAW_DISTANCE
            dim = self._fog(ratio, Cam.FOG_DENSITY * seg.biome.fog_scale)

            # Cache the anchor for sprites/decorations before any culling.
            seg.clip = maxy
            self._anchors[seg.index] = _Anchor(p1.x, p1.y, p1.w, p1.scale, dim, maxy, seg)

            # Cull: behind camera, backfacing, or hidden by a nearer hill.
            if p1.y <= p2.y or p2.y >= maxy:
                continue

            self._draw_band(surface, seg, p1, p2, dim)
            maxy = p2.y

    def _draw_band(self, surface, seg, p1, p2, dim) -> None:
        biome = seg.biome
        amb = biome.ambient

        def col(base):
            c = (base[0] * amb[0], base[1] * amb[1], base[2] * amb[2])
            c = (min(255, c[0]), min(255, c[1]), min(255, c[2]))
            return lerp_color(biome.fog, (int(c[0]), int(c[1]), int(c[2])), dim)

        if seg.light:
            road = col(biome.road_light)
            grass = col(biome.grass_light)
            rumble = col(biome.rumble_light)
            marker = col(biome.lane_marker)
        else:
            road = col(biome.road_dark)
            grass = col(biome.grass_dark)
            rumble = col(biome.rumble_dark)
            marker = None

        x1, y1, w1 = p1.x, p1.y, p1.w
        x2, y2, w2 = p2.x, p2.y, p2.w

        # Grass fills the full width for this vertical band.
        if y1 > y2:
            pygame.draw.rect(surface, grass, (0, int(y2), self.W, int(y1 - y2) + 1))

        r1 = w1 * RUMBLE_RATIO
        r2 = w2 * RUMBLE_RATIO
        # Rumble strips.
        self._quad(surface, x1 - w1 - r1, y1, x1 - w1, y1, x2 - w2, y2, x2 - w2 - r2, y2, rumble)
        self._quad(surface, x1 + w1 + r1, y1, x1 + w1, y1, x2 + w2, y2, x2 + w2 + r2, y2, rumble)
        # Road surface.
        self._quad(surface, x1 - w1, y1, x1 + w1, y1, x2 + w2, y2, x2 - w2, y2, road)
        # Lane dividers (dashed: only on light segments).
        if marker is not None:
            for side in (-1, 1):
                off1 = w1 * LANE_DIVIDER_POS * side
                off2 = w2 * LANE_DIVIDER_POS * side
                m1 = w1 * LANE_MARKER_RATIO
                m2 = w2 * LANE_MARKER_RATIO
                self._quad(surface,
                           x1 + off1 - m1, y1, x1 + off1 + m1, y1,
                           x2 + off2 + m2, y2, x2 + off2 - m2, y2, marker)

    def _quad(self, surface, x1, y1, x2, y2, x3, y3, x4, y4, color) -> None:
        try:
            pygame.draw.polygon(surface, color, [
                (x1, y1), (x2, y2), (x3, y3), (x4, y4)])
        except (ValueError, TypeError):  # pragma: no cover - degenerate polygon
            pass

    # ------------------------------------------------------------- decorations
    def _draw_decorations(self, surface, t) -> None:
        # Far-to-near so nearer scenery overdraws distant scenery.
        for idx in sorted(self._anchors.keys(), reverse=True):
            a = self._anchors[idx]
            if a.dim < 0.05 or not a.seg.decorations:
                continue
            for deco in a.seg.decorations:
                sx = a.sx + a.w * deco.side * deco.offset
                if sx < -200 or sx > self.W + 200:
                    continue
                if a.sy > a.clip + 4:
                    continue
                self._draw_decoration(surface, deco, sx, a.sy, a.scale, a.dim, t)

    def _draw_decoration(self, surface, deco, sx, sy, scale, dim, t) -> None:
        base = shade_color(deco.tint, dim)
        kind = deco.kind
        sway = math.sin(t * 1.4 + deco.sway_phase) * 0.04
        if kind == "tree":
            trunk_h = h_px(scale, 1400 * deco.scale)
            crown_r = w_px(scale, 900 * deco.scale)
            if trunk_h < 2:
                return
            tx = int(sx + trunk_h * sway)
            pygame.draw.rect(surface, shade_color((90, 60, 40), dim),
                             (int(sx - crown_r * 0.12), int(sy - trunk_h),
                              max(2, int(crown_r * 0.24)), int(trunk_h)))
            pygame.draw.circle(surface, shade_color((40, 120, 50), dim),
                               (tx, int(sy - trunk_h)), max(2, int(crown_r * 0.6)))
        elif kind == "pillar":
            ph = h_px(scale, 2600 * deco.scale)
            pw = w_px(scale, 520 * deco.scale)
            if ph < 2:
                return
            pygame.draw.rect(surface, base,
                             (int(sx - pw * 0.5), int(sy - ph), max(2, int(pw)), int(ph)))
            pygame.draw.rect(surface, shade_color(base, 0.7),
                             (int(sx - pw * 0.6), int(sy - ph), max(2, int(pw * 1.2)),
                              max(2, int(ph * 0.08))))
        elif kind == "rock":
            rr = w_px(scale, 520 * deco.scale)
            if rr < 2:
                return
            pygame.draw.circle(surface, base, (int(sx), int(sy - rr * 0.4)), max(2, int(rr * 0.6)))
        elif kind == "cactus":
            ch = h_px(scale, 1200 * deco.scale)
            cw = w_px(scale, 260 * deco.scale)
            if ch < 2:
                return
            green = shade_color((60, 150, 70), dim)
            pygame.draw.rect(surface, green, (int(sx - cw * 0.5), int(sy - ch), max(2, int(cw)), int(ch)))
            pygame.draw.rect(surface, green, (int(sx - cw * 1.4), int(sy - ch * 0.7),
                                              max(2, int(cw * 0.9)), max(2, int(ch * 0.12))))
        elif kind in ("torch", "lantern"):
            ph = h_px(scale, 1100 * deco.scale)
            if ph < 2:
                return
            pygame.draw.rect(surface, base, (int(sx - 2), int(sy - ph), max(2, int(w_px(scale, 120))), int(ph)))
            flame = (255, 170, 60) if kind == "torch" else (255, 230, 150)
            fr = max(2, int(w_px(scale, 260 * deco.scale)))
            flick = 1.0 + 0.2 * math.sin(t * 12 + deco.sway_phase)
            pygame.draw.circle(surface, shade_color(flame, dim),
                               (int(sx), int(sy - ph)), int(fr * 0.5 * flick))
        elif kind == "crystal":
            ch = h_px(scale, 1400 * deco.scale)
            cw = w_px(scale, 500 * deco.scale)
            if ch < 2:
                return
            cyan = shade_color((110, 200, 240), dim)
            cx, cyb = int(sx), int(sy)
            pygame.draw.polygon(surface, cyan, [
                (cx, cyb - int(ch)), (cx + int(cw * 0.5), cyb - int(ch * 0.4)),
                (cx, cyb), (cx - int(cw * 0.5), cyb - int(ch * 0.4))])
        elif kind == "ruin":
            rw = w_px(scale, 900 * deco.scale)
            rh = h_px(scale, 900 * deco.scale)
            if rh < 2:
                return
            pygame.draw.rect(surface, base, (int(sx - rw * 0.5), int(sy - rh), max(2, int(rw)), int(rh)))
            pygame.draw.rect(surface, shade_color(base, 0.6),
                             (int(sx - rw * 0.5), int(sy - rh), max(2, int(rw)), max(2, int(rh * 0.25))))

    # ---------------------------------------------------------------- entities
    def _draw_entities(self, surface, entities: List[Entity], camera, t) -> None:
        cam_z = camera.z
        base_index = int(cam_z // TCfg.SEGMENT_LENGTH)
        drawable = []
        for e in entities:
            if not e.alive:
                continue
            idx = int(e.z // TCfg.SEGMENT_LENGTH)
            a = self._anchors.get(idx)
            if a is None or a.dim < 0.04:
                continue
            sx = a.sx + a.w * (e.world_x() / TCfg.ROAD_WIDTH)
            if sx < -400 or sx > self.W + 400:
                continue
            if a.sy > a.clip + 6:
                continue  # hidden behind a hill
            drawable.append((e.z, e, sx, a.sy, a.scale, a.dim))
        # Far-to-near.
        drawable.sort(key=lambda d: d[0], reverse=True)
        for _, e, sx, sy, scale, dim in drawable:
            e.render(surface, sx, sy, scale, dim, t)

    # ------------------------------------------------------------------ player
    def _draw_player(self, surface, player, camera, t) -> None:
        from .camera import PLAYER_Z_AHEAD
        from ..entities.player import PlayerState

        cam_x = camera.render_x
        cam_y = camera.render_y
        cam_z = camera.z
        ground = 0.0  # player.y is relative; project the ground point then lift
        wz = player.z + PLAYER_Z_AHEAD
        p = project(player.x, ground, wz, cam_x, cam_y, cam_z,
                    camera.depth, self.W, self.H, TCfg.ROAD_WIDTH)
        scale = p.scale
        base_x = p.x
        base_y = p.y  # road surface under the player

        # Shadow shrinks and fades as the player rises.
        lift = h_px(scale, player.y)
        shadow_w = w_px(scale, 560) * (1.0 - clamp(player.y / 1400.0, 0, 0.6))
        shadow_h = shadow_w * 0.32
        if shadow_w > 2:
            shadow = pygame.Surface((int(shadow_w), int(shadow_h) + 1), pygame.SRCALPHA)
            pygame.draw.ellipse(shadow, (0, 0, 0, 110), shadow.get_rect())
            surface.blit(shadow, (int(base_x - shadow_w / 2), int(base_y - shadow_h / 2)))

        # Body metrics. Kept modest so the avatar frames in the lower-centre and
        # never occludes the obstacles it is about to reach.
        sliding = player.state == PlayerState.SLIDING
        dead = player.state == PlayerState.DEAD
        body_h = h_px(scale, 560 if not sliding else 300)
        body_w = w_px(scale, 340 if not sliding else 520)
        if body_h < 4:
            return
        feet_y = base_y - lift
        cx = base_x
        tilt = player.tilt + (0.9 if dead else 0.0)

        # Legs (only while grounded & running-ish).
        col = Palette.PLAYER
        dark = Palette.PLAYER_DARK
        if player.on_ground and not sliding:
            swing = math.sin(player.run_cycle * math.pi) * body_h * 0.16
            lw = max(2, int(body_w * 0.24))
            leg_top = feet_y - body_h * 0.30
            pygame.draw.rect(surface, dark, (int(cx - body_w * 0.28), int(leg_top),
                                             lw, int(body_h * 0.3 + swing)))
            pygame.draw.rect(surface, dark, (int(cx + body_w * 0.28 - lw), int(leg_top),
                                             lw, int(body_h * 0.3 - swing)))

        # Torso — a skewed quad for the lean.
        top_y = feet_y - body_h
        skew = tilt * body_h * 0.5
        torso = [
            (cx - body_w * 0.5 + skew, top_y),
            (cx + body_w * 0.5 + skew, top_y),
            (cx + body_w * 0.5, feet_y - body_h * 0.15),
            (cx - body_w * 0.5, feet_y - body_h * 0.15),
        ]
        pygame.draw.polygon(surface, col, [(int(a), int(b)) for a, b in torso])
        pygame.draw.polygon(surface, dark, [(int(a), int(b)) for a, b in torso],
                            max(1, int(body_w * 0.05)))

        # Arms swing opposite the legs.
        if player.on_ground and not sliding:
            aswing = math.sin(player.run_cycle * math.pi) * body_h * 0.12
            arm_w = max(2, int(body_w * 0.16))
            ay = top_y + body_h * 0.18
            pygame.draw.rect(surface, dark, (int(cx - body_w * 0.55 + skew), int(ay - aswing),
                                             arm_w, int(body_h * 0.34)))
            pygame.draw.rect(surface, dark, (int(cx + body_w * 0.55 - arm_w + skew), int(ay + aswing),
                                             arm_w, int(body_h * 0.34)))

        # Head.
        head_r = w_px(scale, 150)
        if head_r >= 2:
            hx = cx + skew * 1.3
            hy = top_y - head_r * 0.8
            pygame.draw.circle(surface, Palette.SKIN, (int(hx), int(hy)), int(head_r))
            pygame.draw.circle(surface, shade_color(Palette.SKIN, 0.7),
                               (int(hx), int(hy)), int(head_r), max(1, int(head_r * 0.12)))
            # A little headband to read direction.
            pygame.draw.rect(surface, col, (int(hx - head_r), int(hy - head_r * 0.35),
                                            int(head_r * 2), max(2, int(head_r * 0.4))))
