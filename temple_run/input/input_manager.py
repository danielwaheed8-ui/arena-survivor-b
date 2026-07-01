"""
Input manager: key-binding resolution and a light per-frame press buffer.

Design
------
The game's main loop owns pygame's event queue. When it sees a ``KEYDOWN`` it
hands the raw ``pygame`` key integer to this manager and asks *"which logical
action is this?"*. This class exists so that the rest of the game speaks in
verbs — ``"jump"``, ``"left"``, ``"pause"`` — and never in hardware keycodes.
That indirection is what makes rebindable controls, WASD-or-arrows duplication,
and headless testing all fall out for free.

Two responsibilities live here, kept deliberately small and dependency-light:

1. **Binding resolution.** Bindings are declared by *name* (``"LEFT"``, ``"a"``,
   ``"SPACE"``) either by the :class:`Settings` object or, as a fallback, by
   :data:`Keys.DEFAULT_BINDINGS`. Names are human-authored and therefore messy
   (case, ``"LSHIFT"`` vs pygame's ``"left shift"``, ``"RETURN"`` vs
   ``"ENTER"``), so we normalise them through :data:`KEY_NAME_TO_CONST` and a
   set of aliases, then flatten everything into a single
   ``keycode -> action`` dict for O(1) lookup on the hot path.

2. **Frame-scoped "just pressed" buffer.** Menus and one-shot actions want
   edge-triggered semantics ("was *jump* pressed *this* frame?") rather than the
   held state pygame exposes via ``get_pressed``. We record pressed actions into
   a small set, answer :meth:`is_pressed` against it, and clear it at
   :meth:`end_frame`. It is intentionally timestamp-less: the physics layer does
   its own richer input-buffering (coyote time, jump buffering) using
   ``Physics.INPUT_BUFFER``; this buffer only needs to survive a single frame.

Rationale for *not* touching the event queue
--------------------------------------------
Reading ``pygame.event.get()`` in two places drains events unpredictably. The
loop is the single reader; we are a pure translation/aggregation layer. That
keeps us trivially unit-testable — you can drive us with bare integers and never
open a window — and keeps the ownership of the (global, singleton) event queue
in exactly one place.

Only the standard library, ``pygame`` and the project's :mod:`config` are
imported, so this module never participates in an import cycle.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set

import pygame

from ..config import Keys


# ---------------------------------------------------------------------------
# Key-name <-> pygame-constant table
# ---------------------------------------------------------------------------
# Bindings are authored as strings; pygame speaks in integer constants. We keep
# an explicit, readable table rather than relying solely on ``pygame.key.name``
# because (a) name() is not perfectly invertible (it yields ``"left shift"``,
# not ``"LSHIFT"``) and (b) an explicit table documents exactly which keys the
# game supports and survives pygame version churn. Names are stored upper-cased;
# lookups normalise the query first, so callers may use any case they like.
def _build_key_name_table() -> Dict[str, int]:
    """Assemble the canonical ``NAME -> pygame constant`` mapping (upper-case)."""
    table: Dict[str, int] = {}

    # Letters a-z. pygame exposes them as ``K_a`` .. ``K_z``.
    for code in range(ord("a"), ord("z") + 1):
        ch = chr(code)
        table[ch.upper()] = getattr(pygame, f"K_{ch}")

    # Digits 0-9 along the number row (``K_0`` .. ``K_9``).
    for digit in range(10):
        table[str(digit)] = getattr(pygame, f"K_{digit}")

    # Keypad digits, so a numpad-heavy user isn't left out.
    for digit in range(10):
        table[f"KP{digit}"] = getattr(pygame, f"K_KP{digit}", getattr(pygame, f"K_KP_{digit}", 0))

    # Function keys F1-F12.
    for n in range(1, 13):
        const = getattr(pygame, f"K_F{n}", None)
        if const is not None:
            table[f"F{n}"] = const

    # Arrows.
    table.update(
        {
            "LEFT": pygame.K_LEFT,
            "RIGHT": pygame.K_RIGHT,
            "UP": pygame.K_UP,
            "DOWN": pygame.K_DOWN,
        }
    )

    # Whitespace / editing / navigation.
    table.update(
        {
            "SPACE": pygame.K_SPACE,
            "RETURN": pygame.K_RETURN,
            "ENTER": pygame.K_RETURN,
            "ESCAPE": pygame.K_ESCAPE,
            "TAB": pygame.K_TAB,
            "BACKSPACE": pygame.K_BACKSPACE,
            "DELETE": pygame.K_DELETE,
            "INSERT": pygame.K_INSERT,
            "HOME": pygame.K_HOME,
            "END": pygame.K_END,
            "PAGEUP": pygame.K_PAGEUP,
            "PAGEDOWN": pygame.K_PAGEDOWN,
        }
    )

    # Modifiers. The generic ``SHIFT``/``CTRL``/``ALT`` alias the left variant so
    # a binding like ``("shift",)`` resolves to something sensible, while the
    # explicit L/R forms remain distinguishable.
    table.update(
        {
            "LSHIFT": pygame.K_LSHIFT,
            "RSHIFT": pygame.K_RSHIFT,
            "SHIFT": pygame.K_LSHIFT,
            "LCTRL": pygame.K_LCTRL,
            "RCTRL": pygame.K_RCTRL,
            "CTRL": pygame.K_LCTRL,
            "CONTROL": pygame.K_LCTRL,
            "LALT": pygame.K_LALT,
            "RALT": pygame.K_RALT,
            "ALT": pygame.K_LALT,
        }
    )

    # A handful of common punctuation keys, guarded because their pygame names
    # vary a little across builds.
    for name, attr in (
        ("MINUS", "K_MINUS"),
        ("EQUALS", "K_EQUALS"),
        ("COMMA", "K_COMMA"),
        ("PERIOD", "K_PERIOD"),
        ("SLASH", "K_SLASH"),
        ("BACKSLASH", "K_BACKSLASH"),
        ("SEMICOLON", "K_SEMICOLON"),
        ("QUOTE", "K_QUOTE"),
        ("BACKQUOTE", "K_BACKQUOTE"),
        ("LEFTBRACKET", "K_LEFTBRACKET"),
        ("RIGHTBRACKET", "K_RIGHTBRACKET"),
    ):
        const = getattr(pygame, attr, None)
        if const is not None:
            table[name] = const

    # Drop any placeholder zeros the keypad guard above may have introduced.
    return {k: v for k, v in table.items() if v}


#: Canonical ``NAME -> pygame constant`` table. Keys are upper-cased; use
#: :func:`name_to_const` (or :meth:`InputManager.name_to_const`) for lookups so
#: aliasing and normalisation are applied.
KEY_NAME_TO_CONST: Dict[str, int] = _build_key_name_table()

#: Reverse table for :func:`const_to_name`. Built once from the forward table.
#: Because several names may share a constant (e.g. ``ENTER``/``RETURN`` or
#: ``SHIFT``/``LSHIFT``), we deterministically prefer the *first* name inserted,
#: which — given insertion order above — is the canonical primary name.
_CONST_TO_KEY_NAME: Dict[int, str] = {}
for _name, _const in KEY_NAME_TO_CONST.items():
    _CONST_TO_KEY_NAME.setdefault(_const, _name)

#: Name aliases applied *before* the table lookup. This lets binding files or
#: user config use friendlier synonyms without bloating the primary table.
_NAME_ALIASES: Dict[str, str] = {
    "ESC": "ESCAPE",
    "RET": "RETURN",
    "SPACEBAR": "SPACE",
    "SPC": "SPACE",
    "DEL": "DELETE",
    "INS": "INSERT",
    "PGUP": "PAGEUP",
    "PGDN": "PAGEDOWN",
    "PGDOWN": "PAGEDOWN",
    "PAGE_UP": "PAGEUP",
    "PAGE_DOWN": "PAGEDOWN",
    "LEFT SHIFT": "LSHIFT",
    "RIGHT SHIFT": "RSHIFT",
    "LEFT CTRL": "LCTRL",
    "RIGHT CTRL": "RCTRL",
    "LEFT ALT": "LALT",
    "RIGHT ALT": "RALT",
    "LEFT CONTROL": "LCTRL",
    "RIGHT CONTROL": "RCTRL",
}


def _normalise_name(name: str) -> str:
    """Upper-case, trim, unify separators, then resolve any alias.

    Accepts the loose forms real binding tables and users produce — mixed case,
    stray whitespace, ``"page_down"`` vs ``"page down"`` — and returns a key
    that :data:`KEY_NAME_TO_CONST` will recognise (or an unknown-but-clean key).
    """
    key = name.strip().upper()
    # Treat underscores like spaces so "PAGE_UP" and "PAGE UP" both alias.
    spaced = key.replace("_", " ")
    if spaced in _NAME_ALIASES:
        return _NAME_ALIASES[spaced]
    if key in _NAME_ALIASES:
        return _NAME_ALIASES[key]
    return key


def name_to_const(name: str) -> Optional[int]:
    """Resolve a key *name* to its pygame constant, or ``None`` if unknown.

    Robust to case and common aliases. Falls back to pygame's own name table so
    exotic keys we didn't enumerate (authored exactly as ``pygame.key.name``
    reports them) still resolve.
    """
    if not name:
        return None
    canonical = _normalise_name(name)
    const = KEY_NAME_TO_CONST.get(canonical)
    if const is not None:
        return const
    # Last resort: ask pygame to reverse its own printable name. This covers the
    # long tail of keys and any name produced verbatim by ``const_to_name``.
    # ``key_code`` warns (and can misbehave) before ``pygame.init``; since it is
    # only a fallback for keys outside our explicit table, we simply decline to
    # guess when the library isn't up yet.
    if not pygame.get_init():
        return None
    try:
        code = pygame.key.key_code(name.strip().lower())
    except (ValueError, TypeError, AttributeError):
        return None
    return code if code else None


def const_to_name(const: int) -> Optional[str]:
    """Map a pygame key constant back to a canonical upper-case name.

    Prefers our explicit table (so we get ``"LSHIFT"`` rather than pygame's
    ``"left shift"``) and falls back to ``pygame.key.name`` for anything not in
    the table. Returns ``None`` for values pygame doesn't recognise.
    """
    name = _CONST_TO_KEY_NAME.get(const)
    if name is not None:
        return name
    try:
        raw = pygame.key.name(const)
    except (ValueError, TypeError):
        return None
    if not raw:
        return None
    return raw.strip().upper() or None


# ---------------------------------------------------------------------------
# InputManager
# ---------------------------------------------------------------------------
class InputManager:
    """Translate key integers to logical actions and buffer per-frame presses.

    Parameters
    ----------
    settings:
        Optional object exposing a ``bindings`` mapping of
        ``action -> sequence[key-name]`` (the :class:`Settings` object). When it
        is missing, or lacks usable bindings, we fall back to
        :data:`Keys.DEFAULT_BINDINGS`. We keep a reference so :meth:`rebuild`
        can re-read the live bindings after the player edits them.
    """

    def __init__(self, settings: Optional[object] = None) -> None:
        self._settings = settings

        # keycode -> action, rebuilt whenever bindings change. This is the hot
        # lookup used every KEYDOWN, so it is a plain dict for speed.
        self._key_to_action: Dict[int, str] = {}
        # action -> sorted list of bound keycodes, handy for reverse queries and
        # for on-screen "press [KEY]" hints.
        self._action_to_keys: Dict[str, List[int]] = {}

        # The per-frame "just pressed" set (edge-triggered actions).
        self._pressed_this_frame: Set[str] = set()
        # Raw keycodes pressed this frame, for callers that want the hardware key
        # rather than the resolved action.
        self._keys_this_frame: Set[int] = set()

        self.rebuild()

    # -- binding construction ------------------------------------------------
    def _current_bindings(self) -> Dict[str, Iterable[str]]:
        """Return the bindings to build from: settings' if usable, else defaults.

        Defensive on purpose — a half-initialised or stubbed settings object
        must never take the input system down with it.
        """
        bindings = getattr(self._settings, "bindings", None)
        if isinstance(bindings, dict) and bindings:
            return bindings
        return Keys.DEFAULT_BINDINGS

    def rebuild(self) -> None:
        """Recompute the keycode<->action maps from the current bindings.

        Call this after the settings' bindings change (a rebind) so subsequent
        :meth:`action_for` lookups reflect the new layout. Idempotent and cheap;
        it fully replaces the internal maps rather than mutating them, so a
        partially-built map can never be observed.
        """
        key_to_action: Dict[int, str] = {}
        action_to_keys: Dict[str, List[int]] = {}

        for action, key_names in self._current_bindings().items():
            action = str(action)
            resolved: List[int] = []
            # A single string is a common authoring slip ("space" instead of
            # ("space",)); treat it as one key rather than iterating characters.
            if isinstance(key_names, str):
                key_names = (key_names,)
            for key_name in key_names:
                const = name_to_const(str(key_name))
                if const is None:
                    # Unknown key names are skipped rather than fatal — a typo in
                    # a user config shouldn't strand the whole action.
                    continue
                resolved.append(const)
                # First binding wins if two actions claim the same key. The game
                # avoids such clashes in its defaults, but user configs might not,
                # and a deterministic winner beats a nondeterministic one.
                key_to_action.setdefault(const, action)
            # De-duplicate while preserving a stable, sorted order.
            action_to_keys[action] = sorted(set(resolved))

        self._key_to_action = key_to_action
        self._action_to_keys = action_to_keys

    # -- resolution queries --------------------------------------------------
    def action_for(self, key_int: int) -> Optional[str]:
        """Return the logical action bound to ``key_int``, or ``None``.

        This is the primary entry point the main loop calls on every KEYDOWN.
        """
        return self._key_to_action.get(key_int)

    def keys_for(self, action: str) -> List[int]:
        """Return the (possibly empty) list of keycodes bound to ``action``."""
        return list(self._action_to_keys.get(action, ()))

    def key_names_for(self, action: str) -> List[str]:
        """Return human-readable key names bound to ``action`` (for UI hints)."""
        names: List[str] = []
        for const in self._action_to_keys.get(action, ()):
            name = const_to_name(const)
            if name is not None:
                names.append(name)
        return names

    def is_bound(self, key_int: int) -> bool:
        """True if ``key_int`` maps to any action under the current layout."""
        return key_int in self._key_to_action

    # -- per-frame press buffer ---------------------------------------------
    def press(self, action: Optional[str], key_int: Optional[int] = None) -> None:
        """Record that ``action`` was 'just pressed' this frame.

        The main loop typically calls ``mgr.press(mgr.action_for(key), key)`` on
        each KEYDOWN. Both arguments are optional so callers can record a raw key
        with no bound action (useful for menu navigation over arbitrary keys).
        Unknown/``None`` actions are ignored for the action set but still noted
        in the raw-key set.
        """
        if action:
            self._pressed_this_frame.add(action)
        if key_int is not None:
            self._keys_this_frame.add(key_int)

    def feed_key(self, key_int: int) -> Optional[str]:
        """Convenience: resolve ``key_int``, record the press, return the action.

        Lets a caller do the resolve-and-buffer step in one line:
        ``action = mgr.feed_key(event.key)``.
        """
        action = self.action_for(key_int)
        self.press(action, key_int)
        return action

    def is_pressed(self, action: str) -> bool:
        """True if ``action`` was pressed since the last :meth:`end_frame`."""
        return action in self._pressed_this_frame

    def any_pressed(self, actions: Iterable[str]) -> bool:
        """True if *any* of ``actions`` was pressed this frame."""
        pressed = self._pressed_this_frame
        return any(a in pressed for a in actions)

    def key_pressed(self, key_int: int) -> bool:
        """True if the raw ``key_int`` was pressed this frame."""
        return key_int in self._keys_this_frame

    def pressed_actions(self) -> Set[str]:
        """A *copy* of the actions pressed this frame (safe to iterate/mutate)."""
        return set(self._pressed_this_frame)

    def end_frame(self) -> None:
        """Clear the per-frame press buffers. Call once at end of the loop tick.

        Because :meth:`is_pressed` is edge-triggered, forgetting to call this
        would make an action look 'held' forever; keeping the reset here (rather
        than at frame *start*) means presses recorded during event handling are
        still visible throughout the same frame's update/draw.
        """
        self._pressed_this_frame.clear()
        self._keys_this_frame.clear()

    # -- name/const helpers (instance-level convenience) ---------------------
    @staticmethod
    def name_to_const(name: str) -> Optional[int]:
        """Instance-accessible alias of the module-level :func:`name_to_const`."""
        return name_to_const(name)

    @staticmethod
    def const_to_name(const: int) -> Optional[str]:
        """Instance-accessible alias of the module-level :func:`const_to_name`."""
        return const_to_name(const)

    # -- misc ----------------------------------------------------------------
    @property
    def bindings(self) -> Dict[str, List[str]]:
        """A snapshot of the resolved layout as ``action -> [key names]``.

        Reconstructed from the live keycode maps so it always reflects what the
        manager will *actually* do, even if a rebind hasn't been persisted yet.
        """
        return {action: self.key_names_for(action) for action in self._action_to_keys}

    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return (
            f"InputManager(actions={len(self._action_to_keys)}, "
            f"keys={len(self._key_to_action)}, "
            f"pressed={sorted(self._pressed_this_frame)})"
        )
