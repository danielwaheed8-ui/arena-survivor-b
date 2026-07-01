"""
Central configuration.

Everything tunable lives here so designers can balance the game without hunting
through logic. Values are grouped into frozen-ish namespaces (plain classes used
as namespaces) so call-sites read like ``Config.WIDTH`` / ``Physics.GRAVITY``.

Nothing in this module imports from the rest of the package, so it is safe to
import from anywhere without creating cycles.
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

Color = Tuple[int, int, int]


# ---------------------------------------------------------------------------
# Display / timing
# ---------------------------------------------------------------------------
class Config:
    TITLE = "Temple Run — World-Class Python Edition"
    WIDTH = 1280
    HEIGHT = 720
    FPS = 60

    # The horizon sits a little above centre so we can see more road.
    HORIZON_RATIO = 0.42  # fraction of the screen height that is sky

    # We clamp the frame delta so a stutter (or a debugger breakpoint) can never
    # teleport the player through an obstacle.
    MAX_DT = 1.0 / 20.0

    # Where to persist the save file. Kept next to the running script.
    SAVE_FILE = "temple_run_save.json"
    SETTINGS_FILE = "temple_run_settings.json"


# ---------------------------------------------------------------------------
# Pseudo-3D camera / projection
# ---------------------------------------------------------------------------
class Cam:
    # Field of view in degrees; camera depth is derived from it.
    FOV = 100.0
    # Distance from ground to eye, in world units.
    HEIGHT = 1500.0
    # How far behind the player, expressed as a multiple of camera-depth units.
    # Larger -> the player sprite sits lower/closer.
    PLAYER_Z_OFFSET = 0.0
    # Camera depth: 1 / tan(fov/2). Precomputed once.
    DEPTH = 1.0 / math.tan(math.radians(FOV / 2.0))
    # How many segments to draw ahead of the camera.
    DRAW_DISTANCE = 300
    # Fog thickness. Higher = denser fog fading distant road into FOG colour.
    FOG_DENSITY = 5.0
    # Camera sway: the eye drifts slightly toward the player's lateral position.
    CENTRIFUGAL = 0.30  # how hard curves push the player sideways


# ---------------------------------------------------------------------------
# Track geometry
# ---------------------------------------------------------------------------
class Track:
    # Half-width of the road in world units (road spans [-WIDTH, +WIDTH]).
    ROAD_WIDTH = 2200
    # Length of a single track segment along z.
    SEGMENT_LENGTH = 200
    # How many segments share a rumble-stripe colour band.
    RUMBLE_LENGTH = 3
    # Number of lanes and the fraction of the half-road each lane centre sits at.
    LANES = 3
    LANE_FRACTION = 0.62  # outer lane centre = ±ROAD_WIDTH*LANE_FRACTION
    # A generated "chunk" is this many segments. The world keeps a rolling
    # window of chunks so it is effectively endless.
    CHUNK_SEGMENTS = 250
    # Keep this many chunks live at once (behind + ahead of the player).
    CHUNKS_AHEAD = 4
    CHUNKS_BEHIND = 1

    @staticmethod
    def lane_x(lane: int) -> float:
        """World-space centre-x of a lane index in ``[-1, 0, 1]``."""
        return lane * Track.ROAD_WIDTH * Track.LANE_FRACTION


# ---------------------------------------------------------------------------
# Physics / player feel
# ---------------------------------------------------------------------------
class Physics:
    # Gravity in world-units / s^2 (tuned for the jump arc, not realism).
    GRAVITY = 9200.0
    # Initial upward velocity of a jump.
    JUMP_VELOCITY = 3200.0
    # Duration the player stays in the slide pose.
    SLIDE_DURATION = 0.55
    # How quickly the player slews between lanes (higher = snappier).
    LANE_CHANGE_SPEED = 11.0
    # A lane change is "committed" once within this fraction of the target.
    LANE_SNAP_EPS = 0.04

    # Forward speed model (world units / second).
    START_SPEED = 5200.0
    MIN_SPEED = 4200.0
    MAX_SPEED = 15000.0
    # Passive acceleration while running.
    ACCEL = 90.0
    # Speed lost when clipping a glancing obstacle (if you have a shield, etc).
    STUMBLE_SPEED_LOSS = 2600.0

    # Coyote time: you may still jump this long after leaving a ledge.
    COYOTE_TIME = 0.10
    # Input buffering: a jump/slide pressed this early still fires on landing.
    INPUT_BUFFER = 0.14


# ---------------------------------------------------------------------------
# Gameplay tuning
# ---------------------------------------------------------------------------
class Gameplay:
    COIN_VALUE = 1
    GEM_VALUE = 25
    # Distance (in world units) that equals one "metre" of displayed score.
    METERS_PER_UNIT = 1.0 / 100.0
    # Points awarded per metre of distance.
    SCORE_PER_METER = 1.0
    # Near-miss: passing this close to an obstacle without hitting grants bonus.
    NEAR_MISS_RADIUS = 520.0
    NEAR_MISS_BONUS = 15
    # Combo: chained pickups multiply score; the multiplier decays after a gap.
    COMBO_WINDOW = 2.4  # seconds to keep a combo alive
    COMBO_STEP = 0.1    # multiplier added per chained pickup
    COMBO_MAX = 4.0


# ---------------------------------------------------------------------------
# Colour palette (base UI + fallback world colours)
# ---------------------------------------------------------------------------
class Palette:
    WHITE: Color = (245, 245, 245)
    BLACK: Color = (12, 12, 16)
    GREY: Color = (90, 90, 100)
    LIGHT_GREY: Color = (170, 170, 180)
    DARK_GREY: Color = (40, 40, 48)

    GOLD: Color = (255, 205, 60)
    GOLD_DARK: Color = (200, 150, 0)
    GEM: Color = (80, 220, 255)
    GEM_DARK: Color = (30, 150, 200)

    PLAYER: Color = (225, 70, 70)
    PLAYER_DARK: Color = (150, 30, 30)
    SKIN: Color = (255, 205, 165)

    DANGER: Color = (235, 70, 70)
    SUCCESS: Color = (90, 210, 120)
    WARNING: Color = (255, 200, 60)
    INFO: Color = (90, 170, 255)

    UI_PANEL: Color = (24, 26, 34)
    UI_PANEL_LIGHT: Color = (40, 44, 56)
    UI_ACCENT: Color = (255, 160, 60)
    UI_TEXT: Color = (235, 235, 240)
    UI_TEXT_DIM: Color = (150, 155, 165)

    # Fog colour used to fade distant geometry. Overridden per-biome.
    FOG: Color = (150, 155, 170)


def lerp_color(a: Color, b: Color, t: float) -> Color:
    """Linear interpolation between two RGB colours."""
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def shade_color(c: Color, factor: float) -> Color:
    """Multiply a colour's brightness by ``factor`` (clamped to 0..255)."""
    return (
        max(0, min(255, int(c[0] * factor))),
        max(0, min(255, int(c[1] * factor))),
        max(0, min(255, int(c[2] * factor))),
    )


# ---------------------------------------------------------------------------
# Key bindings (defaults; the settings system can override them)
# ---------------------------------------------------------------------------
class Keys:
    # Named to logical actions; the InputManager resolves pygame keycodes.
    DEFAULT_BINDINGS: Dict[str, Tuple[str, ...]] = {
        "left": ("LEFT", "a"),
        "right": ("RIGHT", "d"),
        "jump": ("UP", "w", "SPACE"),
        "slide": ("DOWN", "s"),
        "pause": ("ESCAPE", "p"),
        "confirm": ("RETURN", "SPACE"),
        "back": ("ESCAPE",),
        "use_item": ("e", "RSHIFT"),
    }
