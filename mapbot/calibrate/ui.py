"""Interactive OpenCV helpers for calibration.

The pure parts (display scaling, zoom math, color picking state) are kept
separate from the windowing code so they can be unit tested headless.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from ..config.schema import HSVRange, Rect
from ..errors import UserError
from ..vision.color import hsv_mask, sample_patch, suggest_range, to_hsv

MAX_DISPLAY = (1600, 900)  # fits a 1080p screen with the taskbar and title bar
REFINE_BELOW_PX = 500      # selections narrower than this get a zoomed refine step


class GuiError(UserError):
    pass


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------

def fit_scale(w: int, h: int, max_wh: tuple[int, int] = MAX_DISPLAY, max_zoom: float = 1.0) -> float:
    """Scale so a w x h image fits ``max_wh`` without exceeding ``max_zoom``."""
    return min(max_zoom, max_wh[0] / w, max_wh[1] / h)


def display_to_image(rect_xywh: tuple[int, int, int, int], scale: float,
                     offset: tuple[int, int] = (0, 0)) -> tuple[int, int, int, int]:
    """Map a rect drawn on a scaled (and possibly cropped) view back to image pixels."""
    x, y, w, h = rect_xywh
    ox, oy = offset
    return (
        int(round(x / scale)) + ox,
        int(round(y / scale)) + oy,
        max(1, int(round(w / scale))),
        max(1, int(round(h / scale))),
    )


def padded_crop_box(rect: tuple[int, int, int, int], img_w: int, img_h: int,
                    pad: int = 40) -> tuple[int, int, int, int]:
    """Box around ``rect`` with ``pad`` pixels of margin, clipped to the image."""
    x, y, w, h = rect
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(img_w, x + w + pad), min(img_h, y + h + pad)
    return x0, y0, x1 - x0, y1 - y0


@dataclass
class ColorPicker:
    """State for picking an HSV range by clicking sample pixels."""

    image_bgr: np.ndarray
    margins: list[int] = field(default_factory=lambda: [6, 40, 40])
    samples: list[tuple[int, int, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.hsv = to_hsv(self.image_bgr)

    def add(self, x: int, y: int, radius: int = 1) -> None:
        self.samples.extend(sample_patch(self.hsv, x, y, radius))

    def reset(self) -> None:
        self.samples.clear()

    def widen(self, direction: int) -> None:
        """Grow (+1) or shrink (-1) the range: hue by 1, sat/val by 10."""
        d = 1 if direction > 0 else -1
        h, s, v = self.margins
        self.margins = [max(0, h + d), max(0, s + 10 * d), max(0, v + 10 * d)]

    def range(self) -> HSVRange | None:
        if not self.samples:
            return None
        h, s, v = self.margins
        return suggest_range(self.samples, hue_margin=h, sat_margin=s, val_margin=v)

    def mask(self) -> np.ndarray:
        rng = self.range()
        if rng is None:
            return np.zeros(self.hsv.shape[:2], np.uint8)
        return hsv_mask(self.hsv, rng)

    def coverage(self) -> float:
        m = self.mask()
        return float(np.count_nonzero(m)) / m.size if m.size else 0.0


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

def _check_gui() -> None:
    try:
        cv2.namedWindow("mapbot")
        cv2.destroyWindow("mapbot")
    except cv2.error as e:
        raise GuiError(
            "OpenCV was installed without GUI support. Install 'opencv-python' "
            "(not opencv-python-headless)"
        ) from e


def _select(title: str, img: np.ndarray) -> tuple[int, int, int, int]:
    cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
    cv2.setWindowProperty(title, cv2.WND_PROP_TOPMOST, 1)
    r = cv2.selectROI(title, img, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(title)
    return tuple(int(v) for v in r)  # (0,0,0,0) when cancelled


def select_rect(image: np.ndarray, prompt: str) -> Rect | None:
    """Let the user drag a rectangle. Small selections get a zoomed refine pass.

    Returns ``None`` if the user cancels (Esc or 'c').
    """
    _check_gui()
    ih, iw = image.shape[:2]
    s = fit_scale(iw, ih)
    view = cv2.resize(image, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else image
    coarse = _select(f"{prompt}  [drag, Enter=ok, c=skip]", view)
    if coarse[2] == 0 or coarse[3] == 0:
        return None
    rect = display_to_image(coarse, s)

    if rect[2] < REFINE_BELOW_PX:
        bx, by, bw, bh = padded_crop_box(rect, iw, ih)
        z = fit_scale(bw, bh, max_zoom=6.0)
        crop = image[by:by + bh, bx:bx + bw]
        zoomed = cv2.resize(crop, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
        fine = _select(f"{prompt} - refine (zoomed {z:.1f}x)  [Enter=ok, c=keep coarse]", zoomed)
        if fine[2] and fine[3]:
            rect = display_to_image(fine, z, offset=(bx, by))

    x, y, w, h = rect
    w, h = min(w, iw - x), min(h, ih - y)
    return Rect(x=x, y=y, w=w, h=h)


def pick_color(image: np.ndarray, prompt: str) -> HSVRange | None:
    """Click sample pixels; the right pane previews the resulting mask.

    Keys: Enter/Space save, r reset, + / - widen or narrow the range,
    Esc or q skip. Returns ``None`` if skipped.
    """
    _check_gui()
    picker = ColorPicker(image)
    ih, iw = image.shape[:2]
    z = max(1.0, fit_scale(iw * 2, ih, max_zoom=8.0))
    title = f"{prompt}  [click samples, Enter=save, r=reset, +/-=width, Esc=skip]"

    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            px, py = int(x / z), int(y / z)
            if 0 <= px < iw and 0 <= py < ih:
                picker.add(px, py)

    cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
    cv2.setWindowProperty(title, cv2.WND_PROP_TOPMOST, 1)
    cv2.setMouseCallback(title, on_mouse)
    result: HSVRange | None = None
    try:
        while True:
            left = cv2.resize(image, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
            mask = cv2.cvtColor(picker.mask(), cv2.COLOR_GRAY2BGR)
            right = cv2.resize(mask, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
            canvas = np.hstack([left, right])
            rng = picker.range()
            info = (f"samples {len(picker.samples)}  coverage {picker.coverage():.0%}  "
                    f"margins {picker.margins}  "
                    + (f"{list(rng.lower)}..{list(rng.upper)}" if rng else ""))
            cv2.putText(canvas, info, (6, canvas.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, (0, 255, 255), 1, cv2.LINE_AA)
            cv2.imshow(title, canvas)
            k = cv2.waitKey(30) & 0xFF
            if k in (13, 10, 32):
                result = rng
                break
            if k in (27, ord("q")):
                break
            if k == ord("r"):
                picker.reset()
            elif k in (ord("+"), ord("=")):
                picker.widen(+1)
            elif k in (ord("-"), ord("_")):
                picker.widen(-1)
            if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cv2.destroyAllWindows()
    return result
