"""``mapbot calibrate <subcommand>`` implementations (Phase 1: window, roi, colors, record)."""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from ..capture.grabber import CaptureError, is_black, load_image, save_image
from ..capture.recorder import record as record_frames
from ..capture.session import check_resolution, open_live
from ..capture.window import WindowError
from ..config.schema import MapConfig, Resolution
from ..vision.color import hsv_mask, to_hsv
from ..vision.geometry import crop
from .mapfile import MapFile, resolve_map_path

from .targets import COLOR_TARGETS, ROI_TARGETS


def _open_map(args: argparse.Namespace) -> MapFile:
    path = resolve_map_path(args.map)
    existed = path.exists()
    mf = MapFile.open_or_create(path)
    if not existed:
        print(f"created {path} (and its templates/ folders) from the template")
    return mf


def _title(args: argparse.Namespace, cfg: MapConfig | None) -> str:
    if getattr(args, "title", None):
        return args.title
    return cfg.window_title if cfg else "MapleStory"


def _grab_one(args: argparse.Namespace, cfg: MapConfig | None) -> np.ndarray:
    """One client-area frame: from --image, or live after a short countdown."""
    if getattr(args, "image", None):
        img = load_image(args.image)
        print(f"using saved image {args.image} ({img.shape[1]}x{img.shape[0]})")
        return img
    live = open_live(_title(args, cfg), args.backend)
    try:
        for s in range(int(args.delay), 0, -1):
            print(f"capturing in {s}... (make sure the game window is visible and uncovered)")
            time.sleep(1)
        frame = live.source.read()
    finally:
        live.close()
    if is_black(frame.image):
        raise CaptureError(
            "the captured frame is black. The window may be covered or minimized, or the "
            "game may block this capture method; try --backend mss"
        )
    return frame.image


def _guard_resolution(mf: MapFile, cfg: MapConfig, size: tuple[int, int], redo_all: bool) -> None:
    res = cfg.calibrated_resolution
    if res is None or (res.width, res.height) == size:
        return
    if not redo_all:
        raise CaptureError(
            f"this frame is {size[0]}x{size[1]} but the map was calibrated at "
            f"{res.width}x{res.height}. Recalibrate every ROI (run 'roi' without --only), "
            f"or switch the game back to {res.width}x{res.height}"
        )
    print(f"note: resolution changed {res.width}x{res.height} -> {size[0]}x{size[1]}; "
          f"all ROIs are being recalibrated")


# --------------------------------------------------------------------------
# window
# --------------------------------------------------------------------------

def cmd_window(args: argparse.Namespace) -> int:
    from ..capture.window import enable_dpi_awareness

    mf = _open_map(args) if args.map else None
    cfg = mf.model() if mf else None
    dpi_mode = enable_dpi_awareness()
    live = open_live(_title(args, cfg), args.backend)
    try:
        win, src = live.window, live.source
        region = win.client_region()
        print(f"window      : {win.title!r} (hwnd {win.hwnd})")
        print(f"client area : {region.width}x{region.height} at screen ({region.left}, {region.top})")
        print(f"DPI         : scale {win.dpi_scale():.2f} (process awareness: {dpi_mode})")
        print(f"foreground  : {win.is_foreground()}")
        print(f"backend     : {src.grabber.name}")

        frames, t0 = 0, time.monotonic()
        frame = src.read()
        while time.monotonic() - t0 < 1.0:
            frame = src.read()
            frames += 1
        fps = frames / (time.monotonic() - t0)
        print(f"capture rate: {fps:.1f} FPS (target {args.fps})")
        if fps < args.fps * 0.8:
            print("  ! capture is slower than the target; the bot will run its loop slower")
        if is_black(frame.image):
            print("  ! the captured frame is BLACK: the window is covered, or the game blocks "
                  "this capture method (try --backend mss)")

        out = Path(args.out) if args.out else (mf.path.parent / "reference.png" if mf else Path("reference.png"))
        save_image(out, frame.image)
        print(f"saved reference screenshot -> {out}")
    finally:
        live.close()

    if mf:
        size = (region.width, region.height)
        if cfg.calibrated_resolution is None:
            mf.set(("calibrated_resolution",), Resolution(width=size[0], height=size[1]))
            mf.set(("window_title",), win.title)
            mf.save()
            print(f"recorded calibrated_resolution {size[0]}x{size[1]} in {mf.path}")
        else:
            try:
                check_resolution(cfg, size)
                print(f"resolution matches the map's calibration ({size[0]}x{size[1]})")
            except WindowError as e:
                print(f"  ! {e}")
    return 0


