"""
The difficulty director — the game's invisible pacing conductor.

A great endless runner does not get harder by getting *random*; it gets harder by
getting *faster*, and it stays *fair* while it does. This module owns that curve.
It is the single authority on two coupled things:

1. **How fast the player runs.** We ramp a *target* speed from
   :data:`Physics.START_SPEED` toward :data:`Physics.MAX_SPEED` as a smooth
   function of distance travelled (with a gentle time component so even a
   stationary-looking start still warms up). We never *snap* ``player.speed`` to
   that target — we ease it with frame-rate-independent damping so acceleration
   feels organic and a revive/boost can perturb it without a jolt.

2. **How the track ahead is populated.** We hand the spawner a fresh
   :class:`SpawnKnobs` bundle every frame. Two knobs matter most:

   * ``feature_gap`` — the world-unit spacing between feature slots. This is the
     crux of fairness: at 15,000 u/s a 2,600-unit gap is only ~0.17 s of reaction
     time, which is unplayable. So we *scale the gap with speed* to guarantee a
     minimum reaction window (``feature_gap = max(base, effective_speed *
     MIN_REACTION)``). Faster player ⇒ wider spacing ⇒ reaction time never dips
     below the floor. This is what keeps a fast run *hard* rather than *cheap*.
   * the probability knobs (obstacle / coin / gem / powerup / double / moving) —
     these *intensify* with the difficulty ``level`` so the mix shifts from
     forgiving (lots of coin runs, single-lane obstacles) toward punishing (dense
     obstacle rows, more double-blocks, more moving rollers) as the run matures.

Design rationale worth calling out:

* **One source of truth for pace.** Speed and spawn density are derived from the
  same ``intensity`` scalar, so the difficulty always feels *coherent* — you never
  get a slow track that's wall-to-wall obstacles, or a blistering track that's
  empty. Tuning is a matter of editing a handful of anchors here.
* **Distance-driven, not timer-driven.** Two players who reach 3,000 m face the
  same challenge regardless of how long it took them, which is the fair contract
  an endless runner makes with a leaderboard.
* **Bounded everywhere.** Every probability is clamped, ``feature_gap`` has a hard
  floor, and the level/intensity curves saturate. Nothing here can spiral into an
  unbeatable state.

The director is pure logic: it imports only config, mathutils and the
:class:`SpawnKnobs` dataclass. It reads a handful of read-only attributes off the
player and (optionally) writes ``player.speed``. It never touches pygame, the
event bus, or any sibling system, which keeps it trivially unit-testable.
"""

from __future__ import annotations

import math
from typing import Any, Dict

from ..config import Gameplay, Physics
from ..entities.spawner import SpawnKnobs
from ..mathutils import clamp, clamp01, damp, lerp, smoothstep

# ---------------------------------------------------------------------------
# Tuning anchors
# ---------------------------------------------------------------------------
# All of the director's "personality" lives in these constants. They are grouped
# and commented so a designer can rebalance the whole game from one screen.

# --- speed ramp ------------------------------------------------------------
# Distance (in world units) over which the speed ramp goes from "just started"
# to "flat out". Chosen so the ramp feels meaningful for a couple of minutes of
# play rather than maxing out in the first ten seconds.
RAMP_DISTANCE_UNITS = 1_400_000.0  # ~14 km of displayed distance to top speed
# A small, purely time-based warm-up so the very first seconds still accelerate
# perceptibly before distance has accumulated. Fraction of the ramp filled per
# second, saturating quickly.
RAMP_TIME_SECONDS = 55.0
# How much of the ramp comes from the time term vs. the distance term. The
# distance term dominates (fairness: same distance ⇒ same speed); the time term
# just smooths the opening.
TIME_RAMP_WEIGHT = 0.18

# ``damp`` smoothing = "fraction of the gap to target remaining after one
# second". Small ⇒ fast. We keep it fairly snappy so the player reaches the
# ramp's dictated speed without a laggy, floaty feel — but not instant, so
# transient perturbations (boost ending, a revive resetting speed) glide back.
SPEED_SMOOTHING = 0.0006

