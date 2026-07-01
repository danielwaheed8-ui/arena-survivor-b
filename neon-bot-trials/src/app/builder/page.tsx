'use client';

import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import { BuilderCanvas, type BuilderMode } from '@/components/BuilderCanvas';
import { Badge, Button, Panel, Slider, Stat } from '@/components/ui';
import { ARENAS } from '@/lib/arenas';
import { PART_CATALOG, PART_TYPES } from '@/lib/parts';
import {
  addPart,
  batteryCapacity,
  canAddPart,
  cloneDesign,
  countParts,
  createEmptyRobot,
  MAX_TOTAL_PARTS,
  PRESET_ROBOTS,
  removePart,
  totalMass,
  updatePart,
} from '@/lib/robots';
import { saveRobot } from '@/lib/storage';
import { useGameStore } from '@/store/gameStore';
import type { PartType } from '@/lib/types';

export default function BuilderPage() {
  const router = useRouter();
  const design = useGameStore((s) => s.design);
  const setDesign = useGameStore((s) => s.setDesign);
  const hydrate = useGameStore((s) => s.hydrate);
  const hydrated = useGameStore((s) => s.hydrated);
  const arenaId = useGameStore((s) => s.arenaId);
  const setArenaId = useGameStore((s) => s.setArenaId);

  const [mode, setMode] = useState<BuilderMode>({ kind: 'select' });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ text: string; tone: 'ok' | 'err' } | null>(null);
  const noticeTimer = useRef<number | null>(null);

  useEffect(() => hydrate(), [hydrate]);
  useEffect(
    () => () => {
      if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    },
    [],
  );

  const flash = useCallback((text: string, tone: 'ok' | 'err' = 'ok') => {
    if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    setNotice({ text, tone });
    noticeTimer.current = window.setTimeout(() => setNotice(null), 2600);
  }, []);

  const selected = design.parts.find((p) => p.id === selectedId) ?? null;

  const handlePlace = useCallback(
    (x: number, y: number) => {
      if (mode.kind !== 'place') return;
      const result = addPart(design, mode.type, { x, y });
      if (!result.part) {
        flash(result.reason ?? 'Cannot add part.', 'err');
        return;
      }
      setDesign(result.design);
      setSelectedId(result.part.id);
      setMode({ kind: 'select' });
    },
    [design, mode, setDesign, flash],
  );

  const handleMovePart = useCallback(
    (partId: string, x: number, y: number) => {
      setDesign(updatePart(design, partId, { anchor: { x, y } }));
    },
    [design, setDesign],
  );

  const handleRemoveSelected = useCallback(() => {
    if (!selectedId) return;
    setDesign(removePart(design, selectedId));
    setSelectedId(null);
  }, [design, selectedId, setDesign]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedId) {
        const tag = (e.target as HTMLElement)?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA') return;
        e.preventDefault();
        handleRemoveSelected();
      }
      if (e.key === 'Escape') setMode({ kind: 'select' });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectedId, handleRemoveSelected]);

  const handleSave = () => {
    const result = saveRobot(design);
    if (result.ok) flash(`“${design.name}” saved to garage.`);
    else flash(result.error ?? 'Save failed.', 'err');
  };

  const handleTest = () => {
    router.push(`/simulate?arena=${arenaId}`);
  };

  if (!hydrated) {
    return <div className="p-10 text-center text-sm text-slate-500">Loading workshop…</div>;
  }

  return (
    <div className="mx-auto max-w-[1500px] px-4 pb-12 pt-6 sm:px-6">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="hud-label text-neon-magenta">Fabrication Bay</p>
          <h1 className="neon-heading mt-0.5 text-xl text-white">Robot Builder</h1>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="rounded-lg border border-white/15 bg-panel px-3 py-1.5 text-xs text-slate-200 outline-none focus:border-neon-cyan/50"
            value=""
            onChange={(e) => {
              const preset = PRESET_ROBOTS.find((r) => r.id === e.target.value);
              if (preset) {
                setDesign(cloneDesign(preset, preset.name));
                setSelectedId(null);
                flash(`Loaded preset “${preset.name}”.`);
              }
            }}
            data-testid="preset-select"
          >
            <option value="" disabled>
              Load preset…
            </option>
            {PRESET_ROBOTS.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setDesign(createEmptyRobot('New Prototype'));
              setSelectedId(null);
            }}
          >
            New Frame
          </Button>
        </div>
      </header>

      {notice && (
        <div
          className={`animate-fade-up mb-3 rounded-lg border px-4 py-2 text-xs font-medium ${
            notice.tone === 'ok'
              ? 'border-emerald-400/40 bg-emerald-400/10 text-emerald-200'
              : 'border-rose-400/40 bg-rose-400/10 text-rose-200'
          }`}
          data-testid="builder-notice"
        >
          {notice.text}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[250px_minmax(0,1fr)_300px]">
        {/* Part palette */}
        <div className="space-y-4">
          <Panel title="Part Catalog">
            <div className="grid grid-cols-2 gap-2">
              {PART_TYPES.map((type) => {
                const def = PART_CATALOG[type];
                const count = countParts(design, type);
                const armed = mode.kind === 'place' && mode.type === type;
                const allowed = canAddPart(design, type).ok;
                return (
                  <button
                    key={type}
                    onClick={() => setMode(armed ? { kind: 'select' } : { kind: 'place', type })}
                    disabled={!allowed && !armed}
                    title={def.description}
                    data-testid={`palette-${type}`}
                    className={`flex flex-col items-center gap-1 rounded-lg border p-2.5 text-center transition-all disabled:opacity-35 ${
                      armed
                        ? 'border-neon-magenta/70 bg-neon-magenta/15 shadow-neon-pink'
                        : 'border-white/10 bg-white/[0.03] hover:border-neon-cyan/40 hover:bg-neon-cyan/10'
                    }`}
                  >
                    <span className="text-lg leading-none text-neon-cyan">{def.icon}</span>
                    <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-200">
                      {def.label}
                    </span>
                    <span className="mono-value text-[9px] text-slate-500">
                      {count}/{def.maxCount}
                    </span>
                  </button>
                );
              })}
            </div>
            <p className="mt-3 text-[10px] leading-snug text-slate-500">
              {mode.kind === 'place'
                ? `Click the canvas to mount the ${PART_CATALOG[mode.type].label}. Esc to cancel.`
                : 'Arm a part, then click near the chassis to mount it. Drag anchors to reposition.'}
            </p>
          </Panel>

          <Panel title="Chassis">
            <div className="space-y-3">
              <Slider
                label="Width"
                min={50}
                max={130}
                step={2}
                unit="px"
                value={design.chassis.width}
                onChange={(v) =>
                  setDesign({ ...design, chassis: { ...design.chassis, width: v }, updatedAt: Date.now() })
                }
              />
              <Slider
                label="Height"
                min={18}
                max={50}
                step={2}
                unit="px"
                value={design.chassis.height}
                onChange={(v) =>
                  setDesign({ ...design, chassis: { ...design.chassis, height: v }, updatedAt: Date.now() })
                }
              />
              <Slider
                label="Hull Tint"
                min={0}
                max={360}
                step={5}
                unit="°"
                value={design.hue}
                onChange={(v) => setDesign({ ...design, hue: v, updatedAt: Date.now() })}
              />
            </div>
          </Panel>
        </div>

        {/* Canvas */}
        <Panel className="min-h-[420px] lg:min-h-[560px]">
          <BuilderCanvas
            design={design}
            mode={mode}
            selectedId={selectedId}
            onPlace={handlePlace}
            onSelect={setSelectedId}
            onMovePart={handleMovePart}
            className="h-[420px] w-full rounded-xl lg:h-[560px]"
          />
        </Panel>

        {/* Right column: tuning + stats + actions */}
        <div className="space-y-4">
          <Panel
            title={selected ? `Tuning · ${PART_CATALOG[selected.type].label}` : 'Tuning'}
            action={
              selected && (
                <Button variant="danger" size="sm" onClick={handleRemoveSelected} data-testid="remove-part">
                  Remove
                </Button>
              )
            }
          >
            {selected ? (
              <div className="space-y-3" data-testid="tuning-panel">
                {PART_CATALOG[selected.type].params.map((param) => (
                  <Slider
                    key={param.key}
                    label={param.label}
                    min={param.min}
                    max={param.max}
                    step={param.step}
                    unit={param.unit}
                    hint={param.hint}
                    value={selected.tuning[param.key] ?? param.default}
                    onChange={(v) =>
                      setDesign(updatePart(design, selected.id, { tuning: { [param.key]: v } }))
                    }
                  />
                ))}
                <Slider
                  label="Mount Rotation"
                  min={-180}
                  max={180}
                  step={5}
                  unit="°"
                  hint="Orientation of the part on the hull. Thrusters push along this axis."
                  value={Math.round((selected.angle * 180) / Math.PI)}
                  onChange={(v) =>
                    setDesign(updatePart(design, selected.id, { angle: (v * Math.PI) / 180 }))
                  }
                />
              </div>
            ) : (
              <p className="text-xs leading-relaxed text-slate-500">
                Select a mounted part to tune its motors, rhythm and geometry — or arm a part from
                the catalog and click the canvas to mount it.
              </p>
            )}
          </Panel>

          <Panel title="Frame Telemetry">
            <div className="grid grid-cols-3 gap-3">
              <Stat label="Mass" value={totalMass(design).toFixed(1)} unit="u" />
              <Stat label="Battery" value={batteryCapacity(design)} unit="⚡" />
              <Stat
                label="Parts"
                value={`${design.parts.length}/${MAX_TOTAL_PARTS}`}
                tone={design.parts.length >= MAX_TOTAL_PARTS ? 'warn' : 'default'}
              />
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {design.parts.length === 0 && <Badge tone="amber">No locomotion mounted</Badge>}
              {countParts(design, 'wheel') + countParts(design, 'leg') + countParts(design, 'spring') + countParts(design, 'thruster') === 0 &&
                design.parts.length > 0 && <Badge tone="rose">Bot cannot move</Badge>}
              {countParts(design, 'stabilizer') === 0 && <Badge tone="amber">No gyro</Badge>}
              {countParts(design, 'sensor') > 0 && <Badge tone="lime">Closed-loop recovery</Badge>}
            </div>
          </Panel>

          <Panel title="Deploy">
            <label className="hud-label mb-1 block">Designation</label>
            <input
              value={design.name}
              onChange={(e) => setDesign({ ...design, name: e.target.value, updatedAt: Date.now() })}
              maxLength={28}
              className="mb-3 w-full rounded-lg border border-white/15 bg-panel px-3 py-2 text-sm text-white outline-none focus:border-neon-cyan/60"
              data-testid="robot-name"
            />
            <label className="hud-label mb-1 block">Test Arena</label>
            <select
              className="mb-3 w-full rounded-lg border border-white/15 bg-panel px-3 py-2 text-sm text-slate-200 outline-none focus:border-neon-cyan/50"
              value={arenaId}
              onChange={(e) => setArenaId(e.target.value)}
              data-testid="builder-arena-select"
            >
              {ARENAS.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} · {'◆'.repeat(a.difficulty)}
                </option>
              ))}
            </select>
            <div className="flex gap-2">
              <Button className="flex-1" onClick={handleTest} data-testid="launch-test">
                ▶ Launch Test
              </Button>
              <Button variant="accent" onClick={handleSave} data-testid="save-robot">
                Save
              </Button>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
