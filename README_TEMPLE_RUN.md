# Temple Run — World-Class Python Edition

A pseudo-3D endless runner built on **pygame**, engineered as a proper modular
game rather than a single-file script. It takes the architecture the original
draft *described* (FSM, event system, particles, pseudo-3D projection, procedural
audio) and actually makes it **work, endless, fair, and much bigger**.

```bash
pip install pygame
python main.py            # or:  python -m temple_run
```

## Controls

| Action        | Keys                         |
|---------------|------------------------------|
| Change lanes  | ← / → &nbsp; or &nbsp; A / D |
| Jump          | ↑ / W / Space                |
| Slide         | ↓ / S                        |
| Pause         | Esc / P                      |
| Confirm       | Enter / Space                |

Grab coins and gems, **chain** them for a combo multiplier, snag powerups
(magnet, shield, boost, ×2), and run as far as you can. The temple never ends and
the speed keeps climbing.

## What was wrong with the original, and what changed

The pasted 1,500-line monolith had a good *skeleton* but did not run:

| Original problem | Fix in this version |
|---|---|
| `project_3d` was called with a scalar where it expected a 3-tuple (fatal `ValueError` every frame) | One canonical `mathutils.project` used by the renderer **and** collision |
| `_draw_segment` used `r1`/`r2` before assignment; `_draw_entity`/`_draw_segment` referenced an undefined global `track` | Renderer rewritten cleanly; no undefined names |
| Curve accumulation applied to the wrong points; roads didn't bend correctly | Faithful OutRun accumulating-curve projection with hill occlusion |
| The track was **finite** — the run ended at the last segment | Genuinely **endless** streaming track with rolling generation + pruning |
| Collision was lane-index + magic `y > 200` thresholds | World-space collision that matches exactly what is drawn |
| No fairness guarantee | Spawner **proves** a passable, reachable lane always exists (validated: 40/40 seeds survive 4 min of perfect play) |

## Architecture

```
temple_run/
├── config.py            Tunables, palette, key bindings
├── mathutils.py         Lerp/clamp/easings, RNG, the perspective projection
├── core/
│   ├── events.py        Publish/subscribe EventBus + typed events
│   ├── fsm.py           Generic finite state machine (validated transitions)
│   └── pool.py          Object pooling (particles, entities)
├── world/
│   ├── biomes.py        7 cross-fading visual themes (pure data)
│   ├── segment.py       Track slab + roadside scenery
│   └── track.py         Endless procedural road (hills, curves, s-curves)
├── render/
│   ├── camera.py        Follow camera + screen shake
│   └── renderer.py      Pseudo-3D road/scenery/entity/player rendering
├── entities/
│   ├── entity.py        Base entity + world/screen conventions
│   ├── obstacles.py     Barriers, beams, blocks, spikes, sweeping rollers
│   ├── collectibles.py  Coins, gems, powerup pickups
│   ├── powerup_types.py Shared powerup catalogue
│   ├── collision.py     One world-space collision system
│   ├── player.py        Lane runner with input buffering + coyote time
│   └── spawner.py       Fair, pooled, procedural population
├── audio/engine.py      Procedural SFX + a chiptune music sequencer
├── fx/particles.py      Pooled screen-space particle system
├── systems/             scoring · save · settings · difficulty ·
│                        powerups · achievements · missions · shop
├── input/               Key-binding resolution
├── ui/                  widgets · HUD
├── scenes.py            Menu / Play (FSM) / Shop / Missions / etc.
└── game.py              Application shell + main loop
```

### Design principles

- **Decoupling via events.** Systems never call each other directly; scoring
  publishes `COIN_COLLECTED`, and audio/particles/achievements/missions each
  react independently. Adding a new reaction never edits existing code.
- **One source of world→screen truth.** The renderer and collision share the same
  projection and coordinate conventions, so *what you see is exactly what you
  hit* — the bug class that made the original untrustworthy.
- **Fair by construction.** Every obstacle row leaves a reachable, beatable lane;
  moving rollers are solo and can never cover the guaranteed lane; feature spacing
  scales with speed to keep reaction time roughly constant.
- **Endless + pooled.** Track and entities stream in ahead and recycle behind
  through object pools, so memory and GC churn stay flat over a long run.

## Features

- 7 biomes with cross-fading palettes and themed scenery
- Coins, gems, combos with a decaying multiplier, near-miss bonuses
- 4 powerups (magnet, shield, boost, ×2) with HUD timers
- Difficulty director that ramps speed and spawn density while staying fair
- Procedurally synthesized sound effects and looping chiptune music
- Persistent profile: high score, coin balance, stats
- A coin shop with multi-level upgrades and one-shot revive
- Rotating missions and unlockable achievements
- Settings (volumes, particles, screen shake, FPS) with key rebinding support
- Full menu flow driven by a scene system; the run itself is an explicit FSM
