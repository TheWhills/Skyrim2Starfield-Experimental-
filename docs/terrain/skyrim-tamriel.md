# Skyrim's Tamriel as native Starfield terrain (core64 recipe, Skyrim source)

Branch `skyrim/terrain-tamriel`, stacked on `claude/terrain-core64-objects` (86e214a). Status: **built and checked
offline on synthetic Skyrim plugins only; not run on the real Skyrim.esm, not deployed, not run in game.**
Labels as elsewhere: **verified** = measured here, number given; **supported** = supported hypothesis; **unresolved**.

## What it is
core64 (commonwealth-scale.md 6a, core64c.md) proved in game that one overlay worldspace with its own BTD, registered
on Mars, carries Fallout 4's terrain at FO4 height / 70 within 0.01 m. Nothing in that pipeline is specific to
Fallout 4 except where the heights come from. Skyrim stores exterior terrain the same way (LAND/VHGT: f32 offset,
33 x 33 signed-byte gradients, height = 8 x (offset + gradient sum), 4,096-unit cells, 24-byte record headers, zlib
records), so `fo4land`'s reader reads `Skyrim.esm` unchanged. This branch adds:

| File | What |
|---|---|
| `src/fo4sf/skyrimland.py` | Every Tamriel cell: decoded VHGT, LAND extent (read from the file, not a fixed square), cells without LAND, WRLD DNAM default land/water height, exterior cell EditorIDs as landmarks (`Riverwood`, or `X,Y`) |
| `scripts/terrain/make_skyrim_overlay.py` | `info` (Skyrim.esm only) / `build` (the core64 recipe with Skyrim names) / `check` |
| `scripts/terrain/make_cw_overlays.py` | Source made a parameter: world name, LAND grid, fill height for missing cells, landmarks, arrival, display name. **Fallout 4 defaults unchanged** (Commonwealth, -96..95, missing cell = error, Red Rocket); `parser()` factored out of `main()` |
| `dotnet/TerrainOverlays/Program.cs` | Optional per-overlay `name` in `overlays_params.json` for the WRLD/LCTN name; without it the FO4 name as before. **Not compiled here** (NuGet unreachable from the build machine); 4-line change, types checked by reading |
| `tests/test_skyrimland.py` | 9 synthetic-fixture tests: a Skyrim-shaped Tamriel (compressed CELL/LAND, named cells, a cell without LAND, persistent cell), the full build, the offline check |

Cells without LAND (none in a synthetic full map; the real count is what `info` reports) take the WRLD default land
height **only on vertices no real cell covers**: a real neighbour keeps its own shared edge (merge_cells alone lets the
south / west cell win shared edges, which put a 56 m error on the neighbours in the first test run).

## Numbers (verified on synthetic data)
- Synthetic Tamriel at an assumed real extent (Skyrim cells x -57..61, y -43..50, 11,186 cells, 94 x 119):
  **one 73 x 73-cell overlay (7.3 km)**, under the 100 x 100 vanilla maximum. `info` 0.7 s; `build` 33 s, peak RSS
  2.6 GB; BTD 147 MB (real terrain compresses worse: plan for ~180 MB from experiment 2's 33 KB per cell);
  height step 9.7 mm over -207..427 m; offline check **161 of 161 PASS**, 30 plan points, worst point error 9.4 mm.
- Every BTD sample equals the bilinear resample of the Skyrim vertex grid / 70 within one quantisation step
  (test 1). Skyrim vertices decode within 0.5 m, median < 5 cm (the 1.83 m grid is resampled onto 0.78 m, so quad
  kinks are not exact; plan points use only vertices that decode within one step, as for FO4).
- The real Tamriel extent, holes and height range are **unresolved** until `info` runs on Skyrim.esm.

## Hypotheses this inherits
- **H (supported for Skyrim)**: Skyrim units / 70 = metres, as for FO4 (same Bethesda unit). The ray probes test it.
- Local frame = Skyrim position / 70 from Skyrim's origin (pad `origin`, as core64). Skyrim's map is not centred on
  its origin, so the square overlay is sized by the farther side.
- Outside Skyrim's LAND rectangle (Skyrim has no ground there) each vertex takes the nearest edge height eased
  (smoothstep) to the worldspace's default land height over `--edge-falloff-cells` (default 4 cells = 234 m), then
  stays flat at that height to the square's edge. This replaced repeating the edge height outwards (streaks in the
  north / south strips, and walls where the edge is a mountain: Starfield blends an overlay's edge into the planet,
  starfield-community-notes.md). The overlay mask blends its outer cell ring into procedural Mars terrain.
  Unresolved: the planet's own height there; a flat border at Skyrim's default height is the neutral guess.
