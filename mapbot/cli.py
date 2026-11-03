"""Command-line entry point: ``mapbot <command>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config.loader import ConfigError, detect_kind, load_map, load_profile, load_settings


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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mapbot", description=__doc__)
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

    for name, phase, helptext in [
        ("calibrate", 1, "calibration helpers (window, roi, colors, template, bounds, keys, check)"),
        ("run", 4, "run the bot"),
        ("replay", 5, "run the decision loop over saved frames with no input"),
        ("inspect", 2, "annotate saved frames with what perception sees"),
    ]:
        s = sub.add_parser(name, help=f"{helptext} [Phase {phase}]")
        s.add_argument("rest", nargs=argparse.REMAINDER)
        s.set_defaults(func=_not_yet(phase))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
