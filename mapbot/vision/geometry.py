"""Small geometry helpers. All rects are client-area-relative unless noted."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config.schema import Rect


@dataclass(frozen=True)
class ScreenRegion:
    """Absolute screen rectangle (physical pixels)."""

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def contains(self, other: "ScreenRegion") -> bool:
        return (
            self.left <= other.left
            and self.top <= other.top
            and other.right <= self.right
            and other.bottom <= self.bottom
        )


def crop(frame: np.ndarray, rect: Rect) -> np.ndarray:
    """Crop a client-relative ``Rect`` out of a client-area frame.

    Raises ``ValueError`` if the rect lies outside the frame, which usually
    means the map was calibrated at a different resolution.
    """
    h, w = frame.shape[:2]
    if rect.x + rect.w > w or rect.y + rect.h > h:
        raise ValueError(
            f"ROI {rect.x},{rect.y} {rect.w}x{rect.h} is outside the {w}x{h} frame"
        )
    return frame[rect.y : rect.y + rect.h, rect.x : rect.x + rect.w]


def rect_from_xywh(x: int, y: int, w: int, h: int) -> Rect:
    return Rect(x=int(x), y=int(y), w=int(w), h=int(h))
