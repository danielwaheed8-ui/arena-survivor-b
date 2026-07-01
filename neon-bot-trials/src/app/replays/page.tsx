'use client';

import { useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useMemo, useState } from 'react';
import { ReplayViewer } from '@/components/ReplayViewer';
import { Badge, Button, Panel } from '@/components/ui';
import { ARENAS, getArenaById } from '@/lib/arenas';
import { formatScore } from '@/lib/scoring';
import { deleteRun, loadReplay, loadRuns } from '@/lib/storage';
import type { ReplayData, RunRecord } from '@/lib/types';

function ReplaysPageInner() {
  const params = useSearchParams();
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [arenaFilter, setArenaFilter] = useState<string>('all');
  const [selectedRunId, setSelectedRunId] = useState<string | null>(params.get('run'));
  const [replay, setReplay] = useState<ReplayData | null>(null);

  useEffect(() => {
    setRuns(loadRuns());
  }, []);

  useEffect(() => {
    if (!selectedRunId) {
      setReplay(null);
      return;
    }
    setReplay(loadReplay(selectedRunId));
  }, [selectedRunId]);

  const sorted = useMemo(() => {
    const filtered = arenaFilter === 'all' ? runs : runs.filter((r) => r.arenaId === arenaFilter);
    return [...filtered].sort((a, b) => b.score.total - a.score.total);
  }, [runs, arenaFilter]);

  const selectedRun = runs.find((r) => r.id === selectedRunId) ?? null;

  return (
    <div className="mx-auto max-w-[1500px] px-4 pb-12 pt-8 sm:px-6">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="hud-label text-neon-magenta">Mission Archive</p>
          <h1 className="neon-heading mt-1 text-2xl text-white">Runs & Replays</h1>
          <p className="mt-1 text-sm text-slate-400">
            Every completed trial is scored and archived. Recent runs keep full replay data.
          </p>
        </div>
        <select
          className="rounded-lg border border-white/15 bg-panel px-3 py-1.5 text-xs text-slate-200 outline-none focus:border-neon-cyan/50"
          value={arenaFilter}
          onChange={(e) => setArenaFilter(e.target.value)}
          data-testid="replay-arena-filter"
        >
          <option value="all">All arenas</option>
          {ARENAS.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </header>

      <div className="grid gap-4 xl:grid-cols-[420px_minmax(0,1fr)]">
        <Panel title={`Leaderboard · ${sorted.length} runs`} className="max-h-[70vh] overflow-hidden">
          {sorted.length === 0 ? (
            <div className="py-10 text-center">
              <p className="text-sm text-slate-500">No archived runs yet.</p>
              <p className="mt-1 text-xs text-slate-600">
                Complete a trial in the simulator and it will appear here automatically.
              </p>
            </div>
          ) : (
            <ul className="max-h-[58vh] space-y-2 overflow-y-auto pr-1" data-testid="run-list">
              {sorted.map((run, i) => {
                const arena = getArenaById(run.arenaId);
                const active = run.id === selectedRunId;
                return (
                  <li key={run.id}>
                    <button
                      onClick={() => setSelectedRunId(run.id)}
                      className={`w-full rounded-lg border p-3 text-left transition-all ${
                        active
                          ? 'border-neon-cyan/50 bg-neon-cyan/10 shadow-neon'
                          : 'border-white/[0.07] bg-white/[0.02] hover:border-white/20'
                      }`}
                      data-testid={`run-row-${i}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-2">
                          <span className="mono-value w-6 text-right text-xs text-slate-500">
                            {i + 1}.
                          </span>
                          <span className="text-sm font-semibold text-white">{run.robotName}</span>
                          <Badge tone={run.telemetry.completed ? 'lime' : 'rose'}>
                            {run.telemetry.completed ? run.score.grade : 'DNF'}
                          </Badge>
                        </span>
                        <span className="mono-value text-sm font-bold text-cyan-200">
                          {formatScore(run.score.total)}
                        </span>
                      </div>
                      <div className="mt-1.5 flex items-center justify-between pl-8">
                        <span className="text-[11px] text-slate-500">
                          {arena?.name ?? run.arenaId} · {run.telemetry.t.toFixed(1)}s ·{' '}
                          {new Date(run.date).toLocaleDateString()}
                        </span>
                        {run.hasReplay && (
                          <span className="text-[10px] uppercase tracking-wider text-neon-cyan/70">
                            ◍ replay
                          </span>
                        )}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>

        <Panel
          title={selectedRun ? `Replay · ${selectedRun.robotName} @ ${getArenaById(selectedRun.arenaId)?.name ?? ''}` : 'Replay Theater'}
          className="min-h-[480px]"
          action={
            selectedRun && (
              <Button
                variant="danger"
                size="sm"
                onClick={() => {
                  deleteRun(selectedRun.id);
                  setRuns(loadRuns());
                  setSelectedRunId(null);
                }}
                data-testid="delete-run"
              >
                Delete Run
              </Button>
            )
          }
        >
          {replay ? (
            <div className="h-[440px]">
              <ReplayViewer replay={replay} className="rounded-xl border border-white/[0.07]" />
            </div>
          ) : selectedRun ? (
            <div className="flex h-[440px] flex-col items-center justify-center text-center">
              <p className="text-sm text-slate-400">Replay data for this run is no longer stored.</p>
              <p className="mt-1 max-w-sm text-xs text-slate-600">
                Only the most recent runs keep full replay frames to stay inside browser storage
                limits. The score above remains on the leaderboard.
              </p>
            </div>
          ) : (
            <div className="flex h-[440px] flex-col items-center justify-center text-center">
              <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full border border-neon-cyan/40 bg-neon-cyan/10 text-xl text-neon-cyan shadow-neon">
                ◍
              </div>
              <p className="text-sm text-slate-400">Select a run to open its replay.</p>
              <p className="mt-1 text-xs text-slate-600">
                Scrub, slow down, and study exactly where your bot lost its balance.
              </p>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}

export default function ReplaysPage() {
  return (
    <Suspense fallback={<div className="p-10 text-center text-sm text-slate-500">Opening archive…</div>}>
      <ReplaysPageInner />
    </Suspense>
  );
}
