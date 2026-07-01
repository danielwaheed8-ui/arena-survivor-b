'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { RobotPreview } from '@/components/RobotPreview';
import { Badge, Button, Panel } from '@/components/ui';
import { batteryCapacity, cloneDesign, PRESET_ROBOTS, totalMass } from '@/lib/robots';
import { deleteRobot, loadRobots, saveRobot } from '@/lib/storage';
import { useGameStore } from '@/store/gameStore';
import type { RobotDesign } from '@/lib/types';

export default function RobotsPage() {
  const router = useRouter();
  const setDesign = useGameStore((s) => s.setDesign);
  const hydrate = useGameStore((s) => s.hydrate);
  const [robots, setRobots] = useState<RobotDesign[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    hydrate();
    setRobots(loadRobots());
    setLoaded(true);
  }, [hydrate]);

  const refresh = () => setRobots(loadRobots());

  // Presets get a fresh identity (saving one must not shadow the factory
  // design); saved robots keep their id so Save updates them in place.
  const loadForUse = (robot: RobotDesign, isPreset: boolean): RobotDesign =>
    isPreset ? cloneDesign(robot, robot.name) : (JSON.parse(JSON.stringify(robot)) as RobotDesign);

  const openInBuilder = (robot: RobotDesign, isPreset: boolean) => {
    setDesign(loadForUse(robot, isPreset));
    router.push('/builder');
  };

  const card = (robot: RobotDesign, isPreset: boolean) => (
    <article
      key={robot.id}
      className="glass-panel animate-fade-up overflow-hidden transition-all hover:border-neon-cyan/40 hover:shadow-neon"
      data-testid={isPreset ? `preset-card-${robot.id}` : `robot-card-${robot.id}`}
    >
      <RobotPreview design={robot} className="h-36 w-full border-b border-white/[0.07]" />
      <div className="p-4">
        <div className="flex items-center justify-between gap-2">
          <h2 className="truncate text-sm font-semibold text-white">{robot.name}</h2>
          {isPreset ? <Badge tone="magenta">Preset</Badge> : <Badge tone="cyan">Custom</Badge>}
        </div>
        <p className="mono-value mt-1 text-[11px] text-slate-500">
          {robot.parts.length} parts · {totalMass(robot).toFixed(1)}u · {batteryCapacity(robot)}⚡
        </p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Button size="sm" onClick={() => openInBuilder(robot, isPreset)}>
            Edit
          </Button>
          <Button
            size="sm"
            variant="accent"
            onClick={() => {
              setDesign(loadForUse(robot, isPreset));
              router.push('/simulate');
            }}
          >
            Test
          </Button>
          {!isPreset && (
            <>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  const copy = cloneDesign(robot);
                  saveRobot(copy);
                  refresh();
                }}
              >
                Duplicate
              </Button>
              <Button
                size="sm"
                variant="danger"
                onClick={() => {
                  deleteRobot(robot.id);
                  refresh();
                }}
                data-testid={`delete-${robot.id}`}
              >
                Delete
              </Button>
            </>
          )}
        </div>
      </div>
    </article>
  );

  return (
    <div className="mx-auto max-w-7xl px-4 pb-16 pt-8 sm:px-6">
      <header className="mb-6">
        <p className="hud-label text-neon-magenta">Hangar Storage</p>
        <h1 className="neon-heading mt-1 text-2xl text-white">Robot Garage</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-400">
          Saved designs live in your browser. Edit them in the builder, clone variants, or send
          one straight into a trial.
        </p>
      </header>

      <Panel title={`Your Builds · ${robots.length}`} className="mb-8">
        {!loaded ? (
          <p className="py-8 text-center text-sm text-slate-500">Opening garage…</p>
        ) : robots.length === 0 ? (
          <div className="py-8 text-center" data-testid="garage-empty">
            <p className="text-sm text-slate-400">No saved robots yet.</p>
            <p className="mt-1 text-xs text-slate-600">
              Build one in the workshop and press <span className="text-fuchsia-300">Save</span> —
              it will be stored right here.
            </p>
            <Button className="mt-4" onClick={() => router.push('/builder')}>
              Open Builder
            </Button>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {robots.map((r) => card(r, false))}
          </div>
        )}
      </Panel>

      <Panel title="Factory Presets">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {PRESET_ROBOTS.map((r) => card(r, true))}
        </div>
      </Panel>
    </div>
  );
}
