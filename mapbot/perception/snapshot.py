"""What perception reports about one frame. The engine only ever reads this."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Box:
    """Axis-aligned detection in client-area pixels."""

    x: int
    y: int
    w: int
    h: int
    score: float = 1.0
    label: str = ""

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def area(self) -> int:
        return self.w * self.h

    def iou(self, other: "Box") -> float:
        ix = max(0, min(self.x + self.w, other.x + other.w) - max(self.x, other.x))
        iy = max(0, min(self.y + self.h, other.y + other.h) - max(self.y, other.y))
        inter = ix * iy
        union = self.area + other.area - inter
        return inter / union if union else 0.0

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h,
                "score": round(self.score, 3), "label": self.label}


@dataclass
class Perception:
    t: float
    frame_size: tuple[int, int]
    player_minimap: tuple[float, float] | None = None  # minimap-relative
    player_screen: tuple[float, float] | None = None   # client-area anchor
    nametag: Box | None = None
    monsters: list[Box] = field(default_factory=list)
    loot: list[Box] = field(default_factory=list)
    hp: float | None = None
    mp: float | None = None
    alerts: set[str] = field(default_factory=set)
    timings_ms: dict[str, float] = field(default_factory=dict)
    source: str = ""

    # ---- helpers used by strategies (Phase 4+) -----------------------------

    def _ref_x(self) -> float | None:
        return self.player_screen[0] if self.player_screen else None

    def monsters_within(self, range_px: float) -> list[Box]:
        """Monsters whose center is within ``range_px`` horizontally of the player."""
        ref = self._ref_x()
        if ref is None:
            return []
        return [m for m in self.monsters if abs(m.cx - ref) <= range_px]

    def side_counts(self, range_px: float | None = None) -> tuple[int, int]:
        """(left, right) monster counts relative to the player, optionally range-limited."""
        ref = self._ref_x()
        if ref is None:
            return 0, 0
        ms = self.monsters if range_px is None else self.monsters_within(range_px)
        left = sum(1 for m in ms if m.cx < ref)
        return left, len(ms) - left

    def nearest_monster(self) -> Box | None:
        ref = self._ref_x()
        if ref is None or not self.monsters:
            return None
        return min(self.monsters, key=lambda m: abs(m.cx - ref))

    def to_dict(self) -> dict:
        def r(v):
            return None if v is None else [round(c, 1) for c in v]

        return {
            "source": self.source,
            "t": round(self.t, 3),
            "player_minimap": r(self.player_minimap),
            "player_screen": r(self.player_screen),
            "hp": None if self.hp is None else round(self.hp, 3),
            "mp": None if self.mp is None else round(self.mp, 3),
            "monsters": [m.to_dict() for m in self.monsters],
            "loot": [b.to_dict() for b in self.loot],
            "alerts": sorted(self.alerts),
            "timings_ms": {k: round(v, 1) for k, v in self.timings_ms.items()},
        }
