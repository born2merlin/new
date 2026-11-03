"""Pydantic models for class profiles, map configs and bot settings.

Profiles describe *how a class plays* (keys, skills, buffs, movement,
potions). Map configs describe *what is on screen* (ROIs, colors, patrol
bounds, templates). Any validated profile can run on any calibrated map.
The engine only ever sees these models -- it never references a class.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Iterator

from pydantic import (
    AfterValidator,
    BeforeValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .keys import PLACEHOLDER, VALID_KEYS, is_placeholder, normalize_key


class _Strict(BaseModel):
    """Base model: unknown fields are errors (catches typos like `atack:`)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------
# Key type
# --------------------------------------------------------------------------

def _coerce_key(value: object) -> object:
    # YAML reads `key: 1` as an int; number-row keys are common, so accept them.
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 9:
        return str(value)
    return value


def _check_key(value: str) -> str:
    k = normalize_key(value)
    if k == PLACEHOLDER:
        return k
    if k not in VALID_KEYS:
        raise ValueError(
            f"unknown key name {value!r}. Use names like 'a', '1', 'f5', 'shift', "
            f"'ctrl', 'alt', 'space', 'pageup', 'insert', 'left'"
        )
    return k


Key = Annotated[str, BeforeValidator(_coerce_key), AfterValidator(_check_key)]
"""Validated key name (or the placeholder ``TODO``)."""


Seconds = Annotated[float, Field(ge=0)]
Fraction = Annotated[float, Field(ge=0.0, le=1.0)]


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------

class Resource(str, Enum):
    mp = "mp"
    ammo = "ammo"
    none = "none"


class Strategy(str, Enum):
    stand_and_spam = "stand_and_spam"
    close_and_attack = "close_and_attack"
    teleport_hop = "teleport_hop"


class AttackRange(str, Enum):
    melee = "melee"
    short = "short"
    ranged = "ranged"


class AttackDirection(str, Enum):
    facing = "facing"      # skill fires in the direction the character faces
    targeted = "targeted"  # skill auto-targets; facing does not matter


class MovementType(str, Enum):
    teleport = "teleport"
    flash_jump = "flash_jump"
    double_jump = "double_jump"
    dash = "dash"


class LootMode(str, Enum):
    key_sweep = "key_sweep"  # walk over drops and press the loot key
    pet = "pet"              # pet auto-loot; bot does nothing special
    none = "none"


class AttackSkill(_Strict):
    name: str
    key: Key
    cast_time_s: Seconds = 0.6
    cooldown_s: Seconds = 0.0
    priority: int = Field(1, ge=1, description="1 = preferred")
    hold: bool = Field(False, description="hold the key instead of tapping")
    min_targets: int = Field(1, ge=1, description="only use when >= N monsters in range")


class Buff(_Strict):
    name: str
    key: Key
    recast_interval_s: Annotated[float, Field(gt=0)]
    cast_time_s: Seconds = 0.8


class MovementSkill(_Strict):
    name: str
    type: MovementType
    key: Key
    distance_px: Annotated[int, Field(gt=0)] = 150
    cooldown_s: Seconds = 0.0


class Walk(_Strict):
    left: Key = "left"
    right: Key = "right"
    up: Key = "up"
    down: Key = "down"


class Attack(_Strict):
    strategy: Strategy
    range: AttackRange
    range_px: Annotated[int, Field(gt=0, description="horizontal reach in screen px")]
    direction: AttackDirection = AttackDirection.facing
    skills: list[AttackSkill] = Field(min_length=1)


class Movement(_Strict):
    walk: Walk = Walk()
    jump_key: Key | None = None
    skills: list[MovementSkill] = []


class Potions(_Strict):
    hp_key: Key | None = None
    mp_key: Key | None = None
    hp_threshold: Fraction = 0.5
    mp_threshold: Fraction = 0.3
    cooldown_s: Seconds = 1.0


