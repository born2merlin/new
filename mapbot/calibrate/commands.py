"""``mapbot calibrate <subcommand>`` implementations."""

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
from .targets import COLOR_TARGETS, ROI_TARGETS, TEMPLATE_THRESHOLD_FIELD


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


# --------------------------------------------------------------------------
# template
# --------------------------------------------------------------------------

def suggest_single_threshold(scores: list[float]) -> float | None:
    """For one-per-screen templates (name tag, dialogs): midway between the true
    hit (best score) and the strongest other match, clamped to a sane range."""
    if not scores:
        return None
    best = scores[0]
    second = scores[1] if len(scores) > 1 else 0.0
    return round(min(0.95, max(0.6, (best + second) / 2)), 2)


def cmd_template(args: argparse.Namespace) -> int:
    from ..perception.match import best_scores
    from ..perception.templates import ALERT_KINDS, Template, check_template
    from .ui import select_rect

    mf = _open_map(args)
    cfg = mf.model()
    name = args.name
    if args.kind == "alerts" and not name.lower().startswith(ALERT_KINDS):
        print(f"note: alert templates should start with one of {', '.join(ALERT_KINDS)} "
              f"(e.g. death_dialog) so the watchdog knows what they mean")
    out = mf.path.parent / "templates" / args.kind / f"{name}.png"
    if out.exists() and not args.force:
        raise CaptureError(f"{out} already exists; pick another --name or pass --force")

    image = _grab_one(args, cfg)
    check_resolution(cfg, (image.shape[1], image.shape[0]))
    rect = select_rect(image, f"{args.kind}: {name}")
    if rect is None:
        print("cancelled")
        return 0
    sprite = np.ascontiguousarray(crop(image, rect))
    check_template(sprite, out)
    save_image(out, sprite)
    print(f"saved {args.kind} template {out} ({rect.w}x{rect.h})")

    # Score the new template against the same frame to help pick a threshold.
    det = cfg.detection
    region = cfg.rois.play_area if args.kind != "alerts" else None
    search = crop(image, region) if region is not None else image
    scale = det.alert_scale if args.kind == "alerts" else det.match_scale
    scores = best_scores(search, Template(name, args.kind, sprite), scale, n=8)
    field = TEMPLATE_THRESHOLD_FIELD[args.kind]
    current = getattr(det, field)
    print(f"top match scores in this frame: {', '.join(f'{v:.2f}' for v in scores)}")
    print(f"current detection.{field} = {current:.2f} -> "
          f"{sum(v >= current for v in scores)} hit(s) in this frame")
    if args.kind in ("player", "alerts"):
        sug = suggest_single_threshold(scores)
        print(f"suggested detection.{field}: {sug:.2f} (only one should be on screen)")
        if args.set_threshold and sug is not None:
            mf.set(("detection", field), sug)
            mf.save()
            print(f"wrote detection.{field} = {sug:.2f}")
    else:
        print("count how many of these are real (several monsters/drops may be on screen), "
              f"then tune detection.{field} with 'mapbot calibrate check'")
        if args.kind == "monsters":
            print("tip: capture 2-3 templates per monster (different animation frames); "
                  "mirrored copies are added automatically")
    return 0


# --------------------------------------------------------------------------
# bounds
# --------------------------------------------------------------------------

