"""
Procedural audio engine: synthesized SFX and a chiptune music sequencer.

Design & rationale
-------------------
Shipping a game with dozens of ``.wav`` assets is a pain: they bloat the repo,
they need licensing, and they are annoying to tweak. For a game whose whole
aesthetic is "clean, procedural, self-contained", it is far nicer to *generate*
every sound at boot from a handful of oscillators. That is exactly what this
module does — there is not a single audio file anywhere in the project.

Two subsystems live here:

1. **A tiny synthesizer.** :func:`AudioEngine.make_tone` builds a
   ``pygame.mixer.Sound`` from a frequency, a duration and a waveform
   (sine / square / triangle / sawtooth / noise), applies a pitch *sweep* and an
   ADSR-ish amplitude envelope, and packs the result into a correct 16-bit
   *stereo* buffer. On top of that, :meth:`AudioEngine._build_library` bakes a
   named library of one-shot effects (``coin``, ``jump``, ``hit`` …) once at
   startup so playback is just "grab the pre-rendered Sound and play it".

2. **A chiptune sequencer.** Music is described as small note tables (a mood is
   a list of ``(semitone_or_None, beats)`` steps). :meth:`play_music` renders a
   mood into a single looping ``Sound`` and drives it on a dedicated
   ``pygame.mixer.Channel``. :meth:`update` babysits the loop so a track keeps
   playing seamlessly across scene changes.

The engine is wired to the :class:`~temple_run.core.events.EventBus`: it
subscribes to gameplay events (coins, jumps, hits …) and plays the matching
effect automatically, so game logic never has to know audio exists — it just
publishes ``COIN_COLLECTED`` and a *ding* happens.

Robustness
----------
Audio is the single most fragile subsystem on a random machine: the mixer may
fail to open a device, a driver may be missing, a buffer may be rejected. Every
public method therefore degrades **silently** — if the mixer never initialised,
``self.enabled`` is ``False`` and every call is a cheap no-op. Nothing in here
is allowed to raise into the game loop.

Only stdlib (``array``, ``math``, ``random``, ``sys``) and ``pygame`` are used;
notably we do *not* depend on ``numpy`` for buffer construction.
"""

from __future__ import annotations

import array
import math
import random
import sys
from typing import Callable, Dict, List, Optional, Tuple

import pygame

from ..core.events import Event, EventBus, EventType

# ---------------------------------------------------------------------------
# Synthesis constants
# ---------------------------------------------------------------------------
SAMPLE_RATE = 44100          # Hz — CD quality; matches the mixer init below.
BIT_WIDTH = -16              # signed 16-bit samples (pygame's format code).
CHANNELS = 2                 # stereo.
BUFFER_SIZE = 512            # mixer chunk size; small = low latency.
MAX_AMPLITUDE = 32767        # peak value of a signed 16-bit sample.

# Equal-tempered semitone ratio: multiplying a frequency by this raises it one
# semitone. Used by the sequencer to turn note numbers into Hz.
SEMITONE = 2.0 ** (1.0 / 12.0)
# Reference pitch: MIDI-ish note 0 in our tables maps to this frequency (A3).
BASE_FREQ = 220.0

# A "music channel" reserved index. We use a high index so it does not collide
# with the default SFX channels the mixer hands out via ``Sound.play``.
MUSIC_CHANNEL_INDEX = 7


