'use client';

import { useEffect, useState } from 'react';
import { ArenaPreview } from '@/components/ArenaPreview';
import { Badge, DifficultyDots, LinkButton } from '@/components/ui';
import { ARENAS } from '@/lib/arenas';
import { formatScore } from '@/lib/scoring';
import { bestRuns } from '@/lib/storage';
import type { RunRecord } from '@/lib/types';

export default function ArenasPage() {
  const [best, setBest] = useState<Map<string, RunRecord>>(new Map());

  useEffect(() => {
    setBest(bestRuns());
  }, []);

  return (
    <div className="mx-auto max-w-7xl px-4 pb-16 pt-8 sm:px-6">
      <header className="mb-8">
        <p className="hud-label text-neon-magenta">Course Catalog</p>
        <h1 className="neon-heading mt-1 text-2xl text-white">Select Your Trial</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-400">
          Six certification courses, each with its own hazards and scoring benchmark. Clear them
          all to fully certify your bot design.
        </p>
      </header>

      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {ARENAS.map((arena, i) => {
          const record = best.get(arena.id);
          return (
            <article
              key={arena.id}
              className="glass-panel group animate-fade-up overflow-hidden transition-all hover:border-neon-cyan/40 hover:shadow-neon"
              style={{ animationDelay: `${i * 70}ms` }}
              data-testid={`arena-card-${arena.id}`}
            >
              <ArenaPreview arena={arena} className="h-36 w-full border-b border-white/[0.07]" />
              <div className="p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="mono-value text-[10px] text-slate-500">
                      TRIAL {String(i + 1).padStart(2, '0')} · {arena.tagline}
                    </p>
                    <h2 className="mt-0.5 text-lg font-semibold text-white group-hover:text-cyan-200">
                      {arena.name}
                    </h2>
                  </div>
                  <DifficultyDots level={arena.difficulty} />
                </div>

                <p className="mt-2 min-h-[40px] text-xs leading-relaxed text-slate-400">
                  {arena.objective}
                </p>

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {arena.windZones.length > 0 && <Badge tone="cyan">Wind</Badge>}
                  {arena.gravityZones.length > 0 && <Badge tone="magenta">Low-G</Badge>}
                  {arena.movingPlatforms.length > 0 && <Badge tone="amber">Moving</Badge>}
                  {arena.seesaws.length > 0 && <Badge tone="rose">Unstable</Badge>}
                  <Badge tone="lime">{arena.timeLimit}s limit</Badge>
                </div>

                <div className="mt-4 flex items-center justify-between border-t border-white/[0.06] pt-3">
                  <div>
                    <p className="hud-label">Best Score</p>
                    <p className="mono-value text-sm text-cyan-200">
                      {record ? (
                        <>
                          {formatScore(record.score.total)}{' '}
                          <span className="text-slate-500">· {record.robotName}</span>
                        </>
                      ) : (
                        <span className="text-slate-600">No runs yet</span>
                      )}
                    </p>
                  </div>
                  <LinkButton href={`/simulate?arena=${arena.id}`} size="sm">
                    Deploy →
                  </LinkButton>
                </div>

                <p className="mt-3 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[11px] leading-snug text-slate-500">
                  <span className="text-neon-cyan/70">HINT </span>
                  {arena.hint}
                </p>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
