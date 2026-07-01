# Temple Run — Systems Contract (read fully before implementing)

You are implementing **one module** of a larger pygame game called *Temple Run —
World-Class Python Edition*. The pseudo-3D engine core already exists and works.
Your module must plug into it through the stable interfaces below. **Do not**
modify any existing file; only create the single file you are assigned.

## House rules

- **Language:** Python 3.11, standard library + `pygame` only. No other pip deps.
- **Style:** Start every file with a thorough module docstring explaining the
  design and *why*. Use type hints. Comment non-obvious logic. Match the tone of
  the existing codebase (clear, professional, a little opinionated). Aim for the
  line target given in your task (substantial, not padded).
- **Imports:** Use package-relative imports (e.g. `from ..core.events import
  EventBus`). You may import from the "Core APIs" listed below and from Python
  stdlib and `pygame`. Do **not** import sibling fan-out modules (they may not
  exist yet) unless explicitly told to.
- **Robustness:** Never crash the game. Guard optional subsystems (e.g. audio
  mixer) with try/except and degrade gracefully. Never raise from a draw/update
  path.
- **Self-check:** After writing the file, run
  `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python3 -m py_compile <yourfile>`
  and fix any errors. If your module is easily unit-testable in isolation, do a
  quick `python3 -c` smoke import too. Iterate until it compiles cleanly.
- Return the required structured result (file path, exported symbols, line count).

## Coordinate & timing conventions

- Time is in seconds; every `update(dt)` receives a delta-time float (~1/60).
- Screen is `Config.WIDTH` x `Config.HEIGHT` (1280x720). UI is drawn in screen
  pixels. World/3D is handled by the engine; **your modules are screen-space or
  pure logic** unless stated.

## Core APIs you may rely on (already implemented)

### `temple_run.core.events`
```python
class EventType(Enum):
    # flow
    GAME_START, GAME_OVER, GAME_RESTART, PAUSE, RESUME, STATE_CHANGED, QUIT
    # player
    PLAYER_JUMP, PLAYER_SLIDE, PLAYER_LANE_CHANGE, PLAYER_LAND, PLAYER_STUMBLE, PLAYER_DIED
    # pickups / hazards
    COIN_COLLECTED, GEM_COLLECTED, POWERUP_COLLECTED, POWERUP_STARTED, POWERUP_ENDED,
    OBSTACLE_HIT, NEAR_MISS
    # meta / progression
    SCORE_CHANGED, COMBO_CHANGED, MILESTONE_REACHED, BIOME_CHANGED,
    ACHIEVEMENT_UNLOCKED, MISSION_PROGRESS, MISSION_COMPLETED, SHOP_PURCHASE, UPGRADE_PURCHASED
    # ui
    UI_BUTTON, TOAST, SCREEN_SHAKE

@dataclass
class Event:
    type: EventType
    data: dict
    def get(self, key, default=None): ...

class EventBus:
    def subscribe(self, event_type, listener) -> unsubscribe_fn   # listener(event)
    def subscribe_all(self, listener) -> unsubscribe_fn
    def unsubscribe(self, event_type, listener)
    def publish(self, event: Event)
    def emit(self, event_type, **data)   # convenience: emit(EventType.TOAST, text="hi")
    def clear(self)
```

**Event payload schemas** (the `.data` dict):
- `COIN_COLLECTED`: `{entity, value:int}` (value already includes coin multiplier)
- `GEM_COLLECTED`: `{entity, value:int}`
- `POWERUP_COLLECTED`: `{entity, power:str}`  (power is a key in POWERUPS)
- `POWERUP_STARTED` / `POWERUP_ENDED`: `{power:str, type:PowerupType}`
- `NEAR_MISS`: `{entity, distance:float}`
- `OBSTACLE_HIT`: `{entity, fatal:bool, smashed:bool}`
- `BIOME_CHANGED`: `{biome, key:str}`
- `SCORE_CHANGED`: `{score:int}`
- `COMBO_CHANGED`: `{combo:float, active:bool}`
- `PLAYER_JUMP`/`PLAYER_SLIDE`/`PLAYER_LAND`/`PLAYER_STUMBLE`/`PLAYER_DIED`/`PLAYER_LANE_CHANGE`: `{}` (lane change has `{lane, dir}`)
- `TOAST`: `{text:str, color?:tuple, icon?:str}`
- `SCREEN_SHAKE`: `{magnitude:float}`
- `MISSION_COMPLETED`: `{mission}` ; `ACHIEVEMENT_UNLOCKED`: `{achievement}`

