"""
A small, self-contained screen-space UI toolkit.

The menu screens, pause overlay and game-over screen all need the same handful
of primitives: a cached font accessor, buttons that feel alive under the mouse,
static labels, framed panels, progress bars, and transient "toast" notifications
that pop in from the corner. Rather than reach for a heavyweight GUI library (an
extra dependency the contract forbids) we grow our own — a few hundred lines of
pygame drawing that match the look of the rest of the game.

Design notes / rationale
------------------------
* **Palette-driven.** Every widget borrows its colours from :class:`Palette` so
  the whole UI reskins from one place. Buttons derive hover/press tints from
  their base colour via :func:`shade_color` and :func:`lerp_color`, so there is
  no per-state colour table to keep in sync.
* **Feel over fidelity.** Buttons animate their hover/press state with an eased,
  frame-rate-independent spring (``damp``) rather than snapping. That single
  interpolated value drives a subtle scale-up, a brighter fill and a lift shadow,
  which is what makes a flat rectangle read as "pressable".
* **Draw-safe by construction.** Nothing here touches the display surface, the
  event queue, or global pygame state beyond the font module. Every draw path is
  wrapped so a bad colour or a degenerate rect can never raise out of a frame —
  the contract is emphatic that UI must never crash the game, headless or not.
* **Toasts are event-driven.** :class:`ToastManager` subscribes to the ``TOAST``
  event and owns the whole lifecycle (spawn, stack, slide in, hold, fade out),
  so any system can surface a message with a single ``bus.emit(EventType.TOAST,
  text=...)`` and never think about layout.

Everything is screen-space, measured in pixels, and sized against
``Config.WIDTH`` x ``Config.HEIGHT``.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

import pygame

from ..config import Color, Config, Palette, lerp_color, shade_color
from ..core.events import EventBus, EventType
from ..mathutils import clamp01, damp, ease_out_back, ease_out_cubic

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
# Building a SysFont is comparatively expensive, and widgets ask for the same
# few sizes every frame. A tiny module-level cache keyed by (size, bold) keeps
# font construction to once-per-size for the whole process lifetime.
_FONT_CACHE: Dict[Tuple[int, bool], "pygame.font.Font"] = {}

# Preferred UI typeface with graceful fallbacks. SysFont accepts a comma list
# and picks the first installed family, so this quietly degrades on minimal
# systems (and headless CI, where it falls back to the bundled default font).
_FONT_NAME = "Arial,DejaVu Sans,FreeSans"


def get_font(size: int, bold: bool = False) -> "pygame.font.Font":
    """Return a cached :class:`pygame.font.Font` for ``size``/``bold``.

    The font module is initialised lazily on first use so importing this module
    never forces a pygame init. If font construction fails for any reason we
    fall back to pygame's built-in default font rather than propagate the error.
    """
    size = max(6, int(size))
    key = (size, bool(bold))
    font = _FONT_CACHE.get(key)
    if font is None:
        if not pygame.font.get_init():
            pygame.font.init()
        try:
            font = pygame.font.SysFont(_FONT_NAME, size, bold=bold)
        except Exception:
            # Last-resort fallback: the always-available default font.
            font = pygame.font.Font(None, size)
        _FONT_CACHE[key] = font
    return font


# ---------------------------------------------------------------------------
# Low-level drawing helpers
# ---------------------------------------------------------------------------
def draw_text(
    surface: "pygame.Surface",
    text: str,
    pos: Tuple[int, int],
    size: int,
    color: Color,
    center: bool = False,
    bold: bool = False,
    shadow: bool = True,
    alpha: int = 255,
) -> "pygame.Rect":
    """Blit ``text`` at ``pos`` and return its bounding rect.

    ``center`` treats ``pos`` as the centre point rather than the top-left.
    A cheap drop shadow (offset black copy) is drawn by default because flat
    text tends to disappear over the busy 3D backdrop. ``alpha`` lets callers
    fade text in/out without touching the colour.
    """
    font = get_font(size, bold)
    try:
        if shadow:
            sh = font.render(text, True, (0, 0, 0))
            if alpha < 255:
                sh.set_alpha(alpha)
            r = sh.get_rect()
            if center:
                r.center = (pos[0] + 2, pos[1] + 2)
            else:
                r.topleft = (pos[0] + 2, pos[1] + 2)
            surface.blit(sh, r)
        img = font.render(text, True, color)
        if alpha < 255:
            img.set_alpha(alpha)
        rect = img.get_rect()
        if center:
            rect.center = pos
        else:
            rect.topleft = pos
        surface.blit(img, rect)
        return rect
    except Exception:
        # Never let a rendering hiccup take down a frame.
        return pygame.Rect(pos[0], pos[1], 0, 0)


def panel(
    surface: "pygame.Surface",
    rect: "pygame.Rect",
    color: Color,
    radius: int = 12,
    border: int = 0,
    border_color: Optional[Color] = None,
    alpha: int = 255,
) -> None:
    """Draw a rounded, optionally-bordered, optionally-translucent panel.

    When ``alpha`` is opaque we draw straight onto ``surface`` (fast path). When
    a caller wants translucency we render onto a throwaway ``SRCALPHA`` surface
    first so the rounded corners composite correctly against whatever is behind.
    """
    rect = pygame.Rect(rect)
    if rect.width <= 0 or rect.height <= 0:
        return
    radius = max(0, min(radius, rect.width // 2, rect.height // 2))
    try:
        if alpha >= 255:
            pygame.draw.rect(surface, color, rect, border_radius=radius)
            if border > 0:
                bc = border_color if border_color is not None else shade_color(color, 1.4)
                pygame.draw.rect(surface, bc, rect, width=border, border_radius=radius)
            return
        # Translucent path: build the panel on its own alpha surface.
        layer = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        local = pygame.Rect(0, 0, rect.width, rect.height)
        pygame.draw.rect(layer, (*color, alpha), local, border_radius=radius)
        if border > 0:
            bc = border_color if border_color is not None else shade_color(color, 1.4)
            pygame.draw.rect(layer, (*bc, alpha), local, width=border, border_radius=radius)
        surface.blit(layer, rect.topleft)
    except Exception:
        # Older SDL builds without border_radius, or a bad colour: fall back to
        # a plain filled rect so at least *something* renders.
        try:
            surface.fill(color, rect)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Label
# ---------------------------------------------------------------------------
class Label:
    """A static piece of text with a fixed anchor.

    Labels are intentionally dumb: they hold their string and style and paint it
    on :meth:`draw`. Menus that need a value to change (a score, a toggle state)
    just reassign :attr:`text` before drawing.
    """

    def __init__(
        self,
        pos: Tuple[int, int],
        text: str,
        size: int = 24,
        color: Color = Palette.UI_TEXT,
        center: bool = False,
        bold: bool = False,
        shadow: bool = True,
    ) -> None:
        self.pos = pos
        self.text = text
        self.size = size
        self.color = color
        self.center = center
        self.bold = bold
        self.shadow = shadow
        self.visible = True

    def draw(self, surface: "pygame.Surface") -> "pygame.Rect":
        if not self.visible:
            return pygame.Rect(self.pos[0], self.pos[1], 0, 0)
        return draw_text(
            surface, self.text, self.pos, self.size, self.color,
            center=self.center, bold=self.bold, shadow=self.shadow,
        )


# ---------------------------------------------------------------------------
# Panel widget
# ---------------------------------------------------------------------------
class Panel:
    """A framed background box — the substrate menus and dialogs sit on.

    Thin wrapper over :func:`panel` that remembers its geometry and style so it
    can be dropped into a screen's widget list alongside buttons and labels.
    """

    def __init__(
        self,
        rect: "pygame.Rect",
        color: Color = Palette.UI_PANEL,
        radius: int = 16,
        border: int = 2,
        border_color: Optional[Color] = None,
        alpha: int = 235,
    ) -> None:
        self.rect = pygame.Rect(rect)
        self.color = color
        self.radius = radius
        self.border = border
        self.border_color = border_color if border_color is not None else Palette.UI_PANEL_LIGHT
        self.alpha = alpha
        self.visible = True

    def draw(self, surface: "pygame.Surface") -> None:
        if not self.visible:
            return
        panel(
            surface, self.rect, self.color, radius=self.radius,
            border=self.border, border_color=self.border_color, alpha=self.alpha,
        )


# ---------------------------------------------------------------------------
# Button
# ---------------------------------------------------------------------------
class Button:
    """A clickable, animated button.

    State is captured in a single ``_hover`` value in ``[0, 1]`` that eases
    toward its target (1 when the mouse is over it, 0 otherwise) and a ``_press``
    value that dips while the mouse button is held down. Those two scalars drive
    every visual: fill brightness, a slight scale-up on hover, an accent underline
    and a lift shadow. Animating a couple of floats rather than swapping discrete
    "normal/hover/pressed" sprites is what gives the button its springy feel.

    Two interaction paths are supported and can be mixed freely:

    * event-driven — feed pygame events to :meth:`handle_event`, which returns
      ``True`` on a completed click (press *and* release inside the button) and
      invokes ``action`` if one was supplied;
    * poll-driven — call :meth:`update` each frame with the current mouse
      position and button state so the animation advances even between events.
    """

    def __init__(
        self,
        rect: "pygame.Rect",
        text: str,
        action: Optional[Callable[[], None]] = None,
        color: Color = Palette.UI_PANEL_LIGHT,
        text_color: Color = Palette.UI_TEXT,
        accent: Color = Palette.UI_ACCENT,
        size: int = 26,
        radius: int = 12,
        event_bus: Optional[EventBus] = None,
        emit_ui_event: bool = True,
    ) -> None:
        self.rect = pygame.Rect(rect)
        self.text = text
        self.action = action
        self.color = color
        self.text_color = text_color
        self.accent = accent
        self.size = size
        self.radius = radius
        self.event_bus = event_bus
        self.emit_ui_event = emit_ui_event

        self.enabled = True
        self.visible = True

        # Animation state.
        self._hover = 0.0          # 0..1 eased hover amount
        self._press = 0.0          # 0..1 eased press amount
        self._armed = False        # a mouse-down landed inside us and is held
        self._hovered = False      # last-known hover boolean (for handle_event)

    # -- geometry ------------------------------------------------------------
    def contains(self, point: Tuple[int, int]) -> bool:
        return self.rect.collidepoint(point)

    # -- per-frame animation -------------------------------------------------
    def update(self, mouse_pos: Tuple[int, int], mouse_down: bool) -> None:
        """Advance the hover/press animation from the current mouse state.

        ``damp`` gives frame-rate-independent easing; the small smoothing
        constants make the animation quick but not instant. We approximate a
        one-frame dt here because widgets are polled once per frame and the
        exact delta is not worth threading through the UI layer.
        """
        if not self.visible or not self.enabled:
            self._hover = damp(self._hover, 0.0, 0.0005, 1.0 / Config.FPS)
            self._press = damp(self._press, 0.0, 0.0005, 1.0 / Config.FPS)
            self._hovered = False
            return
        self._hovered = self.contains(mouse_pos)
        dt = 1.0 / Config.FPS
        hover_target = 1.0 if self._hovered else 0.0
        press_target = 1.0 if (self._hovered and mouse_down) else 0.0
        self._hover = damp(self._hover, hover_target, 0.0005, dt)
        self._press = damp(self._press, press_target, 0.00005, dt)

    # -- event handling ------------------------------------------------------
    def handle_event(self, event: "pygame.event.Event") -> bool:
        """Process one pygame event; return ``True`` on a completed click.

        A click requires the down-press *and* the release to both land inside
        the button (the ``_armed`` latch), which matches native button
        behaviour: press, slide off, release — no click.
        """
        if not self.visible or not self.enabled:
            return False
        etype = getattr(event, "type", None)
        if etype == pygame.MOUSEMOTION:
            self._hovered = self.contains(getattr(event, "pos", (-1, -1)))
        elif etype == pygame.MOUSEBUTTONDOWN and getattr(event, "button", 0) == 1:
            if self.contains(getattr(event, "pos", (-1, -1))):
                self._armed = True
                self._press = 1.0
        elif etype == pygame.MOUSEBUTTONUP and getattr(event, "button", 0) == 1:
            inside = self.contains(getattr(event, "pos", (-1, -1)))
            was_armed = self._armed
            self._armed = False
            self._press = 0.0
            if was_armed and inside:
                self._fire()
                return True
        return False

    def _fire(self) -> None:
        """Invoke the action and announce the click. Never raises."""
        if self.event_bus is not None and self.emit_ui_event:
            try:
                self.event_bus.emit(EventType.UI_BUTTON, text=self.text)
            except Exception:
                pass
        if self.action is not None:
            try:
                self.action()
            except Exception:
                # A misbehaving callback must not corrupt the UI event loop.
                pass

    # -- drawing -------------------------------------------------------------
    def draw(self, surface: "pygame.Surface") -> None:
        if not self.visible:
            return
        try:
            self._draw(surface)
        except Exception:
            pass

    def _draw(self, surface: "pygame.Surface") -> None:
        hover = self._hover
        press = self._press

        # A hovered button grows very slightly; a pressed one shrinks back. The
        # net effect is a springy "lift then push" as the pointer arrives.
        grow = ease_out_back(clamp01(hover)) * 6.0 - press * 3.0
        rect = self.rect.inflate(int(grow), int(grow))

        # Disabled buttons read as dim and flat.
        if not self.enabled:
            base = shade_color(self.color, 0.6)
            panel(surface, rect, base, radius=self.radius, border=2,
                  border_color=shade_color(base, 1.2))
            draw_text(surface, self.text, rect.center, self.size,
                      Palette.UI_TEXT_DIM, center=True, bold=True)
            return

        # Fill brightens on hover and darkens on press.
        fill = lerp_color(self.color, shade_color(self.color, 1.35), hover)
        fill = shade_color(fill, 1.0 - press * 0.18)

        # Lift shadow: a soft dark rect peeking out below, receding as pressed.
        lift = int((hover * 4.0) * (1.0 - press))
        if lift > 0:
            shadow_rect = rect.move(0, lift)
            panel(surface, shadow_rect, (0, 0, 0), radius=self.radius, alpha=90)

        panel(surface, rect, fill, radius=self.radius, border=2,
              border_color=lerp_color(shade_color(self.color, 1.3), self.accent, hover))

        # Accent underline that sweeps in on hover.
        if hover > 0.02:
            uw = int(rect.width * 0.6 * ease_out_cubic(clamp01(hover)))
            if uw > 0:
                ux = rect.centerx - uw // 2
                uy = rect.bottom - max(4, self.radius // 2)
                try:
                    pygame.draw.line(surface, self.accent, (ux, uy), (ux + uw, uy), 3)
                except Exception:
                    pass

        # Label brightens toward white as the button lights up.
        tcol = lerp_color(self.text_color, Palette.WHITE, hover * 0.5)
        draw_text(surface, self.text, rect.center, self.size, tcol,
                  center=True, bold=True)


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------
class ProgressBar:
    """A horizontal fill bar for values in ``[0, 1]``.

    Handy for mission/achievement progress, powerup timers on menus, or a
    volume slider's readout. The displayed fill eases toward the true value so
    changes glide rather than jump; set :attr:`value` and let :meth:`update`
    (or the draw-time catch-up) chase it.
    """

    def __init__(
        self,
        rect: "pygame.Rect",
        value: float = 0.0,
        fill_color: Color = Palette.UI_ACCENT,
        back_color: Color = Palette.UI_PANEL,
        radius: int = 8,
        show_label: bool = False,
        label_color: Color = Palette.UI_TEXT,
    ) -> None:
        self.rect = pygame.Rect(rect)
        self._value = clamp01(value)
        self._display = self._value
        self.fill_color = fill_color
        self.back_color = back_color
        self.radius = radius
        self.show_label = show_label
        self.label_color = label_color
        self.visible = True

    @property
    def value(self) -> float:
        return self._value

    @value.setter
    def value(self, v: float) -> None:
        self._value = clamp01(v)

    def set_value(self, v: float, *, snap: bool = False) -> None:
        """Set the target fill; ``snap`` also jumps the animated display value."""
        self.value = v
        if snap:
            self._display = self._value

    def update(self, dt: float) -> None:
        # Ease the shown fill toward the target so bumps animate smoothly.
        self._display = damp(self._display, self._value, 0.001, max(0.0, dt))

    def draw(self, surface: "pygame.Surface") -> None:
        if not self.visible:
            return
        try:
            self._draw(surface)
        except Exception:
            pass

    def _draw(self, surface: "pygame.Surface") -> None:
        # If update() is never called (static screens) still snap toward target.
        if abs(self._display - self._value) < 0.001:
            self._display = self._value
        rect = self.rect
        radius = max(0, min(self.radius, rect.height // 2))
        panel(surface, rect, self.back_color, radius=radius, border=2,
              border_color=shade_color(self.back_color, 1.5))
        frac = clamp01(self._display)
        inner = rect.inflate(-6, -6)
        fill_w = int(inner.width * frac)
        if fill_w > 0:
            fill_rect = pygame.Rect(inner.left, inner.top, fill_w, inner.height)
            fr = max(0, min(radius, fill_rect.height // 2))
            # A brighter cap on the leading edge gives the fill some depth.
            top = shade_color(self.fill_color, 1.15)
            pygame.draw.rect(surface, top, fill_rect, border_radius=fr)
            pygame.draw.rect(surface, self.fill_color,
                             fill_rect.inflate(0, -fill_rect.height // 3),
                             border_radius=fr)
        if self.show_label:
            draw_text(surface, f"{int(round(frac * 100))}%", rect.center,
                      max(12, rect.height - 8), self.label_color, center=True, bold=True)


# ---------------------------------------------------------------------------
# Toasts
# ---------------------------------------------------------------------------
class Toast:
    """A single transient notification card.

    Its life runs through three phases driven by :attr:`age` vs :attr:`life`:
    an eased **slide-in** from the right, a steady **hold**, and a **fade-out**.
    :meth:`alpha` and :meth:`slide` expose those so the manager can lay the card
    out without knowing the timing curve.
    """

    IN_TIME = 0.28    # seconds spent sliding/fading in
    OUT_TIME = 0.45   # seconds spent fading out at the end

    def __init__(
        self,
        text: str,
        color: Color = Palette.UI_ACCENT,
        icon: Optional[str] = None,
        life: float = 2.6,
    ) -> None:
        self.text = str(text)
        self.color = color
        self.icon = icon
        self.life = max(0.6, float(life))
        self.age = 0.0
        # Vertical slot position (target y), eased by the manager as the stack
        # shifts when toasts above it expire.
        self.y = 0.0
        self.target_y = 0.0
        self._first_layout = True

    @property
    def dead(self) -> bool:
        return self.age >= self.life

    def update(self, dt: float) -> None:
        self.age += dt

    def alpha(self) -> int:
        """0..255 opacity following the in/hold/out envelope."""
        if self.age < self.IN_TIME:
            a = ease_out_cubic(clamp01(self.age / self.IN_TIME))
        elif self.age > self.life - self.OUT_TIME:
            remaining = self.life - self.age
            a = clamp01(remaining / self.OUT_TIME)
        else:
            a = 1.0
        return int(clamp01(a) * 255)

    def slide(self) -> float:
        """Horizontal offset (px) the card is pushed right by during entry."""
        if self.age >= self.IN_TIME:
            return 0.0
        t = clamp01(self.age / self.IN_TIME)
        # Start fully off to the right, ease home.
        return (1.0 - ease_out_cubic(t)) * 60.0


class ToastManager:
    """Owns the stack of active toasts in the top-right corner.

    If handed an :class:`EventBus` it subscribes to :data:`EventType.TOAST` and
    spawns a card for each event, reading the optional ``color``/``icon`` from
    the payload (see the contract's TOAST schema). Systems therefore never touch
    this class directly — they just emit toasts.
    """

    MARGIN = 20            # gap from the screen edges
    WIDTH = 320            # card width
    HEIGHT = 56            # card height
    GAP = 10               # vertical gap between stacked cards
    MAX_VISIBLE = 6        # older cards beyond this are dropped

    def __init__(self, event_bus: Optional[EventBus] = None) -> None:
        self.toasts: List[Toast] = []
        self.event_bus = event_bus
        self._unsub: Optional[Callable[[], None]] = None
        if event_bus is not None:
            try:
                self._unsub = event_bus.subscribe(EventType.TOAST, self._on_toast)
            except Exception:
                self._unsub = None

    # -- event glue ----------------------------------------------------------
    def _on_toast(self, event) -> None:
        """EventBus listener: turn a TOAST event into a card. Never raises."""
        try:
            text = event.get("text", "")
            color = event.get("color", Palette.UI_ACCENT)
            icon = event.get("icon", None)
            life = event.get("life", 2.6)
            if text:
                self.push(str(text), color=color, icon=icon, life=life)
        except Exception:
            pass

    # -- public API ----------------------------------------------------------
    def push(
        self,
        text: str,
        color: Color = Palette.UI_ACCENT,
        icon: Optional[str] = None,
        life: float = 2.6,
    ) -> Toast:
        """Add a toast to the stack and return it."""
        toast = Toast(text, color=color, icon=icon, life=life)
        self.toasts.append(toast)
        # Cap the stack: retire the oldest survivors early so we never pile up.
        if len(self.toasts) > self.MAX_VISIBLE:
            overflow = self.toasts[: len(self.toasts) - self.MAX_VISIBLE]
            for t in overflow:
                # Hurry them off screen rather than yanking them mid-frame.
                t.age = max(t.age, t.life - Toast.OUT_TIME)
        return toast

    def clear(self) -> None:
        self.toasts.clear()

    def close(self) -> None:
        """Unsubscribe from the event bus (call on teardown)."""
        if self._unsub is not None:
            try:
                self._unsub()
            except Exception:
                pass
            self._unsub = None

    # -- per-frame -----------------------------------------------------------
    def update(self, dt: float) -> None:
        dt = max(0.0, dt)
        for toast in self.toasts:
            toast.update(dt)
        # Reap dead cards.
        self.toasts = [t for t in self.toasts if not t.dead]
        # Re-flow the stack: assign target slots top-down and ease each card's
        # y toward its slot so the whole column slides up when one expires.
        y = self.MARGIN
        for toast in self.toasts:
            toast.target_y = float(y)
            if toast._first_layout:
                toast.y = toast.target_y
                toast._first_layout = False
            else:
                toast.y = damp(toast.y, toast.target_y, 0.0001, dt)
            y += self.HEIGHT + self.GAP

    # -- drawing -------------------------------------------------------------
    def draw(self, surface: "pygame.Surface") -> None:
        try:
            for toast in self.toasts:
                self._draw_toast(surface, toast)
        except Exception:
            pass

    def _draw_toast(self, surface: "pygame.Surface", toast: Toast) -> None:
        alpha = toast.alpha()
        if alpha <= 0:
            return
        x = Config.WIDTH - self.WIDTH - self.MARGIN + int(toast.slide())
        y = int(toast.y)
        rect = pygame.Rect(x, y, self.WIDTH, self.HEIGHT)

        # Card body — translucent panel with an accent left edge in the toast's
        # colour, so a green "mission complete" reads differently from a red hit.
        panel(surface, rect, Palette.UI_PANEL, radius=12, border=2,
              border_color=toast.color, alpha=alpha)
        accent = pygame.Rect(rect.left + 3, rect.top + 8, 5, rect.height - 16)
        panel(surface, accent, toast.color, radius=3, alpha=alpha)

        # Optional icon glyph in a coloured chip.
        text_x = rect.left + 18
        if toast.icon:
            chip_c = rect.left + 34
            chip_cy = rect.centery
            try:
                pygame.draw.circle(surface, shade_color(toast.color, 0.5),
                                   (chip_c, chip_cy), 15)
            except Exception:
                pass
            draw_text(surface, str(toast.icon), (chip_c, chip_cy), 22,
                      Palette.WHITE, center=True, bold=True, alpha=alpha)
            text_x = rect.left + 56

        # Message, vertically centred, truncated if it would overflow the card.
        msg = self._fit(toast.text, rect.right - text_x - 12)
        draw_text(surface, msg, (text_x, rect.centery), 22, Palette.UI_TEXT,
                  center=False, bold=True, alpha=alpha)

    def _fit(self, text: str, max_width: int) -> str:
        """Ellipsize ``text`` so its rendered width fits ``max_width``."""
        if max_width <= 0:
            return ""
        font = get_font(22, bold=True)
        try:
            if font.size(text)[0] <= max_width:
                return text
            ell = "…"
            # Trim characters until the text plus ellipsis fits.
            trimmed = text
            while trimmed and font.size(trimmed + ell)[0] > max_width:
                trimmed = trimmed[:-1]
            return (trimmed + ell) if trimmed else ell
        except Exception:
            return text


__all__ = [
    "get_font",
    "draw_text",
    "panel",
    "Label",
    "Panel",
    "Button",
    "ProgressBar",
    "Toast",
    "ToastManager",
]
