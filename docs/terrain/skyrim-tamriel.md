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
Checkerboard result (owner, same day): the checkers cover the ground with Skyrim's layout, so the overridden LTEX records
and cloned materials are what the terrain draws. Colours are washed toward pink (Mars light) but recognisable; a white
speckle overlays them (likely template texture slots left at the vanilla files); one texture repeat is about 4 m
(Skyrim's is about 10 m). Riverwood's green comes largely from Skyrim's LAND vertex colours (VCLR) and grass objects,
neither translated yet. The build now prints the template's texture slots and writes it to ground_template.mat.json.
The template (owner's `ground_template.mat.json`, `Materials\Terrain\DirtFootprints01.mat`) uses shader model
`Terrain1Layer` with five texture slots (Albedo 0, Normal 1, Roughness 3, AmbientOcclusion 5, Height 6) and a
`BSMaterial::TerrainSettingsComponent` (TilingDistance 3.2 m, MaxDisplacement 0.24, RotationAngle 148, BlendSoftness
0.28, DisplacementMidpoint 0.504). The speckle was the vanilla footprint AO / height maps left in slots 5 / 6. Skyrim
ground materials now get a shared white AO and mid-grey (flat) height map, MaxDisplacement 0, and TilingDistance 9.75 m
(Skyrim repeats a landscape texture ~6 times per 4,096-unit cell; `--skyrim-ground-tiling` to change).

### Another planet (`--planet`; owner's idea: Jemison, away from New Atlantis; not tested in game)
Mars's atmosphere and weather tint everything (stone, wood and snow share the ground's sepia cast). Owner's SfInspect
dumps: the Mars template world `LC172World` carries the Mars biome `2A3777` and no climate; its location
`LC172WorldLocation` sits under `SSol_PMars_Surface` (01B736). Jemison registers only `NewAtlantis` (stored latitude
0.7111, longitude 2.2810 rad; SfInspect prints the two swapped), which uses biome `1CBD6A` and climate `24E982`; the
Jemison surface location is `SAlphaCentauri_PJemison_Surface` (01AB2B).
`make_skyrim_overlay.py build --planet JemisonPlanetData --latlon -0.3 -0.8606 --biome 1CBD6A --climate 24E982
--location-parent 01AB2B` registers the overlay on Jemison half a turn of longitude from New Atlantis and keeps the
generic Mars overlay records as templates, replacing only the world's biome / climate and the location's parent
(`world_overrides`, `location_parent` in overlays_params.json; `--template-*` still swap whole records).
First Jemison test (owner): HUD read JEMISON, so the registration took; but it was night (half a turn of longitude from
New Atlantis: opposite local time) and the player floated in an ocean with Skyrim's mountains rising out of it (Jemison
has a sea level; Mars has none, and Riverwood sits near 0 m in the overlay frame). Next: same longitude as New Atlantis,
another latitude (`--latlon -0.6 2.281`), and `--height-offset <m>` (terrain + objects lifted together; objects through
`height_offset_m` in overlays_params.json, applied in make_skyrim_objects.to_local) so Skyrim's sea (-14000 units =
-200 m) meets Jemison's sea level, measured with `player.getpos z` at the water surface.

