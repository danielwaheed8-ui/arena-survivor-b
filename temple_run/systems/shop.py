"""
Shop — where coins earned in the temple become lasting power.

The :class:`Shop` is the game's economy sink. Every coin the player grabs while
running (and every coin a completed mission drops into the wallet) accumulates in
``save.data["coins_balance"]``; the shop is the one place that *spends* it. It
sells two fundamentally different things:

* **Upgrades** — multi-level, permanent stat boosts. Each level costs more than
  the last and grants a little more of some gameplay quantity (a longer magnet, a
  fatter coin value, a head-start off the line, a one-shot revive, ...). An
  upgrade is described once, declaratively, by an :class:`ShopItem`; the concrete
  per-level price and effect are *computed* from that description, so re-balancing
  is a one-line edit and the save only ever needs to store an integer level.

* **Skins / characters** — one-time cosmetic unlocks. They cost coins once and
  then stay unlocked forever. They carry no gameplay effect (this game rewards
  skill, not wallet), so they live in a separate save section and a separate code
  path from the numeric upgrades.

Design notes / rationale
------------------------
* **Declarative catalogue, computed values.** An :class:`ShopItem` is immutable
  data: a name, a description, a kind, and — for upgrades — a base price, a price
  growth factor, a max level, and a per-level effect *step*. Prices grow
  geometrically (``base * growth**level``) which is the classic "each rank hurts a
  bit more" curve every idle/runner economy uses; effects grow linearly from the
  step. Nothing about an owned item is stored except its integer level (upgrades)
  or a boolean (skins), so the save stays tiny and forward-compatible.

* **One writer for persistence.** Like every meta-system, the shop does not own a
  file. Upgrade levels live in ``save.get_section("upgrades")`` and skin unlocks
  in ``save.get_section("unlocked")`` — live dicts the :class:`SaveManager` owns.
  A successful purchase mutates the balance and the relevant section, then asks
  the save manager to flush, so there is a single source of truth and a single
  fsync per purchase.

* **The game reads *computed* getters, never raw levels.** Collision code asks
  ``shop.coin_value_bonus()``; the run bootstrap asks ``shop.head_start_units()``;
  the powerup manager could ask ``shop.magnet_duration_bonus()``. These translate
  the stored integer levels into the world-space quantities the engine actually
  uses, keeping the balance maths in exactly one place and out of the hot loop.

* **Purchases are all-or-nothing and announced.** :meth:`buy` validates funds and
  the level cap *before* mutating anything, so a rejected purchase leaves the save
  untouched. A successful one deducts the coins, bumps the level/unlock, persists,
  and then publishes ``SHOP_PURCHASE`` (always) plus ``UPGRADE_PURCHASED`` (for
  upgrades) and a celebratory ``TOAST`` so audio, achievements and the HUD can all
  react without the shop knowing they exist.

* **Never crash the loop.** The shop is touched from a menu, not the render loop,
  but its getters *are* read while playing. Every public method is defended so a
  corrupt save section, a bogus item id, or a malformed balance costs at most a
  wrong number — never a traceback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

Color = Tuple[int, int, int]

from ..config import Gameplay, Palette
from ..core.events import Event, EventBus, EventType
from ..entities.powerup_types import POWERUPS
from ..mathutils import clamp

__all__ = ["ShopItem", "Shop", "CATALOGUE"]

# World units per displayed metre. The config expresses the inverse
# (``METERS_PER_UNIT`` = metres per unit, e.g. 1/100), so units-per-metre is its
# reciprocal. Guarded so a pathological config value can never divide by zero.
_UNITS_PER_METER: float = (
    1.0 / Gameplay.METERS_PER_UNIT if Gameplay.METERS_PER_UNIT else 100.0
)
# Distance a single Head Start level grants, in displayed metres.
_HEAD_START_METERS_PER_LEVEL: float = 250.0


# The two "kinds" of thing the shop sells. Kept as bare strings (not an Enum) so
# they serialise trivially and read cleanly in the ``catalog()`` payload the UI
# consumes.
KIND_UPGRADE: str = "upgrade"
KIND_SKIN: str = "skin"


# ---------------------------------------------------------------------------
# A single catalogue entry
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ShopItem:
    """One purchasable thing: a multi-level upgrade *or* a one-time skin unlock.

    A :class:`ShopItem` is immutable, declarative data — it holds no live state.
    The player's *progress* against it (an upgrade's current level, whether a skin
    is owned) lives in the save sections and is looked up by ``id``. This split is
    deliberate: the catalogue can be re-tuned or reordered freely between builds
    without migrating anyone's save, because the save only ever stores an id and a
    small integer/flag.

    Fields
    ------
    id:
        Stable identifier used as the save-section key and in every event/payload.
        Never reuse an id for a different meaning across builds.
    name:
        Short player-facing title (e.g. "Coin Magnet Duration").
    desc:
        One-line description shown on the shop card. For upgrades it should read
        well with the per-level effect implied ("Each level extends the magnet").
    kind:
        Either :data:`KIND_UPGRADE` or :data:`KIND_SKIN`.
    base_price:
        Cost of the *first* purchase. For an upgrade this is the level-1 price; for
        a skin it is the (single) unlock price.
    price_growth:
        Geometric multiplier applied per already-owned level for upgrades: the cost
        to buy level ``L+1`` is ``base_price * price_growth**L`` (so level 1 costs
        ``base_price``). Ignored for skins (which are bought once).
    max_level:
        Highest attainable level for an upgrade (``1`` for a one-shot upgrade like
        revive; ``1`` for a skin — a skin is "owned" (level 1) or not (level 0)).
    effect_step:
        The gameplay quantity added *per level* for upgrades. Its units depend on
        the upgrade (world units for head-start, seconds for durations, points for
        coin value, ...); the computed getters know how to interpret it. ``0`` for
        skins and for upgrades whose effect is a plain boolean (e.g. revive, whose
        "effect" is simply "own >= 1 level").
    color:
        Accent ``(r, g, b)`` colour for the shop card / toast, purely cosmetic.
    """

    id: str
    name: str
    desc: str
    kind: str
    base_price: int
    price_growth: float
    max_level: int
    effect_step: float
    color: Color = Palette.UI_ACCENT

    # ---- derived helpers ------------------------------------------------- #
    @property
    def is_upgrade(self) -> bool:
        """``True`` for multi-level stat upgrades, ``False`` for skins."""
        return self.kind == KIND_UPGRADE

    def price_for_level(self, current_level: int) -> int:
        """Cost to buy the *next* level given ``current_level`` already owned.

        Uses the geometric growth curve ``base_price * growth**level``. The result
        is rounded to the nearest 5 coins so prices read as tidy numbers on the
        card rather than "1173"; it is always at least ``base_price`` for the first
        purchase. For a fully-owned item this is still computed (callers gate on
        :meth:`Shop.can_buy` / the level cap first), never raising.
        """
        level = max(0, int(current_level))
        growth = self.price_growth if self.price_growth > 0 else 1.0
        raw = self.base_price * (growth ** level)
        # Snap to a multiple of 5 for a clean shopfront, but never below 5.
        snapped = int(round(raw / 5.0)) * 5
        return max(5, snapped)


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------
# The single, hand-tuned list of everything for sale. Order here is display order
# in the shop. Prices/growth/steps are balanced so the early upgrades are within a
# run or two's reach and the later ranks are long-term goals; the numbers are the
# only thing a designer needs to touch to re-balance the economy.
#
# Effect-bearing upgrade ids are *also* referenced by the computed getters below,
# so renaming one means updating both places — hence they are named as module
# intent, not display strings.
CATALOGUE: List[ShopItem] = [
    # -- Upgrades ------------------------------------------------------------
    ShopItem(
        id="coin_value",
        name="Golden Touch",
        desc="Every coin is worth more. +1 point per coin per level.",
        kind=KIND_UPGRADE,
        base_price=150,
        price_growth=1.9,
        max_level=5,
        effect_step=1.0,          # +1 coin value per level
        color=Palette.GOLD,
    ),
    ShopItem(
        id="magnet_duration",
        name="Coin Magnet Duration",
        desc="Extends how long the Coin Magnet power-up lasts. +1.0 s per level.",
        kind=KIND_UPGRADE,
        base_price=200,
        price_growth=1.8,
        max_level=5,
        effect_step=1.0,          # +1.0 s per level
        color=POWERUPS["magnet"].color if "magnet" in POWERUPS else Palette.INFO,
    ),
    ShopItem(
        id="boost_duration",
        name="Speed Boost Duration",
        desc="Extends how long the Speed Boost power-up lasts. +0.75 s per level.",
        kind=KIND_UPGRADE,
        base_price=220,
        price_growth=1.8,
        max_level=5,
        effect_step=0.75,         # +0.75 s per level
        color=POWERUPS["boost"].color if "boost" in POWERUPS else Palette.WARNING,
    ),
    ShopItem(
        id="score_multiplier",
        name="Score Booster",
        desc="A permanent bonus to all points. +10% score per level.",
        kind=KIND_UPGRADE,
        base_price=300,
        price_growth=2.1,
        max_level=5,
        effect_step=0.10,         # +0.10 to the score multiplier per level
        color=Palette.UI_ACCENT,
    ),
    ShopItem(
        id="head_start",
        name="Head Start",
        desc="Begin each run already sprinting. +250 m of free distance per level.",
        kind=KIND_UPGRADE,
        base_price=250,
        price_growth=2.0,
        max_level=4,
        # 250 m of head-start per level, stored in world units (100 u = 1 m).
        effect_step=_HEAD_START_METERS_PER_LEVEL * _UNITS_PER_METER,
        color=Palette.SUCCESS,
    ),
    ShopItem(
        id="revive",
        name="Second Wind",
        desc="Once per run, shrug off a fatal hit and keep running.",
        kind=KIND_UPGRADE,
        base_price=800,
        price_growth=1.0,         # single level; growth is irrelevant
        max_level=1,
        effect_step=0.0,          # boolean effect: owned or not
        color=Palette.DANGER,
    ),
    # -- Skins (one-time cosmetic unlocks) -----------------------------------
    ShopItem(
        id="skin_azure",
        name="Azure Explorer",
        desc="A cool-blue outfit for the daring runner. Cosmetic only.",
        kind=KIND_SKIN,
        base_price=500,
        price_growth=1.0,
        max_level=1,
        effect_step=0.0,
        color=Palette.INFO,
    ),
    ShopItem(
        id="skin_ember",
        name="Ember Raider",
        desc="Blaze down the track in fiery reds. Cosmetic only.",
        kind=KIND_SKIN,
        base_price=750,
        price_growth=1.0,
        max_level=1,
        effect_step=0.0,
        color=Palette.PLAYER,
    ),
    ShopItem(
        id="skin_shadow",
        name="Shadow Stalker",
        desc="A sleek all-black outfit for the temple's most elusive. Cosmetic only.",
        kind=KIND_SKIN,
        base_price=1200,
        price_growth=1.0,
        max_level=1,
        effect_step=0.0,
        color=Palette.DARK_GREY,
    ),
]

# Index by id for O(1) lookup from ids in save data / event payloads.
_ITEM_BY_ID: Dict[str, ShopItem] = {item.id: item for item in CATALOGUE}


class Shop:
    """Owns the catalogue, spends the wallet, and exposes computed gameplay values.

    Lifecycle::

        shop = Shop(event_bus=bus, save=save)   # reads levels/unlocks from save
        ...
        if shop.buy("coin_value"):              # menu button
            ...                                 # persisted + announced for you
        ...
        bonus = shop.coin_value_bonus()         # collision code, every pickup
        head  = shop.head_start_units()         # run bootstrap

    The shop is a pure-logic meta-system: it never touches a pygame surface and
    never reads the event queue. It *publishes* purchase events (so audio and
    achievements can react) but subscribes to nothing — nothing that happens in a
    run changes what you own.
    """

    def __init__(self, event_bus: EventBus, save: Any) -> None:
        """Bind to the event bus and the save manager.

        Parameters
        ----------
        event_bus:
            The shared :class:`EventBus`. Purchases publish ``SHOP_PURCHASE`` /
            ``UPGRADE_PURCHASED`` / ``TOAST`` here. May not be ``None`` in normal
            use, but the shop tolerates a ``None`` bus (it simply skips
            announcements) so it stays unit-testable in isolation.
        save:
            The :class:`~temple_run.systems.save.SaveManager` (duck-typed — we use
            ``data``, ``get_section``, ``add`` and ``save``). Upgrade levels live
            in ``save.get_section("upgrades")`` and skin unlocks in
            ``save.get_section("unlocked")``; the wallet is
            ``save.data["coins_balance"]``.
        """
        self.bus: Optional[EventBus] = event_bus
        self.save: Any = save

        # Touch both sections once up front so they exist (auto-created) and any
        # corrupt shape is repaired before the first purchase.
        self._normalise_sections()

    # ------------------------------------------------------------------ #
    # Save-section access
    # ------------------------------------------------------------------ #
    def _upgrades(self) -> Dict[str, Any]:
        """The live ``upgrades`` sub-dict (id -> integer level)."""
        return self.save.get_section("upgrades")

    def _unlocked(self) -> Dict[str, Any]:
        """The live ``unlocked`` sub-dict (id -> truthy flag) for skins."""
        return self.save.get_section("unlocked")

    def _normalise_sections(self) -> None:
        """Coerce the two owned-state sections into well-typed shapes.

        A hand-edited or partially-written save might hold, say, a string where an
        upgrade level should be an int, or a level above the item's cap. We clamp
        every known upgrade level into ``[0, max_level]`` and coerce every unlock
        flag to a bool, leaving unknown keys (from a newer build) untouched so we
        never destroy data we don't understand.
        """
        try:
            upgrades = self._upgrades()
            for item in CATALOGUE:
                if not item.is_upgrade:
                    continue
                level = self._coerce_level(upgrades.get(item.id, 0), item.max_level)
                upgrades[item.id] = level
        except Exception as exc:  # pragma: no cover - defensive
            self._log(f"could not normalise upgrades section: {exc!r}")

        try:
            unlocked = self._unlocked()
            for item in CATALOGUE:
                if item.is_upgrade:
                    continue
                unlocked[item.id] = bool(unlocked.get(item.id, False))
        except Exception as exc:  # pragma: no cover - defensive
            self._log(f"could not normalise unlocked section: {exc!r}")

    # ------------------------------------------------------------------ #
    # Wallet
    # ------------------------------------------------------------------ #
    def balance(self) -> int:
        """The player's spendable coin balance, coerced to a non-negative int."""
        try:
            raw = self.save.data.get("coins_balance", 0)
            value = int(raw)
        except (TypeError, ValueError, AttributeError):
            return 0
        return value if value > 0 else 0

    # ------------------------------------------------------------------ #
    # Item queries
    # ------------------------------------------------------------------ #
    def item(self, item_id: str) -> Optional[ShopItem]:
        """The :class:`ShopItem` for ``item_id``, or ``None`` if unknown."""
        return _ITEM_BY_ID.get(item_id)

    def level(self, item_id: str) -> int:
        """Current owned level of ``item_id``.

        For upgrades this is the stored integer level (0 if never bought). For
        skins it is ``1`` if unlocked and ``0`` otherwise, so skins and upgrades
        answer "how much do I own" uniformly. Unknown ids return ``0``.
        """
        item = self.item(item_id)
        if item is None:
            return 0
        if item.is_upgrade:
            return self._coerce_level(self._upgrades().get(item_id, 0), item.max_level)
        # Skin: owned == level 1.
        return 1 if self.is_unlocked(item_id) else 0

    def max_level(self, item_id: str) -> int:
        """The highest attainable level for ``item_id`` (``0`` if unknown)."""
        item = self.item(item_id)
        return item.max_level if item is not None else 0

    def is_unlocked(self, item_id: str) -> bool:
        """Whether a *skin* is unlocked (always ``True`` for owned upgrades).

        For a skin this reads the ``unlocked`` section. For an upgrade "unlocked"
        is read as "owned at least one level", which lets generic UI treat both
        kinds the same when it just wants a yes/no "do I have this".
        """
        item = self.item(item_id)
        if item is None:
            return False
        if item.is_upgrade:
            return self.level(item_id) > 0
        return bool(self._unlocked().get(item_id, False))

    def is_maxed(self, item_id: str) -> bool:
        """Whether ``item_id`` is owned at its maximum level (fully bought)."""
        item = self.item(item_id)
        if item is None:
            return True  # nothing to buy for an unknown id
        return self.level(item_id) >= item.max_level

    def price(self, item_id: str) -> int:
        """Cost of the *next* purchase of ``item_id``.

        For an upgrade this is the price of the next level given the current one;
        for a skin it is the flat unlock price. A fully-owned item still returns a
        number (its would-be next price) — callers should gate on :meth:`is_maxed`
        for display ("MAX") rather than reading a sentinel here. Unknown ids return
        ``0``.
        """
        item = self.item(item_id)
        if item is None:
            return 0
        if item.is_upgrade:
            return item.price_for_level(self.level(item_id))
        return item.price_for_level(0)  # skins: single flat price

    def can_buy(self, item_id: str) -> bool:
        """Whether ``item_id`` can be bought *right now* (funds + not maxed)."""
        item = self.item(item_id)
        if item is None or self.is_maxed(item_id):
            return False
        return self.balance() >= self.price(item_id)

    # ------------------------------------------------------------------ #
    # Purchasing
    # ------------------------------------------------------------------ #
    def buy(self, item_id: str) -> bool:
        """Attempt to purchase the next level / unlock of ``item_id``.

        The purchase is validated before any state changes, so a failed buy is a
        clean no-op:

        * unknown id, already maxed, or insufficient funds -> return ``False``.

        On success we, in order:

        1. deduct the price from ``coins_balance`` (via ``save.add`` so the counter
           stays integral),
        2. increment the upgrade level *or* flip the skin unlock flag,
        3. flush the save so the purchase survives a crash,
        4. publish ``SHOP_PURCHASE`` (always), ``UPGRADE_PURCHASED`` (upgrades
           only), and a celebratory ``TOAST``.

        Returns ``True`` on a completed purchase, ``False`` otherwise. Never raises
        — a persistence or event-bus hiccup is logged, and the in-memory state
        (already mutated) remains consistent so the player still owns what they
        paid for.
        """
        item = self.item(item_id)
        if item is None:
            self._log(f"buy({item_id!r}) — unknown item")
            return False

        if self.is_maxed(item_id):
            # Nothing left to buy; a well-behaved UI won't offer the button, but a
            # double-click or a stale screen might still try.
            return False

        cost = self.price(item_id)
        if self.balance() < cost:
            return False

        # ---- commit the purchase -------------------------------------------
        # Deduct first. ``add`` with a negative amount keeps the balance an int and
        # self-heals a corrupt (non-numeric) value to 0 before subtracting.
        try:
            self.save.add("coins_balance", -cost)
        except Exception as exc:  # pragma: no cover - defensive
            self._log(f"could not deduct coins for {item_id!r}: {exc!r}")
            return False

        new_level: int
        if item.is_upgrade:
            new_level = min(item.max_level, self.level(item_id) + 1)
            try:
                self._upgrades()[item_id] = new_level
            except Exception as exc:  # pragma: no cover - defensive
                self._log(f"could not record upgrade level for {item_id!r}: {exc!r}")
        else:
            new_level = 1
            try:
                self._unlocked()[item_id] = True
            except Exception as exc:  # pragma: no cover - defensive
                self._log(f"could not record unlock for {item_id!r}: {exc!r}")

        # ---- persist -------------------------------------------------------
        try:
            self.save.save()
        except Exception as exc:  # pragma: no cover - defensive
            self._log(f"could not persist purchase of {item_id!r}: {exc!r}")

        # ---- announce ------------------------------------------------------
        self._announce_purchase(item, new_level, cost)
        return True

    def _announce_purchase(self, item: ShopItem, new_level: int, cost: int) -> None:
        """Publish the purchase events and a toast. Best-effort, never raises.

        ``SHOP_PURCHASE`` fires for everything (audio's button/purchase sting,
        achievements that count spends). ``UPGRADE_PURCHASED`` fires only for
        upgrades and carries the new level so an achievement like "max out an
        upgrade" can check it. The toast wording adapts to kind and to hitting the
        cap.
        """
        if self.bus is None:
            return

        # A tidy status line for the toast: skins and maxed upgrades read
        # differently from a plain rank-up.
        if not item.is_upgrade:
            message = f"Unlocked: {item.name}"
        elif new_level >= item.max_level:
            message = f"{item.name} maxed! (Lv {new_level})"
        else:
            message = f"{item.name} upgraded to Lv {new_level}"

        try:
            # The purchase fact, for anything that cares about spends generally.
            self.bus.publish(
                Event(
                    EventType.SHOP_PURCHASE,
                    {
                        "id": item.id,
                        "kind": item.kind,
                        "level": new_level,
                        "cost": cost,
                    },
                )
            )
            # A narrower event for upgrade-only reactions (progression tracking).
            if item.is_upgrade:
                self.bus.publish(
                    Event(
                        EventType.UPGRADE_PURCHASED,
                        {"id": item.id, "level": new_level, "cost": cost},
                    )
                )
            # Player-facing confirmation.
            self.bus.emit(
                EventType.TOAST,
                text=message,
                color=item.color,
                icon="shop",
            )
        except Exception as exc:  # pragma: no cover - defensive
            self._log(f"could not announce purchase of {item.id!r}: {exc!r}")

    # ------------------------------------------------------------------ #
    # Computed gameplay values (read by the running game)
    # ------------------------------------------------------------------ #
    # These translate stored levels into the concrete quantities the engine uses.
    # Keeping the maths here — not scattered across collision/scoring code — means
    # a rebalance touches one function, and the getters can be called every frame
    # without re-reading balance/level parsing more than a cheap dict lookup.

    def coin_value_bonus(self) -> int:
        """Extra points added to every coin's value, from the coin_value upgrade.

        Collision/scoring adds this on top of ``Gameplay.COIN_VALUE`` per coin. At
        level 0 it is ``0``; each level adds ``effect_step`` (1) point.
        """
        return int(self._upgrade_amount("coin_value"))

    def magnet_duration_bonus(self) -> float:
        """Extra seconds added to the Coin Magnet power-up's duration."""
        return float(self._upgrade_amount("magnet_duration"))

    def boost_duration_bonus(self) -> float:
        """Extra seconds added to the Speed Boost power-up's duration."""
        return float(self._upgrade_amount("boost_duration"))

    def score_multiplier_bonus(self) -> float:
        """Additive bonus to the score multiplier (e.g. 0.30 at level 3).

        The scoring system multiplies point gains by ``1.0 + this``, so a level-3
        Score Booster (3 x 0.10) makes every point worth 1.30x.
        """
        return float(self._upgrade_amount("score_multiplier"))

    def score_multiplier(self) -> float:
        """The full score multiplier the shop contributes: ``1.0 + bonus``.

        Provided as a convenience so callers can multiply directly without
        remembering to add the base 1.0.
        """
        return 1.0 + self.score_multiplier_bonus()

    def head_start_units(self) -> float:
        """World-unit distance the player begins each run already having covered.

        The run bootstrap seeds ``player.distance`` (and the scoring/difficulty
        ramp) with this so a Head Start upgrade both skips the slow opening metres
        and immediately counts toward distance-based score. ``0.0`` at level 0.
        """
        return float(self._upgrade_amount("head_start"))

    def head_start_meters(self) -> int:
        """The head-start expressed in displayed metres (for UI / achievements).

        Converts :meth:`head_start_units` using the same 100-units-per-metre scale
        the rest of the game uses, so the shop card and the run agree.
        """
        return int(round(self.head_start_units() * Gameplay.METERS_PER_UNIT))

    def has_revive(self) -> bool:
        """Whether the one-shot revive (Second Wind) is owned.

        The game consumes at most one revive per run; the shop only reports
        ownership. ``True`` once the single level of ``revive`` is bought.
        """
        return self.level("revive") >= 1

    def revive_charges(self) -> int:
        """Number of revives available at the *start* of a run (0 or 1).

        Kept as a count (not just a bool) so a future multi-charge upgrade needs no
        call-site changes; today it is exactly the owned level of ``revive``.
        """
        return self.level("revive")

    def active_skin(self) -> Optional[str]:
        """The id of the most-premium unlocked skin, or ``None`` if none owned.

        The game may use this to pick which player colours to draw. We return the
        *last* unlocked skin in catalogue order, treating catalogue order as
        "cheapest first, fanciest last" — a reasonable default "wear your best".
        Selection UI can override this later; the shop just reports a sensible pick.
        """
        chosen: Optional[str] = None
        for item in CATALOGUE:
            if item.kind == KIND_SKIN and self.is_unlocked(item.id):
                chosen = item.id
        return chosen

    def _upgrade_amount(self, item_id: str) -> float:
        """Total effect of an upgrade: ``level * effect_step`` (0 if unknown).

        The single place stored levels become effect magnitudes. All the public
        getters funnel through here so the "level times step" convention lives in
        exactly one function.
        """
        item = self.item(item_id)
        if item is None or not item.is_upgrade:
            return 0.0
        return self.level(item_id) * item.effect_step

    # ------------------------------------------------------------------ #
    # UI-facing catalogue
    # ------------------------------------------------------------------ #
    def catalog(self) -> List[Dict[str, Any]]:
        """Return the whole shopfront for the shop screen.

        Each entry matches the contract schema plus a few extras the card needs::

            {"id", "name", "desc", "price", "level", "max", "kind", "affordable"}

        ``affordable`` folds together "can I pay for it" and "is there anything
        left to buy" so a maxed item is never shown as affordable. ``price`` for a
        maxed item is still the computed would-be price; the UI should show "MAX"
        when ``level >= max``. Read-only and cheap; safe to call every frame the
        shop screen is open.
        """
        rows: List[Dict[str, Any]] = []
        balance = self.balance()
        for item in CATALOGUE:
            level = self.level(item.id)
            maxed = level >= item.max_level
            price = self.price(item.id)
            affordable = (not maxed) and balance >= price
            rows.append(
                {
                    "id": item.id,
                    "name": item.name,
                    "desc": item.desc,
                    "price": price,
                    "level": level,
                    "max": item.max_level,
                    "kind": item.kind,
                    "affordable": affordable,
                    # Extras the card can use but the contract schema doesn't require.
                    "maxed": maxed,
                    "color": item.color,
                    "owned": self.is_unlocked(item.id),
                }
            )
        return rows

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _coerce_level(value: Any, max_level: int) -> int:
        """Coerce a stored level into a clean int in ``[0, max_level]``.

        Defends against a corrupt save section: non-numeric, negative, or
        over-cap values all collapse to a valid level rather than propagating a
        bad number into price/effect maths.
        """
        try:
            level = int(value)
        except (TypeError, ValueError):
            return 0
        cap = max(0, int(max_level))
        return int(clamp(level, 0, cap))

    def _log(self, message: str) -> None:
        """Emit a diagnostic line to stdout. Never raises."""
        try:
            print(f"[shop] {message}")
        except Exception:  # pragma: no cover - stdout should always work
            pass

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        owned = ", ".join(
            f"{item.id}:{self.level(item.id)}/{item.max_level}"
            for item in CATALOGUE
        )
        return f"<Shop balance={self.balance()} [{owned}]>"
