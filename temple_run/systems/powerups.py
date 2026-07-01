"""
Active-powerup lifecycle and effect aggregation.

The :class:`PowerupManager` is the single authority on *which* powerups are
currently in effect and *how much time* each has left. It is a pure-logic system:
it never touches a pygame surface and never reads the event queue. It listens for
``POWERUP_COLLECTED`` (published by the collision code when the player runs into a
powerup pickup) and turns that pickup into a live, ticking effect. Every other
system asks *this* object the questions it cares about:

* collision / player  -> :meth:`is_invincible`, :meth:`speed_mult`
* the coin magnet      -> :meth:`magnet_active`
* scoring              -> :meth:`score_mult` (wired via the injected multiplier
                          source in :class:`ScoreSystem`)
* collision coin award -> :meth:`coin_mult`
* the HUD              -> :meth:`active_list` (feeds the ``powerups`` snapshot key)

Design notes / rationale
------------------------
* **One effect per powerup key, refreshable.** Temple-Run powerups do not stack a
  second copy of themselves — grabbing a magnet while a magnet is already running
  should *extend* the magnet, not run two overlapping magnets. So active effects
  are keyed by their powerup key and re-collecting simply resets the remaining
  timer to the full duration. We still fire ``POWERUP_STARTED`` only on the first
  activation of an effect that was not already running, so audio/particles do not
  re-sting on a mere refresh; a refresh is signalled by re-emitting nothing (the
  HUD bar simply refills because ``remaining`` jumps back up).

* **Effects of *different* keys stack multiplicatively.** A ``boost`` (speed
  x1.6) and an ``x2`` (score/coins x2) can be active simultaneously, and their
  effects compose: speed is the *product* of every active ``speed_mult`` and the
  score/coin multipliers are the *product* of every active integer multiplier.
  Invincibility and magnet are booleans — *any* active effect that grants them is
  enough. This "aggregate over all active" model means the game asks one question
  and gets the correct combined answer, with no special-casing per powerup.

* **Catalogue is imported, behaviour is derived.** All the tunables (durations,
  colours, symbols, effect flags) live in
  :mod:`temple_run.entities.powerup_types` so the pickup entity and this manager
  can never disagree. We only read that catalogue; we never redefine it. Unknown
  keys are ignored defensively so a stray/garbage event can never crash the run.

* **Deterministic expiry ordering.** :meth:`update` decays every timer by ``dt``
  and collects the ones that hit zero into a list *before* publishing any
  ``POWERUP_ENDED`` events, so a handler reacting to one expiry (e.g. re-querying
  :meth:`speed_mult`) always sees a consistent snapshot of what is still active.

* **Never crash the loop.** The collected-event handler and :meth:`update`
  swallow bad payloads: a malformed powerup event costs a powerup, not the frame.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..entities.powerup_types import POWERUPS, PowerupType, get_powerup


class _ActiveEffect:
    """A single powerup currently in effect, with its countdown timer.

    This is an intentionally tiny mutable record rather than a frozen dataclass:
    the only thing that changes over its lifetime is ``remaining``, which we
    decrement every frame and reset to ``duration`` on a refresh. Everything else
    is copied from the immutable :class:`PowerupType` so we never have to look the
    catalogue entry up again on the hot path.
    """

    __slots__ = ("kind", "remaining", "duration")

    def __init__(self, kind: PowerupType) -> None:
        self.kind: PowerupType = kind
        # ``duration`` is cached separately so the HUD can render a fill ratio
        # (remaining / duration) even after a refresh changed the effective
        # window; here they are always equal, but keeping the field explicit
        # documents the intent and future-proofs per-powerup duration bonuses.
        self.duration: float = float(kind.duration)
        self.remaining: float = float(kind.duration)

    def refresh(self) -> None:
        """Top the timer back up to a full duration (re-collect while active)."""
        self.remaining = self.duration

    @property
    def expired(self) -> bool:
        return self.remaining <= 0.0


class PowerupManager:
    """Owns the set of active powerup effects and aggregates their influence.

    The manager is fully functional in isolation: construct it with an
    :class:`EventBus`, publish ``POWERUP_COLLECTED`` events at it, tick it with
    :meth:`update`, and query the effect accessors. It subscribes on construction
    and can be torn down with :meth:`close` (though most games simply drop it).
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._bus: EventBus = event_bus

        # Active effects keyed by powerup key ("magnet", "shield", ...). Using a
        # dict (rather than a list) makes "is this powerup already running?" and
        # "refresh this powerup" O(1), which is exactly the two operations the
        # collect handler needs. Insertion order is preserved by dict, so
        # :meth:`active_list` renders the HUD icons in the order they were picked
        # up — a nice, stable UX detail.
        self._active: Dict[str, _ActiveEffect] = {}

        # Keep the unsubscribe handle so :meth:`close` can detach cleanly. The
        # EventBus hands back a zero-arg callable from ``subscribe``.
        self._unsub: Callable[[], None] = self._bus.subscribe(
            EventType.POWERUP_COLLECTED, self._on_collected
        )

    # ------------------------------------------------------------------ events
    def _on_collected(self, event: Event) -> None:
        """React to a ``POWERUP_COLLECTED`` event by starting/refreshing an effect.

        Payload schema (per the systems contract): ``{entity, power: str}`` where
        ``power`` is a key in ``POWERUPS``. We only need ``power``. Anything we do
        not recognise is ignored rather than raised — a bad event must not end the
        run.
        """
        try:
            key = event.get("power")
            if not key or key not in POWERUPS:
                return
            self.activate(key)
        except Exception as exc:  # pragma: no cover - defensive belt-and-braces
            # A powerup failing to start is a cosmetic loss, never a crash.
            print(f"[powerups] failed to activate from event: {exc}")

    def activate(self, key: str) -> None:
        """Start the powerup ``key`` (or refresh it if already running).

        This is also usable directly (e.g. from a shop "head start" that grants a
        free shield, or from tests) without going through the event bus. On a
        genuinely new activation we publish ``POWERUP_STARTED``; a refresh of an
        already-active effect is silent so audio/particles do not double-fire.
        """
        if key not in POWERUPS:
            return  # Unknown powerup key — ignore defensively.

        existing = self._active.get(key)
        if existing is not None:
            # Already running: extend its life, but do not re-announce it.
            existing.refresh()
            return

        kind = get_powerup(key)
        self._active[key] = _ActiveEffect(kind)
        # Announce the fresh start so audio can sting, particles can burst, and
        # achievements/missions can count "powerups used". We forward the
        # ``PowerupType`` so listeners avoid a second catalogue lookup.
        self._bus.publish(
            Event(EventType.POWERUP_STARTED, {"power": key, "type": kind})
        )

    # ------------------------------------------------------------------ update
    def update(self, dt: float) -> None:
        """Decay every active timer by ``dt`` and retire the ones that expire.

        We snapshot the expired effects first and only *then* publish
        ``POWERUP_ENDED`` for each, so any handler that re-queries this manager
        during an expiry sees a coherent, already-pruned set of active effects.
        """
        if not self._active:
            return
        try:
            step = float(dt)
        except (TypeError, ValueError):
            return
        if step <= 0.0:
            return

        expired: List[_ActiveEffect] = []
        for effect in self._active.values():
            effect.remaining -= step
            if effect.expired:
                expired.append(effect)

        if not expired:
            return

        # Remove all expired effects before announcing any of them so the world
        # is consistent by the time listeners react.
        for effect in expired:
            self._active.pop(effect.kind.key, None)

        for effect in expired:
            self._bus.publish(
                Event(
                    EventType.POWERUP_ENDED,
                    {"power": effect.kind.key, "type": effect.kind},
                )
            )

    # --------------------------------------------------------------- accessors
    def is_active(self, key: str) -> bool:
        """True if the powerup ``key`` is currently in effect."""
        return key in self._active

    def is_invincible(self) -> bool:
        """True if *any* active powerup grants invincibility (shield or boost)."""
        return any(e.kind.invincible for e in self._active.values())

    def magnet_active(self) -> bool:
        """True if *any* active powerup pulls coins toward the player."""
        return any(e.kind.magnet for e in self._active.values())

    def speed_mult(self) -> float:
        """Combined forward-speed multiplier: the product of all active effects.

        With nothing active this is a neutral ``1.0``. A lone ``boost`` yields
        ``1.6``; a (hypothetical) second speed powerup would compound on top.
        The engine multiplies the player's base speed by this value, so it must
        never be zero or negative — every catalogue ``speed_mult`` is >= 1.0, and
        an empty product is 1.0, so this is safe by construction.
        """
        mult = 1.0
        for effect in self._active.values():
            mult *= effect.kind.speed_mult
        return mult

    def score_mult(self) -> int:
        """Combined score multiplier: the product of all active integer multipliers.

        Returns ``1`` when nothing is active. This is the value the scoring
        system multiplies point gains by (via its injected multiplier source),
        so it is deliberately an ``int`` — score should stay in whole numbers.
        """
        mult = 1
        for effect in self._active.values():
            mult *= effect.kind.score_mult
        return mult

    def coin_mult(self) -> int:
        """Combined coin multiplier: the product of all active coin multipliers.

        Collision folds this into a coin's ``value`` at pickup time, so a coin
        collected under an active ``x2`` is worth two coins toward both the score
        and the coin tally. Returns ``1`` with nothing active.
        """
        mult = 1
        for effect in self._active.values():
            mult *= effect.kind.coin_mult
        return mult

    # ------------------------------------------------------------------ queries
    def remaining(self, key: str) -> float:
        """Seconds left on powerup ``key`` (``0.0`` if it is not active)."""
        effect = self._active.get(key)
        return effect.remaining if effect is not None else 0.0

    def any_active(self) -> bool:
        """True if at least one powerup is currently running."""
        return bool(self._active)

    def active_keys(self) -> List[str]:
        """Keys of the currently active powerups, in pickup order."""
        return list(self._active.keys())

    def active_list(self) -> List[Dict[str, object]]:
        """Build the ``powerups`` entries for the shared HUD snapshot.

        Each entry matches the contract schema exactly::

            {"key", "name", "color", "symbol", "remaining", "duration"}

        The HUD renders one timer bar per entry, using ``remaining / duration``
        as the fill ratio and ``color``/``symbol`` for the icon. Entries appear
        in pickup order (dict insertion order) so newly grabbed powerups slot in
        at the end rather than reshuffling the whole strip.
        """
        entries: List[Dict[str, object]] = []
        for effect in self._active.values():
            kind = effect.kind
            # Clamp the reported remaining to >= 0 so a frame that overshot the
            # expiry (large dt) never hands the HUD a negative bar length before
            # the effect is pruned on the same/next update.
            remaining = effect.remaining if effect.remaining > 0.0 else 0.0
            entries.append(
                {
                    "key": kind.key,
                    "name": kind.name,
                    "color": kind.color,
                    "symbol": kind.symbol,
                    "remaining": remaining,
                    "duration": effect.duration,
                }
            )
        return entries

    # ------------------------------------------------------------------ lifecycle
    def reset(self) -> None:
        """Clear all active powerups (called on run start / restart).

        We do *not* publish ``POWERUP_ENDED`` for effects cleared this way: a
        reset is a hard scene boundary, not a natural expiry, and firing end
        events here would let stale run-scoped listeners (achievements, missions)
        double-count. Anything that needs to react to a run boundary should key
        off ``GAME_START`` / ``GAME_OVER`` instead.
        """
        self._active.clear()

    def close(self) -> None:
        """Detach from the event bus. Optional; most games just drop the manager."""
        try:
            self._unsub()
        except Exception:  # pragma: no cover - unsubscribe is best-effort
            pass

    # ------------------------------------------------------------------ dunder
    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        if not self._active:
            return "<PowerupManager idle>"
        parts = ", ".join(
            f"{k}={e.remaining:.1f}s" for k, e in self._active.items()
        )
        return f"<PowerupManager {parts}>"
