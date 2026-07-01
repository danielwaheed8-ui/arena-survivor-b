"""
User settings — the game's small, persistent bag of preferences.

The :class:`Settings` object owns everything the *player* is allowed to tune from
the options screen: audio volumes, the toggles that trade fidelity for comfort or
performance (particles, screen shake, an FPS read-out, a high-contrast mode), and
the keyboard bindings that map physical keys to logical game actions. It knows how
to load and save itself as JSON, reset to sane defaults, and — the fiddly bit —
translate between pygame key *constants* (integers like ``pygame.K_a``), pygame
key *names* (``"a"``, ``"left"``), and the human-facing binding strings stored in
:data:`temple_run.config.Keys.DEFAULT_BINDINGS`.

Design goals and rationale
--------------------------

* **Separate from the save file.** Progress (coins, unlocks, high scores) lives in
  :class:`~temple_run.systems.save.SaveManager`; *preferences* live here, in their
  own small file (``Config.SETTINGS_FILE``). They change on different cadences and
  for different reasons — wiping your progress should not reset your key bindings,
  and vice-versa — so they get independent files and independent lifecycles.

* **Never crash the game.** Loading happens at startup and saving happens when the
  player leaves the options menu, but a corrupt file, a permissions error, or a
  hand-edited blob with the wrong shape must all be survivable. Every I/O and
  parse boundary is wrapped in ``try/except``; on any failure we log a line to
  stdout and fall back to in-memory defaults. A lost settings file is a minor
  annoyance; a traceback that kills the process is not acceptable.

* **Tolerant, self-healing schema.** :meth:`load` merges the on-disk values *onto*
  a fresh set of defaults rather than replacing them, and coerces every field back
  to its expected type (clamping volumes, forcing bools, validating bindings). A
  file written by an older or newer build — or a file missing half its keys — is
  read as far as it makes sense and repaired for the rest.

* **Bindings are the interesting part.** The rest of the game does not want to care
  whether "jump" is bound to ``UP``, ``w`` or ``SPACE``; it just asks
  :meth:`action_for_key` "what action is this key int?" and gets back
  ``"jump"`` or ``None``. To answer that we keep a reverse map from key constants
  to actions, rebuilt whenever bindings change. Building that map robustly across
  pygame's slightly inconsistent naming (``"left"`` vs ``"LEFT"``, ``"rshift"``
  which :func:`pygame.key.key_code` does not even recognise) is what most of the
  key-table code below is for.

The public surface is deliberately small: construct (which loads), read/write the
typed fields through their getters/setters, rebind keys, and :meth:`save`. An
input manager or audio engine can be handed this object and query it directly.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from typing import Any, Dict, List, Optional

import pygame

from ..config import Config, Keys
from ..mathutils import clamp01

__all__ = ["Settings", "DEFAULT_SETTINGS"]


# ---------------------------------------------------------------------------
# Default schema
# ---------------------------------------------------------------------------
# The canonical shape of a settings file. ``load`` deep-copies this and merges the
# on-disk values over the top, so every key is guaranteed present (and the right
# type) after a load — even from an empty, ancient, or partially-corrupt file.
#
# ``bindings`` is filled in from ``Keys.DEFAULT_BINDINGS`` at construction time
# rather than hard-coded here, so there is a single source of truth for the game's
# default controls.
DEFAULT_SETTINGS: Dict[str, Any] = {
    "sfx_volume": 0.7,        # one-shot sound effects, 0..1
    "music_volume": 0.5,      # background music bed, 0..1
    "particles": True,        # emit particle FX (off = cheaper / calmer)
    "screen_shake": True,     # camera/screen shake on impacts
    "show_fps": False,        # draw a frames-per-second read-out
    "high_contrast": False,   # accessibility: bolder, higher-contrast UI
    # "bindings" is injected in __init__ from Keys.DEFAULT_BINDINGS.
}

# The boolean toggles, listed once so load/coerce/reset can iterate them.
_BOOL_KEYS = ("particles", "screen_shake", "show_fps", "high_contrast")
# The [0, 1] float knobs.
_FLOAT_KEYS = ("sfx_volume", "music_volume")


class Settings:
    """Owns and persists the player's tunable preferences.

    Typical use::

        settings = Settings()              # loads immediately from disk
        settings.set_sfx_volume(0.9)
        settings.rebind("jump", "SPACE")
        settings.save()

        # elsewhere, resolving input:
        action = settings.action_for_key(event.key)   # -> "jump" or None

    All mutating helpers operate on in-memory attributes; nothing touches the disk
    until :meth:`save` is called.
    """

    def __init__(self, path: str = Config.SETTINGS_FILE) -> None:
        """Create the settings object and immediately :meth:`load` from ``path``.

        Parameters
        ----------
        path:
            Filesystem location of the JSON settings file. Defaults to
            ``Config.SETTINGS_FILE`` (resolved relative to the working directory).
        """
        self.path: str = path

        # -- tunable fields, seeded with defaults -------------------------- #
        # These are populated properly by ``load`` below, but we assign the
        # defaults up front so the object is fully usable even if the load fails
        # or is skipped (e.g. in a unit test that patches ``load`` out).
        self.sfx_volume: float = float(DEFAULT_SETTINGS["sfx_volume"])
        self.music_volume: float = float(DEFAULT_SETTINGS["music_volume"])
        self.particles: bool = bool(DEFAULT_SETTINGS["particles"])
        self.screen_shake: bool = bool(DEFAULT_SETTINGS["screen_shake"])
        self.show_fps: bool = bool(DEFAULT_SETTINGS["show_fps"])
        self.high_contrast: bool = bool(DEFAULT_SETTINGS["high_contrast"])

        # ``bindings`` maps a logical action -> list of key *name* strings, e.g.
        # ``{"jump": ["UP", "w", "SPACE"], ...}``. Seeded from the shared defaults.
        self.bindings: Dict[str, List[str]] = self._default_bindings()

        # Static, case-insensitive table of key-name -> pygame constant, built once
        # from pygame's own K_* constants plus a few friendly aliases. Used by the
        # reverse resolver below. Built before ``load`` so ``_rebuild_key_map`` can
        # run against a valid table.
        self._name_to_const: Dict[str, int] = self._build_name_to_const_table()

        # Reverse map: pygame key constant (int) -> action name. Rebuilt from
        # ``self.bindings`` whenever the bindings change. Populated by ``load``.
        self._key_to_action: Dict[int, str] = {}

        # Pull whatever is on disk into the fields above, then build the key map.
        self.load()

    # ------------------------------------------------------------------ #
    # Disk I/O
    # ------------------------------------------------------------------ #
    def load(self) -> None:
        """Load settings from disk, tolerating a missing or corrupt file.

        The on-disk dictionary is merged onto a fresh copy of
        :data:`DEFAULT_SETTINGS`, then every field is coerced to its expected type
        (volumes clamped to ``[0, 1]``, toggles forced to ``bool``, bindings
        validated). A missing, unreadable, or invalid file leaves us cleanly on
        the defaults. The key-to-action reverse map is rebuilt at the end so the
        object is immediately ready to resolve input.
        """
        merged: Dict[str, Any] = copy.deepcopy(DEFAULT_SETTINGS)
        # Defaults don't carry bindings (they're derived); seed them explicitly so
        # a file that omits "bindings" still ends up with the full control set.
        merged["bindings"] = self._default_bindings()

        raw: Optional[str] = None
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as fh:
                    raw = fh.read()
        except OSError as exc:
            self._log(f"could not read settings file {self.path!r}: {exc!r} — using defaults")
            raw = None

        if raw:
            try:
                loaded = json.loads(raw)
            except (json.JSONDecodeError, ValueError) as exc:
                self._log(f"settings file {self.path!r} is corrupt ({exc!r}) — using defaults")
                loaded = None

            if isinstance(loaded, dict):
                # Shallow, key-by-key merge is enough: the schema is flat apart
                # from ``bindings``, which we handle specially below.
                for key, value in loaded.items():
                    if key == "bindings":
                        merged["bindings"] = self._sanitise_bindings(value)
                    else:
                        merged[key] = value
            elif loaded is not None:
                self._log(f"settings file {self.path!r} has unexpected top-level type — using defaults")

        # Commit the merged/validated values onto our typed fields.
        self._apply_dict(merged)
        # A fresh reverse map reflecting the (possibly-loaded) bindings.
        self._rebuild_key_map()

    def save(self) -> bool:
        """Persist the current settings to disk atomically.

        We serialise to a temp file in the same directory as the target, flush +
        fsync it, then ``os.replace`` it over the real file — an atomic swap on
        POSIX and Windows, so a reader ever only sees the old file or the complete
        new one, never a torn write. Any failure is logged and swallowed; saving
        must never take the game down.

        Returns
        -------
        bool
            ``True`` on a successful write, ``False`` if anything went wrong.
        """
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            self._log(f"could not create settings directory {directory!r}: {exc!r}")
            return False

        # Serialise first: if the data somehow isn't encodable, fail before we
        # create any temp files on disk.
        try:
            payload = json.dumps(self.to_dict(), indent=2, sort_keys=True)
        except (TypeError, ValueError) as exc:
            self._log(f"settings are not JSON-serialisable: {exc!r}")
            return False

        tmp_path: Optional[str] = None
        try:
            fd, tmp_path = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=directory)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self.path)
            tmp_path = None  # replaced successfully; nothing to clean up
            return True
        except OSError as exc:
            self._log(f"could not write settings file {self.path!r}: {exc!r}")
            return False
        finally:
            # Remove an orphaned temp file if we bailed before the rename.
            if tmp_path is not None and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def reset_defaults(self) -> None:
        """Restore every setting (including bindings) to its factory default.

        Does *not* persist on its own — callers should :meth:`save` afterwards if
        they want the reset to survive a restart (the options screen's "reset"
        button typically does both).
        """
        fresh = copy.deepcopy(DEFAULT_SETTINGS)
        fresh["bindings"] = self._default_bindings()
        self._apply_dict(fresh)
        self._rebuild_key_map()

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-ready snapshot of the current settings.

        A plain dict mirroring the on-disk schema. Bindings are deep-copied so the
        caller can't accidentally mutate our live lists.
        """
        return {
            "sfx_volume": self.sfx_volume,
            "music_volume": self.music_volume,
            "particles": self.particles,
            "screen_shake": self.screen_shake,
            "show_fps": self.show_fps,
            "high_contrast": self.high_contrast,
            "bindings": {action: list(keys) for action, keys in self.bindings.items()},
        }

    # ------------------------------------------------------------------ #
    # Typed getters / setters (volumes clamp to [0, 1])
    # ------------------------------------------------------------------ #
    def get_sfx_volume(self) -> float:
        """Return the SFX volume, guaranteed in ``[0, 1]``."""
        return self.sfx_volume

    def set_sfx_volume(self, value: float) -> float:
        """Set the SFX volume, clamping into ``[0, 1]``. Returns the stored value."""
        self.sfx_volume = clamp01(self._as_float(value, self.sfx_volume))
        return self.sfx_volume

    def get_music_volume(self) -> float:
        """Return the music volume, guaranteed in ``[0, 1]``."""
        return self.music_volume

    def set_music_volume(self, value: float) -> float:
        """Set the music volume, clamping into ``[0, 1]``. Returns the stored value."""
        self.music_volume = clamp01(self._as_float(value, self.music_volume))
        return self.music_volume

    def set_particles(self, enabled: bool) -> bool:
        """Enable/disable particle FX. Returns the stored boolean."""
        self.particles = bool(enabled)
        return self.particles

    def set_screen_shake(self, enabled: bool) -> bool:
        """Enable/disable screen shake. Returns the stored boolean."""
        self.screen_shake = bool(enabled)
        return self.screen_shake

    def set_show_fps(self, enabled: bool) -> bool:
        """Enable/disable the FPS read-out. Returns the stored boolean."""
        self.show_fps = bool(enabled)
        return self.show_fps

    def set_high_contrast(self, enabled: bool) -> bool:
        """Enable/disable high-contrast UI. Returns the stored boolean."""
        self.high_contrast = bool(enabled)
        return self.high_contrast

    def toggle(self, name: str) -> bool:
        """Flip a boolean toggle by field name and return its new value.

        A convenience for options screens that wire a single button to each
        toggle. Unknown names are ignored and return ``False``.
        """
        if name in _BOOL_KEYS:
            new_value = not bool(getattr(self, name))
            setattr(self, name, new_value)
            return new_value
        return False

    # ------------------------------------------------------------------ #
    # Key bindings
    # ------------------------------------------------------------------ #
    def key_names_for(self, action: str) -> List[str]:
        """Return a *copy* of the key names bound to ``action``.

        Empty list for an unknown action. A copy is returned so callers can't
        mutate our stored binding list by accident — use :meth:`rebind` to change
        bindings.
        """
        return list(self.bindings.get(action, ()))

    def rebind(self, action: str, key_name: str) -> bool:
        """Bind ``action`` to a single ``key_name``, replacing any previous keys.

        We validate the name against the key table; an unrecognised name is
        rejected (logged, no change) so a typo can't silently strand an action
        with no working key. The reverse map is rebuilt on success so the new
        binding takes effect immediately.

        Returns
        -------
        bool
            ``True`` if the rebind was applied, ``False`` if the key name was not
            recognised.
        """
        normalised = self._normalise_name(key_name)
        if normalised is None:
            self._log(f"rebind({action!r}, {key_name!r}) rejected — unknown key name")
            return False
        # Store the canonical form we can resolve later. A single-key binding is
        # the common rebind case; use ``add_binding`` for multi-key actions.
        self.bindings[action] = [normalised]
        self._rebuild_key_map()
        return True

    def add_binding(self, action: str, key_name: str) -> bool:
        """Add ``key_name`` as an *additional* key for ``action`` (no duplicates).

        Unlike :meth:`rebind`, this keeps any existing keys. Useful for "add a
        second key" UI. Returns ``True`` if applied.
        """
        normalised = self._normalise_name(key_name)
        if normalised is None:
            self._log(f"add_binding({action!r}, {key_name!r}) rejected — unknown key name")
            return False
        keys = self.bindings.setdefault(action, [])
        # Compare case-insensitively so we don't stack "SPACE" and "space".
        if not any(self._normalise_name(k) == normalised for k in keys):
            keys.append(normalised)
            self._rebuild_key_map()
        return True

    def clear_binding(self, action: str) -> None:
        """Remove all keys bound to ``action`` (leaving it unbound)."""
        if action in self.bindings:
            self.bindings[action] = []
            self._rebuild_key_map()

    def resolve_key(self, pygame_key_int: int) -> Optional[str]:
        """Return the action a pygame key constant is bound to, or ``None``.

        This is the primary lookup the input layer uses: given ``event.key`` it
        answers "which logical action fired?". Backed by the pre-built reverse map
        for O(1) resolution. If a key is bound to more than one action, the last
        one built wins (bindings are iterated in insertion order); in practice the
        default set is unambiguous.
        """
        return self._key_to_action.get(pygame_key_int)

    def action_for_key(self, key_int: int) -> Optional[str]:
        """Alias for :meth:`resolve_key`, matching the contract's naming.

        Both names exist because different call-sites read more naturally with one
        or the other; they are the same lookup.
        """
        return self._key_to_action.get(key_int)

    def const_for_name(self, key_name: str) -> Optional[int]:
        """Resolve a key *name* string to its pygame constant, or ``None``.

        Case-insensitive and alias-aware (``"SPACE"``, ``"space"``, ``"esc"`` …).
        Exposed so UI can, e.g., show which physical key a binding maps to.
        """
        return self._const_for_name(key_name)

    def name_for_const(self, key_int: int) -> str:
        """Return a display-friendly, upper-cased name for a pygame key constant.

        Falls back through :func:`pygame.key.name` so even keys we don't have an
        explicit alias for still render something sensible. Never raises.
        """
        try:
            name = pygame.key.name(int(key_int))
        except Exception:  # pragma: no cover - defensive against odd inputs
            return "?"
        # pygame gives lowercase, space-separated names ("left", "right shift").
        return name.upper() if name else "?"

    # ------------------------------------------------------------------ #
    # Internal: schema application / coercion
    # ------------------------------------------------------------------ #
    def _apply_dict(self, data: Dict[str, Any]) -> None:
        """Copy a (merged) settings dict onto our typed fields, coercing types.

        Volumes are clamped to ``[0, 1]``; toggles are forced to ``bool``;
        bindings are sanitised into an ``action -> list[str]`` shape. Anything
        missing or malformed falls back to the corresponding default, so the
        object is always left in a fully valid state.
        """
        self.sfx_volume = clamp01(self._as_float(data.get("sfx_volume"), DEFAULT_SETTINGS["sfx_volume"]))
        self.music_volume = clamp01(self._as_float(data.get("music_volume"), DEFAULT_SETTINGS["music_volume"]))

        for key in _BOOL_KEYS:
            setattr(self, key, self._as_bool(data.get(key), DEFAULT_SETTINGS[key]))

        # Bindings may already be sanitised (from ``load``) or raw (from a reset);
        # running them through the sanitiser again is cheap and idempotent.
        self.bindings = self._sanitise_bindings(data.get("bindings"))

    def _sanitise_bindings(self, value: Any) -> Dict[str, List[str]]:
        """Validate an arbitrary ``bindings`` value into ``action -> list[str]``.

        Starts from a copy of the defaults so every known action is always
        present, then overlays whatever valid entries the input provides. Each
        candidate key name is normalised against the key table; names we can't
        resolve are dropped (with a log) rather than kept as dead bindings. An
        action that ends up with *no* valid keys is restored to its default set so
        the player is never stranded with an uncontrollable action.
        """
        result: Dict[str, List[str]] = self._default_bindings()

        if not isinstance(value, dict):
            # Nothing usable — the defaults we already have stand.
            return result

        for action, raw_keys in value.items():
            if not isinstance(action, str):
                continue
            # Accept a bare string as a single-key binding for convenience.
            if isinstance(raw_keys, str):
                raw_keys = [raw_keys]
            if not isinstance(raw_keys, (list, tuple)):
                continue

            cleaned: List[str] = []
            for name in raw_keys:
                normalised = self._normalise_name(name)
                if normalised is None:
                    self._log(f"dropping unknown key {name!r} bound to action {action!r}")
                    continue
                if normalised not in cleaned:  # de-dupe within an action
                    cleaned.append(normalised)

            if cleaned:
                result[action] = cleaned
            elif action in result:
                # An action explicitly present but with only bad keys: keep its
                # default rather than leaving it unbound.
                self._log(f"action {action!r} had no valid keys — keeping defaults")
            else:
                # An unknown action with no valid keys — ignore it entirely.
                continue

        return result

    @staticmethod
    def _default_bindings() -> Dict[str, List[str]]:
        """Return a fresh, mutable copy of the default bindings.

        ``Keys.DEFAULT_BINDINGS`` stores tuples; we convert to lists so bindings
        are mutable in place (add/rebind), and copy so we never alias the shared
        config object.
        """
        return {action: list(keys) for action, keys in Keys.DEFAULT_BINDINGS.items()}

    # ------------------------------------------------------------------ #
    # Internal: the key-name <-> pygame-constant table
    # ------------------------------------------------------------------ #
    def _rebuild_key_map(self) -> None:
        """Rebuild the pygame-constant -> action reverse map from ``bindings``.

        Called whenever bindings change (load, reset, rebind, add/clear). Each
        bound key name is resolved to a pygame constant via the name table; names
        that don't resolve are skipped (they were already validated on the way in,
        but we stay defensive). The result lets :meth:`resolve_key` answer in O(1).
        """
        mapping: Dict[int, str] = {}
        for action, key_names in self.bindings.items():
            for name in key_names:
                const = self._const_for_name(name)
                if const is not None:
                    mapping[const] = action
        self._key_to_action = mapping

    def _const_for_name(self, key_name: Any) -> Optional[int]:
        """Resolve a key name string to a pygame constant, or ``None``.

        Resolution order:

        1. Our precomputed, upper-cased alias table (handles ``LEFT``, ``SPACE``,
           ``RSHIFT`` and friends uniformly).
        2. :func:`pygame.key.key_code` as a fallback for anything the table missed
           (it accepts the lowercase display names pygame itself produces).

        Both stages are case-insensitive. Returns ``None`` for unknown names.
        """
        if not isinstance(key_name, str):
            return None
        key = key_name.strip().upper()
        if not key:
            return None

        const = self._name_to_const.get(key)
        if const is not None:
            return const

        # Fallback: pygame's own resolver. It wants the lowercase display name
        # ("left", "space"), so try the lowercased original.
        try:
            return int(pygame.key.key_code(key_name.strip().lower()))
        except Exception:  # pragma: no cover - defensive
            # key_code raises a plain ValueError ("unknown key name") for names it
            # doesn't know; anything else is equally "unresolvable" for our needs.
            return None

    def _normalise_name(self, key_name: Any) -> Optional[str]:
        """Canonicalise a key name for *storage* (upper-cased), or ``None``.

        A name is accepted iff it resolves to a pygame constant. The canonical
        stored form is the upper-cased table key when we have one (so bindings are
        tidy and comparable), otherwise the upper-cased input. This keeps the
        on-disk bindings human-readable and consistent (``"SPACE"``, not a mix of
        ``"space"``/``"Space"``).
        """
        if not isinstance(key_name, str):
            return None
        const = self._const_for_name(key_name)
        if const is None:
            return None
        # Prefer the canonical table name for this constant when one exists, so
        # e.g. both "space" and "SPACE" store as "SPACE".
        canonical = self._const_to_table_name.get(const)
        return canonical if canonical is not None else key_name.strip().upper()

    def _build_name_to_const_table(self) -> Dict[str, int]:
        """Build the static, upper-cased key-name -> pygame-constant table.

        We derive the bulk of it automatically from pygame's ``K_*`` constants:
        for each ``pygame.K_FOO`` we register the name ``"FOO"`` (upper-cased,
        without the ``K_`` prefix). That single loop covers letters, digits, the
        arrows (``LEFT``/``RIGHT``/``UP``/``DOWN``), ``SPACE``, ``RETURN``,
        ``ESCAPE``, ``TAB``, both shift/ctrl/alt variants, the keypad, and more —
        matching exactly the names used throughout ``Keys.DEFAULT_BINDINGS``.

        On top of that we register a handful of friendly *aliases* (``ENTER`` for
        ``RETURN``, ``ESC`` for ``ESCAPE``, ``SHIFT``/``CTRL``/``ALT`` for the
        left-hand variants) so options screens and hand-edited files can use the
        obvious names. Also builds the inverse ``_const_to_table_name`` used to
        canonicalise stored names.
        """
        table: Dict[str, int] = {}
        # First pass: every K_* integer constant becomes NAME -> const.
        for attr in dir(pygame):
            if not attr.startswith("K_"):
                continue
            value = getattr(pygame, attr, None)
            if not isinstance(value, int) or isinstance(value, bool):
                continue
            # "K_a" -> "A", "K_LEFT" -> "LEFT", "K_SPACE" -> "SPACE".
            name = attr[2:].upper()
            if name:  # skip a hypothetical bare "K_"
                table.setdefault(name, value)

        # Second pass: convenience aliases. Only added if the target exists, so we
        # never invent a binding for a key this pygame build lacks.
        aliases = {
            "ENTER": "RETURN",
            "ESC": "ESCAPE",
            "SHIFT": "LSHIFT",
            "CTRL": "LCTRL",
            "CONTROL": "LCTRL",
            "ALT": "LALT",
            "DEL": "DELETE",
            "SPACEBAR": "SPACE",
            "PGUP": "PAGEUP",
            "PGDN": "PAGEDOWN",
        }
        for alias, target in aliases.items():
            if target in table:
                table.setdefault(alias, table[target])

        # Inverse table: constant -> canonical (first-registered) name. We prefer
        # the shortest sensible name so common keys canonicalise nicely (e.g. the
        # constant for return maps back to "RETURN", not "ENTER"). Because dict
        # iteration is insertion-ordered and the K_* pass runs first, the direct
        # K_* names win over aliases automatically.
        self._const_to_table_name: Dict[int, str] = {}
        for name, const in table.items():
            self._const_to_table_name.setdefault(const, name)

        return table

    # ------------------------------------------------------------------ #
    # Internal: small typed coercions & logging
    # ------------------------------------------------------------------ #
    @staticmethod
    def _as_float(value: Any, default: float) -> float:
        """Coerce ``value`` to a float, falling back to ``default`` on bad input."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _as_bool(value: Any, default: bool) -> bool:
        """Coerce ``value`` to a bool with JSON/human-friendly leniency.

        Accepts real bools, ``0/1``, and the strings ``"true"/"false"/"yes"/"no"/
        "on"/"off"`` (case-insensitive). Anything unrecognised yields ``default``,
        so a corrupt entry self-heals to its default rather than becoming a
        surprising truthy/falsey value.
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "1", "yes", "on"):
                return True
            if lowered in ("false", "0", "no", "off"):
                return False
        return bool(default)

    def _log(self, message: str) -> None:
        """Emit a diagnostic line to stdout. Never raises."""
        try:
            print(f"[settings] {message}", file=sys.stdout)
        except Exception:  # pragma: no cover - stdout should always work
            pass

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Settings(path={self.path!r}, "
            f"sfx={self.sfx_volume:.2f}, music={self.music_volume:.2f}, "
            f"particles={self.particles}, shake={self.screen_shake}, "
            f"actions={len(self.bindings)})"
        )
