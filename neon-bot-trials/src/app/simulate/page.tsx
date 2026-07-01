'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { SimulationStage, type FrameSample, type StageHandle } from '@/components/SimulationStage';
import { Badge, Button, Meter, Panel, Stat } from '@/components/ui';
import { ARENAS, getArenaById } from '@/lib/arenas';
import type { RunEndResult } from '@/lib/engine';
import { PART_CATALOG } from '@/lib/parts';
import { REPLAY_SAMPLE_HZ } from '@/lib/replay';
import { freshId, getPresetById, PRESET_ROBOTS } from '@/lib/robots';
import { computeScore, formatScore } from '@/lib/scoring';
import { loadRobots, saveReplay, saveRun } from '@/lib/storage';
import { useGameStore } from '@/store/gameStore';
import type { RobotDesign, RunRecord, ScoreBreakdown, SimStatus, Telemetry } from '@/lib/types';

const SPEEDS = [0.5, 1, 2, 4];

function SimulatePageInner() {
  const router = useRouter();
  const params = useSearchParams();
  const hydrate = useGameStore((s) => s.hydrate);
  const hydrated = useGameStore((s) => s.hydrated);
  const draft = useGameStore((s) => s.design);
  const storeArenaId = useGameStore((s) => s.arenaId);
  const setStoreArenaId = useGameStore((s) => s.setArenaId);
  const speed = useGameStore((s) => s.speed);
  const setSpeed = useGameStore((s) => s.setSpeed);
  const cinematic = useGameStore((s) => s.cinematic);
  const setCinematic = useGameStore((s) => s.setCinematic);

  useEffect(() => hydrate(), [hydrate]);
  // Leaving the page must always restore chrome.
  useEffect(() => () => setCinematic(false), [setCinematic]);

  const arenaParam = params.get('arena');
  const arena = useMemo(
    () => getArenaById(arenaParam ?? storeArenaId) ?? ARENAS[0],
    [arenaParam, storeArenaId],
  );
  useEffect(() => {
    if (arena.id !== storeArenaId) setStoreArenaId(arena.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [arena.id]);

  const [savedRobots, setSavedRobots] = useState<RobotDesign[]>([]);
  useEffect(() => setSavedRobots(loadRobots()), []);

  const [robotKey, setRobotKey] = useState<string>('draft');
  const design = useMemo(() => {
    if (robotKey === 'draft') return draft;
    return (
      getPresetById(robotKey) ?? savedRobots.find((r) => r.id === robotKey) ?? draft
    );
  }, [robotKey, draft, savedRobots]);

  const stageRef = useRef<StageHandle>(null);
  const [sample, setSample] = useState<FrameSample | null>(null);
  const [results, setResults] = useState<{
    telemetry: Telemetry;
    score: ScoreBreakdown;
    runId: string;
    replaySaved: boolean;
  } | null>(null);

  const status: SimStatus = sample?.status ?? 'ready';

  const handleRunEnd = useCallback(
    (result: RunEndResult, engine: { design: RobotDesign }) => {
      const score = computeScore(result.telemetry, arena);
      const runId = freshId('run');
      const replay = {
        version: 1 as const,
        runId,
        arenaId: arena.id,
        robotName: engine.design.name,
        design: engine.design,
        bodies: result.replayBodies,
        frames: result.replayFrames,
        sampleHz: REPLAY_SAMPLE_HZ,
        duration: result.telemetry.t,
      };
      const replaySaved = saveReplay(replay);
      const record: RunRecord = {
        id: runId,
        arenaId: arena.id,
        robotName: engine.design.name,
        robotId: engine.design.id,
        date: Date.now(),
        telemetry: result.telemetry,
        score,
        hasReplay: replaySaved,
      };
      saveRun(record);
      setResults({ telemetry: result.telemetry, score, runId, replaySaved });
    },
    [arena],
  );

  const handleRestart = useCallback(() => {
    setResults(null);
    stageRef.current?.reset();
    stageRef.current?.start();
  }, []);

  const togglePlay = useCallback(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const s = stage.getStatus();
    if (s === 'running') stage.pause();
    else if (s === 'paused') stage.resume();
    else if (s === 'ready') stage.start();
    else handleRestart();
  }, [handleRestart]);

  // Rebuild the stage cleanly when arena/robot changes mid-session.
  useEffect(() => {
    setResults(null);
  }, [arena.id, design.id]);

  if (!hydrated) {
    return <div className="p-10 text-center text-sm text-slate-500">Priming simulation…</div>;
  }

  const tel = sample?.telemetry ?? null;
  const movableParts = design.parts.filter((p) => p.type !== 'glow' && p.type !== 'sensor');

  return (
    <div className={`mx-auto ${cinematic ? 'max-w-none px-0' : 'max-w-[1500px] px-4 sm:px-6'} pb-10 pt-4`}>
      {!cinematic && (
        <header className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="hud-label text-neon-magenta">
              Trial {String(ARENAS.findIndex((a) => a.id === arena.id) + 1).padStart(2, '0')} ·{' '}
              {arena.tagline}
            </p>
            <h1 className="neon-heading mt-0.5 text-xl text-white">{arena.name}</h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              className="rounded-lg border border-white/15 bg-panel px-3 py-1.5 text-xs text-slate-200 outline-none focus:border-neon-cyan/50"
              value={arena.id}
              onChange={(e) => {
                router.replace(`/simulate?arena=${e.target.value}`);
              }}
              data-testid="arena-select"
            >
              {ARENAS.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            <select
              className="max-w-[180px] rounded-lg border border-white/15 bg-panel px-3 py-1.5 text-xs text-slate-200 outline-none focus:border-neon-cyan/50"
              value={robotKey}
              onChange={(e) => setRobotKey(e.target.value)}
              data-testid="robot-select"
            >
              <option value="draft">Workshop Draft · {draft.name}</option>
              <optgroup label="Presets">
                {PRESET_ROBOTS.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </optgroup>
              {savedRobots.length > 0 && (
                <optgroup label="Garage">
                  {savedRobots.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </div>
        </header>
      )}

      <div className={`grid gap-4 ${cinematic ? '' : 'xl:grid-cols-[minmax(0,1fr)_280px]'}`}>
        <div className="relative">
          <SimulationStage
            key={`${arena.id}:${design.id}`}
            ref={stageRef}
            arena={arena}
            design={design}
            speed={speed}
            cinematic={cinematic}
            onSample={setSample}
            onRunEnd={handleRunEnd}
            className={`w-full rounded-2xl border border-white/10 ${
              cinematic
                ? 'h-[calc(100vh-3.5rem)] rounded-none border-0'
                : 'h-[440px] sm:h-[calc(100vh-240px)] sm:min-h-[480px]'
            }`}
          />

          {/* HUD overlay */}
          <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between p-4">
            <div className="glass-panel px-3 py-2">
              <div className="flex items-center gap-4">
                <Stat label="Time" value={tel ? tel.t.toFixed(1) : '0.0'} unit="s" />
                <Stat label="Dist" value={tel ? Math.max(0, tel.distance).toFixed(0) : '0'} unit="px" />
                <div className="w-28">
                  <span className="hud-label">Battery</span>
                  <Meter value={sample?.batteryFrac ?? 1} className="mt-1.5" />
                </div>
              </div>
            </div>
            <div className="flex flex-col items-end gap-2">
              <Badge
                tone={
                  status === 'running'
                    ? 'lime'
                    : status === 'finished'
                      ? 'cyan'
                      : status === 'failed'
                        ? 'rose'
                        : 'amber'
                }
              >
                {status === 'ready' ? 'Standby' : status}
              </Badge>
              {sample?.windActive && <Badge tone="cyan">⚠ Wind Zone</Badge>}
            </div>
          </div>

          {/* Progress bar */}
          <div className="pointer-events-none absolute inset-x-4 bottom-16">
            <div className="h-1 overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full bg-gradient-to-r from-neon-cyan to-emerald-400 transition-[width] duration-200"
                style={{ width: `${(tel?.progress ?? 0) * 100}%` }}
              />
            </div>
          </div>

          {/* Control bar */}
          <div className="absolute inset-x-0 bottom-0 flex items-center justify-center gap-2 p-3">
            <div className="glass-panel pointer-events-auto flex flex-wrap items-center justify-center gap-2 px-3 py-2">
              <Button size="sm" onClick={togglePlay} data-testid="play-pause" className="min-w-[92px]">
                {status === 'running' ? '❚❚ Pause' : status === 'paused' ? '▶ Resume' : status === 'ready' ? '▶ Launch' : '↻ Rerun'}
              </Button>
              <Button size="sm" variant="ghost" onClick={handleRestart} data-testid="reset-run">
                ↺ Reset
              </Button>
              <div className="mx-1 h-5 w-px bg-white/10" />
              {SPEEDS.map((s) => (
                <button
                  key={s}
                  onClick={() => setSpeed(s)}
                  data-testid={`speed-${s}`}
                  className={`rounded-md px-2 py-1 text-[11px] font-bold ${
                    speed === s
                      ? 'bg-neon-cyan/25 text-cyan-100 shadow-neon'
                      : 'text-slate-400 hover:bg-white/[0.07] hover:text-white'
                  }`}
                >
                  {s}×
                </button>
              ))}
              <div className="mx-1 h-5 w-px bg-white/10" />
              <Button
                size="sm"
                variant={cinematic ? 'accent' : 'ghost'}
                onClick={() => setCinematic(!cinematic)}
                data-testid="cinematic-toggle"
              >
                {cinematic ? '✕ Exit Cinematic' : '⌘ Cinematic'}
              </Button>
            </div>
          </div>
        </div>

        {/* Live telemetry sidebar */}
        {!cinematic && (
          <div className="space-y-4">
            <Panel title="Motor Telemetry">
              {movableParts.length === 0 ? (
                <p className="text-xs text-slate-500">
                  This frame has no actuators. Add wheels, legs, springs or thrusters in the
                  builder.
                </p>
              ) : (
                <ul className="space-y-2.5" data-testid="motor-telemetry">
                  {movableParts.map((p, i) => (
                    <li key={p.id}>
                      <div className="mb-1 flex items-center justify-between">
                        <span className="text-[11px] font-medium text-slate-300">
                          <span className="mr-1.5 text-neon-cyan">{PART_CATALOG[p.type].icon}</span>
                          {PART_CATALOG[p.type].label} {i + 1}
                        </span>
                        <span className="mono-value text-[10px] text-slate-500">
                          {Math.round((sample?.partActivity[p.id] ?? 0) * 100)}%
                        </span>
                      </div>
                      <Meter value={sample?.partActivity[p.id] ?? 0} />
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel title="Run Telemetry">
              <div className="grid grid-cols-2 gap-3">
                <Stat label="Progress" value={`${Math.round((tel?.progress ?? 0) * 100)}%`} tone="good" />
                <Stat label="Max X" value={tel ? tel.maxX.toFixed(0) : '—'} />
                <Stat label="Flips" value={tel?.flips ?? 0} tone={tel && tel.flips > 0 ? 'warn' : 'default'} />
                <Stat label="Impacts" value={tel?.crashes ?? 0} tone={tel && tel.crashes > 2 ? 'bad' : 'default'} />
                <Stat label="Tilt Avg" value={tel ? `${((tel.avgTilt * 180) / Math.PI).toFixed(0)}°` : '—'} />
                <Stat
                  label="Energy"
                  value={tel ? tel.energyUsed.toFixed(0) : '0'}
                  unit={`/${tel?.batteryCapacity ?? '—'}`}
                />
              </div>
            </Panel>

            <Panel title="Objective">
              <p className="text-xs leading-relaxed text-slate-400">{arena.objective}</p>
              <p className="mt-2 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[11px] leading-snug text-slate-500">
                <span className="text-neon-cyan/70">HINT </span>
                {arena.hint}
              </p>
            </Panel>
          </div>
        )}
      </div>

      {/* Results modal */}
      {results && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="glass-panel animate-fade-up w-full max-w-md p-6" data-testid="results-modal">
            <div className="flex items-start justify-between">
              <div>
                <p className="hud-label text-neon-magenta">
                  {results.telemetry.completed ? 'Trial Complete' : 'Trial Failed'}
                </p>
                <h2 className="neon-heading mt-1 text-2xl text-white">
                  {results.telemetry.completed ? 'CERTIFIED' : (results.telemetry.failReason ?? 'Run over')}
                </h2>
              </div>
              <div
                className={`flex h-14 w-14 items-center justify-center rounded-xl border text-3xl font-black ${
                  results.telemetry.completed
                    ? 'border-emerald-400/50 bg-emerald-400/10 text-emerald-300'
                    : 'border-amber-400/50 bg-amber-400/10 text-amber-300'
                }`}
                data-testid="grade"
              >
                {results.score.grade}
              </div>
            </div>

            <div className="mono-value mt-4 text-center text-4xl font-bold text-cyan-200" data-testid="final-score">
              {formatScore(results.score.total)}
            </div>
            <p className="mt-1 text-center text-[11px] uppercase tracking-widest text-slate-500">
              Final Score · saved to leaderboard
            </p>

            <ul className="mt-4 space-y-1.5 border-t border-white/[0.07] pt-4 text-xs">
              {[
                ['Course completion', results.score.completionPoints],
                ['Time bonus', results.score.timeBonus],
                ['Stability bonus', results.score.stabilityBonus],
                ['Energy efficiency', results.score.energyBonus],
                ['Flip penalty', -results.score.flipPenalty],
                ['Impact penalty', -results.score.crashPenalty],
              ].map(([label, v]) => (
                <li key={label as string} className="flex justify-between">
                  <span className="text-slate-400">{label}</span>
                  <span className={`mono-value ${(v as number) < 0 ? 'text-rose-300' : 'text-slate-200'}`}>
                    {(v as number) >= 0 ? '+' : ''}
                    {formatScore(v as number)}
                  </span>
                </li>
              ))}
            </ul>

            <div className="mt-5 grid grid-cols-2 gap-2">
              <Button onClick={handleRestart} data-testid="retry-run">
                ↻ Run Again
              </Button>
              <Button
                variant="accent"
                disabled={!results.replaySaved}
                onClick={() => router.push(`/replays?run=${results.runId}`)}
                data-testid="watch-replay"
              >
                ◍ Watch Replay
              </Button>
              <Button variant="ghost" onClick={() => router.push('/arenas')}>
                Change Arena
              </Button>
              <Button variant="ghost" onClick={() => router.push('/builder')}>
                Tune in Builder
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function SimulatePage() {
  return (
    <Suspense fallback={<div className="p-10 text-center text-sm text-slate-500">Loading arena…</div>}>
      <SimulatePageInner />
    </Suspense>
  );
}
