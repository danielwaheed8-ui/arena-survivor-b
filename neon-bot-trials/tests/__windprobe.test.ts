import { describe, expect, it } from 'vitest';
import { getArenaById } from '@/lib/arenas';
import { SimEngine } from '@/lib/engine';
import { PRESET_ROBOTS } from '@/lib/robots';

describe('wind probe', () => {
  it('reports whether any body ever enters a wind zone in wind-tunnel', () => {
    const arena = getArenaById('wind-tunnel')!;
    for (const preset of PRESET_ROBOTS) {
      const engine = new SimEngine(arena, preset);
      engine.start();
      let minBodyY = Infinity;
      let everInZone = false;
      let everWindSample = false;
      for (let i = 0; i < 3600 && !engine.isOver(); i++) {
        engine.tick();
        const f = engine.getFrame();
        if (f.windSample) everWindSample = true;
        for (const b of f.bodies) {
          minBodyY = Math.min(minBodyY, b.y);
          for (const z of arena.windZones) {
            if (
              b.x > z.x - z.w / 2 &&
              b.x < z.x + z.w / 2 &&
              b.y > z.y - z.h / 2 &&
              b.y < z.y + z.h / 2
            ) {
              everInZone = true;
            }
          }
        }
      }
      const tel = engine.getTelemetry();
      // eslint-disable-next-line no-console
      console.log(
        `${preset.name}: minBodyY=${minBodyY.toFixed(1)} everInZone=${everInZone} windBadge=${everWindSample} t=${tel.t} maxX=${tel.maxX} completed=${tel.completed} fail=${tel.failReason ?? '-'}`,
      );
    }
    expect(true).toBe(true);
  });
});
