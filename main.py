#!/usr/bin/env python3
"""
Temple Run — World-Class Python Edition (launcher)
==================================================

A pseudo-3D endless runner built on pygame.

    pip install pygame
    python main.py          # or:  python -m temple_run

Controls
--------
    Left / Right  (A / D)        change lanes
    Up / W / Space               jump over low barriers
    Down / S                     slide under high beams
    Esc / P                      pause

All the real code lives in the :mod:`temple_run` package, split into small,
single-responsibility modules: the engine core, the endless track, the pseudo-3D
renderer, the entities, and the meta-systems (audio, particles, scoring,
difficulty, powerups, achievements, missions, shop and UI).
"""

import os
import sys


def main() -> None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from temple_run.game import main as run
    except ImportError as exc:
        print("Failed to import the game package.")
        print("Did you install pygame?  ->  pip install pygame")
        print(f"Details: {exc}")
        sys.exit(1)
    run()


if __name__ == "__main__":
    main()
