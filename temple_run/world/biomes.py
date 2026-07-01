"""
Biomes — the visual themes the endless track cycles through.

A biome is *pure data*: a bundle of colours plus weights describing what scenery
to sprinkle along the roadside. The track generator stamps a biome onto each
chunk, blends colours across the seam between two biomes, and the renderer reads
those colours when shading road, rumble, grass and sky. Nothing here imports
pygame, so biomes stay trivially testable and serialisable.

Adding a new theme is a matter of appending one :class:`Biome` to ``BIOMES``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from ..config import Color
from ..mathutils import lerp

# Kinds of roadside scenery a biome can request. The renderer knows how to draw
# each of these; biomes only choose *how often* each appears.
DECOR_KINDS = ("tree", "pillar", "rock", "torch", "crystal", "cactus", "lantern", "ruin")


@dataclass
class Biome:
    key: str
    name: str
    # Sky gradient (top -> bottom) and the fog colour distant geometry fades to.
    sky_top: Color
    sky_bottom: Color
    fog: Color
    # Road surface alternating bands.
    road_light: Color
    road_dark: Color
    # Rumble stripes at the road edge.
    rumble_light: Color
    rumble_dark: Color
    # Ground either side of the road.
    grass_light: Color
    grass_dark: Color
    # Dashed centre-lane markers.
    lane_marker: Color
    # A subtle full-screen tint multiplied over the frame (1,1,1 = none).
    ambient: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    # Weighted scenery table: kind -> relative frequency.
    decor_weights: Dict[str, float] = field(default_factory=dict)
    # How thick the fog is in this biome (overrides the global default softly).
    fog_scale: float = 1.0
    # Palette for obstacles themed to this biome (used by the obstacle module).
    obstacle_tint: Color = (40, 40, 46)

    def decor_table(self) -> List[Tuple[str, float]]:
        return [(k, w) for k, w in self.decor_weights.items() if w > 0]


def _blend(a: Color, b: Color, t: float) -> Color:
    return (
        int(lerp(a[0], b[0], t)),
        int(lerp(a[1], b[1], t)),
        int(lerp(a[2], b[2], t)),
    )


def blend_biomes(a: Biome, b: Biome, t: float) -> Biome:
    """Produce an interpolated biome used across the transition seam."""
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    amb = (
        lerp(a.ambient[0], b.ambient[0], t),
        lerp(a.ambient[1], b.ambient[1], t),
        lerp(a.ambient[2], b.ambient[2], t),
    )
    return Biome(
        key=f"{a.key}->{b.key}",
        name=f"{a.name}/{b.name}",
        sky_top=_blend(a.sky_top, b.sky_top, t),
        sky_bottom=_blend(a.sky_bottom, b.sky_bottom, t),
        fog=_blend(a.fog, b.fog, t),
        road_light=_blend(a.road_light, b.road_light, t),
        road_dark=_blend(a.road_dark, b.road_dark, t),
        rumble_light=_blend(a.rumble_light, b.rumble_light, t),
        rumble_dark=_blend(a.rumble_dark, b.rumble_dark, t),
        grass_light=_blend(a.grass_light, b.grass_light, t),
        grass_dark=_blend(a.grass_dark, b.grass_dark, t),
        lane_marker=_blend(a.lane_marker, b.lane_marker, t),
        ambient=amb,
        decor_weights=a.decor_weights if t < 0.5 else b.decor_weights,
        fog_scale=lerp(a.fog_scale, b.fog_scale, t),
        obstacle_tint=_blend(a.obstacle_tint, b.obstacle_tint, t),
    )


# ---------------------------------------------------------------------------
# The biome library. Order defines the default cycle.
# ---------------------------------------------------------------------------
BIOMES: List[Biome] = [
    Biome(
        key="temple",
        name="Ancient Temple",
        sky_top=(46, 58, 92), sky_bottom=(196, 176, 150), fog=(150, 140, 130),
        road_light=(78, 72, 60), road_dark=(66, 60, 50),
        rumble_light=(210, 200, 170), rumble_dark=(120, 60, 40),
        grass_light=(46, 104, 50), grass_dark=(38, 92, 44),
        lane_marker=(220, 214, 190),
        ambient=(1.0, 0.98, 0.92),
        decor_weights={"tree": 3, "pillar": 4, "rock": 2, "torch": 2, "ruin": 2},
        obstacle_tint=(70, 58, 44),
    ),
    Biome(
        key="jungle",
        name="Jungle Ruins",
        sky_top=(40, 70, 70), sky_bottom=(150, 200, 170), fog=(120, 160, 130),
        road_light=(70, 66, 58), road_dark=(58, 56, 50),
        rumble_light=(200, 210, 180), rumble_dark=(60, 90, 50),
        grass_light=(30, 120, 44), grass_dark=(22, 100, 36),
        lane_marker=(230, 235, 210),
        ambient=(0.94, 1.0, 0.94),
        decor_weights={"tree": 6, "pillar": 2, "rock": 2, "ruin": 3},
        fog_scale=1.2,
        obstacle_tint=(48, 66, 40),
    ),
    Biome(
        key="desert",
        name="Sun Temple Dunes",
        sky_top=(120, 150, 210), sky_bottom=(240, 210, 150), fog=(226, 200, 150),
        road_light=(150, 130, 96), road_dark=(138, 118, 86),
        rumble_light=(240, 230, 200), rumble_dark=(180, 120, 70),
        grass_light=(214, 186, 120), grass_dark=(200, 172, 108),
        lane_marker=(250, 244, 220),
        ambient=(1.04, 1.0, 0.88),
        decor_weights={"cactus": 5, "rock": 4, "pillar": 2, "ruin": 1},
        fog_scale=0.8,
        obstacle_tint=(120, 96, 64),
    ),
    Biome(
        key="cavern",
        name="Crystal Cavern",
        sky_top=(12, 14, 26), sky_bottom=(30, 36, 60), fog=(24, 30, 52),
        road_light=(52, 54, 68), road_dark=(44, 46, 60),
        rumble_light=(120, 150, 210), rumble_dark=(60, 40, 90),
        grass_light=(28, 30, 52), grass_dark=(22, 24, 44),
        lane_marker=(160, 200, 255),
        ambient=(0.8, 0.85, 1.05),
        decor_weights={"crystal": 6, "rock": 4, "pillar": 2, "torch": 1},
        fog_scale=1.4,
        obstacle_tint=(50, 54, 78),
    ),
    Biome(
        key="lava",
        name="Molten Depths",
        sky_top=(40, 12, 12), sky_bottom=(150, 60, 30), fog=(120, 50, 30),
        road_light=(60, 46, 42), road_dark=(50, 38, 34),
        rumble_light=(255, 160, 60), rumble_dark=(120, 30, 20),
        grass_light=(90, 30, 20), grass_dark=(70, 22, 16),
        lane_marker=(255, 200, 120),
        ambient=(1.1, 0.9, 0.82),
        decor_weights={"rock": 5, "pillar": 3, "torch": 4, "ruin": 2},
        fog_scale=1.3,
        obstacle_tint=(70, 40, 34),
    ),
    Biome(
        key="ice",
        name="Frozen Sanctum",
        sky_top=(120, 150, 200), sky_bottom=(220, 235, 250), fog=(210, 225, 240),
        road_light=(150, 165, 185), road_dark=(138, 154, 176),
        rumble_light=(240, 250, 255), rumble_dark=(120, 160, 200),
        grass_light=(200, 220, 235), grass_dark=(184, 206, 224),
        lane_marker=(255, 255, 255),
        ambient=(0.95, 0.98, 1.08),
        decor_weights={"crystal": 4, "rock": 3, "pillar": 3, "lantern": 2},
        fog_scale=0.9,
        obstacle_tint=(120, 140, 165),
    ),
    Biome(
        key="night",
        name="Moonlit Shrine",
        sky_top=(8, 8, 24), sky_bottom=(40, 40, 78), fog=(30, 30, 60),
        road_light=(48, 48, 60), road_dark=(40, 40, 52),
        rumble_light=(180, 180, 220), rumble_dark=(80, 60, 120),
        grass_light=(24, 40, 34), grass_dark=(18, 32, 28),
        lane_marker=(200, 200, 240),
        ambient=(0.82, 0.84, 1.06),
        decor_weights={"tree": 3, "pillar": 3, "lantern": 4, "ruin": 2},
        fog_scale=1.5,
        obstacle_tint=(46, 46, 62),
    ),
]

BIOME_BY_KEY: Dict[str, Biome] = {b.key: b for b in BIOMES}


def biome_at_index(order_index: int) -> Biome:
    """Cycle through the biome library by an integer chunk counter."""
    return BIOMES[order_index % len(BIOMES)]


def default_biome() -> Biome:
    return BIOMES[0]