def cmd_bounds(args: argparse.Namespace) -> int:
    from ..capture.grabber import DirectorySource
    from ..config.schema import PatrolBounds
    from ..perception.detectors import find_player_dot

    mf = _open_map(args)
    cfg = mf.model()
    if cfg.rois.minimap is None or cfg.colors.player_dot is None:
        raise CaptureError(
            f"set the minimap ROI and player_dot color first "
            f"('mapbot calibrate roi' / 'colors' --map {args.map})"
        )
    mm, color = cfg.rois.minimap, cfg.colors.player_dot

    if args.frames:
        src = DirectorySource(args.frames)
        xs, total = [], 0
        while (f := src.read()) is not None:
            total += 1
            check_resolution(cfg, f.size)
            dot = find_player_dot(f.image, mm, color)
            if dot is not None:
                xs.append(dot[0])
        if len(xs) < 2:
            raise CaptureError(f"the player dot was found in only {len(xs)} of {total} frames; "
                               f"check the player_dot color with 'calibrate check'")
        left, right = int(min(xs)) + args.inset, int(max(xs)) - args.inset
        print(f"dot found in {len(xs)}/{total} frames; x range {min(xs):.0f}..{max(xs):.0f}, "
              f"inset {args.inset}")
    else:
        if args.set is None:
            raise CaptureError("pass --set left / --set right (standing at that edge), or --frames DIR")
        image = _grab_one(args, cfg)
        check_resolution(cfg, (image.shape[1], image.shape[0]))
        dot = find_player_dot(image, mm, color)
        if dot is None:
            raise CaptureError("the player dot was not found on the minimap in this frame")
        x = int(round(dot[0]))
        current = cfg.patrol or PatrolBounds(left_x=0, right_x=mm.w - 1)
        left, right = current.left_x, current.right_x
        if args.set == "left":
            left = x + args.inset
        else:
            right = x - args.inset
        print(f"dot at minimap x={x}; {args.set} edge -> {left if args.set == 'left' else right}")
        if cfg.patrol is None:
            other = "right" if args.set == "left" else "left"
            print(f"now stand at the {other} edge and run with --set {other}")

    if left >= right:
        raise CaptureError(f"left ({left}) must be < right ({right}); patrol area too narrow "
                           f"for inset {args.inset}?")
    mf.set(("patrol",), PatrolBounds(left_x=left, right_x=right))
    mf.save()
    print(f"saved patrol bounds left_x={left} right_x={right} to {mf.path}")
    return 0


# --------------------------------------------------------------------------
# check (live / folder preview, no input)
# --------------------------------------------------------------------------

def cmd_check(args: argparse.Namespace) -> int:
    import cv2

    from ..capture.grabber import DirectorySource
    from ..debug.annotate import annotate
    from ..perception.perceiver import Perceiver
    from .ui import _check_gui, fit_scale

    mf = _open_map(args)
    cfg = mf.model()
    perceiver = Perceiver.for_map(cfg, mf.path, strict=False)
    for prob in perceiver.problems:
        print(f"  ! {prob}")
    _check_gui()

    live = None
    if args.frames:
        source = DirectorySource(args.frames)
        delay = max(1, int(1000 / args.fps))
    else:
        live = open_live(_title(args, cfg), args.backend, cfg)
        source, delay = live.source, 1
    title = "mapbot check  [q=quit, space=pause, s=save]  (no input is sent)"
    paused, frame, shown, t_last = False, None, None, time.monotonic()
    print("previewing; no keys are sent to the game")
    try:
        while True:
            if not paused or frame is None:
                frame = source.read()
                if frame is None:
                    print("end of frames")
                    break
                check_resolution(cfg, frame.size)
                p = perceiver.perceive(frame.image, frame.t, frame.source)
                now = time.monotonic()
                fps = 1.0 / max(1e-6, now - t_last)
                t_last = now
                shown = annotate(frame.image, p, cfg, extra_lines=[f"{fps:.1f} FPS  {frame.source}"])
                s = fit_scale(shown.shape[1], shown.shape[0])
                if s < 1:
                    shown = cv2.resize(shown, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            cv2.imshow(title, shown)
            k = cv2.waitKey(delay) & 0xFF
            if k in (ord("q"), 27):
                break
            if k == ord(" "):
                paused = not paused
            if k == ord("s"):
                out = mf.path.parent / f"check_{datetime.now():%Y%m%d_%H%M%S}.png"
                save_image(out, frame.image)
                print(f"saved frame -> {out}")
            if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cv2.destroyAllWindows()
        if live:
            live.close()
    return 0
