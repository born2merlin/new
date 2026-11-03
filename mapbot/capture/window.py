"""Find the game window and its client area (Windows only, via ctypes).

All coordinates are physical pixels. ``enable_dpi_awareness()`` must run
before any other window call, otherwise Windows display scaling (125%, 150%)
reports scaled-down coordinates and every ROI would be off.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass

from ..errors import UserError
from ..vision.geometry import ScreenRegion

IS_WINDOWS = sys.platform == "win32"


class WindowError(UserError):
    """User-facing problem finding or using the game window."""


def _require_windows() -> None:
    if not IS_WINDOWS:
        raise WindowError(
            "window detection only works on Windows (the game client runs there); "
            "use --image to calibrate from a saved screenshot instead"
        )


_dpi_done = False


def enable_dpi_awareness() -> str:
    """Make this process per-monitor DPI aware. Returns the mode that worked."""
    global _dpi_done
    if not IS_WINDOWS:
        return "n/a"
    if _dpi_done:
        return "already set"
    _dpi_done = True
    user32 = ctypes.windll.user32
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == -4 (Win10 1703+)
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "per-monitor v2"
    except AttributeError:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return "per-monitor"
    except (AttributeError, OSError):
        pass
    user32.SetProcessDPIAware()
    return "system"


@dataclass(frozen=True)
class GameWindow:
    hwnd: int
    title: str

    # ---- geometry ----------------------------------------------------------

    def client_region(self) -> ScreenRegion:
        """Client area (no title bar / borders) in absolute screen pixels."""
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        if not user32.IsWindow(self.hwnd):
            raise WindowError("the game window was closed")
        if user32.IsIconic(self.hwnd):
            raise WindowError("the game window is minimized; restore it first")
        rect = wintypes.RECT()
        if not user32.GetClientRect(self.hwnd, ctypes.byref(rect)):
            raise WindowError("GetClientRect failed for the game window")
        origin = wintypes.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(origin))
        return ScreenRegion(origin.x, origin.y, rect.right - rect.left, rect.bottom - rect.top)

    def dpi_scale(self) -> float:
        """Windows display scaling of the window's monitor (1.0 = 100%)."""
        try:
            return ctypes.windll.user32.GetDpiForWindow(self.hwnd) / 96.0
        except AttributeError:
            return 1.0

    # ---- state -------------------------------------------------------------

    def is_foreground(self) -> bool:
        return int(ctypes.windll.user32.GetForegroundWindow() or 0) == self.hwnd

    def exists(self) -> bool:
        return bool(ctypes.windll.user32.IsWindow(self.hwnd))


def virtual_screen() -> ScreenRegion:
    """Bounding box of all monitors."""
    _require_windows()
    gsm = ctypes.windll.user32.GetSystemMetrics
    # SM_XVIRTUALSCREEN=76, SM_YVIRTUALSCREEN=77, SM_CXVIRTUALSCREEN=78, SM_CYVIRTUALSCREEN=79
    return ScreenRegion(gsm(76), gsm(77), gsm(78), gsm(79))


def list_windows() -> list[tuple[int, str]]:
    """All visible top-level windows with a title: ``[(hwnd, title), ...]``."""
    _require_windows()
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                found.append((int(hwnd), buf.value))
        return True

    user32.EnumWindows(_cb, 0)
    return found


def choose_window(candidates: list[tuple[int, str]], title: str) -> tuple[int, str]:
    """Pick the game window: an exact title match wins, else a unique substring match.

    Kept free of Windows calls so it can be unit tested.
    """
    exact = [c for c in candidates if c[1] == title]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise WindowError(
            f"{len(exact)} windows are titled {title!r}; close the extra game clients"
        )
    partial = [c for c in candidates if title.lower() in c[1].lower()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise WindowError(
            f"no window titled {title!r} found. Is the game running and not minimized? "
            f"If the title differs, set window_title in map.yaml"
        )
    names = ", ".join(repr(c[1]) for c in partial[:5])
    raise WindowError(
        f"several windows contain {title!r} ({names}); set the exact window_title in map.yaml"
    )


def find_window(title: str = "MapleStory") -> GameWindow:
    _require_windows()
    enable_dpi_awareness()
    hwnd, name = choose_window(list_windows(), title)
    return GameWindow(hwnd, name)
