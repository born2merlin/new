"""Phase 0 tests: profile/map/settings schema and error messages."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from mapbot.cli import main
from mapbot.config import ConfigError, load_map, load_profile, load_settings
from mapbot.config.schema import Strategy

ROOT = Path(__file__).resolve().parents[1]
PROFILES = sorted((ROOT / "profiles").glob("*.yaml"))

MINIMAL = """
name: Test
resource: none
attack:
  strategy: stand_and_spam
  range: ranged
  range_px: 300
  skills:
    - name: Shot
      key: a
"""


def write(tmp_path: Path, body: str, name: str = "p.yaml") -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def problems(tmp_path: Path, body: str, **kw) -> list[str]:
    with pytest.raises(ConfigError) as ei:
        load_profile(write(tmp_path, body), **kw)
    return ei.value.problems


# ---- shipped files --------------------------------------------------------

@pytest.mark.parametrize("path", PROFILES, ids=lambda p: p.name)
def test_shipped_profiles_validate(path: Path) -> None:
    load_profile(path)


def test_examples_cover_all_strategies() -> None:
    used = {load_profile(p).model.attack.strategy for p in PROFILES}
    # teleport_hop is shipped as the Mage's Phase-6 option; the two others must be live.
    assert {Strategy.stand_and_spam, Strategy.close_and_attack} <= used


def test_mage_has_placeholders_and_fails_strict() -> None:
    mage = ROOT / "profiles" / "mage_il_lv38.yaml"
    result = load_profile(mage)
    assert any("Thunder Bolt" in w for w in result.warnings)
    with pytest.raises(ConfigError) as ei:
        load_profile(mage, allow_placeholders=False)
    assert all("mapbot calibrate keys" in p for p in ei.value.problems)


def test_complete_examples_pass_strict() -> None:
    for name in ("bowman_example.yaml", "warrior_example.yaml"):
        load_profile(ROOT / "profiles" / name, allow_placeholders=False)


def test_map_template_and_settings() -> None:
    result = load_map(ROOT / "maps" / "_template" / "map.yaml")
    assert "patrol" in result.warnings[-1]
    with pytest.raises(ConfigError):
        load_map(ROOT / "maps" / "_template" / "map.yaml", require_calibrated=True)
    s = load_settings(ROOT / "settings.yaml")
    assert s.hotkeys.pause_toggle == "f12"


# ---- error messages -------------------------------------------------------

def test_minimal_profile_and_numeric_key(tmp_path: Path) -> None:
    body = MINIMAL.replace("key: a", "key: 1")
    p = load_profile(write(tmp_path, body)).model
    assert p.attack.skills[0].key == "1"


def test_typo_field_suggests_fix(tmp_path: Path) -> None:
    body = MINIMAL.replace("range_px: 300", "range_px: 300\n  stratgy: x")
    [msg] = problems(tmp_path, body)
    assert msg.startswith("attack.stratgy: unknown field")
    assert "did you mean 'strategy'" in msg


def test_unknown_strategy(tmp_path: Path) -> None:
    [msg] = problems(tmp_path, MINIMAL.replace("stand_and_spam", "spin_to_win"))
    assert msg.startswith("attack.strategy: 'spin_to_win' is not allowed")
    assert "close_and_attack" in msg


def test_bad_key_name(tmp_path: Path) -> None:
    [msg] = problems(tmp_path, MINIMAL.replace("key: a", "key: Shfit"))
    assert msg.startswith("attack.skills[0].key: unknown key name 'Shfit'")


def test_threshold_out_of_range(tmp_path: Path) -> None:
    body = MINIMAL + "potions:\n  hp_key: delete\n  hp_threshold: 50\n"
    [msg] = problems(tmp_path, body)
    assert msg.startswith("potions.hp_threshold:")
    assert "1" in msg


def test_teleport_hop_needs_teleport(tmp_path: Path) -> None:
    [msg] = problems(tmp_path, MINIMAL.replace("stand_and_spam", "teleport_hop"))
    assert "type: teleport" in msg


def test_mp_resource_needs_mp_key(tmp_path: Path) -> None:
    [msg] = problems(tmp_path, MINIMAL.replace("resource: none", "resource: mp"))
    assert "potions.mp_key is not set" in msg


def test_duplicate_key_binding(tmp_path: Path) -> None:
    body = MINIMAL + "buffs:\n  - name: Haste\n    key: a\n    recast_interval_s: 100\n"
    [msg] = problems(tmp_path, body)
    assert "key 'a' is bound twice" in msg
    assert "Shot" in msg and "Haste" in msg


def test_missing_required(tmp_path: Path) -> None:
    msgs = problems(tmp_path, "name: X\nresource: none\n")
    assert msgs == ["attack: required field is missing"]


def test_empty_skills(tmp_path: Path) -> None:
    body = MINIMAL.split("  skills:")[0] + "  skills: []\n"
    [msg] = problems(tmp_path, body)
    assert msg.startswith("attack.skills:")


def test_yaml_syntax_error_has_line(tmp_path: Path) -> None:
    [msg] = problems(tmp_path, "name: X\nattack: [unclosed\n")
    assert "YAML syntax error at line" in msg


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="file not found"):
        load_profile(tmp_path / "nope.yaml")


# ---- CLI ------------------------------------------------------------------

def test_cli_validate_exit_codes(tmp_path: Path, capsys) -> None:
    good = write(tmp_path, MINIMAL, "good.yaml")
    bad = write(tmp_path, MINIMAL.replace("key: a", "key: ???"), "bad.yaml")
    assert main(["validate", str(good)]) == 0
    assert main(["validate", str(good), str(bad)]) == 1
    out = capsys.readouterr().out
    assert "OK    [profile]" in out and "FAIL  [profile]" in out
    mage = str(ROOT / "profiles" / "mage_il_lv38.yaml")
    assert main(["validate", mage]) == 0
    assert main(["validate", "--strict", mage]) == 1
