# Optimization log

Ongoing (AGENTS.md "Keep optimizing"). Every entry: date, agent, what, **measured before / after** (same command,
same input), and the commit. Use the `optimization` label on the issue or PR.

## Baselines (measured 2026-10-09 on the owner's PC; Ryzen 9 7950X3D, RTX 4070 Ti 12 GB, 32 GB)

| What | Command | Measured | Source |
|---|---|---|---|
| Full conversion build, 15 cells / 4,014 models | `scripts/convert_batch.py --cell-json merged.json` (no `--resume`) | 311–373 s | Claude, journal 2026-10-09 |
| Plugin write, 15 cells | `dotnet/PluginSpike` | ~10 s (not timed precisely) | Claude |
| Unit tests (241) | `python -m unittest discover -s tests` | 2.4 s | Claude |
| Deploy + launch + load cell | `research/s1/cycle.ps1` | ~3 min | Claude |
| Parsons route run, 45 routes | `scripts/game/route_run.ps1` | ~2 min per door route (prompt search + console checks) | Claude, in progress |
| Guardian status (one sample) | `guardian.py status` | 1.1 s | Claude |
| Remote usage report, 24 h | `remote_usage.py` | 2.7 s | Claude |
| Local model tokens per task | `guardian.py report` | no data yet (no model) | n/a |

## Candidates (not done; each needs a before/after)
- Build: `--resume` checkpoints (Codex) instead of full rebuilds when only a few models change. The last six
  Claude rebuilds were full (~6 min each) for changes touching 2–118 models.
- Route runs: the prompt search takes up to 9 screenshot+OCR rounds per door; start the tilt from the last
  successful pitch per cell.
- Remote usage: Codex 102 M input tokens in 24 h, 96% cached; Claude 160 M cache reads; Grok 73 M input.
  Long single sessions dominate. Shorter sessions with handoff notes may cut cached-context cost; measure first.

## Entries

### 2026-10-09 Claude: model load without memory mapping (local team)
Before: `lms load qwen3-14b --gpu max` -> LM Studio held 10.5 GB of system RAM for a model fully in VRAM; RAM 88.2%,
the guardian held every request (restrict/block). After: `tools/ai-team/load_model.py` (tryMmap=false,
keepModelInMemory=false) -> LM Studio 5.4 GB, RAM 71.4%, VRAM unchanged (10,890 -> 10,930 MiB). Requests admitted.

### 2026-10-09 Claude: 32K context at the cost of 16K (local team)
OpenCode's own system prompt + tools is ~12K tokens; at 16K context it compacted and re-continued in a loop.
Before: 16K, f16 KV cache, VRAM 10,952 MiB. After: 32K, q8_0 K/V cache + flash attention, VRAM 11,061 MiB (90.1%,
below the 92% restrict level with a resident model). Twice the context for +109 MiB.

### 2026-10-09 Claude: wake remote agents with a fresh session, not a fork
Before: `wake_agent.py` forked Codex's last session; one headless turn reported **5,677,999 tokens used** (the
whole long session history replayed) and, in the default read-only sandbox, could not fix or post anything.
After: default is a fresh session with a short brief pointing at #32 / handoff / AGENTS.md, with workspace-write +
network. `--fork` stays available when the old context is really needed. After (measured): the next fresh-session wake fixed the bug it was briefed on, ran the tests and the guard, and
opened PR #34 using **54,793 tokens** (99% less than the fork's 5,677,999).

