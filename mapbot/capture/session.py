"""Open a live capture of the game window with the startup checks from the plan."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config.schema import MapConfig
from .grabber import LiveSource, make_grabber
from .window import GameWindow, WindowError, find_window, virtual_screen

log = logging.getLogger(__name__)


class ResolutionMismatch(WindowError):
    pass


def check_resolution(cfg: MapConfig, size: tuple[int, int]) -> None:
    """Refuse to continue if the client size differs from the calibrated one."""
    res = cfg.calibrated_resolution
    if res is None:
        return
    if (res.width, res.height) != tuple(size):
        raise ResolutionMismatch(
            f"the game client area is {size[0]}x{size[1]} but map {cfg.name!r} was calibrated "
            f"at {res.width}x{res.height}. Set the game back to that resolution/window mode, "
            f"or recalibrate with 'mapbot calibrate roi'"
        )


@dataclass
class LiveCapture:
    window: GameWindow
    source: LiveSource

    def close(self) -> None:
        self.source.close()


def open_live(title: str, backend: str, cfg: MapConfig | None = None) -> LiveCapture:
    window = find_window(title)
    region = window.client_region()
    if region.width == 0 or region.height == 0:
        raise WindowError("the game window has an empty client area (still loading?)")
    if not virtual_screen().contains(region):
        log.warning(
            "part of the game client area %s is off-screen; those pixels will be black. "
            "Move the window fully onto a monitor (in windowed 1920x1080 on a 1080p screen, "
            "use borderless instead)", region,
        )
    if cfg is not None:
        check_resolution(cfg, (region.width, region.height))
    return LiveCapture(window, LiveSource(window, make_grabber(backend)))
