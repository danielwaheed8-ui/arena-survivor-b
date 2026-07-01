"""
A small, synchronous publish/subscribe EventBus.

Systems communicate by publishing typed events rather than calling each other
directly. The scoring system doesn't need a reference to the audio engine — it
just publishes ``COIN_COLLECTED`` and whoever cares reacts. This keeps the
dependency graph shallow and makes it trivial to add new reactions (a new
achievement, a new particle burst) without editing existing code.

Delivery is synchronous and immediate: ``publish`` runs every subscriber before
returning. That is exactly what a single-threaded game loop wants — no hidden
ordering surprises, no async races. A tiny deferred queue is provided for the
rare case where you want to publish an event from *inside* a handler without
recursing.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Deque, Dict, List


class EventType(Enum):
    # --- flow ---------------------------------------------------------------
    GAME_START = auto()
    GAME_OVER = auto()
    GAME_RESTART = auto()
    PAUSE = auto()
    RESUME = auto()
    STATE_CHANGED = auto()
    QUIT = auto()

    # --- player -------------------------------------------------------------
    PLAYER_JUMP = auto()
    PLAYER_SLIDE = auto()
    PLAYER_LANE_CHANGE = auto()
    PLAYER_LAND = auto()
    PLAYER_STUMBLE = auto()
    PLAYER_DIED = auto()

    # --- pickups / hazards --------------------------------------------------
    COIN_COLLECTED = auto()
    GEM_COLLECTED = auto()
    POWERUP_COLLECTED = auto()
    POWERUP_STARTED = auto()
    POWERUP_ENDED = auto()
    OBSTACLE_HIT = auto()
    NEAR_MISS = auto()

    # --- meta / progression -------------------------------------------------
    SCORE_CHANGED = auto()
    COMBO_CHANGED = auto()
    MILESTONE_REACHED = auto()
    BIOME_CHANGED = auto()
    ACHIEVEMENT_UNLOCKED = auto()
    MISSION_PROGRESS = auto()
    MISSION_COMPLETED = auto()
    SHOP_PURCHASE = auto()
    UPGRADE_PURCHASED = auto()

    # --- ui -----------------------------------------------------------------
    UI_BUTTON = auto()
    TOAST = auto()
    SCREEN_SHAKE = auto()


@dataclass
class Event:
    """An event carries a type and an arbitrary data payload."""

    type: EventType
    data: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


Listener = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._subs: Dict[EventType, List[Listener]] = {}
        self._any: List[Listener] = []
        self._deferred: Deque[Event] = deque()
        self._dispatching = False

    # -- subscription --------------------------------------------------------
    def subscribe(self, event_type: EventType, listener: Listener) -> Callable[[], None]:
        """Register ``listener`` for ``event_type``. Returns an unsubscribe fn."""
        self._subs.setdefault(event_type, []).append(listener)

        def _off() -> None:
            self.unsubscribe(event_type, listener)

        return _off

    def subscribe_all(self, listener: Listener) -> Callable[[], None]:
        """Register a listener that receives *every* event (useful for logging)."""
        self._any.append(listener)

        def _off() -> None:
            if listener in self._any:
                self._any.remove(listener)

        return _off

    def unsubscribe(self, event_type: EventType, listener: Listener) -> None:
        lst = self._subs.get(event_type)
        if lst and listener in lst:
            lst.remove(listener)

    def clear(self) -> None:
        self._subs.clear()
        self._any.clear()
        self._deferred.clear()

    # -- publishing ----------------------------------------------------------
    def publish(self, event: Event) -> None:
        """Deliver ``event`` immediately to all matching subscribers.

        Handlers are copied before iteration so a handler may safely
        subscribe/unsubscribe during dispatch without mutating the live list.
        """
        self._dispatching = True
        try:
            for listener in list(self._subs.get(event.type, ())):
                listener(event)
            for listener in list(self._any):
                listener(event)
        finally:
            self._dispatching = False
        # Drain anything queued during dispatch.
        self._flush_deferred()

    def emit(self, event_type: EventType, **data: Any) -> None:
        """Convenience: ``bus.emit(EventType.TOAST, text="hi")``."""
        self.publish(Event(event_type, dict(data)))

    def defer(self, event: Event) -> None:
        """Queue an event to be delivered after the current dispatch finishes."""
        self._deferred.append(event)
        if not self._dispatching:
            self._flush_deferred()

    def _flush_deferred(self) -> None:
        while self._deferred:
            self.publish(self._deferred.popleft())
