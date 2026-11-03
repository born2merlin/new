# Calibration guide

Calibration is per map. Everything lands in `maps/<map_id>/map.yaml`, and the tool keeps the file's comments. Each save is validated first, so a bad value is never written.

Use a short map id with only letters, digits, `_` and `-`, such as `ant_tunnel_1`. The first calibrate command for a new id creates `maps/<id>/` from the template, including its `templates/` folders.

## Before you start (GMS at 1920x1080)

- **Use borderless** if your monitor is 1920x1080. A *windowed* 1920x1080 client on a 1080p screen pushes part of the client area off-screen behind the title bar. `calibrate window` warns about this, but those pixels will capture black.
- Keep the game on the **primary monitor**. dxcam only captures that one. On another monitor, use `--backend mss` (slower).
- Windows display scaling (125%, 150%) is fine. mapbot is DPI aware and works in physical pixels.
- Don't change the game resolution or window mode after calibrating. `run` refuses to start if the client size differs from `calibrated_resolution`.
- The game client may run elevated. If window detection or capture fails, run your terminal **as Administrator**.

## 1. Find the window: `mapbot calibrate window --map <id>`

This prints the window title, client size and position, DPI scale, and measured capture FPS. It saves `maps/<id>/reference.png` and records `calibrated_resolution`.

**What to check:**
- The client area is `1920x1080`.
- The capture rate is at least ~25 FPS.
- There is no black-frame warning.
- `reference.png` shows the game and nothing else.

## 2. Mark regions: `mapbot calibrate roi --map <id>`

After a 3-second countdown, the tool captures a frame and asks for each region in turn:

| ROI | What to drag |
|---|---|
| `minimap` | the minimap's map area only, not its title or buttons |
| `hp_bar` | the whole HP bar, the full width the red fill can reach |
| `mp_bar` | the whole MP bar |
| `play_area` | where monsters can appear; leave out the minimap, status bar and chat |

Small selections (the minimap and bars) get a second, zoomed view so you can tighten the box to the pixel. Press **Enter** to accept, or **c** to skip a region. Use `--only hp_bar mp_bar` to redo just some regions. Use `--image file.png` to work from a saved screenshot.

## 3. Pick colors: `mapbot calibrate colors --map <id>`

Do this at **full HP and full MP**. Each target opens a zoomed view of its region, with a live mask preview beside it:

- `player_dot`: click your yellow dot a few times.
- `hp_fill` / `mp_fill`: click several spots along the fill.

Press **+ / -** to widen or narrow the range, **r** to reset, **Enter** to save, **Esc** to skip.

**What to check:**
- HP/MP coverage is near 100%. The tool warns below 60%.
- `player_dot` coverage is tiny. If other minimap pixels light up, narrow the range.

Red wraps around hue 0, so an HP range like `lower: [172, ...]`, `upper: [6, ...]` is expected.

## 4. Record frames: `mapbot calibrate record --map <id> --seconds 60 --fps 5`

This saves `frames/<id>/<timestamp>/frame_00001.png …` plus an `index.jsonl` of timestamps. It sends no input. Move or fight by hand while it records, so the frames cover:
- the full patrol width
- low HP/MP
- several monsters and drops on screen

These frames become the offline fixtures and replay input for Phase 2 onward.

## Coming in later phases

- `template` (monster, loot, name-tag and alert images) and `bounds` (patrol edges): Phase 2
- `check` (live perception preview with no input): Phase 2
- `keys` (fill the profile's `TODO` keys): Phase 3
