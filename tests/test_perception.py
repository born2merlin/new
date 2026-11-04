"""Phase 2 tests: perception on synthetic frames, plus template/bounds/inspect commands."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import synth
from mapbot.calibrate import ui
from mapbot.calibrate.commands import suggest_single_threshold
from mapbot.capture.grabber import Frame, save_image
from mapbot.capture.recorder import FrameRecorder
from mapbot.cli import main
from mapbot.config import load_map
from mapbot.config.schema import LabelSet, Rect
from mapbot.debug.annotate import annotate
from mapbot.perception import detectors as d
from mapbot.perception.match import match_templates, nms
from mapbot.perception.perceiver import NotCalibrated, Perceiver
from mapbot.perception.snapshot import Box, Perception
from mapbot.perception.templates import Template, TemplateError, TemplateSet, check_template

MONSTERS = [(300, 600, False), (900, 620, True), (1500, 580, False)]
SCENE = dict(monsters=MONSTERS, loot=[(1000, 700)], nametag=(950, 760), noise=True)


@pytest.fixture
def map_dir(tmp_path: Path) -> Path:
    md = tmp_path / "maps" / "synth"
    md.mkdir(parents=True)
    (md / "map.yaml").write_text(synth.calibrated_map_yaml(), encoding="utf-8")
    synth.write_templates(md)
    return md


@pytest.fixture
def cfg(map_dir: Path):
    return load_map(map_dir / "map.yaml").model


@pytest.fixture
def perceiver(cfg, map_dir: Path) -> Perceiver:
    return Perceiver.for_map(cfg, map_dir / "map.yaml", smooth_frames=1)


# ---- minimap / bars -------------------------------------------------------

@pytest.mark.parametrize("dot", [(30, 60), (110, 100), (200, 150)])
def test_player_dot(cfg, dot) -> None:
    f = synth.frame(dot_x=dot[0], dot_y=dot[1], noise=True)
    x, y = d.find_player_dot(f, cfg.rois.minimap, cfg.colors.player_dot)
    mm = cfg.rois.minimap
    assert abs(x - (dot[0] - mm.x)) <= 2 and abs(y - (dot[1] - mm.y)) <= 2


def test_player_dot_missing(cfg) -> None:
    f = synth.frame()
    mm = cfg.rois.minimap
    f[mm.y:mm.y + mm.h, mm.x:mm.x + mm.w] = synth.MINIMAP_BG
    assert d.find_player_dot(f, mm, cfg.colors.player_dot) is None


@pytest.mark.parametrize("fill", [0.0, 0.15, 0.5, 0.83, 1.0])
def test_bars(cfg, fill) -> None:
    f = synth.frame(hp=fill, mp=1 - fill, noise=True)
    assert d.read_bar(f, cfg.rois.hp_bar, cfg.colors.hp_fill) == pytest.approx(fill, abs=0.03)
    assert d.read_bar(f, cfg.rois.mp_bar, cfg.colors.mp_fill) == pytest.approx(1 - fill, abs=0.03)


def test_bar_tolerates_text_overlay(cfg) -> None:
    import cv2

    f = synth.frame(hp=0.6)
    x, y, w, h = synth.HP_BAR
    cv2.putText(f, "1234/2000", (x + 30, y + 10), cv2.FONT_HERSHEY_PLAIN, 0.7, (255, 255, 255), 1)
    assert d.read_bar(f, cfg.rois.hp_bar, cfg.colors.hp_fill) == pytest.approx(0.6, abs=0.03)


def test_hp_smoothing_drops_single_glitch(cfg, map_dir) -> None:
    p = Perceiver.for_map(cfg, map_dir / "map.yaml", smooth_frames=3)
    reads = [p.perceive(synth.frame(hp=h)).hp for h in (0.8, 0.8, 0.0, 0.8)]
    assert reads[2] == pytest.approx(0.8, abs=0.03)  # one-frame 0% is ignored


# ---- template matching ----------------------------------------------------

def test_nms() -> None:
    a, b, c = Box(0, 0, 10, 10, 0.9), Box(2, 2, 10, 10, 0.8), Box(50, 50, 10, 10, 0.7)
    assert nms([b, a, c], 0.3) == [a, c]


def test_match_finds_all_including_mirrored(cfg) -> None:
    ts = TemplateSet.load(Path("does-not-exist"))
    ts.add(Template("blob", "monsters", synth.MONSTER))
    ts.add(Template("blob~flip", "monsters", np.ascontiguousarray(synth.MONSTER[:, ::-1])))
    f = synth.frame(monsters=MONSTERS, noise=True)
    for scale in (1.0, 0.5):
        hits = match_templates(f, ts["monsters"], 0.8, scale=scale)
        got = sorted((h.x, h.y) for h in hits)
        assert len(got) == 3, (scale, got)
        for (gx, gy), (ex, ey, _f) in zip(got, sorted(MONSTERS)):
            assert abs(gx - ex) <= 3 and abs(gy - ey) <= 3
    labels = {h.label for h in match_templates(f, ts["monsters"], 0.8)}
    assert labels == {"blob", "blob~flip"}


def test_template_load_and_validation(map_dir: Path) -> None:
    ts = TemplateSet.load(map_dir)
    assert ts.counts() == {"monsters": 2, "loot": 1, "player": 1, "alerts": 1}  # + auto flip
    assert ts["alerts"][0].alert_kind == "death"
    with pytest.raises(TemplateError, match="flat color"):
        check_template(np.full((30, 30, 3), 90, np.uint8), "x.png")
    with pytest.raises(TemplateError, match="only 5x5"):
        check_template(synth.MONSTER[:5, :5], "y.png")


def test_alert_kind_from_name() -> None:
    img = synth.DEATH
    assert Template("rune_prompt_2", "alerts", img).alert_kind == "rune"
    assert Template("dialog-npc", "alerts", img).alert_kind == "dialog"
    assert Template("lie3", "alerts", img).alert_kind == "lie"


# ---- full perceiver -------------------------------------------------------

def test_perceive_scene(perceiver: Perceiver, cfg) -> None:
    p = perceiver.perceive(synth.frame(hp=0.62, mp=0.3, dot_x=70, **SCENE))
    assert p.player_minimap == pytest.approx((60, 60), abs=2)
    assert p.hp == pytest.approx(0.62, abs=0.03) and p.mp == pytest.approx(0.3, abs=0.03)
    assert len(p.monsters) == 3
    assert [b.label for b in p.loot] == ["meso"]
    tag_x, tag_y = 950 + synth.NAMETAG.shape[1] / 2, 760 + synth.NAMETAG.shape[0] / 2
    assert p.player_screen == pytest.approx((tag_x, tag_y - cfg.detection.nametag_to_body_px), abs=3)
    assert p.alerts == set()
    assert {"minimap", "hp", "mp", "nametag", "monsters", "loot", "alerts", "total"} <= set(p.timings_ms)
    json.dumps(p.to_dict())  # serializable for perception.jsonl


def test_perception_helpers() -> None:
    p = Perception(t=0, frame_size=(1920, 1080), player_screen=(1000, 700),
                   monsters=[Box(600, 600, 40, 40), Box(1100, 600, 40, 40), Box(1700, 600, 40, 40)])
    assert len(p.monsters_within(400)) == 2
    assert p.side_counts() == (1, 2)
    assert p.side_counts(400) == (1, 1)
    assert p.nearest_monster().x == 1100
    assert Perception(t=0, frame_size=(1, 1)).nearest_monster() is None


def test_nametag_tracking_follows_player(perceiver: Perceiver) -> None:
    a = perceiver.perceive(synth.frame(nametag=(950, 760)))
    b = perceiver.perceive(synth.frame(nametag=(1010, 760)))   # small move: tracked window
    c = perceiver.perceive(synth.frame(nametag=(200, 500)))    # jump: full-area fallback
    assert a.nametag.x == pytest.approx(950, abs=3)
    assert b.nametag.x == pytest.approx(1010, abs=3)
    assert c.nametag.x == pytest.approx(200, abs=3)


def test_monster_under_own_nametag_ignored(perceiver: Perceiver) -> None:
    p = perceiver.perceive(synth.frame(monsters=[(970, 750, False)], nametag=(950, 760)))
    assert all(not p.nametag.contains(m.cx, m.cy) for m in p.monsters)


def test_alerts_throttled_but_persistent(perceiver: Perceiver) -> None:
    every = perceiver.cfg.detection.alert_every_n
    res = [perceiver.perceive(synth.frame(dead=True)) for _ in range(every + 1)]
    assert all(r.alerts == {"death"} for r in res)
    assert sum("alerts" in r.timings_ms for r in res) == 2  # frame 0 and frame N


def test_color_mode_monsters(map_dir: Path) -> None:
    text = (map_dir / "map.yaml").read_text().replace(
        "detection:\n",
        "detection:\n  monster_detector: color\n"
        "  monster_color: {lower: [140, 150, 100], upper: [160, 255, 255]}\n",
    )
    (map_dir / "map.yaml").write_text(text)
    cfg = load_map(map_dir / "map.yaml").model
    p = Perceiver.for_map(cfg, map_dir / "map.yaml").perceive(synth.frame(**SCENE))
    assert len(p.monsters) == 3 and all(m.label == "color" for m in p.monsters)


def test_not_calibrated_errors(tmp_path: Path) -> None:
    from mapbot.calibrate.mapfile import MapFile

    mf = MapFile.open_or_create(tmp_path / "m" / "map.yaml")
    with pytest.raises(NotCalibrated) as ei:
        Perceiver.for_map(mf.model(), mf.path)
    msg = str(ei.value)
    assert "rois.minimap not set" in msg and "calibrate template --kind monsters" in msg
    lenient = Perceiver.for_map(mf.model(), mf.path, strict=False)
    p = lenient.perceive(synth.frame())
    assert p.hp is None and p.monsters == []


def test_annotate_draws(perceiver: Perceiver, cfg) -> None:
    f = synth.frame(dead=True, **SCENE)
    out = annotate(f, perceiver.perceive(f), cfg)
    assert out.shape == f.shape and not np.array_equal(out, f)


def test_threshold_suggestion() -> None:
    assert suggest_single_threshold([1.0, 0.5]) == 0.75
    assert suggest_single_threshold([1.0, 0.99]) == 0.95
    assert suggest_single_threshold([0.7]) == 0.6
    assert suggest_single_threshold([]) is None


# ---- CLI: template / bounds / inspect ------------------------------------

@pytest.fixture
def cli_map(map_dir: Path, monkeypatch) -> Path:
    monkeypatch.chdir(map_dir.parent.parent)  # so --map synth resolves to maps/synth
    return map_dir


def test_cli_template_saves_and_sets_threshold(cli_map: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    shot = tmp_path / "shot.png"
    save_image(shot, synth.frame(**SCENE))
    tag = Rect(x=950, y=760, w=synth.NAMETAG.shape[1], h=synth.NAMETAG.shape[0])
    monkeypatch.setattr(ui, "select_rect", lambda img, prompt: tag)
    args = ["calibrate", "template", "--map", "synth", "--image", str(shot),
            "--kind", "player", "--name", "me2", "--set-threshold"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert (cli_map / "templates" / "player" / "me2.png").is_file()
    assert "suggested detection.nametag_threshold" in out
    assert 0.6 <= load_map(cli_map / "map.yaml").model.detection.nametag_threshold <= 0.95
    assert main(args) == 1  # exists, no --force
    assert "already exists" in capsys.readouterr().err


def test_cli_template_rejects_flat_crop(cli_map: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    shot = tmp_path / "shot.png"
    save_image(shot, synth.frame())
    monkeypatch.setattr(ui, "select_rect", lambda img, prompt: Rect(x=500, y=300, w=60, h=60))
    assert main(["calibrate", "template", "--map", "synth", "--image", str(shot),
                 "--kind", "monsters", "--name", "grass"]) == 1
    assert "flat color" in capsys.readouterr().err
    assert not (cli_map / "templates" / "monsters" / "grass.png").exists()


def test_cli_bounds_from_frames_and_single_edges(cli_map: Path, tmp_path: Path) -> None:
    rec = FrameRecorder(tmp_path / "walk", every_s=0)
    for i, x in enumerate(range(40, 200, 20)):
        rec.offer(Frame(synth.frame(dot_x=x), t=i, index=i))
    rec.close()
    assert main(["calibrate", "bounds", "--map", "synth", "--frames", str(tmp_path / "walk")]) == 0
    patrol = load_map(cli_map / "map.yaml").model.patrol
    assert (patrol.left_x, patrol.right_x) == (30 + 5, 170 - 5)  # minimap-relative, inset 5

    left = tmp_path / "left.png"
    save_image(left, synth.frame(dot_x=60))
    assert main(["calibrate", "bounds", "--map", "synth", "--image", str(left), "--set", "left", "--inset", "0"]) == 0
    assert load_map(cli_map / "map.yaml").model.patrol.left_x == 50
    bad = tmp_path / "bad.png"
    save_image(bad, synth.frame(dot_x=50))
    assert main(["calibrate", "bounds", "--map", "synth", "--image", str(bad), "--set", "right", "--inset", "0"]) == 1


def test_cli_inspect_writes_outputs_and_labels(cli_map: Path, tmp_path: Path, capsys) -> None:
    frames = tmp_path / "fx"
    rec = FrameRecorder(frames, every_s=0)
    rec.offer(Frame(synth.frame(hp=0.5, **SCENE), 0, 1))
    rec.offer(Frame(synth.frame(dead=True), 1, 2))
    rec.close()
    assert main(["inspect", str(frames), "--map", "synth", "--write-labels"]) == 0
    out_dir = tmp_path / "fx_inspect"
    assert (out_dir / "frame_00001.png").is_file()
    lines = (out_dir / "perception.jsonl").read_text().splitlines()
    assert len(lines) == 2 and len(json.loads(lines[0])["monsters"]) == 3
    labels = LabelSet.model_validate_json((frames / "labels.json").read_text())
    assert labels.frames["frame_00001.png"].hp == pytest.approx(0.5, abs=0.03)
    assert labels.frames["frame_00002.png"].alerts == ["death"]
    assert (frames / labels.map).resolve() == (cli_map / "map.yaml").resolve()
    assert "player dot found: 2/2" in capsys.readouterr().out
    assert main(["inspect", str(frames), "--map", "synth", "--write-labels"]) == 1  # no --force