**Riverwood on Jemison (owner, 2026-10-16):** `--planet JemisonPlanetData --latlon -0.6 2.281 --biome 1CBD6A --climate
24E982 --location-parent 01AB2B --height-offset 185` (Jemison's sea level measured at about -15 m in the overlay frame
with `player.getpos z`; Skyrim's sea is -200 m): daylight, blue sky with clouds, the HUD reads JEMISON, Riverwood dry
and in place, colours close to Skyrim's (green pines, grey stone, pale thatch). Mars's atmosphere was the sepia cast.
Remaining on the ground: hard-edged blobs where Skyrim textures blend (snow over dirt), from the flat height maps that
Terrain1Layer blends by. Each Skyrim ground material now gets a height map from its own detail
(`skyrimground.height_from_diffuse`: luminance high-pass, mean 128, fixed spread, so no texture always wins), with
MaxDisplacement still 0; `--skyrim-ground-flat-height` restores the flat maps.
Detail height maps did not change the specks (owner's next close-ups), so the cause is the encoding: 3-bit alphas
that the renderer reads as a probability (fo76utils' rule, now matching what is seen) turn Skyrim's faint, wide layers
(a 15-30 % dusting of snow or gravel) into hard-edged scattered specks. `--ltex-blend solid` (now the default) snaps
each alpha to 0 or 7 at one half: a sample shows the layer that covers most of what is left there, faint layers give
way to the ones below. `--ltex-blend dither` keeps the old encoding.
Solid blending did not remove the specks either (owner, same day), so they are most likely inside one texture or its
conversion, not the blend. `scripts\terrain\ground_at.py --pos X Y` (from `player.getpos x / y`) prints the Skyrim LTEX
layers at that spot and what the staged BTD draws there, and with `--zip` exports those Skyrim textures as PNG previews.
`ground_at.py` at a white-blob spot (owner, merge shift (600, -1300) m): Skyrim paints 100 % `LDirt02` there and the
BTD draws `LDirt02` as base with every overlay at alpha 0, so the blobs are not blending. Skyrim's `Dirt02.dds` has no
blobs; its alpha is a speckled specular mask. Suspect: the colour texture kept that alpha (BC1 keeps 1-bit alpha) and
Terrain1Layer reads albedo alpha. Ground colours are now written opaque (`--skyrim-ground-keep-alpha` keeps it);
`--skyrim-ground-flat-normal` exists to rule the normal maps in or out if blobs remain.
Owner's test with the alpha forced to 1: the specks were gone but the whole Dirt02 area turned into one pale, smooth,
sky-reflecting patch. So Terrain1Layer reads albedo alpha as a smooth, frost-like sheen: Skyrim's specular alpha (bright
specks) drew the blobs, alpha 1 everywhere drew the patch, and the alpha-0 areas between the blobs looked like proper
dirt. Default is now alpha 0 (`--skyrim-ground-alpha zero`), written as BC3 because BC1 turns alpha-0 texels black.
Correction (owner's alpha-0 test: still one pale patch): the alpha was a red herring. BC1 turned every low-alpha texel of
Dirt02 black, so the "proper dirt" between the old blobs was black texels and the blobs were the texture's real colour,
drawn pale and sky-reflecting. A very dark albedo reading as a mirror points at roughness: the object converter's
uniform roughness (190 / 255) is apparently read the other way round by the terrain shader. Skyrim ground materials now
keep the vanilla dirt's own roughness map (`--skyrim-ground-roughness vanilla`, default; `uniform` for the old value).
Alpha stays 0 in BC3 (harmless, and BC1's black texels are avoided).
`dds_info.py` (owner): vanilla `DirtFootprints01_color` is BC1_UNORM_SRGB 2048 px averaging sRGB (144, 109, 90); our
`ldirt02_color` is BC3_UNORM_SRGB 1024 px averaging (44, 43, 36), normal BC5_SNORM and roughness BC4 like vanilla. The
file is right; the colour is about a third as bright. Skyrim draws its ground dark and brightens it with vertex colour;
under Starfield's PBR a near-black ground is dominated by the sky's Fresnel reflection, which explains the pale,
detail-less, sky-tinted patch and why alpha and roughness changes did nothing while the brighter pine-needle textures
looked fine. Each Skyrim ground colour is now scaled in linear light to a mean luminance of 0.15
(`--skyrim-ground-brightness`, vanilla dirt about 0.17; 0 = off), hue and detail kept.

### Colour tests: the BTD texture index rule (2026-10-16)
`--skyrim-ground-colours` painted six Skyrim textures solid. The pale patch (base LDirt02 by `ground_at.py`) never
took LDirt02's colour; cyan (LDirt02) showed on a hillside, blue (LFieldGrass02NoGrass) in the river, and skipping
one LTEX slot (`--skyrim-ground-skip-slots 00030139`) changed which texture filled the patch. Reading quadrant byte
b as table entry b - 1 instead of n - b (the Fallout 76 rule from fo76utils) mirrors the sorted table, which fits
all three: LDirt02 (entry 0) showed the last entry, which the slot skip replaced. **Supported hypothesis**: the build
now writes `--ltex-index head` (b = index + 1); `--ltex-index tail` rebuilds the old way for comparison. Next test:
the same colour build with head, expecting cyan on the village paths, red under the pines, magenta/yellow in the river.
Follow-up with `ground_at.py` at the old pale spot (getpos 866.21, -1956.37): Skyrim paints LDirt02 100 %, the
build had five overlays at alpha 0 and LDirt02 as a byte-5 base, and the game showed blue = overlay 4. So Starfield
reads only bytes 0..4 and the base is the last valid one among them (**supported hypothesis**). The build now writes
at most four overlays and the base right after them (single texture: `1 0 0 0 0 0 0 0`, vanilla's form).
**Verified in game (2026-10-16):** with the head index rule and the base inside bytes 0..4 the colour test put every
painted texture where Skyrim paints it (LDirt02 cyan under the tree at getpos 866, -1956), and the normal build shows
Skyrim's own ground textures there (dirt, pine needles, riverbed). Still missing: Skyrim's per-vertex land colour
(VCLR, which tints the textures warmer / greener in Skyrim), grass (GRAS) and the river water.
Side-by-sides with Skyrim (same Riverwood spots) showed our ground far paler and greyer. Now: `--skyrim-ground-brightness`
defaults to 0 (Skyrim's own colours; the 0.15 scaling was added for the patch that turned out to be the index bug),
and `--skyrim-ground-tint vertex` (default) multiplies each Skyrim ground texture by the mean LAND VCLR vertex colour
where Skyrim paints it, the way Skyrim tints per vertex (one tint per texture: an approximation).
Grass-field close-up (2026-10-16): Skyrim's LFieldGrass texture drew as a smooth, wet-looking dark sheet with only its
flowers visible. The roughness / colour-alpha defaults were chosen while the index bug drew other textures, so they
are reset: `--skyrim-ground-roughness matte` (default; a fully rough map, Skyrim's ground has no sheen) and
`--skyrim-ground-alpha one` (default; BC1 like the vanilla dirt). `vanilla` / `zero` remain for comparison.
**Verified in game (2026-10-16):** with colour alpha zero (BC3) the Skyrim ground lost its texture and went dark a few
metres away while objects with the same texture kept it; rebuilt with `--skyrim-ground-alpha one` (BC1, the new
default) and `--skyrim-ground-roughness matte`, the distant darkening is gone. Terrain1Layer reads the albedo alpha;
keep it at 1 like the vanilla dirt.

## Water (`--skyrim-water`, 2026-10-16)
Skyrim's rivers and lakes are cell water: DATA flag 0x2 and an XCLW level per cell (the sea is the worldspace
default). Starfield keeps the same cell fields (Mutagen Starfield Cell.xml: XCLW, XCWT, HasWater) and its worlds list
cells with their own level (WRLD XCLW CellWaterHeightLocations + WHGT WaterHeights; New Atlantis lists 8 cells in the
owner's dump). `build --skyrim-water` gives each 100 m Starfield cell the Skyrim level that keeps most of Skyrim's wet /
dry LAND vertices inside it right (src/fo4sf/skyrimwater.py); TerrainOverlays sets HasWater, WaterHeight, Water
(`--skyrim-water-form`, default WATR 01C0CC WaterClearLake) and fills the world's two lists. Sea-level cells stay the planet ocean.
**Supported hypothesis**, not yet seen in game. Not included: Skyrim's placed waterfalls / flowing-water effect meshes.
**Verified in game (2026-10-16):** Riverwood's river fills its channel at Skyrim's level. Water type: the owner
compared WaterClear 000018 (bright lagoon green), WaterOceanDark 0560D0, WaterClearLake 01C0CC and WaterSilt 190D1F
and picked WaterClearLake, now the default. `SfInspect list Water` lists the 15 Starfield.esm WATR records.
Owner's wider Jemison views (2026-10-16): (1) far away, Skyrim grass showed orange / purple sand and dirt showed snow:
the distant terrain draws with something tied to the LTEX record, not to the override's material, so it shows the
spare records' VANILLA looks (LSandRipple01_Orange, LSandRough03_Purple, LSnowLumpy01, ...). Spare records are now
matched by ground kind (skyrimground.slot_score: same category, related one, coloured variants last); the build prints
how many matched. **Supported hypothesis.** (2) Flat water sheets hung in the air beside mountain lakes: a cell now
refuses any level that floods more than 2 % of ground Skyrim keeps dry. (3) Water default is now WaterOceanDark
0560D0 (owner's final pick). (4) Mountains look bare and white because only the cells around Riverwood have objects:
Skyrim covers its mountains with mountain / cliff meshes; widen `make_skyrim_objects.py export --radius`.
**Correction (2026-10-16):** the orange ground (owner's close-up at getpos 911.74, -1783.52: boot prints) is
Starfield's own LDirtFootprints01, the plain-ground fallback. Skyrim's engine-default land texture (BTXT FormID 0) and
the Skyrim textures beyond the spare records mapped to it, near and far; the "distant view shows the record's vanilla
look" idea above was wrong for that. With `--skyrim-ground` every category and the default now map to a converted
Skyrim texture (default: LDirt02), so no vanilla Starfield ground remains.
