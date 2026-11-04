"""Stateless detectors. Each takes a client-area BGR frame plus map settings.

All thresholds, ROIs and colors come from ``MapConfig``; nothing is hardcoded
to a map, class or resolution.
"""

from __future__ import annotations

import cv2
import numpy as np

from ..config.schema import Detection, HSVRange, Rect
from ..vision.color import hsv_mask, to_hsv
from ..vision.geometry import crop
from .match import ScaledImage, match_templates
from .snapshot import Box
from .templates import Template


# ---- minimap --------------------------------------------------------------

def find_player_dot(frame: np.ndarray, minimap: Rect, color: HSVRange,
                    min_area: int = 2) -> tuple[float, float] | None:
    """Centroid of the largest player-dot blob, relative to the minimap ROI."""
    mask = hsv_mask(to_hsv(crop(frame, minimap)), color)
    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return None
    areas = stats[1:, cv2.CC_STAT_AREA]
    i = int(np.argmax(areas))
    if areas[i] < min_area:
        return None
    cx, cy = centroids[i + 1]
    return float(cx), float(cy)


# ---- HP / MP bars ---------------------------------------------------------

def read_bar(frame: np.ndarray, bar: Rect, color: HSVRange, column_fill: float = 0.5) -> float:
    """Fill ratio 0..1 of a bar that fills from the left.

    A column counts as filled when ``column_fill`` of its pixels match the fill
    color. The fill end is the x that maximizes (filled - empty) columns to its
    left, so the HP/MP numbers drawn over the bar (short unfilled gaps inside
    the fill) and stray matches beyond it don't move the reading.
    """
    mask = hsv_mask(to_hsv(crop(frame, bar)), color)
    filled = (mask.mean(axis=0) / 255.0) >= column_fill
    if not filled.any():
        return 0.0
    gain = np.cumsum(np.where(filled, 1, -1))
    end = int(np.argmax(gain)) + 1
    return end / mask.shape[1] if gain[end - 1] > 0 else 0.0


# ---- templates in a region -----------------------------------------------

class Region:
    """A cropped part of the frame, downscaled lazily and shared by several detectors."""

    def __init__(self, frame: np.ndarray, rect: Rect | None) -> None:
        if rect is None:
            self.image, self.offset = frame, (0, 0)
        else:
            self.image, self.offset = crop(frame, rect), (rect.x, rect.y)
        self.scaled = ScaledImage(self.image)


def _in_region(region: Region, templates: list[Template], threshold: float,
               det: Detection, scale: float | None = None) -> list[Box]:
    if not templates:
        return []
    return match_templates(region.scaled, templates, threshold,
                           scale=det.match_scale if scale is None else scale,
                           nms_iou=det.nms_iou, offset=region.offset)


def track_window(play_area: Rect, last: Box, pad: int) -> Rect:
    """Sub-rectangle of the play area around the last name-tag box."""
    x0 = max(play_area.x, last.x - pad)
    y0 = max(play_area.y, last.y - pad)
    x1 = min(play_area.x + play_area.w, last.x + last.w + pad)
    y1 = min(play_area.y + play_area.h, last.y + last.h + pad)
    return Rect(x=x0, y=y0, w=max(1, x1 - x0), h=max(1, y1 - y0))


def find_nametag(frame: np.ndarray, area: Region, templates: list[Template], det: Detection,
                 play_area: Rect | None = None, last: Box | None = None) -> Box | None:
    """Best name-tag hit; searches near ``last`` first, then the whole play area."""
    if last is not None and play_area is not None and det.nametag_track_px > 0:
        near = Region(frame, track_window(play_area, last, det.nametag_track_px))
        hits = _in_region(near, templates, det.nametag_threshold, det)
        if hits:
            return max(hits, key=lambda b: b.score)
    hits = _in_region(area, templates, det.nametag_threshold, det)
    return max(hits, key=lambda b: b.score) if hits else None


def player_anchor(tag: Box, det: Detection) -> tuple[float, float]:
    """The name tag sits under the character; move up to roughly the body center."""
    return tag.cx, tag.cy - det.nametag_to_body_px


def find_monsters_template(area: Region, templates: list[Template], det: Detection) -> list[Box]:
    return _in_region(area, templates, det.monster_threshold, det)


def find_monsters_color(area: Region, det: Detection) -> list[Box]:
    assert det.monster_color is not None
    ox, oy = area.offset
    mask = hsv_mask(to_hsv(area.image), det.monster_color)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    n, _l, stats, _c = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, px = (int(v) for v in stats[i])
        if det.monster_min_area <= px <= det.monster_max_area:
            out.append(Box(x + ox, y + oy, w, h, 1.0, "color"))
    return out


def find_loot(area: Region, templates: list[Template], det: Detection) -> list[Box]:
    return _in_region(area, templates, det.loot_threshold, det)


def find_alerts(frame: np.ndarray, templates: list[Template], det: Detection) -> set[str]:
    by_name = {t.name: t for t in templates}
    hits = _in_region(Region(frame, None), templates, det.alert_threshold, det, scale=det.alert_scale)
    return {by_name[h.label].alert_kind for h in hits}