## 2026-11-03 skyrim_hairs --diagnose: hair texture conversions and repeated shaping (Claude)
Owner: the Nord / Imperial --diagnose run (48 hairstyles x 3 copies, 61c5ff1) was still going after 15+ minutes.
Causes: every Skyrim-blended hairline got its own full-atlas conversion (region keyed by its exact UV points), the
'rough' copies re-converted every texture under a new name, and each copy re-ran the whole shaping (follow head,
conform, layers, fit report) on ~10k tessellated vertices. Now: regions keyed by the 1/16-texture cells they touch
(hairlines sampling the same part share one material), setting-only copies write a new .mat on the same textures
(skyrim_hairs.settings_variant), and the copies reuse the hairstyle's shaped mesh. Measured (scratchpad
bench_hairmats.py: 12 blended hairline shapes in one area of a 1024x1024 texture, each with a 'rough' copy, texconv
stubbed): before 24 texture conversions, 11.6 s; after 4 conversions, 1.9 s. Shaping per hairstyle in --diagnose:
3 runs -> 1 (by construction; not timed on the owner's data).

## 2026-11-05 strand cards: skip smoothing lines that are clearly taken, and fewer copies on request (Claude)
Owner: the round 7 build (--strand-cards, three card copies per hairstyle) took about an hour; the first hair builds
took ~2 minutes (no cards, no tessellation). Profile (scratchpad hash_cards.py, the test shell, 5 layers, 3500 card
cap): ~85% of traced lines are rejected by the spacing test, after smoothing each; vertex offsets were re-summed
per card. Now a raw trace on >= 80% kept cells is dropped before smoothing (PRE_OCCUPIED) and offsets are a running
count. Measured: dense 4.48 s -> 3.73 s, thin 4.40 s -> 3.50 s with scipy; 14.6 s -> 12.0 s numpy-only (cards
1654 -> 1674 / 1674 -> 1665: a few lines the old order smoothed then rejected are now dropped first, so the rng draws
shift; same method). Bigger levers, not code: scipy installed (cKDTree; 4.5 s vs 14.6 s here, the gap grows with
the hair's size) and --strand-copies (build only the copies being judged: each grows its own cards).

## 2026-11-15 Skyrim model checkpoints: hash only the converter's own modules (Claude)
Owner: "we don't want to rebuild unnecessary steps". The Riverwood build's step 2 (make_skyrim_objects convert
--resume) printed "reused": 0 and reconverted all 265 models (71.8 s, owner's log 2026-11-14) although no model or
converter code had changed: the checkpoint signature hashed every src/fo4sf/*.py, so the day's retarget /
bodyprofile commits invalidated every model. Now it hashes only the modules the conversion imports (converter_modules:
the import closure of skyrimconvert, convert_static, bsa, checkpoints; checked against sys.modules after importing
them: nothing loaded is missing, 6 lazily imported extras are hashed too). Before: 265 converted, 71.8 s on a build
with no converter change. After: one more full conversion (the signature's file list changed), then expected 265
reused on the next builds; to be confirmed from the owner's next two build logs.
Measured (owner's Riverwood build log, 2026-11-15, after commits to retarget / furniture / af_pose only): step 2
"reused": 229 of 235 assets, "seconds": 18.0 (before: 0 reused, 71.8 s). The remaining 6 and the 30 failures
(15 "no triangle geometry", 15 effect-shader-only shapes: models with nothing to convert, retried each build) are not
checkpointed; 265 vs 235 is the models / assets count of the batch.

## 2026-11-15: flame iterations rebuilt everything
Owner: "are we doing the thing where we're running more steps than needed for the test again". Yes: each flame test ran
the full riverwood_doors.ps1 (interior export, all model conversion, navmesh, NPCs, furniture, plugin build, install),
and every flame change reconverted all ~265 models (skyrimfire.py was in the global checkpoint signature through
skyrimconvert's imports; -FlameStyle too). Changes:
* `make_skyrim_objects.py`: skyrimfire and the flame style left the global signature (FLAME_MODULES); a model the
  flame code touches (flame shapes / cards, skipped effect shapes, AddOnNodes) carries `flame_key` (skyrimfire digest +
  style) and is redone alone when it changes; the convert summary reports `flame_models_redone`.
* `riverwood_doors.ps1 -AssetsOnly`: convert (resume) + install only; the plugin from the last full build is reused.
  Both modes now print their total seconds.
Measured: before = the owner's full build 2026-11-15 22:57 with every model reconverting (the converter itself had
changed): **117 s** (convert 68.1 s of it, 265 models, reused 0). Full build with the
checkpoints reused (2026-11-16, -FlameStyle particles, 229 of 235 models reused, convert 22.8 s): **72 s**. After =
the next -AssetsOnly flame run ("assets-only build: N s") - pending. This commit itself changes skyrimconvert.py and
make_skyrim_objects.py, so the next build reconverts every model once more.
First -AssetsOnly run (owner, 2026-11-16 10:14): **81 s** with every model reconverted again (convert 64.6 s, reused 0,
224 assets): the commit before it had changed skyrimconvert.py (layered fire), which is in the global signature. Still
below the 117 s full build with everything reconverting (no export / navmesh / NPCs / plugin). Rule for flame rounds:
keep the change in skyrimfire.py (per-model flame_key) when it can live there; the tint / candle-size round after it
touches only skyrimfire.py, so the next -AssetsOnly run redoes the flame models alone - its time is the "after".
After (owner, 2026-11-16 10:19, -AssetsOnly, skyrimfire.py-only change): reused 196, flame_models_redone 25, convert
**21.5 s** (before: 64.6 s with everything reconverted; 68.1 s inside the 117 s full build). Convert is now 3x faster for
a flame round. The total "assets-only build: N s" line was cut off in the paste; the rest of the run is install only.

## Riverwood build: flame methods out of the global signature, quieter window, step times (2026-11-21)
Owner: "does it need to do all of this every time we test". Measured before (owner's build 10:59, after the soft-candle
commit put flame code in skyrimconvert.py): full build **145 s**, convert 76.5 s with "reused": 0 (all 250 models
reconverted); the build before it (10:21, nothing in the converter changed): **62 s**, convert 7.3 s, reused 249. The
window: 823 lines.
Changes: (1) the converter's flame methods moved to src/fo4sf/skyrimflames.py (FlameMixin), which is in
make_skyrim_objects.FLAME_MODULES: a flame change now redoes the flame models only (as skyrimfire changes did,
2026-11-16: convert 64.6 s -> 21.5 s); (2) riverwood_doors.ps1 runs every python / dotnet step through Run: full output
to <Work>\logs\riverwood_doors_last.log, the window filtered by tools/owner/log_noise.txt (the 10:59 log: 823 -> about
105 lines, every FAIL / error / WARNING kept), -FullLog prints everything; (3) each step's time and a table at the end.
This commit changes skyrimconvert.py once more (the methods left it), so the next build reconverts everything one last
time. After: the first build after a flame-only change (its step table: "2. convert" time and reused count) - pending.
Owner's first run after it (2026-11-21 11:20, -AssetsOnly with the soft candle v2 change): window 20 lines; convert
70 s (every model, the expected one-time reconvert), install 5 s, total 87 s. The 12 s outside the steps: the
navmesh_defaults.json search of all of C:\Modding ran before the -AssetsOnly branch; moved into step 1 (the full build
only). After for the flame-only case: still the next flame change.
Owner's run 2026-11-21 11:49 (-AssetsOnly, soft v3): convert **74 s**, every model again. Cause: the soft v3 commit
added --candle-exposure to make_skyrim_objects.py, and the whole script file was in the checkpoint signature. Now only
the convert path counts (convert_source: cmd_convert, the functions it reaches, the constants they read, compared as an
ast without comments or line numbers): new options in main and the lod / stage / check commands no longer reconvert.
The signature's shape changed with it, so the next build reconverts once more. After (-CandleExposure N, flame_key only):
pending.
After (owner, 2026-11-21 12:52, full build with the lighting change: skyriminterior / lightmodel / PluginSpike, no
converter change): convert step **15 s** (200 / 265 models at 11 s: checkpoints reused) against 70 - 77 s in the three
runs that reconverted everything; full build **80 s** (before: 145 s). The window: about 130 lines with step times.
Regression (owner, 2026-11-21 13:12): convert **73 s**, every model again: the ambient-cube commit added a DDS writer to
src/fo4sf/textures.py, which skyrimconvert imports (in the checkpoint signature). Rule from it: code the converter does
not run goes in a module it does not import (the cube writer is used only by make_skyrim_interior). Not moved back:
moving it would change textures.py again and cost one more full reconvert.


## 2026-11-22: terrain_blend with aligned texture positions
- Owner's terrain_blend.ps1: 8.2 min (one pass) -> 14.7 min (two passes, raster slot plan). The map-wide slot plan
  adds about 32 s per 144 x 144-quadrant tile (synthetic, measured here); owner's run: 15.5 min (from 14.7).
