"""
Canonical powerup definitions — shared between the pickup entity (which needs a
colour and a symbol to draw) and the powerup manager (which needs durations and
effect flags). Keeping the catalogue in one dependency-free place stops the two
systems from disagreeing about, say, how long the magnet lasts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

Color = Tuple[int, int, int]


@dataclass(frozen=True)
class PowerupType:
    key: str
    name: str
    color: Color
    symbol: str          # short glyph drawn on the pickup / HUD icon
    duration: float      # seconds the effect lasts
    invincible: bool = False
    magnet: bool = False
    speed_mult: float = 1.0
    score_mult: int = 1
    coin_mult: int = 1
    description: str = ""


POWERUPS: Dict[str, PowerupType] = {
    "magnet": PowerupType(
        key="magnet", name="Coin Magnet", color=(90, 170, 255), symbol="U",
        duration=8.0, magnet=True,
        description="Draws nearby coins straight to you.",
    ),
    "shield": PowerupType(
        key="shield", name="Guardian Shield", color=(120, 230, 220), symbol="O",
        duration=7.0, invincible=True,
        description="Shrug off any hit while it lasts.",
    ),
    "boost": PowerupType(
        key="boost", name="Speed Boost", color=(255, 150, 60), symbol=">>",
        duration=5.0, invincible=True, speed_mult=1.6,
        description="Sprint forward, smashing through everything.",
    ),
    "x2": PowerupType(
        key="x2", name="Score x2", color=(255, 205, 60), symbol="x2",
        duration=12.0, score_mult=2, coin_mult=2,
        description="Double all points and coins.",
    ),
}

POWERUP_KEYS = tuple(POWERUPS.keys())


def get_powerup(key: str) -> PowerupType:
    return POWERUPS[key]
