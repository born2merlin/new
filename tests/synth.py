"""Synthetic GMS-like client frames for tests (no real game assets needed).

Layout loosely follows a 1920x1080 client: minimap top-left with a yellow
player dot, red HP / blue MP bars bottom-center. Phase 2 perception tests
reuse this; real screenshots go in tests/fixtures/<map>/.
"""

from __future__ import annotations

import numpy as np

W, H = 1920, 1080
MINIMAP = (10, 40, 220, 140)        # x, y, w, h
HP_BAR = (800, 1030, 160, 12)
MP_BAR = (980, 1030, 160, 12)

# BGR colors
BG = (60, 90, 40)
MINIMAP_BG = (70, 70, 70)
YELLOW = (0, 230, 255)
RED = (40, 30, 230)
BLUE = (230, 120, 30)
EMPTY_BAR = (40, 40, 40)


def frame(hp: float = 1.0, mp: float = 1.0, dot_x: int = 110, dot_y: int = 100,
          size: tuple[int, int] = (W, H)) -> np.ndarray:
    w, h = size
    img = np.full((h, w, 3), BG, np.uint8)
    mx, my, mw, mh = MINIMAP
    img[my:my + mh, mx:mx + mw] = MINIMAP_BG
    img[dot_y - 2:dot_y + 3, dot_x - 2:dot_x + 3] = YELLOW
    for (x, y, bw, bh), fill, color in ((HP_BAR, hp, RED), (MP_BAR, mp, BLUE)):
        if y + bh <= h and x + bw <= w:
            img[y:y + bh, x:x + bw] = EMPTY_BAR
            img[y:y + bh, x:x + int(bw * fill)] = color
    # A slightly different red so the HP hue range must wrap through 0.
    img[HP_BAR[1]:HP_BAR[1] + 3, HP_BAR[0]:HP_BAR[0] + int(HP_BAR[2] * hp)] = (60, 20, 220)
    return img