class AudioEngine:
    """Owns the mixer, a baked SFX library, and a looping music sequencer.

    Parameters
    ----------
    event_bus:
        The shared :class:`EventBus`. The engine subscribes to gameplay events
        and auto-plays the matching SFX.
    get_sfx_volume / get_music_volume:
        Optional ``() -> float`` callables (typically bound to the settings
        object) queried on every play so a volume change takes effect live. If
        omitted, the engine keeps its own internal volume fields instead.
    """

    def __init__(
        self,
        event_bus: EventBus,
        get_sfx_volume: Optional[Callable[[], float]] = None,
        get_music_volume: Optional[Callable[[], float]] = None,
    ) -> None:
        self.event_bus = event_bus
        self._get_sfx_volume = get_sfx_volume
        self._get_music_volume = get_music_volume

        # Internal fallbacks used when no getter is supplied.
        self._sfx_volume = 0.7
        self._music_volume = 0.5

        # Populated by _build_library(); name -> Sound.
        self.sounds: Dict[str, pygame.mixer.Sound] = {}

        # Music state.
        self._music_channel: Optional[pygame.mixer.Channel] = None
        self._music_cache: Dict[str, pygame.mixer.Sound] = {}
        self._current_music: Optional[str] = None
        # Slight jitter timer so update() only polls the loop occasionally.
        self._music_poll = 0.0

        # Try to bring the mixer up. If it fails we run "deaf" but never crash.
        self.enabled = self._init_mixer()

        if self.enabled:
            self._build_library()
            self._music_channel = pygame.mixer.Channel(MUSIC_CHANNEL_INDEX)

        # Always subscribe: if disabled the handlers are cheap no-ops, and this
        # keeps behaviour identical whether or not audio came up.
        self._subscribe_events()

    # ------------------------------------------------------------------ setup
    def _init_mixer(self) -> bool:
        """Bring up ``pygame.mixer``; return True on success, False otherwise."""
        try:
            # pre_init lets us pick the format even if pygame.init() already ran.
            pygame.mixer.pre_init(SAMPLE_RATE, BIT_WIDTH, CHANNELS, BUFFER_SIZE)
            pygame.mixer.init(SAMPLE_RATE, BIT_WIDTH, CHANNELS, BUFFER_SIZE)
        except (pygame.error, Exception):  # noqa: BLE001 - never let audio kill the game
            return False
        # Confirm the mixer actually opened (some drivers "succeed" then report
        # None from get_init()).
        return pygame.mixer.get_init() is not None

    def _subscribe_events(self) -> None:
        """Map gameplay events onto SFX names so playback is automatic."""
        bus = self.event_bus
        # (event type, sfx name) — the payload is irrelevant for the sound.
        wiring: Tuple[Tuple[EventType, str], ...] = (
            (EventType.COIN_COLLECTED, "coin"),
            (EventType.GEM_COLLECTED, "gem"),
            (EventType.PLAYER_JUMP, "jump"),
            (EventType.PLAYER_LAND, "land"),
            (EventType.PLAYER_SLIDE, "slide"),
            (EventType.OBSTACLE_HIT, "hit"),
            (EventType.POWERUP_COLLECTED, "powerup"),
            (EventType.UI_BUTTON, "button"),
            (EventType.MILESTONE_REACHED, "milestone"),
            (EventType.PLAYER_LANE_CHANGE, "lanechange"),
            (EventType.COMBO_CHANGED, "combo"),
            (EventType.NEAR_MISS, "whoosh"),
        )
        for event_type, name in wiring:
            bus.subscribe(event_type, self._make_sfx_handler(name))

    def _make_sfx_handler(self, name: str) -> Callable[[Event], None]:
        """Return a listener that plays ``name`` when it fires.

        A tiny bit of context-sensitivity lives here: a *fatal* obstacle hit
        should sound heavier than a glancing one, and the combo chime is
        suppressed while a combo is merely decaying (``active`` False) so the
        HUD does not spam a note every frame.
        """

        def _handler(event: Event) -> None:
            if not self.enabled:
                return
            # COMBO_CHANGED fires on decay too; only chime when it's meaningful.
            if name == "combo" and not event.get("active", True):
                return
            self.play(name)

        return _handler

    # -------------------------------------------------------------- synthesis
    def make_tone(
        self,
        freq: float,
        duration: float,
        volume: float = 1.0,
        wave: str = "sine",
        sweep: Optional[float] = None,
        noise: bool = False,
    ) -> Optional[pygame.mixer.Sound]:
        """Synthesize a single tone and return it as a ``pygame.mixer.Sound``.

        Parameters
        ----------
        freq:
            Base frequency in Hz.
        duration:
            Length in seconds.
        volume:
            Peak amplitude scale in ``[0, 1]`` *before* the runtime volume.
        wave:
            One of ``"sine"``, ``"square"``, ``"triangle"``, ``"saw"``. Ignored
            when ``noise`` is set.
        sweep:
            Optional target frequency in Hz. When given, the pitch glides
            linearly from ``freq`` to ``sweep`` across the duration (great for
            coin *blips* and whooshes).
        noise:
            When True the tone is filtered white noise instead of an oscillator
            (used for hits / slides / percussive textures).

        The samples are shaped by a short attack and a decay-to-silence release
        (an ADSR-ish envelope) so tones never *click* at their edges, then
        packed into an interleaved 16-bit **stereo** buffer.
        """
        if not self.enabled:
            return None
        try:
            return self._render_tone(freq, duration, volume, wave, sweep, noise)
        except Exception:  # noqa: BLE001 - a bad tone must never crash boot
            return None

    def _render_tone(
        self,
        freq: float,
        duration: float,
        volume: float,
        wave: str,
        sweep: Optional[float],
        noise: bool,
    ) -> pygame.mixer.Sound:
        """The actual sample loop behind :meth:`make_tone`."""
        n = max(1, int(SAMPLE_RATE * max(0.0, duration)))
        buf = array.array("h", bytes(4 * n))  # 2 channels * 2 bytes, zeroed.

        # Envelope shape: quick attack, then a smooth exponential-ish decay so
        # every effect "plops" rather than cutting off with a click.
        attack = max(1, int(n * 0.02))
        vol = _clamp01(volume)

        two_pi = 2.0 * math.pi
        phase = 0.0
        for i in range(n):
            t = i / n  # normalised time 0..1 across the tone.

            # Instantaneous frequency (linear glide toward ``sweep`` if given).
            f = freq if sweep is None else freq + (sweep - freq) * t

            if noise:
                sample = random.uniform(-1.0, 1.0)
            else:
                # Advance the phase by the *current* frequency each sample so a
                # pitch sweep stays phase-continuous (no clicks).
                phase += two_pi * f / SAMPLE_RATE
                if phase > two_pi:
                    phase -= two_pi
                sample = _oscillator(wave, phase)

            # ADSR-ish envelope: linear attack ramp then decay to zero.
            if i < attack:
                env = i / attack
            else:
                # Decay: 1 -> 0 over the remaining tail, curved for a natural fall.
                frac = (i - attack) / max(1, (n - attack))
                env = (1.0 - frac) ** 1.6

            value = int(sample * env * vol * MAX_AMPLITUDE)
            # Interleaved L/R — same value in both channels (mono content).
            buf[2 * i] = value
            buf[2 * i + 1] = value

        return self._sound_from_buffer(buf)

    def _sound_from_buffer(self, buf: "array.array[int]") -> pygame.mixer.Sound:
        """Wrap a signed-16-bit sample array in a ``Sound`` (endian-correct)."""
        # pygame's ``-16`` format is *system* endianness. ``array('h')`` is
        # native-endian, so on any normal platform they already agree; we only
        # byteswap on the (rare) big-endian machine to be safe.
        if sys.byteorder == "big":
            buf = array.array("h", buf)
            buf.byteswap()
        return pygame.mixer.Sound(buffer=buf.tobytes())

    # ---------------------------------------------------------------- library
    def _build_library(self) -> None:
        """Bake every named one-shot effect once, at startup.

        Each entry is a short, characterful blip. The choices are deliberately
        opinionated: coins are bright ascending sines, hits are noisy and low,
        power-ups arpeggiate upward, etc. Baking up-front means playback is a
        zero-allocation ``Sound.play`` at runtime.
        """
        make = self.make_tone

        # A coin is a bright two-note "bling": a quick blip then a higher ring.
        self.sounds["coin"] = self._sequence([
            make(880, 0.05, 0.55, "square"),
            make(1320, 0.10, 0.50, "square", sweep=1500),
        ])
        # A gem is shinier and longer: a rising sine with a sparkle tail.
        self.sounds["gem"] = self._sequence([
            make(1046, 0.06, 0.5, "sine", sweep=1318),
            make(1568, 0.14, 0.45, "sine", sweep=2093),
        ])
        # Jump: a fast upward "boing" (pitch sweeps up).
        self.sounds["jump"] = make(320, 0.16, 0.55, "square", sweep=720)
        # Land: a short low thud (downward sweep + a touch of noise body).
        self.sounds["land"] = self._mix([
            make(180, 0.10, 0.55, "sine", sweep=90),
            make(120, 0.06, 0.30, "sine", noise=True),
        ])
        # Slide: a filtered noise "shhh" that sweeps down.
        self.sounds["slide"] = make(600, 0.22, 0.35, "sine", sweep=180, noise=True)
        # Hit: a harsh, low noisy crunch — the "you messed up" sound.
        self.sounds["hit"] = self._mix([
            make(140, 0.28, 0.6, "square", sweep=70),
            make(90, 0.22, 0.5, "sine", noise=True),
        ])
        # Power-up: a triumphant three-note upward arpeggio.
        self.sounds["powerup"] = self._sequence([
            make(523, 0.08, 0.5, "square"),
            make(659, 0.08, 0.5, "square"),
            make(784, 0.16, 0.5, "square", sweep=880),
        ])
        # Button: a soft, short UI click.
        self.sounds["button"] = make(660, 0.05, 0.35, "triangle", sweep=760)
        # Combo: a crisp rising ping that gets used as the combo climbs.
        self.sounds["combo"] = make(988, 0.09, 0.4, "triangle", sweep=1245)
        # Milestone: a celebratory four-note fanfare.
        self.sounds["milestone"] = self._sequence([
            make(523, 0.09, 0.5, "square"),
            make(659, 0.09, 0.5, "square"),
            make(784, 0.09, 0.5, "square"),
            make(1046, 0.20, 0.55, "square", sweep=1175),
        ])
        # Lane change: a very short, dry tick so movement feels responsive.
        self.sounds["lanechange"] = make(440, 0.04, 0.30, "triangle", sweep=520)
        # Whoosh: a near-miss air rush — noisy downward sweep.
        self.sounds["whoosh"] = make(1200, 0.18, 0.35, "sine", sweep=300, noise=True)

        # Drop any that failed to render so ``play`` treats them as "unknown".
        self.sounds = {k: v for k, v in self.sounds.items() if v is not None}

    def _sequence(self, parts: List[Optional[pygame.mixer.Sound]]) -> Optional[pygame.mixer.Sound]:
        """Concatenate several rendered tones back-to-back into one Sound."""
        raws = [self._raw_samples(p) for p in parts if p is not None]
        if not raws:
            return None
        joined = array.array("h")
        for chunk in raws:
            joined.extend(chunk)
        return self._sound_from_buffer(joined)

    def _mix(self, parts: List[Optional[pygame.mixer.Sound]]) -> Optional[pygame.mixer.Sound]:
        """Overlay several rendered tones (sample-wise sum, clamped)."""
        raws = [self._raw_samples(p) for p in parts if p is not None]
        raws = [r for r in raws if len(r)]
        if not raws:
            return None
        length = max(len(r) for r in raws)
        out = array.array("h", bytes(2 * length))
        for r in raws:
            for i in range(len(r)):
                out[i] = _clamp16(out[i] + r[i])
        return self._sound_from_buffer(out)

    @staticmethod
    def _raw_samples(sound: pygame.mixer.Sound) -> "array.array[int]":
        """Extract a Sound's interleaved 16-bit samples as an array."""
        data = array.array("h")
        try:
            data.frombytes(sound.get_raw())
            if sys.byteorder == "big":
                data.byteswap()
        except Exception:  # noqa: BLE001 - degrade to silence rather than crash
            return array.array("h")
        return data

    # -------------------------------------------------------------- SFX play
    def play(self, name: str) -> None:
        """Play a one-shot SFX by name. No-op if disabled or unknown."""
        if not self.enabled:
            return
        sound = self.sounds.get(name)
        if sound is None:
            return
        try:
            sound.set_volume(self.sfx_volume)
            sound.play()
        except Exception:  # noqa: BLE001 - audio hiccup must not stop the game
            pass

    # ---------------------------------------------------------- music: tables
    # A mood is a list of steps: (semitone offset from BASE_FREQ, beats). A
    # ``None`` semitone is a rest. Two simultaneous voices (melody + bass) give
    # the loop a bit of body without a real synth. Kept short so the render is
    # cheap and the loop stays tight.
    MUSIC_MOODS: Dict[str, Dict[str, object]] = {
        "menu": {
            "bpm": 96,
            "wave": "triangle",
            "melody": [(12, 1), (16, 1), (19, 1), (16, 1),
                       (14, 1), (17, 1), (21, 1), (17, 1)],
            "bass": [(0, 2), (5, 2), (7, 2), (5, 2)],
        },
        "run": {
            "bpm": 132,
            "wave": "square",
            "melody": [(12, 0.5), (19, 0.5), (24, 0.5), (19, 0.5),
                       (17, 0.5), (12, 0.5), (16, 0.5), (19, 0.5)],
            "bass": [(0, 1), (0, 1), (7, 1), (5, 1)],
        },
        "danger": {
            "bpm": 150,
            "wave": "square",
            "melody": [(13, 0.5), (13, 0.5), (18, 0.5), (13, 0.5),
                       (11, 0.5), (16, 0.5), (11, 0.5), (10, 0.5)],
            "bass": [(1, 1), (1, 1), (0, 1), (0, 1)],
        },
    }

    # ----------------------------------------------------------- music: play
    def play_music(self, name: str) -> None:
        """Start (or switch to) a looping chiptune track by mood name."""
        if not self.enabled or self._music_channel is None:
            return
        if name not in self.MUSIC_MOODS:
            return
        if self._current_music == name and self._music_channel.get_busy():
            return  # already playing this mood — don't restart it.
        track = self._music_cache.get(name)
        if track is None:
            track = self._render_music(name)
            if track is None:
                return
            self._music_cache[name] = track
        self._current_music = name
        try:
            track.set_volume(self.music_volume)
            # loops=-1 asks SDL to loop forever; update() is a belt-and-braces
            # safety net in case a driver ever drops the loop.
            self._music_channel.play(track, loops=-1)
        except Exception:  # noqa: BLE001
            pass

    def stop_music(self) -> None:
        """Stop the background track (if any)."""
        self._current_music = None
        if self._music_channel is not None:
            try:
                self._music_channel.stop()
            except Exception:  # noqa: BLE001
                pass

    def _render_music(self, name: str) -> Optional[pygame.mixer.Sound]:
        """Bake one loop of a mood into a stereo Sound (melody + bass mixed)."""
        mood = self.MUSIC_MOODS[name]
        bpm = float(mood["bpm"])  # type: ignore[arg-type]
        wave = str(mood["wave"])
        beat = 60.0 / bpm  # seconds per beat.

        melody = self._render_voice(mood["melody"], beat, wave, 0.32)  # type: ignore[arg-type]
        bass = self._render_voice(mood["bass"], beat, "triangle", 0.30, octave=-1)  # type: ignore[arg-type]
        if melody is None and bass is None:
            return None

        voices = [v for v in (melody, bass) if v is not None]
        length = max(len(v) for v in voices)
        out = array.array("h", bytes(2 * length))
        for v in voices:
            for i in range(len(v)):
                out[i] = _clamp16(out[i] + v[i])
        return self._sound_from_buffer(out)

    def _render_voice(
        self,
        notes: List[Tuple[Optional[int], float]],
        beat: float,
        wave: str,
        volume: float,
        octave: int = 0,
    ) -> Optional["array.array[int]"]:
        """Render one monophonic voice (a list of note/rest steps) to samples."""
        voice = array.array("h")
        for semitone, beats in notes:
            dur = beat * beats
            if semitone is None:
                # A rest: append silence of the right length.
                voice.extend(array.array("h", bytes(4 * int(SAMPLE_RATE * dur))))
                continue
            freq = BASE_FREQ * (SEMITONE ** (semitone + 12 * octave))
            # Render slightly shorter than the slot so consecutive notes have a
            # tiny gap — that staccato is what makes it read as "chiptune".
            tone = self.make_tone(freq, dur * 0.9, volume, wave)
            samples = self._raw_samples(tone) if tone is not None else array.array("h")
            voice.extend(samples)
            gap = int(SAMPLE_RATE * dur * 0.1)
            voice.extend(array.array("h", bytes(4 * gap)))
        return voice if len(voice) else None

    # ---------------------------------------------------------- music: update
    def update(self, dt: float) -> None:
        """Advance the sequencer bookkeeping and keep the loop alive.

        SDL loops the music channel for us, so this is deliberately light: we
        only poll a few times per second and re-kick the loop if a driver ever
        lets it fall silent. Safe to call every frame; a no-op when disabled.
        """
        if not self.enabled or self._music_channel is None:
            return
        self._music_poll += dt
        if self._music_poll < 0.25:
            return
        self._music_poll = 0.0
        # Keep the channel's live volume in step with the settings getter.
        track = self._music_cache.get(self._current_music or "")
        if track is not None:
            try:
                track.set_volume(self.music_volume)
            except Exception:  # noqa: BLE001
                pass
        # Safety net: if we believe music should be playing but the channel went
        # idle, restart it. This never fires under a healthy driver.
        if self._current_music and not self._music_channel.get_busy():
            self.play_music(self._current_music)

    # ------------------------------------------------------------ volume API
    @property
    def sfx_volume(self) -> float:
        """Current SFX volume in ``[0, 1]`` (from the getter or the field)."""
        if self._get_sfx_volume is not None:
            try:
                return _clamp01(float(self._get_sfx_volume()))
            except Exception:  # noqa: BLE001
                return self._sfx_volume
        return self._sfx_volume

    @property
    def music_volume(self) -> float:
        """Current music volume in ``[0, 1]`` (from the getter or the field)."""
        if self._get_music_volume is not None:
            try:
                return _clamp01(float(self._get_music_volume()))
            except Exception:  # noqa: BLE001
                return self._music_volume
        return self._music_volume

    def set_sfx_volume(self, v: float) -> None:
        """Set the internal SFX volume (used when no getter is supplied)."""
        self._sfx_volume = _clamp01(v)

    def set_music_volume(self, v: float) -> None:
        """Set the internal music volume and apply it to the live track."""
        self._music_volume = _clamp01(v)
        track = self._music_cache.get(self._current_music or "")
        if track is not None:
            try:
                track.set_volume(self.music_volume)
            except Exception:  # noqa: BLE001
                pass

    # ---------------------------------------------------------------- teardown
    def shutdown(self) -> None:
        """Stop everything and release the mixer. Idempotent and safe."""
        self.stop_music()
        if not self.enabled:
            return
        try:
            pygame.mixer.stop()
            pygame.mixer.quit()
        except Exception:  # noqa: BLE001
            pass
        self.enabled = False


