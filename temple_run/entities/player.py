"""
The player controller.

The player is a lane-based endless runner avatar with a compact behaviour state
machine:

    RUNNING  --jump-->  JUMPING  --land-->  RUNNING
    RUNNING  --slide--> SLIDING  --timer--> RUNNING
    any      --hit-->   STUMBLING (recoverable) or DEAD

It integrates its own forward motion (``z += speed * dt``), eases smoothly
between the three lanes, and arcs through jumps under gravity. Quality-of-life
touches that the original lacked are here: **input buffering** (a jump pressed a
few frames early still fires the instant you land) and **coyote time** (a jump
requested just after leaving the ground still counts), so the controls feel
forgiving instead of twitchy.

The player never draws itself or touches particles/audio directly — it publishes
events (``PLAYER_JUMP``, ``PLAYER_LAND``, …) on the bus and lets the presentation
systems react. That keeps the physics module pure and testable.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Optional

from ..config import Physics, Track as TCfg
from ..core.events import Event, EventBus, EventType
from ..mathutils import clamp, damp

# How high the player must be to clear a low (jumpable) obstacle.
JUMP_CLEAR_HEIGHT = 240.0
# Lean applied to the sprite while shifting lanes (radians-ish, visual only).
MAX_TILT = 0.35


class PlayerState(Enum):
    IDLE = auto()
    RUNNING = auto()
    JUMPING = auto()
    SLIDING = auto()
    STUMBLING = auto()
    DEAD = auto()


class Player:
    def __init__(self, event_bus: EventBus):
        self.bus = event_bus
        self.reset()

    # --------------------------------------------------------------- lifecycle
    def reset(self) -> None:
        self.state = PlayerState.IDLE
        # Lateral (world x), vertical (height above road), and camera-z.
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        self.vy = 0.0

        self.current_lane = 0
        self.target_lane = 0

        # Forward speed is driven by the difficulty director; start sane.
        self.speed = Physics.START_SPEED
        self.boost_multiplier = 1.0

        # Timers and buffers.
        self._slide_time = 0.0
        self._coyote = 0.0
        self._buffered_jump = 0.0
        self._buffered_slide = 0.0
        self._stumble_time = 0.0

        # Animation scratch.
        self.run_cycle = 0.0
        self.tilt = 0.0
        self.alive = True
        self.distance = 0.0  # total world units travelled

    def start_running(self) -> None:
        self.state = PlayerState.RUNNING

    # ----------------------------------------------------------------- helpers
    @property
    def world_z(self) -> float:
        """Z used for collision and for drawing the sprite (ahead of camera)."""
        from ..render.camera import PLAYER_Z_AHEAD
        return self.z + PLAYER_Z_AHEAD

    @property
    def effective_speed(self) -> float:
        return self.speed * self.boost_multiplier

    @property
    def on_ground(self) -> bool:
        return self.state in (PlayerState.RUNNING, PlayerState.SLIDING,
                              PlayerState.STUMBLING)

    @property
    def is_sliding(self) -> bool:
        return self.state == PlayerState.SLIDING

    @property
    def is_airborne(self) -> bool:
        return self.state == PlayerState.JUMPING or self.y > 1.0

    def occupied_lane(self) -> int:
        """The lane the player currently overlaps, derived from world x."""
        unit = TCfg.ROAD_WIDTH * TCfg.LANE_FRACTION
        lane = round(self.x / unit) if unit else 0
        return int(clamp(lane, -1, 1))

    def clears_low_obstacle(self) -> bool:
        return self.y >= JUMP_CLEAR_HEIGHT

    # ------------------------------------------------------------------- input
    def move_left(self) -> None:
        if self.state == PlayerState.DEAD:
            return
        if self.target_lane > -(TCfg.LANES // 2):
            self.target_lane -= 1
            self.bus.publish(Event(EventType.PLAYER_LANE_CHANGE,
                                   {"lane": self.target_lane, "dir": -1}))

    def move_right(self) -> None:
        if self.state == PlayerState.DEAD:
            return
        if self.target_lane < TCfg.LANES // 2:
            self.target_lane += 1
            self.bus.publish(Event(EventType.PLAYER_LANE_CHANGE,
                                   {"lane": self.target_lane, "dir": 1}))

    def jump(self) -> None:
        if self.state == PlayerState.DEAD:
            return
        # Buffer the request; it will fire this frame if allowed.
        self._buffered_jump = Physics.INPUT_BUFFER

    def slide(self) -> None:
        if self.state == PlayerState.DEAD:
            return
        self._buffered_slide = Physics.INPUT_BUFFER

    def _do_jump(self) -> None:
        self.state = PlayerState.JUMPING
        self.vy = Physics.JUMP_VELOCITY
        self._buffered_jump = 0.0
        self._coyote = 0.0
        self.bus.publish(Event(EventType.PLAYER_JUMP, {}))

    def _do_slide(self) -> None:
        self.state = PlayerState.SLIDING
        self._slide_time = Physics.SLIDE_DURATION
        self._buffered_slide = 0.0
        self.bus.publish(Event(EventType.PLAYER_SLIDE, {}))

    # ----------------------------------------------------------------- damage
    def stumble(self) -> None:
        """A recoverable hit: lose speed, briefly stagger, keep running."""
        if self.state == PlayerState.DEAD:
            return
        self.state = PlayerState.STUMBLING
        self._stumble_time = 0.5
        self.speed = max(Physics.MIN_SPEED, self.speed - Physics.STUMBLE_SPEED_LOSS)
        self.bus.publish(Event(EventType.PLAYER_STUMBLE, {}))

    def kill(self) -> None:
        if self.state == PlayerState.DEAD:
            return
        self.state = PlayerState.DEAD
        self.alive = False
        self.vy = Physics.JUMP_VELOCITY * 0.4  # a small death "pop"
        self.bus.publish(Event(EventType.PLAYER_DIED, {}))

    # ------------------------------------------------------------------ update
    def update(self, dt: float, track) -> None:
        if self.state == PlayerState.IDLE:
            return

        self._tick_timers(dt)

        if self.state == PlayerState.DEAD:
            # Ragdoll-ish fall so the death is legible before Game Over.
            self.vy -= Physics.GRAVITY * dt
            self.y = max(-400.0, self.y + self.vy * dt)
            self.speed = damp(self.speed, 0.0, 0.0001, dt)
            self.z += self.effective_speed * dt
            return

        # Forward motion.
        self.z += self.effective_speed * dt
        self.distance += self.effective_speed * dt

        self._update_lanes(dt)
        self._update_vertical(dt)
        self._service_buffers()

        # Run animation speed scales with velocity for a lively gait.
        if self.on_ground and self.state != PlayerState.STUMBLING:
            self.run_cycle += dt * (6.0 + self.effective_speed / 1400.0)

    def _tick_timers(self, dt: float) -> None:
        self._buffered_jump = max(0.0, self._buffered_jump - dt)
        self._buffered_slide = max(0.0, self._buffered_slide - dt)
        self._coyote = max(0.0, self._coyote - dt)
        if self.state == PlayerState.STUMBLING:
            self._stumble_time -= dt
            if self._stumble_time <= 0.0:
                self.state = PlayerState.RUNNING

    def _update_lanes(self, dt: float) -> None:
        target_x = TCfg.lane_x(self.target_lane)
        self.x = damp(self.x, target_x, 0.0000009, dt)
        if abs(self.x - target_x) < TCfg.ROAD_WIDTH * Physics.LANE_SNAP_EPS:
            self.current_lane = self.target_lane
        # Visual lean toward the direction of travel.
        lean_target = clamp((target_x - self.x) / (TCfg.ROAD_WIDTH * 0.4), -1, 1) * MAX_TILT
        self.tilt = damp(self.tilt, lean_target, 0.0001, dt)

    def _update_vertical(self, dt: float) -> None:
        if self.state == PlayerState.JUMPING:
            self.vy -= Physics.GRAVITY * dt
            self.y += self.vy * dt
            if self.y <= 0.0:
                self.y = 0.0
                self.vy = 0.0
                self.state = PlayerState.RUNNING
                self._coyote = Physics.COYOTE_TIME
                self.bus.publish(Event(EventType.PLAYER_LAND, {}))
        elif self.state == PlayerState.SLIDING:
            self._slide_time -= dt
            if self._slide_time <= 0.0:
                self.state = PlayerState.RUNNING

    def _service_buffers(self) -> None:
        # Fire a buffered jump if we're grounded (or within coyote time).
        can_jump = self.state in (PlayerState.RUNNING, PlayerState.STUMBLING) \
            or self._coyote > 0.0
        if self._buffered_jump > 0.0 and can_jump and self.state != PlayerState.JUMPING:
            self._do_jump()
            return
        # Fire a buffered slide only while grounded and running.
        if self._buffered_slide > 0.0 and self.state == PlayerState.RUNNING:
            self._do_slide()