### `temple_run.config`
```python
Config: TITLE, WIDTH=1280, HEIGHT=720, FPS=60, HORIZON_RATIO=0.42, MAX_DT,
        SAVE_FILE="temple_run_save.json", SETTINGS_FILE="temple_run_settings.json"
Cam:    FOV, HEIGHT, DEPTH, DRAW_DISTANCE, FOG_DENSITY, ...
Track:  ROAD_WIDTH, SEGMENT_LENGTH, LANES=3, LANE_FRACTION; staticmethod lane_x(lane)
Physics: GRAVITY, JUMP_VELOCITY, SLIDE_DURATION, START_SPEED, MIN_SPEED, MAX_SPEED, ACCEL, ...
Gameplay: COIN_VALUE, GEM_VALUE, SCORE_PER_METER, METERS_PER_UNIT=1/100,
          NEAR_MISS_BONUS=15, COMBO_WINDOW=2.4, COMBO_STEP=0.1, COMBO_MAX=4.0
Palette: WHITE, BLACK, GREY, LIGHT_GREY, DARK_GREY, GOLD, GOLD_DARK, GEM, GEM_DARK,
         PLAYER, PLAYER_DARK, SKIN, DANGER, SUCCESS, WARNING, INFO,
         UI_PANEL, UI_PANEL_LIGHT, UI_ACCENT, UI_TEXT, UI_TEXT_DIM, FOG   # all (r,g,b)
Keys:   DEFAULT_BINDINGS: dict[str, tuple[str,...]]  # action -> key name strings
lerp_color(a,b,t)->rgb ; shade_color(c,factor)->rgb   # module-level helpers
Color = tuple[int,int,int]
```
Distance in metres = `world_units * Gameplay.METERS_PER_UNIT`.

### `temple_run.mathutils`
```python
lerp, clamp, clamp01, inv_lerp, remap, approach, damp(cur,target,smoothing,dt),
sign, wrap, ping_pong, smoothstep,
ease_in_quad, ease_out_quad, ease_in_out_quad, ease_in_cubic, ease_out_cubic,
ease_in_out_cubic, ease_out_back, ease_out_elastic, ease_out_bounce
class Vec2: x,y, add/sub/scale/length/normalized/dot/rotate
class RNG:  random(), range(lo,hi), int_range(lo,hi), chance(p), choice(seq),
            choices(seq,weights,k), shuffle, sign(), weighted_key(dict), reseed(seed)
project(...) -> Projected(x,y,w,scale)   # engine use; you likely won't need it
```
`damp`'s `smoothing` is "fraction of the gap remaining after one second" (small = fast).

### `temple_run.entities.powerup_types`
```python
@dataclass(frozen=True)
class PowerupType:
    key:str, name:str, color:(r,g,b), symbol:str, duration:float,
    invincible:bool=False, magnet:bool=False, speed_mult:float=1.0,
    score_mult:int=1, coin_mult:int=1, description:str=""
POWERUPS: dict[str, PowerupType]     # keys: "magnet","shield","boost","x2"
POWERUP_KEYS: tuple[str,...]
get_powerup(key) -> PowerupType
```

### `temple_run.entities.spawner`
```python
@dataclass
class SpawnKnobs:
    feature_gap:float=2600.0, obstacle_prob:float=0.55, coin_prob:float=0.30,
    gem_prob:float=0.04, powerup_prob:float=0.05, double_prob:float=0.18,
    moving_prob:float=0.08, coin_run_len:int=6
```
(Difficulty module: import and return this.)

### `temple_run.entities.player` (read-only attributes you may query)
```python
player.speed:float          # forward speed (world u/s); difficulty sets this
player.boost_multiplier:float
player.effective_speed:float
player.distance:float        # total world units travelled
player.state: PlayerState    # enum: IDLE,RUNNING,JUMPING,SLIDING,STUMBLING,DEAD
player.alive:bool
```

## The shared HUD/game snapshot (dict)

