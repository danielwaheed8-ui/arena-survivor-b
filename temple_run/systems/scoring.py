"""
Scoring, combo, and milestone bookkeeping.

The :class:`ScoreSystem` owns every number a player watches climb: the running
score, the coin and gem tallies, the distance travelled (in displayed metres),
and the combo multiplier. It is deliberately a *pure logic* system — it never
touches pygame surfaces and never reads the event queue. It listens to the
gameplay events published by the rest of the engine (coins, gems, near-misses)
and produces two things: authoritative counters, and a handful of derived events
(``SCORE_CHANGED``, ``COMBO_CHANGED``, ``MILESTONE_REACHED``) that the HUD,
audio, particles, achievements and missions all key off.

Design notes / rationale
------------------------
* **Single source of truth.** Collision code decides *what* was collected and
  emits an event with a pre-computed base ``value`` (e.g. a coin's value already
  folds in the powerup coin-multiplier). Scoring decides *how many points* that
  is worth once the combo and score-multiplier are applied. Keeping that split
  clean means no other system has to know the combo rules.

* **Combo as a multiplier, not a counter.** Temple-Run-style combos reward
  *chaining* pickups. Every coin, gem or near-miss collected within
  ``Gameplay.COMBO_WINDOW`` seconds of the previous one bumps the multiplier by
  ``Gameplay.COMBO_STEP`` (capped at ``Gameplay.COMBO_MAX``). Let the window
  lapse and the combo collapses back to a neutral ``1.0``. The multiplier is a
  float so the HUD can show "x2.3" and so distance points can optionally ride it
  too if a designer wants — here we keep distance points un-combo'd so idle
  running never inflates the score, which matches the genre.

* **Score multiplier source is injected, not imported.** A ``x2`` powerup should
  double every point gain, but scoring must not import the powerup module (it is
  a sibling fan-out module that may not exist yet, and the contract forbids it).
  Instead the game hands us a ``() -> int`` callable via
  :meth:`set_score_multiplier_source`; we call it lazily on every award. Default
  is a constant ``1`` so the system is fully functional in isolation.

* **Integer score, float accumulator.** Distance points accrue fractionally
  (``SCORE_PER_METER`` per metre, and a metre is a fraction of a frame's
  travel), so we accumulate in a float and only commit whole points to the
  integer ``score``. This avoids the classic "score never increments because
  each frame adds 0.4 and gets truncated" bug.

* **Never crash the loop.** Event handlers and :meth:`update` swallow bad
  payloads defensively — a malformed event should cost a point, not the frame.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from ..config import Gameplay
from ..core.events import Event, EventBus, EventType
from ..mathutils import clamp


# Distance between score milestones, in displayed metres. Every time the player
# crosses a multiple of this we fire ``MILESTONE_REACHED`` so audio can sting and
# achievements/missions can react.
MILESTONE_INTERVAL_M: int = 500

# The neutral combo value: no chain active, points pass through at face value.
COMBO_BASE: float = 1.0


class ScoreSystem:
    """Owns score, coins, gems, distance and the combo multiplier.

    The system is driven two ways:

    * **Events** (push): coins, gems and near-misses arrive as bus events and
      immediately award points and feed the combo.
    * **:meth:`update`** (pull): called once per frame with the frame's delta
      time and the player's cumulative distance in world units. This awards
      distance points, ages the combo timer, and emits milestone events.

    All public counters are plain attributes so the HUD can read them directly,
    but :meth:`snapshot` is the blessed way to hand them to the shared snapshot.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self.bus: EventBus = event_bus

        # ---- authoritative counters ---------------------------------------
        self.score: int = 0
        self.coins: int = 0
        self.gems: int = 0
        self.distance_m: int = 0

        # ---- combo state ---------------------------------------------------
        # ``combo`` is the live multiplier (>= 1.0). ``combo_active`` is True
        # whenever the multiplier is above the neutral base, i.e. there is an
        # ongoing chain the HUD should highlight.
        self.combo: float = COMBO_BASE
        self.combo_active: bool = False
        # Seconds left before the current chain lapses. Refreshed on every
        # qualifying pickup; when it hits zero the combo decays to the base.
        self._combo_timer: float = 0.0

        # ---- fractional accumulators --------------------------------------
        # Distance points arrive in sub-unit slivers each frame; we bank them
        # here and only push whole points into ``score``.
        self._score_fraction: float = 0.0
        # We track the last distance we were told about so we can award points
        # for the *delta* travelled rather than re-scoring the whole run.
        self._last_distance_units: float = 0.0
        # Highest whole-metre milestone we have already announced.
        self._last_milestone_m: int = 0

        # ---- score multiplier injection -----------------------------------
        # A ``() -> int`` giving the current powerup score multiplier. Defaults
        # to a constant 1 so the system works standalone; the game overrides it
        # with the powerup manager's ``score_mult`` once wired up.
        self._score_mult_source: Callable[[], int] = lambda: 1

        self._subscribe()

    # ------------------------------------------------------------------ setup
    def _subscribe(self) -> None:
        """Wire up to the gameplay events that grant points."""
        self.bus.subscribe(EventType.COIN_COLLECTED, self._on_coin)
        self.bus.subscribe(EventType.GEM_COLLECTED, self._on_gem)
        self.bus.subscribe(EventType.NEAR_MISS, self._on_near_miss)

    def set_score_multiplier_source(self, fn: Optional[Callable[[], int]]) -> None:
        """Install the powerup score-multiplier provider.

        ``fn`` must be a zero-arg callable returning an ``int`` (e.g. ``2`` while
        an ``x2`` powerup is live). Passing ``None`` restores the default of a
        constant ``1``. The callable is invoked on every point award, so it
        always reflects the current powerup state without polling.
        """
        self._score_mult_source = fn if fn is not None else (lambda: 1)

    # ------------------------------------------------------------- multiplier
    def _score_multiplier(self) -> int:
        """Fetch the current powerup score multiplier, defended against errors.

        A misbehaving source (raising, or returning something non-numeric) must
        never break scoring, so we fall back to ``1`` on any problem.
        """
        try:
            mult = int(self._score_mult_source())
        except Exception:
            return 1
        # A zero or negative multiplier would silently swallow all points; treat
        # anything below 1 as the neutral multiplier.
        return mult if mult >= 1 else 1

    # ------------------------------------------------------------------ combo
    def _bump_combo(self) -> None:
        """Extend/raise the combo for a freshly chained pickup or near-miss.

        Called for every coin, gem and near-miss. If the previous link is still
        within the combo window the multiplier steps up; either way the window
        is refreshed so the next pickup has a full ``COMBO_WINDOW`` to arrive.
        """
        was_active = self.combo_active
        previous = self.combo

        if self._combo_timer > 0.0:
            # The chain is alive: raise the multiplier, capped at the maximum.
            self.combo = min(self.combo + Gameplay.COMBO_STEP, Gameplay.COMBO_MAX)
        else:
            # Starting a fresh chain. The first pickup after a lapse already
            # counts as one link, so we open at base + one step.
            self.combo = min(COMBO_BASE + Gameplay.COMBO_STEP, Gameplay.COMBO_MAX)

        # Refresh the decay window.
        self._combo_timer = Gameplay.COMBO_WINDOW
        self.combo_active = self.combo > COMBO_BASE

        if self.combo != previous or self.combo_active != was_active:
            self._emit_combo_changed()

    def _tick_combo(self, dt: float) -> None:
        """Age the combo window; collapse the multiplier when it lapses."""
        if self._combo_timer <= 0.0:
            return
        self._combo_timer -= dt
        if self._combo_timer <= 0.0:
            self._combo_timer = 0.0
            self._collapse_combo()

    def _collapse_combo(self) -> None:
        """Reset the combo to the neutral base and notify listeners."""
        if self.combo != COMBO_BASE or self.combo_active:
            self.combo = COMBO_BASE
            self.combo_active = False
            self._emit_combo_changed()

    def _emit_combo_changed(self) -> None:
        """Publish the current combo state for the HUD/audio to react to."""
        self.bus.emit(
            EventType.COMBO_CHANGED,
            combo=self.combo,
            active=self.combo_active,
        )

    # ------------------------------------------------------------- awarding
    def _award(self, base_points: float) -> None:
        """Add ``base_points`` (already combo-scaled if applicable) to the score.

        The powerup score multiplier is applied here, and the running fractional
        remainder is banked so no fractional points are lost between frames.
        Emits ``SCORE_CHANGED`` only when the whole-number score actually moves.
        """
        if base_points <= 0.0:
            return

        gained = base_points * self._score_multiplier()
        self._score_fraction += gained

        # Commit whole points; keep the remainder for next time.
        whole = int(self._score_fraction)
        if whole > 0:
            self._score_fraction -= whole
            self.score += whole
            self._emit_score_changed()

    def _emit_score_changed(self) -> None:
        """Publish the new integer score."""
        self.bus.emit(EventType.SCORE_CHANGED, score=self.score)

    # --------------------------------------------------------- event handlers
    def _on_coin(self, event: Event) -> None:
        """Handle ``COIN_COLLECTED``: +1 coin, combo-scaled points, bump combo.

        ``value`` already includes the powerup coin-multiplier (the collision
        code folds that in), so we do *not* re-apply coin multipliers here — we
        only apply the combo and the score multiplier.
        """
        value = self._event_value(event, default=Gameplay.COIN_VALUE)
        self.coins += 1
        # Combo is bumped *before* scoring so this very coin rides the new,
        # higher multiplier — chaining should feel immediately rewarding.
        self._bump_combo()
        self._award(value * self.combo)

    def _on_gem(self, event: Event) -> None:
        """Handle ``GEM_COLLECTED``: +1 gem, combo-scaled points, bump combo."""
        value = self._event_value(event, default=Gameplay.GEM_VALUE)
        self.gems += 1
        self._bump_combo()
        self._award(value * self.combo)

    def _on_near_miss(self, event: Event) -> None:
        """Handle ``NEAR_MISS``: fixed bonus, bump combo.

        A near miss is a skill flourish — it keeps a combo alive between pickups
        and grants a flat bonus rather than a per-item value.
        """
        self._bump_combo()
        self._award(Gameplay.NEAR_MISS_BONUS * self.combo)

    @staticmethod
    def _event_value(event: Event, default: int) -> float:
        """Read a numeric ``value`` from an event payload, tolerantly.

        Bad or missing payloads fall back to the sensible ``default`` so a
        malformed event never zeroes out a pickup's worth.
        """
        try:
            raw = event.get("value", default)
            value = float(raw)
        except (TypeError, ValueError):
            return float(default)
        # Guard against negative/NaN nonsense sneaking in from a bad producer.
        if value != value or value < 0.0:  # value != value catches NaN
            return float(default)
        return value

    # ------------------------------------------------------------------ frame
    def update(self, dt: float, distance_units: float) -> None:
        """Advance scoring by one frame.

        Parameters
        ----------
        dt:
            Frame delta-time in seconds. Used only to age the combo window.
        distance_units:
            The player's *cumulative* distance in world units (``player.distance``).
            We award distance points for the delta since the last call, convert
            the running total to displayed metres, and fire milestone events.

        This method is deliberately side-effect-light beyond the counters and
        events it is documented to touch, and it must never raise: it is called
        from the game's hot update path every frame.
        """
        # --- combo ageing ---------------------------------------------------
        if dt > 0.0:
            self._tick_combo(dt)

        # --- distance -> points --------------------------------------------
        # Award points for ground newly covered. On the very first call (or
        # after a reset) ``_last_distance_units`` is the starting distance, so
        # no spurious catch-up points are granted.
        delta_units = distance_units - self._last_distance_units
        if delta_units < 0.0:
            # Distance should only ever grow; if it somehow rewound (a reset the
            # scoring system missed) just resync without awarding negatives.
            delta_units = 0.0
        self._last_distance_units = distance_units

        if delta_units > 0.0:
            delta_metres = delta_units * Gameplay.METERS_PER_UNIT
            # Distance points are intentionally *not* combo-scaled: idle running
            # should not inflate the combo-reward economy.
            self._award(delta_metres * Gameplay.SCORE_PER_METER)

        # --- displayed distance & milestones -------------------------------
        total_metres = distance_units * Gameplay.METERS_PER_UNIT
        new_distance_m = int(total_metres)
        if new_distance_m != self.distance_m:
            self.distance_m = new_distance_m

        self._check_milestones(new_distance_m)

    def _check_milestones(self, distance_m: int) -> None:
        """Fire ``MILESTONE_REACHED`` for each 500 m threshold newly crossed.

        A single frame can, in principle, leap several thresholds if the player
        is very fast and the frame is long, so we announce every one we passed
        rather than only the nearest — no milestone is ever skipped.
        """
        if distance_m < self._last_milestone_m + MILESTONE_INTERVAL_M:
            return
        # Highest milestone multiple at or below the current distance.
        newest = (distance_m // MILESTONE_INTERVAL_M) * MILESTONE_INTERVAL_M
        marker = self._last_milestone_m + MILESTONE_INTERVAL_M
        while marker <= newest:
            self.bus.emit(EventType.MILESTONE_REACHED, meters=marker)
            marker += MILESTONE_INTERVAL_M
        self._last_milestone_m = newest

    # ------------------------------------------------------------------ state
    def reset(self) -> None:
        """Clear all counters and combo state for a fresh run.

        Emits ``SCORE_CHANGED`` and ``COMBO_CHANGED`` so any HUD bound to the
        bus snaps back to zero immediately, without waiting for the first frame.
        """
        had_score = self.score != 0
        had_combo = self.combo != COMBO_BASE or self.combo_active

        self.score = 0
        self.coins = 0
        self.gems = 0
        self.distance_m = 0

        self.combo = COMBO_BASE
        self.combo_active = False
        self._combo_timer = 0.0

        self._score_fraction = 0.0
        self._last_distance_units = 0.0
        self._last_milestone_m = 0

        if had_score:
            self._emit_score_changed()
        if had_combo:
            self._emit_combo_changed()

    def snapshot(self) -> Dict[str, Any]:
        """Return this system's slice of the shared HUD snapshot.

        The keys line up with the contract's snapshot schema so the game can
        ``snapshot.update(score_system.snapshot())`` each frame.
        """
        return {
            "score": self.score,
            "coins": self.coins,
            "gems": self.gems,
            "distance_m": self.distance_m,
            # Round for a tidy HUD read-out ("x2.3") without leaking float dust.
            "combo": round(clamp(self.combo, COMBO_BASE, Gameplay.COMBO_MAX), 2),
            "combo_active": self.combo_active,
        }
