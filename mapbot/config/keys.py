"""Key names accepted in profiles.

These match the key names understood by ``pydirectinput`` (scan-code based
input), so a profile that validates here can be sent to the game unchanged.
"""

from __future__ import annotations

PLACEHOLDER = "TODO"

_LETTERS = [chr(c) for c in range(ord("a"), ord("z") + 1)]
_DIGITS = [str(d) for d in range(10)]
_FKEYS = [f"f{n}" for n in range(1, 13)]
_NUMPAD = [f"num{d}" for d in range(10)]
_NAMED = [
    "shift", "shiftleft", "shiftright",
    "ctrl", "ctrlleft", "ctrlright",
    "alt", "altleft", "altright",
    "space", "enter", "tab", "esc", "backspace",
    "insert", "delete", "home", "end", "pageup", "pagedown",
    "left", "right", "up", "down",
]
_SYMBOLS = ["`", "-", "=", "[", "]", "\\", ";", "'", ",", ".", "/"]

VALID_KEYS: frozenset[str] = frozenset(
    _LETTERS + _DIGITS + _FKEYS + _NUMPAD + _NAMED + _SYMBOLS
)


def is_placeholder(key: str | None) -> bool:
    return key is not None and key.strip().upper() == PLACEHOLDER


def normalize_key(key: str) -> str:
    """Lower-case and strip a key name; placeholders become ``TODO``."""
    k = key.strip()
    if is_placeholder(k):
        return PLACEHOLDER
    return k.lower()