# --------------------------------------------------------------------------
# roi
# --------------------------------------------------------------------------

def cmd_roi(args: argparse.Namespace) -> int:
    from .ui import select_rect

    mf = _open_map(args)
    cfg = mf.model()
    targets = args.only or list(ROI_TARGETS)
    image = _grab_one(args, cfg)
    size = (image.shape[1], image.shape[0])
    _guard_resolution(mf, cfg, size, redo_all=set(targets) == set(ROI_TARGETS))

    changed = []
    for t in targets:
        print(f"\n[{t}] {ROI_TARGETS[t]}")
        rect = select_rect(image, t)
        if rect is None:
            print(f"  skipped {t}")
            continue
        mf.set(("rois", t), rect)
        changed.append(t)
        print(f"  {t}: x={rect.x} y={rect.y} w={rect.w} h={rect.h}")

    if not changed:
        print("nothing changed")
        return 0
    mf.set(("calibrated_resolution",), Resolution(width=size[0], height=size[1]))
    mf.save()
    save_image(mf.path.parent / "calib_roi.png", image)
    print(f"\nsaved {', '.join(changed)} to {mf.path}")
    return 0


# --------------------------------------------------------------------------
# colors
# --------------------------------------------------------------------------

def cmd_colors(args: argparse.Namespace) -> int:
    from .ui import pick_color

    mf = _open_map(args)
    cfg = mf.model()
    targets = args.only or list(COLOR_TARGETS)
    missing = [COLOR_TARGETS[t][0] for t in targets if getattr(cfg.rois, COLOR_TARGETS[t][0]) is None]
    if missing:
        raise CaptureError(
            f"set these ROIs first with 'mapbot calibrate roi --map {args.map}': "
            f"{', '.join(sorted(set(missing)))}"
        )
    image = _grab_one(args, cfg)
    check_resolution(cfg, (image.shape[1], image.shape[0]))

    changed = []
    for t in targets:
        roi_name, hint = COLOR_TARGETS[t]
        region = crop(image, getattr(cfg.rois, roi_name))
        print(f"\n[{t}] {hint}")
        rng = pick_color(region, t)
        if rng is None:
            print(f"  skipped {t}")
            continue
        cover = float(np.count_nonzero(hsv_mask(to_hsv(region), rng))) / (region.shape[0] * region.shape[1])
        mf.set(("colors", t), rng)
        changed.append(t)
        print(f"  {t}: lower={list(rng.lower)} upper={list(rng.upper)}  covers {cover:.0%} of {roi_name}")
        if t != "player_dot" and cover < 0.6:
            print("  ! low coverage; were you at full HP/MP? Re-run and click more of the bar")
        if t == "player_dot" and cover > 0.05:
            print("  ! the dot color also matches lots of the minimap; try narrowing (-) next time")

    if changed:
        mf.save()
        print(f"\nsaved {', '.join(changed)} to {mf.path}")
    return 0


# --------------------------------------------------------------------------
# record
# --------------------------------------------------------------------------

def cmd_record(args: argparse.Namespace) -> int:
    mf = _open_map(args)
    cfg = mf.model()
    out = Path(args.out) if args.out else Path("frames") / mf.path.parent.name / datetime.now().strftime("%Y%m%d_%H%M%S")
    live = open_live(_title(args, cfg), args.backend, cfg)
    try:
        print(f"recording {args.seconds:g}s at {args.fps:g} FPS -> {out}  (Ctrl+C to stop early)")
        try:
            n = record_frames(live.source, out, seconds=args.seconds, fps=args.fps)
        except KeyboardInterrupt:
            n = sum(1 for _ in out.glob("frame_*.png"))
            print("stopped early")
    finally:
        live.close()
    print(f"saved {n} frames to {out}")
    return 0
