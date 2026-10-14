# Research log

New findings go here (newest first). Each entry: question, method, evidence, **status**: verified /
supported hypothesis / unresolved. Older research lives in docs/JOURNAL.md and docs/spikes/; link, don't copy.

## 2026-10-12 Claude: correction, which teleports raise "Boundary Reached" in a merged overlay
- Question: core64c's first plan (PR #76) and PR #74's commonwealth-scale.md said a single teleport more than about
  4 cells from where the player stood raised "Boundary Reached", and that core64b's 300 m hops were verified safe.
  What do the runner reports actually show?
- Method: `scripts/terrain/teleport_audit.py` (new, synthetic test `test_teleport_audit`) rebuilds every teleport of
  the eight overlay queues (core64, core64b, exp2b, exp2b2, exp2b3, exp2c, exp2d, exp3) from spec.json + obs.json,
  hops as qstep.ps1 makes them, and judges it by the read that follows; counted only from a position where the
  previous teleport landed. qstep types setpos x, then y, then z, so each setpos moves one axis.
- Evidence (**verified** counts): of 145 teleports that moved the player at most 2 cells (100 m) along each axis, 144
  landed (the other in exp2b's second attempt, where the player fell through the world at most points); of 28 that
  moved 3 or more cells, 11 relocated the player 8.2 to 11.8 km further along that axis or hung at the drop height
  (all 6 in core64: 292.6 m east, 303.5 m south, 296.2 m west and three diagonals of 3 to 4 cells), 17 landed. In
  exp3, 250.5 and 267.0 m single-axis moves within 2 cells landed and a 248.7 m move across 3 cells hung. core64b's
  hops were at most 187.4 m per axis.
- Status: "about 4 cells" and "300 m hops are safe" **refuted**; a per-setpos distance limit (230 to 292 m, which
  core64 alone fits) **refuted** by exp3; "at most 2 cells per axis lands, 3 or more is a risk" **supported
  hypothesis**; the mechanism (a 5 x 5 loaded grid?) **unresolved**. core64c's plan now keeps every teleport within
  200 m per axis (docs/terrain/core64c.md "Teleport rule"); PR #74's commonwealth-scale.md still states the old claim.

## 2026-10-12 Claude: core64c, every Fallout4.esm exterior object of the 64-cell core on core64, staged
- Question: can ALL Fallout 4 exterior objects of the core (which covers the whole playable Commonwealth) go onto the
  core64 terrain as one experiment, how large is that, and what has to give? Write-up:
  [docs/terrain/core64c.md](../terrain/core64c.md).
- Method: `Fo4Land export-exterior` in 11 bands, `scripts/terrain/make_core64c.py` (select, measure, stage, check),
  `convert_batch.py --prefix fo4core --max-texture` (new: top mip levels dropped per texture kind, full and written
  size logged), `dotnet/TerrainOverlays` objects mode (new), synthetic tests `test_make_core64c`, `test_texture_cap`.
  Staged `C:\Modding\staging\terrain_core64c`. Not deployed, not run in game.
- Evidence:
  - **verified**: 706,579 FO4 references in the covered cells (701,754 placed objects + 4,825 actors / hazards /
    traps); 649,596 convert-eligible references of 11,887 models; 56,983 skipped with a reason (decals 13,118, lights
    6,275, idle markers 5,828, power lines 4,982, editor markers 13,542, actors 3,685, trigger volumes 2,414, effects
    2,087, water planes 721, ...); 11,769 models convert and 118 do not (exactly the dry run's prediction), so
    **648,358 references** are placed (1,238 more skipped as `conversion_failed`). Conversion 2,499 s, one process.
  - **verified** (directory listing): every large vanilla Starfield archive is 4,294,061,043 to 4,294,946,755 bytes,
    never 2^32 or more. **unresolved**: whether the engine reads past 4 GiB, and whether numbered per-plugin archives
    (`.* - Main[0-9]*\.ba2` in Starfield.exe) load.
  - **verified** (dry run of the converter's material logic over the FO4 texture archives' DX10 records): 2,632
    materials, 8,635 textures, 7.30 GiB at full resolution; the converted set at full resolution with meshes,
    geometries, terrain and materials is 8.47 GiB (an earlier "about 8.3 GiB" left out the terrain and materials).
    **supported** (estimate): a
    split into the 15 occupied 1.6 km regions needs 28.8 GiB (shared materials repeat) and the four central regions
    5.6 to 6.2 GiB each, so a region split does not fit 4 GiB archives either.
  - **verified**: with per-kind caps (color 1024, normal 512, rough 256, opacity 512 px; top mip levels dropped) the
    converted textures are 2.42 GiB (7.26 GiB before the caps, logged per texture); the Data tree is 3.63 GiB and
    Archive2 with the installer's arguments builds one stored archive of 3,899,305,077 bytes (51,821 entries, 0 packed).
  - **verified**: `FO4TerrainCore.esm` 46,114,630 B = core64's 4,102 records, all unchanged, + 11,699 STAT + 70 DOOR
    + 648,358 REFR in 1,708 cells (up to 6,049 per cell); BTD, mask and Mars plugin byte-identical to core64; 0 missing
    model, geometry, material or texture files.
  - **verified**: BTD minus FO4 LAND under all 648,358 origins: median 2.78 mm, p99 86.7 mm, max 3.19 m; 97.3 % within
    5 cm, 673 above 0.25 m. **supported**: the tail is steep FO4 relief (median 3.54 m per terrain quad there, 0.46 m
    overall: quarry walls, cliffs, terrain under building floors) rounded off by the 0.78 m BTD grid.
  - **verified**: plan of 3 entries (terrain probes clear of objects; the Sanctuary player house, Red Rocket shop and
    Concord museum roofs, 4.72 to 14.10 m above the terrain under the landing disc, each dropped on twice;
    informational probes, screenshot spots only with `stage --views`), every teleport at most 2 cells per axis with
    19 terrain waypoints and no runner hops (fix pass, entry below); the judged roofs equal FO4's own collision within
    0.045 mm (the museum's compound bodies through Codex's `fo4_compounds.decode_body`); 252 of 252 offline checks.
- Status: offline **verified**; everything in game **unresolved** (load and streaming of ~1,700 populated cells,
  frame time, whether objects merge with the terrain's offset everywhere, night-time screenshots).

## 2026-10-11 Claude: core64, one 64-cell Commonwealth overlay staged
- Question: does ONE large overlay (option a) load its real heights everywhere around a single arrival? exp2b (one
  29-cell overlay, stored BTD) read FO4 heights within 0.08 m and FO4 objects within 0.02 m in game; exp3 (four
  14-cell overlays) read real terrain only in the arrival tile, probes 500-700 m away in the neighbours hung at the
  drop height even after the runner's two 8 s re-reads, so separate overlays cannot be walked between.
- Method: `make_cw_overlays.py build --plan rays` (new: one overlay, `--world`, `--coc`, `--btd-copy-meshes`, ray
  entries), `dotnet/TerrainOverlays`, `make_cw_overlays.py check` (new: ray entry contract, COC marker, archive inputs,
  CNAM uniqueness), an Archive2 dry run into the scratch folder, 8 new synthetic tests (43 in test_overlay_grid).
- Evidence (**verified** offline, `C:\Modding\staging\terrain_core64`): FO4Core_Commonwealth, 64 x 64 cells = CW
  cells -32..31 (6.4 km, local frame = FO4 / 70), BTD 103,172,485 B, range -120 / 503 m (step 9.506 mm), Absolute
  (INAM 1, HNAM 0), mask ring 255 on all four edges (6400 px BC4, 20,480,128 B); FO4TerrainCore.esm 183,160 B (4,096
  cells), FO4TerrainCore_Mars.esm 6,512 B (MarsPlanetData CNAM 10 vanilla + 1 at exp2b's lat/long 0.3, -1.2, unique,
  nearest other entry 33,561 cells away). Check 208 of 208; 37 plan points decode within one step (worst 9.29 mm).
  Archive2 dry run: 3 entries, all stored (packed 0), byte-identical to the staged files, 226,825,369 B. Build 9.3 s,
  peak working set 2,049 MiB (commit 2,788 MiB); rebuild byte-identical.
- **unresolved** until the run: whether a 64-cell overlay activates and streams everywhere (6 entries, one direction
  each from the Red Rocket arrival, probes at 0 / 200 / 500 / 1000 / 2000 / 3000 m where inside, plus Sanctuary,
  Vault 111, the Sanctuary bridge and Concord).

## 2026-10-11 Claude: the whole Commonwealth at Starfield scale
- Question: can the whole Commonwealth (LAND 192 x 192 FO4 cells, 11.23 km) become native Starfield terrain with
  exact geography, as one overlay, a grid of overlays, a custom planet surface or static meshes, and what limits the
  size? Write-up: [docs/terrain/commonwealth-scale.md](../terrain/commonwealth-scale.md).
- Method: raw scans of Starfield.esm (PNDT, SFBK, SFPT, SFTR, WRLD) and the BTD header survey; INI defaults decoded
  from the setting initialisers in Starfield.exe and the CK (code that references each name string); Fallout4.esm
  placed-reference extents; fits of lat/long -> planet cell against the two measured registrations; vanilla overlay
  clusters under a true-scale model. Then `src/fo4sf/overlay_grid.py`, `scripts/terrain/make_cw_overlays.py`,
  `dotnet/TerrainOverlays`, `tests/test_overlay_grid.py` (35 after QA's review), and experiment 3 staged in
  `C:\Modding\staging\terrain_exp3`. Scratch scripts in `C:\Modding\research\terrain\scale\`.
- Evidence:
  - **verified**: overlay blocks are 3 to 14 cells (430: 207 / 121 / 77 of 3 / 4 / 5, two of 14); procedural surface
    blocks 14 (616) and 26 (217) cells; the 108 BTDs of 100 x 100 cells are editor / test worlds with the default
    -500 / 1000 range, none registered on a planet.
  - **verified** values (meaning supported): `uDefaultGameTerrainWidthInCells` 100, `uPlayableSpaceOverlayCellBuffer`
    5, `uOverlayMergeZoneSize` 1, `uBlockSize` 10, `uBlockMergeZoneSize` 2, `uPlanetBiomMapFaceDim` 256,
    `uAlignment:Overlay` 4; CK `iBlockCutRecommendedMaxDimensionExclusive` 6 (the "maximum recommended cut
    dimensions" message).
  - **verified**: PNDT `CNAM` = latitude first, then longitude, radians (Earth overlays at Kyoto, Hong Kong, Cairo, St.
    Louis, Orlando; CydoniaCity at real Cydonia). Mutagen's names are swapped.
  - **verified**: the playable Commonwealth (cells with >= 20 references) is FO4 x -34..31, y -39..31 = 39 x 42
    Starfield cells; the LAND grid is 114.
  - **unresolved**: the absolute lat/long -> planet cell rule (0 of 7 projections x 13 scales x 20 origin grids fit
    World01 (+30, -35), LC172World (-5, -23) and exp2b (-12, -27)). World01's (+30, -35) holds for the first attempt
    of all five registered runs only; the three second cocs in the same session arrived at non-whole-cell offsets
    (**unresolved**). **supported**: true planet scale locally, bounded only: Cydonia's 8 overlays fit one landing
    without overlap for scale 0.5 to about 1.1 to 1.2.
  - **verified** (raw BA2 headers): the terrain-only vanilla archives (Terrain01..04, TerrainPatch) store all 2,004 of
    their BTDs uncompressed; SFBGS00D Main stores its 108 BTDs uncompressed too, but stores all 11,974 of its entries
    that way, so it says nothing about BTDs in particular; Meshes01 is fully packed; our `--pack` archive held the BTD
    zlib-packed (27,375,606 of 27,612,888 bytes). exp2b attempt 1 (runner obs.json) read z = -116.00, the BTD
    minimum, at 14 of 14 probes, the spawn and the beyond probe outside the overlay; attempt 2 read its spawn mid-fall
    (-354.13), started every drop near -309 m, and 10 of 14 probes fell through (no evidence either way). **unresolved**: why the BTD
    read flat (packed BTDs not readable is one hypothesis; the BTD not used at all is not excluded; exp1c's flat -13.94
    is not raw 0 of its -500..1000 range). The installer stores archives uncompressed since `claude/test-queue`
    f210b91; the rerun exp2b3 is queued and gates experiment 3.
  - **verified** (runner obs.json): our persistent anchors read back their unmerged local position in 4 of 4 attempts
    (exp1d a1, a2; exp2b a1, a2); the vanilla LC172World anchor moved with its merge. So experiment 3 no longer reads
    one tile's anchor from another tile's landing (those "position" entries could not measure anything): every entry
    uses the coc'd tile's own spawn (x, y) and a z_ref probe, and three locate transects find where each tile really
    sits from the heights read (`make_cw_overlays.py analyse`; on simulated runs over the real BTDs it recovers H_ll,
    off-by-one, scale 0.5 and scale 1.2 placements uniquely).
  - **verified** offline: experiment 3 (2 x 2 tiles of 14 cells, Sanctuary / Vault 111 / Red Rocket), re-staged: 9
    entries, 115 points, 490 of 490 checks, worst point 5.167 mm (step 5.173 mm); BTDs and plugins byte-identical to
    the first staging; masks north / south symmetric (mask row order unresolved); synthetic test: four tiles side by
    side = one BTD of the region, sample for sample.
- Status: recommendation (one overlay of the playable core plus surroundings, grid of 14-cell overlays as fallback)
  is a **supported hypothesis** pending exp2b3 and exp3 in game. Why exp2b read flat, landing size, seam blending, the
  lat/long rule, large-overlay behaviour, the even-size grid origin and the mask row order are **unresolved**.

## 2026-10-11 Claude: terrain experiment 2c, the FO4 objects around Red Rocket on the native terrain
- Question: can the real FO4 exterior references (cells x -20..-15, y 16..21) be placed on the exp2b terrain so the
  runner measures object-on-terrain alignment, and what does the converted collision say they stand on?
  Write-up: [docs/terrain/experiment2c.md](../terrain/experiment2c.md).
- Method: new `dotnet/Fo4Land export-exterior` (Fo4Export's serializers compiled in unchanged), `src/fo4sf/exterior.py`
  (skip reasons, placement, surface queries), `src/fo4sf/sfbodies.py` (reads back converted collision),
  `convert_batch.py --prefix`, `dotnet/TerrainExp2` objects mode, `scripts/terrain/make_exp2c.py` (select / stage /
  check); synthetic tests `test_exterior`, `test_sfbodies`, `test_make_exp2c`, `test_batch_prefix`. Staged
  `C:\Modding\staging\terrain_exp2c`. Not deployed, not run in game.
- Evidence:
  - **verified**: export = 8,960 references + 48 actors, the same 9,008 FormIDs, cells and positions (0.004 units)
    as the raw Python reader; 496 persistent references live in the world's persistent cell.
  - **verified**: 8,069 placed (1,385 models), 939 skipped with a reason (decals, lights, power lines, markers,
    effects, triggers, actors, 15 models that do not convert, 2 water planes); trees convert (STAT + BSTriShape).
  - **verified**: converted collision read back = FO4's own (RedRExt_Workshop01: 5,898 triangles, 0 differ).
    Workshop01 has no floor; the shop floor is RedRExt_Workshop02 at origin + 0.0286 m. (Corrected in the fix pass:
    Workshop02 also holds the canopy roof; the COC marker stands 2 m above the terrain and the player falls 1.88 m onto
    the pump island, 0.117 m above the terrain.)
  - **verified**: clockwise heading (PluginSpike / routes.py): 33 references at floor height fall inside the shop
    footprint, 0 with the opposite sign.
  - **verified**: building z - BTD = -0.56 mm (FO4 LAND: 0.00 mm); BTD vs FO4 terrain under all 8,069 origins:
    median 1.43 mm, p99 56.6 mm, max 482 mm (sharp FO4 edge).
  - **verified**: raw walk: all 847 exp2b records unchanged, Mars plugin / BTD / mask byte-identical, 8,071 REFR in
    16 cells as written, 0 missing geometry / material / texture files; 109 checks PASS.
- Status: offline **verified**. Whether overlay references merge with the terrain's offset, texture archive needs,
  object bounds in exteriors and the capsule radius used for point choice are **unresolved** (in-game run pending).
- Fix pass after QA (same day): the first plan lost the runner's new `z_ref` key (its entries copied six keys by
  hand), judged points 0.10 to 0.31 m above the terrain that the 0.5 m tolerance cannot tell from terrain, and mixed
  terrain probes with object probes, while exp2b's first attempt read flat ground (-116.00, the BTD minimum, at all
  14 probes) with its anchor unmerged. Now (**verified** offline, `offline_check.json` 137 checks PASS):
  - every entry carries every key of the base entry and has its own terrain reference `zref_ground` as `z_ref`;
    four entries: terrain gate, object tops >= 1.0 m above the terrain, shop floor (informational), informational;
  - with the runner's own formula: entry 1 fails on flat ground (5.49 m), entry 2 fails without objects (15.99 m),
    entry 3 passes either way (0.142 m: informational); the integ runner plans all four tests with `z_ref`;
  - the judged tops and the floor equal FO4's own collision (source NIFs, `routes.collision_bodies`) within 0.035 mm,
    all on layer 1; the low-drop entry's teleport positions are clear with a 0.4 m x 1.8 m cylinder (walls included);
  - `exterior.place` takes the cell after the rigged-door hinge shift (door `077A83` moved from cell (-10, 10) to
    (-10, 11)); `check` tests every reference's cell against its written position;
  - re-staged on `terrain_exp2b2` (exp2b + BTD also under `meshes/terrain`); not queued until an exp2b-family run
    shows the BTD relief (**unresolved**: compressed BTD storage is the supported cause, PR #67).

## 2026-10-11 Claude: overlay record fixes
- Question: in which records do our terrain experiment plugins differ from vanilla unique overlays, and what must
  SFBK `FNAM` hold? Write-up: [docs/terrain/overlay-records.md](../terrain/overlay-records.md).
- Method: raw walks of Starfield.esm (SFBK, WRLD, LCTN, PNDT, STAT) and per-cell statistics of the raw u16 heights of
  every decodable vanilla BTD with 1..30 cells (1,711 SFBK; scratch scripts, outputs not in the repo); vanilla overlay
  masks decoded with the new BC4 decoder. Then `src/fo4sf/overlay.py`, `scripts/terrain/overlay_records.py`,
  `dotnet/TerrainExp1` overlay mode, `dotnet/TerrainExp2` params, `make_exp2.py restage`, `tests/test_overlay.py`.
  Staged `C:\Modding\staging\terrain_exp1d` and `terrain_exp2b`. Not deployed, not run in game.
- Evidence:
  - **verified**: `FNAM` = `DNAM.x * DNAM.y` u16 in all 1,730 vanilla SFBK with an FNAM. Value = raw height of each
    cell's south-west corner sample, cells from the south row: every cell exact in 1,464 of 1,711 records, 94.6 % of
    all cells; min / max / mean / median / midrange / centre / north-first order: 0 records exact. lc172world 9/9,
    akilacity 89 % of cells, NewAtlantis 91 %, lc001world 4/25.
  - **verified**: all 430 overlay WRLDs have `XLCN`; `LocTypeOverlay` on the location in 11 of the 72 registered
    ones (LC172World among them), city / settlement keywords on the rest. LC172WorldLocation: parent
    `SSol_PMars_Surface` 01B736.
  - **verified**: vanilla masks are DNAM cells x 100 px, legacy `BC4U`, one mip, in a General BA2; ours match the
    format. `INAM` 1 (Absolute) in 10 vanilla blocks, `HNAM` -239..0; 1,743 Relative.
  - **verified**: PNDT `CNAM` entry = f64 (Mutagen Longitude), f64 (Latitude), u32 WRLD; Mars 10 entries + ours.
  - **verified** (offline check, both folders PASS): FNAM 50 B / 1,682 B equal to the rule for every cell, XLCN ->
    LCTN (2CA99D, 01B736), INAM/HNAM 0/0 (exp1d) and 1/0 (exp2b), persistent XMarker anchor `01000800`
    (plan `02000800`), Mars entry, mask decodes exactly, plan points within one quantisation step.
- Status: records **verified** offline. Whether any of the four differences matters in game, the meaning of `HNAM`,
  the stale FNAM of 247 vanilla blocks, mask row order and the run-time load-order byte (02 assumed) are
  **unresolved**.

## 2026-10-11 Claude: terrain experiment 2 staged
- Question: can the real Commonwealth terrain around Red Rocket be one native Starfield BTD at absolute positions,
  ready for the unattended runner, whichever BTD lookup experiment 1 finds?
  Write-up: [docs/terrain/experiment2.md](../terrain/experiment2.md).
- Method:
  - `src/fo4sf/terrain_grid.py`: grid rule, choice of n, separable bilinear resampling with edge clamping, and
    interpolation rules for check points.
  - `scripts/terrain/make_exp2.py`: reads the FO4 cells with the PR #56 `fo4land` module, writes the BTD with
    `btd.py`, then `plan.json` and `expected.json`.
  - `dotnet/TerrainExp2`: writes the plugin from experiment 1's template.
  - Survey of the LTEX quadrant maps of the 753 top-level vanilla BTDs (scratch).
  - Staged in `C:\Modding\staging\terrain_exp2`. Not deployed.
- Evidence (**verified** offline):
  - n = 29: Starfield cells -14..14, samples -1400..1499.22 m. That covers the PR #56 patch plus 300 m.
  - FO4 cells x/y -24..25 (2,500) read, so the whole BTD holds real heights.
  - BTD 27,612,888 B. Heights -114.46..140.67 m, header -116/142, step 3.937 mm.
  - Base texture `001235C2` LDirtFootprints01: the base of 2,334,675 quadrants in vanilla BTDs, and the only texture
    of TempJemisonWorld.
  - Plugin 36,742 B, checked with a raw walk:
    - WRLD `FO4CW_Commonwealth`, overlay `BNAM` pointing to SFBK `ANAM Data\TERRAIN\FO4CW_Commonwealth.btd`
      (record path and name both match), `DNAM` 29 x 29, `ENAM` -116/142;
    - `NAM0`/`NAM9` raw -1400/1500 m (Mutagen shows metres / 4096);
    - 841 cells;
    - COC cell `FO4CW_RedRocketSpawn` (-10, 11) with a marker at (-989.03, 1147.20, 107.14).
  - 14 check points at FO4 vertices (Red Rocket, flat, slope, both seam kinds, resampled). The decoded BTD returns
    every expected height within 3.221 mm under bilinear and both triangle splits.
  - Over all 4,225 patch vertices: median error 1.58 cm, p99 13.4 cm, max 1.42 m at a 75 deg cliff.
  - Rebuilds are byte-identical.
  - SFBK `FNAM[0]` = the BTD's SW corner raw height in 3 of 3 vanilla blocks.
- Status:
  - BTD, plugin and plan are **verified** offline.
  - H (BTD z = FO4 z / 70) and the grid rule remain **supported hypotheses** until experiment 1 or 2 runs in game.
  - **Unresolved**: `FNAM[1..7]`, whether `SmallWorld` or 841 empty cells matter, FO4's triangle split, and cliff
    accuracy at a 0.78 m grid.
  - Next (plan): an exterior exporter for the Red Rocket statics. Fo4Export is interior-only.

## 2026-10-11 Claude: Starfield terrain architecture
- Question: how can native Starfield terrain carry the exact Commonwealth geography (S5 / WP-12)?
  Full write-up: [docs/terrain/architecture.md](../terrain/architecture.md).
- Method: raw record walk of both ESMs; new read-only SfInspect commands (`wrld`, `sfbk`, `planetworlds`, `wcells`,
  `form`); index-only listing of the terrain BA2s and a 44-byte header survey of all 2,112 `.btd`; BTD decoder after
  fo76utils (MIT) checked byte-for-byte on vanilla files; ref-vs-terrain fits; xEdit's Starfield definitions read for
  field names; FO4 `LAND.VHGT` decoded for all Commonwealth cells.
- Evidence: Starfield.esm has 0 `LAND` (Fallout4.esm 37,020). 430/433 WRLD point through an overlay component to an
  SFBK whose `ANAM` is `Data\TERRAIN\<EditorID>.btd`; 72 WRLD are registered by planets (`PNDT.MasterWorldspaces`,
  lat/long). BTD: 128 samples per 100 m cell, u16 heights linear in metres between a per-file min/max, LOD0-4,
  vanilla up to 100 x 100 cells. Commonwealth LAND: 192 x 192 cells, -118.86..641.03 m.
- Status: format, record chain and sizes **verified**; height scale in metres and grid alignment (BTD cell i = world
  cell i - n//2) **supported hypothesis** (pad at 111.4 m vs refs at 112-113.5 m; 130/133 NewAtlantis object cells inside
  the predicted footprint); whether a plugin worldspace with its own BTD loads, and whether it needs a planet entry,
  **unresolved** until experiment 1 (staged in `C:\Modding\staging\terrain_exp1`, not deployed). Recommendation:
  option A, a dedicated worldspace with a native BTD.

## 2026-10-11 Claude: FO4 terrain source patch
- Question: can we read absolute Fallout 4 terrain heights for a small patch, and prove them right, by reusing
  existing work before writing a LAND parser?
- Method:
  - Read fo76utils `fo4land` (MIT, commit `c52da18`) as the reference. It cannot be built here: there is no
    compiler or scons, and nothing was installed.
  - Wrote `src/fo4sf/fo4land.py`, which follows its VHGT algorithm, and `dotnet/Fo4Land`, a Mutagen-based second
    decode.
  - Extracted cells x -18..-17, y 18..19 of `Commonwealth` around the Red Rocket Truck Stop
    (REFR `000211C0`, `RedRExt_Workshop01`).
  - Details and commands: [docs/terrain/source-patch.md](../terrain/source-patch.md).
- Evidence (report.json; all **verified**):
  - Python vs Mutagen decode: max abs difference 0.0 over 4,356 vertices, and the same 1,315 refs.
  - All 1,315 temporary refs lie inside their XCLC cell (min margin 0.21 units).
  - Patch seams: max difference 0.0.
  - The Red Rocket floor z 7360 equals the terrain at its origin (residual 0). Over its footprint the max abs
    residual is 8 units.
  - 100 rocks, stumps, saplings and shrubs: z minus terrain median -7.4 units. Flipped or transposed grids give
    367-653.
  - Patch relief 1840 units, slope median 11.3 deg, max 76.5 deg.
  - Whole world: 36,864 cells. 649 of 73,344 neighbour seams (0.88%) do not match, the worst by 13,056 units in the
    far north-west (x -68..-62, y 76..77).
- Status: VHGT layout and orientation (row 0 = south, col 0 = west, height = 8 * (offset + accumulated gradient),
  origin = XCLC * 4096) are **verified** for Fallout4.esm.
  - The large maple trees sit 266 units deep. That they are planted deep on purpose is a **supported hypothesis**.
  - **Unresolved**: FO4's triangle split (bilinear vs either diagonal differs by up to 19 units at the refs),
    whether the big seams matter (are they in the playable area), and how any of this maps to Starfield terrain
    scale or format. 70 units/m is only the object scale.

## 2026-10-09 Claude: which FO4 collision bodies are movable?
- Question: how does an FO4 `bhkPhysicsSystem` mark a body as movable (pushable), so the converter can stop turning
  physics objects into fixed obstacles (Vault 114 door `05C7DC` is blocked by a ragdoll skeleton)?
- Method: compared `SkeletonClothed01.nif` (ragdoll) with `SubPlatformWall01.nif` (static) in the
  `hknpPhysicsSystemData` packfile, then scanned all 4,014 converted models (local script, not in the repo).
- Evidence: body cinfo +12 (u32) is a motion index: skeleton bodies 0..16 with 17 motion entries and 16 constraints
  (`hkpRagdollConstraintData`, `hkpLimitedHingeConstraintData`), layer 10; static wall `0x7FFFFFFF`, layer 1.
- Scan (motion index != 0x7FFFFFFF): 490 models / 5,340 placements with one moving body; 59 / 345 with several and no
  joints (cryo pods, roof hatches); 29 / 167 ragdolls with joints (skeletons, V111 gear-room gates, gurney).
- Status: "+12 = motion index, 0x7FFFFFFF = static": **supported hypothesis** (2 files). "Motion index means
  pushable": **refuted as stated**: placed Statics like `BldgShellWoodStairsRailing01` also have one, so it also covers
  keyframed / animated bodies. **Unresolved:** the motion entries' mass / motion type, which separates pushable
  (dynamic) from keyframed bodies.
- Follow-up (same day): system +32 holds motion *properties* (present only for dynamic bodies; values like 104.375 /
  31.57 / 0.1 / 0.05 identical in skeleton and pencil) and +48 the motion *cinfos*: u16 motion-properties id at +0,
  inverse mass f32 at +4. Skeleton: id 0, inverse mass 0.1 (10 kg); pencil: id 0, 2.0 (0.5 kg); stair railing and cryo
  pod: id 0xFFFF, inverse mass 0 (keyframed). Rule "dynamic = motion index != 0x7FFFFFFF, its cinfo id != 0xFFFF and
  inverse mass > 0": **supported hypothesis** (4 files, consistent across the scan). Rescan of 4,014 models: 373 single
  dynamic (4,642 placements: loose items), 22 multi-body without joints (156: breakable railings, gore), 29 ragdolls
  (167). Railings and cryo pods move to static, which is correct for them.

## 2026-10-09 Starfield `.af` animation header (door rigs)
- Question: what are the u16 fields at 0x28 of `open.af`?
- Method: compared four door families' `open.af` with their `characterassets\skeleton.rig` name tables
  (docs/spikes/WP-doors-research.md, "Header fields vs rig bone tables").
- Evidence: Akila 6 bones / field 6; generic 21/21; ship small 24/24; ship large 49/49.
- Status: field 2 = rig bone count: **verified** (4 of 4). Field 1 = format version: **supported hypothesis**.
  Field 3 = frame count: **supported hypothesis** (30 fps unconfirmed). Field 4: **unresolved**.

## 2026-10-09 FO4 precombine collision bodies with "shared vertex index out of range"
- Question: what primitive encoding do these `SCOL\CM*.NIF` bodies use?
- Evidence: 0 packed vertices, shared-index entries in triples (2130, start, x), primitives like (3,2,2,2);
  docs/JOURNAL.md "Precombine debris parts" and its correction.
- Status: **unresolved**. The "thin rods" reading was **refuted** (groups up to ~3 m in every axis).
