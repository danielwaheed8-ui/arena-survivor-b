"""
Missions — bite-sized goals that give a run a reason beyond "beat the high score".

Where achievements are permanent, lifetime landmarks ("run 5000 m *once*"),
missions are the game's *rotating* objective board: a small set of three active
goals that the player chips away at, completes for a coin reward, and then sees
replaced by a fresh set. They are the connective tissue between a single run and
the long-term economy — every mission that completes drops coins into the shop
wallet, so even a mediocre run feels like progress.

The :class:`MissionSystem` is a pure-logic meta-system. It never touches a pygame
surface and never reads the event queue; it subscribes to the same gameplay
events everything else keys off (coins, gems, powerups, near-misses, biome
changes, score) and translates them into progress against whatever missions
happen to be active. It owns nothing the renderer needs directly — the HUD/menu
reads its state through :meth:`snapshot`.

Design notes / rationale
------------------------
* **Templates, not hand-authored missions.** A mission is an *instance* of a
  :class:`MissionTemplate` (e.g. "collect N coins") with a concrete, randomly
  rolled goal ("collect 120 coins"). Rolling from templates gives endless variety
  from a compact table and keeps balance in one place (each template declares its
  goal range, its coin reward scaling and how it reads progress from an event).
  Adding a new mission type is one entry in ``TEMPLATES``.

* **Two lifetimes: lifetime vs. "in one run".** Some goals accumulate across
  sessions ("collect N coins" — a coin is a coin whenever you grab it); others
  are explicitly *single-run* ("run N metres **in one run**", "score N **in one
  run**"). The template flags which it is with ``per_run``. Per-run missions have
  their progress reset by :meth:`reset_run` at the start of every run so a fresh
  attempt starts from zero; lifetime missions ignore run boundaries and their
  progress is persisted verbatim.

* **Progress is monotonic and idempotent-ish per event.** Handlers only ever
  *add* to a mission's counter (or, for "reach a level" style goals, *raise* it
  to a new maximum). We never subtract, so a mission bar never visibly rewinds
  mid-run except for the deliberate per-run reset. Completion is latched: once a
  mission is done it stops consuming events and simply waits for the batch to
  finish so the whole set can reroll together.

* **One writer for persistence.** Like every meta-system, missions do not own a
  file. They stash the active batch and its progress inside
  ``save.get_section("missions")`` — a live dict the :class:`SaveManager` owns —
  and ask the save manager to flush when something meaningful changes (a mission
  completes, a batch rerolls). This keeps a single source of truth and a single
  fsync.

* **Deterministic when seeded.** All randomness flows through an injectable
  :class:`~temple_run.mathutils.RNG`. Passing a seeded RNG makes the rolled batch
  reproducible, which is invaluable for tests and for a "daily missions" mode
  that wants everyone to get the same board.

* **Never crash the loop.** Every event handler and the reroll path are wrapped
  so a malformed payload, a corrupt saved batch, or a template that no longer
  exists costs at most one mission — never the frame or the run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config import Palette
from ..core.events import Event, EventBus, EventType
from ..entities.powerup_types import POWERUP_KEYS
from ..mathutils import RNG, clamp
from ..world.biomes import BIOME_BY_KEY

__all__ = ["Mission", "MissionTemplate", "MissionSystem", "TEMPLATES"]


# Number of missions shown on the board at once. Three is the sweet spot: enough
# variety that at least one usually fits your play-style, few enough to fit a HUD
# strip and to feel achievable within a session or two.
ACTIVE_MISSION_COUNT: int = 3


# ---------------------------------------------------------------------------
# Mission template
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MissionTemplate:
    """A *kind* of mission: the recipe an active :class:`Mission` is rolled from.

    A template is immutable data plus a tiny amount of behaviour describing how a
    concrete mission is created and how it renders. The stateful per-instance
    values (the rolled goal, the reward, live progress) live on :class:`Mission`.

    Fields
    ------
    key:
        Stable identifier persisted in the save (so a reloaded mission knows
        which template it came from). Never reuse a key for a different meaning.
    text:
        A ``str.format`` template for the player-facing label. It receives the
        rolled ``goal`` and, for parameterised templates (e.g. "reach biome X"),
        a ``param`` — a human-readable noun such as a biome name.
    goal_range:
        Inclusive ``(low, high)`` bounds for the randomly rolled goal. For
        "reach X" style templates the goal is always ``1`` and this is ``(1, 1)``.
    goal_step:
        The goal is rounded to a multiple of this so it reads as a tidy number
        ("collect 120 coins", not "collect 117 coins").
    reward_per_unit:
        Coins awarded per unit of goal, folded into a base reward. Bigger asks
        pay out more; see :meth:`roll_reward`.
    reward_base:
        Flat coin floor added to every reward so even a tiny goal is worth doing.
    per_run:
        ``True`` if this goal is measured within a single run and should be reset
        by :meth:`MissionSystem.reset_run`. ``False`` for lifetime-cumulative
        goals.
    params:
        Optional pool of ``(param_key, param_label)`` choices for parameterised
        templates. ``reach_biome`` uses this to pick which biome to target. An
        empty tuple means the template takes no parameter.
    """

    key: str
    text: str
    goal_range: Tuple[int, int]
    goal_step: int
    reward_per_unit: float
    reward_base: int
    per_run: bool
    params: Tuple[Tuple[str, str], ...] = ()

    # ---- construction helpers ------------------------------------------- #
    def roll_goal(self, rng: RNG) -> int:
        """Pick a concrete goal within ``goal_range``, snapped to ``goal_step``.

        The result is always at least ``goal_step`` (so a goal is never zero) and
        never exceeds the range's upper bound after rounding.
        """
        low, high = self.goal_range
        if high <= low:
            return max(int(low), 1)
        raw = rng.int_range(int(low), int(high))
        step = max(1, int(self.goal_step))
        # Round to the nearest step, then clamp back inside the declared range so
        # rounding up near the top can't overshoot the intended maximum.
        snapped = int(round(raw / step)) * step
        snapped = max(step, min(snapped, high))
        return snapped

    def roll_param(self, rng: RNG) -> Tuple[str, str]:
        """Pick a ``(param_key, param_label)`` for a parameterised template.

        Returns ``("", "")`` for templates that take no parameter, so callers can
        store the pair unconditionally.
        """
        if not self.params:
            return ("", "")
        return rng.choice(list(self.params))

    def roll_reward(self, goal: int) -> int:
        """Compute the coin reward for a rolled ``goal``.

        Reward scales linearly with the ask on top of a flat base, then is
        clamped to a sane floor so no mission is worthless. We keep it an ``int``
        because coins are whole.
        """
        reward = int(self.reward_base + goal * self.reward_per_unit)
        return max(reward, 10)


# ---------------------------------------------------------------------------
# The template library
# ---------------------------------------------------------------------------
# Each template maps onto one gameplay event stream (see the handler wiring in
# ``MissionSystem._subscribe``). Ranges and rewards are tuned so the three-mission
# board takes "a session or two" to clear, matching the contract's intent.
#
# ``reach_biome``'s params are drawn from the biome library so labels stay in sync
# with the world; we skip the very first biome ("temple") because every run starts
# there and reaching it would be trivial/instant.
_BIOME_PARAMS: Tuple[Tuple[str, str], ...] = tuple(
    (b.key, b.name) for b in BIOME_BY_KEY.values() if b.key != "temple"
)

TEMPLATES: Tuple[MissionTemplate, ...] = (
    MissionTemplate(
        key="collect_coins",
        text="Collect {goal} coins",
        goal_range=(60, 220),
        goal_step=10,
        reward_per_unit=0.5,
        reward_base=40,
        per_run=False,  # coins count whenever you grab them, across runs
    ),
    MissionTemplate(
        key="collect_gems",
        text="Collect {goal} gems",
        goal_range=(3, 12),
        goal_step=1,
        reward_per_unit=12.0,
        reward_base=30,
        per_run=False,
    ),
    MissionTemplate(
        key="run_distance",
        text="Run {goal} m in one run",
        goal_range=(800, 3000),
        goal_step=100,
        reward_per_unit=0.08,
        reward_base=40,
        per_run=True,  # "in one run" — resets each attempt
    ),
    MissionTemplate(
        key="use_powerups",
        text="Use {goal} power-ups",
        goal_range=(3, 10),
        goal_step=1,
        reward_per_unit=14.0,
        reward_base=30,
        per_run=False,
    ),
    MissionTemplate(
        key="near_misses",
        text="Pull off {goal} near-misses",
        goal_range=(8, 30),
        goal_step=2,
        reward_per_unit=5.0,
        reward_base=30,
        per_run=False,
    ),
    MissionTemplate(
        key="reach_biome",
        text="Reach the {param}",
        goal_range=(1, 1),
        goal_step=1,
        reward_per_unit=0.0,
        reward_base=70,
        per_run=True,  # you must reach it within a run
        params=_BIOME_PARAMS,
    ),
    MissionTemplate(
        key="score_run",
        text="Score {goal} in one run",
        goal_range=(2000, 9000),
        goal_step=250,
        reward_per_unit=0.02,
        reward_base=45,
        per_run=True,
    ),
)

# Index the library by key for O(1) rehydration of a persisted batch.
_TEMPLATE_BY_KEY: Dict[str, MissionTemplate] = {t.key: t for t in TEMPLATES}


# ---------------------------------------------------------------------------
# A concrete, active mission
# ---------------------------------------------------------------------------
@dataclass
class Mission:
    """One active goal on the board: a rolled instance of a :class:`MissionTemplate`.

    A mission is mostly a small mutable record. Its identity is the pair
    (``template.key``, rolled ``goal``/``param``); its state is ``progress`` and
    the latched ``done`` flag. Progress accounting is intentionally simple: the
    system feeds increments/values in and the mission clamps and latches.
    """

    template: MissionTemplate
    goal: int
    reward: int
    # For parameterised templates, the concrete target: e.g. ("desert",
    # "Sun Temple Dunes"). ("", "") for templates without a parameter.
    param_key: str = ""
    param_label: str = ""
    # Live progress toward ``goal``. Whole units (coins, metres, points, ...).
    progress: int = 0
    # Latched completion flag — set once ``progress`` first reaches ``goal`` and
    # never cleared (a completed mission waits for its batch to reroll).
    done: bool = False

    # ---- progress accounting -------------------------------------------- #
    def add_progress(self, amount: int) -> bool:
        """Advance progress by ``amount`` (clamped at ``goal``).

        Returns ``True`` if this call is what *first* completed the mission, so
        the caller knows to fire the reward exactly once. Amounts <= 0 and calls
        on an already-complete mission are no-ops.
        """
        if self.done or amount <= 0:
            return False
        self.progress = min(self.goal, self.progress + int(amount))
        if self.progress >= self.goal:
            self.done = True
            return True
        return False

    def raise_to(self, value: int) -> bool:
        """Raise progress to at least ``value`` (a high-water mark, never lowers).

        Used by "in one run" magnitude goals — distance and score report a
        cumulative *total*, not a delta, so we track the maximum seen this run.
        Returns ``True`` if this call first completed the mission.
        """
        if self.done:
            return False
        if value > self.progress:
            self.progress = min(self.goal, int(value))
        if self.progress >= self.goal:
            self.done = True
            return True
        return False

    def reset_progress(self) -> None:
        """Zero out live progress and clear completion (used for per-run resets)."""
        self.progress = 0
        self.done = False

    # ---- presentation --------------------------------------------------- #
    @property
    def text(self) -> str:
        """The player-facing label with the goal/param substituted in.

        Formatting is defended so a malformed template can never raise on the
        draw path; on any problem we fall back to the raw template string.
        """
        try:
            return self.template.text.format(goal=self.goal, param=self.param_label)
        except Exception:  # pragma: no cover - defensive
            return self.template.text

    @property
    def ratio(self) -> float:
        """Fill ratio in ``[0, 1]`` for a HUD/menu progress bar."""
        if self.goal <= 0:
            return 1.0 if self.done else 0.0
        return clamp(self.progress / self.goal, 0.0, 1.0)

    # ---- persistence ---------------------------------------------------- #
    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain JSON-safe dict for the save section."""
        return {
            "template": self.template.key,
            "goal": self.goal,
            "reward": self.reward,
            "param_key": self.param_key,
            "param_label": self.param_label,
            "progress": self.progress,
            "done": self.done,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Optional["Mission"]:
        """Rehydrate a mission from a persisted dict, or ``None`` if unusable.

        A saved mission whose template no longer exists (renamed/removed in a
        later build) is dropped by returning ``None`` — the system will simply
        roll a replacement. All fields are read defensively so a hand-edited or
        partially-written save can't crash the load.
        """
        try:
            template = _TEMPLATE_BY_KEY.get(str(data.get("template", "")))
            if template is None:
                return None
            goal = max(1, int(data.get("goal", 1)))
            reward = max(0, int(data.get("reward", 0)))
            mission = cls(
                template=template,
                goal=goal,
                reward=reward,
                param_key=str(data.get("param_key", "")),
                param_label=str(data.get("param_label", "")),
            )
            mission.progress = max(0, min(goal, int(data.get("progress", 0))))
            mission.done = bool(data.get("done", False)) or mission.progress >= goal
            return mission
        except Exception:  # pragma: no cover - defensive
            return None


# ---------------------------------------------------------------------------
# The mission system
# ---------------------------------------------------------------------------
class MissionSystem:
    """Owns the active mission board, feeds it events, and rewards completions.

    Lifecycle::

        missions = MissionSystem(event_bus=bus, save=save)   # loads or rolls a batch
        ...                       # play; events drive progress automatically
        missions.reset_run()      # at the start of every run (clears per-run goals)
        ...
        board = missions.snapshot()   # hand to the HUD / missions screen

    The system subscribes on construction; call :meth:`close` to detach if a
    caller ever needs to tear it down (most games just drop it).
    """

    def __init__(
        self,
        event_bus: EventBus,
        save: Any,
        rng: Optional[RNG] = None,
    ) -> None:
        """Wire up the system, then load a persisted batch or roll a fresh one.

        Parameters
        ----------
        event_bus:
            The shared :class:`EventBus`. We subscribe to the gameplay events that
            feed mission progress and publish ``MISSION_COMPLETED`` / ``TOAST``.
        save:
            The :class:`~temple_run.systems.save.SaveManager` (duck-typed — we
            only use ``get_section``, ``add`` and ``save``). Missions persist
            their batch here and pay rewards into ``coins_balance``.
        rng:
            Optional :class:`RNG` for reproducible rolls. Defaults to a fresh,
            time-seeded RNG.
        """
        self.bus: EventBus = event_bus
        self.save: Any = save
        self.rng: RNG = rng if rng is not None else RNG()

        # The live board: exactly ``ACTIVE_MISSION_COUNT`` missions once loaded.
        self.missions: List[Mission] = []

        # Unsubscribe handles so :meth:`close` can detach every listener.
        self._unsubs: List[Callable[[], None]] = []
        self._subscribe()

        # Restore the persisted board, or roll a brand-new set if there is none
        # (first launch, corrupt section, or a save from before missions existed).
        self._load_or_roll()

    # ------------------------------------------------------------------ setup
    def _subscribe(self) -> None:
        """Subscribe to every gameplay event a template cares about.

        Each handler is tiny and defensive; the mapping here is the single place
        that documents which event drives which template family.
        """
        b = self.bus
        self._unsubs.append(b.subscribe(EventType.COIN_COLLECTED, self._on_coin))
        self._unsubs.append(b.subscribe(EventType.GEM_COLLECTED, self._on_gem))
        # We count a powerup as "used" the moment it is collected (it always then
        # activates), which matches the player's intuition better than waiting for
        # POWERUP_STARTED and avoids double-counting a refresh.
        self._unsubs.append(b.subscribe(EventType.POWERUP_COLLECTED, self._on_powerup))
        self._unsubs.append(b.subscribe(EventType.NEAR_MISS, self._on_near_miss))
        self._unsubs.append(b.subscribe(EventType.BIOME_CHANGED, self._on_biome))
        self._unsubs.append(b.subscribe(EventType.SCORE_CHANGED, self._on_score))
        # Distance-based missions ride the milestone stream, which reports metres
        # already computed by the scoring system — no need to re-read the player.
        self._unsubs.append(b.subscribe(EventType.MILESTONE_REACHED, self._on_milestone))

    # ------------------------------------------------------------ persistence
    def _section(self) -> Dict[str, Any]:
        """The live save sub-dict this system owns (auto-created)."""
        return self.save.get_section("missions")

    def _load_or_roll(self) -> None:
        """Populate :attr:`missions` from the save, or roll a fresh batch.

        A persisted batch is only accepted if it rehydrates into exactly the
        expected number of usable missions; anything short (some templates were
        dropped, the list was truncated) triggers a clean reroll so the player is
        never left with a half-empty board.
        """
        loaded: List[Mission] = []
        try:
            section = self._section()
            raw_list = section.get("active", [])
            if isinstance(raw_list, list):
                for entry in raw_list:
                    if isinstance(entry, dict):
                        mission = Mission.from_dict(entry)
                        if mission is not None:
                            loaded.append(mission)
        except Exception as exc:  # pragma: no cover - defensive
            self._log(f"could not load missions section: {exc!r}")
            loaded = []

        if len(loaded) == ACTIVE_MISSION_COUNT:
            self.missions = loaded
        else:
            # No valid saved board (first run / corrupt / schema change) — roll
            # one and persist it so the next launch is stable.
            self._roll_new_batch()
            self._persist()

    def _persist(self) -> None:
        """Write the current board into the save section and flush to disk.

        Called whenever the board changes in a way worth surviving a crash: a
        completion, a reroll, or a per-run reset of persisted per-run progress.
        Never raises — persistence failures are logged by the save manager.
        """
        try:
            section = self._section()
            section["active"] = [m.to_dict() for m in self.missions]
            self.save.save()
        except Exception as exc:  # pragma: no cover - defensive
            self._log(f"could not persist missions: {exc!r}")

    # --------------------------------------------------------------- rolling
    def _roll_new_batch(self) -> None:
        """Replace the board with a fresh, varied set of missions.

        We draw distinct *templates* where possible so the three missions feel
        varied (you rarely want two "collect coins" side by side). If the library
        is smaller than the board size we fall back to allowing repeats. Each
        chosen template is then rolled into a concrete goal/param/reward.
        """
        available = list(TEMPLATES)
        self.rng.shuffle(available)

        chosen: List[MissionTemplate] = []
        if len(available) >= ACTIVE_MISSION_COUNT:
            chosen = available[:ACTIVE_MISSION_COUNT]
        else:  # pragma: no cover - library is always large enough in practice
            # Too few templates to fill the board uniquely; permit repeats.
            while len(chosen) < ACTIVE_MISSION_COUNT:
                chosen.append(self.rng.choice(list(TEMPLATES)))

        self.missions = [self._instantiate(t) for t in chosen]

    def _instantiate(self, template: MissionTemplate) -> Mission:
        """Roll one concrete :class:`Mission` from ``template``."""
        goal = template.roll_goal(self.rng)
        param_key, param_label = template.roll_param(self.rng)
        reward = template.roll_reward(goal)
        return Mission(
            template=template,
            goal=goal,
            reward=reward,
            param_key=param_key,
            param_label=param_label,
        )

    def _maybe_reroll(self) -> None:
        """If every mission on the board is complete, roll a whole new batch.

        Missions reroll as a *set* rather than individually so the board changes
        feel like a deliberate refresh and so a single fast-completing mission
        doesn't churn constantly. Persisted on reroll.
        """
        if self.missions and all(m.done for m in self.missions):
            self._roll_new_batch()
            self._persist()

    # ----------------------------------------------------------- completion
    def _complete(self, mission: Mission) -> None:
        """Pay out a freshly completed mission and announce it.

        Adds the coin reward to the spendable balance, flushes the save, then
        publishes ``MISSION_COMPLETED`` and a celebratory ``TOAST``. Ordering
        matters: we bank the reward *before* announcing so a listener that reads
        ``coins_balance`` in response sees the updated figure.
        """
        try:
            # Reward the player's wallet. ``add`` keeps the counter integral.
            self.save.add("coins_balance", int(mission.reward))
        except Exception as exc:  # pragma: no cover - defensive
            self._log(f"could not credit mission reward: {exc!r}")

        # Persist the completion + reward together.
        self._persist()

        # Announce to the wider game (audio sting, HUD banner, achievements that
        # count "missions completed", etc.).
        try:
            self.bus.publish(Event(EventType.MISSION_COMPLETED, {"mission": mission}))
            self.bus.emit(
                EventType.TOAST,
                text=f"Mission complete: {mission.text}  (+{mission.reward} coins)",
                color=Palette.SUCCESS,
                icon="mission",
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._log(f"could not announce mission completion: {exc!r}")

    def _apply(self, mission: Mission, completed: bool) -> None:
        """Common tail after a progress update: reward + persist if just done.

        ``completed`` is the boolean returned by the mission's
        ``add_progress``/``raise_to`` call — ``True`` only on the transition into
        completion. On a plain progress bump we deliberately do *not* flush the
        save every event (that would fsync on every coin); progress is cheap to
        recompute and is re-persisted at the next completion/reroll/run boundary.
        """
        if completed:
            self._complete(mission)
            self._maybe_reroll()

    # -------------------------------------------------------- event handlers
    def _on_coin(self, event: Event) -> None:
        """``COIN_COLLECTED`` -> +1 toward every 'collect coins' mission.

        We count *one coin per event* rather than the event's ``value``: the
        value already folds in the coin multiplier (an ``x2`` coin is worth two
        points), but a mission to "collect N coins" should count physical pickups,
        not multiplier-inflated points. Counting pickups keeps the goal honest.
        """
        self._advance_family("collect_coins", 1)

    def _on_gem(self, event: Event) -> None:
        """``GEM_COLLECTED`` -> +1 toward every 'collect gems' mission."""
        self._advance_family("collect_gems", 1)

    def _on_powerup(self, event: Event) -> None:
        """``POWERUP_COLLECTED`` -> +1 toward every 'use power-ups' mission.

        The payload's ``power`` is validated against the known powerup keys so a
        stray event with a bogus key can't inflate progress.
        """
        power = event.get("power")
        if power is not None and power not in POWERUP_KEYS:
            return
        self._advance_family("use_powerups", 1)

    def _on_near_miss(self, event: Event) -> None:
        """``NEAR_MISS`` -> +1 toward every 'near-misses' mission."""
        self._advance_family("near_misses", 1)

    def _on_biome(self, event: Event) -> None:
        """``BIOME_CHANGED`` -> complete any 'reach biome X' mission that matches.

        The payload is ``{biome, key}``. We match on the ``key`` string (falling
        back to the biome object's ``.key`` if the flat key is absent) against
        each reach-biome mission's ``param_key``; a match completes that mission.
        """
        key = event.get("key")
        if not key:
            biome = event.get("biome")
            key = getattr(biome, "key", None)
        if not key:
            return
        for mission in self._family("reach_biome"):
            if mission.done:
                continue
            if mission.param_key == key:
                completed = mission.add_progress(mission.goal)
                self._apply(mission, completed)

    def _on_score(self, event: Event) -> None:
        """``SCORE_CHANGED`` -> raise every 'score in one run' mission's mark.

        Score is reported as a cumulative run total, so we use ``raise_to`` (a
        high-water mark) rather than adding deltas — this is naturally correct
        even if a score event is ever missed.
        """
        try:
            score = int(event.get("score", 0))
        except (TypeError, ValueError):
            return
        for mission in self._family("score_run"):
            if mission.done:
                continue
            completed = mission.raise_to(score)
            self._apply(mission, completed)

    def _on_milestone(self, event: Event) -> None:
        """``MILESTONE_REACHED`` -> raise every 'run N m in one run' mission.

        The event carries the ``meters`` figure the scoring system just crossed
        (a multiple of 500). We treat it as the current in-run distance and raise
        the distance missions' high-water mark toward it.
        """
        try:
            meters = int(event.get("meters", 0))
        except (TypeError, ValueError):
            return
        if meters <= 0:
            return
        for mission in self._family("run_distance"):
            if mission.done:
                continue
            completed = mission.raise_to(meters)
            self._apply(mission, completed)

    # ---------------------------------------------------------- helpers
    def _family(self, template_key: str) -> List[Mission]:
        """All active missions rolled from the template named ``template_key``."""
        return [m for m in self.missions if m.template.key == template_key]

    def _advance_family(self, template_key: str, amount: int) -> None:
        """Add ``amount`` to every active mission of a given additive template.

        Used by the counter-style templates (coins, gems, powerups, near-misses)
        where progress is a simple running tally. Each affected mission is put
        through :meth:`_apply` so a completion is rewarded and the batch can
        reroll. We iterate a snapshot of the family because a reroll triggered by
        one completion would otherwise mutate the list mid-loop.
        """
        for mission in self._family(template_key):
            if mission.done:
                continue
            completed = mission.add_progress(amount)
            self._apply(mission, completed)

    # ------------------------------------------------------------- lifecycle
    def reset_run(self) -> None:
        """Reset per-run mission progress at the start of a run.

        Lifetime missions (collect coins/gems, use powerups, near-misses) keep
        their progress; only ``per_run`` missions (distance, score, reach-biome)
        are zeroed so a new attempt starts fresh. If any per-run mission had
        *completed* in a previous run its reward has already been paid and it
        stays done — we never reset a mission that was already finished, so the
        player can't re-farm a per-run reward by dying and retrying. Persists if
        anything actually changed.
        """
        changed = False
        for mission in self.missions:
            if mission.template.per_run and not mission.done and mission.progress != 0:
                mission.reset_progress()
                changed = True
        if changed:
            self._persist()

    def reroll(self) -> None:
        """Force a fresh batch immediately (e.g. a 'refresh missions' button).

        Unlike the automatic reroll this does not require the board to be
        complete; it simply discards the current set and rolls a new one. Any
        unclaimed progress is lost, which is the intended cost of a manual
        refresh.
        """
        self._roll_new_batch()
        self._persist()

    def snapshot(self) -> List[Dict[str, Any]]:
        """Return the board for the HUD / missions screen.

        Each entry matches the contract schema::

            {"text", "progress", "goal", "reward", "done"}

        Read-only and cheap; safe to call every frame.
        """
        board: List[Dict[str, Any]] = []
        for mission in self.missions:
            board.append(
                {
                    "text": mission.text,
                    "progress": mission.progress,
                    "goal": mission.goal,
                    "reward": mission.reward,
                    "done": mission.done,
                }
            )
        return board

    def close(self) -> None:
        """Detach every event subscription. Safe to call more than once."""
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:  # pragma: no cover - best-effort
                pass
        self._unsubs.clear()

    # ------------------------------------------------------------- internals
    def _log(self, message: str) -> None:
        """Emit a diagnostic line to stdout. Never raises."""
        try:
            print(f"[missions] {message}")
        except Exception:  # pragma: no cover - stdout should always work
            pass

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        parts = ", ".join(
            f"{m.template.key}:{m.progress}/{m.goal}{'*' if m.done else ''}"
            for m in self.missions
        )
        return f"<MissionSystem [{parts}]>"
