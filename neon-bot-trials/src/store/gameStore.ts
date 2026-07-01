'use client';

import { create } from 'zustand';
import { DEFAULT_ARENA_ID } from '@/lib/arenas';
import { cloneDesign, PRESET_ROBOTS } from '@/lib/robots';
import { loadDraft, saveDraft } from '@/lib/storage';
import type { RobotDesign } from '@/lib/types';

/**
 * Session-level game state. The builder draft auto-persists to localStorage
 * (debounced) so work in progress survives navigation and reloads.
 */
interface GameState {
  hydrated: boolean;
  design: RobotDesign;
  arenaId: string;
  speed: number;
  cinematic: boolean;

  hydrate: () => void;
  setDesign: (design: RobotDesign) => void;
  setArenaId: (id: string) => void;
  setSpeed: (speed: number) => void;
  setCinematic: (on: boolean) => void;
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;
function persistDraft(design: RobotDesign): void {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => saveDraft(design), 300);
}

export const useGameStore = create<GameState>((set, get) => ({
  hydrated: false,
  design: cloneDesign(PRESET_ROBOTS[0], 'Volt Roller'),
  arenaId: DEFAULT_ARENA_ID,
  speed: 1,
  cinematic: false,

  hydrate: () => {
    if (get().hydrated) return;
    const draft = loadDraft();
    set({ hydrated: true, ...(draft ? { design: draft } : {}) });
  },

  setDesign: (design) => {
    persistDraft(design);
    set({ design });
  },

  setArenaId: (arenaId) => set({ arenaId }),
  setSpeed: (speed) => set({ speed }),
  setCinematic: (cinematic) => {
    if (typeof document !== 'undefined') {
      document.body.classList.toggle('cinematic', cinematic);
    }
    set({ cinematic });
  },
}));
