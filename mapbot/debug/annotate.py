"""Draw what perception sees onto a copy of the frame (inspect, check, overlay)."""

from __future__ import annotations

import cv2
import numpy as np

from ..config.schema import MapConfig, Rect
from ..perception.snapshot import Box, Perception

GREEN = (80, 220, 80)
RED = (60, 60, 240)
YELLOW = (0, 230, 255)
CYAN = (230, 220, 40)
WHITE = (255, 255, 255)
GRAY = (160, 160, 160)
FONT = cv2.FONT_HERSHEY_SIMPLEX


def _rect(img, r: Rect | Box, color, label: str = "", thick: int = 2) -> None:
    cv2.rectangle(img, (r.x, r.y), (r.x + r.w, r.y + r.h), color, thick)
    if label:
        cv2.putText(img, label, (r.x, max(12, r.y - 4)), FONT, 0.45, color, 1, cv2.LINE_AA)


def _text(img, lines: list[str], org=(10, 0)) -> None:
    x, y = org
    for i, line in enumerate(lines):
        yy = y + 22 + i * 20
        cv2.putText(img, line, (x, yy), FONT, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, line, (x, yy), FONT, 0.55, WHITE, 1, cv2.LINE_AA)


def annotate(frame: np.ndarray, p: Perception, cfg: MapConfig, *,
             extra_lines: list[str] | None = None) -> np.ndarray:
    img = frame.copy()
    r = cfg.rois
    for name, roi in (("minimap", r.minimap), ("hp", r.hp_bar), ("mp", r.mp_bar)):
        if roi is not None:
            _rect(img, roi, GRAY, name, 1)
    if r.play_area is not None:
        _rect(img, r.play_area, GRAY, "play area", 1)

    if r.minimap is not None:
        if cfg.patrol is not None:
            for x in (cfg.patrol.left_x, cfg.patrol.right_x):
                cv2.line(img, (r.minimap.x + x, r.minimap.y), (r.minimap.x + x, r.minimap.y + r.minimap.h), CYAN, 1)
        if p.player_minimap is not None:
            c = (int(r.minimap.x + p.player_minimap[0]), int(r.minimap.y + p.player_minimap[1]))
            cv2.circle(img, c, 6, YELLOW, 2)

    for m in p.monsters:
        _rect(img, m, RED, f"{m.label} {m.score:.2f}")
    for b in p.loot:
        _rect(img, b, YELLOW, f"loot {b.score:.2f}")
    if p.nametag is not None:
        _rect(img, p.nametag, GREEN, f"me {p.nametag.score:.2f}")
    if p.player_screen is not None:
        x, y = (int(v) for v in p.player_screen)
        cv2.drawMarker(img, (x, y), GREEN, cv2.MARKER_CROSS, 24, 2)

    pct = lambda v: "--" if v is None else f"{v:.0%}"  # noqa: E731
    lines = [
        f"HP {pct(p.hp)}  MP {pct(p.mp)}  monsters {len(p.monsters)}  loot {len(p.loot)}",
        f"dot {None if p.player_minimap is None else tuple(round(v) for v in p.player_minimap)}"
        f"  alerts {', '.join(sorted(p.alerts)) or 'none'}",
        "ms " + " ".join(f"{k}:{v:.0f}" for k, v in p.timings_ms.items()),
    ] + (extra_lines or [])
    # Put the text block just right of the minimap so it doesn't cover it.
    x0 = (r.minimap.x + r.minimap.w + 12) if r.minimap is not None else 10
    _text(img, lines, (x0, 0))
    if p.alerts:
        cv2.rectangle(img, (0, 0), (img.shape[1] - 1, img.shape[0] - 1), RED, 6)
    return img