- Mars registration: experiment 2b's (latitude 0.3, longitude -1.2 -> planet cell (-12, -27)), verified in game.
  **Never install with another terrain experiment** (every Mars plugin overrides MarsPlanetData).

## Ground textures (`--land-textures`; supported hypothesis, not in-game tested)
Without the option the BTD carries one plain ground texture (LDirtFootprints01, as every terrain experiment so far).
With it, Skyrim's own texture painting is carried over (`src/fo4sf/landtex.py`, tests in `tests/test_landtex.py`):

1. **Skyrim layers -> weights.** Each LAND's BTXT (base per quadrant) and ATXT + VTXT (layers with per-vertex opacity)
   become an effective weight per Skyrim LTEX at every vertex (layers draw in order over the base).
2. **Skyrim LTEX -> Starfield LTEX.** Every Skyrim texture gets a category from its EditorID and diffuse path (snow,
   ice, road, gravel, rock, sand, mud, ash, forest floor, grass, dirt); every category gets the first Starfield.esm
   LTEX whose EditorID names it (else LDirtFootprints01). The result goes to `ltex_mapping.json` next to the build,
   with each texture's share of the map: **edit it and pass it back with `--ltex-mapping`** (per category, or per
   Skyrim EditorID). Choosing good Starfield textures is a look-and-adjust step.
3. **Encoding.** Weights are resampled onto the 0.78 m BTD grid in 64-row bands. Per 50 m quadrant: the most-used
   texture is the base (byte 5), up to five more are overlays (bytes 0-4, least used on top), and 3-bit alphas per
   sample are solved top-down so the stacked blend reproduces Skyrim's weights (synthetic round trip: mean error under
   5 %; a quadrant needing more than six textures drops the rest, reported as `weight_beyond_six_layers_max`).

