#!/usr/bin/env python3
"""
Temple Run — World-Class Python Edition (launcher / web entry)
==============================================================

A pseudo-3D endless runner built on pygame.

    pip install pygame
    python main.py            # desktop
    python -m temple_run      # desktop (alternative)

This file is also the **pygbag** entry point for the WebAssembly build: it runs
an async main loop that yields to the browser each frame, so the same code plays
both on the desktop and in a browser tab.

Controls
--------
    Left / Right  (A / D)        change lanes
    Up / W / Space               jump over low barriers
    Down / S                     slide under high beams
    Esc / P                      pause
"""

import asyncio
import os
import sys


async def main() -> None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from temple_run.game import amain
    except ImportError as exc:
        print("Failed to import the game package.")
        print("Did you install pygame?  ->  pip install pygame")
        print(f"Details: {exc}")
        raise
    await amain()


if __name__ == "__main__":
    asyncio.run(main())
