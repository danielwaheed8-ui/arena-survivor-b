'use client';

import { useEffect, useState } from 'react';
import { Badge, Panel } from '@/components/ui';
import { ARENAS, getArenaById, validateArena } from '@/lib/arenas';
import { SimEngine } from '@/lib/engine';
import { PART_CATALOG, PART_TYPES } from '@/lib/parts';
import { decodeFrame, encodeFrame } from '@/lib/replay';
import { PRESET_ROBOTS, validateDesign } from '@/lib/robots';
import { computeScore } from '@/lib/scoring';
import { createMemoryStore, loadRobots, saveRobot } from '@/lib/storage';

interface CheckResult {
  name: string;
  pass: boolean;
  detail: string;
}

/**
 * Runtime self-verification. Runs the same core systems the game uses —
 * including a real headless physics run — inside the browser and reports
 * PASS/FAIL. The Playwright visual QA suite asserts on this page.
 */
function runChecks(): CheckResult[] {
  const results: CheckResult[] = [];
  const push = (name: string, pass: boolean, detail: string) =>
    results.push({ name, pass, detail });

  // 1. Arena definitions
  const arenaErrors = ARENAS.flatMap((a) => validateArena(a).errors.map((e) => `${a.id}: ${e}`));
  push(
    'Arena definitions valid',
    ARENAS.length >= 6 && arenaErrors.length === 0,
    arenaErrors.length === 0 ? `${ARENAS.length} arenas validated` : arenaErrors.join('; '),
  );

  // 2. Part catalog integrity
  const partErrors: string[] = [];
  for (const type of PART_TYPES) {
    for (const p of PART_CATALOG[type].params) {
      if (!(p.min < p.max)) partErrors.push(`${type}.${p.key}: min ≥ max`);
      if (p.default < p.min || p.default > p.max) partErrors.push(`${type}.${p.key}: default out of range`);
    }
  }
  push(
    'Part catalog integrity',
    partErrors.length === 0,
    partErrors.length === 0 ? `${PART_TYPES.length} part types checked` : partErrors.join('; '),
  );

  // 3. Preset designs
  const presetErrors = PRESET_ROBOTS.flatMap((r) => validateDesign(r).errors.map((e) => `${r.name}: ${e}`));
  push(
    'Preset robots valid',
    PRESET_ROBOTS.length >= 3 && presetErrors.length === 0,
    presetErrors.length === 0 ? `${PRESET_ROBOTS.length} presets validated` : presetErrors.join('; '),
  );

  // 4. Storage round-trip (isolated memory store)
  try {
    const store = createMemoryStore();
    const saved = saveRobot(PRESET_ROBOTS[0], store);
    const loaded = loadRobots(store);
    const ok = saved.ok && loaded.length === 1 && loaded[0].name === PRESET_ROBOTS[0].name;
    push('Save/load round-trip', ok, ok ? 'Design survived serialization' : 'Round-trip mismatch');
  } catch (e) {
    push('Save/load round-trip', false, String(e));
  }

  // 5. Live physics smoke test — 5 simulated seconds of the Volt Roller
  try {
    const arena = getArenaById('first-drive')!;
    const engine = new SimEngine(arena, PRESET_ROBOTS[0]);
    engine.start();
    for (let i = 0; i < 300 && !engine.isOver(); i++) engine.tick();
    const tel = engine.getTelemetry();
    const moved = tel.distance > 40;
    push(
      'Physics engine drives robots',
      moved && tel.t > 4,
      `Δx=${tel.distance.toFixed(0)}px in ${tel.t.toFixed(1)}s simulated`,
    );
  } catch (e) {
    push('Physics engine drives robots', false, String(e));
  }

  // 6. Scoring determinism
  try {
    const arena = ARENAS[0];
    const tel = {
      t: 20,
      distance: 2000,
      maxX: 2140,
      progress: 1,
      energyUsed: 50,
      batteryCapacity: 150,
      flips: 0,
      crashes: 1,
      avgTilt: 0.1,
      completed: true,
      failed: false,
    };
    const a = computeScore(tel, arena);
    const b = computeScore(tel, arena);
    push(
      'Scoring is deterministic',
      a.total === b.total && a.total > 1000,
      `score=${a.total}, grade=${a.grade}`,
    );
  } catch (e) {
    push('Scoring is deterministic', false, String(e));
  }

  // 7. Replay codec round-trip
  try {
    const bodies = [
      { x: 123.45, y: -67.8, angle: 1.5708 },
      { x: 0, y: 999.9, angle: -3.1 },
    ];
    const decoded = decodeFrame(encodeFrame(bodies, 0b101), 2);
    const ok =
      Math.abs(decoded.bodies[0].x - 123.45) < 0.06 &&
      Math.abs(decoded.bodies[1].angle - -3.1) < 0.001 &&
      decoded.firingMask === 5;
    push('Replay codec round-trip', ok, ok ? 'Quantization within tolerance' : 'Codec mismatch');
  } catch (e) {
    push('Replay codec round-trip', false, String(e));
  }

  // 8. Canvas support
  try {
    const canvas = document.createElement('canvas');
    canvas.width = 8;
    canvas.height = 8;
    const ctx = canvas.getContext('2d');
    push('Canvas 2D rendering available', ctx !== null, ctx ? '2D context acquired' : 'No 2D context');
  } catch (e) {
    push('Canvas 2D rendering available', false, String(e));
  }

  return results;
}

