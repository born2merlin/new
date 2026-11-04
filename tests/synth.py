"""Synthetic GMS-like client frames for tests (no real game assets needed).

Layout loosely follows a 1920x1080 client: minimap top-left with a yellow
player dot, red HP / blue MP bars bottom-center, a textured play area with
monster sprites, a name tag, loot coins and an optional death dialog.
Real screenshots go in tests/fixtures/local/<map>/ (git-ignored).
"""

from __future__ import annotations

import cv2
import numpy as np

W, H = 1920, 1080
MINIMAP = (10, 40, 220, 140)        # x, y, w, h
HP_BAR = (800, 1030, 160, 12)
MP_BAR = (980, 1030, 160, 12)
PLAY_AREA = (0, 200, 1920, 800)

# BGR colors
BG = (60, 90, 40)
MINIMAP_BG = (70, 70, 70)
YELLOW = (0, 230, 255)
RED = (40, 30, 230)
BLUE = (230, 120, 30)
EMPTY_BAR = (40, 40, 40)
MONSTER_PURPLE = (170, 40, 150)


def _monster_sprite() -> np.ndarray:
    """An asymmetric 48x40 blob with eyes, so its mirror image differs."""
    s = np.zeros((40, 48, 3), np.uint8)
    s[:] = BG
    cv2.ellipse(s, (24, 24), (20, 14), 0, 0, 360, MONSTER_PURPLE, -1)
    cv2.circle(s, (32, 18), 4, (255, 255, 255), -1)
    cv2.circle(s, (33, 18), 2, (0, 0, 0), -1)
    cv2.rectangle(s, (4, 30), (12, 38), (30, 30, 120), -1)  # a tail on one side only
    return s


def _coin_sprite() -> np.ndarray:
    s = np.zeros((20, 20, 3), np.uint8)
    s[:] = BG
    cv2.circle(s, (10, 10), 8, (0, 190, 240), -1)
    cv2.circle(s, (10, 10), 8, (0, 120, 160), 2)
    cv2.putText(s, "$", (5, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 80, 120), 1)
    return s


def _nametag_sprite(name: str = "IceMage38") -> np.ndarray:
    s = np.zeros((18, 90, 3), np.uint8)
    s[:] = (35, 35, 35)
    cv2.putText(s, name, (4, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
    return s


def _death_dialog() -> np.ndarray:
    s = np.full((120, 300, 3), (200, 200, 200), np.uint8)
    cv2.rectangle(s, (0, 0), (299, 119), (90, 60, 40), 3)
    cv2.putText(s, "You have died.", (40, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 2)
    cv2.rectangle(s, (110, 75), (190, 105), (60, 140, 220), -1)
    cv2.putText(s, "OK", (135, 97), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    return s


MONSTER = _monster_sprite()
COIN = _coin_sprite()
NAMETAG = _nametag_sprite()
DEATH = _death_dialog()


def _paste(img: np.ndarray, sprite: np.ndarray, x: int, y: int) -> None:
    h, w = sprite.shape[:2]
    img[y:y + h, x:x + w] = sprite


def frame(hp: float = 1.0, mp: float = 1.0, dot_x: int = 110, dot_y: int = 100,
          size: tuple[int, int] = (W, H), *,
          monsters: list[tuple[int, int, bool]] = (),
          loot: list[tuple[int, int]] = (),
          nametag: tuple[int, int] | None = None,
          dead: bool = False,
          noise: bool = False) -> np.ndarray:
    """Build a frame. ``monsters`` are (x, y, flipped) top-left positions."""
    w, h = size
    img = np.full((h, w, 3), BG, np.uint8)
    if noise:
        rng = np.random.default_rng(7)
        img = np.clip(img.astype(np.int16) + rng.integers(-12, 13, img.shape), 0, 255).astype(np.uint8)
    mx, my, mw, mh = MINIMAP
    img[my:my + mh, mx:mx + mw] = MINIMAP_BG
    img[dot_y - 2:dot_y + 3, dot_x - 2:dot_x + 3] = YELLOW
    for (x, y, bw, bh), fill, color in ((HP_BAR, hp, RED), (MP_BAR, mp, BLUE)):
        if y + bh <= h and x + bw <= w:
            img[y:y + bh, x:x + bw] = EMPTY_BAR
            img[y:y + bh, x:x + int(bw * fill)] = color
    # A slightly different red so the HP hue range must wrap through 0.
    if HP_BAR[1] + 3 <= h:
        img[HP_BAR[1]:HP_BAR[1] + 3, HP_BAR[0]:HP_BAR[0] + int(HP_BAR[2] * hp)] = (60, 20, 220)
    for x, y, flipped in monsters:
        _paste(img, MONSTER[:, ::-1] if flipped else MONSTER, x, y)
    for x, y in loot:
        _paste(img, COIN, x, y)
    if nametag is not None:
        _paste(img, NAMETAG, *nametag)
    if dead:
        _paste(img, DEATH, 810, 400)
    return img


def write_templates(map_dir, *, monsters=True, loot=True, player=True, alerts=True) -> None:
    """Save the synthetic sprites as calibration templates under ``map_dir/templates``."""
    from pathlib import Path

    from mapbot.capture.grabber import save_image

    root = Path(map_dir) / "templates"
    if monsters:
        save_image(root / "monsters" / "blob.png", MONSTER)
    if loot:
        save_image(root / "loot" / "meso.png", COIN)
    if player:
        save_image(root / "player" / "nametag.png", NAMETAG)
    if alerts:
        save_image(root / "alerts" / "death_dialog.png", DEATH)


def calibrated_map_yaml(name: str = "synth") -> str:
    """A fully calibrated map.yaml matching the synthetic layout."""
    def r(t):
        return "{x: %d, y: %d, w: %d, h: %d}" % t

    return f"""name: {name}
window_title: MapleStory
calibrated_resolution: {{width: {W}, height: {H}}}
rois:
  minimap: {r(MINIMAP)}
  hp_bar: {r(HP_BAR)}
  mp_bar: {r(MP_BAR)}
  play_area: {r(PLAY_AREA)}
colors:
  player_dot: {{lower: [20, 150, 180], upper: [35, 255, 255]}}
  hp_fill: {{lower: [170, 120, 120], upper: [6, 255, 255]}}
  mp_fill: {{lower: [100, 150, 150], upper: [115, 255, 255]}}
patrol: {{left_x: 40, right_x: 180}}
detection:
  monster_threshold: 0.8
  loot_threshold: 0.8
  nametag_threshold: 0.8
  alert_threshold: 0.8
"""
