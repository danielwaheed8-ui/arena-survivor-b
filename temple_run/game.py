"""
The application shell.

`Game` owns the pygame window, the fixed-timestep main loop, and the systems that
must **persist across scenes** — the event bus, settings, save profile, audio,
input, shop, achievements, missions and the global toast stack. Everything that
belongs to a single run (the track, player, renderer, scoring, …) lives inside
the `PlayScene` in `scenes.py`.

Scene switching is a simple replace-with-optional-return model: menus hand each
other a `return_to` scene so "Back" always works, while starting a run replaces
the whole scene. The loop clamps delta-time (a debugger pause can never teleport
the player through a wall) and draws the toast stack on top of whatever scene is
active.
"""

from __future__ import annotations

import sys
from typing import Optional

import pygame

from .config import Config
from .core.events import Event, EventBus, EventType
from .mathutils import RNG


# Running inside a browser via pygbag / Emscripten? A few things differ there:
# there is no real audio mixer worth spinning up, system fonts are absent, and
# Python-in-WASM is slower, so we trim the draw distance for a smoother frame.
IS_WEB = (sys.platform == "emscripten")


class Game:
    def __init__(self) -> None:
        pygame.init()
        if not IS_WEB:
            try:
                pygame.mixer.pre_init(44100, -16, 2, 512)
            except Exception:
                pass
        else:
            # Lighter render load for the WASM build.
            from .config import Cam
            Cam.DRAW_DISTANCE = min(Cam.DRAW_DISTANCE, 150)
        self.screen = pygame.display.set_mode((Config.WIDTH, Config.HEIGHT))
        pygame.display.set_caption(Config.TITLE)
        self.clock = pygame.time.Clock()
        self.running = True
        self.rng = RNG()

        # --- persistent systems ------------------------------------------------
        self.bus = EventBus()
        self.settings = self._make_settings()
        self.save = self._make_save()
        self.audio = self._make_audio()
        self.input = self._make_input()
        self.shop = self._make_shop()
        self.achievements = self._make_achievements()
        self.missions = self._make_missions()
        self.toasts = self._make_toasts()

        self.bus.subscribe(EventType.QUIT, lambda e: self.quit())

        # Apply persisted audio volumes if the engine came up.
        self._sync_audio_volumes()

        # Start on the main menu.
        self.scene = None
        self.go_menu()

    # ---------------------------------------------------------- system factories
    # These are wrapped so a single missing/So-far-unbuilt module degrades to a
    # harmless stub instead of crashing the whole game during development.
    def _make_settings(self):
        try:
            from .systems.settings import Settings
            s = Settings()
            s.load()
            return s
        except Exception as exc:  # pragma: no cover
            print(f"[settings] unavailable: {exc}")
            return None

    def _make_save(self):
        try:
            from .systems.save import SaveManager
            sv = SaveManager(event_bus=self.bus)
            sv.load()
            return sv
        except Exception as exc:  # pragma: no cover
            print(f"[save] unavailable: {exc}")
            return None

    def _make_audio(self):
        # Skip procedural audio synthesis in the browser build: the mixer is
        # unreliable under Emscripten and generating the sound buffers in WASM
        # would stall startup for seconds. The game runs silent there.
        if IS_WEB:
            return None
        try:
            from .audio.engine import AudioEngine
            get_sfx = (lambda: self.settings.sfx_volume) if self.settings else None
            get_music = (lambda: self.settings.music_volume) if self.settings else None
            return AudioEngine(self.bus, get_sfx, get_music)
        except Exception as exc:  # pragma: no cover
            print(f"[audio] unavailable: {exc}")
            return None

    def _make_input(self):
        try:
            from .input.input_manager import InputManager
            return InputManager(self.settings)
        except Exception as exc:  # pragma: no cover
            print(f"[input] unavailable: {exc}")
            return None

    def _make_shop(self):
        try:
            from .systems.shop import Shop
            return Shop(self.bus, self.save)
        except Exception as exc:  # pragma: no cover
            print(f"[shop] unavailable: {exc}")
            return None

    def _make_achievements(self):
        try:
            from .systems.achievements import AchievementSystem
            return AchievementSystem(self.bus, self.save)
        except Exception as exc:  # pragma: no cover
            print(f"[achievements] unavailable: {exc}")
            return None

    def _make_missions(self):
        try:
            from .systems.missions import MissionSystem
            return MissionSystem(self.bus, self.save, self.rng)
        except Exception as exc:  # pragma: no cover
            print(f"[missions] unavailable: {exc}")
            return None

    def _make_toasts(self):
        try:
            from .ui.widgets import ToastManager
            return ToastManager(self.bus)
        except Exception as exc:  # pragma: no cover
            print(f"[toasts] unavailable: {exc}")
            return None

    def _sync_audio_volumes(self) -> None:
        if self.audio and self.settings:
            try:
                self.audio.set_sfx_volume(self.settings.sfx_volume)
                self.audio.set_music_volume(self.settings.music_volume)
            except Exception:
                pass

    # ------------------------------------------------------------ scene switching
    def set_scene(self, scene) -> None:
        old = self.scene
        if old is not None and hasattr(old, "on_exit"):
            old.on_exit()
        self.scene = scene
        if scene is not None and hasattr(scene, "on_enter"):
            scene.on_enter()

    def go_menu(self) -> None:
        from .scenes import MenuScene
        self.set_scene(MenuScene(self))

    def go_play(self) -> None:
        from .scenes import PlayScene
        self.set_scene(PlayScene(self))

    def go_settings(self, return_to=None) -> None:
        from .scenes import SettingsScene
        self.set_scene(SettingsScene(self, return_to))

    def go_shop(self, return_to=None) -> None:
        from .scenes import ShopScene
        self.set_scene(ShopScene(self, return_to))

    def go_achievements(self, return_to=None) -> None:
        from .scenes import AchievementsScene
        self.set_scene(AchievementsScene(self, return_to))

    def go_missions(self, return_to=None) -> None:
        from .scenes import MissionsScene
        self.set_scene(MissionsScene(self, return_to))

    def go_help(self, return_to=None) -> None:
        from .scenes import HelpScene
        self.set_scene(HelpScene(self, return_to))

    # ---------------------------------------------------------------- main loop
    def quit(self) -> None:
        self.running = False

    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(Config.FPS) / 1000.0
            dt = min(dt, Config.MAX_DT)
            self._handle_events()
            if not self.running:
                break
            self._update(dt)
            self._draw()
            pygame.display.flip()
        self._shutdown()

    async def run_async(self) -> None:
        """Cooperative main loop for the browser (pygbag) build.

        Identical to :meth:`run` but yields to the event loop each frame via
        ``await asyncio.sleep(0)`` so the browser stays responsive. Works on the
        desktop too, so a single async entry point serves both targets.
        """
        import asyncio
        while self.running:
            dt = self.clock.tick(Config.FPS) / 1000.0
            dt = min(dt, Config.MAX_DT)
            self._handle_events()
            if not self.running:
                break
            self._update(dt)
            self._draw()
            pygame.display.flip()
            await asyncio.sleep(0)
        self._shutdown()

    def one_frame(self, dt: float) -> None:
        """Advance and draw a single frame (handy for tests / embedding)."""
        self._handle_events()
        self._update(dt)
        self._draw()
        pygame.display.flip()

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.quit()
                return
            if self.scene is not None:
                self.scene.handle_event(event)

    def _update(self, dt: float) -> None:
        if self.scene is not None:
            self.scene.update(dt)
        if self.toasts is not None:
            try:
                self.toasts.update(dt)
            except Exception:
                pass

    def _draw(self) -> None:
        if self.scene is not None:
            self.scene.draw(self.screen)
        if self.toasts is not None:
            try:
                self.toasts.draw(self.screen)
            except Exception:
                pass

    def _shutdown(self) -> None:
        try:
            if self.save is not None:
                self.save.save()
        except Exception:
            pass
        pygame.quit()


def main() -> None:
    game = Game()
    game.run()
    sys.exit(0)


async def amain() -> None:
    """Async entry used by the browser (pygbag) build and by ``main.py``."""
    game = Game()
    await game.run_async()


if __name__ == "__main__":
    main()
