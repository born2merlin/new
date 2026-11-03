"""Phase 1 tests: color math, geometry, window selection, frame IO, map editing, calibrate CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

import synth
from mapbot.calibrate import ui
from mapbot.calibrate.mapfile import MapFile, resolve_map_path
from mapbot.capture.grabber import DirectorySource, Frame, is_black, load_image, save_image
from mapbot.capture.recorder import FrameRecorder, record
from mapbot.capture.session import ResolutionMismatch, check_resolution
from mapbot.capture.window import WindowError, choose_window
from mapbot.cli import main
from mapbot.config import ConfigError, load_map
from mapbot.config.schema import HSVRange, MapConfig, Rect
from mapbot.vision.color import hsv_mask, suggest_range, to_hsv
from mapbot.vision.geometry import ScreenRegion, crop


def bgr_hsv(bgr) -> tuple[int, int, int]:
    return tuple(int(v) for v in to_hsv(np.array([[bgr]], np.uint8))[0, 0])


# ---- color ----------------------------------------------------------------

def test_suggest_range_simple_hue() -> None:
    y = bgr_hsv(synth.YELLOW)
    rng = suggest_range([y])
    assert rng.lower[0] <= y[0] <= rng.upper[0]
    assert not rng.hue_wraps


def test_suggest_range_wraps_for_red() -> None:
    rng = suggest_range([(176, 200, 200), (178, 210, 220), (2, 200, 210)], hue_margin=3)
    assert rng.hue_wraps
    assert rng.lower[0] == 173 and rng.upper[0] == 5
    hsv = np.array([[[177, 205, 205], [1, 205, 205], [60, 205, 205]]], np.uint8)
    assert list(hsv_mask(hsv, rng)[0]) == [255, 255, 0]


def test_suggest_range_wide_spread_is_full_hue() -> None:
    # Hues 0/60/120 fit in a 120-wide arc, so the range stays partial...
    rng = suggest_range([(0, 100, 100), (60, 100, 100), (120, 100, 100)])
    assert (rng.lower[0], rng.upper[0]) == (174, 126)  # margin wraps below 0
    # ...but samples spread all around the circle cover every hue.
    rng = suggest_range([(h, 100, 100) for h in (0, 40, 80, 120, 160)], hue_margin=20)
    assert (rng.lower[0], rng.upper[0]) == (0, 179)


def test_hsv_schema_allows_hue_wrap_only() -> None:
    HSVRange(lower=(170, 10, 10), upper=(5, 255, 255))
    with pytest.raises(ValueError, match="only hue may wrap"):
        HSVRange(lower=(10, 200, 10), upper=(20, 100, 255))
    with pytest.raises(ValueError, match="out of range"):
        HSVRange(lower=(0, 0, 0), upper=(200, 255, 255))


def test_color_picker_on_synthetic_hp_bar() -> None:
    img = synth.frame(hp=1.0)
    x, y, w, h = synth.HP_BAR
    bar = img[y:y + h, x:x + w]
    p = ui.ColorPicker(bar)
    assert p.range() is None and p.coverage() == 0
    p.add(5, 1)   # darker-red top stripe
    p.add(50, 8)  # main red
    assert p.range().hue_wraps
    assert p.coverage() == pytest.approx(1.0)
    half = synth.frame(hp=0.5)[y:y + h, x:x + w]
    assert float(np.count_nonzero(hsv_mask(to_hsv(half), p.range()))) / half[..., 0].size == pytest.approx(0.5, abs=0.02)
    before = list(p.margins)
    p.widen(+1)
    assert p.margins == [before[0] + 1, before[1] + 10, before[2] + 10]
    p.reset()
    assert p.range() is None


# ---- geometry / ui math ---------------------------------------------------

def test_crop_and_bounds() -> None:
    img = np.zeros((100, 200, 3), np.uint8)
    assert crop(img, Rect(x=10, y=20, w=30, h=40)).shape == (40, 30, 3)
    with pytest.raises(ValueError, match="outside the 200x100 frame"):
        crop(img, Rect(x=190, y=0, w=20, h=10))


def test_screen_region_contains() -> None:
    screen = ScreenRegion(0, 0, 1920, 1080)
    assert screen.contains(ScreenRegion(0, 0, 1920, 1080))
    assert not screen.contains(ScreenRegion(0, 31, 1920, 1080))  # windowed 1080p w/ title bar


def test_display_mapping_roundtrip() -> None:
    s = ui.fit_scale(1920, 1080)
    assert s == pytest.approx(1600 / 1920)
    disp = (int(10 * s), int(40 * s), int(220 * s), int(140 * s))
    x, y, w, h = ui.display_to_image(disp, s)
    assert abs(x - 10) <= 2 and abs(w - 220) <= 2
    # refine pass: crop offset + zoom
    assert ui.display_to_image((60, 60, 300, 120), 3.0, offset=(100, 200)) == (120, 220, 100, 40)
    assert ui.padded_crop_box((5, 5, 10, 10), 100, 100, pad=40) == (0, 0, 55, 55)


# ---- window selection -----------------------------------------------------

def test_choose_window() -> None:
    wins = [(1, "MapleStory"), (2, "MapleStory Wiki - Chrome"), (3, "Discord")]
    assert choose_window(wins, "MapleStory") == (1, "MapleStory")
    assert choose_window([(2, "MapleStory Wiki - Chrome")], "maplestory")[0] == 2
    with pytest.raises(WindowError, match="close the extra"):
        choose_window([(1, "MapleStory"), (4, "MapleStory")], "MapleStory")
    with pytest.raises(WindowError, match="no window titled"):
        choose_window([(3, "Discord")], "MapleStory")
    with pytest.raises(WindowError, match="several windows"):
        choose_window([(2, "MapleStory guide"), (5, "MapleStory forum")], "MapleStory")


def test_check_resolution() -> None:
    cfg = MapConfig(name="m", calibrated_resolution={"width": 1920, "height": 1080})
    check_resolution(cfg, (1920, 1080))
    check_resolution(MapConfig(name="m"), (800, 600))  # not calibrated yet: no check
    with pytest.raises(ResolutionMismatch, match="calibrated at 1920x1080"):
        check_resolution(cfg, (1366, 768))


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows behavior")
def test_window_command_off_windows(capsys) -> None:
    assert main(["calibrate", "window"]) == 1
    assert "only works on Windows" in capsys.readouterr().err


# ---- frame IO -------------------------------------------------------------

def test_is_black() -> None:
    assert is_black(np.zeros((10, 10, 3), np.uint8))
    assert not is_black(synth.frame())


def test_recorder_and_directory_source(tmp_path: Path) -> None:
    rec = FrameRecorder(tmp_path / "rec", every_s=0.2)
    saved = [rec.offer(Frame(synth.frame(hp=i / 10), t=100 + i * 0.1, index=i)) for i in range(6)]
    rec.close()
    assert saved == [True, False, True, False, True, False]
    src = DirectorySource(tmp_path / "rec")
    assert len(src) == 3
    frames = [src.read() for _ in range(3)]
    assert src.read() is None
    assert [f.t for f in frames] == [0.0, 0.2, 0.4]
    assert frames[0].size == (1920, 1080) and frames[0].source == "frame_00001.png"


def test_record_loop_with_fake_clock(tmp_path: Path) -> None:
    now = [0.0]

    class Src:
        i = 0

        def read(self):
            self.i += 1
            return Frame(synth.frame(), now[0], self.i)

    def sleep(dt):
        now[0] += dt

    n = record(Src(), tmp_path / "r", seconds=2.0, fps=5, clock=lambda: now[0], sleep=sleep)
    assert n == 10
    lines = (tmp_path / "r" / "index.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["t"] == pytest.approx(1.8, abs=0.11)


def test_image_io_unicode_path(tmp_path: Path) -> None:
    p = tmp_path / "ảnh" / "x.png"
    save_image(p, synth.frame())
    assert load_image(p).shape == (1080, 1920, 3)


# ---- map file editing -----------------------------------------------------

def test_mapfile_create_set_preserves_comments(tmp_path: Path) -> None:
    path = tmp_path / "maps" / "ant_tunnel" / "map.yaml"
    mf = MapFile.open_or_create(path)
    assert (path.parent / "templates" / "monsters").is_dir()
    mf.set(("rois", "minimap"), Rect(x=10, y=40, w=220, h=140))
    mf.save()
    text = path.read_text()
    assert "minimap: {x: 10, y: 40, w: 220, h: 140}" in text
    assert "# set with: mapbot calibrate roi" in text
    assert "hp_bar: null" in text
    cfg = load_map(path).model
    assert cfg.name == "ant_tunnel" and cfg.rois.minimap.w == 220


def test_mapfile_refuses_invalid_save(tmp_path: Path) -> None:
    path = tmp_path / "m" / "map.yaml"
    MapFile.open_or_create(path, name="m")
    before = path.read_text()
    mf = MapFile(path)
    mf.set(("patrol",), {"left_x": 100, "right_x": 50})
    with pytest.raises(ConfigError, match="left_x"):
        mf.save()
    assert path.read_text() == before


def test_resolve_map_path() -> None:
    assert resolve_map_path("ant_tunnel") == Path("maps/ant_tunnel/map.yaml")
    assert resolve_map_path("x/y/map.yaml") == Path("x/y/map.yaml")
    with pytest.raises(ConfigError, match="may only contain"):
        resolve_map_path("bad name!")


# ---- calibrate CLI (GUI stubbed) -----------------------------------------

@pytest.fixture
def shot(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "shot.png"
    save_image(p, synth.frame())
    return p


def test_cli_roi_and_colors_from_image(shot: Path, monkeypatch, capsys) -> None:
    rects = {"minimap": synth.MINIMAP, "hp_bar": synth.HP_BAR, "mp_bar": synth.MP_BAR,
             "play_area": (0, 200, 1920, 800)}
    monkeypatch.setattr(ui, "select_rect", lambda img, name: Rect(**dict(zip("xywh", rects[name]))))
    assert main(["calibrate", "roi", "--map", "test_map", "--image", str(shot)]) == 0

    def fake_pick(region, name):
        p = ui.ColorPicker(region)
        if name == "player_dot":
            ys, xs = np.where(np.all(region == synth.YELLOW, axis=-1))
            p.add(int(xs[0]) + 2, int(ys[0]) + 2)
        else:
            p.add(5, 1)
            p.add(50, 8)
        return p.range()

    monkeypatch.setattr(ui, "pick_color", fake_pick)
    assert main(["calibrate", "colors", "--map", "test_map", "--image", str(shot)]) == 0
    out = capsys.readouterr().out
    assert "covers 100% of hp_bar" in out

    result = load_map("maps/test_map/map.yaml")
    cfg = result.model
    assert cfg.calibrated_resolution.width == 1920
    assert cfg.rois.hp_bar.x == synth.HP_BAR[0]
    assert cfg.colors.hp_fill.hue_wraps
    assert result.warnings == ["patrol: not calibrated yet (see 'mapbot calibrate --help')"]
    assert Path("maps/test_map/calib_roi.png").is_file()


def test_cli_colors_requires_rois(shot: Path, capsys) -> None:
    assert main(["calibrate", "colors", "--map", "empty_map", "--image", str(shot)]) == 1
    assert "set these ROIs first" in capsys.readouterr().err


def test_cli_roi_only_rejects_resolution_change(shot: Path, monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setattr(ui, "select_rect", lambda img, name: Rect(x=1, y=1, w=5, h=5))
    assert main(["calibrate", "roi", "--map", "m", "--image", str(shot)]) == 0
    small = tmp_path / "small.png"
    save_image(small, synth.frame(size=(1366, 768)))
    assert main(["calibrate", "roi", "--map", "m", "--image", str(small), "--only", "minimap"]) == 1
    assert "calibrated at 1920x1080" in capsys.readouterr().err
    # Redoing every ROI at the new size is allowed.
    assert main(["calibrate", "roi", "--map", "m", "--image", str(small)]) == 0
    assert load_map("maps/m/map.yaml").model.calibrated_resolution.width == 1366
