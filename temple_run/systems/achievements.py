"""
Achievements — the game's long-tail reward system.

An *achievement* is a one-time milestone that rewards a player for doing
something noteworthy: their very first coin, a thousand coins across every run
they have ever played, a single 5 km sprint, chaining a full x4 combo, or
smashing ten obstacles while a boost is live. Some achievements watch *lifetime*
totals (persisted forever); others watch *this-run* behaviour (reset when a new
run starts). The :class:`AchievementSystem` unifies both under one small, purely
event-driven engine.

Design notes / rationale
------------------------

* **Data, not code.** Each achievement is a plain :class:`Achievement` record —
  an id, human-readable name/description, an icon glyph, a numeric goal, and a
  *metric key* naming the counter it tracks. There is deliberately no per-
  achievement callback in the definition table; adding a new achievement is
  usually a one-line entry, and the handful of counters they read are updated in
  exactly one place each. This keeps the catalogue skimmable and the wiring
  auditable.

* **Two flavours of counter, one progress model.** A metric is either
  ``"lifetime"`` (a running total that survives across sessions, e.g.
  ``coins_total``) or ``"run"`` (a per-run tally cleared by :meth:`reset_run`,
  e.g. ``run_distance_m``). :class:`Achievement` records which flavour it reads;
  :meth:`_progress_for` looks the current value up in the right bucket. Unlocking
  is monotonic: once ``progress >= goal`` the achievement latches unlocked and is
  never re-locked, even if a per-run counter later resets.

* **Persistence lives in the save's ``achievements`` section.** We never open a
  file ourselves — the :class:`~temple_run.systems.save.SaveManager` owns disk.
  We keep two dicts inside ``save.get_section("achievements")``: ``unlocked``
  (id -> True) and ``lifetime`` (metric key -> int). Because ``get_section``
  hands back a *live* dict, mutating ours mutates the save in place; we ask the
  manager to :meth:`~temple_run.systems.save.SaveManager.save` after any unlock
  or lifetime bump so progress is durable even if the process dies mid-run.

* **Pure event consumer, pure logic producer.** The system reads only the event
  bus (coins, gems, near-misses, powerups, obstacle hits, milestones, combo
  changes, biome changes) and the read-only save. It never touches a pygame
  surface. When an achievement unlocks it publishes ``ACHIEVEMENT_UNLOCKED``
  ``{achievement}`` plus a ``TOAST`` so the HUD/audio can celebrate — it does not
  draw anything itself. The achievements *screen* consumes :meth:`snapshot`.

* **Never crash the loop.** Handlers run on the hot event-dispatch path, so every
  one is wrapped so a malformed payload costs at most a missed count, never the
  frame. The lifetime save write is best-effort; a failed disk write is logged by
  the save manager, not raised here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from ..config import Palette
from ..core.events import Event, EventBus, EventType
from ..entities.powerup_types import POWERUP_KEYS

__all__ = ["Achievement", "AchievementSystem"]


# ---------------------------------------------------------------------------
# Metric scopes
# ---------------------------------------------------------------------------
# An achievement's metric is read from one of two buckets. "lifetime" values are
# cumulative across every run and are persisted; "run" values are the current
# run's tally and are wiped by ``reset_run``. Storing the scope on the record
# lets one progress lookup serve both kinds.
SCOPE_LIFETIME = "lifetime"
SCOPE_RUN = "run"


@dataclass(frozen=True)
class Achievement:
    """An immutable description of a single unlockable milestone.

    Attributes
    ----------
    id:
        Stable, machine-readable identifier used as the persistence key. Never
        change an existing id or players lose their unlock.
    name:
        Short title shown in toasts and the achievements screen.
    description:
        One-line explanation of how to earn it.
    icon:
        A tiny glyph (an emoji or a couple of ASCII characters) the UI can draw
        beside the entry; purely cosmetic.
    goal:
        The metric value at which the achievement unlocks. A goal of ``1`` makes
        it a simple "did it once" flag; larger goals drive a progress bar.
    metric:
        The counter key this achievement watches (see :data:`AchievementSystem.
        _metrics`). Progress is ``min(counter, goal)``.
    scope:
        Either :data:`SCOPE_LIFETIME` (cumulative, persisted) or
        :data:`SCOPE_RUN` (this-run only, reset each run).
    """

    id: str
    name: str
    description: str
    icon: str
    goal: int
    metric: str
    scope: str = SCOPE_LIFETIME

    def progress_from(self, value: int) -> int:
        """Clamp a raw counter ``value`` to this achievement's goal.

        Progress is never reported above the goal, so a UI can safely compute a
        ``progress / goal`` fill fraction without overshooting the bar.
        """
        if value < 0:
            return 0
        return value if value < self.goal else self.goal

    def is_met(self, value: int) -> bool:
        """Return ``True`` when a raw counter ``value`` satisfies the goal."""
        return value >= self.goal


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------
# The full set of achievements. Keep ids stable forever (they are the save
# keys). The list is ordered roughly easy -> hard so the achievements screen
# reads as a natural progression. Metric keys must match the counters the system
# maintains in ``_metrics`` (lifetime) or ``_run`` (per-run).
def _build_catalogue() -> List[Achievement]:
    """Construct the ordered list of achievement definitions.

    A function (rather than a module-level literal) keeps the ``Achievement``
    constructor calls readable and lets us reference :data:`POWERUP_KEYS` for the
    "collect every powerup in one run" goal without a magic number that could
    drift out of sync with the powerup catalogue.
    """
    powerup_count = len(POWERUP_KEYS)
    return [
        # --- first steps ---------------------------------------------------
        Achievement(
            "first_coin", "First Gold", "Collect your very first coin.",
            "\U0001FA99", 1, "coins_total", SCOPE_LIFETIME,
        ),
        Achievement(
            "first_gem", "Shiny", "Collect your first gem.",
            "\U0001F48E", 1, "gems_total", SCOPE_LIFETIME,
        ),
        # --- lifetime grinds ----------------------------------------------
        Achievement(
            "coins_1000", "Coin Hoarder", "Collect 1000 coins in total.",
            "\U0001F4B0", 1000, "coins_total", SCOPE_LIFETIME,
        ),
        Achievement(
            "gems_100", "Gem Collector", "Collect 100 gems in total.",
            "\U0001F48E", 100, "gems_total", SCOPE_LIFETIME,
        ),
        Achievement(
            "distance_total_25k", "Frequent Flyer",
            "Run 25,000 metres across all your runs.",
            "\U0001F30D", 25000, "distance_total_m", SCOPE_LIFETIME,
        ),
        Achievement(
            "runs_50", "Persistent", "Finish 50 runs.",
            "\U0001F3C3", 50, "runs_total", SCOPE_LIFETIME,
        ),
        # --- single-run distance ------------------------------------------
        Achievement(
            "run_1000m", "Getting Started", "Run 1000 m in a single run.",
            "\U0001F4CF", 1000, "run_distance_m", SCOPE_RUN,
        ),
        Achievement(
            "run_5000m", "Marathoner", "Run 5000 m in a single run.",
            "\U0001F3C5", 5000, "run_distance_m", SCOPE_RUN,
        ),
        Achievement(
            "survive_3min", "Endurance", "Survive for 3 minutes in one run.",
            "⏱", 180, "run_time_s", SCOPE_RUN,
        ),
        # --- skill flourishes ---------------------------------------------
        Achievement(
            "near_miss_master", "Daredevil",
            "Pull off 25 near misses in a single run.",
            "\U0001F4A8", 25, "run_near_misses", SCOPE_RUN,
        ),
        Achievement(
            "combo_x4", "Combo King", "Reach a x4 combo.",
            "\U0001F525", 1, "run_combo_x4", SCOPE_RUN,
        ),
        Achievement(
            "boost_smash_10", "Wrecking Ball",
            "Smash 10 obstacles while a boost is active.",
            "\U0001F4A5", 10, "run_boost_smashes", SCOPE_RUN,
        ),
        Achievement(
            "all_powerups_run", "Fully Loaded",
            "Collect every powerup type in a single run.",
            "⭐", powerup_count, "run_powerup_types", SCOPE_RUN,
        ),
        # --- milestone flair ----------------------------------------------
        Achievement(
            "biome_explorer", "Explorer", "Visit 3 different biomes in one run.",
            "\U0001F5FA", 3, "run_biomes", SCOPE_RUN,
        ),
    ]


class AchievementSystem:
    """Tracks progress towards, and the unlock state of, every achievement.

    The system is entirely event-driven. It subscribes to the gameplay events
    that feed its counters, keeps two counter buckets (persisted lifetime totals
    and volatile per-run tallies), and re-evaluates the affected achievements on
    every relevant event. Newly satisfied achievements latch unlocked, persist,
    and announce themselves via ``ACHIEVEMENT_UNLOCKED`` + ``TOAST``.

    Typical wiring::

        ach = AchievementSystem(event_bus=bus, save=save)
        # ... gameplay runs, events flow, achievements unlock themselves ...
        ach.reset_run()          # at the start of each new run
        data = ach.snapshot()    # for the achievements screen
    """

    def __init__(self, event_bus: EventBus, save: Any) -> None:
        """Create the system, load persisted state, and subscribe to events.

        Parameters
        ----------
        event_bus:
            The shared :class:`~temple_run.core.events.EventBus`. We both read
            from it (gameplay events) and publish to it (unlock + toast).
        save:
            A :class:`~temple_run.systems.save.SaveManager`-like object exposing
            ``get_section(name) -> dict`` and ``save()``. All persistence flows
            through it; we never touch the disk directly.
        """
        self.bus: EventBus = event_bus
        self.save = save

        # ---- catalogue -----------------------------------------------------
        self.achievements: List[Achievement] = _build_catalogue()
        # Fast id -> record lookup for progress queries and unlock checks.
        self._by_id: Dict[str, Achievement] = {a.id: a for a in self.achievements}

        # ---- persisted section --------------------------------------------
        # ``get_section`` returns a *live* dict inside the save; mutating it and
        # calling ``save.save()`` is how we persist. We keep two nested dicts:
        #   "unlocked":  {achievement_id: True}
        #   "lifetime":  {metric_key: int}
        section = self._section()
        self._unlocked: Dict[str, bool] = self._ensure_dict(section, "unlocked")
        # Cumulative counters that persist across sessions.
        self._metrics: Dict[str, int] = self._ensure_dict(section, "lifetime")

        # ---- per-run counters ---------------------------------------------
        # Volatile tallies reset by ``reset_run``. Kept in memory only — a run in
        # progress that is abandoned should not persist half-finished progress.
        self._run: Dict[str, int] = {}
        # Which distinct powerup keys / biome keys we have seen *this run*, used
        # to derive the "types collected" and "biomes visited" counts.
        self._run_powerup_keys: Set[str] = set()
        self._run_biome_keys: Set[str] = set()
        self._reset_run_counters()

        # Backfill any lifetime metrics missing from an older save so lookups
        # always find an int, and re-scan on boot so an old save that already met
        # a (newly-added) lifetime goal unlocks retroactively.
        self._normalise_metrics()
        self._reconcile_unlocks()

        # ---- subscriptions -------------------------------------------------
        # Keep the unsubscribe handles so a host can tear the system down cleanly.
        self._unsubs: List[Callable[[], None]] = []
        self._subscribe()

    # ------------------------------------------------------------------ setup
    def _subscribe(self) -> None:
        """Wire every counter to the event(s) that drive it."""
        sub = self.bus.subscribe
        self._unsubs.extend(
            [
                sub(EventType.COIN_COLLECTED, self._on_coin),
                sub(EventType.GEM_COLLECTED, self._on_gem),
                sub(EventType.NEAR_MISS, self._on_near_miss),
                sub(EventType.POWERUP_COLLECTED, self._on_powerup),
                sub(EventType.OBSTACLE_HIT, self._on_obstacle_hit),
                sub(EventType.COMBO_CHANGED, self._on_combo),
                sub(EventType.MILESTONE_REACHED, self._on_milestone),
                sub(EventType.BIOME_CHANGED, self._on_biome),
                sub(EventType.GAME_OVER, self._on_game_over),
            ]
        )

    def close(self) -> None:
        """Detach from the event bus. Safe to call more than once."""
        for off in self._unsubs:
            try:
                off()
            except Exception:  # pragma: no cover - defensive
                pass
        self._unsubs.clear()

    # ------------------------------------------------------------- persistence
    def _section(self) -> Dict[str, Any]:
        """Return the live ``achievements`` save section, tolerating a bad save.

        A missing or misbehaving ``get_section`` must not stop achievements from
        working; we degrade to an in-memory dict so the system is still fully
        functional (just non-persistent) in that unlikely case.
        """
        try:
            section = self.save.get_section("achievements")
        except Exception:  # pragma: no cover - defensive
            section = None
        if not isinstance(section, dict):
            section = {}
        return section

    @staticmethod
    def _ensure_dict(container: Dict[str, Any], key: str) -> Dict[str, Any]:
        """Return ``container[key]`` as a dict, creating/repairing it in place.

        Because the section is a live reference into the save, the created dict
        is stored back into ``container`` so subsequent :meth:`_persist` writes
        capture it.
        """
        value = container.get(key)
        if not isinstance(value, dict):
            value = {}
            container[key] = value
        return value

    def _normalise_metrics(self) -> None:
        """Coerce every persisted lifetime counter to a non-negative int.

        A hand-edited or partially-corrupt save could contain strings or missing
        keys; normalising up front means the hot-path handlers can assume ints.
        """
        for key in _LIFETIME_METRIC_KEYS:
            self._metrics[key] = self._as_nonneg_int(self._metrics.get(key, 0))

    def _persist(self) -> None:
        """Flush the save to disk, best-effort.

        Called after any unlock or lifetime-counter change. The save manager
        already swallows and logs I/O errors, but we still guard the call so a
        surprising exception can never escape onto the event-dispatch path.
        """
        try:
            self.save.save()
        except Exception:  # pragma: no cover - save() is itself defensive
            pass

    # ------------------------------------------------------------- run counters
    def _reset_run_counters(self) -> None:
        """Zero every per-run tally and clear the per-run "seen" sets."""
        self._run = {key: 0 for key in _RUN_METRIC_KEYS}
        self._run_powerup_keys.clear()
        self._run_biome_keys.clear()

    def reset_run(self) -> None:
        """Clear per-run progress at the start of a fresh run.

        Lifetime counters and unlock flags are untouched; only the volatile
        this-run tallies (distance, time, near misses, boost smashes, powerup
        types, biomes, the x4-combo flag) are reset. Already-unlocked
        achievements stay unlocked forever.
        """
        self._reset_run_counters()

    # ------------------------------------------------------------- counter bumps
    def _bump_lifetime(self, metric: str, amount: int = 1) -> None:
        """Add ``amount`` to a persisted lifetime counter, then re-check + save.

        Only achievements watching this exact metric are re-evaluated, and we
        persist regardless of whether an unlock fired so the running total itself
        is durable (a player who quits at 999 coins keeps their 999).
        """
        if amount == 0:
            return
        self._metrics[metric] = self._as_nonneg_int(self._metrics.get(metric, 0)) + amount
        unlocked_any = self._check_metric(metric)
        # Persist the counter change even without an unlock so lifetime totals
        # survive; the unlock path (if any) also persisted, but a second cheap
        # save is harmless and keeps the two code paths simple.
        if not unlocked_any:
            self._persist()

    def _bump_run(self, metric: str, amount: int = 1) -> None:
        """Add ``amount`` to a volatile per-run counter and re-check it.

        Per-run counters are never persisted directly (only the unlock they
        might trigger is), so this does not save unless an achievement unlocks.
        """
        if amount == 0:
            return
        self._run[metric] = self._run.get(metric, 0) + amount
        self._check_metric(metric)

    def _set_run(self, metric: str, value: int) -> None:
        """Set a per-run counter to an absolute ``value`` (monotonic upward).

        Used for gauges that are naturally absolute rather than incremental — the
        current run distance and elapsed time — so late/duplicate events can't
        double-count. We never move a counter backwards within a run.
        """
        current = self._run.get(metric, 0)
        if value > current:
            self._run[metric] = value
            self._check_metric(metric)

    # ------------------------------------------------------------- unlock logic
    def _check_metric(self, metric: str) -> bool:
        """Re-evaluate every achievement that watches ``metric``.

        Returns ``True`` if at least one achievement unlocked as a result, so the
        caller can avoid a redundant second save.
        """
        unlocked_any = False
        for ach in self.achievements:
            if ach.metric != metric:
                continue
            if self._is_unlocked(ach.id):
                continue
            if ach.is_met(self._raw_value(ach)):
                self._unlock(ach)
                unlocked_any = True
        return unlocked_any

    def _reconcile_unlocks(self) -> None:
        """Unlock, silently, anything already satisfied by persisted state.

        Runs once at construction. If a save predates a newly-added lifetime
        achievement whose goal it already meets, we mark it unlocked *without*
        firing a toast/event (the player earned it in a prior session; spamming
        celebrations on boot would be obnoxious). Per-run achievements never
        reconcile on boot because their counters start at zero.
        """
        changed = False
        for ach in self.achievements:
            if ach.scope != SCOPE_LIFETIME:
                continue
            if self._is_unlocked(ach.id):
                continue
            if ach.is_met(self._raw_value(ach)):
                self._unlocked[ach.id] = True
                changed = True
        if changed:
            self._persist()

    def _unlock(self, ach: Achievement) -> None:
        """Latch ``ach`` unlocked, persist it, and celebrate.

        Idempotent: a double call is a no-op. On the first unlock we mark the
        flag, save, then publish ``ACHIEVEMENT_UNLOCKED`` (carrying the record so
        listeners have its name/icon) and a ``TOAST`` for the on-screen banner.
        Publishing happens *after* persisting so the unlock is durable even if a
        listener does something slow or throws.
        """
        if self._is_unlocked(ach.id):
            return
        self._unlocked[ach.id] = True
        self._persist()

        # Announce it. These emits are wrapped so a misbehaving listener can't
        # take down the handler that triggered the unlock.
        try:
            self.bus.emit(EventType.ACHIEVEMENT_UNLOCKED, achievement=ach)
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            self.bus.emit(
                EventType.TOAST,
                text=f"Achievement: {ach.name}",
                color=Palette.GOLD,
                icon=ach.icon,
            )
        except Exception:  # pragma: no cover - defensive
            pass

    def _is_unlocked(self, achievement_id: str) -> bool:
        """Return whether ``achievement_id`` has been earned (persisted flag)."""
        return bool(self._unlocked.get(achievement_id, False))

    # ------------------------------------------------------------- value lookup
    def _raw_value(self, ach: Achievement) -> int:
        """Fetch the current raw counter value backing ``ach`` (unclamped)."""
        if ach.scope == SCOPE_RUN:
            return int(self._run.get(ach.metric, 0))
        return int(self._metrics.get(ach.metric, 0))

    def _progress_for(self, ach: Achievement) -> int:
        """Return the goal-clamped progress figure for the achievements screen."""
        return ach.progress_from(self._raw_value(ach))

    # --------------------------------------------------------- event handlers
    # Every handler is defensive: it reads its payload tolerantly and swallows
    # errors so a malformed event can never break the dispatch loop. Counters are
    # the only side effect; the counter helpers handle unlock/persist.

    def _on_coin(self, event: Event) -> None:
        """A coin was collected: one coin toward the lifetime coin total.

        We count *one coin per event* rather than the event's point ``value``:
        the "1000 coins" goal is about coins picked up, not score, so a x2 coin
        multiplier should not inflate progress.
        """
        try:
            self._bump_lifetime("coins_total", 1)
        except Exception:  # pragma: no cover - defensive
            pass

    def _on_gem(self, event: Event) -> None:
        """A gem was collected: one gem toward the lifetime gem total."""
        try:
            self._bump_lifetime("gems_total", 1)
        except Exception:  # pragma: no cover - defensive
            pass

    def _on_near_miss(self, event: Event) -> None:
        """A near miss occurred: one toward the per-run near-miss tally."""
        try:
            self._bump_run("run_near_misses", 1)
        except Exception:  # pragma: no cover - defensive
            pass

    def _on_powerup(self, event: Event) -> None:
        """A powerup was collected: track distinct types seen this run.

        ``run_powerup_types`` is the *number of distinct* powerup keys collected
        this run (for "collect every powerup type in one run"), so we key off a
        set and only bump the counter when a genuinely new type appears.
        """
        try:
            power = event.get("power")
            if not power or power in self._run_powerup_keys:
                return
            self._run_powerup_keys.add(power)
            self._set_run("run_powerup_types", len(self._run_powerup_keys))
        except Exception:  # pragma: no cover - defensive
            pass

    def _on_obstacle_hit(self, event: Event) -> None:
        """An obstacle was hit: count boost-smashes.

        ``OBSTACLE_HIT`` carries ``{fatal, smashed}``. A *smashed* obstacle is one
        the player barrelled through (boost/shield invincibility) rather than one
        that ended the run. We only credit the "wrecking ball" achievement for
        non-fatal smashes, which is exactly plowing through while boosting.
        """
        try:
            smashed = bool(event.get("smashed", False))
            fatal = bool(event.get("fatal", False))
            if smashed and not fatal:
                self._bump_run("run_boost_smashes", 1)
        except Exception:  # pragma: no cover - defensive
            pass

    def _on_combo(self, event: Event) -> None:
        """The combo changed: flag when it reaches the x4 maximum this run.

        ``run_combo_x4`` is a 0/1 latch (goal 1). Once the combo hits 4.0 in a
        run we set it and it stays set until :meth:`reset_run`.
        """
        try:
            combo = float(event.get("combo", 0.0))
            # Compare with a small epsilon: the combo is built from repeated
            # float additions of COMBO_STEP and may land at 3.9999999.
            if combo >= 4.0 - 1e-6 and self._run.get("run_combo_x4", 0) == 0:
                self._set_run("run_combo_x4", 1)
        except Exception:  # pragma: no cover - defensive
            pass

    def _on_milestone(self, event: Event) -> None:
        """A distance milestone was reached: update the per-run distance gauge.

        ``MILESTONE_REACHED`` carries ``{meters}`` at each 500 m boundary, which
        is a convenient, event-driven proxy for run distance without us having to
        poll the player every frame. It is absolute, so we set (not add) it.
        """
        try:
            meters = int(event.get("meters", 0))
            if meters > 0:
                self._set_run("run_distance_m", meters)
        except Exception:  # pragma: no cover - defensive
            pass

    def _on_biome(self, event: Event) -> None:
        """The biome changed: track distinct biomes visited this run.

        ``BIOME_CHANGED`` carries ``{biome, key}``. Like powerup types we key off
        a set of distinct biome keys and set the run counter to the set size.
        """
        try:
            key = event.get("key")
            if not key or key in self._run_biome_keys:
                return
            self._run_biome_keys.add(key)
            self._set_run("run_biomes", len(self._run_biome_keys))
        except Exception:  # pragma: no cover - defensive
            pass

    def _on_game_over(self, event: Event) -> None:
        """A run ended: fold this run's totals into the persisted lifetime ones.

        Per-run distance and run-count are lifetime-relevant, so on game over we
        add the finished run's distance to ``distance_total_m`` and increment
        ``runs_total`` (both watched by lifetime achievements). The event may
        carry ``distance_m``; if not we fall back to the highest per-run distance
        the milestone events gave us. We deliberately do *not* reset per-run
        counters here — :meth:`reset_run` owns that at the *start* of the next
        run, so the game-over screen can still read this run's stats.
        """
        try:
            distance_m = self._as_nonneg_int(
                event.get("distance_m", event.get("distance", self._run.get("run_distance_m", 0)))
            )
            if distance_m > 0:
                self._bump_lifetime("distance_total_m", distance_m)
            self._bump_lifetime("runs_total", 1)
        except Exception:  # pragma: no cover - defensive
            pass

    # ------------------------------------------------------------------ frame
    def update(self, dt: float, player: Optional[Any] = None) -> None:
        """Advance time-based per-run counters by one frame.

        The only time-driven achievement is "survive 3 minutes", so we accumulate
        elapsed run time here. ``player`` is accepted for symmetry with the other
        systems' ``update`` signatures and, when supplied and alive, lets us keep
        the per-run distance gauge current between the coarse 500 m milestone
        events. The method never raises: it is on the hot path.

        Parameters
        ----------
        dt:
            Frame delta-time in seconds.
        player:
            Optional read-only player object. If it exposes ``alive`` and
            ``distance`` we use them to refine the run-time and run-distance
            gauges; otherwise time still advances on ``dt`` alone.
        """
        try:
            if dt <= 0.0:
                return
            # Only accrue survival time while the player is actually running. If
            # we were not handed a player we optimistically count the time (the
            # caller is responsible for only ticking us during active play).
            alive = True
            if player is not None:
                alive = bool(getattr(player, "alive", True))
            if alive:
                # Elapsed time is fractional; accumulate in a float and only push
                # whole seconds into the (integer) run counter so we don't lose
                # sub-second slivers to truncation.
                self._run_time_accum += dt
                whole = int(self._run_time_accum)
                if whole > 0:
                    self._run_time_accum -= whole
                    self._bump_run("run_time_s", whole)

            # Opportunistically refine run distance from the live player, which is
            # finer-grained than the 500 m milestone pulses.
            if player is not None:
                distance_units = getattr(player, "distance", None)
                if isinstance(distance_units, (int, float)):
                    self._set_run("run_distance_m", int(distance_units * _METERS_PER_UNIT))
        except Exception:  # pragma: no cover - defensive
            pass

    # ------------------------------------------------------------------ query
    def snapshot(self) -> List[Dict[str, Any]]:
        """Return the achievements-screen view as a list of plain dicts.

        Each entry is ``{id, name, description, icon, unlocked, progress, goal}``
        with ``progress`` clamped to ``goal``. The list preserves the catalogue's
        easy-to-hard ordering so the screen can render it directly. This is the
        blessed read path; UI code should not reach into the private counters.
        """
        out: List[Dict[str, Any]] = []
        for ach in self.achievements:
            out.append(
                {
                    "id": ach.id,
                    "name": ach.name,
                    "description": ach.description,
                    "icon": ach.icon,
                    "unlocked": self._is_unlocked(ach.id),
                    "progress": self._progress_for(ach),
                    "goal": ach.goal,
                }
            )
        return out

    def unlocked_count(self) -> int:
        """Return how many achievements are currently unlocked."""
        return sum(1 for a in self.achievements if self._is_unlocked(a.id))

    def total_count(self) -> int:
        """Return the total number of achievements in the catalogue."""
        return len(self.achievements)

    def is_unlocked(self, achievement_id: str) -> bool:
        """Public query: has ``achievement_id`` been earned?"""
        return self._is_unlocked(achievement_id)

    def get(self, achievement_id: str) -> Optional[Achievement]:
        """Return the :class:`Achievement` record for an id, or ``None``."""
        return self._by_id.get(achievement_id)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _as_nonneg_int(value: Any) -> int:
        """Coerce ``value`` to a non-negative int, defaulting bad input to 0."""
        try:
            n = int(float(value))
        except (TypeError, ValueError):
            return 0
        return n if n > 0 else 0

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"AchievementSystem(unlocked={self.unlocked_count()}/"
            f"{self.total_count()})"
        )

    # A float accumulator for sub-second run time, declared here as a class-level
    # default so ``update`` can use it even before the first tick. Instance
    # assignment in ``update`` shadows it per-instance.
    _run_time_accum: float = 0.0


# ---------------------------------------------------------------------------
# Metric-key registries
# ---------------------------------------------------------------------------
# Enumerating the metric keys once (rather than scattering string literals) lets
# the constructor pre-seed every counter to zero and normalise persisted values,
# and documents the full set of counters the system maintains. These must stay in
# sync with the ``metric`` fields used in ``_build_catalogue``.
_LIFETIME_METRIC_KEYS = (
    "coins_total",
    "gems_total",
    "distance_total_m",
    "runs_total",
)

_RUN_METRIC_KEYS = (
    "run_distance_m",
    "run_time_s",
    "run_near_misses",
    "run_boost_smashes",
    "run_powerup_types",
    "run_combo_x4",
    "run_biomes",
)

# Local mirror of the world-unit -> displayed-metre conversion. We keep it as a
# module constant (rather than importing Gameplay everywhere) so ``update`` can
# convert player distance cheaply. Matches ``Gameplay.METERS_PER_UNIT``.
_METERS_PER_UNIT = 1.0 / 100.0