# --- fairness floor --------------------------------------------------------
# Minimum reaction time, in seconds, the player is guaranteed before a feature
# slot arrives. This is *the* fairness knob. 0.7 s is a comfortable human visual
# reaction budget for a telegraphed obstacle; below ~0.4 s an endless runner
# stops being a skill test and becomes a memory test.
MIN_REACTION = 0.72
# The relaxed base spacing used at low speeds where reaction time is already
# generous. Matches the spawner's own default so early play is unchanged.
BASE_FEATURE_GAP = 2600.0
# An absolute hard floor on the gap. Even if the reaction-time formula somehow
# produced something tiny (it can't, given MAX_SPEED * MIN_REACTION), we never
# let two feature slots sit closer than this — the spawner itself also enforces
# a 1200-unit minimum, and we stay comfortably above it.
MIN_FEATURE_GAP = 3200.0

# --- level curve -----------------------------------------------------------
# Every this many world units of distance, the player gains a difficulty level.
# Purely cosmetic/telemetry (surfaced in the HUD snapshot) but also used as a
# readable driver for the probability ramps.
UNITS_PER_LEVEL = 120_000.0  # ~1200 m of displayed distance per level

# --- probability envelopes -------------------------------------------------
# Each spawn probability interpolates from an EASY anchor (intensity 0) to a HARD
# anchor (intensity 1). The spawner treats obstacle/coin/gem/powerup as a
# partition of a single roll, so we keep obstacle + coin + gem + powerup <= ~1.0
# at every intensity and let the remainder be intentional "breather" slots.
#
#                       (easy,   hard)
OBSTACLE_PROB = (0.42, 0.66)   # more of the track is hazardous later
COIN_PROB = (0.40, 0.24)       # fewer freebie coin runs as it heats up
GEM_PROB = (0.030, 0.055)      # gems trend slightly rarer-feeling but richer
POWERUP_PROB = (0.070, 0.045)  # powerups thin out so late game stays tense
DOUBLE_PROB = (0.10, 0.42)     # far more two-lane blocks late (still never 3)
MOVING_PROB = (0.03, 0.20)     # rollers become common at high intensity
# Coin runs get a touch shorter as things speed up so grabbing a full run
# demands commitment rather than being a free lane.
COIN_RUN_LEN = (7, 4)


