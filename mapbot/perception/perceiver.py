"""Turn a frame into a ``Perception`` snapshot using one map's calibration."""

from __future__ import annotations

import logging
import statistics
import time
from collections import deque
from pathlib import Path

import numpy as np

from ..config.schema import MapConfig, MonsterDetector
from ..errors import UserError
from . import detectors as d
from .snapshot import Perception
from .templates import TemplateSet

log = logging.getLogger(__name__)


class NotCalibrated(UserError):
    pass


class Perceiver:
    """Runs every detector on a frame.

    The only state is a short median filter on HP/MP, which hides one-frame
    glitches (damage numbers or effects drawn over the bars).
    """

    def __init__(self, cfg: MapConfig, templates: TemplateSet, *, strict: bool = True,
                 smooth_frames: int = 3, alert_every_n: int | None = None) -> None:
        """``alert_every_n`` overrides the map setting; use 1 for unrelated saved frames."""
        self.cfg = cfg
        self.templates = templates
        self.alert_every_n = alert_every_n or cfg.detection.alert_every_n
        self.problems = self._check()
        if strict and self.problems:
            raise NotCalibrated(
                f"map {cfg.name!r} is not ready for perception:\n  - " + "\n  - ".join(self.problems)
            )
        for p in self.problems:
            log.warning("perception: %s", p)
        self._hp: deque[float] = deque(maxlen=smooth_frames)
        self._mp: deque[float] = deque(maxlen=smooth_frames)
        self._last_tag = None
        self._alerts: set[str] = set()
        self._n = 0

    @classmethod
    def for_map(cls, cfg: MapConfig, map_path: str | Path, **kw) -> "Perceiver":
        return cls(cfg, TemplateSet.load(Path(map_path).parent), **kw)

    def _check(self) -> list[str]:
        c, out = self.cfg, []
        hint = "mapbot calibrate"
        for roi in ("minimap", "hp_bar", "mp_bar", "play_area"):
            if getattr(c.rois, roi) is None:
                out.append(f"rois.{roi} not set ({hint} roi)")
        for col in ("player_dot", "hp_fill", "mp_fill"):
            if getattr(c.colors, col) is None:
                out.append(f"colors.{col} not set ({hint} colors)")
        if c.detection.monster_detector is MonsterDetector.template and not self.templates["monsters"]:
            out.append(f"no monster templates ({hint} template --kind monsters)")
        if not self.templates["player"]:
            out.append(f"no name-tag template, so distance to monsters is unknown "
                       f"({hint} template --kind player)")
        return out

    def reset(self) -> None:
        """Forget smoothing/tracking state (call when frames are not consecutive)."""
        self._hp.clear()
        self._mp.clear()
        self._last_tag = None
        self._alerts = set()
        self._n = 0

    def perceive(self, frame: np.ndarray, t: float | None = None, source: str = "") -> Perception:
        c, det, tpl = self.cfg, self.cfg.detection, self.templates
        h, w = frame.shape[:2]
        p = Perception(t=time.monotonic() if t is None else t, frame_size=(w, h), source=source)
        timings = p.timings_ms

        def timed(name, fn):
            t0 = time.perf_counter()
            try:
                return fn()
            finally:
                timings[name] = (time.perf_counter() - t0) * 1000

        if c.rois.minimap and c.colors.player_dot:
            p.player_minimap = timed("minimap", lambda: d.find_player_dot(frame, c.rois.minimap, c.colors.player_dot))
        if c.rois.hp_bar and c.colors.hp_fill:
            p.hp = self._smooth(self._hp, timed("hp", lambda: d.read_bar(frame, c.rois.hp_bar, c.colors.hp_fill, det.bar_column_fill)))
        if c.rois.mp_bar and c.colors.mp_fill:
            p.mp = self._smooth(self._mp, timed("mp", lambda: d.read_bar(frame, c.rois.mp_bar, c.colors.mp_fill, det.bar_column_fill)))

        if c.rois.play_area is not None:
            area = d.Region(frame, c.rois.play_area)
            p.nametag = timed("nametag", lambda: d.find_nametag(
                frame, area, tpl["player"], det, c.rois.play_area, self._last_tag))
            self._last_tag = p.nametag
            if p.nametag is not None:
                p.player_screen = d.player_anchor(p.nametag, det)
            if det.monster_detector is MonsterDetector.color and det.monster_color is not None:
                ms = timed("monsters", lambda: d.find_monsters_color(area, det))
            else:
                ms = timed("monsters", lambda: d.find_monsters_template(area, tpl["monsters"], det))
            if p.nametag is not None:
                ms = [m for m in ms if not p.nametag.contains(m.cx, m.cy)]
            p.monsters = ms
            p.loot = timed("loot", lambda: d.find_loot(area, tpl["loot"], det))
        if tpl["alerts"]:
            # Alerts persist between checks; a dialog stays up for many frames.
            if self._n % self.alert_every_n == 0:
                self._alerts = timed("alerts", lambda: d.find_alerts(frame, tpl["alerts"], det))
            p.alerts = set(self._alerts)
        self._n += 1
        timings["total"] = sum(timings.values())
        return p

    @staticmethod
    def _smooth(buf: deque[float], value: float) -> float:
        buf.append(value)
        return statistics.median(buf)
