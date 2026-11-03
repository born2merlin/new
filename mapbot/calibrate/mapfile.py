"""Read/modify/write ``maps/<id>/map.yaml`` while keeping its comments.

Every save is validated against ``MapConfig`` first, so calibration can never
leave an invalid map file behind.
"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from ..config.loader import ConfigError, _format_errors
from ..config.schema import MapConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "maps" / "_template" / "map.yaml"
_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _yaml() -> YAML:
    y = YAML()  # round-trip mode
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 120
    # Keep explicit `null` (ruamel writes an empty value by default).
    y.representer.add_representer(
        type(None), lambda r, _d: r.represent_scalar("tag:yaml.org,2002:null", "null")
    )
    return y


def resolve_map_path(arg: str, maps_dir: str | Path = "maps") -> Path:
    """Accept a map id (``henesys_hunting``), a folder, or a ``map.yaml`` path."""
    p = Path(arg)
    if p.suffix in (".yaml", ".yml"):
        return p
    if p.is_dir() or os.sep in arg or "/" in arg:
        return p / "map.yaml"
    if not _ID_RE.match(arg):
        raise ConfigError(p, [f"map id {arg!r} may only contain letters, digits, _ and -"])
    return Path(maps_dir) / arg / "map.yaml"


def _to_yaml_value(value: Any) -> Any:
    """Convert models/tuples to compact flow-style YAML nodes."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        m = CommentedMap((k, _to_yaml_value(v)) for k, v in value.items())
        m.fa.set_flow_style()
        return m
    if isinstance(value, (list, tuple)):
        s = CommentedSeq(_to_yaml_value(v) for v in value)
        s.fa.set_flow_style()
        return s
    return value


def _plain(node: Any) -> Any:
    if isinstance(node, dict):
        return {str(k): _plain(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_plain(v) for v in node]
    return node


class MapFile:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._yaml = _yaml()
        self.data: CommentedMap = self._yaml.load(self.path.read_text(encoding="utf-8"))
        if not isinstance(self.data, dict):
            raise ConfigError(self.path, ["top level must be a mapping of field: value"])

    @classmethod
    def open_or_create(cls, path: str | Path, name: str | None = None) -> "MapFile":
        """Open ``path``; if missing, create it from the template."""
        p = Path(path)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            for sub in ("monsters", "loot", "player", "alerts"):
                (p.parent / "templates" / sub).mkdir(parents=True, exist_ok=True)
            text = TEMPLATE.read_text(encoding="utf-8") if TEMPLATE.is_file() else "name: map\n"
            p.write_text(text, encoding="utf-8")
            mf = cls(p)
            mf.set(("name",), name or p.parent.name)
            mf.save()
            return mf
        return cls(p)

    def get(self, keys: tuple[str, ...]) -> Any:
        node: Any = self.data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return None
            node = node[k]
        return node

    def set(self, keys: tuple[str, ...], value: Any) -> None:
        node = self.data
        for k in keys[:-1]:
            if not isinstance(node.get(k), dict):
                node[k] = CommentedMap()
            node = node[k]
        node[keys[-1]] = _to_yaml_value(value)

    def model(self) -> MapConfig:
        try:
            return MapConfig.model_validate(_plain(self.data))
        except ValidationError as e:
            raise ConfigError(self.path, _format_errors(MapConfig, e)) from None

    def save(self) -> MapConfig:
        cfg = self.model()  # refuse to write an invalid file
        buf = io.StringIO()
        self._yaml.dump(self.data, buf)
        tmp = self.path.with_suffix(".yaml.tmp")
        tmp.write_text(buf.getvalue(), encoding="utf-8")
        os.replace(tmp, self.path)
        return cfg