class DifficultyDirector:
    """Owns the run's pace: player speed *and* spawn density, coherently.

    Usage from the game loop::

        director = DifficultyDirector()
        ...
        knobs = director.update(dt, player)   # every frame, before spawner.update
        spawner.update(player, track, knobs)

    The director keeps no reference to the player between frames; everything it
    needs is passed into :meth:`update`, and everything it exposes
    (:attr:`level`, :attr:`intensity`, :meth:`snapshot`) is derived state a HUD
    can read cheaply.
    """

    def __init__(self) -> None:
        # Public, read-by-others state. Initialised via reset() so the ctor and
        # a mid-session restart share one definition of "fresh".
        self.level: int = 1
        self.intensity: float = 0.0
        # The un-eased speed the ramp currently *wants* the player to run at.
        # Kept around mostly for introspection/tests; player.speed chases it.
        self.target_speed: float = Physics.START_SPEED
        # Internal warm-up clock for the small time-based ramp term.
        self._elapsed: float = 0.0
        # Cache the last knobs so a consumer that calls update() at a different
        # cadence than it reads still gets something sane.
        self._knobs: SpawnKnobs = SpawnKnobs()
        self.reset()

    # ------------------------------------------------------------- lifecycle
    def reset(self) -> None:
        """Return the director to its start-of-run state.

        Called on GAME_START / GAME_RESTART by the game controller. We reset the
        warm-up clock, level and intensity, and rebuild a fresh, *easy* knob
        bundle so the first frames after a restart are gentle even before the
        first :meth:`update` lands.
        """
        self.level = 1
        self.intensity = 0.0
        self.target_speed = Physics.START_SPEED
        self._elapsed = 0.0
        # Build the easy-anchor knobs directly rather than calling update(),
        # since we have no player here.
        self._knobs = self._make_knobs(intensity=0.0, effective_speed=Physics.START_SPEED)

    # --------------------------------------------------------------- update
    def update(self, dt: float, player: Any) -> SpawnKnobs:
        """Advance the director one frame and return this frame's spawn knobs.

        Steps:

        1. Advance the warm-up clock.
        2. Recompute :attr:`intensity` (0..1) from distance + a little time.
        3. Recompute :attr:`level` from distance.
        4. Ramp :attr:`target_speed` and ease ``player.speed`` toward it.
        5. Build and return a :class:`SpawnKnobs` bundle scaled by speed & level.

        The method is defensive: ``dt`` is clamped to a sane range and every
        attribute read off ``player`` is guarded, so a malformed player (or a
        pathological ``dt`` from a stall) can never crash the run or push the
        speed out of bounds.
        """
        # Guard dt: a debugger pause or a dropped frame must not fast-forward the
        # ramp or blow up the damping exponent. Clamp to [0, MAX_DT]. A NaN/inf dt
        # (which clamp would pass straight through) would poison the damping and
        # permanently corrupt player.speed, so we reject non-finite values first.
        try:
            dt = float(dt)
            if not math.isfinite(dt):
                dt = 0.0
            dt = clamp(dt, 0.0, Physics.MAX_DT if hasattr(Physics, "MAX_DT") else 0.05)
        except (TypeError, ValueError):
            dt = 0.0

        self._elapsed += dt

        # --- distance & the two ramp terms ---------------------------------
        distance = self._read_distance(player)

        # Distance term: the primary, fairness-preserving driver. Smoothstepped
        # so the curve eases in and out rather than ramping linearly — the pace
        # change feels deliberate, quick in the middle, gentle at the extremes.
        distance_t = smoothstep(0.0, RAMP_DISTANCE_UNITS, distance)

        # Time term: a fast-saturating warm-up so the opening seconds accelerate
        # even before much distance exists. clamp01 keeps it bounded.
        time_t = clamp01(self._elapsed / RAMP_TIME_SECONDS)

        # Blend: distance dominates; time nudges the opening. The result is the
        # single 0..1 intensity scalar that drives *everything* downstream.
        self.intensity = clamp01(
            lerp(distance_t, max(distance_t, time_t), TIME_RAMP_WEIGHT)
        )

        # --- level ----------------------------------------------------------
        # Levels are a readable integer telemetry surface; they rise forever with
        # distance (the probability ramps saturate via intensity, so an ever-
        # climbing level number does no harm — it's just a badge).
        self.level = 1 + int(max(0.0, distance) // UNITS_PER_LEVEL)

        # --- speed ramp -----------------------------------------------------
        self.target_speed = self._ramp_speed(self.intensity)
        self._apply_speed(player, dt)

        # --- knobs ----------------------------------------------------------
        effective_speed = self._read_effective_speed(player)
        self._knobs = self._make_knobs(self.intensity, effective_speed)
        return self._knobs

    # ------------------------------------------------------- speed helpers
    def _ramp_speed(self, intensity: float) -> float:
        """Map an intensity in [0,1] to a target forward speed.

        The speed curve is deliberately *not* the same shape as ``intensity``
        (which already carries the time warm-up). We anchor speed purely between
        START and MAX and reuse the smooth intensity as the parameter, giving a
        monotonic, saturating climb that tops out at :data:`Physics.MAX_SPEED`.
        """
        start = float(Physics.START_SPEED)
        top = float(Physics.MAX_SPEED)
        # A touch of extra ease so the top-end approach is gradual rather than
        # arriving abruptly at MAX_SPEED.
        eased = smoothstep(0.0, 1.0, clamp01(intensity))
        speed = lerp(start, top, eased)
        # Respect the engine's floor/ceiling regardless of anchor edits.
        return clamp(speed, float(Physics.MIN_SPEED), top)

    def _apply_speed(self, player: Any, dt: float) -> None:
        """Ease ``player.speed`` toward :attr:`target_speed` (never snap).

        We use :func:`damp` for frame-rate-independent exponential smoothing so
        the acceleration feels identical at 30 or 144 FPS. Writing ``player.speed``
        is guarded: a read-only or duck-typed player simply doesn't get steered,
        and the run continues at whatever speed it had.
        """
        if player is None:
            return
        current = self._read_speed(player)
        # With dt==0 (a paused frame) damp is a no-op; that's exactly right.
        new_speed = damp(current, self.target_speed, SPEED_SMOOTHING, dt)
        # If anything upstream produced a non-finite value (a poisoned current
        # speed read off a stub, say), fall back to the ramp's own target rather
        # than writing NaN/inf into the player and corrupting every later frame.
        if not math.isfinite(new_speed):
            new_speed = self.target_speed
        # Final safety clamp so nothing downstream ever sees an out-of-range
        # speed even if a subclass overrode the anchors oddly.
        new_speed = clamp(new_speed, float(Physics.MIN_SPEED), float(Physics.MAX_SPEED))
        try:
            player.speed = new_speed
        except (AttributeError, TypeError):
            # Player exposes speed read-only (or is a stub); nothing to do.
            pass

    # -------------------------------------------------------- knob builder
    def _make_knobs(self, intensity: float, effective_speed: float) -> SpawnKnobs:
        """Construct the :class:`SpawnKnobs` bundle for a given intensity/speed.

        ``feature_gap`` is the fairness centrepiece: it is the *larger* of the
        relaxed base gap and the distance the player covers during the guaranteed
        reaction window at their current speed. So the faster you go, the more
        breathing room between hazards — reaction time is held at or above
        :data:`MIN_REACTION` no matter the speed.
        """
        t = clamp01(intensity)

        # Reaction-time-preserving spacing. effective_speed is world-units/second,
        # so speed * seconds = world-units of runway before the next feature.
        reaction_gap = max(effective_speed, 0.0) * MIN_REACTION
        feature_gap = max(BASE_FEATURE_GAP, reaction_gap, MIN_FEATURE_GAP)

        # Probability ramps: each lerps between its easy and hard anchor by t and
        # is then clamped to a defensive [0,1] (anchors are already sane, but a
        # future edit shouldn't be able to emit an invalid probability).
        obstacle_prob = _prob(OBSTACLE_PROB, t)
        coin_prob = _prob(COIN_PROB, t)
        gem_prob = _prob(GEM_PROB, t)
        powerup_prob = _prob(POWERUP_PROB, t)

        # The four partition probabilities share a single spawner roll. Keep their
        # sum below 1.0 so there is always some chance of a deliberate empty
        # "breather" slot — a run with zero gaps is exhausting and unfair.
        obstacle_prob, coin_prob, gem_prob, powerup_prob = _normalise_partition(
            obstacle_prob, coin_prob, gem_prob, powerup_prob, headroom=0.06
        )

        # Row-shape modifiers. These aren't part of the partition; they modulate
        # *what kind* of obstacle row appears when the obstacle branch is taken.
        double_prob = _prob(DOUBLE_PROB, t)
        moving_prob = _prob(MOVING_PROB, t)

        # Coin runs shorten with intensity; round to a sane integer and floor at
        # a length that still reads as a "run" rather than a stray coin.
        coin_run_len = int(round(lerp(COIN_RUN_LEN[0], COIN_RUN_LEN[1], t)))
        coin_run_len = max(3, coin_run_len)

        return SpawnKnobs(
            feature_gap=feature_gap,
            obstacle_prob=obstacle_prob,
            coin_prob=coin_prob,
            gem_prob=gem_prob,
            powerup_prob=powerup_prob,
            double_prob=double_prob,
            moving_prob=moving_prob,
            coin_run_len=coin_run_len,
        )

    # ---------------------------------------------------- defensive readers
    # The player is passed in duck-typed; each attribute we depend on is read
    # through a tiny guarded helper so a partial stub (or a None during a state
    # transition) degrades to a sensible default instead of raising.

    @staticmethod
    def _read_distance(player: Any) -> float:
        try:
            d = float(getattr(player, "distance", 0.0))
            return d if d >= 0.0 else 0.0
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _read_speed(player: Any) -> float:
        try:
            return float(getattr(player, "speed", Physics.START_SPEED))
        except (TypeError, ValueError):
            return float(Physics.START_SPEED)

    def _read_effective_speed(self, player: Any) -> float:
        """Best-effort read of the player's *effective* (boosted) speed.

        We prefer the player's own ``effective_speed`` (which folds in the boost
        multiplier), because spacing must account for the *actual* rate the world
        rushes toward the player — a boost that doubles speed must double the gap
        to keep reaction time honest. If the attribute is missing we reconstruct
        it from ``speed * boost_multiplier``, and failing that fall back to the
        director's target speed.
        """
        try:
            eff = getattr(player, "effective_speed", None)
            if eff is not None:
                return max(0.0, float(eff))
        except (TypeError, ValueError):
            pass
        # Reconstruct from parts if the convenience property isn't present.
        speed = self._read_speed(player)
        try:
            boost = float(getattr(player, "boost_multiplier", 1.0))
        except (TypeError, ValueError):
            boost = 1.0
        return max(0.0, speed * max(0.0, boost))

    # ---------------------------------------------------------- introspection
    def snapshot(self) -> Dict[str, Any]:
        """Return the director's slice of the shared HUD snapshot.

        Only ``level`` is contractually required; we keep it minimal so the game
        can merge it without surprises. (``intensity`` and ``speed`` are exposed
        as plain attributes for anyone who wants richer telemetry.)
        """
        return {"level": int(self.level)}

    # Convenience read-outs occasionally handy for debug overlays / tests. These
    # are deliberately derived, not stored, so they can never drift from state.
    @property
    def speed_kmh(self) -> int:
        """The current *target* speed expressed in display km/h.

        Uses the same metres-per-unit convention as the rest of the game so a
        debug HUD reads consistently with the scoring system's speedometer.
        """
        metres_per_sec = self.target_speed * Gameplay.METERS_PER_UNIT
        return int(round(metres_per_sec * 3.6))

    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return (
            f"<DifficultyDirector level={self.level} "
            f"intensity={self.intensity:.2f} target_speed={self.target_speed:.0f}>"
        )


# ---------------------------------------------------------------------------
# Module-level knob-math helpers
# ---------------------------------------------------------------------------
# Kept at module scope (not methods) because they are pure and stateless — easier
# to reason about and to unit-test in isolation.

def _prob(anchor: "tuple[float, float]", t: float) -> float:
    """Interpolate a probability between its (easy, hard) anchor and clamp to [0,1]."""
    return clamp01(lerp(anchor[0], anchor[1], clamp01(t)))


def _normalise_partition(
    obstacle: float,
    coin: float,
    gem: float,
    powerup: float,
    headroom: float = 0.06,
) -> "tuple[float, float, float, float]":
    """Scale a set of partition probabilities so their sum leaves some headroom.

    The spawner draws one uniform roll and walks the cumulative obstacle → coin →
    gem → powerup thresholds; whatever probability mass is left over becomes an
    empty "breather" slot. We guarantee at least ``headroom`` of that breather
    mass (so the sum never reaches 1.0) by proportionally shrinking the four
    probabilities when they would otherwise crowd it out. If the raw sum already
    fits, the values pass through untouched.
    """
    total = obstacle + coin + gem + powerup
    budget = 1.0 - clamp01(headroom)
    if total <= budget or total <= 0.0:
        # Already within budget (or degenerate) — nothing to rescale.
        return (
            clamp01(obstacle),
            clamp01(coin),
            clamp01(gem),
            clamp01(powerup),
        )
    scale = budget / total
    return (
        clamp01(obstacle * scale),
        clamp01(coin * scale),
        clamp01(gem * scale),
        clamp01(powerup * scale),
    )
