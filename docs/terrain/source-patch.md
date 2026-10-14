# FO4 terrain source patch: Red Rocket Truck Stop (Commonwealth cells -18..-17 x 18..19)

Claude, 2026-10-11. This doc covers the source side only: reading Fallout 4 `LAND` heights for a 2x2-cell patch and
checking them. Nothing here touches Starfield terrain, and nothing was tested in game. Labels: **verified** (measured
here, command below), **supported hypothesis**, **unresolved**. A terrain research handoff the owner mentioned could
not be found, so this doc assumes no earlier terrain work.

## 1. Reuse first: what already existed

**fo76utils `fo4land`** ([github.com/fo76utils/fo76utils](https://github.com/fo76utils/fo76utils), MIT licence,
"Copyright (c) 2021-2025 fo76utils", commit `c52da18`, 2025-03-12). Shallow-cloned into
`C:\Modding\research\ext\fo76utils-src` (outside the repo). It was only read: none of its scripts or binaries were
run, and no code was copied. What it does (**verified by reading** `doc/fo4land.md`, `src/fo4land.cpp`,
`src/landdata.cpp`):
- Usage: `fo4land INFILE.ESM[,...] OUTFILE.DDS [[-d ARCHIVEPATH] FMT [XMIN YMIN XMAX YMAX] [worldID [defTxtID]]]`.
  FMT 0 = 16-bit height map, 1 = normals, 2/3 = texture alphas, 4 = vertex colours, 5/6 = texture sets.
  `worldID` defaults to `0x0000003C`. The cell range runs from SW (min) to NE (max).
- World selection: `LandscapeData::loadESMFile` finds the WRLD record by form ID and then the GRUP that follows it
  (type 1, world children). `findESMLand` then recurses through the groups, skipping group types 2, 3 and 7. Each
  `LAND` takes its cell position from the `XCLC` (int32 x, int32 y) of the last `CELL` seen.
- VHGT decoding (`landdata.cpp` lines 381-408): float32 offset times 8, then 33 rows of 33 signed bytes, with
  row 0 at the south and column 0 at the west. The first byte of a row adds to the running height of the previous
  row's first vertex, and each later byte adds to its west neighbour. Height = `offset*8 + (z << 3)` in game units.
  The minimum size it accepts is 1093 bytes.
- Output: a DDS with a custom 11-word header (`FO4_LAND`, xMin, yMin, zMin, xMax, yMax, zMax, water level, 32,
  default land level). Heights are **normalised to 16 bits** over the extracted range
  (`h = zMin + v * (zMax - zMin) / 65535`). Each cell keeps **only 32 x 32 vertices**: the shared 33rd row and column
  are dropped, on the assumption that they equal the neighbour's first.
- Building it needs SCons and a C++ compiler. **Verified not runnable here** (2026-10-11): `g++`, `gcc`, `clang`,
  `cl`, `scons`, `cmake`, `make` and `zig` are not on PATH, and there is no Visual Studio, no vswhere and no MSYS2.
  The task rules forbid installing them, so fo4land served as the reference algorithm.

**Mutagen** (0.55.0-alpha.67, already used by the repo's dotnet tools): `Mutagen.Bethesda.Fallout4` has
`Landscape.VertexHeightMap` with `Offset` and a 33x33 byte `HeightMap`. It parses the bytes but does not accumulate
the gradients. **Verified**: the new `dotnet/Fo4Land` project compiles against it and reads the patch, and
`HeightMap[col, row]` indexing gives results identical to the Python decoder (section 3a).

**This repo**: nothing read `LAND` before. A grep for `VHGT|LAND|Landscape|terrain` finds only record counts
(`scripts/recon.py`) and notes in FORMAT-GAP, RISKS and PLAN. Codex's `Fo4Export` exports placements but not
`LAND`, and it was not touched.

**Decision.** Primary path: a small Python reader, `src/fo4sf/fo4land.py`, that follows fo4land's algorithm.
Second, independent decode: Mutagen through the new `dotnet/Fo4Land`. Why:
- fo4land cannot be built here.
- Its output loses precision: 16-bit normalisation over the whole extracted range gives a step of 0.81 units for
  the full Commonwealth (measured below).
- It also drops the 33rd edge vertices, which are exactly what the seam check needs.
- Python matches the repo's converter and unittest stack.
- Mutagen supplies a record parser written by someone else for the cross-check, at the cost of about 100 lines.

## 2. The patch

| | value |
|---|---|
| Worldspace | `Commonwealth`, WRLD `0000003C` (EDID matched). DNAM land/water level 0.0 / 450.0 |
| Cells | x -18..-17, y 18..19. SW origin (-73728, 73728) units = (-1053.26, 1053.26) m at 70 units/m |
| Structure | Red Rocket Truck Stop building: REFR `000211C0`, base STAT `RedRExt_Workshop01`, pos (-69232, 80304, 7360), rot z 3.927 rad (225 deg), cell (-17, 19), OBND (-585, -1262, 0)..(606, 1575, 1384) |
| Grids | four 33x33 grids per cell plus a merged 65x65 grid (row 0 = south, col 0 = west, 128 units apart) |

| cell | CELL | LAND | VHGT offset | min (units) | max (units) |
|---|---|---|---|---|---|
| (-18, 18) | 0000DDC1 | 0000F2C0 | 998 | 6328 | 7984 |
| (-17, 18) | 0000DDC0 | 0000F2C1 | 864 | 6144 | 7256 |
| (-18, 19) | 0000DDA0 | 0000F2E1 | 969 | 6328 | 7856 |
| (-17, 19) | 0000DD9F | 0000F2E2 | 791 | 6272 | 7432 |

The x coordinates are negative. The y coordinates are positive because the familiar Sanctuary-area structures
(Red Rocket, Vault 111 at cell (-22, 22)) lie north of the origin. Negative-y handling (floor division, signed
XCLC) is covered by the synthetic tests.

In Fallout4.esm the world's persistent cell (`00018AA2`) also carries `XCLC (0, 0)` and holds 33,141 persistent
refs. The reader tells it apart from the real cell (0, 0) because it sits outside the exterior blocks (**verified**).

## 3. Checks (all **verified**, numbers from `report.json`)

**(a) Two independent decodes.** Python reader vs `dotnet/Fo4Land` (Mutagen parser plus a separate C# decode):
- Heights: 4 cells, 4,356 vertices, **max abs difference 0.0 units**.
- Records: CELL form IDs equal. Both found the same 1,315 temporary refs (0 only in one of them).
- Ref positions: max difference 0.00375 units. This comes from the float32 -> JSON decimal -> double round trip,
  not from the data.

**(b) Cell coordinates vs refs.** All 1,315 temporary refs lie inside their cell's square
`[x*4096, (x+1)*4096) x [y*4096, (y+1)*4096)`. The minimum margin is 0.21 units and none are outside, so the origin
is XCLC * 4096.

**(c) Shared borders.**
- Inside the patch: 2 east/west and 2 north/south pairs, max difference **0.0**.
- Patch plus its ring of neighbours: 24 pairs, of which one vertex differs by 8 units ((-19, 19) / (-19, 20)).
- Whole world (`--world-scan`): 73,344 neighbour pairs. **649 pairs (0.88%) do not match**, covering 16,171
  vertices. The worst is 13,056 units at (-65, 76) / (-65, 77), and the worst ten are all in x -68..-62, y 76..77.
  Small steps are common: 31 pairs at 8 units, 37 at 16, 39 at 24.
- **Unresolved**: whether the big seams are inside the playable area.
- Consequence: any converter that shares edge vertices, as fo4land does, must pick a side or weld.

**(d) Alignment.** Terrain was interpolated bilinearly on the merged grid. The spread across the two possible
triangle splits is reported separately because FO4's split direction is **unresolved**.
- Red Rocket floor (REFR z 7360): terrain at the origin is **7360.0** with all three interpolations, so the
  residual is 0.
- Under the building, in a disc of radius 585 units (inside the bounds at any rotation): terrain 7352..7367, and
  z minus terrain has median 1.6 and max abs **8 units (0.11 m)**. The terrain is flattened to the building floor.
- Grounded refs (regex `^(RockBoulder|RockM|RockS|RockPileM|TreeMapleForest|TreeMapleblasted|TreeSapling|TreeStump|TreeCedarShrub)\d`,
  temporary refs): n = 181, z minus terrain median **-24.3 units (-0.35 m)**.
  - Without the large maple trees: n = 100, median **-7.4 units**, p10 -28, p90 +4.9, max abs 69.5.
  - `TreeMapleForest*` (n = 69) median -266 units: big trees are planted deep (supported hypothesis: this hides the
    trunk base on slopes).
  - Spread between bilinear and the triangle splits: median 1.2 units, max 19.
- Orientation control on the same 100 refs (median |z - terrain|): as decoded **11.2 units**, north/south flipped
  367, east/west flipped 653, transposed 394. Row 0 = south and column 0 = west is therefore the only orientation
  that fits.
- Slope of the 65x65 patch: heights 6144..7984 units (87.8..114.1 m at 70 units/m), relief 1840 units (26.3 m).
  Slope median 11.3 deg, p90 23.6 deg, max 76.5 deg (a pit at the (-17, 18)/(-17, 19) corner), 3.0% of vertices
  steeper than 30 deg.

**Whole world facts** (`--world-scan`):
- 36,864 cells (x and y -96..95), all with a 1096-byte VHGT.
- The 3 trailing bytes are non-zero in 779 cells. They are ignored, as fo4land does.
- Heights range from -8320 to 44872 units, so fo4land's 16-bit step for the full world would be 0.81 units.

## 4. What this does not prove
- **Unresolved**: Starfield terrain scale and representation. 70 units/m is the repo's *object* conversion; the
  metres columns use it only for readability. Starfield has no `LAND` (docs/FORMAT-GAP.md).
- **Unresolved**: FO4's quad triangulation (see the interpolation spread above).
- Not extracted yet: normals (VNML), vertex colours (VCLR), texture layers (BTXT/ATXT/VTXT), water.
- Nothing was tested in game.

## 5. Reproduce

```
python -m unittest tests.test_fo4land          # synthetic, no game data
dotnet build dotnet/Fo4Land -c Release
dotnet run --no-build -c Release --project dotnet/Fo4Land -- <Fallout4.esm> Commonwealth -18 18 -17 19 <out>/mutagen_cells.json
python scripts/terrain/fo4_land_patch.py --esm <Fallout4.esm> --world Commonwealth --x0 -18 --y0 18 \
    --out <out> --structure 000211C0 --mutagen <out>/mutagen_cells.json --world-scan
```

Runtime on the 331 MB `Fallout4.esm` with a warm file cache: 3.1 s for the Mutagen run, 0.7 s for the Python
script, and 2.6 s with `--world-scan`. Outputs
(derived game data, kept outside git) are in `C:\Modding\research\terrain\patch_-18_18\`:
- `heights.json`: per-cell 33x33 grids and the merged 65x65 grid, in units
- `merged_units.npy` and `merged_metres.npy`
- `refs.json`: 1,404 refs with terrain under each
- `report.json`
- `mutagen_cells.json`
- `preview.png`: north up, cell borders in yellow, Red Rocket in red, grounded refs as cyan dots

## 6. What the Starfield side needs next
1. Decide how terrain is represented. RISKS.md S5 offers a fallback: bake the 65x65 grid into a static mesh tile
   with collision. That reuses `sfmesh` / `sfcollision`. Native `.btd` terrain for a custom worldspace is
   unresolved.
2. Settle the height scale by measurement, not by assumption. Place the tile and the converted Red Rocket building
   at the same converted origin. The building floor must sit on the tile: in FO4 the residual is 0 units at the
   origin and within 8 units over the footprint.
3. Choose the triangle split and a seam policy before stitching more than one patch.
