# Maintainer guide

A short field manual for working on Neon Bot Trials.

## The one invariant that matters

**Dynamic body ordering.** `SimEngine.registerDynamicBodies` defines the order:
chassis, then per part (in `design.parts` order): wheel body / leg upper /
leg lower / spring foot, then seesaws, then moving platforms.
`preview.ts#staticFrameFromDesign` and the replay codec both rely on this order.
If you add a part type with physics bodies, update **both** files or replays
and previews will render the wrong shapes at the wrong transforms.
`tests/replay.test.ts` and `tests/engine.test.ts` guard the basics.

## Units cheat-sheet (Matter.js)

| Quantity | Unit | Note |
| --- | --- | --- |
| position | px | y grows downward |
| body.velocity | px/tick | multiply by 60 for px/s |
| body.angularVelocity | rad/tick | multiply by 60 for rad/s |
| applyForce | mass × 0.001 × g-units | matches how Matter applies gravity |
| tick | 1000/60 ms | `TICK_MS` in engine.ts |

All human-readable constants in `engine.ts` are rad/s or rad/s² and converted
with `DT` at the point of use. If a motor feels 60× too strong, you forgot the
conversion.

## Where behavior lives

- Motor feel / gait / thrust: constants at the top of `src/lib/engine.ts`.
- Course difficulty: geometry in `src/lib/arenas.ts` (comments document the
  height-matching of ramps and seesaw pylons).
- Score weights: `src/lib/scoring.ts`.
- Tuning ranges the player can reach: `src/lib/parts.ts`.

## Balance workflow

`tests/balance.report.test.ts` runs every preset through every arena headlessly
and prints a matrix (`DONE/DNF`, time, progress, score). It asserts every arena
is completable by at least one preset. When you touch engine constants or arena
geometry, read that matrix before trusting your change. For deeper digging,
write a scratch test that logs `engine.getFrame()` fields over time — that is
how the walking gait and every arena stall in development were diagnosed.

## Rendering

`NeonRenderer` is stateless with respect to the simulation — it draws whatever
frame you hand it (live engine frame, decoded replay frame, or rest pose).
Visual-only state (particles, trails) lives inside the renderer; call
`renderer.reset()` whenever the subject changes. Keep `shadowBlur` usage paired
with a reset to 0 — it is the main perf lever.

## Persistence

Keys: `nbt:robots`, `nbt:runs`, `nbt:draft`, `nbt:replay:<runId>`. Every read
validates and repairs; corrupt entries are dropped silently. Caps:
24 robots, 100 runs, 10 replays (oldest replays pruned, with a quota-pressure
fallback that clears other replays and retries once). Tests inject the
in-memory store from `createMemoryStore()` — never touch `window.localStorage`
directly in library code; go through `storage.ts`.

## Visual QA

`qa/visual-qa.spec.ts` is behavioral, not pixel-diff: it mounts parts, runs a
full trial (Skyhopper at 4× finishes First Drive in seconds), opens the replay
it just saved, and asserts the `/qa` runtime self-check passes. Screenshots are
review artifacts, not assertions, so the suite doesn't flake on rendering
noise. If you add a screen, add: a render check, a canvas-paint check
(`canvasColorCount`), a screenshot, and add the route to the overflow test.

## Release checklist

```bash
npm run lint && npm run typecheck && npm test && npm run visual:qa
```

All four must pass. `qa/artifacts/REPORT.md` is the human-reviewable output.
