# In-game test tools (Windows)

Drive a running Starfield from scripts to test converted content, without keyboard macros or mods.

| Script | What it does |
|---|---|
| `input.ps1` | Sends keys, text, mouse moves and clicks to the game. **Refuses to send anything unless Starfield is the foreground window** (checked before every step), so it can never type into another app. Starfield ignores `SendInput` keyboard events; set `$env:LEGACY='1'` to use `keybd_event`, which works. Steps: `key:enter`, `type:coc X`, `hold:w,1500`, `move:dx,dy`, `click:x,y`, `wait:ms`, separated by `|`. |
| `shot.ps1`, `shot_region.ps1` | Screenshot (downscaled) / native-resolution capture of a screen region (for OCR). |
| `ocr.ps1`, `ocr_prep.py`, `parse_getpos.py` | Read console replies with the built-in Windows OCR. The console font is light grey (~150) over a dimmed game (~85): `ocr_prep` keeps bright, unsaturated pixels as black-on-white. The parser handles the OCR's quirks (labels and numbers in separate columns, `.` read as a space). |
| `readpos.ps1` | Opens the console, runs `player.getpos x/y/z`, reads the answer by OCR, closes the console. Prints `x y z` (metres). |
| `probe_points.py`, `probe.ps1`, `probe_map.py` | **Collision mapper.** Picks floor-like pieces from an exported FO4 cell, teleports the player 1.5 m above each (`player.setpos`, god mode on), waits, reads the height. `PASS` = landed on it, `FALL` = dropped through (missing collision), `HELD` = stopped well above (e.g. the stair top). Results to CSV and a top-down map image. |
| `walk_route.py`, `walk.ps1` | **Walk check (issue #29).** Chains nearby floor pieces into short aimed steps and holds W. A rise too tall to step ends the route instead of teleporting onto it. Does not toggle god mode or close the game. Exit 0 only when every leg arrives. |
| `cycle.ps1` | Close game, redeploy staging (`deploy_starfield.py`), launch via Steam, load the last save, clear the first-console-use dialog, `coc` into a cell, screenshot. |

Requirements: Starfield running windowed/borderless on the primary screen; the player in the cell; Python with numpy + Pillow
(`$env:FO4SF_PYTHON` can point at a venv's `python.exe`). The console achievements warning appears on the first console command
of a session and swallows input: run one harmless command first (`cycle.ps1` does).

Lessons: `con` is a reserved Windows file name (`con.png` cannot be opened); `scof` accepts a name but never wrote a file here,
hence the OCR route; walking with held keys drifts and gets stuck, teleporting with `player.setpos` is exact.