class Loot(_Strict):
    mode: LootMode = LootMode.none
    key: Key | None = None


class Profile(_Strict):
    name: str
    class_archetype: str = Field("", description="informational only; the engine ignores it")
    resource: Resource
    attack: Attack
    buffs: list[Buff] = []
    movement: Movement = Movement()
    potions: Potions = Potions()
    loot: Loot = Loot()

    # ---- cross-field checks ------------------------------------------------

    @model_validator(mode="after")
    def _cross_checks(self) -> "Profile":
        problems: list[str] = []

        if self.attack.strategy is Strategy.teleport_hop and not any(
            m.type is MovementType.teleport for m in self.movement.skills
        ):
            problems.append(
                "attack.strategy is 'teleport_hop' but movement.skills has no skill "
                "with type: teleport"
            )

        if self.resource is Resource.mp and self.potions.mp_key is None:
            problems.append("resource is 'mp' but potions.mp_key is not set")

        if self.loot.mode is LootMode.key_sweep and self.loot.key is None:
            problems.append("loot.mode is 'key_sweep' but loot.key is not set")

        names = [s.name for s in self.attack.skills]
        dup_names = sorted({n for n in names if names.count(n) > 1})
        if dup_names:
            problems.append(f"attack.skills has duplicate names: {dup_names}")

        # Two different actions bound to the same key is almost always a mistake.
        seen: dict[str, str] = {}
        for path, key in self.iter_keys():
            if key == PLACEHOLDER:
                continue
            if key in seen:
                problems.append(f"key {key!r} is bound twice: {seen[key]} and {path}")
            else:
                seen[key] = path

        if problems:
            raise ValueError("; ".join(problems))
        return self

    # ---- helpers -----------------------------------------------------------

    def iter_keys(self) -> Iterator[tuple[str, str]]:
        """Yield ``(field_path, key)`` for every key binding in the profile."""
        for i, s in enumerate(self.attack.skills):
            yield f"attack.skills[{i}].key ({s.name})", s.key
        for i, b in enumerate(self.buffs):
            yield f"buffs[{i}].key ({b.name})", b.key
        w = self.movement.walk
        for d in ("left", "right", "up", "down"):
            yield f"movement.walk.{d}", getattr(w, d)
        if self.movement.jump_key is not None:
            yield "movement.jump_key", self.movement.jump_key
        for i, m in enumerate(self.movement.skills):
            yield f"movement.skills[{i}].key ({m.name})", m.key
        if self.potions.hp_key is not None:
            yield "potions.hp_key", self.potions.hp_key
        if self.potions.mp_key is not None:
            yield "potions.mp_key", self.potions.mp_key
        if self.loot.key is not None:
            yield "loot.key", self.loot.key

    def placeholders(self) -> list[str]:
        """Field paths whose key is still the ``TODO`` placeholder."""
        return [path for path, key in self.iter_keys() if is_placeholder(key)]


# --------------------------------------------------------------------------
# Map config
# --------------------------------------------------------------------------

class Rect(_Strict):
    """Rectangle relative to the game window's client area (pixels)."""

    x: Annotated[int, Field(ge=0)]
    y: Annotated[int, Field(ge=0)]
    w: Annotated[int, Field(gt=0)]
    h: Annotated[int, Field(gt=0)]


class HSVRange(_Strict):
    """OpenCV HSV range: H in 0-179, S/V in 0-255.

    Hue is circular: if ``lower`` hue > ``upper`` hue the range wraps through
    0 (e.g. red: lower H 170, upper H 8). S and V must satisfy lower <= upper.
    """

    lower: tuple[int, int, int]
    upper: tuple[int, int, int]

    @field_validator("lower", "upper")
    @classmethod
    def _bounds(cls, v: tuple[int, int, int]) -> tuple[int, int, int]:
        h, s, val = v
        if not (0 <= h <= 179 and 0 <= s <= 255 and 0 <= val <= 255):
            raise ValueError(f"HSV values out of range (H 0-179, S/V 0-255): {list(v)}")
        return v

    @model_validator(mode="after")
    def _ordered(self) -> "HSVRange":
        if any(lo > hi for lo, hi in zip(self.lower[1:], self.upper[1:])):
            raise ValueError(
                f"lower {list(self.lower)} must be <= upper {list(self.upper)} "
                f"for S and V (only hue may wrap around)"
            )
        return self

    @property
    def hue_wraps(self) -> bool:
        return self.lower[0] > self.upper[0]


