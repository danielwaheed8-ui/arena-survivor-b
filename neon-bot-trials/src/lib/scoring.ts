import type { ArenaDef, ScoreBreakdown, Telemetry } from './types';

/**
 * Deterministic scoring from run telemetry. Kept pure so it is unit-testable
 * and so the results modal can show an honest breakdown.
 */
export function computeScore(telemetry: Telemetry, arena: ArenaDef): ScoreBreakdown {
  const completionPoints = telemetry.completed
    ? 1000
    : Math.round(telemetry.progress * 600);

  const timeBonus = telemetry.completed
    ? Math.round(Math.max(0, 1 - telemetry.t / arena.timeLimit) * 500)
    : 0;

  // avgTilt of 0 rad = perfectly level the whole run; 0.8 rad+ = chaos.
  const stabilityBonus = Math.round(Math.max(0, 1 - telemetry.avgTilt / 0.8) * 200);

  const energyFrac =
    telemetry.batteryCapacity > 0
      ? Math.min(1, telemetry.energyUsed / telemetry.batteryCapacity)
      : 1;
  const energyBonus = Math.round((1 - energyFrac) * 150);

  const flipPenalty = Math.min(200, telemetry.flips * 40);
  const crashPenalty = Math.min(150, telemetry.crashes * 15);

  const total = Math.max(
    0,
    completionPoints + timeBonus + stabilityBonus + energyBonus - flipPenalty - crashPenalty,
  );

  return {
    completionPoints,
    timeBonus,
    stabilityBonus,
    energyBonus,
    flipPenalty,
    crashPenalty,
    total,
    grade: gradeFor(total, telemetry.completed),
  };
}

export function gradeFor(total: number, completed: boolean): ScoreBreakdown['grade'] {
  if (completed && total >= 1500) return 'S';
  if (completed && total >= 1200) return 'A';
  if (completed || total >= 500) return 'B';
  if (total >= 250) return 'C';
  return 'D';
}

export function formatScore(n: number): string {
  return n.toLocaleString('en-US');
}
