"""Template matching with downscaling, local-peak extraction and NMS."""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np

from .snapshot import Box
from .templates import MIN_TEMPLATE_PX, Template


def nms(boxes: Sequence[Box], iou: float) -> list[Box]:
    """Greedy non-max suppression: keep the best box, drop others overlapping it."""
    kept: list[Box] = []
    for b in sorted(boxes, key=lambda b: b.score, reverse=True):
        if all(b.iou(k) <= iou for k in kept):
            kept.append(b)
    return kept


class ScaledImage:
    """Caches downscaled copies of one frame so several templates share the work."""

    def __init__(self, image: np.ndarray) -> None:
        self.image = image
        self._cache: dict[float, np.ndarray] = {1.0: image}

    def at(self, scale: float) -> np.ndarray:
        if scale not in self._cache:
            self._cache[scale] = cv2.resize(
                self.image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
            )
        return self._cache[scale]


def effective_scale(t: Template, scale: float) -> float:
    """Don't shrink a template below MIN_TEMPLATE_PX; small sprites match at higher scale."""
    w, h = t.size
    need = MIN_TEMPLATE_PX / min(w, h)
    return 1.0 if need >= 1.0 else max(scale, round(need, 2))


def match_scores(image: np.ndarray, t: Template, scale: float = 1.0) -> tuple[np.ndarray, float]:
    """Raw TM_CCOEFF_NORMED map for one template. Returns (scores, scale used)."""
    s = effective_scale(t, scale)
    img = image if s == 1.0 else cv2.resize(image, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    tpl = t.scaled(s)
    if tpl.shape[0] > img.shape[0] or tpl.shape[1] > img.shape[1]:
        return np.zeros((0, 0), np.float32), s
    res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
    return np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0), s


def _peaks(res: np.ndarray, threshold: float, tw: int, th: int, limit: int = 200):
    """Local maxima of ``res`` above ``threshold`` (at most ``limit``, best first)."""
    if res.size == 0:
        return []
    k = max(3, (min(tw, th) // 2) | 1)
    local_max = cv2.dilate(res, np.ones((k, k), np.uint8))
    ys, xs = np.where((res >= threshold) & (res >= local_max - 1e-6))
    if len(xs) > limit:
        order = np.argsort(res[ys, xs])[::-1][:limit]
        ys, xs = ys[order], xs[order]
    return [(int(x), int(y), float(res[y, x])) for y, x in zip(ys, xs)]


def match_templates(
    image: np.ndarray | ScaledImage,
    templates: Sequence[Template],
    threshold: float,
    *,
    scale: float = 1.0,
    nms_iou: float = 0.3,
    offset: tuple[int, int] = (0, 0),
) -> list[Box]:
    """Find every template in ``image``; boxes are full-resolution, shifted by ``offset``."""
    si = image if isinstance(image, ScaledImage) else ScaledImage(image)
    ox, oy = offset
    boxes: list[Box] = []
    for t in templates:
        s = effective_scale(t, scale)
        img = si.at(s)
        tpl = t.scaled(s)
        th, tw = tpl.shape[:2]
        if th > img.shape[0] or tw > img.shape[1]:
            continue
        res = np.nan_to_num(cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED), nan=0.0)
        w, h = t.size
        for x, y, score in _peaks(res, threshold, tw, th):
            boxes.append(Box(int(round(x / s)) + ox, int(round(y / s)) + oy, w, h, score, t.name))
    return nms(boxes, nms_iou)


def best_scores(image: np.ndarray, t: Template, scale: float = 1.0, n: int = 5) -> list[float]:
    """Top ``n`` distinct peak scores (for suggesting a threshold during calibration)."""
    res, s = match_scores(image, t, scale)
    th, tw = t.scaled(s).shape[:2]
    peaks = _peaks(res, -1.0, tw, th, limit=2000)
    boxes = nms([Box(x, y, tw, th, sc) for x, y, sc in peaks], 0.1)
    return [b.score for b in boxes[:n]]
