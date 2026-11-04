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

**Tip: make the play area tight.** On a flat map, mark only a band of about 300 px around the platform, not the whole screen. Monster matching takes time in proportion to the area searched. In tests, a 1920x800 area took ~120 ms per frame, and a 1920x300 band took ~50 ms. Redo just that region with `calibrate roi --map <id> --only play_area`.

## 5. Templates: `mapbot calibrate template --map <id> --kind <kind> --name <name>`

Freeze a frame (live after the countdown, or `--image file.png`), then drag a **tight** box. The tool rejects crops that are tiny or a single flat color.

| kind | what to capture | tips |
|---|---|---|
| `monsters` | each monster on your map | Capture 2–3 per monster (different animation frames). A mirrored copy is added automatically, so either facing works. |
| `player` | **your name tag**, the label under your character | This is how the bot finds *you* on screen to judge monster distance. Use `--set-threshold`. |
| `loot` | meso and common drops | Optional, used for looting in Phase 5. |
| `alerts` | the death dialog, rune prompts, other dialogs | Name them `death_*`, `rune_*` or `dialog_*`. The watchdog **stops** the bot when it sees one (Phase 4); it never tries to solve them. |

After saving, the tool scores the template against the same frame. For `player` and `alerts`, only one should be on screen, so it suggests a threshold halfway between the real hit and the best false match; `--set-threshold` writes it. For `monsters` and `loot`, count how many of the top scores are real hits and tune the threshold with `check`.

Templates live in `maps/<id>/templates/<kind>/*.png`. Delete a file to drop it.

## 6. Patrol bounds: `mapbot calibrate bounds --map <id>`

There are two ways to set them:
- **From a recording (easiest):** walk from one edge of the area to the other while `calibrate record` runs, then use `bounds --frames frames/<id>/<timestamp>`. Both edges come from the dot's min and max x.
- **One edge at a time:** stand at the left edge and run `bounds --set left`, then at the right edge run `bounds --set right`.

`--inset N` (default 5 minimap px) keeps the patrol a little inside each edge.

## 7. Check perception: `mapbot calibrate check --map <id>`

This opens a live preview with no input sent. It shows:
- ROIs, patrol lines, and the player dot
- your name-tag anchor (green cross)
- monster and loot boxes with scores
- HP/MP %, alerts, and time per stage

Keys: **space** pauses, **s** saves the frame, **q** quits. `--frames DIR` previews a recording instead.

**What to tune in `map.yaml` → `detection`:**
- Missed monsters → lower `monster_threshold` or add templates.
- Boxes on scenery or effects → raise it.
- Slow (`total` well over ~60 ms) → tighten `play_area`, or lower `match_scale` (0.4).
- Small sprites missed → raise `match_scale` (0.75–1.0).

## 8. Offline test fixtures (your real screenshots)

Real frames stay on your PC: `tests/fixtures/local/` is git-ignored.

1. Record some varied play with `calibrate record`.
2. Copy the folder to `tests/fixtures/local/<name>/`, picking 10–30 interesting frames.
3. Run `mapbot inspect tests/fixtures/local/<name> --map <id> --write-labels`. It writes annotated images to `tests/fixtures/local/<name>_inspect/` and a **draft** `labels.json` built from what perception saw.
4. Open the annotated images and **correct** `labels.json` by hand: the true monster count, HP/MP, dot position, and alerts. Remove any field you don't want checked.
5. Run `pytest`. `tests/test_real_fixtures.py` checks:
   - the dot is within 3 px and HP/MP within 3%
   - monster recall is at least 80%, with no large overcount
   - alerts match exactly

Re-run it after changing thresholds or templates to catch regressions.

## Coming in later phases

- `keys` (fill the profile's `TODO` keys): Phase 3
