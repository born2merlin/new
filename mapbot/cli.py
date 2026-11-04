"""Command-line entry point: ``mapbot <command>``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config.loader import ConfigError, detect_kind, load_map, load_profile, load_settings
from .errors import UserError


def _cmd_validate(args: argparse.Namespace) -> int:
    failed = 0
    for raw in args.files:
        path = Path(raw)
        kind = args.kind if args.kind != "auto" else detect_kind(path)
        try:
            if kind == "profile":
                result = load_profile(path, allow_placeholders=not args.strict)
                warnings = result.warnings
            elif kind == "map":
                result = load_map(path, require_calibrated=args.strict)
                warnings = result.warnings
            else:
                load_settings(path)
                warnings = []
        except ConfigError as e:
            failed += 1
            print(f"FAIL  [{kind}] {e}")
            continue
        if warnings:
            print(f"OK    [{kind}] {path} ({len(warnings)} warning(s))")
            for w in warnings:
                print(f"  ! {w}")
        else:
            print(f"OK    [{kind}] {path}")
    if failed:
        print(f"\n{failed} file(s) failed validation.")
    return 1 if failed else 0


def _not_yet(phase: int):
    def run(args: argparse.Namespace) -> int:
        print(f"'{args.command}' is not implemented yet (planned for Phase {phase}).")
        return 2

    return run


def _calibrate_dispatch(args: argparse.Namespace) -> int:
    # Imported lazily so 'validate' works without OpenCV installed.
    from .calibrate import commands

    settings = load_settings(args.settings) if args.settings else None
    if getattr(args, "backend", None) is None:
        args.backend = settings.capture_backend if settings else "dxcam"
    if getattr(args, "fps", None) is None:
        args.fps = settings.capture_fps if settings else 30
    return getattr(commands, f"cmd_{args.calib}")(args)


def _inspect(args: argparse.Namespace) -> int:
    from .inspect_frames import cmd_inspect

    return cmd_inspect(args)


def _add_calibrate(sub) -> None:
    from .calibrate.targets import COLOR_TARGETS, ROI_TARGETS, TEMPLATE_KINDS

    c = sub.add_parser("calibrate", help="calibration helpers for a map and profile")
    csub = c.add_subparsers(dest="calib", required=True)

    def common(sp, *, live: bool = True, image: bool = False, map_required: bool = True):
        sp.add_argument("--map", required=map_required,
                        help="map id (maps/<id>/map.yaml, created if missing) or a map.yaml path")
        if live:
            sp.add_argument("--title", help="game window title (default: map's window_title)")
            sp.add_argument("--backend", choices=["dxcam", "mss"],
                            help="capture backend (default: settings.yaml)")
        if image:
            sp.add_argument("--image", help="calibrate from a saved screenshot instead of live")
            sp.add_argument("--delay", type=float, default=3,
                            help="seconds to wait before a live capture (default 3)")
        sp.set_defaults(func=_calibrate_dispatch)

    w = csub.add_parser("window", help="find the game window, check DPI/capture rate, save a screenshot")
    common(w, map_required=False)
    w.add_argument("--out", help="where to save the screenshot (default maps/<id>/reference.png)")
    w.add_argument("--fps", type=int, help="target capture FPS to compare against")

    r = csub.add_parser("roi", help="drag rectangles for minimap, HP/MP bars and play area")
    common(r, image=True)
    r.add_argument("--only", nargs="+", choices=list(ROI_TARGETS), help="only these ROIs")

    k = csub.add_parser("colors", help="click pixels to set the player-dot and HP/MP fill colors")
    common(k, image=True)
    k.add_argument("--only", nargs="+", choices=list(COLOR_TARGETS), help="only these colors")

    rec = csub.add_parser("record", help="save frames from the live game for offline tests/replay")
    common(rec)
    rec.add_argument("--seconds", type=float, default=30)
    rec.add_argument("--fps", type=float, default=5, help="frames saved per second (default 5)")
    rec.add_argument("--out", help="output folder (default frames/<map>/<timestamp>)")

    t = csub.add_parser("template", help="drag a box to save a monster/loot/name-tag/alert template")
    common(t, image=True)
    t.add_argument("--kind", required=True, choices=TEMPLATE_KINDS,
                   help="monsters | loot | player (your name tag) | alerts (death_*, rune_*, dialog_*)")
    t.add_argument("--name", required=True, help="file name without .png, e.g. orange_mush_1")
    t.add_argument("--force", action="store_true", help="overwrite an existing template")
    t.add_argument("--set-threshold", action="store_true",
                   help="write the suggested threshold (player/alerts only)")

    b = csub.add_parser("bounds", help="set patrol bounds from the minimap dot position")
    common(b, image=True)
    b.add_argument("--set", choices=["left", "right"], help="the edge you are standing at now")
    b.add_argument("--frames", help="folder recorded while walking edge to edge (sets both)")
    b.add_argument("--inset", type=int, default=5, help="minimap px to stay inside each edge (default 5)")

    ch = csub.add_parser("check", help="preview perception live or over saved frames (no input)")
    common(ch)
    ch.add_argument("--frames", help="preview a recorded folder instead of the live game")
    ch.add_argument("--fps", type=float, default=10, help="playback speed for --frames (default 10)")

    for name, phase, helptext in [
        ("keys", 3, "test and set profile keybinds"),
    ]:
        s = csub.add_parser(name, help=f"{helptext} [Phase {phase}]")
        s.add_argument("rest", nargs=argparse.REMAINDER)
        s.set_defaults(func=_not_yet(phase), command=f"calibrate {name}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mapbot", description=__doc__)
    p.add_argument("--settings", default="settings.yaml" if Path("settings.yaml").is_file() else None,
                   help="bot settings file (default: ./settings.yaml if present)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = p.add_subparsers(dest="command", required=True)

    v = sub.add_parser("validate", help="check profile / map / settings YAML files")
    v.add_argument("files", nargs="+", help="YAML files to check")
    v.add_argument(
        "--kind", choices=["auto", "profile", "map", "settings"], default="auto",
        help="file type (default: guess from path)",
    )
    v.add_argument(
        "--strict", action="store_true",
        help="treat TODO keys and missing map calibration as errors (what 'run' uses)",
    )
    v.set_defaults(func=_cmd_validate)

    _add_calibrate(sub)

    i = sub.add_parser("inspect", help="run perception over saved frames; write annotated images")
    i.add_argument("target", help="an image or a folder of frames (e.g. from 'calibrate record')")
    i.add_argument("--map", required=True, help="map id or map.yaml path")
    i.add_argument("--out", help="output folder (default <target>_inspect next to it)")
    i.add_argument("--no-images", action="store_true", help="only write perception.jsonl")
    i.add_argument("--write-labels", action="store_true",
                   help="write a draft labels.json into the frames folder for offline tests")
    i.add_argument("--force", action="store_true", help="overwrite an existing labels.json")
    i.set_defaults(func=_inspect)

    for name, phase, helptext in [
        ("run", 4, "run the bot"),
        ("replay", 5, "run the decision loop over saved frames with no input"),
    ]:
        s = sub.add_parser(name, help=f"{helptext} [Phase {phase}]")
        s.add_argument("rest", nargs=argparse.REMAINDER)
        s.set_defaults(func=_not_yet(phase))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return args.func(args)
    except UserError as e:  # anything else is a bug and keeps its traceback
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
