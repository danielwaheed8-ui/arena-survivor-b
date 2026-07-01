"""
Track segments and roadside scenery descriptors.

A :class:`Segment` is one short slab of road along the ``z`` axis. It stores the
near/far elevation (so the road can rise and fall), a curvature value used by the
renderer's accumulating-curve trick, a light/dark flag for the rumble stripes,
and the biome it belongs to. Scenery objects (trees, pillars, …) are attached to
segments so they scroll and cull naturally with the road.

Segments are deliberately lean (``__slots__``) because an endless run creates a
lot of them.
"""

from __future__ import annotations

from typing import List, Optional

from ..config import Track
from ..mathutils import lerp
from .biomes import Biome


class Decoration:
    """A roadside scenery item anchored to a segment.

    ``side`` is -1 (left) or +1 (right); ``offset`` is how far past the road edge
    it sits (1.0 == exactly at the rumble edge, larger == further out). ``scale``
    multiplies its drawn size. ``kind`` is one of :data:`biomes.DECOR_KINDS`.
    """

    __slots__ = ("kind", "side", "offset", "scale", "tint", "sway_phase")

    def __init__(self, kind: str, side: int, offset: float, scale: float,
                 tint=(255, 255, 255), sway_phase: float = 0.0):
        self.kind = kind
        self.side = side
        self.offset = offset
        self.scale = scale
        self.tint = tint
        self.sway_phase = sway_phase


class Segment:
    __slots__ = (
        "index", "z_near", "z_far", "y_near", "y_far",
        "curve", "light", "biome", "decorations", "clip",
    )

    def __init__(
        self,
        index: int,
        y_near: float,
        y_far: float,
        curve: float,
        light: bool,
        biome: Biome,
    ):
        self.index = index
        self.z_near = index * Track.SEGMENT_LENGTH
        self.z_far = (index + 1) * Track.SEGMENT_LENGTH
        self.y_near = y_near
        self.y_far = y_far
        self.curve = curve
        self.light = light
        self.biome = biome
        self.decorations: List[Decoration] = []
        # ``clip`` is scratch space the renderer fills each frame (hill occlusion).
        self.clip = 0.0

    def elevation_at(self, z: float) -> float:
        """Interpolated road-surface height at world ``z`` inside this segment."""
        t = (z - self.z_near) / Track.SEGMENT_LENGTH
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
        return lerp(self.y_near, self.y_far, t)

    def add_decoration(self, deco: Decoration) -> None:
        self.decorations.append(deco)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Segment {self.index} y={self.y_near:.0f} curve={self.curve:.2f}>"
