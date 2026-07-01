import { describe, expect, it } from 'vitest';
import { ARENAS } from '@/lib/arenas';
import { SimEngine } from '@/lib/engine';
import { PRESET_ROBOTS } from '@/lib/robots';
import { computeScore } from '@/lib/scoring';

/**
 * Balance sweep: runs every preset through every arena headlessly and prints
 * a matrix. Asserts the game is *winnable*: at least one preset completes each
 * of the first two arenas, and every arena is survivable past 25% progress.
 */
describe('gameplay balance sweep', () => {
  it('presets can actually play the campaign', () => {
    const completions = new Map<string, string[]>();
    const bestProgress = new Map<string, number>();
    const lines: string[] = [];

    for (const arena of ARENAS) {
      for (const preset of PRESET_ROBOTS) {
        const engine = new SimEngine(arena, preset);
        engine.start();
        const maxTicks = Math.min(arena.timeLimit, 120) * 60;
        for (let i = 0; i < maxTicks && !engine.isOver(); i++) engine.tick();
        const tel = engine.getTelemetry();
        const score = computeScore(tel, arena);
        lines.push(
          `${arena.id.padEnd(16)} ${preset.name.padEnd(14)} ` +
            `${tel.completed ? 'DONE' : 'DNF '} t=${tel.t.toFixed(1).padStart(6)}s ` +
            `prog=${(tel.progress * 100).toFixed(0).padStart(3)}% score=${String(score.total).padStart(5)} ` +
            `flips=${tel.flips} ${tel.failReason ?? ''}`,
        );
        if (tel.completed) {
          completions.set(arena.id, [...(completions.get(arena.id) ?? []), preset.name]);
        }
        bestProgress.set(arena.id, Math.max(bestProgress.get(arena.id) ?? 0, tel.progress));
      }
    }

    // eslint-disable-next-line no-console
    console.log('\n' + lines.join('\n'));

    // Every arena in the campaign must be completable by at least one
    // shipped preset — the game is winnable end to end.
    for (const arena of ARENAS) {
      expect(
        completions.get(arena.id)?.length ?? 0,
        `${arena.id} completable by a preset (best progress ${((bestProgress.get(arena.id) ?? 0) * 100).toFixed(0)}%)`,
      ).toBeGreaterThanOrEqual(1);
    }
  }, 120000);
});
