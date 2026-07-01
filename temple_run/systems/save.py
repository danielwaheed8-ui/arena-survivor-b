"""
Persistent save data — the game's long-term memory.

The :class:`SaveManager` owns the single JSON blob that survives between play
sessions: lifetime totals (coins, gems, distance), the high score, the player's
spendable coin balance, and the opaque sub-dictionaries that other meta-systems
(achievements, missions, shop, settings) stash their own state into. Keeping all
of this behind one object means there is exactly one place that touches the disk,
one schema to reason about, and one atomic write path.

Design goals and rationale
--------------------------

* **Never crash the game.** Save/load happens on the edges of a play session,
  often while the render loop is still spinning. A corrupt file, a full disk, a
  permissions error, or a half-written blob from a previous crash must all be
  *survivable*. Every I/O boundary is wrapped in ``try/except`` and, on failure,
  logs a line to stdout and carries on with in-memory defaults. Losing a save is
  regrettable; a traceback that kills the process mid-run is unacceptable.

* **Atomic writes.** A naive ``open(path, "w")`` that is interrupted (power loss,
  ``kill -9``) leaves a truncated, unparseable file — the worst outcome, because
  the *next* load then throws away otherwise-good progress. Instead we serialise
  to a sibling temp file, ``flush`` + ``fsync`` it, then ``os.replace`` it over
  the real path. ``os.replace`` is atomic on POSIX and Windows, so a reader ever
  only sees the old file or the fully-written new one — never a torn write.

* **Forward/backward tolerant schema.** ``load`` merges the on-disk dict *onto*
  a fresh copy of the defaults rather than replacing them. New keys added in a
  later build appear with sane defaults even when reading an old save; unknown
  keys from a newer save are preserved untouched. Section dictionaries
  (``unlocked``, ``upgrades``, ...) are always present so callers can index them
  without defensive checks.

* **One writer, many sections.** Achievements/missions/shop don't get their own
  files; they call :meth:`get_section` to obtain a live, auto-created dict inside
  ``self.data`` and mutate it, then ask the manager to :meth:`save`. This keeps a
  single source of truth and a single fsync.

The public surface is deliberately small: construct, :meth:`load`, mutate via the
typed helpers or sections, :meth:`save`. An optional :class:`EventBus` lets the
manager auto-record a run summary when it sees ``GAME_OVER``.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from typing import Any, Callable, Dict, Optional

from ..config import Config

# The core event bus is a "Core API" the contract allows us to import. We keep
# the import optional at the *type* level (the ctor accepts ``None``) but the
# module import itself is cheap and cycle-free, so importing it eagerly is fine.
from ..core.events import Event, EventType

__all__ = ["SaveManager", "DEFAULT_SAVE"]


# ---------------------------------------------------------------------------
# Default schema
# ---------------------------------------------------------------------------
# This is the canonical shape of a save file. ``load`` deep-copies it and merges
# the on-disk data over the top, so every one of these keys is guaranteed to be
# present (with the right type) after a load, even from an ancient or empty file.
#
# Scalar keys are lifetime aggregates or single values; the trailing dict-valued
# keys are namespaced "sections" owned by other systems (see :meth:`get_section`).
DEFAULT_SAVE: Dict[str, Any] = {
    # -- headline progression ------------------------------------------------
    "high_score": 0,          # best single-run score ever
    "best_distance_m": 0,     # furthest single run, in displayed metres
    # -- lifetime totals -----------------------------------------------------
    "total_coins": 0,         # every coin ever picked up
    "total_gems": 0,          # every gem ever picked up
    "total_distance_m": 0,    # cumulative metres across all runs
    "total_runs": 0,          # number of completed runs
    # -- spendable currency --------------------------------------------------
    "coins_balance": 0,       # coins available to spend in the shop
    # -- system-owned sections (auto-created, opaque to us) ------------------
    "unlocked": {},           # shop: one-time unlocks (skins/characters)
    "upgrades": {},           # shop: multi-level upgrade levels
    "achievements": {},       # achievement unlock flags + counters
    "missions": {},           # active missions + progress
    "stats": {},              # misc lifetime counters (near-misses, jumps, ...)
    "settings": {},           # optional mirror of user settings
}

# Keys whose values are namespaced sub-dictionaries. Used to normalise types on
# load (a corrupt file might have, say, a string where a dict belongs).
_SECTION_KEYS = ("unlocked", "upgrades", "achievements", "missions", "stats", "settings")


class SaveManager:
    """Owns and persists the game's cross-session save data.

    Typical use::

        save = SaveManager(event_bus=bus)   # loads immediately
        save.add("coins_balance", 50)
        save.record_run(score=1200, coins=40, gems=2, distance_m=880)
        save.save()

    All mutating helpers operate on the in-memory :attr:`data` dict; nothing
    touches the disk until :meth:`save` is called (or ``GAME_OVER`` fires, if an
    event bus was supplied).
    """

    def __init__(self, path: str = Config.SAVE_FILE, event_bus: Optional[Any] = None) -> None:
        """Create the manager and immediately :meth:`load` from ``path``.

        Parameters
        ----------
        path:
            Filesystem location of the JSON save. Defaults to
            ``Config.SAVE_FILE`` (resolved relative to the working directory).
        event_bus:
            Optional :class:`~temple_run.core.events.EventBus`. If given, the
            manager subscribes to ``GAME_OVER`` and persists a run summary
            automatically, so callers that already emit that event get free
            checkpointing. May be ``None`` for a purely manual workflow.
        """
        self.path: str = path
        self.event_bus = event_bus
        # Start from a pristine copy of the defaults so ``data`` is usable even
        # before (or instead of) a successful load.
        self.data: Dict[str, Any] = copy.deepcopy(DEFAULT_SAVE)
        # Unsubscribe handle for our optional GAME_OVER listener, so a caller can
        # tear us down cleanly if it ever needs to.
        self._unsubscribe: Optional[Callable[[], None]] = None

        # Pull whatever is on disk into ``self.data``.
        self.load()

        # Wire up automatic run persistence if we were handed a bus.
        if event_bus is not None:
            try:
                self._unsubscribe = event_bus.subscribe(EventType.GAME_OVER, self._on_game_over)
            except Exception as exc:  # pragma: no cover - defensive
                # A malformed bus must not prevent the manager from working.
                self._log(f"could not subscribe to GAME_OVER: {exc!r}")

    # ------------------------------------------------------------------ #
    # Disk I/O
    # ------------------------------------------------------------------ #
    def load(self) -> Dict[str, Any]:
        """Load the save file, tolerating a missing or corrupt file.

        The on-disk dictionary is *merged onto* a fresh copy of
        :data:`DEFAULT_SAVE`, so the result always has the full schema. If the
        file is absent, unreadable, or not valid JSON, we quietly fall back to
        defaults (and leave the possibly-broken file in place for inspection;
        the next :meth:`save` will overwrite it atomically).

        Returns
        -------
        dict
            The freshly populated :attr:`data` dictionary.
        """
        # Always begin from clean defaults; a failed/partial load then leaves us
        # in a well-defined state rather than a half-mutated one.
        merged: Dict[str, Any] = copy.deepcopy(DEFAULT_SAVE)

        raw: Optional[str] = None
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as fh:
                    raw = fh.read()
        except OSError as exc:
            self._log(f"could not read save file {self.path!r}: {exc!r} — using defaults")
            raw = None

        if raw:
            try:
                loaded = json.loads(raw)
            except (json.JSONDecodeError, ValueError) as exc:
                self._log(f"save file {self.path!r} is corrupt ({exc!r}) — using defaults")
                loaded = None

            if isinstance(loaded, dict):
                self._merge_into(merged, loaded)
            elif loaded is not None:
                # A valid JSON file that isn't an object (e.g. a bare list/number)
                # is meaningless as a save — ignore it and keep defaults.
                self._log(f"save file {self.path!r} has unexpected top-level type — using defaults")

        self.data = merged
        # Normalise types (guarantee the section keys really are dicts, etc.).
        self._coerce_schema()
        return self.data

    def save(self) -> bool:
        """Persist :attr:`data` to disk atomically.

        We serialise to a temp file in the *same directory* as the target (so
        ``os.replace`` stays on one filesystem and remains atomic), fsync it to
        push it past the OS write cache, then atomically rename it over the real
        file. Any failure is logged and swallowed — saving must never take the
        game down.

        Returns
        -------
        bool
            ``True`` on a successful write, ``False`` if anything went wrong.
        """
        # Resolve the directory the save lives in; empty string means CWD.
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            self._log(f"could not create save directory {directory!r}: {exc!r}")
            return False

        # Serialise first: if the data somehow isn't JSON-encodable we want to
        # fail *before* we create any temp files.
        try:
            payload = json.dumps(self.data, indent=2, sort_keys=True)
        except (TypeError, ValueError) as exc:
            self._log(f"save data is not JSON-serialisable: {exc!r}")
            return False

        tmp_path: Optional[str] = None
        try:
            # ``NamedTemporaryFile`` with delete=False lets us fsync + close it
            # and then os.replace it. Keeping it in ``directory`` guarantees the
            # rename is same-filesystem and therefore atomic.
            fd, tmp_path = tempfile.mkstemp(
                prefix=".save-", suffix=".tmp", dir=directory
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                # Force the bytes to stable storage before the rename so a crash
                # right after replace() can't resurrect an empty temp file.
                os.fsync(fh.fileno())

            # Atomic swap: readers see either the old file or the complete new one.
            os.replace(tmp_path, self.path)
            tmp_path = None  # replaced successfully; nothing to clean up
            return True
        except OSError as exc:
            self._log(f"could not write save file {self.path!r}: {exc!r}")
            return False
        finally:
            # If we bailed after creating the temp file but before the rename,
            # remove the orphan so we don't litter the directory.
            if tmp_path is not None and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def reset(self) -> Dict[str, Any]:
        """Wipe all progress back to defaults and persist immediately.

        Returns the fresh :attr:`data` dictionary. Used by a "delete save data"
        menu action.
        """
        self.data = copy.deepcopy(DEFAULT_SAVE)
        self.save()
        return self.data

    # ------------------------------------------------------------------ #
    # Typed accessors
    # ------------------------------------------------------------------ #
    def get(self, key: str, default: Any = None) -> Any:
        """Read a top-level value, falling back to ``default`` if absent."""
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Write a top-level value. Does not persist — call :meth:`save`."""
        self.data[key] = value

    def add(self, key: str, amount: float) -> float:
        """Increment a numeric top-level counter by ``amount`` and return it.

        Missing keys are treated as ``0``. Non-numeric existing values are
        overwritten rather than raising, so a corrupt entry self-heals. The
        result is coerced back to ``int`` when both operands are integral so we
        don't accidentally turn coin counts into floats.
        """
        current = self.data.get(key, 0)
        if not isinstance(current, (int, float)) or isinstance(current, bool):
            # ``bool`` is an ``int`` subclass; treat it (and anything odd) as 0.
            current = 0
        new_value = current + amount
        # Keep integer counters integral for clean JSON and display.
        if isinstance(current, int) and float(amount).is_integer():
            new_value = int(new_value)
        self.data[key] = new_value
        return new_value

    def get_section(self, name: str) -> Dict[str, Any]:
        """Return the named sub-dictionary, creating it if necessary.

        Other systems call this to obtain a live, mutable slice of the save they
        own outright (e.g. ``save.get_section("upgrades")``). The returned dict
        *is* the stored object — mutating it mutates the save in place — so a
        subsequent :meth:`save` persists the changes.
        """
        section = self.data.get(name)
        if not isinstance(section, dict):
            section = {}
            self.data[name] = section
        return section

    # ------------------------------------------------------------------ #
    # Run bookkeeping
    # ------------------------------------------------------------------ #
    def record_run(self, score: int, coins: int, gems: int, distance_m: int) -> None:
        """Fold a finished run's results into the lifetime totals and highs.

        Updates cumulative counters (coins/gems/distance/runs), bumps the
        spendable ``coins_balance`` by the coins earned, and advances
        ``high_score`` / ``best_distance_m`` if this run beat them. Callers are
        expected to :meth:`save` afterwards (the automatic ``GAME_OVER`` path
        does this for them).

        All inputs are defensively coerced to non-negative integers so a bad
        payload can't corrupt the totals.
        """
        score = self._as_nonneg_int(score)
        coins = self._as_nonneg_int(coins)
        gems = self._as_nonneg_int(gems)
        distance_m = self._as_nonneg_int(distance_m)

        # Lifetime aggregates.
        self.add("total_coins", coins)
        self.add("total_gems", gems)
        self.add("total_distance_m", distance_m)
        self.add("total_runs", 1)

        # Coins earned this run become spendable currency.
        self.add("coins_balance", coins)

        # Personal bests (only ever move upward).
        if score > int(self.data.get("high_score", 0) or 0):
            self.data["high_score"] = score
        if distance_m > int(self.data.get("best_distance_m", 0) or 0):
            self.data["best_distance_m"] = distance_m

    def is_high_score(self, score: int) -> bool:
        """Return ``True`` if ``score`` would beat the stored high score."""
        return self._as_nonneg_int(score) > int(self.data.get("high_score", 0) or 0)

    # ------------------------------------------------------------------ #
    # Event handling
    # ------------------------------------------------------------------ #
    def _on_game_over(self, event: Event) -> None:
        """Persist a run summary in response to a ``GAME_OVER`` event.

        The event payload is read defensively: any of ``score``, ``coins``,
        ``gems``, ``distance_m`` may be missing (they default to ``0``). We
        record the run and immediately flush to disk so progress survives even if
        the process is closed on the game-over screen.

        This never raises — a bad payload or a failed write is logged, not
        propagated, because it runs on the event-dispatch path.
        """
        try:
            score = event.get("score", 0)
            coins = event.get("coins", 0)
            gems = event.get("gems", 0)
            # Accept either the displayed-metre key or a raw fallback.
            distance_m = event.get("distance_m", event.get("distance", 0))
            self.record_run(score, coins, gems, distance_m)
            self.save()
        except Exception as exc:  # pragma: no cover - belt & braces on hot path
            self._log(f"failed to record run on GAME_OVER: {exc!r}")

    def close(self) -> None:
        """Detach from the event bus. Safe to call more than once."""
        if self._unsubscribe is not None:
            try:
                self._unsubscribe()
            except Exception:  # pragma: no cover - defensive
                pass
            self._unsubscribe = None

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _merge_into(self, base: Dict[str, Any], incoming: Dict[str, Any]) -> None:
        """Recursively merge ``incoming`` onto ``base`` in place.

        Nested dictionaries are merged key-by-key so a partial section on disk
        doesn't wipe sibling defaults; every other type (including lists) is
        taken verbatim from ``incoming``. This is what makes the schema tolerant
        of both older and newer save files.
        """
        for key, value in incoming.items():
            existing = base.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                self._merge_into(existing, value)
            else:
                base[key] = value

    def _coerce_schema(self) -> None:
        """Guarantee the invariant types of the top-level schema.

        A hand-edited or corrupt file might contain, say, a string where a
        section dict belongs. Rather than let a later ``get_section`` mutation or
        ``.items()`` call explode, we quietly repair the shape here: every known
        section key becomes a dict, and the headline numeric counters become
        non-negative ints.
        """
        for key in _SECTION_KEYS:
            if not isinstance(self.data.get(key), dict):
                self.data[key] = {}

        for key in (
            "high_score",
            "best_distance_m",
            "total_coins",
            "total_gems",
            "total_distance_m",
            "total_runs",
            "coins_balance",
        ):
            self.data[key] = self._as_nonneg_int(self.data.get(key, 0))

    @staticmethod
    def _as_nonneg_int(value: Any) -> int:
        """Coerce ``value`` to a non-negative int, defaulting bad input to 0."""
        try:
            # ``int(float(...))`` copes with "42", 42.9, True, etc.; bool first
            # because bool is an int subclass we still want to accept.
            n = int(float(value))
        except (TypeError, ValueError):
            return 0
        return n if n > 0 else 0

    def _log(self, message: str) -> None:
        """Emit a diagnostic line to stdout. Never raises."""
        try:
            print(f"[save] {message}", file=sys.stdout)
        except Exception:  # pragma: no cover - stdout should always work
            pass

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"SaveManager(path={self.path!r}, "
            f"high_score={self.data.get('high_score')}, "
            f"coins_balance={self.data.get('coins_balance')}, "
            f"total_runs={self.data.get('total_runs')})"
        )
