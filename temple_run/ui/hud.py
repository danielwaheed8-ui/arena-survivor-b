"""
The in-run heads-up display.

The HUD reads the shared *snapshot* dict the game assembles each frame (see the
contract) and paints score, currency, distance, speed, the combo meter, the
active biome, and the stack of active powerup timers. It is deliberately
self-contained — it keeps its own small font cache and draw helpers rather than
depending on the widget toolkit — so it can be rendered even if other UI systems
change underneath it.

Everything here is screen-space and must never raise from the draw path.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import pygame

from ..config import Config, Palette, shade_color

_FONT_CACHE: Dict[Tuple[int, bool], pygame.font.Font] = {}


def _font(size: int, bold: bool = False) -> pygame.font.Font:
    key = (size, bold)
    f = _FONT_CACHE.get(key)
    if f is None:
        f = pygame.font.SysFont("Arial", size, bold=bold)
        _FONT_CACHE[key] = f
    return f


def _text(surface, s, pos, size, color, center=False, bold=False, shadow=True):
    font = _font(size, bold)
    if shadow:
        sh = font.render(s, True, (0, 0, 0))
        r = sh.get_rect()
        if center:
            r.center = (pos[0] + 2, pos[1] + 2)
        else:
            r.topleft = (pos[0] + 2, pos[1] + 2)
        surface.blit(sh, r)
    img = font.render(s, True, color)
    r = img.get_rect()
    if center:
        r.center = pos
    else:
        r.topleft = pos
    surface.blit(img, r)
    return r


class HUD:
    def __init__(self):
        self.biome_flash = 0.0
        self.biome_name = ""
        self._combo_pulse = 0.0

    def on_biome_change(self, name: str) -> None:
        self.biome_name = name
        self.biome_flash = 2.5

    def on_combo(self) -> None:
        self._combo_pulse = 1.0

    def update(self, dt: float) -> None:
        self.biome_flash = max(0.0, self.biome_flash - dt)
        self._combo_pulse = max(0.0, self._combo_pulse - dt * 2.0)

    def draw(self, surface, snap: dict, fps: Optional[float] = None,
             show_fps: bool = False) -> None:
        self._draw_score(surface, snap)
        self._draw_currency(surface, snap)
        self._draw_distance_speed(surface, snap)
        self._draw_combo(surface, snap)
        self._draw_biome(surface)
        self._draw_powerups(surface, snap)
        if show_fps and fps is not None:
            _text(surface, f"{fps:4.0f} fps", (Config.WIDTH - 110, Config.HEIGHT - 28),
                  18, Palette.UI_TEXT_DIM)

    # ------------------------------------------------------------------ pieces
    def _draw_score(self, surface, snap) -> None:
        score = snap.get("score", 0)
        _text(surface, f"{score:,}", (28, 22), 46, Palette.UI_TEXT, bold=True)
        _text(surface, "SCORE", (30, 70), 18, Palette.UI_TEXT_DIM)
        hs = snap.get("high_score", 0)
        if hs:
            _text(surface, f"BEST {hs:,}", (30, 94), 16, Palette.UI_ACCENT)

    def _draw_currency(self, surface, snap) -> None:
        # Coins with a little coin glyph.
        cx, cy = Config.WIDTH - 150, 30
        pygame.draw.circle(surface, Palette.GOLD, (cx, cy + 10), 11)
        pygame.draw.circle(surface, Palette.GOLD_DARK, (cx, cy + 10), 11, 2)
        _text(surface, f"{snap.get('coins', 0)}", (cx + 20, cy), 26, Palette.GOLD, bold=True)
        # Gems below.
        gy = cy + 34
        pts = [(cx, gy + 2), (cx + 9, gy + 10), (cx, gy + 18), (cx - 9, gy + 10)]
        pygame.draw.polygon(surface, Palette.GEM, pts)
        pygame.draw.polygon(surface, Palette.GEM_DARK, pts, 2)
        _text(surface, f"{snap.get('gems', 0)}", (cx + 20, gy - 2), 24, Palette.GEM, bold=True)

    def _draw_distance_speed(self, surface, snap) -> None:
        dm = snap.get("distance_m", 0)
        _text(surface, f"{dm} m", (Config.WIDTH // 2, 26), 30, Palette.UI_TEXT,
              center=True, bold=True)
        spd = snap.get("speed_kmh", 0)
        lvl = snap.get("level", 1)
        _text(surface, f"{spd} km/h   ·   Lv {lvl}", (Config.WIDTH // 2, 56), 18,
              Palette.UI_TEXT_DIM, center=True)

    def _draw_combo(self, surface, snap) -> None:
        combo = snap.get("combo", 1.0)
        if not snap.get("combo_active", False) or combo <= 1.001:
            return
        pulse = 1.0 + self._combo_pulse * 0.3
        size = int(30 * pulse)
        x = Config.WIDTH // 2
        y = 96
        _text(surface, f"x{combo:.1f}", (x, y), size, Palette.UI_ACCENT,
              center=True, bold=True)
        _text(surface, "COMBO", (x, y + 24), 14, Palette.UI_TEXT_DIM, center=True)

    def _draw_biome(self, surface) -> None:
        if self.biome_flash <= 0.0 or not self.biome_name:
            return
        alpha = min(1.0, self.biome_flash / 0.6)
        y = 150
        col = shade_color(Palette.UI_TEXT, alpha)
        _text(surface, self.biome_name, (Config.WIDTH // 2, y), 34,
              col, center=True, bold=True)

    def _draw_powerups(self, surface, snap) -> None:
        powerups: List[dict] = snap.get("powerups", [])
        if not powerups:
            return
        x = Config.WIDTH - 70
        y = 120
        for pu in powerups:
            remaining = pu.get("remaining", 0.0)
            duration = pu.get("duration", 1.0) or 1.0
            frac = max(0.0, min(1.0, remaining / duration))
            color = pu.get("color", Palette.INFO)
            # Timer ring.
            pygame.draw.circle(surface, shade_color(color, 0.35), (x, y), 24)
            self._ring(surface, x, y, 24, frac, color)
            _text(surface, pu.get("symbol", "?"), (x, y - 10), 20,
                  Palette.WHITE, center=True, bold=True)
            _text(surface, f"{remaining:0.0f}s", (x, y + 26), 14,
                  Palette.UI_TEXT_DIM, center=True)
            y += 74

    def _ring(self, surface, cx, cy, r, frac, color) -> None:
        if frac <= 0:
            return
        steps = max(3, int(frac * 40))
        pts = [(cx, cy)]
        for i in range(steps + 1):
            a = -math.pi / 2 + (math.tau * frac) * (i / steps)
            pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
        if len(pts) >= 3:
            try:
                pygame.draw.polygon(surface, color, pts)
            except (ValueError, TypeError):
                pass