`game` assembles this each frame and hands it to the HUD. Producers must populate
their part; consumers must read defensively (`snapshot.get(...)`).
```python
snapshot = {
  "score": int, "coins": int, "gems": int, "distance_m": int,
  "combo": float, "combo_active": bool,
  "speed_kmh": int, "high_score": int, "level": int,
  "biome_name": str,
  "powerups": [ {"key":str,"name":str,"color":(r,g,b),"symbol":str,
                 "remaining":float,"duration":float}, ... ],
  "state": str,
}
```

---

# Per-module specifications

Only implement the module named in your task. Each spec lists the file path, the
public class(es), and required methods. You may add private helpers freely.

## MODULE audio  — file `temple_run/audio/engine.py`
`class AudioEngine`:
- `__init__(self, event_bus, get_sfx_volume=None, get_music_volume=None)` — try to
  `pygame.mixer.init(44100, -16, 2, 512)`; set `self.enabled`. Generate a library
  of procedural SFX (sine/square/noise with an ADSR-ish decay envelope): at least
  `coin, gem, jump, land, slide, hit, powerup, button, combo, milestone,
  lanechange, whoosh`. Subscribe to the relevant events to auto-play SFX
  (COIN_COLLECTED->coin, GEM_COLLECTED->gem, PLAYER_JUMP->jump, PLAYER_LAND->land,
  PLAYER_SLIDE->slide, OBSTACLE_HIT->hit, POWERUP_COLLECTED->powerup,
  UI_BUTTON->button, MILESTONE_REACHED->milestone, PLAYER_LANE_CHANGE->lanechange).
- `play(name:str)` — play a one-shot SFX by name (respect sfx volume; no-op if
  disabled/unknown).
- A tiny **chiptune music sequencer**: build looping background tracks
  procedurally from note tables (a couple of moods, e.g. "menu","run","danger").
  `play_music(name)`, `stop_music()`, `update(dt)` advances the sequencer and
  keeps the loop going. Use a `pygame.mixer.Channel` for music.
- `set_sfx_volume(v)`, `set_music_volume(v)`; helpers to (re)generate a note.
- Provide `make_tone(freq, duration, volume, wave="sine", sweep=None, noise=False)`
  returning a `pygame.mixer.Sound`. Correct 16-bit stereo buffer construction.
- Must degrade silently if the mixer can't init.
Target ~320 lines.

## MODULE particles — file `temple_run/fx/particles.py`
`@dataclass class Particle` (pooled) and `class ParticleSystem`:
- Screen-space 2D particles with an object pool (use `temple_run.core.pool.Pool`).
- `emit(kind, x, y, count=1, **kw)` plus convenience presets:
  `burst_coins(x,y)`, `burst_hit(x,y)`, `dust(x,y)`, `smoke(x,y)`,
  `sparkle(x,y,color)`, `confetti(x,y)`, `ring(x,y,color)`, `powerup_burst(x,y,color)`.
- Kinds differ in gravity, drag, fade, size curve, colour, glow, shape
  (circle/square/streak/ring). Support additive-ish glow via SRCALPHA where cheap.
- `update(dt)` integrates & recycles dead particles; cap the live count (e.g. 800)
  and drop oldest if exceeded. `draw(surface)`. `clear()`.
- `count` property. Keep it fast (avoid per-particle surface alloc in hot path;
  reuse small glow surfaces or draw primitives).
Target ~320 lines.

## MODULE scoring — file `temple_run/systems/scoring.py`
`class ScoreSystem`:
- `__init__(self, event_bus)`. Track `score:int, coins:int, gems:int,
  distance_m:int, combo:float, combo_active:bool`.
- Subscribe: COIN_COLLECTED (+value*combo, coins+=1), GEM_COLLECTED (+value*combo,
  gems+=1), NEAR_MISS (+Gameplay.NEAR_MISS_BONUS, bumps combo).
- Combo: each chained pickup/near-miss within `Gameplay.COMBO_WINDOW` seconds adds
  `Gameplay.COMBO_STEP` up to `Gameplay.COMBO_MAX` (start at 1.0). Combo decays to
  1.0 after the window with no pickups; publish COMBO_CHANGED on change.
- `set_score_multiplier_source(fn)` — a `()->int` giving the powerup score
  multiplier (default 1). Apply it to all point gains.
- `update(dt, distance_units)` — award distance points (`SCORE_PER_METER` per
  metre), tick the combo timer, milestone every 500 m -> publish
  MILESTONE_REACHED `{meters}`. Publish SCORE_CHANGED when score changes.
