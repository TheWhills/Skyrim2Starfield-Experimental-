# Terrain experiment 2: real Commonwealth heights around Red Rocket as native Starfield terrain

Author: Claude, 2026-10-11. Branch `claude/terrain-exp2` (built on `claude/terrain-architecture` (PR #57) with
`claude/terrain-source` (PR #56) merged in). Status: **built and checked offline, staged, not deployed, not run in game**.

> **Follow-up (2026-10-11): experiment 2b** in [overlay-records.md](overlay-records.md) is this experiment with the
> overlay record fixes: SFBK `FNAM` = one raw height per BTD cell (1,682 B, the "connections" below were wrong),
> a Location, an overlay mask, Absolute alignment (`INAM` 1, `HNAM` 0), a Mars registration plugin
> (`FO4TerrainExp2_Mars.esm`) and a persistent anchor. Staged in `C:\Modding\staging\terrain_exp2b`. `make_exp2.py
> build` and `restage` now write that form; `C:\Modding\staging\terrain_exp2` is left as first built.

Labels: **verified** = measured here, number given; **supported** = supported hypothesis; **unresolved** = not known.
Offline checks are not in-game acceptance.

## What it tests
Experiment 1 ([architecture.md](architecture.md), section 5) asks whether a plugin worldspace loads its own BTD at
all, by record path or by name, and at what height scale, using flat test pads. Experiment 2 is the next step on
the same mechanism: **the real Fallout 4 terrain around the Red Rocket truck stop, at absolute positions, in one
29 x 29-cell native BTD**. It answers:

1. Does a large real-terrain BTD (27.6 MB, 841 cells) load and render like the 5 x 5 test BTD?
2. Hypothesis **H**: BTD height = world z in metres, and FO4 positions and heights convert at 70 units per metre
   (the repo's object scale). Then a player dropped at FO4 vertex (x, y) / 70 lands at FO4 height / 70.
3. Grid rule (supported, from PR #57): the BTD's south-west sample is n // 2 cells west and south of the world
   origin, with 100 m cells, 128 samples per cell and row 0 at the south edge.
4. Are there steps at the LOD0 block borders (Starfield 100 m cells) or at FO4 cell borders?

It is built so that it works **whichever BTD lookup experiment 1 finds**. The SFBK `ANAM` record path and the
worldspace EditorID name both lead to `Data\TERRAIN\FO4CW_Commonwealth.btd`, as for experiment 1's `FO4TX_World01`.

## Staged files (`C:\Modding\staging\terrain_exp2`, outside the repo)

| File | Bytes | Content |
|---|---|---|
| `FO4TerrainExp2.esm` | 36,742 | master Starfield.esm. The WRLD, SFBK, cells and COC ref below, with its own FormIDs from 0x800 and nothing shared with FO4Port.esm |
| `Data\Terrain\FO4CW_Commonwealth.btd` | 27,612,888 | 29 x 29 cells, 3,712 x 3,712 samples, version 6, heights -116..142 m |
| `plan.json` | 1,761 | runner input: COC, 14 check points, `drop_z` 150, `beyond` |
| `expected.json` | 11,518 | hypothesis, grid, coverage, LTEX, every point with metadata and the offline check |
| `exp2_params.json` | 487 | numbers the plugin builder reads (written by the Python step) |
| `README.txt` | 2,812 | manual console steps |
| `preview.png` | 270,403 | heightmap with the BTD cell grid and the check points (north up) |

The layout fits `scripts/game/exp_install.py` (branch `claude/test-queue`). That tool activates only the first
`.esm` and copies the `Data\` tree, here a single BTD. `plan.json` and the other top-level files are not copied
into the game.

## Grid and coverage
- Region that must have real heights: the PR #56 patch (FO4 cells x -18..-17, y 18..19, which is
  x -1053.26..-936.23 m and y 1053.26..1170.29 m) plus 300 m on every side. That gives x -1353.26..-636.23 m and
  y 753.26..1470.29 m.
- The grid is anchored at the world origin, so it must reach x = -1353 m on the west and y = +1470 m on the north.
  The smallest n that does is **n = 29** (`terrain_grid.choose_n`). With n = 29:
  - the samples run from -1400.00 to 1499.22 m on both axes;
  - Starfield cells **-14..14** (841);
  - this is within the vanilla maximum of 100 x 100 cells.
- FO4 cells read: **x -24..25, y -24..25 (2,500 cells)**. That is every FO4 cell under the BTD footprint, so the
  whole BTD holds real Commonwealth heights.
  - The minimum for the region alone would be x -24..-11, y 12..25 (196 cells). The other ~75% of the BTD would
    then repeat the nearest FO4 edge height in long streaks.
  - Reading the whole footprint costs a few seconds and keeps the area around the test true to the Commonwealth.
  - Edge clamping is still implemented and unit-tested: `--extract region`, or any sample outside the cells read,
    takes the nearest edge height. There is no extrapolation and no cliff.
- Resampling: bilinear on the merged FO4 vertex grid, done separably (`terrain_grid.resample_bilinear`), at each
  sample's world position times 70. Heights are FO4 units / 70.
  - FO4's own triangle split is still **unresolved** (PR #56). Bilinear is the choice for now.
- FO4 seams in the cells read (**verified**): 4,900 neighbour pairs, of which 42 vertices do not match. The worst is
  152 units (2.2 m), between cells (-15,-1) and (-14,-1), about 1.4 km from Red Rocket. The merged grid takes the
  south/west cell's copy.
- Heights -114.46..140.67 m. The header range is -116..142 m, so the **16-bit quantisation step is 3.937 mm**.

## Ground texture
- **`001235C2` `LDirtFootprints01`** (`Materials\Terrain\DirtFootprints01.mat`). In a survey of the quadrant maps of
  all 753 top-level vanilla BTDs (scratch `ltex_survey.py`, decoding rule from fo76utils `getCellTextureSet`), it is:
  - the base texture of 2,334,675 cell quadrants, 2,268,003 of them with no other layer;
  - the next most common base is `00010861` `LDefault006Base`, with 280,277 quadrants.
- `TempJemisonWorld`, the vanilla 100 x 100-cell world without a planet, uses it as its only texture.
- The BTD copies that file's layout exactly (**verified** by reading it):
  - its 7-entry LTEX table (`00010861 00010860 0001085F 0001085E 0001085D 0001085C 001235C2`);
  - quadrant bytes `1 0 0 0 0 0 0 0` (table index 7 - 1 = 6, which is `001235C2`);
  - all texture weights 0.
- No FO4 textures yet.

## Plugin `FO4TerrainExp2.esm`
- Built by `dotnet/TerrainExp2` with Mutagen. The template is the same as experiment 1's, the Mars landing world
  `LC172World` (02DF8C) and its block `OverlayBlockLC172World` (102382), so the two experiments differ only in the
  BTD and the cell grid. Biome, climate, water and flags are the template's (`SmallWorld`, no water: block `WHGT`
  -3.4e38).
- Raw record walk of the written file (`make_exp2.py check`, independent of Mutagen; **verified**):

| Record | Fields |
|---|---|
| WRLD `01000801` `FO4CW_Commonwealth` | overlay component `BFCB` `SNAM`/`PNAM` (template) `BNAM` = `01000800` (the SFBK); second `BNAM` = `002A3777` (Mars biome, template); `NAM0` = (-1400, -1400), `NAM9` = (1500, 1500) |
| SFBK `01000800` `FO4CW_CommonwealthBlock` | `ANAM` = `Data\TERRAIN\FO4CW_Commonwealth.btd`, `DNAM` = 29 x 29, `ENAM` = -116 / 142 (= BTD header, as in vanilla), `FNAM` = 8 raw border heights |
| CELL x 842 | 841 exterior cells -14..14 (empty) + the persistent top cell |
| CELL `0100088F` `FO4CW_RedRocketSpawn` | XCLC (-10, 11) |
| REFR `01000890` `FO4CW_RedRocketSpawnMarker` | base `000032` COCMarkerHeading at (-989.0286, 1147.2000, 107.1434) |

Details:
- `NAM0`/`NAM9` (object bounds) are raw metres. Mutagen shows them divided by 4096, so the template's -0.0488 /
  0.0732 are raw -200 / 300 m, matching its cells -2..2. Writing -1400/4096 produced raw -1400.0 (**verified**).
- `FNAM` ("connections") holds the corners and edge midpoints, SW, S, SE, E, NE, N, NW, W. Only the first value
  matches vanilla (the SW corner, 3 of 3 blocks checked: lc172world, akilacity, newatlantis). **Superseded**: vanilla
  `FNAM` holds one raw u16 per BTD cell, the SW-corner sample of each cell (exact for every cell in 1,464 of 1,711
  vanilla blocks; [overlay-records.md](overlay-records.md)), so this 16-byte `FNAM` has the wrong size. Fixed in exp2b.
- Spawn: the Red Rocket building `000211C0` origin is FO4 (-69232, 80304, 7360). Divided by 70 that is
  (-989.0286, 1147.2), in Starfield cell (-10, 11). The decoded BTD ground there is 105.1434 m (FO4 7360 / 70 =
  105.1429). The marker is 2 m higher, at 107.1434. The building itself is not placed in this experiment.

## Check points (`plan.json`)
- Every point is an exact FO4 vertex: position = vertex units / 70, expect = vertex height / 70.
- A vertex is eligible only if the decoded BTD gives its height back within one quantisation step under all three
  interpolation rules (bilinear and both triangle splits). So the expectation does not depend on how the engine
  interpolates BTD samples, and FO4's triangle split does not matter at a vertex.
- `shift sens.` is how much a half-sample (0.39 m) grid shift would move the reading on that slope.
- `drop_z` = 150 m (the highest point is 121.71 m). `beyond` = (-1500, 1147.2), 100 m west of the BTD's west edge.

| Label | x (m) | y (m) | expect (m) | kind / note | slope | decoded error | shift sens. |
|---|---|---|---|---|---|---|---|
| redrocket_1 | -989.2571 | 1146.5143 | 105.1429 | 0.72 m from the building origin | 0.0 | 2.34 mm | 0 |
| redrocket_2 | -989.2571 | 1148.3429 | 105.1429 | 1.17 m from the origin | 0.0 | 0.52 mm | 0 |
| flat_1 | -987.4286 | 1128.2286 | 105.0286 | 5 x 5 vertices level (forecourt) | 0.0 | 0.65 mm | 0 |
| flat_2 | -976.4571 | 1144.6857 | 105.0286 | 5 x 5 vertices level | 0.0 | 0.65 mm | 0 |
| slope_1_cell_-18_18 | -1009.3714 | 1075.2000 | 104.9143 | steepest eligible in FO4 cell (-18,18) | 28.6 | 1.26 mm | 0.21 m |
| slope_2_cell_-17_18 | -983.7714 | 1106.2857 | 100.5714 | cell (-17,18) | 25.9 | 1.65 mm | 0.19 m |
| slope_3_cell_-18_19 | -1044.1143 | 1153.8286 | 109.8286 | cell (-18,19) | 26.7 | 2.95 mm | 0.20 m |
| slope_4_cell_-17_19 | -947.2000 | 1141.0286 | 98.8571 | cell (-17,19) | 23.8 | 1.14 mm | 0.17 m |
| seam_fo4_west | -998.4000 | 1106.2857 | 100.3429 | 2 vertices west of FO4 border x = -69632 (-994.74 m) | 19.5 | 3.22 mm | 0.14 m |
| seam_fo4_east | -991.0857 | 1100.8000 | 99.5429 | 2 vertices east of it | 14.0 | 2.94 mm | 0.10 m |
| seam_sf_west | -1000.2286 | 1089.8286 | 100.4571 | 0.23 m west of Starfield cell border x = -1000 m (LOD0 block border) | 15.6 | 0.76 mm | 0.11 m |
| seam_sf_east | -998.4000 | 1089.8286 | 100.0000 | 1.60 m east of it | 18.7 | 0.81 mm | 0.13 m |
| resampled_sw | -1258.0571 | 857.6000 | 94.8571 | ~200 m SW of the patch, FO4 cell (-22,14) | 13.4 | 2.04 mm | 0.09 m |
| resampled_ne | -735.0857 | 1367.7714 | 121.7143 | ~200 m NE of the patch, FO4 cell (-13,23) | 14.1 | 2.65 mm | 0.10 m |

## Offline verification (verified)
- `make_exp2.py check` re-decodes the written BTD with `src/fo4sf/btd.py`. It checks each of the 14 plan points
  under bilinear and both triangle splits. The **max error is 3.221 mm**, against a step of 3.937 mm. The worst
  point is seam_fo4_west; bilinear alone gives 2.919 mm.
  - Spawn ground: 105.1434 m.
  - Two builds from scratch gave byte-identical BTD and esm files (SHA-256 compared).
- Header and LTEX checks:
  - range -116 / 142;
  - LTEX table as above, quadrant `1 0 0 0 0 0 0 0`, weights max 0;
  - re-decoding is exact by construction: the writer and reader round trip is tested in `tests/test_btd.py`.
- All 4,225 FO4 vertices of the patch (bilinear on the decoded BTD against the FO4 vertex height). Context only:
  these are not the plan points.

  | Slope | Vertices | Median | p99 | Max |
  |---|---|---|---|---|
  | 0-10 deg | 1,769 | 1.20 cm | 9.1 cm | 18 cm |
  | 10-20 deg | 1,709 | 1.76 cm | 11.2 cm | 22 cm |
  | 20-30 deg | 619 | 2.32 cm | 18.0 cm | 36 cm |
  | 30-45 deg | 110 | 3.53 cm | 20.6 cm | 26 cm |
  | over 45 deg | 18 | 55 cm | 136 cm | **1.42 m**, at a 75 deg cliff |

  A 0.78 m grid cannot hold FO4's sharp cliff edges. If that matters in game, the fix is to sample FO4's triangles
  (once the split is known) or to use a finer grid. It is not a bug: shifting the BTD grid by half a sample or a
  whole sample raises the median from 1.58 cm to 5.55 cm and 10.35 cm, so the generator and the checker agree on
  the alignment. This check is internal consistency, not in-game proof.

## Running it
**Unattended runner** (branch `claude/test-queue`). Run it after experiment 1, never with both installed:

    python scripts/game/testqueue.py plan-terrain --staging <FO4Port build dir> --exp-dir C:\Modding\staging\terrain_exp2 ^
        --out <queue dir> --plugins FO4TerrainExp2.esm
    python scripts/game/testqueue.py run --queue <queue dir>

- The runner COCs to `FO4CW_RedRocketSpawn`.
- For each point it teleports to (x, y, 150), waits, and reads `player.getpos`.
- It reports PASS when every point is within 0.5 m and within 2 m horizontally.
- It records a screenshot at `beyond`.

**By hand:** `C:\Modding\staging\terrain_exp2\README.txt`. In short:
1. Install the esm and the BTD.
2. `tgm`, then `coc FO4CW_RedRocketSpawn`, then `player.getpos z`, which should give about 105.14.
3. For each point: `player.setpos x/y/z`, land, then `player.getpos z`.
4. Look past x = -1400 m.

## Reading the result

| Observation | Meaning |
|---|---|
| All points within 0.5 m | Real terrain loads; H and the grid rule hold. Next: the Red Rocket statics (below) |
| All off by one constant | vertical offset (a world height origin or the SFBK alignment fields `HNAM`/`INAM`) |
| Heights scaled (read / expect constant) | Height mapping differs: x8 is fo76utils' FIXME scale, 0.7 would mean 100 units per metre |
| Slope points off by up to their `shift sens.`, flat points right | half-sample grid shift: sample centres, not corners |
| One seam pair differs, the rest pass | LOD0 block stitching (seam_sf) or FO4 border handling (seam_fo4) |
| Fell through (NOTERRAIN) | The BTD did not load. Compare with experiment 1: size (27.6 MB, 29 cells), `SmallWorld` with 841 cells, or the lookup path |
| Experiment 1 passes only with the Mars registration | Add the same `PNDT` entry for `FO4CW_Commonwealth` (an `FO4TerrainExp1_Mars.esm` copy) |

## Next step: Red Rocket exterior statics in this worldspace

> **Built (2026-10-11) as experiment 2c**, [experiment2c.md](experiment2c.md): `Fo4Land export-exterior`, the
> existing converter (`--prefix fo4cw`), and `TerrainExp2` placing STAT / DOOR records and references in exp2b's
> plugin (one plugin, exp2b's FormIDs kept), not PluginSpike. The plan below is the original sketch.

- `dotnet/Fo4Export` (Codex's, not changed here) exports **interior** cells only. `export <EditorID>` looks only at
  interior cells, and FO4 exterior cells mostly have no EditorID. Its `AllCells()` already walks worldspace cells,
  but only to resolve teleport dependencies.
- The exterior references already exist in the PR #56 tools:
  - `scripts/terrain/fo4_land_patch.py` writes `refs.json` with every REFR of the patch cells (1,315: base type and
    EditorID, position, rotation, scale);
  - `dotnet/Fo4Land` reads the same refs with Mutagen.
- Neither emits the schema v2 placement JSON that the cell converter consumes (model path, persistence, linked refs,
  teleports).
- `dotnet/PluginSpike` (Claude's) builds interior cells only (`Cell.Flag.IsInteriorCell`, interior blocks).
- Proposed order:
  1. A Claude-owned exterior exporter (an `export-exterior <world> <x0> <x1> <y0> <y1>` mode in `dotnet/Fo4Land`)
     that writes schema v2 JSON for FO4 cells x -18..-17, y 18..19. It should reuse Fo4Export's `ReferenceExport`
     by linking the source file, without editing it.
  2. Convert the referenced meshes with the existing asset pipeline.
  3. Teach PluginSpike to place those refs in `FO4CW_Commonwealth`. Each goes into the Starfield cell
     floor(x / 100 m), floor(y / 100 m), at FO4 position / 70, with z unchanged under H. The world blocks and
     sub-blocks are grouped as in TerrainExp2.
- If H holds, `RedRExt_Workshop01` lands with its floor exactly on the terrain: FO4 z 7360 = terrain, residual 0
  (PR #56), and 105.1429 m against the decoded BTD's 105.1434 m.

## Unknowns
1. Everything in game: whether it loads, H, the grid rule, seams, what lies beyond the edge. Experiment 1 comes first.
2. Whether `SmallWorld` (copied from the 5 x 5 template) limits a 29 x 29 world, and whether all 841 empty cells are
   needed. In vanilla akilacity, 55 of its 81 BTD cells hold references (`SfInspect wcells`); whether the
   other 26 have empty CELL records was not checked.
3. ~~The meaning of `FNAM` entries 2-8~~ (resolved: one value per cell, see overlay-records.md); the alignment
   fields (`HNAM`/`INAM`/`JNAM`) for a master worldspace (exp2b tests `INAM` 1 / `HNAM` 0).
4. FO4's triangle split, and cliff accuracy (above).

## Reproduce

    python scripts/terrain/make_exp2.py build --fo4 <Fallout4.esm> --sf-data <Starfield\Data> --out C:\Modding\staging\terrain_exp2
    dotnet run --project dotnet/TerrainExp2 -c Release -- <Starfield.esm> C:\Modding\staging\terrain_exp2
    python scripts/terrain/make_exp2.py check --sf-data <Starfield\Data> --out C:\Modding\staging\terrain_exp2
    python -m unittest tests.test_terrain_grid

The build step reads 2,500 FO4 cells and writes the 27.6 MB BTD in a few seconds. The scratch analysis scripts
(LTEX survey, FNAM comparison, error by slope) are not in the repo. Their outputs are in `C:\Modding\research\terrain\`.
