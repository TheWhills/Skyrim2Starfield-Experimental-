# The whole Commonwealth as native Starfield terrain: size limits, options, generator, experiment 3

Author: Claude, 2026-10-11. Branch `claude/commonwealth-terrain-scale`, stacked on PR #64
(`claude/terrain-overlay-records` at e8c0171, which contains #60, #57 and #56). Starfield 1.16.244. Nothing of experiment
3 ran in game or in the Creation Kit. Labels: **verified** (checked offline on files, command or number given),
**supported** (supported hypothesis), **unresolved**. Revised the same evening after QA's review of PR #67: the
experiment 3 plan no longer relies on anchors (they do not merge), the packing evidence is restated at its real
strength, and exp3 is gated on an uncompressed exp2b rerun.

Already verified in game before this work (runner, 2026-10-11, `C:\Modding\research\terrain\binding\findings.md`):
a worldspace's own BTD applies only when it is an overlay activated on a planet (PNDT `CNAM` entry); activation merges
its cells into the planet worldspace at a whole-cell XY offset plus a Z offset; the outer cell ring of an overlay is
blended with procedural ground (LC172World border cells 4 to 6 m off, inner cell within 0.02 m).

## Short answer

0. **Gate for every BTD option: no run has read our BTD heights yet.** exp2b's first attempt (16:28 to 16:46) merged
   at (-12, -27) cells and read **z = -116.00, the BTD's minimum, at 14 of 14 probes, at the spawn and at the beyond
   probe** (outside the overlay) (runner obs.json). Its second attempt read the spawn mid-fall (z -354.13), so the
   runner's Z offset (-459.27) started every drop near -309 m, under that surface: 10 of 14 probes fell through, two
   stayed at -309.27 and the two far ones read -116.00, so it adds nothing about the BTD. Archive facts (**verified**, raw BA2 headers): our installer stored the BTD zlib-packed (`FO4TerrainExp2 -
   Main.ba2`: 27,375,606 of 27,612,888 bytes); the terrain-only vanilla archives store all their BTDs uncompressed
   (Terrain01..04 and TerrainPatch: 2,004 BTDs). SFBGS00D - Main also stores its 108 BTDs uncompressed, but it stores
   all 11,974 of its entries that way (as every DLC Main.ba2 here does), so it says nothing about BTDs in particular;
   Meshes01 is fully packed. Cause of the flat read: **unresolved**. A packed BTD that the terrain streamer cannot read
   is one hypothesis; the BTD not being used at all is not excluded (the beyond probe outside the overlay read -116.00
   too), and exp1c's flat -13.94 is a different signature (its range is -500..1000, so not raw 0). Since 17:06 the
   installer stores every archive entry uncompressed (`claude/test-queue` f210b91, in the integration worktree as
   904232f) and the uncompressed rerun `terrain_exp2b3` is queued. **Experiment 3 must not be queued until that rerun
   reads the BTD's own heights** (staged README says so).
1. **The full LAND grid cannot be one landing in any option.** The Commonwealth LAND grid is 192 FO4 cells =
   11,234.7 m = 114 Starfield cells per side. Starfield's default game terrain width is **100 cells** with a
   **5-cell** playable buffer (decoded from Starfield.exe, **verified** values, meaning **supported**), and the
   largest overlay any planet registers is **14 x 14 cells** (**verified**). The 108 BTDs of 100 x 100 cells are
   editor and test worlds, not overlays or surface blocks (**verified**).
2. **The playable Commonwealth fits.** Cells with at least 20 placed references span FO4 cells x -34..31, y -39..31:
   3.86 x 4.15 km, **39 x 42 Starfield cells** (**verified**). With 1.2 to 2.5 km of visible surroundings that is
   64 to 90 cells, inside one landing.
3. **Recommendation: (a) one overlay** for the playable Commonwealth plus its surroundings (64 to 90 cells, Absolute
   alignment), placed in the middle of the landing by a measured lat/long. **Fallback: (b) a grid of 14-cell
   overlays**, edge-matched by construction, if a large overlay fails. (c) a custom planet surface stays research; (d)
   static mesh tiles only for terrain the BTD cannot hold (the far ring, cliffs). Exactness argument: (a) has no seams;
   (b) has a 1-cell merge ring at every seam whose behaviour is unknown (experiment 3 measures it).
4. **Generator built**: `scripts/terrain/make_cw_overlays.py` + `src/fo4sf/overlay_grid.py` + `dotnet/TerrainOverlays`
   write the BTDs, masks, SFBK / LCTN / WRLD / cells / anchors and the Mars registration for any FO4 cell rectangle,
   as one overlay (`--tile` at least the region) or a grid; `analyse` reads the runner's results. 35 synthetic tests.
5. **Experiment 3 staged, gated on item 0** (`C:\Modding\staging\terrain_exp3`): 2 x 2 overlays of 14 x 14 cells
   around Sanctuary, Vault 111 and Red Rocket, one shared height range, masks 0 on the seams, a COC cell per tile,
   placed by hypothesis H_ll so they should lie edge to edge. 9 plan entries, 115 points: each tile in its own landing,
   the seams in T00's landing, three **locate transects** that find where T10, T01 and T11 really sit in T00's landing
   from the heights read (whether or not H_ll holds), and T00's outer edges with mask 255 and 0. Offline check: 490 of
   490 items pass, worst point 5.17 mm (step 5.17 mm).

## 1. Size limits

### 1.1 Vanilla overlays and blocks (verified)
Raw walk of Starfield.esm (scratch `scan_planets.py`, output `C:\Modding\research\terrain\scale\planets.json`):

| What | Sizes (cells per side: count) |
|---|---|
| SFBK of the 430 overlay worldspaces (`WRLD` overlay `BNAM`) | 3: 207, 4: 121, 5: 77, 6: 3, 7: 3, 8: 7, 9: 1, 10: 5, 11: 3, 12: 1, **14: 2** (NewAtlantis, SettleWaggonerFarm) |
| Overlays registered on a planet (PNDT `CNAM`, 72) | 3 to 14; 11 have 10 or more cells (cities, settlements, a few large locations) |
| Overlay source blocks (`NAM1 OverlaySource\...`) | 3, 4, 5: 135 each |
| Procedural surface blocks (`NAM1` = theme) | **14** ("1K" themes): 616, **26** ("2K"): 217 |
| SFBK with `DNAM` 100 x 100 | 1: `OverlayBlockTestPCMBaseSurvey01Overlay`, no WRLD in the shipped esm |

The 108 BTDs of 100 x 100 cells (architecture.md 1.4): all top-level `terrain/*.btd`, all with the default range
-500 / 1000 m (= `fTerrainMinHeight` / `fTerrainMaxHeight` below), 92 of them 4,210,995 or 4,211,023 bytes (the same
flat default terrain). 100 have neither an SFBK nor a WRLD in Starfield.esm, 5 have a test overlay block
(`TestPCM*`, `lc136worldDUPLICATE000`, `xxTestLightingGIWorld02`), 3 have a WRLD (`DefaultWorld` with 0 cells,
`TempJemisonWorld` without an overlay component, `OutpostOverlayTemplate`). None is registered on a planet. They are
the editor's default terrain for new worlds (`uDefaultEditorTerrainWidthInCells` = 100), not proof that a 100-cell
overlay works in game. Scratch `btd100.py`.

### 1.2 Engine and CK defaults (verified values; meaning supported)
Method: each INI setting is a static object built by a 4-instruction initialiser (`mov r8d, value` or
`vmovss xmm2, [constant]`, `lea rdx, name`, `lea rcx, object`, `call`). Scratch `inidefaults.py` finds the code that
references each name string in Starfield.exe and decodes the value; `xref_lea.py` / `xref_addr.py` follow the CK's
"maximum recommended cut dimensions are %1x%1" message to the setting it formats.

| Setting | Default | Reading (supported unless marked) |
|---|---|---|
| `uDefaultGameTerrainWidthInCells:Terrain` | 100 | width of a worldspace's terrain in game: a landing (planet worldspace) is 100 x 100 cells |
| `uDefaultEditorTerrainWidthInCells:Terrain` | 100 | same in the editor; matches the 108 test BTDs |
| `uPlayableSpaceOverlayCellBuffer:Planet` | 5 | buffer cells at the edge of the playable space (CK string: `GetHalfPlanetPlayableWidthInCells() > aCellBuffer`) |
| `uOverlayMergeZoneSize:Overlays` | 1 | the 1-cell ring an overlay blends with planet ground (matches the LC172World measurement) |
| `uBlockSize:Stitching` / `uBlockMergeZoneSize:Stitching` | 10 / 2 | surface blocks: 10-cell core, 2-cell merge zones; 14 = 12 + 2 and 26 = 2 x 12 + 2 fit a 12-cell pitch with 2-cell overlaps |
| `uHeightMergeStyle:Stitching`, `uMaterialMergeStyle` | 1, 1 | blend style in merge zones (meaning unresolved) |
| `uPlanetBiomMapFaceDim:Planet` | 256 | = SFTR `DNAM` edge 256 (all 1,505 trees), 2 faces (`CNAM` 2) |
| `uAlignment:Overlay` | 4 | default alignment mode; 4 = Median in the SFBK `JNAM` enum (xEdit) |
| `bUsePlacedOverlayParentOffset:Overlay` | 0 | |
| `uMinCellsFromBorder:Landing`, `uLandingKeepBufferSize:Landing` | 17, 3 | landing site constraints |
| `fCellWidthToNewOverlayMultiplier:Landing` | 3.0 | |
| `iPlanetContentBlockOverlaySafeZoneBufferSize:PlanetContent` | 10 | cells kept free of procedural content around overlays |
| `fTerrainMinHeight` / `fTerrainMaxHeight`, `fDefaultTerrainZMin/ZMax` | -500 / 1000 | default BTD range (verified: matches all 108 test BTDs) |
| `uMaximumPlayableAreaWorldCoord:General`, `fPlayableAreaX/Y/Z` | 4096, 100 / 100 / 50 | unresolved (probably space) |
| `bDisableWorldShift`, `bDisableTerrainShift` | 0, 0 | world and terrain shifting are on |
| CK `iBlockCutRecommendedMaxDimensionExclusive:General` | 6 | **the CK recommends overlays under 6 x 6 cells** (the value the "%1x%1" message prints) |

### 1.3 The Commonwealth (verified, Fallout4.esm)

| Extent | FO4 cells | Metres | Starfield cells | Heights |
|---|---|---|---|---|
| LAND grid | -96..95 (192) | 11,234.7 | 114 | -118.86..641.03 m |
| Placed references, cells with at least 20 | x -34..31, y -39..31 | 3,862 x 4,155 | 39 x 42 | -118.86..302.74 m |
| Pip-Boy map (WRLD `MNAM` NW (-33, 25), SE (28, -36)) | 62 x 62 | 3,628 | 37 | -118.86..295.66 m |
| 64-cell window on the playable core | | 6,400 | 64 | -118.86..521.37 m |
| 90-cell window on the playable core | | 9,000 | 90 | -118.86..641.03 m |

55 % of the LAND cells have a mean height below 0 (sea and rivers; water is not handled by this track).
BTD size: 30.6 to 34.2 KB per cell in experiment 3 (32.8 in experiment 2); one 64 x 64-cell overlay of the
playable core measured 103.2 MB (25.2 KB per cell, generator trial in section 5), so 90 x 90 is about 200 to 270 MB
and the full 114 x 114 about 330 to 430 MB, in one plugin BA2. The BTD stores every cell and LOD level as
its own zlib block, so streaming per cell is possible (**supported**; whether the overlay merge loads a whole BTD at
once is **unresolved**).

### 1.4 What follows
- One landing holds at most about 90 x 90 usable cells (100 minus the buffer) (**supported**). The full 114-cell
  LAND grid does not fit in any option; the outermost ~1 km ring (FO4's own unplayable, LOD-only terrain) can only be
  cropped, drawn as planet LOD (option c) or as static LOD meshes (option d).
- A single overlay of 64 to 90 cells is 4.6 to 6.4 times wider than any vanilla overlay. Experiment 2b (29 cells)
  activated and merged but read flat (Short answer, item 0); its uncompressed rerun exp2b3 is the first possible
  in-game data point above 14.

## 2. Where an activated overlay lands (lat/long -> planet cell)

- **PNDT `CNAM` order (verified):** each entry is f64 latitude, f64 longitude (radians), u32 WRLD. Evidence: the 11
  Earth overlays sit at their real cities with the first value as latitude: LC146World (34.91, 135.73 deg) Kyoto,
  LC152World (22.15, 114.33) Hong Kong, LC154World (30.38, 30.97) Cairo, LC144World (38.58, -91.20) St. Louis,
  lc017world (28.46, -81.42) Orlando; CydoniaCity on Mars at (41.03, -9.80) = the real Cydonia region. Mutagen 0.55
  names the first value `Longitude` and the second `Latitude`; our builders write the latitude into Mutagen's
  `Longitude` (TerrainOverlays) and the check reads the raw bytes. In these terms experiment 1's World01 is at
  latitude 0.2, longitude 1.2 rad and experiment 2b at latitude 0.3, longitude -1.2.
- **Measured (runner obs.json):** World01 (0.2, 1.2) -> local origin at planet cell **(+30, -35)**: the COC marker
  (50, 50) arrived at (3050, -3450) in the **first** attempt of all five registered runs (terrain_exp1_mars, exp1b,
  exp1c, B_w01, exp1d). The three second attempts that coc'd again in the same game session (exp1_mars, exp1b, exp1d)
  arrived at (77.6, 101.1), (74.0, 8.0) and (75.3, 99.7) instead: not a whole-cell offset of (50, 50), so not this
  merge (**unresolved**; an unmerged load is one candidate). LC172World (-0.043119, -0.087881) -> **(-5, -23)**
  (anchor 0010238E, run `terrain_A2_lc172`: offset -500, -2300, Z -3.62); exp2b's `FO4CW_Commonwealth` (0.3, -1.2) ->
  **(-12, -27)** in both attempts (from the spawn: arrived at (-2189.03, -1552.80) for the marker at local (-989.03,
  1147.20)).
- **No absolute rule found (unresolved):** 7 projections (equirectangular, sinusoidal, orthographic, azimuthal
  equidistant / Lambert per hemisphere, Mercator, swapped axes) x 13 scales (Mars radius; 49,152 = 256 x 16 x 12 cells
  per face over pi, pi/2, 2 pi; 14- and 10-cell pitches) x 4 sign choices x 20 origin grids (1 to 256 cells, floor or
  round) reproduce the measurements in 0 cases, with the first two or all three (scratch `latlon_fit.py`). So few
  points cannot separate projection, scale and the landing's origin snapping; all three offsets are within 35 cells
  of the landing's origin.
- **Local scale (supported):** hypothesis H_ll: near a registration the offset moves at true planet scale, x east =
  R cos(lat) dlon / 100 m, y north = R dlat / 100 m (Mars R = 3,390 km from its PNDT body data: 33,900 cells per
  radian). Vanilla clusters only bound it (scratch `clusters.py`): the 8 Cydonia overlays overlap at scale factor
  0.25 and not from 0.5 to 4 (QA's recomputation: none from 0.5 to 2), and span 51 x 79 cells at 1 (fits in one
  90-cell landing), 91 x 148 at 2 (does not), counting the spread of their origins plus the largest overlay (QA, with
  another convention: 43 x 73 and 81 x 142). Akila (2 overlays) and Ixyll II (3) show the same picture. So 0.5 <= s <=
  about 1.1 to 1.2 if the Cydonia overlays are meant to share one landing; nothing pins s = 1.
- **Consequence:** edge-to-edge overlays need the local rule measured. Our persistent anchors cannot do it: they read
  back their unmerged local position in 4 of 4 attempts (exp1d a1, a2: (50, 50, 10); exp2b a1, a2: (-989.03, 1147.20,
  105.14)), while the vanilla LC172World anchor moved with its merge. Experiment 3 therefore measures placement from
  heights (locate transects, `analyse`). A single overlay only needs a lat/long that puts it in the middle of the
  landing; experiment 2b gave one offset, (-12, -27) at (0.3, -1.2), to start from.

## 3. Options

| | (a) One big overlay | (b) Grid of adjacent overlays | (c) Custom planet surface with our blocks | (d) Static mesh tiles |
|---|---|---|---|---|
| What | One WRLD + SFBK + BTD (64 to 90 cells), Absolute, one PNDT entry | N x N overlays of <= 14 cells, one PNDT entry each, lat/longs edge to edge | A planet (new, or an override of an unused one) whose surface tree (SFTR: 2 faces x 256 x 256 pattern slots) points at our patterns (SFPT: 16 x 16 block slots) of our 14-cell blocks (SFBK + BTD) | FO4 LAND triangles as `.mesh` tiles with collision, placed as statics over a flat or lowered ground |
| Geography | exact (1 sample = 0.78 m, quantisation 6 to 12 mm; FO4 cliffs lose up to 1.4 m, experiment 2) | exact inside tiles; at seams unknown | exact only if block alignment and merge blending keep absolute heights (unknown) | exact (FO4's own triangles) |
| Seams | none inside; outer 1-cell ring blends into planet ground (fine: outside the playable area) | every seam has two 1-cell merge rings (`uOverlayMergeZoneSize` 1). With mask 0 on seams they may stay exact (unknown); if blended, a 200 m strip per seam is wrong by metres (LC172: 4 to 6 m) | blocks overlap by 2 cells; equal heights in both blocks blend to the same values (supported) | tile edges share vertices (we control them); none with the ground if it is hidden |
| Placement | lat/long so the overlay sits in the middle of the 100-cell landing: one measurement (exp2b gives one) | the local lat/long rule to the cell (exp3 locates the tiles from heights); rounding to whole cells must not shift a tile | which face cell a lat/long falls in (projection unresolved), or fill every slot | none (worldspace coordinates) |
| LOD / far terrain | BTD LOD0-4 inside; beyond the overlay the planet's procedural ground | same | the planet's own LOD shows our blocks (far terrain is the Commonwealth) | own LOD meshes needed |
| Overlay mask | 255 on the outer ring (vanilla style) | 255 on outer edges, 0 on seams; north / south rings only in pairs while the mask row order is unresolved (exp3) | none (blocks have no mask) | n/a |
| Precedent | none above 14 cells (vanilla max), CK recommends < 6 | each tile vanilla-sized | the way every vanilla planet is built (procedural blocks) | statics are routine |
| Effort | done (generator, `--tile` >= region) | done (generator) | large: SFTR (512 KB arrays), SFPT, SFBK sets, rotation byte meaning, face mapping, a planet | large: terrain mesh + collision + materials + LOD pipelines |
| Main unknowns | does a 64-90-cell overlay activate, stream and stay exact; Z offset of Absolute | seam blending; the lat/long rule; overlap refusals ("Overlapping existing overlay") | block height alignment (`JNAM`, Relative), merge style, rotation identity (`GNAM` 0x08?), SFTR overrides ("CK does not copy this on overrides"), procedural content on it | performance at 4,700 to 37,000 tiles; terrain materials |
| Cheapest in-game test | exp2b3 (29 cells, uncompressed rerun, queued); then a 64-cell core overlay (`--tile 64`) | **exp3 (staged, after exp2b3)** | override MarsSurfaceTree so every slot holds one test pattern of one 14-cell marker block; coc LC172Ext01, probe the 12-cell pitch, rotation and heights | one FO4 cell as a mesh tile with collision in exp2b's world, 1 m above the BTD |

Evidence for (c) (**verified** record layout, behaviour **unresolved**): SFTR `CNAM` 2, `DNAM` 256, then per face
`FNAM` 65,536 SFPT FormIDs and `GNAM` 65,536 bytes (almost all 0x08); SFPT `FNAM` 256 SFBK FormIDs, `GNAM` 256 bytes:
(k << 5) | 0x08 for 1 x 1 blocks (eight orientations, equally common) and 0x10 / 0x40 / 0x50 for the other three slots
of a 26-cell block, `DAT2` per-slot height adjustment (0 in most patterns), optional `DNAM` worldspaces: 34 unique
patterns (`PatternCydoniaCity`, `PatternNewAtlantisWorld`, ...) list the overlays placed on them over a full grid of
procedural blocks; 5 surface trees carry a `SurfaceTreePatternSwapInfo_Component` (Mars swaps in 0012268E). CK strings
show unique pattern placement per planet ("current block pattern is already set as unique on a planet", "Original block
pattern for surface tree on ... Point: [ ... Hemisphere:"). So a pattern can place specific blocks at specific slots;
the planet's base terrain can be ours, but none of its height or blending rules is known.

## 4. Recommendation and decision gates

**(a) one Commonwealth overlay** of the playable core plus surroundings, Absolute alignment (`INAM` 1, `HNAM` 0),
its own Location, mask ring 255, registered on a host planet at a lat/long measured to put it in the middle of the
landing. Start at 64 x 64 cells (6.4 km: the 3.9 x 4.2 km playable area plus 1.2 km), grow toward 90 if it works.
Static LOD meshes (d) for the ring beyond only if the far view matters.

Gates, in order (each a queued runner job; nothing else depends on guessing):
0. **exp2b3** (queued 17:06, installer f210b91): exp2b with its BTD stored uncompressed. Reads the BTD's heights ->
   queue exp3. Still flat at -116 -> packing was not the cause: find out why the BTD is not used (records, alignment,
   archive path) before any further BTD experiment; exp3 would only repeat it.
1. **exp1d / exp2b** (done): exp1d's anchor not merged, heights not ours; exp2b merged at (-12, -27), flat at its
   minimum (item 0).
2. **exp3 (staged here, after gate 0):** tile heights, seam behaviour with mask 0, the outer ring with mask 255 and 0,
   where the tiles really sit in one landing (the local lat/long rule, from heights), the even-size grid origin.
3. **exp4 (next, generator ready):** if exp2b3 passes, `--fo4-cells -34 31 -39 31 --tile 64 --pad origin
   --grid-points 4` (the playable core in one overlay, its frame = the CW frame) at a lat/long chosen from exp2b's and
   exp3's offsets; if large overlays fail, 14-cell tiles with the exp3 calibration.

Why not (b) first: it is only as exact as its seams, needs the placement rule to the cell, and multiplies records
(the 64-cell core = 25 tiles of 14). Why not (c): every vanilla planet uses it, but the exactness depends on four
unknown rules and it needs a planet. Why not (d): new pipelines (terrain collision, materials, LOD) for what the BTD
already does.

## 5. Generator

    python scripts/terrain/make_cw_overlays.py build --fo4 <Fallout4.esm> --sf-data <Starfield\Data> --out <dir>
        [--fo4-cells X0 X1 Y0 Y1] [--tile 14] [--pad centre|sw|origin] [--grid-points 0] [--prefix FO4CW3]
        [--plugin FO4TerrainExp3.esm]
        [--mars-plugin FO4TerrainExp3_Mars.esm | --no-mars] [--alignment absolute|relative] [--hnam 0]
        [--ref-lat 0.2 --ref-lon 1.2 --ref-offset 30 -35] [--centre-cell 0 0] [--radius-km 3390]
        [--mask-ns symmetric|outer] [--load-byte 02] [--max-jump 400] [--locate-step 200]
        [--plan grid|rays] [--world <edid>] [--coc <edid>Spawn] [--btd-copy-meshes]
        [--rays nw:135,ne:45,e:0,se:-40,s:-90,w:180] [--ray-distances 0 200 500 1000 2000 3000] [--edge-keep 200]
    dotnet run --project dotnet/TerrainOverlays -c Release -- <Starfield.esm> <dir>
    python scripts/terrain/make_cw_overlays.py check --sf-data <Starfield\Data> --out <dir> [--no-plugins] [--verbose]
    python scripts/terrain/make_cw_overlays.py analyse --out <dir> --runs <runner queue folder> [--json <file>]
        [--tol 0.5] [--window 30] [--free-z]

- `src/fo4sf/overlay_grid.py`: FO4 cell rectangle -> Starfield cells (CW frame = FO4 units / 70), split into n x n
  tiles (padding split between both sides), tile frames (local = CW - origin; the BTD grid rule of terrain_grid.py),
  sample lattices that continue across seams, outer edges, seam segments, the shared height range, H_ll placement
  (`latlon_for_offset`, `predicted_offset`, `group_targets`), `mask_edges` (below), `whole_cells` and `locate_tile`
  (where an overlay sits, from height reads: every whole-cell shift in a window, reads inside the overlay but outside
  its 1-cell merge ring must all match its BTD within 0.5 m, at least 3 of them).
- Masks: `overlay.mask_array(n, edges=...)` writes rings only on the edges given. The engine's image row order of an
  overlay mask is **unresolved** (QA's offline count of placed references inside the mask-0 area points both ways),
  so `--mask-ns symmetric` (default) writes the north and south rings only when both are outer edges: the mask then
  reads the same either way and a flipped row order cannot put 255 on a seam. A single overlay keeps its full ring;
  in a grid with several rows the outer north / south edges get 0 (`--mask-ns outer` restores them once the row
  order is known).
- `make_cw_overlays.py`: reads FO4 LAND once (`fo4land`, or a cached `.npz`), resamples every tile at its CW sample
  positions (separable bilinear), quantises all tiles with one range, writes BTDs (LTEX of TempJemisonWorld, as
  experiment 2), masks (texconv BC4, or the built-in lossless writer), `overlays_params.json`, `plan.json`,
  `expected.json`, `README.txt`, `preview.png`. Check points are FO4 vertices whose decoded height equals the FO4
  height within one quantisation step under bilinear and both triangle splits, on slopes up to 25 deg.
- Plan entries (`make_plan`), runner format: every entry cocs into the tile whose frame its points use, and takes the
  merge offset from that tile's spawn: `spawn_local` is the COC marker's x and y only, so the runner's Z offset stays 0
  and a spawn read mid-fall cannot lower the drops; the anchor is still read, and the runner falls back to the spawn
  when it reads its local position. `z_ref` names the entry's flat centre probe, from which the judge takes the Z
  offset. `drop_z` = highest expected point + 40 m (locate entries: the shared maximum + 40 m). `settle_ms` covers the
  whole free fall from `drop_z` to 20 m under the lowest point at 3.71 m/s^2 plus 1 s (at least 8 s). Points are
  ordered nearest-first from the spawn, with waypoint probes (eligible vertices at least 150 m inside a tile edge, in
  the coc'd tile only for tile and edges entries) wherever a jump would exceed `--max-jump`. Kinds: `tile` (one per
  tile, own landing), `group`, `locate` (one per other tile) and `edges`, all in the first tile's landing (section 6).
- `analyse`: reads `tests/*/a*/spec.json` + `obs.json` from runner queue folders and reports, whatever the runner's
  verdict: the merge offset of each landing (spawn read - spawn_local; whole cells or not), the anchor read, the Z
  offset (z_ref, else the coc'd tile's own heights), every point's error in the entry's frame, and for every tile the
  whole-cell shift that fits the heights read (`locate_tile`; the coc'd tile itself should be at (0, 0); reads the
  coc'd tile explains are not used for the others). Positions are the ones the game reported, so a probe that ended
  away from its target still counts.
- `dotnet/TerrainOverlays`: per tile an SFBK (copy of OverlayBlockLC172World: `ANAM`, `DNAM`, `ENAM` = shared range,
  `FNAM` = SW-corner rule, `INAM`/`HNAM`), its own LCTN (keyword LocTypeOverlay, parent SSol_PMars_Surface; the CK
  warns when overlays share one), a WRLD (copy of LC172World) with all n x n cells, a COC cell with a marker 2 m
  above the anchor, and a persistent XMarker anchor; anchors take FormIDs 0x800 + tile index so plan.json can name
  them (load-order byte `--load-byte`, 02 as exp2b's resolved; the runner reads the ref literally). The Mars plugin
  appends one `CNAM` entry per tile. It has no unit test of its own: `check` walks its real output raw (records,
  fields, FormIDs, CNAM order), and a synthetic test feeds `check`'s record walk minimal plugins and mutated ones.
- One overlay = `--tile` at least the region's size (option a); `--pad origin` puts tile origins on multiples of the
  tile size, so a single overlay over the FO4 origin has its own frame equal to the CW frame (FO4 position / 70 is the
  local position, as in experiment 2); `--grid-points K` adds a K x K spread of check points. The whole LAND grid
  with 14-cell tiles is 9 x 9 tiles (126 cells). Tiles are resampled in row strips and check points decode 2 x 2
  samples, so memory stays per strip (strips equal one resample bit for bit: test).
- Option (a) trial (scratch folder, not staged): the playable core, FO4 cells x -34..31, y -39..31, `--tile 64 --pad
  origin --grid-points 4` -> one overlay of Starfield cells -32..31 on both axes, origin = CW origin, BTD 103,172,485
  B, range -120..503 m (step 9.506 mm), plugin 183,096 B with 4,096 cells; about 18 s to build. Plan after this
  revision: 21 points + 55 waypoints (the grid points are up to 4,692 m from the spawn), drop 310 m, wait 15.5 s (the
  earlier fixed 8 s left 8 of 21 points mid-fall, QA), longest jump 386 m, about 1.6 h in game; `--max-jump 0` drops
  the waypoints. Check 299 of 299 without plugins.
- Tests (`tests/test_overlay_grid.py`, 35, synthetic heights from a formula): region and padding arithmetic, frames,
  lattice continuity, seams and edges, masks per edge and `mask_edges` (row-flip invariant), H_ll round trip and
  scale, edge-to-edge targets, fall times and waits, whole-cell offsets, `locate_tile` (finds a shift, rejects a
  missing tile, free Z); a full build of 2 x 2 tiles of 5 cells whose four BTDs side by side are **exactly** the raw
  samples of one 10 x 10-cell BTD of the same region; the plan contract (coc'd frame, spawn x / y, z_ref, drop, wait,
  jumps, FO4 vertices), locate transects (at least 3 probes in the target, none in a merge ring), the edges entry; the
  offline check passes and catches a wrong expectation, a step at a seam and five plan-contract errors; the raw plugin
  walk on minimal synthetic plugins passes and catches a swapped lat/long and a non-persistent anchor; `analyse` on
  simulated runner output (anchors unmerged, spawn mid-fall, a Z offset) finds T10 one cell off H_ll, T01 on it and
  T11 missing, finds a BTD one cell off its own frame, and reads runner folders (BOM included); a single-overlay
  build; row strips equal one resample bit for bit; the 2 x 2-sample decode equals point_interp.

## 6. Experiment 3 (staged, not deployed; gated)

`C:\Modding\staging\terrain_exp3` (outside the repo): `FO4TerrainExp3.esm` 39,822 B, `FO4TerrainExp3_Mars.esm`
6,573 B, four BTDs 6,000,752 to 6,701,057 B, four masks 980,128 B, `overlays_params.json`, `plan.json`,
`expected.json`, `offline_check.json`, `README.txt`, `preview.png`. FO4 cells x -35..10, y -6..40 -> Starfield cells
x -21..6, y -4..23 (28 x 28) -> 2 x 2 tiles of 14. Shared range -40..299 m, step 5.173 mm. Re-staged after QA's
review: BTDs and both plugins byte-identical to the first staging (SHA-256), masks and plan new. **Do not queue before
gate 0** (exp2b3 reads real heights; the staged README starts with this).

| Tile | CW cells x / y | Own origin (CW m) | Mask ring | Anchor / spawn (local) | lat, lon (rad) | Predicted planet cell |
|---|---|---|---|---|---|---|
| FO4CW3_T00 (SW) | -21..-8 / -4..9 | (-1400, 300) | w | 02000800 (52.34, 58.40, 88.57) | 0.200825959, 1.198886263 | (-7, -7) |
| FO4CW3_T10 (SE) | -7..6 / -4..9 | (0, 300) | e | 02000801 (45.71, 47.43, 9.83) | 0.200825959, 1.199307677 | (7, -7) |
| FO4CW3_T01 (NW) | -21..-8 / 10..23 | (-1400, 1700) | w | 02000802 (410.74, -553.49, 105.14) = Red Rocket | 0.201238938, 1.198886216 | (-7, 7) |
| FO4CW3_T11 (NE) | -7..6 / 10..23 | (0, 1700) | e | 02000803 (100.57, 49.94, 56.23) | 0.201238938, 1.199307648 | (7, 7) |

- Seams: x = -700 m (T00 | T10, T01 | T11), y = 1000 m (T00 / T01, T10 / T11). Red Rocket (CW -989, 1147), Sanctuary
  (-1154, 1260) and Vault 111 (-1275, 1305) all lie in T01, at least one cell from its seams.
- Masks (`--mask-ns symmetric`): the west tiles ring on w, the east tiles on e; every N / S edge, outer or seam, is 0.
- Placement by H_ll from World01's measured offset, group centre at planet cell (0, 0): adjacent tiles differ by
  14 cells = 4.130e-4 rad in latitude and 4.214e-4 rad in longitude.
- `plan.json`, 9 entries, 115 points (18 of them waypoints), runner format (points and `expect` in the entry's frame,
  `expect` = FO4 height / 70); every entry: coc the frame tile, its spawn x / y, `z_ref` = that tile's flat centre:

| # | Entry | Points | Drop / wait | What it measures |
|---|---|---|---|---|
| 0-3 | `tile` T00, T10, T01, T11 (own landing) | 10, 10, 13, 10 | 95-190 m / 9.5-11 s | landmarks or centre, a slope, its side of each seam at near (1.5-2.2 m), ring (40-52 m, inside the 1-cell merge ring) and inner (140-149 m) distance; the landing's merge offset (spawn) |
| 4 | `group` (T00's landing) | 31 | 175 m / 11 s | T00's centre and both sides of all 4 seam segments: passes only if the tiles lie edge to edge (H_ll at scale 1) and the seams are exact |
| 5-7 | `locate` T10, T01, T11 (T00's landing) | 9, 9, 13 | 340 m / 16 s | a transect every ~200 m from T00's centre toward each tile; `analyse` finds the tile at whatever whole-cell shift it really has |
| 8 | `edges` T00 (T00's landing) | 10 | 240 m / 11.5 s | T00's outer w edge (mask 255) and s edge (mask 0): two probes in the cell ring (40-60 m), one inside it (140-170 m) each |

- Locate coverage (**verified** offline from the staged probe positions): the T10 and T01 transects put at least 3
  probes inside the target's interior for a shift of 3 to 20 cells along H_ll's direction (scale about 0.2 to 1.4;
  below 14 the target overlaps T00, whose own probes then read T00) and -6 to +6 cells across it; the T11 diagonal
  for (k, k) up to 22.
  `analyse` on simulated runs over the real exp3 BTDs found every tile at its true shift, with no other consistent
  shift, for: H_ll; T10 one cell further east and T01 one cell south (T11 absent: not found); scale 0.5 ((7, 0),
  (0, 7)); scale 1.2 with a 2-cell side shift ((17, 2), (-1, 17), (17, 17)). Limits: the transects look only in H_ll's
  direction (a flipped axis sign is "not found"), and where tiles overlap (scale 0.5) the diagonal transect could not
  separate T11 from T01.
- Offline check (`make_cw_overlays.py check`, raw record walk independent of Mutagen): **490 of 490 pass**. Every
  point decodes within one step under all three interpolation rules (worst 5.167 mm); all seams continue the lattice
  (largest raw step across a seam not above twice the steps beside it); the entry contract (frame = coc'd tile, spawn x
  / y, z_ref among the points, drop, wait covers the fall, jumps at most 447 m, tile and edges points in their own tile,
  waypoints outside merge rings); each WRLD -> own LCTN (2CA99D, parent 01B736) -> SFBK (`ANAM`, `DNAM` 14 x 14,
  `ENAM` -40 / 299, `FNAM` 196 values = rule, `INAM` 1, `HNAM` 0); anchors `01000800..803` persistent XMarkers at the
  plan positions, plan refs `0200080x`; 4 COC cells; Mars plugin overrides 0003F59A with 10 + 4 entries, latitude
  first; masks decode exactly.
- Runtime: about 2.6 h in one game session (exp2b took about 70 s per probe with an 8 s wait).

**Reading the result** (`make_cw_overlays.py analyse --out C:\Modding\staging\terrain_exp3 --runs <queue folder>`)

| Observation | Meaning |
|---|---|
| Everything flat at the BTD minimum, as in exp2b | gate 0 was not passed: do not interpret anything else |
| A tile entry passes; `analyse`: own tile at (0, 0), merge offset whole cells | that tile's heights are exact (H); its Z offset is in the verdict detail (H: Absolute, HNAM 0 -> about 0) |
| `analyse`: own tile at (+-1, 0) or (0, +-1) instead of (0, 0) in every tile entry | the BTD sits one cell off its own frame: the n // 2 grid-origin rule is wrong for even sizes. 14 is the first even size tested in game (LC172World 3, exp2b 29); the vanilla even-sized worlds oedebugoverlay (4 x 4, WRLD object bounds +-200 m) and LC165World (10 x 10, +-500 m) agree with the rule (cells -2..1 and -5..4, as QA notes) but do not show where the BTD's samples go |
| A tile entry's merge offset is not whole cells | that landing did not merge as expected (as World01's second cocs): its probes are not in the tile's frame, its heights say nothing; rerun it as the first coc of a session |
| Tile entries: whole-cell merge offsets differing by (14, 0), (0, 14), (14, 14) from T00's | each tile's own landing puts it where H_ll predicts relative to T00's; this alone does not show that one landing holds them side by side (the group and locate entries do) |
| Group entry passes | in one landing the tiles lie edge to edge (H_ll at scale 1) and the seams are exact: (b) works |
| Locate: a tile found at H_ll's shift ((14, 0), (0, 14), (14, 14)) | H_ll holds for it in one landing |
| Locate: found at another shift | the actual placement: the local rule's scale and axes follow (e.g. (7, 0) for T10 = scale 0.5); recompute the lat/longs and confirm with one more run |
| Locate: not found | the tile is not along the transect: opposite axis sign, more than 1.4 x H_ll's distance, overlapping (and maybe refused, "Overlapping existing overlay"), or not activated |
| Seam `ring` probes off by metres while `near` and `inner` are exact | in the group entry (tiles adjacent in that landing): the merge ring blends even with mask 0, option (b) cannot be exact at seams, go (a). In a tile entry the seam borders whatever its own landing put there (the neighbour only if it is adjacent: locate shows it), so compare with the edges entry's mask-0 ring on an outer edge. The masks are row-flip invariant, so none of this can be a flipped mask |
| `edges`: w ring (mask 255) off by metres, s ring (mask 0) exact | the mask controls the ring blend; mask 0 on seams should keep them exact |
| `edges`: both rings off | the outer merge ring blends whatever the mask holds |
| Tile entries `NOTERRAIN` | 14-cell overlays do not load where exp2b3's 29-cell one does: compare records |

Runner facts behind this plan (**verified** from obs.json, 2026-10-11):
- Anchors: our persistent XMarker anchors read back their unmerged local position in all 4 attempts (exp1d a1, a2:
  (50.00, 50.00, 10.00); exp2b a1, a2: (-989.03, 1147.20, 105.14)), while the vanilla LC172World anchor 0010238E
  moved with the merge (-500, -2300). Both kinds sit in the world's persistent top cell (raw walk: group type 8, flag
  0x400), so the difference is **unresolved**. QA's reading: a persistent ref resolves in its own worldspace. So no
  exp3 entry depends on an anchor, and the earlier "position" entries (coc T00, another tile's anchor, no spawn
  fallback) were removed: the anchor would have read its local position, the runner would have used offset (0, 0, 0)
  and probed the other tile's local coordinates inside T00's landing.
- The spawn is sometimes read mid-fall (exp1d a1 z -500.00, exp2b a2 z -354.13); with a 3-value `spawn_local` the
  runner lowered every drop by that much (exp2b a2: drops near -309 m, all fell through). Hence x / y only plus z_ref.
- One `drop_z` per entry and a fixed 8 s wait left low points mid-fall (QA: 8 of 21 points of the 64-cell trial need
  11.3 to 11.8 s at 3.71 m/s^2 against about 10.9 s); waits are now sized from the fall.
- Long jumps: in exp2b a1 a 349 m setpos jump ended 141.9 m short (judged INCONCLUSIVE MOVED), a 560 m one arrived in
  both attempts; the cause is **unresolved**. Waypoints keep jumps at about 400 m or less (447 m at most after
  snapping); `analyse` uses the positions the game reported, so a displaced probe still counts.
- Second coc in one session: World01's second cocs arrived unmerged-looking, exp2b's did not. exp3 cocs 9 times in one
  session; `analyse` flags every entry whose merge offset is not whole cells.
- Load-order byte: the anchor refs assume 02 (exp2b's 02000800 resolved with the same Plugins.txt layout).

## 6a. core64: one overlay of the playable core (staged, not run)

Added 2026-10-11 evening, branch `claude/terrain-core64` (stacked on this PR). Since this document was written,
gate 0 passed in game: exp2b with its BTD stored uncompressed (runner `terrain_exp2b3`) read FO4 heights within
0.08 m, and FO4 objects placed on it aligned within 0.02 m. exp3 then read real terrain only in the tile it arrived
in: every probe 500 to 700 m away, in or near a neighbouring 14-cell overlay, hung at the drop height even after
the runner's two extra 8 s waits, so a landing seems to load only the overlay it arrives in and separate overlays
cannot be walked between. Option (a) is the candidate; core64 tests whether ONE large overlay loads everywhere.

`C:\Modding\staging\terrain_core64` (outside the repo), **verified offline** (`check`: 208 of 208):

| Item | Value |
|---|---|
| Region | FO4 cells x -34..31, y -39..31 (playable core, section 1.3), `--tile 64 --pad origin`: CW cells -32..31 on both axes, 6.4 km; local frame = CW frame (FO4 position / 70) |
| Records | `FO4TerrainCore.esm` 183,160 B: WRLD `FO4Core_Commonwealth` (4,096 cells), SFBK `FO4Core_CommonwealthBlock` (DNAM 64, ENAM -120 / 503, INAM 1 Absolute, HNAM 0), own LCTN `FO4Core_CommonwealthLocation`, COC cell `FO4Core_RedRocketSpawn` (grid -10, 11) with `FO4Core_RedRocketSpawnMarker` (COCMarkerHeading) 2 m above the flat vertex at Red Rocket, local (-989.26, 1146.51, 105.14 ground) |
| Mars | `FO4TerrainCore_Mars.esm` 6,512 B: MarsPlanetData CNAM = 10 vanilla + 1, latitude 0.3, longitude -1.2 (exp2b's registration, merged at planet cell (-12, -27) in game); the entry is unique, the nearest other is 33,561 cells away |
| Data tree (`--pack` input) | `Data/Terrain/FO4Core_Commonwealth.btd` 103,172,485 B, the same bytes at `Data/meshes/terrain/` (`--btd-copy-meshes`, as exp2b had), mask `Data/textures/terrain/overlaymasks/fo4core_commonwealth.dds` 20,480,128 B (BC4 6400 px, 255 on the outer cell ring only). Archive2 dry run into the scratch folder with the installer's arguments: 3 entries, all stored (packed 0), byte-identical, 226,825,369 B |
| Build | 9.3 s, peak working set 2,049 MiB (commit 2,788 MiB) for the 64-cell BTD; rebuild byte-identical (SHA-256) |

`plan.json` (`--plan rays`), runner format, 6 entries, 37 points. Each entry is ONE coc arrival at
`FO4Core_RedRocketSpawn` and one direction: the arrival's flat vertex first (= the marker's ground, `z_ref`), then FO4
vertices at 200, 500, 1000, 2000 and 3000 m from it while they stay at least 200 m (2 cells) inside the overlay,
plus the landmarks on the ray nearest their bearing, ordered by distance. `spawn_local` = the marker's ground (x, y,
z). Probes prefer vertices of at most 10 deg within 29 m (two remain at 23 and 25 deg); every expectation is the FO4
height / 70 at that vertex and decodes within one step (worst 9.29 mm, step 9.51 mm). No waypoints: the distances are
the measurement, so the longest jump is about 1 km (exp2b once ended a 349 m jump 141.9 m short; `analyse` uses the
positions the game reported).

| Ray (bearing) | Probes (m from the arrival) | Drop / wait |
|---|---|---|
| nw (135) | Sanctuary 199, 200, Vault 111 328, 500, 1000, 2000 | 245 m / 10.5 s |
| ne (45) | 200, 500, 1000, 2000 | 155 m / 10 s |
| e (0) | 200, 500, 1000, 2000, 3000 | 150 m / 11 s |
| se (-40) | Concord (map marker 00082138) 166, 200, 500, 1000, 2000, 3000 | 150 m / 11.5 s |
| s (-90) | 200, 500, 1000, 2000, 3000 | 150 m / 10 s |
| w (180) | Sanctuary bridge (NorthBridge 0001F970) 117, 200, 500, 1000, 2000 | 305 m / 12 s |

3 km is outside the 2-cell margin toward nw, ne and w (Red Rocket is 1.5 km north-west of the overlay's centre).

Queue (runner, `claude/test-queue`): `testqueue.py plan-terrain --staging <build> --exp-dir
C:\Modding\staging\terrain_core64 --out <queue> --plugins FO4TerrainCore.esm,FO4TerrainCore_Mars.esm --fresh`
(`--fresh`: every entry is a first coc after a relaunch). Reading: `make_cw_overlays.py analyse --out
C:\Modding\staging\terrain_core64 --runs <queue>` prints per ray each probe's distance and its error or `hung`.

| Observation | Meaning |
|---|---|
| Every probe within 0.5 m of its FO4 height (after the z_ref Z offset) in every direction | one 64-cell overlay loads everywhere around one arrival: grow toward 90 cells, then content |
| Probes read real heights up to some distance, then hang at the drop height | the overlay streams only near the arrival (as exp3's neighbours): the distance tells how large one walkable piece can be |
| The arrival probe already wrong or hanging | the 64-cell overlay did not activate (size limit): compare with exp2b, try 45 cells |
| Spawn offset not whole cells | the landing did not merge as expected; the entry says nothing about heights |

## 7. Risks
- Gate 0: until a run reads our BTD heights (exp2b3), no BTD-based option is validated; if the uncompressed rerun is
  still flat, the cause is elsewhere (records, alignment, archive path) and (d) static meshes gain weight.
- A 64 to 90-cell overlay may not activate, may load slowly, or may be cut at the landing's edge; nothing in vanilla
  is that large. Mitigation: grow in steps (29 -> 64 -> 90), fall back to (b).
- The lat/long rule may have per-landing origin snapping that moves a large overlay off-centre; the spawn offset
  shows it and the lat/long can be corrected (anchors cannot: they do not merge).
- Merge rings at seams (b) may be impossible to make exact.
- Even-sized BTDs: if the n // 2 origin rule is wrong for even n, every 14- or 64-cell tile is one cell off; exp3's
  `analyse` detects it (own tile not at (0, 0)) and odd sizes avoid it.
- Mask row order: until known, grids keep 0 on outer north / south edges (no blend ring there).
- Water (55 % of LAND cells average below 0 m), FO4 land textures, grass and terrain holes are not handled yet.
- Host planet: Mars is a test host; the final host (a hidden or new planet) changes the Location parent and the
  lat/long reference.
- FO4 cliffs: a 0.78 m grid loses up to 1.4 m at 75 deg cliffs (experiment 2); (d) patches if needed.

## 8. Unknowns
1. Whether the 100-cell game terrain width bounds a landing as read here (supported only by the setting's name and
   value and the measured offsets, all within 35 cells).
2. The absolute lat/long -> planet cell rule and the landing's origin snapping.
3. Overlay size limits in game above 14 cells (exp2b3: 29).
4. Seam behaviour between adjacent overlays and the role of the mask in blending (exp3).
5. Option (c) rules: block pitch, height alignment, merge style, rotation identity, face projection.
6. Why exp2b read flat at its minimum (gate 0), why our persistent anchors do not merge, the mask image row order, and
   what a second coc in one session does.

## Reproduce

    python scripts/terrain/make_cw_overlays.py build --fo4 <Fallout4.esm> --sf-data <Starfield\Data> --out C:\Modding\staging\terrain_exp3
    dotnet run --project dotnet/TerrainOverlays -c Release -- <Starfield.esm> C:\Modding\staging\terrain_exp3
    python scripts/terrain/make_cw_overlays.py check --sf-data <Starfield\Data> --out C:\Modding\staging\terrain_exp3
    python -m unittest tests.test_overlay_grid tests.test_overlay
    (after the run) python scripts/terrain/make_cw_overlays.py analyse --out C:\Modding\staging\terrain_exp3 --runs C:\Modding\testqueue\terrain_exp3 --json <file>

core64 (section 6a):

    python scripts/terrain/make_cw_overlays.py build --fo4 <Fallout4.esm> --sf-data <Starfield\Data> --out C:\Modding\staging\terrain_core64
        --fo4-cells -34 31 -39 31 --tile 64 --pad origin --plan rays --prefix FO4Core --world FO4Core_Commonwealth
        --coc FO4Core_RedRocketSpawn --plugin FO4TerrainCore.esm --mars-plugin FO4TerrainCore_Mars.esm
        --experiment terrain_core64 --btd-copy-meshes --ref-lat 0.3 --ref-lon -1.2 --ref-offset -12 -27 --centre-cell -12 -27
    dotnet run --project dotnet/TerrainOverlays -c Release -- <Starfield.esm> C:\Modding\staging\terrain_core64
    python scripts/terrain/make_cw_overlays.py check --sf-data <Starfield\Data> --out C:\Modding\staging\terrain_core64

Install for the runner, after gate 0 only: `scripts/game/exp_install.py install --exp-dir
C:\Modding\staging\terrain_exp3 --plugins FO4TerrainExp3.esm,FO4TerrainExp3_Mars.esm --pack` (branch
`claude/test-queue` at f210b91 or later, which stores the archive uncompressed), then `testqueue.py plan-terrain
--exp-dir C:\Modding\staging\terrain_exp3 ...`. Never with experiment 1 or 2 installed (all three Mars plugins
override MarsPlanetData).

Scratch scripts (not in the repo; outputs are game-derived) in `C:\Modding\research\terrain\scale\`:
`scan_planets.py` (PNDT / SFBK / SFPT / SFTR / WRLD raw scan), `btd100.py`, `sfpt_worlds.py`, `inidefaults.py`,
`xref_lea.py`, `xref_addr.py`, `latlon_fit.py`, `clusters.py`, `fo4_extent.py`, `fo4_landmarks.py`, `fo4_refpos.py`.