# ---------------------------------------------------------------------------
# Small pure helpers (module-level so they carry no per-instance state)
# ---------------------------------------------------------------------------
def _oscillator(wave: str, phase: float) -> float:
    """Return one sample in ``[-1, 1]`` for ``wave`` at the given phase (radians).

    ``phase`` is expected in ``[0, 2*pi)``. Unknown waveforms fall back to sine.
    """
    if wave == "square":
        return 1.0 if phase < math.pi else -1.0
    if wave == "triangle":
        # 0 -> +1 -> 0 -> -1 -> 0 as phase sweeps 0..2pi.
        norm = phase / (2.0 * math.pi)  # 0..1
        return 4.0 * abs(norm - 0.5) - 1.0
    if wave in ("saw", "sawtooth"):
        norm = phase / (2.0 * math.pi)  # 0..1
        return 2.0 * norm - 1.0
    # Default: a pure sine.
    return math.sin(phase)


def _clamp01(v: float) -> float:
    """Clamp a float into ``[0.0, 1.0]``."""
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _clamp16(v: int) -> int:
    """Clamp an int into the signed 16-bit range (prevents mix overflow wrap)."""
    if v < -MAX_AMPLITUDE:
        return -MAX_AMPLITUDE
    if v > MAX_AMPLITUDE:
        return MAX_AMPLITUDE
    return v
