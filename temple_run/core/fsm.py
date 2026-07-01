"""
A tiny, explicit finite state machine.

Two flavours are provided:

* :class:`State` / :class:`StateMachine` — a stack-free, single-current-state
  machine used for the top-level game flow (Menu → Playing → Paused → GameOver)
  and for the player's animation/behaviour states (Running → Jumping → …).

* The machine validates transitions against a declared table so an illegal
  transition (e.g. Dead → Jumping) raises loudly in development instead of
  silently corrupting state — the exact class of bug that made the original
  monolith hard to trust.

States get ``enter``/``exit``/``update`` hooks. The machine forwards ``update``
to the active state every frame and hands transitions a small payload so a
state can, say, know the score when GameOver begins.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Hashable, List, Optional, Set


class State:
    """Base class for a state. Override the hooks you care about."""

    name: str = "state"

    def __init__(self, name: Optional[str] = None):
        if name:
            self.name = name
        self.machine: Optional["StateMachine"] = None

    # Lifecycle hooks -------------------------------------------------------
    def on_enter(self, payload: Dict[str, Any]) -> None:  # pragma: no cover - hook
        """Called when this state becomes active."""

    def on_exit(self) -> None:  # pragma: no cover - hook
        """Called when this state is left."""

    def update(self, dt: float) -> None:  # pragma: no cover - hook
        """Called every frame while this state is active."""

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<State {self.name}>"


class StateMachine:
    def __init__(self, name: str = "fsm"):
        self.name = name
        self._states: Dict[Hashable, State] = {}
        self._transitions: Dict[Hashable, Set[Hashable]] = {}
        self._current_key: Optional[Hashable] = None
        self._on_change: List[Callable[[Hashable, Hashable], None]] = []
        self.previous_key: Optional[Hashable] = None

    # -- construction --------------------------------------------------------
    def add_state(self, key: Hashable, state: State) -> "StateMachine":
        state.machine = self
        self._states[key] = state
        self._transitions.setdefault(key, set())
        return self

    def allow(self, from_key: Hashable, *to_keys: Hashable) -> "StateMachine":
        """Declare that ``from_key`` may transition to each of ``to_keys``."""
        self._transitions.setdefault(from_key, set()).update(to_keys)
        return self

    def allow_any(self, to_key: Hashable) -> "StateMachine":
        """Allow every known state to transition into ``to_key`` (e.g. QUIT)."""
        for k in self._states:
            self._transitions.setdefault(k, set()).add(to_key)
        return self

    def on_change(self, cb: Callable[[Hashable, Hashable], None]) -> None:
        self._on_change.append(cb)

    # -- runtime -------------------------------------------------------------
    @property
    def current_key(self) -> Optional[Hashable]:
        return self._current_key

    @property
    def current(self) -> Optional[State]:
        if self._current_key is None:
            return None
        return self._states[self._current_key]

    def is_in(self, key: Hashable) -> bool:
        return self._current_key == key

    def start(self, key: Hashable, payload: Optional[Dict[str, Any]] = None) -> None:
        """Enter the initial state without transition validation."""
        if key not in self._states:
            raise KeyError(f"{self.name}: unknown initial state {key!r}")
        self._current_key = key
        self.current.on_enter(payload or {})

    def can_transition(self, to_key: Hashable) -> bool:
        if self._current_key is None:
            return True
        return to_key in self._transitions.get(self._current_key, set())

    def transition(self, to_key: Hashable, payload: Optional[Dict[str, Any]] = None,
                   *, force: bool = False) -> bool:
        """Move to ``to_key``. Returns True if the transition happened.

        Raises ``ValueError`` if the transition is not declared and ``force`` is
        False — catching illegal flow early.
        """
        if to_key not in self._states:
            raise KeyError(f"{self.name}: unknown state {to_key!r}")
        if to_key == self._current_key:
            return False
        if not force and not self.can_transition(to_key):
            raise ValueError(
                f"{self.name}: illegal transition {self._current_key!r} -> {to_key!r}"
            )
        old = self._current_key
        if self.current is not None:
            self.current.on_exit()
        self.previous_key = old
        self._current_key = to_key
        self.current.on_enter(payload or {})
        for cb in self._on_change:
            cb(old, to_key)
        return True

    def update(self, dt: float) -> None:
        if self.current is not None:
            self.current.update(dt)