- `reset()`. `snapshot()->dict` returning the score-related snapshot keys
  (`score,coins,gems,distance_m,combo,combo_active`).
Target ~240 lines.

## MODULE save — file `temple_run/systems/save.py`
`class SaveManager`:
- `__init__(self, path=Config.SAVE_FILE)`; `self.data:dict` with sane defaults:
  `high_score, total_coins, total_gems, total_distance_m, total_runs, best_distance_m,
   coins_balance, unlocked:{}, upgrades:{}, achievements:{}, missions:{}, stats:{}, settings:{}`.
- `load()` (tolerant of missing/corrupt file), `save()` (atomic: write temp then
  replace), `reset()`.
- Helpers: `get(key,default)`, `set(key,value)`, `add(key,amount)`,
  `get_section(name)->dict` (auto-create), `record_run(score, coins, gems,
  distance_m)` updating totals/highs. Subscribe optionally to GAME_OVER to persist
  a run summary if an event_bus is passed (`__init__(self, path=..., event_bus=None)`).
- Never throw on I/O errors; log to stdout and continue.
Target ~220 lines.

## MODULE settings — file `temple_run/systems/settings.py`
`class Settings`:
- `__init__(self, path=Config.SETTINGS_FILE)`; fields: `sfx_volume:float=0.7`,
  `music_volume:float=0.5`, `particles:bool=True`, `screen_shake:bool=True`,
  `show_fps:bool=False`, `high_contrast:bool=False`,
  `bindings:dict[str,list[str]]` initialised from `Keys.DEFAULT_BINDINGS`.
- `load()`, `save()` (JSON, tolerant), `reset_defaults()`.
- `key_names_for(action)->list[str]`, `rebind(action, key_name)`,
  `resolve_key(pygame_key_int)->str|None` mapping a pygame key constant to an
  action (build a reverse map from bindings; use `pygame.key.name` and a
  name->const table). Provide `action_for_key(key_int)->str|None`.
- Getters/setters that clamp volumes to [0,1].
Target ~210 lines.

## MODULE input — file `temple_run/input/input_manager.py`
`class InputManager`:
- `__init__(self, settings=None)` — if `settings` given, use its bindings; else
  `Keys.DEFAULT_BINDINGS`. Build a map from pygame key constants to action names.
- `action_for(self, key_int)->str|None`. `rebuild()` after bindings change.
- Optional light input buffering: `press(action)` records a timestamp-less
  "just pressed" set cleared each frame via `end_frame()`; `is_pressed(action)`.
- Provide a `KEY_NAME_TO_CONST` table covering letters, digits, arrows, SPACE,
  RETURN, ESCAPE, SHIFT variants, etc., and `name_to_const(name)` /
  `const_to_name(const)` helpers (robust to case).
- Do not read pygame's event queue yourself; the game feeds you key ints.
Target ~230 lines.

## MODULE difficulty — file `temple_run/systems/difficulty.py`
`class DifficultyDirector`:
- `__init__(self)`; `reset()`. Import `SpawnKnobs` from
  `temple_run.entities.spawner`.