export default function QAPage() {
  const [checks, setChecks] = useState<CheckResult[] | null>(null);

  useEffect(() => {
    // Defer a frame so the page shell paints before physics runs.
    const id = requestAnimationFrame(() => setChecks(runChecks()));
    return () => cancelAnimationFrame(id);
  }, []);

  const passed = checks?.filter((c) => c.pass).length ?? 0;
  const total = checks?.length ?? 0;
  const allPass = checks !== null && passed === total;

  return (
    <div className="mx-auto max-w-3xl px-4 pb-16 pt-8 sm:px-6">
      <header className="mb-6">
        <p className="hud-label text-neon-magenta">Diagnostics</p>
        <h1 className="neon-heading mt-1 text-2xl text-white">System Self-Check</h1>
        <p className="mt-2 text-sm text-slate-400">
          Runs the core game systems — arena data, part catalog, storage, the physics engine, the
          scoring model and the replay codec — live in this browser.
        </p>
      </header>

      <Panel
        title="Check Results"
        action={
          checks === null ? (
            <Badge tone="amber">Running…</Badge>
          ) : (
            <span data-qa-status={allPass ? 'pass' : 'fail'}>
              <Badge tone={allPass ? 'lime' : 'rose'}>
                {passed}/{total} passed
              </Badge>
            </span>
          )
        }
      >
        {checks === null ? (
          <p className="py-8 text-center text-sm text-slate-500">Executing diagnostics…</p>
        ) : (
          <ul className="divide-y divide-white/[0.06]" data-testid="qa-results">
            {checks.map((c) => (
              <li key={c.name} className="flex items-start justify-between gap-4 py-3">
                <div>
                  <p className="text-sm font-medium text-slate-200">{c.name}</p>
                  <p className="mono-value mt-0.5 text-[11px] text-slate-500">{c.detail}</p>
                </div>
                <Badge tone={c.pass ? 'lime' : 'rose'}>{c.pass ? 'PASS' : 'FAIL'}</Badge>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <p className="mt-4 text-[11px] leading-relaxed text-slate-600">
        The full visual QA suite (<span className="mono-value">npm run visual:qa</span>) drives
        every screen with Playwright, captures desktop/tablet/mobile screenshots and asserts on
        this page&apos;s results.
      </p>
    </div>
  );
}