The byte layout is verified (architecture.md 1.4); its MEANING is a **supported hypothesis** taken from fo76utils,
which renders Starfield terrain: overlay byte i pairs with weight bits 3i..3i+2, the base is the last valid byte, and
layers are tested top-down from byte 0 (btdfile.cpp `getCellTextureSet` / `getCellLandTexture`, landtxt.cpp). Vanilla
surveys so far only saw single-texture quadrants. Also unresolved: whether the worldspace must list its LTEX (only
TempJemisonWorld has `LandscapeTextures`). In game: if the ground looks like the mapping (snow on the mountains,
roads where Skyrim's are), the hypothesis holds; if layers appear in the wrong places, the byte / bit pairing differs.
Cost on a Tamriel-sized map: about 5 s extra.

**First in-game test (owner, 2026-10-15, Riverwood):** the layers were carried over (patterns follow the terrain) but
the ground rendered pale pink-white everywhere. The automatic picks took the alphabetically first Starfield LTEX whose
EditorID contains the category word, which can be a test or unused record. The build now surveys the LTEX tables of
every vanilla BTD (`landtex.vanilla_usage`: headers only, the vanilla terrain archives store BTDs uncompressed) and
picks, per category, the matching LTEX that vanilla terrain uses most; a category with no vanilla-used match takes the
plain ground (LDirtFootprints01). The picks and their vanilla BTD counts are printed and kept in `ltex_mapping.json`.
`scripts\terrain\survey_ltex.py` prints the whole usage table, the unused LTEX and each record's fields.

### Skyrim's own ground textures (`--skyrim-ground`; supported hypothesis, not yet tested in game)
The BTD's LTEX table stores raw FormIDs, and a new LTEX in a mod plugin has no fixed FormID at run time, so
`src/fo4sf/skyrimground.py` reuses spare Starfield.esm LTEX records instead: ones no vanilla BTD lists and no BIOM / GCVR
/ PNDT / SFBK record names. The most-covering Skyrim landscape texture sets (TXST TX00 diffuse, TX01 normal; flat normal
when absent) are converted like object textures, with the material cloned from the plain ground's own vanilla material
(LDirtFootprints01's BNAM, read from ContentResources.zip) instead of the object template. dotnet/TerrainOverlays
overrides each chosen record (same FormKey, vanilla material type and friction kept) with BNAM pointing at the new
material (`ltex_overrides` in overlays_params.json). Skyrim textures beyond the spare records borrow the converted one of
their category with the most coverage. Vanilla planets do not use the overridden records, so they look the same.
Build: `make_skyrim_overlay.py build ... --skyrim-ground --content-resources <Starfield>\Tools\ContentResources.zip
--texconv <texconv.exe>` (implies `--land-textures`); textures and materials are staged under the build's `Data`.

## Not included
Objects (statics, trees, buildings: now on branch `skyrim/objects`, [skyrim-objects.md](skyrim-objects.md)), water (Tamriel's sea
and lakes are dry basins at Mars gravity), grass, object LOD, navmesh,
actors. The walled cities (separate WRLDs): branch `skyrim/cities`, [skyrim-cities.md](skyrim-cities.md).

## Running it (Windows; outputs stay outside the repo)

    python scripts\terrain\make_skyrim_overlay.py info --skyrim "<Skyrim Special Edition>\Data\Skyrim.esm" --find river
    python scripts\terrain\make_skyrim_overlay.py build --skyrim "<...>\Skyrim.esm" --sf-data "<Starfield>\Data" ^
        --out C:\Modding\staging\skyrim_tamriel
    dotnet run --project dotnet\TerrainOverlays -c Release -- "<Starfield>\Data\Starfield.esm" C:\Modding\staging\skyrim_tamriel
    python scripts\terrain\make_skyrim_overlay.py check --sf-data "<Starfield>\Data" --out C:\Modding\staging\skyrim_tamriel

Options: `--cells X0 X1 Y0 Y1` (a smaller Skyrim cell rectangle, e.g. a first test of one hold), `--arrival
<cell EditorID | X,Y>` (default `Riverwood`; falls back to the overlay centre if no such cell), `--landmark ...`
(repeatable, extra probe targets), `--display-name`, and any `make_cw_overlays.py build` option (`--mask-writer
builtin` without texconv, `--no-mars`, `--ray-distances ...`). Negative coordinates work as `--landmark -30,-20`. `--land-textures` (+ `--ltex-mapping <edited json>`) adds Skyrim's ground
textures (section above).

Install by hand (game closed; the runner's `exp_install.py --pack` on `claude/integration-1011` does the same): pack
the staged `Data\Terrain`, `Data\meshes`, `Data\textures` into `SkyrimTerrainTamriel - Main.ba2` with
`Archive2.exe Terrain,meshes,textures -create=<...>\SkyrimTerrainTamriel - Main.ba2 -root=<staged>\Data
-format=General -compression=None`, copy it, `SkyrimTerrainTamriel.esm` and `SkyrimTerrainTamriel_Mars.esm` to the game's
Data folder and add both to `Plugins.txt` (`*` prefix). In game: `tgm`, `coc SKY_TamrielRiverwoodSpawn`, then the
points in `README.txt` / `plan.json`. Keep every `player.setpos` move within about 2 cells (200 m) per axis
(core64c.md teleport rule); longer jumps raised "Boundary Reached" and hung.

## Reading the result
| Observation | Meaning |
|---|---|
| Arrival and probes at Skyrim height / 70 (within 0.5 m) | Skyrim terrain loads as native Starfield terrain; H holds for Skyrim |
| Heights scaled by a constant factor | Skyrim's unit differs from FO4's (refutes H for Skyrim) |
| Probes far from the arrival hang at the drop height | streaming distance, as measured for core64; compare per ray |
| No ground at the arrival | compare with core64 on the same install (the records are the same code path) |

**First in-game test of `--skyrim-ground` (owner, 2026-10-15):** built and installed cleanly (55 spare Starfield LTEX
records, 55 of Skyrim's 66 ground textures in use converted, 10 borrowing). The ground went from plain to a detailed
reddish dirt that does not look like Riverwood. Not yet known whether that is Skyrim's texture tinted (the Mars sky
turns Skyrim's green pines brown-grey too; Starfield may also tint terrain with the planet's ground colour) or the
overrides not taking effect. `--skyrim-ground-test` paints a magenta / green checkerboard into every converted ground
texture to tell the two apart. Grass is separate: Skyrim's grass is GRAS objects scattered over grass textures, not
translated yet.