class Resolution(_Strict):
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]


class ROIs(_Strict):
    minimap: Rect | None = None
    hp_bar: Rect | None = None
    mp_bar: Rect | None = None
    play_area: Rect | None = None


class Colors(_Strict):
    player_dot: HSVRange | None = None
    hp_fill: HSVRange | None = None
    mp_fill: HSVRange | None = None


class PatrolBounds(_Strict):
    """Patrol limits as x-coordinates *inside the minimap ROI*."""

    left_x: Annotated[int, Field(ge=0)]
    right_x: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _ordered(self) -> "PatrolBounds":
        if self.left_x >= self.right_x:
            raise ValueError(f"left_x ({self.left_x}) must be < right_x ({self.right_x})")
        return self


class MonsterDetector(str, Enum):
    template = "template"
    color = "color"


class Detection(_Strict):
    monster_detector: MonsterDetector = MonsterDetector.template
    monster_threshold: Fraction = 0.75
    monster_color: HSVRange | None = None
    loot_threshold: Fraction = 0.8
    nametag_threshold: Fraction = 0.8
    alert_threshold: Fraction = 0.85

    @model_validator(mode="after")
    def _color_needs_range(self) -> "Detection":
        if self.monster_detector is MonsterDetector.color and self.monster_color is None:
            raise ValueError("monster_detector is 'color' but monster_color is not set")
        return self


class MapConfig(_Strict):
    name: str
    window_title: str = "MapleStory"
    calibrated_resolution: Resolution | None = None
    rois: ROIs = ROIs()
    colors: Colors = Colors()
    patrol: PatrolBounds | None = None
    detection: Detection = Detection()

    def missing_calibration(self) -> list[str]:
        """Fields that must be calibrated before the bot can run on this map."""
        missing = []
        if self.calibrated_resolution is None:
            missing.append("calibrated_resolution")
        for f in ("minimap", "hp_bar", "mp_bar", "play_area"):
            if getattr(self.rois, f) is None:
                missing.append(f"rois.{f}")
        for f in ("player_dot", "hp_fill", "mp_fill"):
            if getattr(self.colors, f) is None:
                missing.append(f"colors.{f}")
        if self.patrol is None:
            missing.append("patrol")
        return missing


# --------------------------------------------------------------------------
# Bot settings (safety / loop)
# --------------------------------------------------------------------------

class Hotkeys(_Strict):
    pause_toggle: str = "f12"
    hard_stop: str = "ctrl+f12"


class Watchdog(_Strict):
    no_monsters_s: Annotated[float, Field(gt=0)] = 60
    no_player_dot_s: Annotated[float, Field(gt=0)] = 10
    out_of_bounds_s: Annotated[float, Field(gt=0)] = 20
    focus_lost_stop_s: Annotated[float, Field(gt=0)] = 30
    hp_zero_s: Annotated[float, Field(gt=0)] = 1.0
    frozen_frame_s: Annotated[float, Field(gt=0)] = 5
    max_runtime_min: Annotated[float, Field(gt=0)] | None = None


class BotSettings(_Strict):
    loop_hz: Annotated[float, Field(gt=0, le=60)] = 12
    capture_fps: Annotated[int, Field(gt=0, le=144)] = 30
    capture_backend: str = Field("dxcam", pattern="^(dxcam|mss)$")
    hotkeys: Hotkeys = Hotkeys()
    watchdog: Watchdog = Watchdog()
    log_dir: str = "logs"