- `update(self, dt, player)->SpawnKnobs` — ramp a target speed from
  `Physics.START_SPEED` toward `Physics.MAX_SPEED` as a function of distance/time,
  set `player.speed` (ease it, don't snap), and return a `SpawnKnobs` whose
  `feature_gap` **scales with speed** so reaction time stays >= ~0.7s
  (`feature_gap = max(base, player.effective_speed * MIN_REACTION)`), and whose
  obstacle/coin/gem/powerup/double/moving probabilities intensify with level.
- `self.level:int` (rises with distance), `self.intensity:float in [0,1]`.
- `snapshot()->dict` -> `{"level":int}` merged by game.
- Keep it fair: never make `feature_gap` so small that consecutive rows are
  unreachable; cap probabilities sensibly.
Target ~200 lines.

## MODULE powerups — file `temple_run/systems/powerups.py`
`class PowerupManager`:
- `__init__(self, event_bus)`; subscribe POWERUP_COLLECTED (data `power`).
- Track active effects with remaining timers keyed by powerup key; picking up an
  already-active powerup refreshes its timer. On start publish POWERUP_STARTED
  `{power,type}`, on expiry POWERUP_ENDED `{power,type}`.
- `update(dt)` decays timers. Query methods used by collision/game/scoring:
  `is_invincible()->bool`, `magnet_active()->bool`, `speed_mult()->float`
  (product of active), `score_mult()->int`, `coin_mult()->int`.
- `active_list()->list[dict]` producing the snapshot `powerups` entries
  (`key,name,color,symbol,remaining,duration`). `reset()`.
Target ~200 lines.

## MODULE achievements — file `temple_run/systems/achievements.py`
`class Achievement` (id,name,description,icon,goal,check-metric) and
`class AchievementSystem`:
- `__init__(self, event_bus, save)`. Define >=12 achievements (first coin,
  1000 coins total, run 1000m, run 5000m, near-miss master, collect all powerup
  types in one run, combo x4, smash 10 obstacles with boost, survive 3 min,
  gem collector, etc.).
- Track progress via events; persist unlock state + counters in
  `save.get_section("achievements")`. On unlock publish ACHIEVEMENT_UNLOCKED
  `{achievement}` and a TOAST. `reset_run()` clears per-run counters.
- `snapshot()->list[dict]` for the achievements screen
  (`id,name,description,icon,unlocked,progress,goal`).
Target ~300 lines.

## MODULE missions — file `temple_run/systems/missions.py`
`class Mission` and `class MissionSystem`:
- `__init__(self, event_bus, save, rng=None)`. Maintain 3 active missions drawn
  from templates (collect N coins, run N metres in one run, use N powerups,
  N near-misses, reach biome X, score N in one run). Progress tracked via events;
  completing publishes MISSION_COMPLETED `{mission}` + TOAST + a coin reward added
  to `save` (`coins_balance`). Persist active missions + progress in
  `save.get_section("missions")`. When all complete, roll a fresh set.
- `reset_run()` resets per-run counters (missions that are "in one run" reset).
- `snapshot()->list[dict]` (`text,progress,goal,reward,done`).
Target ~280 lines.

## MODULE shop — file `temple_run/systems/shop.py`
`class ShopItem` and `class Shop`:
- `__init__(self, event_bus, save)`. Catalogue of purchasable upgrades stored in
  `save.get_section("upgrades")` and skins/characters in
  `save.get_section("unlocked")`. Upgrades are multi-level with rising prices:
  e.g. `magnet_duration`, `boost_duration`, `coin_value`, `head_start`,
  `revive` (one-shot), `score_multiplier`. Skins are one-time unlocks.
- Currency is `save.data["coins_balance"]`. `buy(item_id)->bool` (checks funds,
  increments level/unlocks, deducts coins, `save.save()`, publishes SHOP_PURCHASE
  / UPGRADE_PURCHASED + TOAST). `price(item_id)->int`, `level(item_id)->int`,
  `max_level(item_id)->int`, `is_unlocked(item_id)->bool`.
- Expose computed gameplay values the game reads: `head_start_units()->float`,
  `coin_value_bonus()->int`, `magnet_duration_bonus()->float`, etc.
- `catalog()->list[dict]` for the shop screen (`id,name,desc,price,level,max,kind,affordable`).
Target ~300 lines.

## MODULE widgets — file `temple_run/ui/widgets.py`
A small screen-space UI toolkit (pygame). Provide:
- `get_font(size, bold=False)` with an internal cache.
- `class Button(rect, text, action=None, ...)`: hover/press states, rounded panel,
  `handle_event(pygame_event)->bool` (returns True if clicked; may call action),
  `update(mouse_pos, mouse_down)`, `draw(surface)`. Nice hover animation.
- `class Label`, `class Panel`, `class ProgressBar(rect, value 0..1)`,
  `class Toast(text,color,icon,life)` and `class ToastManager` that subscribes to
  the TOAST event (its `__init__(self, event_bus=None)`), stacks toasts top-right,
  animates them in/out, `update(dt)`, `draw(surface)`.
- A `draw_text(surface, text, pos, size, color, center=False, bold=False)` helper
  and a `panel(surface, rect, color, radius, border)` helper.
- Consistent look using `Palette`. Everything must be safe to draw headless.
Target ~360 lines.

---

Remember: create only your assigned file, make it compile cleanly under
`py_compile`, and return the structured result.
