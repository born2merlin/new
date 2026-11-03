"""HSV color helpers shared by calibration and perception.

OpenCV hue runs 0-179 and is circular, so red sits at both ends. Ranges whose
lower hue is greater than the upper hue wrap through 0.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import cv2
import numpy as np

from ..config.schema import HSVRange

HUE_MAX = 180  # exclusive; OpenCV 8-bit hue is 0..179


def to_hsv(bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)


def hsv_mask(hsv: np.ndarray, rng: HSVRange) -> np.ndarray:
    """Binary mask (0/255) of pixels inside ``rng``, handling hue wraparound."""
    (hl, sl, vl), (hu, su, vu) = rng.lower, rng.upper
    if hl <= hu:
        return cv2.inRange(hsv, np.array([hl, sl, vl]), np.array([hu, su, vu]))
    a = cv2.inRange(hsv, np.array([hl, sl, vl]), np.array([HUE_MAX - 1, su, vu]))
    b = cv2.inRange(hsv, np.array([0, sl, vl]), np.array([hu, su, vu]))
    return cv2.bitwise_or(a, b)


def _hue_arc(hues: Sequence[int]) -> tuple[int, int, int]:
    """Smallest circular arc covering all hues. Returns (start, end, length)."""
    hs = sorted(set(int(h) % HUE_MAX for h in hues))
    if len(hs) == 1:
        return hs[0], hs[0], 0
    # The arc is the complement of the largest gap between neighboring hues.
    gaps = [((hs[(i + 1) % len(hs)] - hs[i]) % HUE_MAX, i) for i in range(len(hs))]
    gap, i = max(gaps)
    start, end = hs[(i + 1) % len(hs)], hs[i]
    return start, end, HUE_MAX - gap


def suggest_range(
    samples_hsv: Iterable[Sequence[int]],
    *,
    hue_margin: int = 6,
    sat_margin: int = 40,
    val_margin: int = 40,
) -> HSVRange:
    """Build an HSV range that covers every sampled pixel plus a margin."""
    pts = np.asarray(list(samples_hsv), dtype=int).reshape(-1, 3)
    if len(pts) == 0:
        raise ValueError("need at least one sample pixel")

    start, end, length = _hue_arc(pts[:, 0])
    if length + 2 * hue_margin >= HUE_MAX - 1:
        h_lo, h_hi = 0, HUE_MAX - 1
    else:
        h_lo = (start - hue_margin) % HUE_MAX
        h_hi = (end + hue_margin) % HUE_MAX

    def clamp(v: int) -> int:
        return int(max(0, min(255, v)))

    s_lo, s_hi = clamp(pts[:, 1].min() - sat_margin), clamp(pts[:, 1].max() + sat_margin)
    v_lo, v_hi = clamp(pts[:, 2].min() - val_margin), clamp(pts[:, 2].max() + val_margin)
    return HSVRange(lower=(h_lo, s_lo, v_lo), upper=(h_hi, s_hi, v_hi))


def sample_patch(hsv: np.ndarray, x: int, y: int, radius: int = 1) -> list[tuple[int, int, int]]:
    """HSV values of the (2r+1)^2 patch around (x, y), clipped to the image."""
    h, w = hsv.shape[:2]
    y0, y1 = max(0, y - radius), min(h, y + radius + 1)
    x0, x1 = max(0, x - radius), min(w, x + radius + 1)
    return [tuple(int(c) for c in px) for px in hsv[y0:y1, x0:x1].reshape(-1, 3)]
