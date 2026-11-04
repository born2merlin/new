"""Load per-map template images from ``maps/<id>/templates/<kind>/*.png``."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..capture.grabber import IMAGE_EXTS, load_image
from ..errors import UserError

KINDS = ("monsters", "loot", "player", "alerts")
ALERT_KINDS = ("death", "rune", "dialog")
MIN_TEMPLATE_PX = 6      # smaller (after scaling) is too little to match on
MIN_TEMPLATE_STD = 4.0   # flat-color crops match everything


class TemplateError(UserError):
    pass


@dataclass(frozen=True, eq=False)  # eq on numpy arrays is ambiguous; compare by identity
class Template:
    name: str            # file stem, plus "~flip" for mirrored copies
    kind: str
    image: np.ndarray    # BGR, full resolution
    path: Path | None = None
    _scaled: dict = field(default_factory=dict, compare=False, repr=False)

    def scaled(self, scale: float) -> np.ndarray:
        """This template resized by ``scale`` (cached)."""
        if scale == 1.0:
            return self.image
        if scale not in self._scaled:
            import cv2

            self._scaled[scale] = cv2.resize(
                self.image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
            )
        return self._scaled[scale]

    @property
    def size(self) -> tuple[int, int]:
        h, w = self.image.shape[:2]
        return w, h

    @property
    def alert_kind(self) -> str:
        """``death_dialog_2`` -> ``death``; unknown prefixes keep the stem's first word."""
        stem = self.name.split("~")[0].lower()
        for k in ALERT_KINDS:
            if stem.startswith(k):
                return k
        return re.split(r"[_\-\d]", stem)[0] or stem


@dataclass
class TemplateSet:
    by_kind: dict[str, list[Template]] = field(default_factory=lambda: {k: [] for k in KINDS})
    root: Path | None = None

    def __getitem__(self, kind: str) -> list[Template]:
        return self.by_kind.get(kind, [])

    def add(self, t: Template) -> None:
        self.by_kind.setdefault(t.kind, []).append(t)

    def counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.by_kind.items()}

    @classmethod
    def load(cls, map_dir: str | Path) -> "TemplateSet":
        root = Path(map_dir) / "templates"
        ts = cls(root=root)
        for kind in KINDS:
            folder = root / kind
            if not folder.is_dir():
                continue
            for p in sorted(folder.iterdir()):
                if p.suffix.lower() not in IMAGE_EXTS:
                    continue
                img = load_image(p)
                check_template(img, p)
                ts.add(Template(p.stem, kind, img, p))
                if kind == "monsters":
                    # Monsters face either way; matching a mirrored copy covers both.
                    ts.add(Template(f"{p.stem}~flip", kind, np.ascontiguousarray(img[:, ::-1]), p))
        return ts


def check_template(img: np.ndarray, path: Path | str) -> None:
    h, w = img.shape[:2]
    if w < MIN_TEMPLATE_PX * 2 or h < MIN_TEMPLATE_PX * 2:
        raise TemplateError(
            f"template {path} is only {w}x{h}px; capture a larger crop (at least "
            f"{MIN_TEMPLATE_PX * 2}x{MIN_TEMPLATE_PX * 2})"
        )
    # Spread within each channel; img.std() would also count the gap *between*
    # B, G and R, so a solid color like (60, 90, 40) would wrongly pass.
    if float(img.reshape(-1, img.shape[2] if img.ndim == 3 else 1).std(axis=0).max()) < MIN_TEMPLATE_STD:
        raise TemplateError(
            f"template {path} is almost a single flat color and would match everywhere; "
            f"recapture it tightly around the sprite"
        )
