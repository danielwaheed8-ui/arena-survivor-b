"""
Scenes — the top-level application flow.

A *scene* is a self-contained screen with three hooks: ``handle_event``,
``update(dt)`` and ``draw(surface)``. `Game` keeps exactly one active scene and
swaps them on navigation. Menus hand each other a ``return_to`` so Back always
works; starting a run replaces everything with :class:`PlayScene`.

`PlayScene` is where the engine and per-run systems come together. Its *inner*
flow (playing → paused → dying → game-over) is driven by the generic
:class:`StateMachine` from ``core.fsm`` — a real, declared FSM with validated
transitions — so the run can never end up in an illegal state (the class of bug
that made the original monolith's flow fragile).

The menu scenes are intentionally self-sufficient for their buttons (a compact
local widget) so this file does not hard-depend on the shape of the separate
widget toolkit; that toolkit is still used for the global toast stack.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional

import pygame

from .config import Config, Gameplay, Palette, Track as TCfg, shade_color
from .core.events import Event, EventBus, EventType
from .core.fsm import State, StateMachine
from .mathutils import RNG, clamp

# Engine (all first-party, already validated).
from .entities.collision import CollisionSystem
from .entities.player import Player, PlayerState
from .entities.spawner import Spawner, SpawnKnobs
from .render.camera import Camera
from .render.renderer import Renderer
from .ui.hud import HUD
from .world.track import Track


# ===========================================================================
# Tiny local widget: a button that doesn't depend on the external toolkit.
# ===========================================================================
_FONTS: Dict[tuple, pygame.font.Font] = {}


def font(size: int, bold: bool = False) -> pygame.font.Font:
    key = (size, bold)
    f = _FONTS.get(key)
    if f is None:
        f = pygame.font.SysFont("Arial", size, bold=bold)
        _FONTS[key] = f
    return f


def text(surface, s, pos, size, color, center=False, bold=False, shadow=True):
    fnt = font(size, bold)
    if shadow:
        sh = fnt.render(s, True, (0, 0, 0))
        sr = sh.get_rect()
        if center:
            sr.center = (pos[0] + 2, pos[1] + 2)
        else:
            sr.topleft = (pos[0] + 2, pos[1] + 2)
        surface.blit(sh, sr)
    img = fnt.render(s, True, color)
    r = img.get_rect()
    if center:
        r.center = pos
    else:
        r.topleft = pos
    surface.blit(img, r)
    return r


def panel(surface, rect, color=Palette.UI_PANEL, radius=12, border=0,
          border_color=Palette.UI_PANEL_LIGHT, alpha=255):
    rect = pygame.Rect(rect)
    if alpha < 255:
        s = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(s, (*color, alpha), s.get_rect(), border_radius=radius)
        surface.blit(s, rect.topleft)
    else:
        pygame.draw.rect(surface, color, rect, border_radius=radius)
    if border:
        pygame.draw.rect(surface, border_color, rect, border, border_radius=radius)


class Button:
    def __init__(self, rect, label, action: Optional[Callable] = None,
                 accent=Palette.UI_ACCENT, size=28):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.action = action
        self.accent = accent
        self.size = size
        self.hover = 0.0
        self.enabled = True

    def update(self, dt, mouse_pos):
        target = 1.0 if self.enabled and self.rect.collidepoint(mouse_pos) else 0.0
        self.hover += (target - self.hover) * min(1.0, dt * 14.0)

    def handle_event(self, event) -> bool:
        if not self.enabled:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                if self.action:
                    self.action()
                return True
        return False

    def draw(self, surface):
        base = Palette.UI_PANEL if self.enabled else (30, 30, 34)
        col = shade_color(base, 1.0 + 0.35 * self.hover)
        panel(surface, self.rect, col, radius=14, border=2,
              border_color=shade_color(self.accent, 0.5 + 0.5 * self.hover))
        lift = int(self.hover * 2)
        tcol = self.accent if self.enabled else Palette.UI_TEXT_DIM
        text(surface, self.label, (self.rect.centerx, self.rect.centery - lift),
             self.size, tcol, center=True, bold=True)


# ===========================================================================
# Scene base
# ===========================================================================
class Scene:
    def __init__(self, game):
        self.game = game
        self.bus: EventBus = game.bus
        self.buttons: List[Button] = []
        self.time = 0.0

    # hooks
    def on_enter(self):
        pass

    def on_exit(self):
        pass

    def handle_event(self, event):
        for b in self.buttons:
            b.handle_event(event)

    def update(self, dt):
        self.time += dt
        mp = pygame.mouse.get_pos()
        for b in self.buttons:
            b.update(dt, mp)

    def draw(self, surface):
        pass

    # helpers
    def _bg_gradient(self, surface, top=(26, 28, 40), bottom=(12, 12, 18)):
        h = surface.get_height()
        for i in range(0, h, 4):
            t = i / h
            c = (int(top[0] + (bottom[0] - top[0]) * t),
                 int(top[1] + (bottom[1] - top[1]) * t),
                 int(top[2] + (bottom[2] - top[2]) * t))
            surface.fill(c, (0, i, surface.get_width(), 4))


# ===========================================================================
# Main menu
# ===========================================================================
class MenuScene(Scene):
    def __init__(self, game):
        super().__init__(game)
        cx = Config.WIDTH // 2
        y = 300
        gap = 62
        self.buttons = [
            Button((cx - 150, y + gap * 0, 300, 52), "PLAY", game.go_play,
                   accent=Palette.SUCCESS, size=32),
            Button((cx - 150, y + gap * 1, 300, 48), "SHOP", lambda: game.go_shop(MenuScene)),
            Button((cx - 150, y + gap * 2, 300, 48), "MISSIONS",
                   lambda: game.go_missions(MenuScene)),
            Button((cx - 150, y + gap * 3, 300, 48), "ACHIEVEMENTS",
                   lambda: game.go_achievements(MenuScene)),
            Button((cx - 150, y + gap * 4, 300, 48), "SETTINGS",
                   lambda: game.go_settings(MenuScene)),
            Button((cx - 150, y + gap * 5, 300, 48), "QUIT", game.quit,
                   accent=Palette.DANGER),
        ]

    def on_enter(self):
        if self.game.audio:
            try:
                self.game.audio.play_music("menu")
            except Exception:
                pass

    def handle_event(self, event):
        super().handle_event(event)
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.game.go_play()

    def draw(self, surface):
        self._bg_gradient(surface)
        cx = Config.WIDTH // 2
        # Animated title.
        bob = math.sin(self.time * 2.0) * 6
        text(surface, "TEMPLE RUN", (cx, 150 + bob), 84, Palette.UI_ACCENT,
             center=True, bold=True)
        text(surface, "World-Class Python Edition", (cx, 215), 26,
             Palette.UI_TEXT_DIM, center=True)
        for b in self.buttons:
            b.draw(surface)
        # Stats footer.
        if self.game.save:
            d = self.game.save.data
            hs = d.get("high_score", 0)
            coins = d.get("coins_balance", d.get("total_coins", 0))
            text(surface, f"Best {hs:,}     Coins {coins:,}",
                 (cx, Config.HEIGHT - 40), 22, Palette.UI_TEXT_DIM, center=True)


# ===========================================================================
# Play scene — the run itself, with an FSM-driven inner flow.
# ===========================================================================
class PlayScene(Scene):
    S_PLAYING = "playing"
    S_PAUSED = "paused"
    S_DYING = "dying"
    S_GAMEOVER = "gameover"

    def __init__(self, game):
        super().__init__(game)
        seed = (pygame.time.get_ticks() * 2654435761) & 0xFFFFFFFF
        self.rng = RNG(seed)

        # Engine.
        self.track = Track(self.rng, self.bus)
        self.camera = Camera(self.rng)
        self.renderer = Renderer()
        self.player = Player(self.bus)
        self.spawner = Spawner(self.rng)
        self.collision = CollisionSystem(self.bus)
        self.hud = HUD()

        # Per-run systems (guarded — degrade to no-ops if a module is missing).
        self.particles = self._opt(lambda: __import__(
            "temple_run.fx.particles", fromlist=["ParticleSystem"]).ParticleSystem())
        self.scoring = self._opt(lambda: __import__(
            "temple_run.systems.scoring", fromlist=["ScoreSystem"]).ScoreSystem(self.bus))
        self.difficulty = self._opt(lambda: __import__(
            "temple_run.systems.difficulty", fromlist=["DifficultyDirector"]).DifficultyDirector())
        self.powerups = self._opt(lambda: __import__(
            "temple_run.systems.powerups", fromlist=["PowerupManager"]).PowerupManager(self.bus))

        self._death_timer = 0.0
        self._revive_used = False
        self._fps = 0.0

        # Inner FSM.
        self.fsm = self._build_fsm()

        # Event wiring for presentation + flow.
        self._subs: List[Callable] = []
        self._wire_events()

        # Overlay buttons (built lazily on enter of the state).
        self.pause_buttons: List[Button] = []
        self.over_buttons: List[Button] = []

    # -------------------------------------------------------------- utilities
    def _opt(self, factory):
        try:
            return factory()
        except Exception as exc:  # pragma: no cover
            print(f"[playscene] optional system unavailable: {exc}")
            return None

    def _build_fsm(self) -> StateMachine:
        fsm = StateMachine("play")
        fsm.add_state(self.S_PLAYING, _Delegate(self.S_PLAYING, self._update_playing))
        fsm.add_state(self.S_PAUSED, _Delegate(self.S_PAUSED))
        fsm.add_state(self.S_DYING, _Delegate(self.S_DYING, self._update_dying,
                                              self._enter_dying))
        fsm.add_state(self.S_GAMEOVER, _Delegate(self.S_GAMEOVER, None,
                                                 self._enter_gameover))
        fsm.allow(self.S_PLAYING, self.S_PAUSED, self.S_DYING)
        fsm.allow(self.S_PAUSED, self.S_PLAYING, self.S_GAMEOVER)
        fsm.allow(self.S_DYING, self.S_GAMEOVER)
        fsm.allow(self.S_GAMEOVER, self.S_PLAYING)
        return fsm

    def _player_screen(self):
        return (Config.WIDTH * 0.5 + self.player.x * 0.06, Config.HEIGHT * 0.72)

    # -------------------------------------------------------------- lifecycle
    def on_enter(self):
        self.start()

    def on_exit(self):
        for off in self._subs:
            try:
                off()
            except Exception:
                pass
        self._subs.clear()

    def start(self):
        self.player.reset()
        self.spawner.reset(self.player.world_z)
        self.collision.reset()
        if self.scoring:
            self.scoring.reset()
            if self.powerups:
                shop = self.game.shop
                self.scoring.set_score_multiplier_source(
                    lambda: self.powerups.score_mult() * self._shop_score_mult())
        if self.difficulty:
            self.difficulty.reset()
        if self.powerups:
            self.powerups.reset()
        if self.particles:
            self.particles.clear()

        # Shop-driven economy hooks.
        shop = self.game.shop
        if shop:
            try:
                self.spawner.coin_value = 1 + int(shop.coin_value_bonus())
            except Exception:
                self.spawner.coin_value = 1
            # Head start: skip ahead a bit of distance with a moment of safety.
            try:
                head = float(shop.head_start_units())
            except Exception:
                head = 0.0
            if head > 0:
                self.player.z += head
                self.player.distance += head
                self.spawner.reset(self.player.world_z)

        self._death_timer = 0.0
        self._revive_used = False

        if self.game.achievements:
            try:
                self.game.achievements.reset_run()
            except Exception:
                pass
        if self.game.missions:
            try:
                self.game.missions.reset_run()
            except Exception:
                pass

        self.player.start_running()
        self.fsm.start(self.S_PLAYING)
        self.bus.publish(Event(EventType.GAME_START, {}))
        if self.game.audio:
            try:
                self.game.audio.play_music("run")
            except Exception:
                pass

    def _shop_score_mult(self) -> int:
        shop = self.game.shop
        if not shop:
            return 1
        try:
            return max(1, int(shop.score_multiplier_bonus()))
        except Exception:
            return 1

    # ------------------------------------------------------------------ events
    def _wire_events(self):
        b = self.bus
        self._subs.append(b.subscribe(EventType.SCREEN_SHAKE, self._on_shake))
        self._subs.append(b.subscribe(EventType.COIN_COLLECTED, self._on_coin))
        self._subs.append(b.subscribe(EventType.GEM_COLLECTED, self._on_gem))
        self._subs.append(b.subscribe(EventType.POWERUP_COLLECTED, self._on_powerup))
        self._subs.append(b.subscribe(EventType.OBSTACLE_HIT, self._on_hit))
        self._subs.append(b.subscribe(EventType.NEAR_MISS, self._on_near))
        self._subs.append(b.subscribe(EventType.COMBO_CHANGED, self._on_combo))
        self._subs.append(b.subscribe(EventType.BIOME_CHANGED, self._on_biome))
        self._subs.append(b.subscribe(EventType.PLAYER_DIED, self._on_died))

    def _on_shake(self, e):
        if self.game.settings and not self.game.settings.screen_shake:
            return
        self.camera.add_shake(e.get("magnitude", 200.0))

    def _particles_on(self):
        return self.particles and (not self.game.settings or self.game.settings.particles)

    def _on_coin(self, e):
        if self._particles_on():
            x, y = self._player_screen()
            self.particles.burst_coins(x, y)

    def _on_gem(self, e):
        if self._particles_on():
            x, y = self._player_screen()
            self.particles.sparkle(x, y, Palette.GEM)

    def _on_powerup(self, e):
        if self._particles_on():
            from .entities.powerup_types import POWERUPS
            key = e.get("power")
            color = POWERUPS[key].color if key in POWERUPS else Palette.INFO
            x, y = self._player_screen()
            self.particles.powerup_burst(x, y, color)

    def _on_hit(self, e):
        if self._particles_on():
            x, y = self._player_screen()
            self.particles.burst_hit(x, y)

    def _on_near(self, e):
        if self._particles_on():
            x, y = self._player_screen()
            self.particles.ring(x, y, Palette.WARNING)

    def _on_combo(self, e):
        self.hud.on_combo()

    def _on_biome(self, e):
        biome = e.get("biome")
        if biome is not None:
            self.hud.on_biome_change(getattr(biome, "name", ""))

    def _on_died(self, e):
        if self.fsm.is_in(self.S_PLAYING):
            # Try a revive first if the shop upgrade is owned.
            if self._try_revive():
                return
            self.fsm.transition(self.S_DYING)

    def _try_revive(self) -> bool:
        shop = self.game.shop
        if self._revive_used or not shop:
            return False
        try:
            if shop.level("revive") <= 0:
                return False
        except Exception:
            return False
        # Consume it, clear nearby hazards, and grant a breather of invincibility.
        self._revive_used = True
        self.player.alive = True
        self.player.state = PlayerState.RUNNING
        self.player.y = 0.0
        self.player.vy = 0.0
        pz = self.player.world_z
        for ent in self.spawner.entities:
            if ent.collidable and getattr(ent, "pickup_kind", None) and \
                    ent.pickup_kind.name == "NONE" and abs(ent.z - pz) < 6000:
                ent.alive = False
                ent.collidable = False
        if self.powerups:
            try:
                self.powerups.grant("shield")
            except Exception:
                pass
        self.bus.emit(EventType.TOAST, text="REVIVED!", color=Palette.SUCCESS)
        return True

    # ------------------------------------------------------------------ input
    def handle_event(self, event):
        if self.fsm.is_in(self.S_PLAYING):
            self._input_playing(event)
        elif self.fsm.is_in(self.S_PAUSED):
            for btn in self.pause_buttons:
                btn.handle_event(event)
            if event.type == pygame.KEYDOWN and self._is_action(event.key, "pause"):
                self._resume()
        elif self.fsm.is_in(self.S_GAMEOVER):
            for btn in self.over_buttons:
                btn.handle_event(event)
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.game.go_play()

    def _is_action(self, key, action) -> bool:
        if self.game.input:
            try:
                return self.game.input.action_for(key) == action
            except Exception:
                pass
        # Fallback bindings.
        fallback = {
            "pause": (pygame.K_ESCAPE, pygame.K_p),
            "left": (pygame.K_LEFT, pygame.K_a),
            "right": (pygame.K_RIGHT, pygame.K_d),
            "jump": (pygame.K_UP, pygame.K_w, pygame.K_SPACE),
            "slide": (pygame.K_DOWN, pygame.K_s),
        }
        return key in fallback.get(action, ())

    def _input_playing(self, event):
        if event.type != pygame.KEYDOWN:
            return
        if self._is_action(event.key, "left"):
            self.player.move_left()
        elif self._is_action(event.key, "right"):
            self.player.move_right()
        elif self._is_action(event.key, "jump"):
            self.player.jump()
        elif self._is_action(event.key, "slide"):
            self.player.slide()
        elif self._is_action(event.key, "pause"):
            self._pause()

    def _pause(self):
        self.fsm.transition(self.S_PAUSED)
        self._build_pause_buttons()
        self.bus.publish(Event(EventType.PAUSE, {}))

    def _resume(self):
        self.fsm.transition(self.S_PLAYING)
        self.bus.publish(Event(EventType.RESUME, {}))

    def _build_pause_buttons(self):
        cx = Config.WIDTH // 2
        self.pause_buttons = [
            Button((cx - 140, 320, 280, 52), "RESUME", self._resume,
                   accent=Palette.SUCCESS),
            Button((cx - 140, 384, 280, 52), "RESTART", self.game.go_play),
            Button((cx - 140, 448, 280, 52), "QUIT TO MENU", self.game.go_menu,
                   accent=Palette.DANGER),
        ]

    def _build_over_buttons(self):
        cx = Config.WIDTH // 2
        self.over_buttons = [
            Button((cx - 140, 430, 280, 52), "RETRY", self.game.go_play,
                   accent=Palette.SUCCESS),
            Button((cx - 140, 494, 280, 48), "SHOP", lambda: self.game.go_shop(MenuScene)),
            Button((cx - 140, 550, 280, 48), "MENU", self.game.go_menu,
                   accent=Palette.DANGER),
        ]

    # ------------------------------------------------------------------ update
    def update(self, dt):
        self.time += dt
        self._fps = self.game.clock.get_fps()
        self.fsm.update(dt)
        # Overlay button hovers.
        mp = pygame.mouse.get_pos()
        if self.fsm.is_in(self.S_PAUSED):
            for b in self.pause_buttons:
                b.update(dt, mp)
        elif self.fsm.is_in(self.S_GAMEOVER):
            for b in self.over_buttons:
                b.update(dt, mp)

    def _update_playing(self, dt):
        knobs = self._knobs(dt)
        self.player.update(dt, self.track)
        self.track.update(self.player.z)
        self.spawner.update(self.player, self.track, knobs)
        self.spawner.update_entities(dt)
        if self.powerups and self.powerups.magnet_active():
            self.spawner.apply_magnet(self.player, dt)
        self.camera.update(self.player, self.track, dt)
        inv = self.powerups.is_invincible() if self.powerups else False
        coin_mult = self.powerups.coin_mult() if self.powerups else 1
        self.collision.resolve(self.player, self.spawner.entities, inv, coin_mult)
        if self.scoring:
            self.scoring.update(dt, self.player.distance)
        if self.powerups:
            self.powerups.update(dt)
        self.hud.update(dt)
        if self.particles:
            self.particles.update(dt)
            # Ambient run dust.
            if self.player.on_ground and self.rng.chance(0.5) and self._particles_on():
                x, y = self._player_screen()
                self.particles.dust(x + self.rng.range(-20, 20), y)

    def _knobs(self, dt) -> SpawnKnobs:
        if self.difficulty:
            try:
                return self.difficulty.update(dt, self.player)
            except Exception:
                pass
        # Fallback: gently accelerate and keep a fair, speed-scaled gap.
        self.player.speed = min(self.player.speed + 90.0 * dt, 15000.0)
        gap = max(2600.0, self.player.effective_speed * 0.62)
        return SpawnKnobs(feature_gap=gap)

    def _enter_dying(self, payload):
        self._death_timer = 1.4

    def _update_dying(self, dt):
        self._death_timer -= dt
        # Keep the world animating as the player crumples.
        self.player.update(dt, self.track)
        self.camera.update(self.player, self.track, dt)
        if self.particles:
            self.particles.update(dt)
        self.hud.update(dt)
        if self._death_timer <= 0.0:
            self.fsm.transition(self.S_GAMEOVER)

    def _enter_gameover(self, payload):
        self._build_over_buttons()
        snap = self.snapshot()
        # Capture the previous best BEFORE the run is recorded so we can honestly
        # detect a new record (the GAME_OVER handler updates high_score in place).
        prev_high = self.game.save.data.get("high_score", 0) if self.game.save else 0
        self._is_new_best = snap["score"] > prev_high and snap["score"] > 0
        self._final_snapshot = snap
        # Persistence is driven by the GAME_OVER event alone: SaveManager
        # subscribes to it and records + flushes the run. Publishing here (and
        # NOT also calling record_run) keeps a single source of truth and avoids
        # double-counting the run in the lifetime totals.
        self.bus.publish(Event(EventType.GAME_OVER, {
            "score": snap["score"], "coins": snap["coins"],
            "gems": snap["gems"], "distance_m": snap["distance_m"]}))

    # ---------------------------------------------------------------- snapshot
    def snapshot(self) -> dict:
        snap = {
            "score": 0, "coins": 0, "gems": 0, "distance_m": 0,
            "combo": 1.0, "combo_active": False, "speed_kmh": 0,
            "high_score": 0, "level": 1, "biome_name": "", "powerups": [],
            "state": self.fsm.current_key,
        }
        if self.scoring:
            try:
                snap.update(self.scoring.snapshot())
            except Exception:
                pass
        snap["distance_m"] = int(self.player.distance * Gameplay.METERS_PER_UNIT)
        snap["speed_kmh"] = int(self.player.effective_speed * 0.02)
        if self.game.save:
            snap["high_score"] = self.game.save.data.get("high_score", 0)
        if self.difficulty:
            try:
                snap.update(self.difficulty.snapshot())
            except Exception:
                pass
        if self.powerups:
            try:
                snap["powerups"] = self.powerups.active_list()
            except Exception:
                snap["powerups"] = []
        return snap

    # ------------------------------------------------------------------- draw
    def draw(self, surface):
        self.renderer.render_world(surface, self.track, self.player,
                                   self.camera, self.spawner.entities, self.time)
        if self.particles:
            try:
                self.particles.draw(surface)
            except Exception:
                pass
        snap = self.snapshot()
        show_fps = bool(self.game.settings and self.game.settings.show_fps)
        self.hud.draw(surface, snap, self._fps, show_fps)

        if self.fsm.is_in(self.S_PAUSED):
            self._draw_pause(surface)
        elif self.fsm.is_in(self.S_GAMEOVER):
            self._draw_gameover(surface, snap)

    def _dim(self, surface, alpha=150):
        s = pygame.Surface((Config.WIDTH, Config.HEIGHT), pygame.SRCALPHA)
        s.fill((0, 0, 0, alpha))
        surface.blit(s, (0, 0))

    def _draw_pause(self, surface):
        self._dim(surface, 150)
        text(surface, "PAUSED", (Config.WIDTH // 2, 220), 72, Palette.UI_TEXT,
             center=True, bold=True)
        for b in self.pause_buttons:
            b.draw(surface)

    def _draw_gameover(self, surface, snap):
        self._dim(surface, 175)
        cx = Config.WIDTH // 2
        text(surface, "GAME OVER", (cx, 150), 80, Palette.DANGER, center=True, bold=True)
        text(surface, f"Score  {snap['score']:,}", (cx, 250), 40,
             Palette.UI_TEXT, center=True, bold=True)
        text(surface, f"{snap['distance_m']} m    ·    {snap['coins']} coins    ·    {snap['gems']} gems",
             (cx, 300), 24, Palette.UI_TEXT_DIM, center=True)
        if getattr(self, "_is_new_best", False):
            text(surface, "NEW BEST!", (cx, 345), 30, Palette.GOLD, center=True, bold=True)
        for b in self.over_buttons:
            b.draw(surface)


class _Delegate(State):
    """A State that forwards its hooks to plain callbacks (keeps PlayScene flat)."""

    def __init__(self, name, on_update=None, on_enter=None, on_exit=None):
        super().__init__(name)
        self._u = on_update
        self._e = on_enter
        self._x = on_exit

    def on_enter(self, payload):
        if self._e:
            self._e(payload)

    def on_exit(self):
        if self._x:
            self._x()

    def update(self, dt):
        if self._u:
            self._u(dt)


# ===========================================================================
# Simple list/menu sub-scenes (settings / shop / achievements / missions / help)
# ===========================================================================
class _SubScene(Scene):
    title = "SCREEN"

    def __init__(self, game, return_to=None):
        super().__init__(game)
        self.return_to = return_to or MenuScene
        self.buttons = [
            Button((40, Config.HEIGHT - 74, 200, 48), "< BACK", self._back,
                   accent=Palette.DANGER),
        ]

    def _back(self):
        self.game.set_scene(self.return_to(self.game))

    def handle_event(self, event):
        super().handle_event(event)
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._back()

    def draw(self, surface):
        self._bg_gradient(surface)
        text(surface, self.title, (Config.WIDTH // 2, 60), 56,
             Palette.UI_ACCENT, center=True, bold=True)
        self.draw_body(surface)
        for b in self.buttons:
            b.draw(surface)

    def draw_body(self, surface):
        pass


class SettingsScene(_SubScene):
    title = "SETTINGS"

    def __init__(self, game, return_to=None):
        super().__init__(game, return_to)
        self._build()

    def _build(self):
        s = self.game.settings
        cx = Config.WIDTH // 2
        y = 170
        self.rows = []
        if not s:
            return

        def vol_row(label, getter, inc):
            return (label, getter, inc)

        self.buttons += [
            Button((cx + 120, y, 44, 40), "-", lambda: self._vol("sfx", -0.1)),
            Button((cx + 172, y, 44, 40), "+", lambda: self._vol("sfx", 0.1)),
            Button((cx + 120, y + 60, 44, 40), "-", lambda: self._vol("music", -0.1)),
            Button((cx + 172, y + 60, 44, 40), "+", lambda: self._vol("music", 0.1)),
            Button((cx + 120, y + 120, 96, 40), "Toggle", lambda: self._toggle("particles")),
            Button((cx + 120, y + 180, 96, 40), "Toggle", lambda: self._toggle("screen_shake")),
            Button((cx + 120, y + 240, 96, 40), "Toggle", lambda: self._toggle("show_fps")),
        ]

    def _vol(self, which, delta):
        s = self.game.settings
        if not s:
            return
        if which == "sfx":
            s.sfx_volume = clamp(s.sfx_volume + delta, 0, 1)
            if self.game.audio:
                self.game.audio.set_sfx_volume(s.sfx_volume)
        else:
            s.music_volume = clamp(s.music_volume + delta, 0, 1)
            if self.game.audio:
                self.game.audio.set_music_volume(s.music_volume)
        s.save()
        self.bus.emit(EventType.UI_BUTTON)

    def _toggle(self, attr):
        s = self.game.settings
        if not s:
            return
        setattr(s, attr, not getattr(s, attr))
        s.save()
        self.bus.emit(EventType.UI_BUTTON)

    def draw_body(self, surface):
        s = self.game.settings
        cx = Config.WIDTH // 2
        y = 170
        if not s:
            text(surface, "Settings unavailable.", (cx, 260), 26,
                 Palette.UI_TEXT_DIM, center=True)
            return
        rows = [
            (f"SFX Volume   {int(s.sfx_volume * 100)}%", y),
            (f"Music Volume   {int(s.music_volume * 100)}%", y + 60),
            (f"Particles   {'ON' if s.particles else 'OFF'}", y + 120),
            (f"Screen Shake   {'ON' if s.screen_shake else 'OFF'}", y + 180),
            (f"Show FPS   {'ON' if s.show_fps else 'OFF'}", y + 240),
        ]
        for label, ry in rows:
            text(surface, label, (cx - 300, ry + 8), 26, Palette.UI_TEXT)


class ShopScene(_SubScene):
    title = "SHOP"

    def __init__(self, game, return_to=None):
        super().__init__(game, return_to)
        self._build()

    def _build(self):
        shop = self.game.shop
        if not shop:
            return
        try:
            self.items = shop.catalog()
        except Exception:
            self.items = []
        y = 150
        for i, it in enumerate(self.items[:7]):
            iid = it.get("id")
            self.buttons.append(
                Button((Config.WIDTH - 260, y + i * 62, 200, 48), "BUY",
                       (lambda k=iid: self._buy(k)), accent=Palette.GOLD))

    def _buy(self, item_id):
        shop = self.game.shop
        if shop and shop.buy(item_id):
            self._build_refresh()

    def _build_refresh(self):
        # Rebuild the catalogue snapshot after a purchase.
        self.buttons = self.buttons[:1]  # keep BACK
        self._build()

    def draw_body(self, surface):
        shop = self.game.shop
        if not shop:
            text(surface, "Shop unavailable.", (Config.WIDTH // 2, 260), 26,
                 Palette.UI_TEXT_DIM, center=True)
            return
        bal = self.game.save.data.get("coins_balance", 0) if self.game.save else 0
        text(surface, f"Coins: {bal:,}", (Config.WIDTH // 2, 110), 28,
             Palette.GOLD, center=True, bold=True)
        try:
            items = shop.catalog()
        except Exception:
            items = []
        y = 150
        for it in items[:7]:
            panel(surface, (60, y, Config.WIDTH - 340, 52), Palette.UI_PANEL,
                  radius=10, border=1)
            text(surface, it.get("name", "?"), (80, y + 6), 24, Palette.UI_TEXT, bold=True)
            lvl = it.get("level", 0)
            mx = it.get("max", 1)
            desc = it.get("desc", "")
            lvltxt = f"Lv {lvl}/{mx}" if mx > 1 else ("OWNED" if lvl else "")
            text(surface, f"{desc}   {lvltxt}", (80, y + 30), 18, Palette.UI_TEXT_DIM)
            price = it.get("price", 0)
            maxed = lvl >= mx
            text(surface, "MAX" if maxed else f"{price}",
                 (Config.WIDTH - 300, y + 14), 24,
                 Palette.SUCCESS if not maxed else Palette.UI_TEXT_DIM)
            y += 62


class AchievementsScene(_SubScene):
    title = "ACHIEVEMENTS"

    def __init__(self, game, return_to=None):
        super().__init__(game, return_to)
        self.scroll = 0

    def handle_event(self, event):
        super().handle_event(event)
        if event.type == pygame.MOUSEWHEEL:
            self.scroll = clamp(self.scroll - event.y * 40, 0, 4000)

    def draw_body(self, surface):
        ach = self.game.achievements
        if not ach:
            text(surface, "Achievements unavailable.", (Config.WIDTH // 2, 260),
                 26, Palette.UI_TEXT_DIM, center=True)
            return
        try:
            items = ach.snapshot()
        except Exception:
            items = []
        y = 140 - self.scroll
        unlocked = sum(1 for a in items if a.get("unlocked"))
        text(surface, f"{unlocked}/{len(items)} unlocked",
             (Config.WIDTH // 2, 105), 22, Palette.UI_TEXT_DIM, center=True)
        for a in items:
            if -60 < y < Config.HEIGHT:
                on = a.get("unlocked")
                col = Palette.GOLD if on else Palette.UI_PANEL
                panel(surface, (120, y, Config.WIDTH - 240, 56), col if on else Palette.UI_PANEL,
                      radius=10, border=2, border_color=Palette.GOLD if on else Palette.UI_PANEL_LIGHT)
                text(surface, a.get("name", "?"), (140, y + 6), 24,
                     Palette.UI_TEXT if on else Palette.UI_TEXT_DIM, bold=True)
                text(surface, a.get("description", ""), (140, y + 32), 17,
                     Palette.UI_TEXT_DIM)
                prog = a.get("progress", 0)
                goal = a.get("goal", 1) or 1
                text(surface, ("DONE" if on else f"{int(prog)}/{int(goal)}"),
                     (Config.WIDTH - 200, y + 16), 22,
                     Palette.SUCCESS if on else Palette.UI_TEXT_DIM)
            y += 66


class MissionsScene(_SubScene):
    title = "MISSIONS"

    def draw_body(self, surface):
        ms = self.game.missions
        if not ms:
            text(surface, "Missions unavailable.", (Config.WIDTH // 2, 260),
                 26, Palette.UI_TEXT_DIM, center=True)
            return
        try:
            items = ms.snapshot()
        except Exception:
            items = []
        y = 180
        for m in items:
            panel(surface, (160, y, Config.WIDTH - 320, 84), Palette.UI_PANEL,
                  radius=12, border=1)
            text(surface, m.get("text", "?"), (185, y + 12), 26, Palette.UI_TEXT, bold=True)
            prog = m.get("progress", 0)
            goal = m.get("goal", 1) or 1
            frac = clamp(prog / goal, 0, 1)
            bar = pygame.Rect(185, y + 50, Config.WIDTH - 320 - 50, 16)
            panel(surface, bar, (40, 40, 48), radius=8)
            fill = pygame.Rect(bar.x, bar.y, int(bar.width * frac), bar.height)
            panel(surface, fill, Palette.SUCCESS if m.get("done") else Palette.UI_ACCENT, radius=8)
            text(surface, f"{int(prog)}/{int(goal)}   +{m.get('reward', 0)} coins",
                 (bar.right - 4, y + 14), 18, Palette.GOLD)
            y += 100


class HelpScene(_SubScene):
    title = "HOW TO PLAY"

    def draw_body(self, surface):
        cx = Config.WIDTH // 2
        lines = [
            "LEFT / RIGHT  (A / D)   —   change lanes",
            "UP / W / SPACE   —   jump over low barriers",
            "DOWN / S   —   slide under high beams",
            "ESC / P   —   pause",
            "",
            "Grab coins and gems, chain them for combo multipliers,",
            "collect powerups (magnet, shield, boost, x2),",
            "and run as far as you can. The temple never ends.",
        ]
        y = 200
        for ln in lines:
            text(surface, ln, (cx, y), 26, Palette.UI_TEXT, center=True)
            y += 44
