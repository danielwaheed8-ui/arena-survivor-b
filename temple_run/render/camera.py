"""
The camera.

The camera derives its world position from the player each frame:

* ``z`` sits exactly at the player's camera-z (the value the player advances).
  The player *sprite* is drawn a little ahead of the camera (``PLAYER_Z_AHEAD``)
  so it sits near the bottom of the screen — the classic third-person runner
  framing.
* ``y`` rides at a fixed eye-height above the road surface directly beneath the
  camera, so hills make the road rise and fall convincingly.
* ``x`` *partially* follows the player's lateral position. A follow factor of
  0.0 would pin the camera to the road centre (lane changes look huge); 1.0
  would glue the camera to the player (lane changes become invisible). A value
  in between keeps lane movement readable while still leaning into the action.

The camera also owns screen-shake: a decaying random offset added to the world
position, which makes *everything* jolt on impact for free.
"""

from __future__ import annotations

import math

from ..config import Cam
from ..mathutils import RNG

# How strongly the camera tracks the player's lateral position (0..1).
FOLLOW = 0.5
# Player sprite sits this far ahead of the camera along z.
PLAYER_Z_AHEAD = Cam.HEIGHT * Cam.DEPTH


class Camera:
    def __init__(self, rng: RNG | None = None):
        self.x = 0.0
        self.y = Cam.HEIGHT
        self.z = 0.0
        self.depth = Cam.DEPTH
        self._rng = rng or RNG()

        # Screen-shake state.
        self._shake_time = 0.0
        self._shake_dur = 0.0
        self._shake_mag = 0.0
        self.shake_x = 0.0
        self.shake_y = 0.0

    def add_shake(self, magnitude: float, duration: float = 0.35) -> None:
        """Trigger (or reinforce) a screen shake."""
        self._shake_mag = max(self._shake_mag, magnitude)
        self._shake_dur = max(self._shake_dur, duration)
        self._shake_time = self._shake_dur

    def update(self, player, track, dt: float) -> None:
        ground = track.elevation_at(player.z)
        self.x = player.x * FOLLOW
        self.y = ground + Cam.HEIGHT
        self.z = player.z

        # Decay and sample the shake.
        if self._shake_time > 0.0:
            self._shake_time = max(0.0, self._shake_time - dt)
            k = self._shake_time / self._shake_dur if self._shake_dur else 0.0
            amp = self._shake_mag * k * k
            self.shake_x = (self._rng.range(-1.0, 1.0)) * amp
            self.shake_y = (self._rng.range(-1.0, 1.0)) * amp * 0.6
        else:
            self.shake_x = 0.0
            self.shake_y = 0.0

    @property
    def render_x(self) -> float:
        """Camera x including the current shake offset (world units)."""
        return self.x + self.shake_x

    @property
    def render_y(self) -> float:
        return self.y + self.shake_y
