"""Save frames to disk for offline fixtures and replay (``--save-frames``)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

from .grabber import Frame, FrameSource, is_black, save_image

log = logging.getLogger(__name__)


class FrameRecorder:
    """Writes ``frame_00001.png`` ... plus ``index.jsonl`` (file, t) to a folder.

    ``every_s`` throttles saving so a 30 FPS capture doesn't fill the disk;
    ``t`` in the index is seconds since the first saved frame.
    """

    def __init__(self, out_dir: str | Path, every_s: float = 0.2) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.every_s = every_s
        self.count = 0
        self._t0: float | None = None
        self._last: float | None = None
        self._index = (self.out_dir / "index.jsonl").open("a", encoding="utf-8")

    def offer(self, frame: Frame) -> bool:
        """Save ``frame`` if enough time has passed since the last save."""
        if self._last is not None and frame.t - self._last < self.every_s - 1e-6:
            return False
        if self._t0 is None:
            self._t0 = frame.t
        self._last = frame.t
        self.count += 1
        name = f"frame_{self.count:05d}.png"
        save_image(self.out_dir / name, frame.image)
        self._index.write(json.dumps({"file": name, "t": round(frame.t - self._t0, 3)}) + "\n")
        self._index.flush()
        return True

    def close(self) -> None:
        self._index.close()


def record(
    source: FrameSource,
    out_dir: str | Path,
    *,
    seconds: float,
    fps: float = 5.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Record ``seconds`` of frames at ``fps``. Returns the number saved."""
    rec = FrameRecorder(out_dir, every_s=1.0 / fps)
    end = clock() + seconds
    black = 0
    try:
        while clock() < end:
            frame = source.read()
            if frame is None:
                break
            if is_black(frame.image):
                black += 1
            rec.offer(frame)
            sleep(max(0.0, rec.every_s / 2))
    finally:
        rec.close()
    if black:
        log.warning(
            "%d captured frame(s) were black; the game may be blocking capture "
            "or the window is covered", black,
        )
    return rec.count
