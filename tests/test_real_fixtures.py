"""Perception checked against your own labeled screenshots (local only, git-ignored).

Layout: tests/fixtures/local/<any_name>/{frame_*.png, labels.json}
Make one: record frames, copy the folder here, then
  mapbot inspect tests/fixtures/local/<name> --map <id> --write-labels
and hand-correct labels.json. Set MAPBOT_FIXTURES to use another folder.
Skipped automatically when no labeled folders exist.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mapbot.capture.grabber import load_image
from mapbot.config import load_map
from mapbot.config.schema import LabelSet
from mapbot.perception.perceiver import Perceiver

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(os.environ.get("MAPBOT_FIXTURES", ROOT / "tests" / "fixtures" / "local"))
LABEL_FILES = sorted(FIXTURES.glob("*/labels.json")) if FIXTURES.is_dir() else []

DOT_TOL_PX = 3
BAR_TOL = 0.03
MIN_MONSTER_RECALL = 0.8
MAX_MONSTER_OVERCOUNT = 1.25


def _resolve_map(labels_dir: Path, ref: str) -> Path:
    for cand in (labels_dir / ref, ROOT / ref, ROOT / "maps" / ref / "map.yaml"):
        if cand.is_file():
            return cand
    pytest.fail(f"{labels_dir}/labels.json: map {ref!r} not found")


@pytest.mark.skipif(not LABEL_FILES, reason=f"no labeled fixtures under {FIXTURES}")
@pytest.mark.parametrize("labels_path", LABEL_FILES, ids=lambda p: p.parent.name)
def test_real_fixture(labels_path: Path) -> None:
    labels = LabelSet.model_validate(json.loads(labels_path.read_text(encoding="utf-8")))
    folder = labels_path.parent
    map_path = _resolve_map(folder, labels.map)
    cfg = load_map(map_path).model
    perceiver = Perceiver.for_map(cfg, map_path, strict=False, smooth_frames=1, alert_every_n=1)

    errors: list[str] = []
    expected_monsters = found_monsters = detected_monsters = 0
    for name, lab in labels.frames.items():
        perceiver.reset()
        p = perceiver.perceive(load_image(folder / name), source=name)
        if lab.player_dot is not None:
            if p.player_minimap is None:
                errors.append(f"{name}: player dot not found (expected {lab.player_dot})")
            elif max(abs(a - b) for a, b in zip(p.player_minimap, lab.player_dot)) > DOT_TOL_PX:
                errors.append(f"{name}: dot {p.player_minimap} vs expected {lab.player_dot}")
        for bar in ("hp", "mp"):
            want, got = getattr(lab, bar), getattr(p, bar)
            if want is not None and (got is None or abs(got - want) > BAR_TOL):
                errors.append(f"{name}: {bar} {got} vs expected {want}")
        if lab.alerts is not None and sorted(p.alerts) != sorted(lab.alerts):
            errors.append(f"{name}: alerts {sorted(p.alerts)} vs expected {sorted(lab.alerts)}")
        if lab.monsters is not None:
            expected_monsters += lab.monsters
            detected_monsters += len(p.monsters)
            found_monsters += min(len(p.monsters), lab.monsters)

    if expected_monsters:
        recall = found_monsters / expected_monsters
        if recall < MIN_MONSTER_RECALL:
            errors.append(f"monster recall {recall:.0%} < {MIN_MONSTER_RECALL:.0%} "
                          f"(lower detection.monster_threshold or add templates)")
        if detected_monsters > expected_monsters * MAX_MONSTER_OVERCOUNT + 1:
            errors.append(f"{detected_monsters} monsters detected vs {expected_monsters} labeled "
                          f"(false positives: raise detection.monster_threshold)")
    assert not errors, "\n".join(errors)
