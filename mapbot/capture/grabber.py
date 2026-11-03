"""Screen grabbing backends and frame sources.

A *grabber* copies an absolute screen region into a BGR numpy array.
A *frame source* produces client-area frames: either live from the game
window or from a folder of saved screenshots (for offline work and tests).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from ..errors import UserError
from ..vision.geometry import ScreenRegion

log = logging.getLogger(__name__)

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")


class CaptureError(UserError):
    """User-facing capture failure."""


@dataclass
class Frame:
    image: np.ndarray  # BGR, client area only
    t: float           # time.monotonic() when captured (or recorded offset)
    index: int
    source: str = ""   # file name for offline frames

    @property
    def size(self) -> tuple[int, int]:
        h, w = self.image.shape[:2]
        return w, h


def is_black(image: np.ndarray, threshold: float = 3.0) -> bool:
    """True if the frame is (almost) uniformly black, e.g. capture was blocked."""
    return image.size == 0 or float(image.mean()) < threshold


# --------------------------------------------------------------------------
# Grabbers
# --------------------------------------------------------------------------

class Grabber(Protocol):
    name: str

    def grab(self, region: ScreenRegion) -> np.ndarray: ...
    def close(self) -> None: ...


class MssGrabber:
    name = "mss"

    def __init__(self) -> None:
        try:
            import mss
        except ImportError as e:  # pragma: no cover - depends on install
            raise CaptureError("mss is not installed: pip install mss") from e
        self._sct = mss.mss()

    def grab(self, region: ScreenRegion) -> np.ndarray:
        shot = self._sct.grab(
            {"left": region.left, "top": region.top, "width": region.width, "height": region.height}
        )
        return np.ascontiguousarray(np.asarray(shot)[:, :, :3])  # BGRA -> BGR

    def close(self) -> None:
        self._sct.close()


class DxcamGrabber:
    """Desktop Duplication capture on the primary monitor (fastest on Windows)."""

    name = "dxcam"

    def __init__(self) -> None:
        try:
            import dxcam
        except ImportError as e:  # pragma: no cover - Windows only
            raise CaptureError("dxcam is not installed: pip install dxcam") from e
        cam = dxcam.create(output_idx=0, output_color="BGR")
        if cam is None:
            raise CaptureError("dxcam could not open the primary monitor")
        self._cam = cam
        self._screen = ScreenRegion(0, 0, cam.width, cam.height)
        self._last: np.ndarray | None = None
        self._last_region: ScreenRegion | None = None

    def grab(self, region: ScreenRegion) -> np.ndarray:
        if not self._screen.contains(region):
            raise CaptureError(
                f"the game client area {region} is not fully on the primary monitor "
                f"{self._screen}; move the window onto it, or use capture_backend: mss"
            )
        img = self._cam.grab(region=(region.left, region.top, region.right, region.bottom))
        # dxcam returns None when the screen has not changed since the last grab.
        if img is None:
            if self._last is not None and self._last_region == region:
                return self._last
            for _ in range(20):
                time.sleep(0.01)
                img = self._cam.grab(region=(region.left, region.top, region.right, region.bottom))
                if img is not None:
                    break
            else:
                raise CaptureError("dxcam returned no frame; try capture_backend: mss")
        self._last, self._last_region = img, region
        return img

    def close(self) -> None:
        try:
            self._cam.release()
        except Exception:  # pragma: no cover
            pass


def make_grabber(backend: str = "dxcam") -> Grabber:
    """Create the requested backend, falling back to mss if dxcam is unavailable."""
    if backend == "dxcam":
        try:
            return DxcamGrabber()
        except CaptureError as e:
            log.warning("dxcam unavailable (%s); falling back to mss", e)
    return MssGrabber()


# --------------------------------------------------------------------------
# Frame sources
# --------------------------------------------------------------------------

class FrameSource(Protocol):
    def read(self) -> Frame | None: ...
    def close(self) -> None: ...


class LiveSource:
    """Frames of the game window's client area.

    The client rect is re-read each frame, so moving the window is fine.
    If the dxcam backend fails mid-run (e.g. window dragged to another
    monitor), it switches to mss once and logs why.
    """

    def __init__(self, window, grabber: Grabber) -> None:
        self.window = window
        self.grabber = grabber
        self._i = 0

    def read(self) -> Frame:
        region = self.window.client_region()
        try:
            img = self.grabber.grab(region)
        except CaptureError as e:
            if self.grabber.name == "mss":
                raise
            log.warning("%s; switching to mss", e)
            self.grabber.close()
            self.grabber = MssGrabber()
            img = self.grabber.grab(region)
        self._i += 1
        return Frame(img, time.monotonic(), self._i)

    def close(self) -> None:
        self.grabber.close()


class DirectorySource:
    """Frames from saved images, in file-name order.

    If the folder has an ``index.jsonl`` written by the recorder, its
    timestamps are used, so replays keep the original timing.
    """

    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)
        if not self.folder.is_dir():
            raise CaptureError(f"frames folder not found: {self.folder}")
        self.files = sorted(p for p in self.folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)
        if not self.files:
            raise CaptureError(f"no images in {self.folder}")
        self._times: dict[str, float] = {}
        idx = self.folder / "index.jsonl"
        if idx.is_file():
            for line in idx.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._times[rec["file"]] = float(rec["t"])
        self._i = 0

    def __len__(self) -> int:
        return len(self.files)

    def read(self) -> Frame | None:
        if self._i >= len(self.files):
            return None
        path = self.files[self._i]
        self._i += 1
        img = load_image(path)
        t = self._times.get(path.name, float(self._i - 1))
        return Frame(img, t, self._i, source=path.name)

    def close(self) -> None:
        pass


def load_image(path: str | Path) -> np.ndarray:
    import cv2

    # imdecode handles non-ASCII Windows paths, unlike imread.
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise CaptureError(f"could not read image: {path}")
    return img


def save_image(path: str | Path, image: np.ndarray) -> None:
    import cv2

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(p.suffix or ".png", image)
    if not ok:
        raise CaptureError(f"could not encode image: {p}")
    buf.tofile(str(p))
