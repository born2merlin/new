# mapbot

A class-agnostic farming bot for a single MapleStory map. It works from **screen capture only** (dxcam/mss + OpenCV) and standard keyboard input (pydirectinput). It does no memory reading, injection, packet work or client modification. It has no anti-detection or randomization features, and it does not solve runes or other anti-bot checks: if it sees one, it stops.

> ⚠️ **Botting violates Nexon's GMS Terms of Service.** Running this on an official-server account can get that account banned. Nothing here tries to hide it, so that risk is yours.

## Status

| Phase | Scope | Status |
|---|---|---|
| 0 | Skeleton, profile/map/settings schema, validation, example profiles | ✅ done |
| 1 | Window detection, capture, ROI/color calibration, frame recording | ✅ done (verify on Windows) |
| 2 | Perception (minimap, HP/MP, monsters) + offline fixtures | next |
| 3 | Keyboard input, kill switch, focus pause, key calibration | |
| 4 | Mage MVP: patrol / attack / buff / recover + watchdog | |
| 5 | Loot, debug overlay, JSONL log, replay | |
| 6 | teleport_hop, close_and_attack, bowman, docs | |
| 7 | Long-run hardening | |

## Setup (Windows, Python 3.11+)

```bash
pip install -e ".[runtime,dev]"
```

## Phase 0: validate profiles

```bash
mapbot validate profiles/*.yaml maps/_template/map.yaml settings.yaml
```

```bash
mapbot validate --strict profiles/mage_il_lv38.yaml
```

The first command checks every file and lists `TODO` keys as warnings. `--strict` turns those warnings into errors, the same way `mapbot run` will. The Mage profile fails strict until you fill in its keys (Phase 3, `mapbot calibrate keys`).

```bash
pytest
```

## Phase 1: calibrate a map

See [docs/CALIBRATION.md](docs/CALIBRATION.md). In short:

```bash
mapbot calibrate window --map my_map
```
```bash
mapbot calibrate roi --map my_map
```
```bash
mapbot calibrate colors --map my_map
```
```bash
mapbot calibrate record --map my_map --seconds 60
```

## Layout

- `profiles/`: one YAML per class. `_template.yaml` documents every field. Shipped: `mage_il_lv38.yaml` (keys TODO), `bowman_example.yaml`, `warrior_example.yaml`.
- `maps/<map_id>/map.yaml`: per-map ROIs, colors, patrol bounds and detection thresholds, plus template PNGs. Start from `maps/_template/`.
- `settings.yaml`: loop rate, capture backend, kill-switch hotkeys (F12 pause, Ctrl+F12 stop), watchdog limits.
- `mapbot/config/`: pydantic schema and loader with readable errors.
