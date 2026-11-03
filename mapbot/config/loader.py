"""Load YAML config files and turn validation failures into readable messages."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from ..errors import UserError
from .schema import BotSettings, MapConfig, Profile

M = TypeVar("M", bound=BaseModel)


class ConfigError(UserError):
    """Raised when a config file cannot be loaded. ``str()`` is user-facing."""

    def __init__(self, path: Path, problems: list[str]):
        self.path = path
        self.problems = problems
        super().__init__(self._format())

    def _format(self) -> str:
        lines = [f"{self.path}: {len(self.problems)} problem(s)"]
        lines += [f"  - {p}" for p in self.problems]
        return "\n".join(lines)


@dataclass
class LoadResult:
    model: BaseModel
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Error formatting
# --------------------------------------------------------------------------

def _loc_to_path(loc: tuple[Any, ...]) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out or "(top level)"


def _known_fields(model: type[BaseModel], loc: tuple[Any, ...]) -> list[str]:
    """Walk ``loc`` through nested models to find valid sibling field names."""
    current: Any = model
    for part in loc:
        if isinstance(part, int):
            continue
        fields = getattr(current, "model_fields", None)
        if not fields or part not in fields:
            return []
        ann = fields[part].annotation
        current = _unwrap_model(ann)
        if current is None:
            return []
    return list(getattr(current, "model_fields", {}).keys())


def _unwrap_model(ann: Any) -> type[BaseModel] | None:
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return ann
    for arg in getattr(ann, "__args__", ()) or ():
        found = _unwrap_model(arg)
        if found is not None:
            return found
    return None


def _format_errors(model: type[BaseModel], exc: ValidationError) -> list[str]:
    problems = []
    for err in exc.errors():
        loc = tuple(err["loc"])
        path = _loc_to_path(loc)
        etype = err["type"]
        if etype == "extra_forbidden":
            name = str(loc[-1])
            known = _known_fields(model, loc[:-1])
            hint = difflib.get_close_matches(name, known, n=1)
            msg = f"{path}: unknown field"
            if hint:
                msg += f" (did you mean {hint[0]!r}?)"
            elif known:
                msg += f" (allowed: {', '.join(known)})"
        elif etype == "missing":
            msg = f"{path}: required field is missing"
        elif etype == "enum":
            expected = err.get("ctx", {}).get("expected", "")
            msg = f"{path}: {err['input']!r} is not allowed; expected {expected}"
        else:
            text = err["msg"]
            if text.startswith("Value error, "):
                text = text[len("Value error, "):]
            msg = f"{path}: {text}"
        problems.append(msg)
    return problems


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(path, ["file not found"])
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        problem = getattr(e, "problem", None) or str(e)
        raise ConfigError(path, [f"YAML syntax error{where}: {problem}"]) from None
    if data is None:
        raise ConfigError(path, ["file is empty"])
    if not isinstance(data, dict):
        raise ConfigError(path, ["top level must be a mapping of field: value"])
    return data


def _validate(model: type[M], path: Path, data: dict[str, Any]) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise ConfigError(path, _format_errors(model, e)) from None


def load_profile(path: str | Path, *, allow_placeholders: bool = True) -> LoadResult:
    """Load a class profile.

    With ``allow_placeholders=False`` (used by ``mapbot run``), any key still
    set to ``TODO`` is an error instead of a warning.
    """
    p = Path(path)
    profile = _validate(Profile, p, _read_yaml(p))
    todo = [
        f"{field_path}: 'TODO' is a placeholder; set it with "
        f"'mapbot calibrate keys --profile {p}'"
        for field_path in profile.placeholders()
    ]
    if todo and not allow_placeholders:
        raise ConfigError(p, todo)
    return LoadResult(profile, todo)


def load_map(path: str | Path, *, require_calibrated: bool = False) -> LoadResult:
    p = Path(path)
    cfg = _validate(MapConfig, p, _read_yaml(p))
    missing = [
        f"{f}: not calibrated yet (see 'mapbot calibrate --help')"
        for f in cfg.missing_calibration()
    ]
    if missing and require_calibrated:
        raise ConfigError(p, missing)
    return LoadResult(cfg, missing)


def load_settings(path: str | Path | None) -> BotSettings:
    if path is None:
        return BotSettings()
    p = Path(path)
    return _validate(BotSettings, p, _read_yaml(p))


def detect_kind(path: str | Path) -> str:
    """Guess whether a YAML file is a profile, map or settings file."""
    p = Path(path)
    if p.name == "map.yaml" or "maps" in p.parts:
        return "map"
    if p.name.startswith("settings"):
        return "settings"
    return "profile"
