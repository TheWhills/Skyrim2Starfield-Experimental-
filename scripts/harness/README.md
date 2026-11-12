# Headless Starfield test instance (Windows)

An isolated Starfield that a script launches, checks and stops on its own: no window on the owner's screen, no
sound, no input, nothing written to the real install, the MO2 setup, the player's INIs, saves or logs. It sits next
to `scripts/game` (which drives the owner's own foreground game by keystrokes and OCR) as the route to unattended,
parallel, crash-captured test runs.

Ported from **tes4skyrim** (bryantmh, MIT), where the same design runs Skyrim SE in automated quest runs:
`tools/live/hidden_launch.py`, `tools/live/crash_capture.py`, `tools/live/test_instance.py`,
`game_bridge/sandbox/sandbox.cpp`. Its design notes: `docs/commentary/headless_testing.md` in that repo.

| File | Does |
|---|---|
| `test_instance.py` | `build` the instance from hard links + sandbox profile; `launch`, `smoke`, `shot`, `status`, `stop` |
| `hidden_launch.py` | create the game suspended on its own desktop, inject DLLs (sfse_loader's stub, ordinal 1 = StartSFSE), resume; PrintWindow screenshots |
| `sandbox/sandbox.cpp` | `S2SSandbox.dll`, injected before SFSE: redirects Documents and LocalAppData (shell32 export table + already-bound import slots) to the instance's `_profile`, and mutes the process's audio session |
| `crash_capture.py` | cdb attach that catches fast-fail aborts too, full minidump, offline `--analyze`, `--snapshot` for hangs, `--watch` a test folder |

## Use

Once: build the sandbox (Visual Studio with the C++ workload) and install the Windows SDK's Debugging Tools
(for `cdb.exe`), then prove the crash capture without the game:

```powershell
scripts\harness\sandbox\build.bat
python -I scripts\harness\crash_capture.py --selftest
```

Then (Starfield may stay open; the instance is a separate copy):

```powershell
python -I scripts\harness\test_instance.py build --starfield $sf
python -I scripts\harness\test_instance.py smoke --crash
```

`build` puts the instance at `<Starfield's drive>\S2S Test` (hard links need the same drive; `--instance-dir` to
move it) and links: `Starfield.exe`, the game-root DLLs except proxy loaders (dxgi, winhttp, version, ...),
`Starfield.ccc`, the official masters (Starfield, Constellation, OldMars, BlueprintShips, ShatteredSpace, SFBGS*)
and their `.ba2`, the SFSE runtime DLL and the Address Library bins. No other SFSE plugin and no mod, unless named:
`--mod "$armor"` links an MO2 mod folder into the instance's Data (copied when the mod is on another drive) and
enables its plugins. `--ini StarfieldCustom.ini:General:iFPSClamp=6` adds any sandbox INI setting.
**Re-run `build` after every conversion run**: a script that writes a new file leaves the instance's link on the
old one.

`smoke` exits 0 only when every check passes and writes `out\harness\smoke.json` + `smoke.png`:

| Check | Means |
|---|---|
| `window` | the game made a window on the hidden desktop within `--timeout` |
| `alive_after_settle` | still running after `--settle` seconds |
| `screenshot` | PrintWindow returned an image (it warns when it is all black) |
| `sandbox_redirected` | `S2SSandbox.log`: all 3 shell32 exports repointed |
| `sfse_log_in_sandbox` | SFSE wrote its log into the sandbox profile, so SFSE ran and was redirected |
| `player_profile_untouched` | the owner's own StarfieldCustom/Prefs.ini, sfse.txt and Plugins.txt kept size and time |

## What is verified

- **Verified (offline, this repo's tests):** the remote stub equals `sfse_loader/Inject.cpp`'s `kCode` and the
  block layout equals `InjectDLLThreadData` (ianpatt/sfse source); `StartSFSE` is ordinal 1 (`sfse/sfse.def`);
  sfse_loader sets `SteamGameId`/`SteamAppID` to 1716740 (`sfse_loader/main.cpp`), as `launch` does.
- **Verified on Skyrim SE by tes4skyrim, unverified on Starfield:** hidden-desktop rendering, PrintWindow capture
  (Skyrim is D3D11; Starfield's D3D12 swap chain may capture black), the sandbox (which of the three folder
  functions `Starfield.exe` imports is unknown: its log lists every slot repointed), the audio mute, cdb capture.
- **Unverified:** the sandbox INI keys (`iSize W/H`, `bBorderless`, `sIntroSequence`, `bAlwaysActive`) and
  whether Starfield runs without focus. The first smoke run's screenshot answers most of these.

## Next (not in this change)

1. The owner's first `smoke --crash` and what it shows.
2. **Speed:** whether Starfield honours `iFPSClamp` (tes4skyrim's speed-up on Skyrim: each frame advances a fixed
   1/N s; N=6 ran ~11x). Try `build --ini StarfieldCustom.ini:General:iFPSClamp=6` and compare game time.
3. **Bridge:** an SFSE plugin (CommonLibSF, as `native/combat`) with a named pipe that runs console commands on the
   main thread and returns their output, replacing the OCR route for `coc`, `player.setpos`, `getpos`, saves.
   Its addresses come from Ghidra on the current `Starfield.exe`, via the Address Library.
