"""``mapbot inspect``: run perception over saved frames and write what it saw.

Outputs annotated PNGs and ``perception.jsonl``. With ``--write-labels`` it also
writes a draft ``labels.json`` next to the frames for you to hand-correct and
use as an offline test fixture.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from pathlib import Path

from .calibrate.mapfile import resolve_map_path
from .capture.grabber import IMAGE_EXTS, CaptureError, DirectorySource, Frame, load_image, save_image
from .capture.session import check_resolution
from .config.loader import load_map
from .config.schema import FrameLabel, LabelSet
from .debug.annotate import annotate
from .perception.perceiver import Perceiver
from .perception.snapshot import Perception


def label_from(p: Perception) -> FrameLabel:
    return FrameLabel(
        player_dot=None if p.player_minimap is None else tuple(int(round(v)) for v in p.player_minimap),
        hp=None if p.hp is None else round(p.hp, 2),
        mp=None if p.mp is None else round(p.mp, 2),
        monsters=len(p.monsters),
        alerts=sorted(p.alerts),
    )


def _frames(target: Path):
    if target.is_dir():
        src = DirectorySource(target)
        while (f := src.read()) is not None:
            yield f
    elif target.suffix.lower() in IMAGE_EXTS:
        yield Frame(load_image(target), 0.0, 1, source=target.name)
    else:
        raise CaptureError(f"{target} is not an image or a folder of images")


def cmd_inspect(args: argparse.Namespace) -> int:
    target = Path(args.target)
    map_path = resolve_map_path(args.map)
    cfg = load_map(map_path).model
    # No smoothing or alert throttling: each frame's result should reflect that frame alone.
    perceiver = Perceiver.for_map(cfg, map_path, strict=False, smooth_frames=1, alert_every_n=1)
    for prob in perceiver.problems:
        print(f"  ! {prob}")

    base = target if target.is_dir() else target.parent
    out = Path(args.out) if args.out else base.parent / f"{base.name if target.is_dir() else target.stem}_inspect"
    out.mkdir(parents=True, exist_ok=True)

    totals, dots, counts, labels = [], 0, [], {}
    with (out / "perception.jsonl").open("w", encoding="utf-8") as log:
        for frame in _frames(target):
            check_resolution(cfg, frame.size)
            p = perceiver.perceive(frame.image, frame.t, frame.source)
            log.write(json.dumps(p.to_dict()) + "\n")
            if not args.no_images:
                save_image(out / frame.source, annotate(frame.image, p, cfg))
            totals.append(p.timings_ms.get("total", 0.0))
            dots += p.player_minimap is not None
            counts.append(len(p.monsters))
            labels[frame.source] = label_from(p)

    n = len(totals)
    print(f"inspected {n} frame(s) -> {out}")
    print(f"  perception time: median {statistics.median(totals):.0f} ms, max {max(totals):.0f} ms")
    print(f"  player dot found: {dots}/{n}")
    print(f"  monsters per frame: avg {statistics.mean(counts):.1f}, max {max(counts)}")

    if args.write_labels:
        if not target.is_dir():
            raise CaptureError("--write-labels needs a folder of frames")
        lp = target / "labels.json"
        if lp.exists() and not args.force:
            raise CaptureError(f"{lp} already exists (hand-corrected?); pass --force to overwrite")
        try:  # relative, so the fixture folder can move with its map
            map_ref = os.path.relpath(Path(map_path).resolve(), target.resolve())
        except ValueError:  # different drive on Windows
            map_ref = str(Path(map_path).resolve())
        ls = LabelSet(map=map_ref, frames=labels)
        lp.write_text(json.dumps(ls.model_dump(mode="json", exclude_none=True), indent=1), encoding="utf-8")
        print(f"wrote draft labels -> {lp}")
        print("  open the annotated images, fix any wrong values in labels.json, then run pytest")
    return 0
