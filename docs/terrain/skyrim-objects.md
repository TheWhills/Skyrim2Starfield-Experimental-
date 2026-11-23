# Skyrim's exterior objects on the Tamriel overlay

Branch `skyrim/objects`, on top of [skyrim-tamriel.md](skyrim-tamriel.md) (the terrain). Status (updated
2026-11-17): **run on the real game files and verified in game** since 2026-10-15 (Riverwood's objects on the
overlay; distant-object LOD 2026-10-17; grass as static patches); details in the dated sections below (the first
status, "synthetic data only, not run in game", was the state before those runs). Labels: **verified** = measured here; **supported** = supported
hypothesis; **unresolved**.

## What it does
core64c's object path (docs/terrain/core64c.md: 648,358 FO4 objects on the core64 terrain, standing on it in game
within 0.02 m) with Skyrim as the source. Rocks, cliffs, trees, ruins, buildings, bridges, fences and clutter that
Skyrim places in Tamriel become plain Starfield statics at Skyrim position / 70 on `SKY_Tamriel`, in the same plugin
after the terrain records (dotnet/TerrainOverlays' existing `objects.json` mode, unchanged).

| File | What |
|---|---|
| `src/fo4sf/bsa.py` | Skyrim archives: BSA v104 (zlib) / v105 (SE, LZ4 frames), embedded names; `SkyrimArchives` = the Data folder in load order, loose files win (the interface pipeline.Converter uses) |
| `src/fo4sf/skyrimnif.py` | Skyrim SE meshes (NIF BS 100): BSTriShape / BSLODTriShape (vertex layout from the descriptor), NiTriShape / NiTriStrips (both "Material CRC" variants), texture sets, NiAlphaProperty; Skyrim Havok collision -> triangles: compressed mesh (chunks, strips, big triangles, transforms), packed strips, box, sphere, capsule, convex vertices, list, (convex) transform shapes, rigid body T; scaled by 69.99124 game units per havok unit |
| `src/fo4sf/skyrimconvert.py` | `SkyrimConverter(pipeline.Converter)`: FO4's texture conversion, caps and material templates reused; Skyrim materials (diffuse + normal; alpha test -> cutout, alpha blend -> decal, effect shaders skipped); double-sided shapes (SLSF2_Double_Sided: leaves, banners, cloth) get a mirrored back copy of their triangles, so no two-sided material is needed; collision as boxes (below) |
| `src/fo4sf/skyrimrefs.py` | Skyrim.esm -> the schema-v2 placement export FO4 uses (docs/CELL-EXPORT.md): base type, model (MODL / armour MOD2), position, rotation, scale, disabled flag, persistence, cell, enable parent; actors deferred |
| `scripts/terrain/make_skyrim_objects.py` | `export / select / convert / stage / check` |
| `src/fo4sf/checkpoints.py` | optional output prefix (FO4 default `fo4port` unchanged), so resumed Skyrim conversions verify their materials and textures too |

## Collision: Skyrim's own, approximated by boxes (supported, not in-game tested)
Starfield's mesh collision is written here only by transplanting FO4's (same Havok generation); Skyrim's Havok 2010
data is not transplantable and no Starfield compressed-mesh *encoder* exists yet. So every model's own Skyrim collision
is decoded to triangles and rebuilt from the box body verified in game (sfcollision.box_blob, docs/spikes/S6-collision.md):

* **Landscape pieces** (path under `landscape\`, or rock / cliff / mountain / boulder / glacier): **column boxes**.
  The collision surface is rasterised into vertical columns from the piece's lowest point to the highest surface point
  in each cell; neighbouring columns with matching tops merge; the grid coarsens until the count fits a budget of one
  box per 16 m2 of footprint (128 to 512). Nothing is dropped, so no holes: big mountain slabs get coarse columns.
  Measured: 30 m rock 73 boxes (2.6 m cells), 120 m cliff 506 (4.1 m), 400 m mountain 511 (13.8 m), 0.02-0.06 s each.
  Walkable tops stay within about half a cell times the slope.
* **Everything else** (buildings, ruins, bridges, props): FO4 architecture's surface + voxel boxes (sfcollision.mesh_boxes),
  which keep floors, walls and doorways open.
* **No collision in Skyrim -> none here** (grass, ferns, small plants, cobwebs).
* Each converted model records render and collision bounds and whether they overlap (`collision_overlaps_render`
  in the manifest): on real data, a model where they do not is the first sign of a misread collision layout.

## Not included
Actors / NPCs (deferred in the export), lights, sound and idle markers, placed water planes, effects (fog, glow,
waterfall spray), doors that open (Skyrim doors are statics here; load doors lead nowhere), the walled-city worldspaces,
snow / moss directional overlays on rocks (Skyrim's projected material is not translated: rocks show their base
texture), tree wind animation, object LOD. Roughness is uniform (Skyrim keeps specular in the normal map's alpha).

## First run on real files: one command, one report
Before any long conversion, run the diagnostic. It checks the setup (numpy, Pillow, lz4, .NET 9, texconv, Skyrim.esm,
Starfield.esm, ContentResources.zip, the box template), reads Tamriel's terrain, opens every BSA, exports every placed
reference, **parses up to 3,000 distinct Skyrim models read-only** (geometry blocks, collision decoded, unsupported
collision types, collision bounds against render bounds, parse errors grouped) and really converts 20 models near
Riverwood. A few minutes; nothing is installed into either game.

    python -I scripts\skyrim_first_run.py --skyrim-data "<Skyrim Special Edition>\Data" --starfield "<Starfield>" ^
        --texconv "<xEdit>\Edit Scripts\texconv.exe" --work C:\Modding\work\skyrim_first_run

It writes `report.txt` (short: paste it back) and `report.json` (everything). The survey's `MISPLACED` count and
`parse error` lines are where a wrong field layout from nif.xml would show.

## Running it (Windows; outputs stay outside the repo)
Prerequisites: the staged terrain (`make_skyrim_overlay.py build`), Python with `numpy`, `Pillow` and **`lz4`**
(`pip install numpy pillow lz4`), `texconv.exe` (xEdit's `Edit Scripts`), `Starfield\Tools\ContentResources.zip` (Creation
Kit), the .NET 9 SDK. Start with a small region; find its cells with
`make_skyrim_overlay.py info --skyrim <Skyrim.esm> --find riverwood`.

    python scripts\terrain\make_skyrim_objects.py export --skyrim "<Skyrim SE>\Data\Skyrim.esm" --work C:\Modding\work\sky_obj ^
        --cells X0 X1 Y0 Y1
    python scripts\terrain\make_skyrim_objects.py select --work C:\Modding\work\sky_obj --terrain C:\Modding\staging\skyrim_tamriel
    python scripts\terrain\make_skyrim_objects.py convert --work C:\Modding\work\sky_obj --skyrim-data "<Skyrim SE>\Data" ^
        --content-resources "<Starfield>\Tools\ContentResources.zip" --texconv "<xEdit>\Edit Scripts\texconv.exe" ^
        --starfield-data "<Starfield>\Data" --max-texture 1024 --resume
    python scripts\terrain\make_skyrim_objects.py stage --work C:\Modding\work\sky_obj --terrain C:\Modding\staging\skyrim_tamriel ^
        --out C:\Modding\staging\skyrim_objects --sf-esm "<Starfield>\Data\Starfield.esm"
    python scripts\terrain\make_skyrim_objects.py check --out C:\Modding\staging\skyrim_objects

`export --around Riverwood --radius 2` picks the 5 x 5 Skyrim cells around a named exterior cell (or `X,Y`) instead of
`--cells`. Install / uninstall with `scripts\deploy_skyrim_exterior.py` (below).

`--max-texture 1024` keeps one archive under 4 GiB for large regions (core64c needed caps for the Commonwealth);
`check` fails when the staged Data tree would not fit one stored archive. Install exactly as the terrain
(skyrim-tamriel.md): Archive2 over `Terrain,meshes,geometries,materials,textures`, both plugins, `coc` the arrival.
`scripts\deploy_skyrim_exterior.py install --staging <stage --out> --starfield <game>` does that reversibly: one stored
(`-compression=None`) General archive `<plugin> - Main.ba2`, both plugins, Plugins.txt lines, a manifest
(`Data\SkyrimExterior.deploy.json`); it refuses to overwrite files or to sit next to another `*_Mars.esm` terrain
experiment. `uninstall` removes exactly what it added.

## What `check` verifies, and what to read first on real data
Every base model, every geometry / material file the models name and every converted texture the materials name
exists; every reference lies inside the BTD's cells; the archive fits; and the **frame check**: each object's origin
height minus the terrain height under it. Skyrim's rocks and trees sit on the ground, so on real data the median must
be near 0 (synthetic: 0.00 m, 6 of 6 within 3 m). A large constant offset means the object and terrain frames disagree.

On the first real run also read `convert/manifest.json`: `failure_reasons` (counts), `collision` (columns / surfaces /
none per model), material fallbacks, and any model with `"collision_overlaps_render": false` or `"unsupported"`
collision shapes (layouts read from niftools' nif.xml, checked on synthetic files only).

## Lessons from tes4skyrim (bryantmh/tes4skyrim), which WRITES the Skyrim formats read here
Read 2026-10-14 from its docs and code (`docs/commentary/asset_convert_collision.md`, `asset_convert_nif.md`,
`asset_convert_terrain.md`, `tes5_import_landscape.md`, `docs/audits/worldspace_havok_range.md`,
`asset_convert/collision/cms.py`). It converts Oblivion / Morrowind / Fallout into Skyrim SE and checks its output
against vanilla Skyrim and in game, so its layouts are the best evidence available here short of real files.

Fixed on this branch because of it:
* **bhkRigidBody translation is at byte 52 and rotation at 68** (bhkWorldObject 28 + bhkEntityCInfo 4 +
  bhkRigidBodyCInfo2010 212 = 250 bytes; current nif.xml field order). This reader used 56 / 72: on an identity body
  the four floats at 72 are (0, 0, 1, 0), itself a unit quaternion, so every rigid-body-T collision would have been
  turned 180 degrees. Regression test: `test_rigid_body_transform_offsets_and_plain_bodies` (fails at 56 / 72).
* ~~Skyrim applies the transform on PLAIN bhkRigidBody too~~ **CORRECTED 2026-10-15 on the owner's files:** applying
  it put 285 of 2,473 surveyed vanilla models' collision off the visible mesh (clutter baskets 768 units away, Shack
  kit planks ~1,600, the Orc door's body repeating its node's translation so it doubled); applying it on
  bhkRigidBodyT only fixes 284 of them (the 285th is a collision-only wall piece). Plain bodies' stored transform is
  now ignored; the first run re-measures every rule each time (`misplaced_fixed_by`).
* **Compressed-mesh vertices**: `R x (chunk translation + transform translation + u16 / 1000)` (NifSkope drawCMS,
  tes4skyrim `cms.py`, validated there against the engine's own shape keys), with the fixed 1/1000 step. Vanilla uses
  one identity transform per mesh, so this changes nothing on vanilla data; it is the verified order.

Confirmed (no change needed):
* Havok scale: 1 havok unit = 69.9913 game units, measured in SkyrimSE.exe (here 69.99124).
* Vanilla Skyrim collision is always MOPP + compressed mesh for statics (0 of 17,216 vanilla meshes ship
  bhkPackedNiTriStripsShape, 0 ship bhkMultiSphereShape); clutter adds boxes, convex hulls, lists and transform shapes.
* A rigid body sits at its OWNING node's full world transform (rotation, uniform scale, translation).
* Vanilla trees and flora use NiTriShape (not only BSTriShape); leaves carry NiAlphaProperty 0x92EC, threshold 128
  (test bit 0x200 set, blend bit 0x1 clear).
* LAND: BTXT / ATXT hold LTEX FormIDs directly; VTXT is a 17 x 17 grid, position = row x 17 + column, layers in ATXT
  layer order; row 0 is SOUTH for VHGT, VTXT and VCLR.
* Unpainted quadrants (no BTXT) are common (22.6 % of Oblivion's Tamriel quadrants, the sea floor): the engine draws
  its default land texture there; `landtex` maps them to the engine-default entry.

To keep in mind (not done):
* **Absent LAND past the coastline means "no ground"**; edge-extending heights there invents terrain with steps
  between columns. Inside the landmass a fill is right. Done: the Tamriel overlay's square padding now eases to the
  default land height outside the LAND extent instead of edge-extending (skyrim-tamriel.md).
* **Water**, when it is translated: a cell has water when CELL DATA bit 0x02 is set; its height is XCLW, but
  `-2147483648.0` (0xCF000000) is the "use the worldspace default" sentinel (WRLD DNAM), never a height.
* **Specular**: Skyrim's normal-map ALPHA is the specular mask (landscape and objects); roughness here is uniform.
  Deriving Starfield roughness from that alpha is the next material improvement.
* Grass in Skyrim comes only from LAND layers whose LTEX has GNAM (no references): a later ground-cover step reads it
  from the same layers `landtex` already decodes.
* Starfield community leads (AssetWatcher collision, edge blending, double-sided surfaces, Mars map overrides):
  [starfield-community-notes.md](starfield-community-notes.md).
* Skyrim's own +-64-cell Havok world limit (262,144 units) is a Skyrim engine constant; it does not apply in
  Starfield, but Tamriel's real extent (about -57..61) sits inside it anyway.

## First real run (2026-10-15, owner's Skyrim SE + 76 Creation Club archives)
Verified: terrain (11,186 cells, no holes, -529..563 m), 93 archives / 35,489 textures read, 250,824 placed references
(220,258 to convert, 3,034 models), worn armor meshes (400 parsed, 0 failures, max 77 bones per shape). Fixed from
it: Skyrim's BSLODTriShape is NiTriShape-based (16 vanilla stumps / logs / flora failed to parse), plain rigid-body
transforms (above), ARMO's MODL is a list of armature FormIDs not a path (75 garbage model names), the texture
sample picking an Interface .dds. Second run: 0 parse failures, 0 missing models, collision on the render mesh for
2,543 of 2,544 (the last is the collision-only wrwalltower01collpiece); the sample converted 20 of 20 models near
Riverwood (27 materials). Fixed after it: shader texture paths with Bethesda's build folder in front
(`skyrimhd\build\pc\data\textures\...`, thicket01 / thistle01). Open: cell-edge seams up to 96 units (1.4 m)
somewhere in Tamriel.

## First in-game exterior (owner, 2026-10-15): Riverwood on Mars

Full Tamriel overlay (11,186 cells, 73 x 73 Starfield cells, BTD 133 MB) + the 5 x 5 Skyrim cells around Riverwood
(`export --around Riverwood --radius 2`: 2,183 references; 258 models, 255 converted, 3 effect-only; 1,951 placed;
offline frame check median -0.115 m, 95 % within 3 m; Data 0.58 GiB), installed with `deploy_skyrim_exterior.py`.
`coc SKY_TamrielRiverwoodSpawn` did nothing at first: the plugin was not active in game although the installer had added
it to Plugins.txt; once activated, the arrival worked. In game: the village (houses, mill and water wheel, stone bridge,
walkways, carts), trees and rocks stand on terrain shaped like Riverwood's valley, with the mountains behind. Ground
is Mars's own material (Skyrim ground textures not enabled), the river is a dry bed (no water), no grass.
[screenshot: owner's chat, not in the repo]

## Grass (make_skyrim_objects.py grass)
Skyrim grows grass at run time from the landscape textures (LTEX GNAM -> GRAS: model, density, slope range, position
and height variation). Starfield has nothing that does this for a custom BTD overlay, so `grass` scatters it once
(src/fo4sf/skyrimgrass.py): per Skyrim cell around `--around` (default Riverwood, `--radius` cells), a jittered grid
every `--grass-spacing` metres (default 1.5) picks a painted texture by weight, one of its grasses, and keeps the
point with the grass's density x `--grass-density`, within its slope range and above the cell's water (XCLW). All
instances of one model in one cell are merged into one static (`SKY_Grass_c<x>_<y>_<model>`, no collision) placed by
one reference at the cell's centre. Grass without a normal map converts with a flat normal. `stage` adds
<work>/grass/grass.json automatically (`--no-grass` leaves it out). Not yet: wind, colour range, fit-to-slope tilt,
Skyrim's fade distance (patches draw as ordinary statics).
First in-game look (2026-10-16): only sparse, pale yellow clumps. Changes: `--grass-spacing` default 0.75 m (was 1.5;
Skyrim tries every 20-60 units, 0.3-0.9 m), and `--grass-tint vertex` (default) multiplies each grass model's texture
by the mean Skyrim vertex colour (VCLR) under its instances, as Skyrim tints grass with the ground.

## Native grass: Skyrim's grass grown by Starfield's grass system (2026-10-27, to test)
Owner: the patches above are plain statics (no wind, no fade / density settings, no LOD, pop-in like any object).
Starfield has a run-time grass system (xEdit's wbDefinitionsSF1, format only; `src/fo4sf/sfgrass.py`):
* **GRAS** grass: model, DNAM = contrast, cluster scale, height range, colour range, wind frequency, water clamps,
  max density, min / max slope, flags (vertex lighting, uniform scaling, fits slope, apply between), coverage,
  dirtiness. Skyrim's GRAS has the same core fields and the same flag bits.
* **GCVR** ground cover: grasses (each with an override density, -1 = own), the landscape textures it grows on, a
  painted-material threshold. Skyrim's LTEX -> GRAS link in reverse.
* **BIOM** biome terrain entries {mask, LTEX, GCVR}: how procedural planet surfaces get grass.
**Unresolved:** whether the engine grows a GCVR's grass on a hand-made BTD world like the overlay (painted with the
listed texture), or only through a biome; the real GRAS DNAM layout (38 bytes from xEdit's field list); the scale of
Max Density; what a vanilla grass model needs. Two tools:
* `scripts/terrain/grass_survey.py --starfield ... --out ...` (read-only): the GRAS / GCVR / BIOM records, which LTEX
  carry cover, how many vanilla BTDs (and which world folders) paint one of them, DNAM sizes and the density range,
  block types / materials of a few vanilla grass models. If hand-made worlds paint cover textures, cover alone should
  work.
* **Survey run (owner, 2026-10-28), verified on Starfield.esm:** 189 GRAS, every DNAM 38 bytes with the layout above
  (e.g. GrassFieldDried04A: contrast 15, cluster 0.2, height range 0.35, colour range 0.1, wind 10, max density 94,
  slopes 0-50, flags 4 = fits slope, coverage 90, dirtiness 127 / 127); Max Density 2-98, the same percent scale as
  Skyrim's density (--density-scale 1). 96 GCVR, **all 96 used by biomes** (1,250 biome terrain entries), only ONE
  lists landscape textures itself (GC_GrassFieldDried01_Yellow: LGrassLive01_Red / 02_Yellow, threshold 0.44: a 0-1
  value, not 28), and **none of the 1,999 vanilla BTDs paints a texture a GCVR lists**. So ground cover is not driven by
  a GCVR's own texture list: it comes through the biomes' {mask, LTEX, GCVR} entries (masks: Base, Solid, FlatOuter,
  FlatInner, Talus, Flow, Path = procedural terrain regions). Grass models are ordinary one-shape statics (NiNode,
  BSXFlags, BSGeometry, MaterialID, BSLightingShaderProperty with a .mat), the same layout the converter writes.
  Second run (2026-10-28): biome entries spread over all 7 masks (Base 582, Solid 778, FlatOuter 825, FlatInner
  826, Talus 816, Flow 812, Path 363), 179 textures carry cover through biomes. Only 430 of 1,999 BTDs are named
  after a world with a biome, and none of those (the hand-made worlds: cities, sites) paints a biome-covered texture:
  **no vanilla hand-made world gets run-time grass from its BTD** (their greenery is placed objects). The 31 BTDs that
  do paint biome-covered textures are all planet-trait overlays (overlaytraitboiledseas*, ...diseasedbiosphere*,
  ...emergingtectonics*: LVolcanicMineralDeposit01, LMossForest01_Yellow, LVolcanicRoughSlab01), overlays placed on
  procedural planets like ours. Supported hypothesis: on an overlay the engine grows the cover its biome pairs with
  the painted texture. So the test build's default is now that route: the world's biome gets a {mask, LTEX, GCVR}
  entry per spare Skyrim LTEX and mask (all 7 by default).
  **First in-game test (owner, 2026-10-28, Nirn near Riverwood, terrain staged --no-grass): no grass.** The build itself
  ran clean (27 grasses, 19 covers, ForestDeciduousLifeJemison overridden with 133 entries; Nirn's land biome is that
  vanilla record, so the override reaches the planet). Candidates, cheapest first: the overlay world is a copy of
  LC172World, and if its WRLD DATA has No Grass (bit 7) the engine grows none whatever the biome says (the survey now
  prints the worlds' No Grass / Allow ProcGen flags, ours with --plugin); else the engine does not grow biome cover on
  BTD overlay terrain at all, and the patches stay (with fade work instead).
  **Flags checked (owner's survey, 2026-10-28):** SKY_Tamriel DATA 0x01 (Small World only), No Grass **off**, biome
  1CBD6A; LC172World the same (0x01, Mars biome 2A3777); NewAtlantis 0x00. Only 1 of 433 vanilla worlds sets No
  Grass and none sets FNAM Allow ProcGen. So the flag is not the cause. **Parked:** two routes tried (cover by texture
  list, cover through the world's biome on all masks), no vanilla hand-made world grows run-time grass, nothing left
  to test cheaply. Untested ideas for later: whether painted weights must pass the cover's threshold (0.44) with
  Skyrim's blended layers; a vanilla grass + vanilla cover on one of our textures as a control. Grass stays the baked
  patches; next for grass is their draw / fade distance.
* `scripts/terrain/skyrim_grass_native.py` (test build, MO2 mod S2SGrass.esm): a GRAS per Skyrim grass on the
  converted ground (vanilla GRAS copied: model = the converted Skyrim grass, single instance; Skyrim's density x
  --density-scale, slopes, height / colour range, flags), a GCVR per spare LTEX the terrain overrides (SKYG_...),
  listing the grasses of the Skyrim textures painted with it. Textures that fell back to a vanilla Starfield LTEX get
  no cover (it would grow Skyrim grass on vanilla planets). `--biome <EDID>` also overrides that biome with
  {LTEX, GCVR} entries (second attempt). Test with the terrain staged `--no-grass`.
* **Un-parked (2026-11-22, owner: Skyrim's grass as a Starfield grass type, with its fading).** The October biome
  route went to the wrong biome: it extended the world's land biome (ForestDeciduousLifeJemison), but Nirn's biome map
  is ocean everywhere (make_planet.py --land-px 0 since 2026-10-18), so the planet biome under Riverwood is Nirn's
  ocean biome (NirnOceanNoCoating, our copy of OceanLife04 in the _Mars plugin). Evidence that the engine applies that
  biome to the overlay: vanilla OceanLife04's slime global layer once coated every Riverwood object (why make_planet
  strips it). Supported hypothesis: ground cover is taken from the same biome. Now `--biome planet` (default) adds the
  {mask, LTEX, GCVR} entries to that biome: our own record, so no vanilla planet changes (Nirn's procedural sea floor
  may pick the Skyrim textures too). S2SGrass.esm then has SkyrimTerrainTamriel.esm and its _Mars plugin as masters
  and loads after them. `--control` lists one vanilla cover (the one the world's land biome uses most) on every
  converted texture instead: vanilla grass there but none with Skyrim's points at our grass records / models, none
  either way at the route. Without ltex_mapping.json the texture mapping is read off the installed terrain
  (refresh_btd.infer_mapping) and kept as ltex_mapping_inferred.json. Synthetic tests: tests/test_sfgrass.py
  (PlanetBiomeTests).
  Owner's build (2026-11-22 19:21, verified offline): mapping read off the installed terrain (66 Skyrim textures),
  27 grasses, 19 ground covers, NirnOceanNoCoating (02000801) overridden with 133 entries (19 x 7 masks), no model
  failures, no grassy Skyrim texture skipped. In game (owner, 19:22): no grass at Riverwood. Next: confirm the
  plugin loads (`help S2S_Cover 4`), then `--control` (vanilla cover) to separate the route from our grass.
  Owner's check (19:24): MO2 shows S2SGrass.esm active at index 0F, after SkyrimTerrainTamriel_Mars.esm (09);
  `help S2S_Cover 4` listed nothing. Unresolved whether that means the records are absent or only that the game keeps
  no EditorIDs for GCVR at run time (Starfield drops most EditorIDs); the load order is right. Control test next.
  **Control (owner, 19:26 / 19:31, verified in game): vanilla GC_MossMoundsGrass01 on all 55 converted textures,
  385 entries in NirnOceanNoCoating: no grass either.** So the biome route does not grow cover on this world at all,
  whatever the grass (three routes now: cover texture list, world biome, planet biome). Supported hypothesis: Starfield
  grows ground cover only where it generates the planet surface; a planet's master worldspace (ours, like New
  Atlantis) is hand-made cells, and no vanilla hand-made world gets run-time grass. Last cheap test:
  `--allow-procgen` also sets the world's Allow ProcGen flag (WRLD FNAM bit 3), which no vanilla world sets. If that
  grows nothing, grass stays placed objects and the work moves to making those behave like grass (wind, fade).
  **Allow ProcGen (owner, 20:00, verified in game): the game crashes on `coc` into the world** with the flag set
  (control cover on). So the flag does switch the engine onto another path for this world (planet generation), which
  then fails, probably for want of generation data a hand-made world does not have. Not usable as is; S2S Grass Native
  is left off. Supported hypothesis strengthened: ground cover belongs to the generated planet surface.
  What has and has not been probed (owner asked, 19:44): records (grass_survey: GRAS / GCVR / BIOM, world flags),
  vanilla BTDs (no ground cover data in Starfield's BTD layout; bytes 5..7 of each quadrant unresolved) and four
  in-game setups. Not yet: the engine itself, and where vanilla grass actually grows in game (procedural surface only,
  or also on hand-made terrain). `scripts/re/exe_strings.py` lists Starfield.exe's grass-related INI settings,
  console commands and RTTI class names (read-only), the cheap first look before Ghidra (docs/re/ghidra-ai-setup.md).
  **exe_strings.py on the owner's Starfield.exe (2026-11-22 20:01, verified: the strings exist; what they do is
  supported hypothesis):**
  - Two grass systems. (1) The planet generator (BSProcGen, BGSPlanet::ProcGen, DensityMapDB, GroundCover,
    BGSGroundCover, BGSBiome) with `bAllowProcGenOnOverlays:ProcGen`, `bDisableProcGen:ProcGen`,
    `fBiomePlacementPositionsMinDistanceFromOverlays:PlanetContent`: procgen is kept off overlays unless allowed.
    (2) A Skyrim-style cell grass manager: BGSGrassManager, AddCellGrassTask, CellGrass, "AddCellGrass [%i, %i]",
    folders `meshes\landscape\cellgrass\` and `landscape\grass\`, `sCellGrassSubdirectories:Grass`, GRASS\ among
    the archive root folders, `bAllowCreateGrass:Grass`, `iGrassCellRadius`, `fMin/MaxGrassDistance`,
    `fGrassStartFadeDistance`, `fGrassFadeDistance`, `bUseTerrainTintOnGrass`, `iMaxGrassTypesPerTexure`, and the
    GRAS flags (GRASS_FIT_SLOPE, GRASS_UNIFORM_SCALE, GRASS_VERTEX_LIGHTING, GRASS_BILLBOARD).
  - Console: ToggleGrass, **CreateGrassAt** ("Create a single piece of grass at specified worldspace coordinates"),
    **AddWorldSpaceToPlanetBiome** ("Adds a world space to a planet's biome"; a message reads "Use
    AddWorldspaceToPlanetBiome command instead of COC"), LandOnPlanetBiome, TestBiomePlanet, GetBiomeMaskValue.
  - So: the Allow ProcGen crash on coc fits "use AddWorldspaceToPlanetBiome instead of COC"; and grass may come per
    cell from prebuilt files (cell grass) rather than from the biome. Next: `cellgrass_survey.py` (which grass files
    the archives hold, per world), the console checks (bAllowCreateGrass, bAllowProcGenOnOverlays, CreateGrassAt's
    usage), and the control cover reached by landing on Nirn by ship instead of coc.
  **Creation Kit wiki, Grass page (owner's copy, 2026-11-22; Bethesda's documentation, edited 2026-10-19):**
  - Grass reaches the world only through a biome: GRAS -> GCVR -> the biome's Terrain Data ground cover drop-downs ->
    the biome on a planet (Galaxy View). **"Do not add Ground [cover] to Solid, Base, or Path masks."** Our builds added
    entries for all 7 masks; the default is now 2,3,4,5 (FlatOuter, FlatInner, Talus, Flow).
  - GCVR "Painter Material Threshold": hand-painted landscape (the Landscape Tool's materials, blended weights such as
    60 % grass / 40 % dirt) gets the ground cover where the material passes the threshold. So painted overlay terrain
    is meant to grow ground cover (refutes "only generated surfaces"), through the biome it is painted with.
  - Grass materials: VegetationTranslucent1Layer shader model (2-layer / emissive variants), AlphaTestThreshold no
    lower than 0.2, the vegetation (wind) settings, TerrainTintSettings on to blend with the ground. Our converted
    grass models use the ordinary static material: no wind, no terrain tint. To fix once grass grows at all.
  - Field meanings: Distribution, Contrast, Max Density; Min / Max Slope, Fit to Slope, Above / Below Water Clamp
    (fDistanceFromWaterLevelAbove), Apply Between; Height Range, Color Range (random darkening), Uniform Scaling,
    Vertex Lighting, Wind Frequency (cycles per game minute); GCVR Override Density.
  **Owner's runs (2026-11-22 20:15, verified):** control rebuilt with masks 2-5: GC_MossMoundsGrass01 on 55 textures,
  220 entries in NirnOceanNoCoating. cellgrass_survey.py: 694 grass files in 4 archives (190 vanilla grass NIFs under
  meshes\landscape\grass, textures; 25 in SkyrimTerrainTamriel - Main.ba2 = our baked grass's textures / materials),
  **no cell grass files and no top-level grass\ folder anywhere**. So the cell grass manager (AddCellGrass) has no
  prebuilt data: it presumably builds each cell's grass at run time from ground cover, as Skyrim's did from LTEX
  grass; no second route through files. 135 loose files are Creation Kit material sources under
  Data\Scripts\Source\Materials (e.g. Landscape\Grass\GrassJuniper.mat, GrassSagebrush01.mat): vanilla grass
  material templates (VegetationTranslucent1Layer) for our grass later.
  **Ship landing (owner, 2026-11-22 20:16, verified in game): new game, landed on Nirn at the Skyrim marker, control
  cover (masks 2-5) on: no grass.** So coc was not the cause either. Remaining lead (supported hypothesis): ground cover
  is picked per biome MASK, and our terrain carries none. Starfield's procedural surface computes masks; a painted
  overlay must store them somewhere we write nothing: quadrant bytes 5..7 (filled in 96.6 % of vanilla quadrants,
  0 in ours) or bit 15 of each sample word. vanilla_btd_survey.py now reports both (value histograms, valid entry /
  repeat of bytes 0..4, bit 15 share; --match overlaytrait for planet overlays); in game,
  `player.GetBiomeMaskValue <mask>` ("the ref's biome mask on the terrain at its position") on our ground would show
  whether the engine sees any mask there.
  **Owner's survey (2026-11-22 20:19, verified):** 12 largest hand-made worlds (62,352 quadrants) and 12 planet-trait
  overlays (948): **byte 6 is the only extra byte used** (non-zero in 96.6 % / 77.5 % of quadrants; values 1 or 2 in
  worlds, always 1 in the trait overlays, 8 once), bytes 5 and 7 always 0, bit 15 of the sample words never set.
  Byte 6's value never equals any of the quadrant's bytes 0..4. Ours writes 0 there. Read with the head rule it names
  table entry 0 or 1, which bytes 0..4 then never paint in that quadrant. Unresolved what it is: a sixth "texture"
  that is not drawn (e.g. the one ground cover or biome material comes from), or a small code. The survey now names the
  LTEX it would point at (from Starfield.esm), whether a biome gives that LTEX ground cover, and whether the file paints
  it anywhere with bytes 0..4.
  **Second survey run (owner, 20:23, verified):** vanilla LTEX tables start with Starfield's per-mask placeholder
  textures (LDefault006Base, LDefault005Flow, LDefault004FlatOut, ...), and byte 6 names one of the head entries:
  in the trait overlays always LDefault006Base (or 0); in the hand-made worlds LDefault006Base 55.7 %, LDefault005Flow
  14.7 %, or in the one world whose table starts with sand textures LSandSmooth01 29.4 %. Those textures are painted
  with bytes 0..4 elsewhere in the same files, never in the quadrant whose byte 6 names them. Supported hypothesis:
  byte 6 is the quadrant's mask / mask material (LDefault00N<Mask>), which ground cover is chosen by; ours (0) has
  none. Test: `scripts/terrain/btd_byte6.py set --mask FlatOut` (tools\owner\terrain_byte6.ps1) appends
  LDefault004FlatOut to our table (existing indices unchanged) and writes it into byte 6 of every quadrant, with the
  control cover (masks 2-5) on. `restore` puts the originals back.
  Owner's run (20:28, verified offline): LDefault004FlatOut (0001085F) appended as entry 56 of 56 (vanilla tables
  hold the LDefault textures at the head; ours at the end, unknown whether order matters), byte 6 = 56 in all 21,316
  quadrants of the BTD and its meshes copy, heights / alphas unchanged; exterior reinstalled.
  **VERIFIED IN GAME (owner, 2026-11-22 20:34): run-time grass grows on the Skyrim terrain.** Starfield's own ground
  cover (the control, GC_MossMoundsGrass01 through NirnOceanNoCoating, masks 2-5) shows near Riverwood: tall bladed
  grass and pink flowers on the slopes and clearings, in patches, ground textures unchanged. So the missing piece was
  quadrant byte 6 (0 in our BTDs): the quadrant's mask material, LDefault004FlatOut here. Together the route is:
  GRAS -> GCVR -> {mask, painted LTEX, GCVR} entries in the biome under the overlay (the planet's own biome, Nirn's
  ocean copy) + byte 6 naming an LDefault mask texture that is in the BTD's table. coc works (no ship landing needed).
  Open: why patches rather than everywhere (the cover's own distribution / density, the 0.44 painted-material
  threshold against Skyrim's blended alphas, slopes); one mask everywhere (FlatOut) instead of per-quadrant masks;
  byte 6 has to become part of the terrain build (now a patch over the installed BTD). Next: Skyrim's own grass
  (skyrim_grass_native.py without --control), then grass materials (VegetationTranslucent1Layer, wind, terrain tint).
  Skyrim's grass build (owner, 21:07: 27 grasses, 19 covers, 76 entries = 19 x masks 2-5): **no grass**, while the
  control grows. So the route works and our records or models do not. Candidates: the templates (the first GRAS by
  EditorID and the one GCVR with a texture list: their water clamps, coverage, threshold carried over, e.g. an
  aquatic grass that only grows under water), the converted models (ordinary static material, not
  VegetationTranslucent1Layer), Skyrim's densities (3-37). Now the templates are the control cover itself and its
  first grass (they grow), and `--keep-template-model` builds our records with that grass's vanilla model to
  separate a model problem from a record problem.
  Rebuilt (owner, 21:26): templates grass GrassHelleboreField02 (the hellebore flowers seen in the control), cover
  GC_MossMoundsGrass01; 27 grasses, 19 covers, 76 entries. In game (21:32): **no grass** either. Remaining
  differences from the control: our covers list their texture (LNAM; the growing vanilla cover has none, like 95 of
  96 vanilla covers: the threshold may then apply on a scale our alphas never reach), our GRAS DNAM (Skyrim density
  3-37, slopes), our models, and only 19 Skyrim grass textures. One at a time: covers without LNAM now (default;
  `--cover-textures` for the old way), then `--keep-template-model`.
  Covers without LNAM (owner, 2026-11-23 08:36): **no grass**. Re-reading the control screenshots (20:34): the moss
  grass grew on the slopes and banks only, never on the flat ground (the green clover / grass-textured flats were
  bare). Supported hypothesis: the engine still classifies each sample by mask from the terrain's shape, flats as Base
  (mask 0), and our entries cover masks 2-5 only (the wiki's advice); Skyrim's grassy textures lie mostly on flats, so
  they get nothing. Test: `--biome-masks all` (or 0,2,3,4,5).
  `--biome-masks all` (owner, 08:38 / 08:41: 133 entries): **no grass**. Masks are not the (only) block. Next:
  `--keep-template-model` (our records, the vanilla hellebore model).
  **`--keep-template-model` (owner, 2026-11-23 08:46, verified in game): grass grows** (the hellebore flowers, in
  Skyrim's grassy places, sparse). So our GRAS / GCVR records, Skyrim's densities and slopes and the biome entries all
  work; **the converted Skyrim models are what the grass system rejects** (built as ordinary static props:
  NiNode + BSXFlags + BSGeometry + MaterialID + BSLightingShaderProperty, standard material). Next:
  `scripts/terrain/grass_model_compare.py` prints a vanilla grass NIF next to ours block by block, with their .mesh
  heads and materials (vanilla source .mat from Data\Scripts\Source\Materials), to build ours like vanilla grass.
  **Owner's run (2026-11-23 09:53, verified):** GrassHelleboreField02, GrassPrimRoseDried01, GrassMossMounds02 are
  laid out exactly like our static props: NiNode "<Name>" (flags 0xE, extra BSXFlags) + BSXFlags 0 + one BSGeometry
  "<Name>:0" (flags 0xE, one LOD mesh, mesh flags 0x40) + NiIntegerExtraData MaterialID + BSLightingShaderProperty
  naming the .mat (e.g. Materials\Landscape\Grass\Flowers\GrassFlowersHellebore01.mat; MossMounds uses the ground
  material Materials\Landscape\Ground\Moss\MossForest01.mat). .mesh heads [2, indices, 65536, 2 / 65538 / 196610].
  So the NIF layout is not the difference. Left: the path (vanilla models all under meshes\Landscape\Grass; ours were
  meshes\s2s\grassnative: now landscape\grass\s2s\), the material, the .mesh contents, the shape count. Our
  models were not in the folder for that run (the --keep-template-model build): rebuild, compare again.
  **Second comparison (owner, 2026-11-23 09:58; models under landscape\grass\s2s: still no grass in game):** our
  BeachGrassObj01 / 02 NIFs match vanilla block for block. Differences left: (1) material: ours is a .mat of our own
  (parent PlasticPlainSmooth01, alpha test 0.353, path materials\s2s\landscape\grass\...), vanilla grass uses
  materials in the game's compiled database (VegetationTranslucent1Layer with Alpha / Translucency / Vegetation (wind) /
  TerrainTint components; the moss mounds use plain BaseMaterial, so the shader model alone is not required);
  (2) the .mesh: ours carry vertex colours (64 / 56), none of the three vanilla grass meshes do (uv2 in two of them).
  Supported hypothesis: the grass system takes its material from the compiled database only (by MaterialID), so a
  material that exists only as our .mat file draws nothing. Test: `--vanilla-material
  Materials\Landscape\Grass\Flowers\GrassFlowersHellebore01.mat` puts a vanilla grass material on our geometry.
  `--vanilla-material` (owner, 10:30 / 10:33): **no grass**. The material alone is not the block. Bisection next:
  `--vanilla-geometry` keeps our NIFs, paths, archive and records but points their BSGeometry at the template grass's
  vanilla .mesh (and its bounds). Grass = our .mesh data (vertex colours, no uv2, one meshlet, scale) is rejected;
  none = something outside the mesh (our NIF / archive / path).
  `--vanilla-geometry` + `--vanilla-material` (owner, 10:37 / 10:39): **no grass**. So our NIF drawing the vanilla
  mesh and material grows nothing, while the vanilla NIF does. What differs: the NIF file itself (header: unknown int
  0 vs vanilla 3, sf_data 7a00 vs a 7-byte value such as 8302290b670200; string order) or where it is loaded from (our
  path landscape\grass\s2s\, our S2SGrass - Main.ba2). Next: `--copy-template-nif` writes the vanilla NIF byte for
  byte at our paths in our archive. Grass = our NIF bytes (header); none = path / archive.
  `--copy-template-nif` (owner, 11:10 / 11:19): **no grass**. The vanilla NIF, unchanged, at our path in our archive
  grows nothing; at its own path (in the game's archive) it grows. So the NIF bytes are fine and the file's location
  is the block: our archive (S2SGrass - Main.ba2, packed like our other working mods) or the path
  (landscape\grass\s2s\...). Next: `--loose` (no archive; MO2 serves the files) with the same copy.
  `--copy-template-nif --loose` (owner, 11:28): **no grass**. So neither the archive nor the NIF bytes; what differs
  from the growing build is only the MODL path in our GRAS. Mutagen's Starfield Model (Model.xml): MODL, MODT
  ("TextureFileHashes"), MOLM (material swaps), FLLD, XFLG, MODC, MODF. Our GRAS copies the template's MODT, which
  describes the template's model at its own path. Supported hypothesis: the grass system resolves the model through
  MODT (resource hashes) and a MODT that does not match MODL draws nothing. Test: `--drop-modt` (with
  `--copy-template-nif`); and a dump of the vanilla GRAS (dump_records.py) to decode MODT.
  Dump of GrassHelleboreField02 (owner, 11:45, verified): EDID, OBND, ODTY, BFCB/KSIZ/KWDA (keywords 2BBE80,
  2BBE7F)/BFCE, MODL 'Landscape\Grass\grasshelleborefield02.nif', FLLD 1, DNAM (contrast 60, cluster 0.64, height
  range 0.33, colour 0, wind 1, above-water 0.5, below-water FLT_MAX, max density 40, slopes 0-40, flags 6, coverage
  20, dirtiness 127/127); record flags 0x8000. **No MODT**: that hypothesis is out (--drop-modt changes nothing).
  So our GRAS differs from the growing one only in EDID, MODL and DNAM (DNAM was Skyrim's in the growing
  --keep-template-model build too): the model PATH alone decides. Both our archive and loose files failed, and both
  are served by MO2's virtual file system, while every model that grew sat in the game's own archives. Next test: our
  plugin and archive copied into the real Starfield\Data (as the terrain is installed), the MO2 mod off.
  Real Data folder (owner, 11:49): **no grass**. Not MO2 either. Left: the path string itself. `--path-variants`
  tries three kinds at once, each with a different vanilla NIF so they can be told apart: hellebore flowers at
  Landscape\Grass\S2S_<name>.nif (flat, vanilla case), moss mounds at Landscape\Grass\S2S\<name>.nif (vanilla
  case, subfolder), dried primrose at Landscape\Grass\S2S\GrassPrimRoseDried01.nif (a vanilla file name in our
  subfolder). If none grows, any path outside the vanilla set fails (a precomputed list of grass models?).
  `--path-variants` (owner, 12:09 / 12:20): **none of the three grows**. (The real-Data test at 11:49 did not run:
  the copies were not in Data at 12:09.) So no path of ours works, archive, loose or MO2. Next split: `--model-path
  Landscape\Grass\GrassMossMounds02.nif`, a vanilla model in the game's own archives but not the template's. Moss
  mounds grow = any model in the game's archives works and ours are not seen by the grass loader (e.g. it reads only
  the startup archives); nothing = only the template GRAS's own model works (something ties a GRAS to its model).
  **`--model-path Landscape\Grass\GrassMossMounds02.nif` (owner, 12:30, verified in game): moss mounds grow** on
  the Skyrim terrain (slopes and flats near Riverwood, sparse). So any model inside the game's own archives works,
  and no model of ours is seen by the grass loader (plugin archive, loose, MO2). Supported hypothesis: the grass
  loader reads only the archives listed in Starfield.ini [Archive]. Test: `scripts/tools/archive_ini.py` prints the
  game's list with "S2SGrass - Main.ba2" appended, for StarfieldCustom.ini, with the --copy-template-nif build.
  sResourceArchiveList with S2SGrass - Main.ba2 appended in StarfieldCustom.ini (owner, 12:37): **no grass**. So not
  the archive lists either (assuming the INI took effect). A vanilla file at a vanilla path works, the identical file
  at any of our paths does not: the game seems to ship something per vanilla grass model that ours lack, found by the
  model's path. Starfield.exe names a BSProcGen DensityMapDB and the game has Starfield - DensityMaps.ba2.
  `scripts/tools/ba2_find.py --grep "hellebore|mossmounds"` lists every archived file naming the two grasses that
  grew, to see what else exists per grass model.
  ba2_find (owner, 12:41, verified): the two grasses that grew have only their NIFs (Meshes01) and textures
  (Textures06): **nothing else per grass model**. Starfield - DensityMaps.ba2 (7,761 files) holds terrain mask
  textures per procedural terrain block, one per mask (`<block>_base / _flatinner / _flatouter / _flow / _solid /
  _talus.dds`, textures\terrain\canyons*, overlaysource\*, overlaymasks): the biome masks of generated terrain
  are painted per block, consistent with ground cover being chosen per mask; not related to grass models.
  Next: `--replace-vanilla Landscape\Grass\GrassMossMounds04.nif` writes the hellebore NIF in our archive over
  that vanilla path and names it from every grass. Flowers = the grass loader reads mod files, but only at paths it
  already knows; moss mounds = it reads only the game's own archives.
  **`--replace-vanilla` (owner, 12:46 / 12:48, verified in game): pink flowers grow.** Our archive's file over a
  vanilla grass path is used; the same file at a new path never is. So the grass system reads mod files, but only at
  model paths the game already ships (a lookup against the game's own file index? unresolved why). Workaround
  (`--vanilla-paths`): `unused_grass_paths` lists the grass NIFs the mesh archives ship under
  meshes\landscape\grass\ that no record of the game's own plugins names (GRAS, STAT, MSTT, FLOR, TREE, ACTI,
  MISC, SCOL, PKIN, MOVS, BNDS), and each converted Skyrim grass model goes over one of them: nothing vanilla that
  is placed or grown changes. Our .mesh / .mat files stay at our own paths (to be seen whether those load).
  Owner's question (12:49): these are not placed objects; every plant seen in these tests was grown by Starfield's
  ground cover from our GRAS / GCVR records (the hellebore and moss-mound grasses are flower / moss clumps, sparse at
  Skyrim's densities). Placed (baked) grass is off in these builds.
  `--vanilla-paths` (owner, 12:57): 196 grass NIFs shipped, 184 named by the game's records, **12 free**; so only 12
  of 27 Skyrim grasses got a path (15 "failed"), taken in EditorID order, i.e. probably not Riverwood's: nothing grew,
  inconclusive. Now the free paths go to the grasses covering the most Skyrim ground (grass_coverage: summed LAND
  weight of the textures that grow each grass, Tamriel-wide), and the build prints which grass got which path.
  Owner's run (13:03 / 13:07): ForestGrass01/02, FallForestGrass01, TundraGrass01/03/04, SnowGrass01Forest,
  RockGrass01 (and 4 underwater grasses, now sent last) over the 12 free paths: **nothing grew**. Our NIFs now sit at
  shipped paths, but they still name our .mesh files and .mat at new paths. Next split: `--vanilla-paths
  --vanilla-geometry --vanilla-material ...GrassFlowersHellebore01.mat` (our NIFs at shipped paths drawing the vanilla
  mesh and material). Flowers = the .mesh / .mat paths are refused the same way.
  **Owner (13:12, verified in game): flowers grow** with our NIFs at shipped paths drawing the vanilla mesh and
  material. So our NIF at a shipped path is accepted, and what it names (our .mesh at geometries\<new hash>, our
  .mat) is refused. Next split: `--vanilla-paths --vanilla-material` alone (our .mesh, vanilla material): Skyrim
  shapes with flower textures = the .mesh is fine and the material is refused; nothing = the .mesh is refused.
  `--vanilla-paths --vanilla-material` (owner, 13:18 / 13:24): a sparse pink-flowered plant grows on the forest
  floor (screenshot, dusk), thinner than the hellebore bushes: supported hypothesis that it is our Skyrim mesh with
  the flower material, i.e. **our .mesh files load and our own .mat is what the grass system refuses**. Next, to
  confirm and as the likely route: a Starfield bladed-grass material on the Skyrim meshes
  (Materials\Landscape\Grass\Bladed\GrassCityShort01.mat, the Creation Kit wiki's example; VegetationTranslucent
  with wind and terrain tint).
  **`--vanilla-paths --vanilla-material ...Bladed\GrassCityShort01.mat` (owner, 13:51, verified in game): green
  bladed grass tufts in Skyrim's grass-card shapes grow** on Riverwood's forest floor (sparse, dusk). So: Skyrim
  meshes load; models must sit at shipped grass paths (12 free); materials must be the game's own (our .mat refused,
  in grass only: statics accept it). Open: Skyrim's textures on grass (a Layered Material Swap is opaque REFL data in
  Mutagen; overriding the textures of a used vanilla grass material would recolour vanilla grass), more than 12
  grass types (shared models), density (Skyrim's 3-37 against vanilla 40+ plus coverage), and why the game refuses
  new paths (Starfield.exe; Ghidra).
  Owner's choice (2026-11-23): a working version now, then dig. For it: grasses past the 12 free paths share the
  converted model of a grass of the same family (TundraGrass02 -> TundraGrass01's), else of the commonest one, so all
  Skyrim grass records grow; `--coverage 100` (GRAS 'Distribution': the templates' 20 % made the grass sparse; Skyrim
  fills every spot its density allows); `grass_model_compare.py --list-materials` lists the materials of every vanilla
  grass model, to pick the closest Starfield material per Skyrim grass family.
  Owner's run (14:00): 12 placed + 15 shared, 0 failed; 82 vanilla grass materials listed (Bladed: GrassFieldLive01,
  GrassFieldDried01/02/03/04 with Cyan / Red / Snow / Yellow variants, GrassCostal01/02, GrassDesert01, GrassWetlands01/02,
  GrassWheat01, GrassSedge01, ...; Aquatic, Flowers, Forest, Rocks, Shrubs, Xophile; MossForest01/03). A material
  lives in the NIF, so it is per converted model: now each free path goes to one grass FAMILY (its commonest grass;
  the rest of the family shares it: 15 families, 12 land families fit), and `--vanilla-material auto` gives each
  family's model the closest game material (FAMILY_MATERIALS: forest / field / fern -> GrassFieldLive01, tundra ->
  GrassFieldDried01, Reach -> ...Red, snow / frozen marsh -> ...Snow, fall forest -> ...Yellow, rock -> ...Dried03,
  beach -> GrassCostal01, volcanic -> GrassDesert01, water -> wetlands / seaweed / eelgrass).
  **Owner (2026-11-23 14:17, three screenshots, verified in game): Skyrim grass grows as Starfield ground cover** on
  the rocky slopes and the Riverwood forest floor, in tall bladed clumps that sway and fade like the game's grass. Two
  gaps against Skyrim: (1) every clump is pale straw, also on the green forest floor where Skyrim's grass is green
  (unresolved: GrassFieldLive01 may itself be a pale field grass, or Riverwood's grasses fell into a dried family);
  GrassCityShort01 drew green at the same spot at 13:51. (2) It grows in scattered clumps with bare ground between,
  where Skyrim's is a carpet: Max Density is Skyrim's raw 3-37 against the vanilla template's 40. Next:
  `--family-material FAMILY=MATERIAL` overrides a family's stand-in (the build now prints each family model's
  material after its path), and `--density-scale 3` (Skyrim 3-37 -> 9-111).
  Owner's run (14:28 / 14:30, `--density-scale 3`, forest / field / fern on GrassCityShort01): the clumps on the rocky
  slopes and by the mill are denser but still straw; the forest-floor spot that had one straw tuft now has none
  (verified, screenshots). Unresolved which Skyrim grasses those places grow: the inferred mapping draws 66 Skyrim
  textures with 19 slots, and a slot's ground cover grows every grass of every Skyrim texture drawn with it.
  `grass_at.py --pos X Y` prints, per Skyrim texture at a spot, the grasses Skyrim grows there, the slot our terrain
  uses, and every grass (model, material) that slot's cover grows.
  Owner (14:35 / 14:41): grass_at with the Starfield getpos given as both --pos and --spawn-at listed mostly LDirt02
  and NoGrass textures, while Skyrim's screenshots of the same spot (grass on / off) show a dense grass carpet: the
  position was read after walking away from the coc spot, so the tool looked at the spawn (unresolved until re-run).
  grass_at now takes `--skyrim-pos X Y` (Skyrim's own getpos at the spot), no frame shift involved. Also seen at the
  Riverwood mill (verified, screenshots): Skyrim's green grass on the riverbank meadow, ours a few straw clumps on
  the dirt edges and none on the meadow.
  Owner (14:45 / 14:46, no grass mod in Skyrim): grass_at at Skyrim's own getpos (17448, -48815) in a dense grass
  carpet: visible top textures LFieldGrass02NoGrass 34 %, LDirt02 29 %, LPineForest02NoGrass 19 %, LFieldGrass02
  11 %, LPineForest01 8 %. **Supported hypothesis: Skyrim grows a texture's grass wherever that texture is painted
  as a layer, even under an opaque layer above it** (modders: "any portion of a cell with even 10% opacity of a
  grassy texture has a chance of having those grasses show up"; "there must be still some texture underneath that
  has grass"), while our terrain and its ground cover only know the visible top texture. landtex.cell_layer_presence
  (raw layer opacity, base = 1 over its quadrant) and grass_at's "Skyrim's grass rule" section measure it at a spot.
  If confirmed, the fix is per-location: grassy duplicates of the slots (same textures, Skyrim's grasses as ground
  cover) painted where Skyrim has a grassy layer underneath.
  **Refuted (owner, 14:51):** a grassy texture is painted under only 13 % of the ground there (visible 11 %). So by
  Skyrim.esm's own records that spot grows little grass, yet the owner's Skyrim shows a carpet. Next suspect
  (unresolved): a plugin loaded after Skyrim.esm (Update.esm, DLC, Unofficial Patch, a landscape / texture mod with a
  plugin) gives those textures grass or repaints the cell. skyrim_ltex_scan.py lists, per plugin in Skyrim's Data,
  its LTEX / GRAS counts, the Riverwood textures it defines or overrides with their grass lists, and LAND overrides
  for given Tamriel cells.
  **Owner's scan (14:54, verified): Update.esm has its own LAND for Riverwood's cell (4, -12)**, plus 27 GRAS and
  15 LTEX overrides (Dawnguard 12 LTEX / 1 GRAS, Dragonborn 11 / 3); the Riverwood textures' grass lists are
  Skyrim.esm's own (no plugin overrides them). The game loads Update.esm over Skyrim.esm; every reader here read
  Skyrim.esm alone, so our terrain and grass follow the pre-Update Riverwood ground. Now landtex.read_world_textures,
  read_ltex_loaded and skyrimgrass.read_grass read Skyrim as loaded (Skyrim.esm, then Update.esm and the DLC found
  next to it; later LAND wins per cell, LTEX / GRAS per FormID; FormIDs in that load order; official=False for the
  old way). refresh_btd recompute learns the mapping and spot-checks against Skyrim.esm alone (the installed
  build's input) and paints from Skyrim as loaded (`--skyrim-esm-only` for the old way); it prints how many cells
  Update / DLC repaint. btd_byte6 set / restore now work on the current terrain files (rebuilding from its first
  backup would have undone a refresh). Open: heights (skyrimland) and placed objects still come from Skyrim.esm.
  Owner's refresh (15:06 - 15:14, verified): grass_at at the forest spot with Update.esm: LFieldGrass02 35 % (was
  11 %), FieldGrass01 density 64 (was 32), FieldGrass02 20 (was 3). terrain_blend: Update / DLC repaint 1821 Tamriel
  cells, spot check 100 %; byte 6 set; grass rebuilt (density x 1.5). In game (15:32, screenshots next to Skyrim):
  straw clumps along rock and cliff edges and the mill's dirt edges, none on the open forest floor or the mill meadow
  where Skyrim grows green field grass. Skyrim's brown rock-ground tufts roughly match our straw. Supported hypothesis:
  the field / forest / fern grasses (GrassCityShort01, earlier GrassFieldLive01) never show, in any build so far (the
  13:51 green tufts may have been tundra grass, which LFieldGrass01 grows); the rock / tundra ones do. Test:
  `--model-from fieldgrass,forestgrass,ferngrass=SnowGrass01Forest` puts those families on a model that shows (snowy
  white): white grass on the meadow = their own converted models are the problem, nothing = their ground cover does
  not grow. The build now prints each converted model's shapes, triangles and height.
  Owner (16:54, one screenshot of the forest spot, build log not sent): the open forest floor still bare, straw on
  the edges only, no white grass. If that build ran, the field / forest ground cover does not grow there, while the
  rock-edge covers do. Supported hypotheses: the painted-material threshold (the template cover's, applied to our
  3-bit alphas: Skyrim blends LFieldGrass02 with its look-alike NoGrass twin and dirt, so its alpha rarely passes it),
  or ground cover not growing on a quadrant's base layer (the open floor is the base; rock edges are overlays).
  ground_at.py now takes `--skyrim-pos` too, to read the quadrant bytes and alphas at the spot.
  **ground_at at Skyrim (17448, -48815) (owner, 16:59, verified):** Skyrim paints LFieldGrass02 100 %; the BTD
  draws slot 00030137 (SKYG LFieldGrass02) as overlay 1 at alpha 7/7, and the 31 m maps match Skyrim's layout. So
  the mapping, the five-layer limit and the threshold are not it (refuted at that spot): the field cover's own slot
  is drawn at full strength there and grows nothing. Slot 00030137 re-skins the vanilla ROCK texture LRockLayered05,
  keeping its fields. Supported hypothesis: ground cover follows the vanilla record's kind. grass_slots.py lists every
  covered slot with the record it re-skins and that record's fields.
  **grass_slots.py (owner, 17:02, verified):** the re-skinned records differ in MNAM (material type: one value, shown
  as "7A/", on every rock record; 0x0001C151 on dirt / gravel; others on grass, sand, snow) and QNAM (f32: 1.0 on the
  rock records, 0 on dirt / grass / sand / snow, 0.2-0.7 on gravel road, loose rocks, volcanic). The slots whose grass
  never showed (LFieldGrass02 -> LRockLayered05, LPineForest03 ferns -> LVolcanicWrinkled01, every RockGrass slot)
  re-skin rock records; the tundra slots (LTundra01 -> LDirtPackedGravel01, LFieldGrass01 -> LGrassLiveSparse01_Red)
  re-skin dirt / grass records, and the straw seen is most likely tundra grass. Supported hypothesis: ground cover
  follows the re-skinned record's kind (MNAM and / or QNAM). Test: `--ltex-kind-from LDirtCracked02` overrides each
  covered slot in S2SGrass.esm with the terrain plugin's re-skin (look kept) and the dirt record's MNAM / QNAM.
  Owner's run (17:09 build: 17 slots changed; FieldGrass01 / FernGrass01 models 1 shape, 6 tris, 64 units tall;
  in game 17:12): **forest floor still bare**, straw on the mill bank. Ground kind refuted as the (only) cause.
  Next, one variable: `--only-ltex LFieldGrass02 --keep-template-model` puts ground cover on that slot alone with
  the vanilla hellebore model (verified to render, 08:46): flowers on the forest floor = the slot's cover grows and
  our field-grass model is the problem; nothing = that slot's cover does not grow.
  Owner's run (17:26, verified in game; whether the build was the --only-ltex one is unconfirmed, a git merge was
  half done): **pink flowers grow, on slopes, ridges and banks only** (mill bank, hill crest, far slopes, where the
  straw grew); the flat forest floor at (17448, -48815), LFieldGrass02 at alpha 7/7, stays bare. Same pattern as the
  vanilla moss control (2026-11-22). Supported hypothesis: the engine gives the flats a mask our covers do not grow on.
  **Density maps (owner's ba2_find + 12 samples, 17:30, verified):** `Starfield - DensityMaps.ba2` holds, per SOURCE
  block, `textures\terrain\<folder>\<block>_{base,flatinner,flatouter,flow,solid,talus}.dds` (newatlantis\
  newatlantis01 / nanorthlake01; overlaysource\<theme>\<block>; 90 files per theme). 100 px per cell (1400 px for
  14 x 14 cells), legacy BC4, one mip. Decoded: six independent soft 0-255 masks, not a partition (per-pixel sum
  20..975, 2-3 masks above 8 per pixel), mostly near-binary with noisy edges: base = the lake bed, flatinner /
  flatouter = open ground, flow = drainage lines, solid sparse, talus = slopes. The world overlays themselves
  (NewAtlantis.btd, lc172world, akilacity) have no mask set, only `overlaymasks\<world>.dds`: hand-made worlds do not
  get density maps of their own terrain (their per-quadrant byte 6 names LDefault006Base / 005Flow / 004FlatOut).
  Next: `--mask-test` grows one told-apart vanilla grass per biome mask (hellebore flowers, wheat, moss mounds,
  primrose, sage, salt, city grass; the build prints which mask got which) on the --only-ltex slot.
  **Mask test (owner, 17:35-17:44, verified in game):** byte 6 = LDefault004FlatOut -> only mask 2's grass
  (GrassMossMounds01) grew; byte 6 = LDefault006Base -> only mask 0's (GrassHellebore01). So **quadrant byte 6
  selects the biome mask per 50 m quadrant; mask 0 = Base, mask 2 = FlatOuter.** With either mask the grass grew only
  in small spots near banks and edges, never across the flats (the forest floor at alpha 7/7 stays bare), like the
  control with cover on every texture (2026-11-22). So the limit is a per-spot density independent of texture, slot
  and mask. Supported hypothesis: the density maps our BTD lacks (vanilla source blocks ship
  textures\terrain\<folder>\<block>_<mask>.dds). Test: `tools\owner\terrain_density.ps1` writes uniform 255 maps at
  textures\terrain\sky_tamriel_<mask>.dds and textures\terrain\sky_tamriel\sky_tamriel_<mask>.dds (73 x 73 cells,
  7300 px, 26.6 MB each) into the staging and reinstalls; `-Remove` takes them out.
  Owner's run (17:47): the install refused: staged Data 4.25 GiB, over one archive's 4 GiB (the exterior was
  uninstalled by then; `terrain_density.ps1 -Remove` restores it). The maps now go into the grass mod instead:
  `skyrim_grass_native.py --density-maps 255` writes them into S2SGrass - Main.ba2 (General, like vanilla
  DensityMaps.ba2; hair_pack.pack general_textures), compressed (uniform maps shrink to almost nothing).
  **Uniform density maps (owner, 17:51 / 17:53, verified in game): no change.** The flat forest floor stays bare;
  the flowers (mask 0) grow only at the river bank and by the mill logs. So maps at textures\terrain\sky_tamriel_*
  (flat or in a sky_tamriel folder) are not read for our world, or are not the limit (refuted as the fix).
  Pattern over every test (control, Skyrim grass, flowers, mask test, density maps): ground cover grows on raised
  ground (banks, ridges, hill crests, rock edges) and never on the low flats beside the river. Supported hypothesis:
  a height / water clamp: the cell's water plane (381.43 m for the Riverwood cells, one flat level per cell) lies
  close to or above the flats in the engine's view, and the GRAS water clamps (kept from the vanilla template)
  forbid grass there. Check: `player.getpos z` on a bare flat and at a flower spot against 381.43.
* Why native grass is the faithful route: Skyrim stores no grass positions either. It grows GRAS at run time from the
  painted ground textures (density, slope, height / colour range), as Starfield's ground cover does; the baked patches
  imitate that with our own random scatter. They also sat on Skyrim's layers while, until 2026-11-22, the terrain drew
  other textures in places (index rule, edge byte blending), which made them look misplaced.

## Model-space normal maps (2026-10-16)
Riverwood's riverbank ledges and cliffs drew dark and flat with only the grass texture's flowers showing, while the
same texture on the flat terrain looked right. Skyrim landscape objects often set SLSF1 Model_Space_Normals (bit 12,
`_msn` maps: object-space normals); Starfield reads every normal map as tangent space. The converter now drops such
maps and lights those shapes from their vertex normals (flat normal map). **Correction:** `inspect_nif.py` showed
the Riverwood ledges (landscape\dirtcliffs\*) do NOT set that flag, so it was not their cause (the handling stays
for models that do). The real cause: the colour textures were written as BC1, whose 1-bit alpha makes texconv encode
every texel under alpha 0.5 as transparent black, and Skyrim's diffuse alpha is a specular mask. FieldGrass02 on the
ledge tops kept only its bright flowers. The converter now writes opaque colour (alpha 255) before BC1; cutouts keep
their separate opacity map.
Grass density follow-up (owner's stats, Riverwood 5 x 5 cells at 0.75 m): 152,100 candidates, 85 % on textures without
grass, 2,354 kept. Skyrim's own GRAS densities there are 3-37 %, and Skyrim tries every grass of a texture at every
grid point (iMinGrassSize 20 units). Now: default `--grass-spacing 0.3` (20 units), every grass in the texture's list
gets its own density roll, and the GRAS water rule is honoured (0 above / 1 above at most / 2 below / 3 below at most /
4 either / 5 either at most; cells without water only pass the above-water rules, so kelp stays in rivers).

## Distant-object LOD: survey of vanilla Starfield (2026-10-16, owner's survey_lod.py run)
**Verified from the owner's archives:**
* `lodsettings\<world>.lod`, 20 bytes = 5 x int32: (-35, -59, 136, 0, 0) for NewAtlantis, (-6, -6, 16, 0, 0) for
  CydoniaCity, (-4, -3, 8, 0, 0) for DR010World: south-west cell x, y, cells per side, then two zeros (FO4's had
  lowest / highest LOD level there). 1,903 of them.
* Per-object LOD models mirror the full model's path: `meshes\lod\generated\<model path>_lod_<0..3>.nif`, e.g.
  `...\streetclutter\nabenchaangle45a01_lod_0.nif` (NiNode + BSGeometry + BSLightingShaderProperty, .mat paths).
  STAT major flag HasDistantLod 0x8000 (Mutagen) is the switch candidate; Starfield STAT has no FO4-style MNAM list.
* Per-world generated output: `meshes\lod\generated\composite\<world>\<object>_<x>_<y>_lod_<L>_cell0.nif`, one file per
  source object per block and level; block coordinates step 1 / 2 / 4 / 8 at levels 0..3 (NewAtlantis 1,324 files,
  CydoniaCity 1,060), plus `textures\lod\generated\composite\` textures. No .bto / .btr files.
Second survey (composite samples + NewAtlantis cell list), **verified**:
* A composite NIF holds ONE BSGeometry with identity transform whose geometry is already in world coordinates (metres):
  NA_LOD_ApolloTower's sphere centre (218, 254, 260) m sits in cell (2, 2) and appears in lod0 blocks (2, 2) and (1, 2).
* Block size is 2^L cells (L = LOD level 0..3: 1, 2, 4, 8 cells = 100..800 m), blocks aligned to the lodsettings origin
  (NewAtlantis origin (-35, -59): lod1 blocks odd, lod2 at 1 mod 4, lod3 at -3 mod 8; all match). The file name gives the
  block's south-west cell.
* Each composite has its own material `Materials\LOD\Generated\Composite\<World>\<name>.mat` and baked textures
  `textures\lod\generated\composite\<world>\<name>_{color,normal,rough,metal,emissive,opacity}.dds`.
* The name prefix is the source object's EditorID (NA_LOD_ApolloTower: a LOD-only STAT), one file per object per block.
* NewAtlantis cells span x -8..18, y -14..8 (city core -7..6); lodsettings (-35, -59, 136) covers a larger square.
**Unresolved:** how the engine finds the composite files (folder scan by world vs an index), and whether HasDistantLod +
per-object `_lod_N` models alone draw distant objects without composites.
**First LOD generator** (`make_skyrim_objects.py lod`, after stage; src/fo4sf/skyrimlod.py): lodsettings
(cell_min, cell_min, size rounded to 8, 0, 0); every reference of a static with radius x scale >= `--lod-min-radius`
(default 20 m; trees skipped) merged per object and cell into level-0 meshes in world coordinates using the full
converted model and its own materials; level-L NIFs list the level-0 meshes of their 2^L block (no geometry stored
twice); those bases get STAT flag HasDistantLod (0x8000). Not yet seen in game.
First in-game LOD test (2026-10-16, Throat of the World view): our composites do NOT draw. Gagarin (a vanilla planet
overlay world) compared: lodsettings (-3, -14, 32, 0, 0), composite blocks in the world's own cells with the same
2^L alignment as ours, one BSGeometry per file, BSXFlags 1 (ours 0), material
`Materials\\LOD\\Generated\\Composite\\<world>\\<name>.mat` per file. The name prefix (Gagarin_LOD_Grp012,
NA_LOD_ApolloTower) is not a STAT EditorID (SfInspect found no Static NA_LOD_Apollo). How the engine knows which
composite names exist is the open question.
**Found (owner's find_in_plugin.py run):** the composite name prefixes are LAYR (layer) records: Gagarin_LOD,
Gagarin_LOD_Grp01 .. Grp016, Gagarin_LOD_Crane01, NA_LOD_ApolloTower. Mutagen Starfield Layer: PNAM parent, XCLP
colour, LODB LodBehavior {Default, Aggregate, NoLods}; references join a layer through XLYR. So composite LOD is made
per layer and block. The generator now writes one LAYR `<base>_LOD` per LOD base (LodBehavior Aggregate by default,
objects.json "lod_behavior" to change), links those references to it (XLYR) and names the composites after it.
**Supported hypothesis**: the engine loads composites by the layers its references use.
Second LOD test (layers, Aggregate): still not drawn. Vanilla layer Gagarin_LOD_Grp012: LodBehavior Aggregate, Parent
Gagarin_LOD 0799F1. WRLD comparison (owner's dumps): SettleGagarinWorld and NewAtlantis (composite LOD) have HNAM [5],
the Mars template LC172World (no composites) HNAM [0]; Gagarin also has Water 000018. TerrainOverlays now puts the
LOD layers under a parent `<world>_LOD` and sets the world's HNAM to [5] when it writes LOD layers.
Vanilla LOD layer contents (owner's `SfInspect layers SettleGagarinWorld Gagarin_LOD`): ordinary placed statics of
ordinary bases (MacKitSmBase68, IndExtSupBeamLg01, ...; ref flags 0, base flags 0 / 0x200, no HasDistantLod), so our
layer setup matches vanilla. Third test (HNAM 5 + parent layer): still not drawn. Remaining differences: our
composites carry several BSGeometry shapes and the full models' materials (vanilla: one shape, baked composite
material and textures), BSXFlags (now 1 as vanilla), and the surface block record (to compare).
**Decisive test (2026-10-16): `lod --vanilla-test`** replaced all 6,612 of our composites with vanilla Gagarin crane
composites (vanilla mesh and baked material) moved over our objects: still nothing drawn from the Throat of the World.
So the engine does not load composite LOD for this overlay world at all; our file contents are not the (only) cause.
Matched so far without effect: lodsettings, composite names / folder / 2^L blocks, LAYR Aggregate layers with a
parent, XLYR on the references, world HNAM 5, BSXFlags 1, STAT HasDistantLod. **Unresolved, parked.** Untested ideas:
something in a vanilla world's records we cannot see in Mutagen's view (unknown subrecords), a cache built only by
the Creation Kit, or the engine skipping composite LOD for worlds added by plugins.
**Correction (same day): the decisive test was not decisive.** Vanilla composites have an identity root node and keep
world coordinates in their vertices; the first `--vanilla-test` moved the cranes with the root node's translation,
which the engine may ignore for LOD (then all 6,612 cranes stood at Gagarin's (125, 110) m in our world, out of the
Throat of the World view). `--vanilla-test` now bakes the offset into a copy of the vanilla mesh (vanilla material kept)
and writes identity-root NIFs like vanilla's. LOD is un-parked until that test runs. Composite node names now use the
lowercase world folder, as vanilla's do.
**Found (2026-10-17): our lodsettings file was never installed.** The owner's archive survey lists 6,612 composites in
`SkyrimTerrainTamriel - Main.ba2` but no `lodsettings\sky_tamriel.lod`: deploy_skyrim_exterior.py packed only Terrain,
meshes, geometries, materials and textures. Every vanilla LOD world ships its .lod (ShatteredSpace - Main01.ba2, a
plugin's own archive, holds 66, e.g. sfbgs001dazraworld.lod, next to 2,519 Dazra composites: plugin worlds do get
composite LOD). So all four in-game LOD tests ran without LOD settings and none of them tells us anything about our
files. The installer now packs `lodsettings`; the lod run's file list moved to `Data\<world>.lodfiles.json` (not packed).
Fifth test (2026-10-17, with lodsettings installed): our own composites, then the vertex-moved crane test: nothing
drawn either time. Next: `scripts/tools/compare_worlds.py` compares the WRLD records raw (every subrecord, record and
plugin header flags, child groups) of SettleGagarinWorld, NewAtlantis, ShatteredSpace's SFBGS001DazraWorld (a plugin
world with composite LOD), LC172World and SKY_Tamriel.
**WRLD comparison (owner's compare_worlds.py, 2026-10-17):** fields both LOD worlds (NewAtlantis, SFBGS001DazraWorld)
have and ours lacks: RNAM (large references; LC172World has none either), OFST / CLSZ (the Creation Kit's cell offset
tables; LC172World has them), XCLW / WHGT (water lists, deliberately off). HNAM is 0 in Dazra, so HNAM is not the LOD
switch. RNAM (Mutagen WorldspaceGridReference: grid cell, then [reference, its own cell]) lists, per cell, large
references of that cell and its neighbours. Sixth test: the lod step now lists every LOD reference as a large
reference in each 100 m cell its bounding circle covers (`--no-large-refs` to skip); TerrainOverlays writes them to
Worldspace.LargeReferences. Unverified. OFST / CLSZ are not written (Mutagen does not build them).
Sixth test result: large references (RNAM) changed nothing visible. **Overlay component (owner's SfInspect /
compare_worlds runs):** the WRLD's WorldSpaceOverlayComponent SNAM is a placed reference in every LOD world
(NewAtlantis 011720, base 25586D, layer 01CCB9; Dazra 01D1BA, base 29AE97; LC030World 012CDE) and 0 in LC172World and
ours; its PNAM has bit 0 set in every LOD world (3, 0x15, 1) and is 4 in LC172World and ours. Seventh test: with LOD
layers, TerrainOverlays sets SNAM = our persistent anchor (XMarker) and PNAM |= 1. Meaning of both unresolved.
Seventh test result (SNAM / PNAM): nothing drawn. The SNAM references are ordinary statics (NewAtlantis: base
SciIntSegSmRailMid03; Dazra: MacKitMedWheel04, which has a LodOwnerComponent, REFL "BETH" ...). Next test,
`scripts/tools/lod_override_test.py`: our archive overrides New Atlantis's own Apollo tower composites with cranes at
the vanilla paths. Cranes over the tower from afar = composite LOD is read from a plugin's archive and our NIF layout
draws (so the Skyrim world's setup is the problem); none = it is not read from our archive.
Override test 1 (Apollo tower only): New Atlantis looked unchanged from outside the city, but NA_LOD_ApolloTower is
not the obvious spire (the MAST is na_lod_themast), so inconclusive. The tool now replaces every New Atlantis
composite by default.
**Verified (override test 2, 2026-10-17): composite LOD is read from a plugin's archive and our NIF layout draws.**
With all 662 New Atlantis composites overridden from `SkyrimTerrainTamriel - Main.ba2` by vertex-moved cranes
(identity-root NIF from sfnif.build_static_nif, our .mesh, vanilla material), New Atlantis's distant skyline was cranes
(owner's screenshot). So the Skyrim world's missing LOD is in how the world or its layers are set up, not in the files
or the archive. Next test, `lod --lod-layer NA_LOD_TheMast --vanilla-test`: every Skyrim LOD reference joins that
vanilla LAYR (TerrainOverlays uses a Starfield.esm LAYR of that EditorID as is), composites named after it, one file per
block: cranes over Skyrim = our own LAYR records are the problem; none = the world is.
Layer test result: Skyrim LOD references in the vanilla LAYR NA_LOD_TheMast (22A26A), composites named after it, cranes:
still nothing over Skyrim. So neither the files, the archive nor our LAYR records are the problem: the Skyrim
worldspace itself is not given composite LOD. Next: `scripts/tools/compare_cells.py` (cell records and cell children,
NewAtlantis / Dazra / LC030World against LC172World and ours).
**Cell comparison (owner's compare_cells.py):** no per-cell field only the LOD worlds have (their 5-10 % BFCB/REFL
reflection-probe components aside); vanilla cells have DATA, LTMP and XILS where ours have none, but so does
LC172World. (Cell record flag 0x40000 is just "compressed".) Remaining WRLD difference: OFST / CLSZ, the cell index.
LC172World has it too, but it has no LOD files, so it was never a counterexample. `scripts/tools/world_offsets.py`
verifies the index layout on a vanilla world (LC030World) and writes it into our plugin after TerrainOverlays.
Cell index test (2026-10-17): OFST / CLSZ verified on LC030World (90/90, offsets relative to the WRLD record, x fastest,
CLSZ = record size with header) and written for SKY_Tamriel (74 x 74): still no cranes. **Eliminated so far:** file
contents, archive, names, lodsettings presence, our LAYR records (vanilla layer test), HNAM, RNAM, overlay SNAM / PNAM,
OFST / CLSZ, STAT HasDistantLod, BSXFlags. Untested: anything the Creation Kit computes on save that we cannot see,
how the player arrives (coc vs landing), the BTD / SFBK, the planet registration. Next step proposed: open and resave
the plugin in the owner's Creation Kit (or its LOD generation, if offered) and diff what it writes.
**Creation Kit (owner, 2026-10-17):** loading the plugin gives "CELLS: Error adding cell (01000805) to world space
(01000803). Cell will be destroyed." for our south-west cells (OK crashes the CK). GRUP block / sub-block labels are
not the cause: ours follow the vanilla rule ((y, x), floor division by 32 / 8) for 5,329 / 5,329 cells (compare_cells).
Found instead: our exterior cells had no DATA at all (Mutagen's nullable Flags stayed null; `Flags |= HasWater` on
null is null, so even the water cells' HasWater was never written), and no XILS; every vanilla exterior cell has DATA
0x2 (HasWater), XCLW (float max = no water) and XILS 1.0. TerrainOverlays now writes all three on every cell, and
make_skyrim_objects.py adds the cell index (world_offsets.py) after every plugin build.
**CK warnings export (owner, after the DATA fix):** only cell 01001222 ((-1, -1)) is still refused. 19,494 x "Reference
(...) to STAT 'SKY_...' is not a large ref" = every RNAM entry: our STATs had no OBND (object bounds), so to the CK
every object is zero-sized. 104 x "Reference (01000800) attached to wrong cell for its location: 'Surface' (2147483647,
2147483647)" (our anchor in the persistent cell). The lod step now stores each static's mesh bounds (metres) in
objects.json and TerrainOverlays writes them as OBND.
CK after OBND: "not a large ref" down from 19,494 to 149 (SKY_fcHawkNoNest, SKY_WinterholdExtTowerRingBase), one
"Invalid large ref data found for world 'SKYTamriel'". The last refused cell: "Cell (01001CD6) Surface already exists at
coord (-1, -1)": the CK put our persistent cell (no XCLC) at (-1, -1), then refused the real (-1, -1) and attached its
100 references to the persistent cell. The persistent cell now gets XCLC (int.MaxValue, int.MaxValue), where the CK
files it anyway and where LC172World's sits. Still no LOD in game after OBND.
XCLC (MAXINT, MAXINT) on the persistent cell did not stop the CK refusing (-1, -1). Vanilla persistent cells are empty
records (compare_cells: no fields at all); ours had DATA HasWater since experiment 1. It is now empty too.
Empty persistent cell: the CK then refused (0, 0) instead (0100126C), so it files a persistent cell it does not
recognise at a default grid. Vanilla: one cell per world has record flag 0x400 (Persistent), LC172World's at XCLC
(MAXINT, MAXINT). Ours now has both.
**Full LOD (2026-10-17):** modders report that the CK's LOD layers generate nothing for custom locations and that
the working option is the reference flag "Is Full LOD" (REFR record flag bit 16 = 0x10000, xEdit wbDefinitionsSF1;
owner's r/starfieldmods and Nexus finds; `-MockWorldSpaceLOD` crashed the owner's CK at "Initializing FaceGen" for
our plugin and Starfield.esm alike, and that command was reported for Fallout 4). The lod step now flags every LOD
reference (radius x scale >= --lod-min-radius) Is Full LOD (`--no-full-lod` to skip). Unverified in game.

## Object LOD (works, 2026-10-17)
**Verified in game:** distant objects of a modded worldspace come from the Creation Kit's `-MockWorldSpaceLOD` layout,
not from composite LOD. The owner ran `CreationKit.exe -MockWorldSpaceLOD:SkyrimTerrainTamriel.esm SKY_Tamriel` from
cmd in the Starfield folder (it ran once despite earlier crashes at "Initializing FaceGen"); its 3,316 NIFs + 1 lodsettings,
packed into our archive, showed Whiterun, forests and cliffs from the Throat of the World. Layout (src/fo4sf/objectlod.py):
`lodsettings\SKYTamriel.LOD` (-33, -25, 69, 0, 0) = the cells holding references; `meshes\terrain\SKYTamriel\objects\
SKYTamriel.<L>.<x>.<y>.nif`, L = 1 / 2 / 4 / 8 (2,402 / 672 / 187 / 55 files), every level listing all 218,219 references
(cell = floor(pos / 100 m), blocks aligned to the lodsettings origin). Each NIF (bs 175) is one BSWeakReferenceNode:
NiNode header, then per base (raw FormID, crc(model stem), "nif\0", crc("meshes\" + model folder), count, per instance
3 x (3 f32 rotation, 0), x, y, z, scale, then u32 0), then 10 zero bytes. crc = sfnif.material_id. Our writer
reproduces all 3,316 CK files byte for byte from their parsed entries, and the hashes for 17,156 of our entries. The CK
names the world without underscores (SKYTamriel); which name the game reads is not yet known, so both are written.
The CK also listed two vanilla markers (XMarker, COCMarkerHeading); ours leaves Starfield.esm bases out.
`make_skyrim_objects.py lod` now writes object LOD after the plugin build (needs formids.json); composite LOD is opt-in
(`--composite-lod`), Is Full LOD opt-in (`--full-lod`). `--ck-lod-reference <CK Objects folder>` compares ours with the
CK's and picks the rotation convention.
Rotation: matched by position, the CK's instance rotations agreed with exterior.ref_matrix (R) for 465 and with its
transpose for 3,544 of 10,220 instances (owner's run), and the transposed build showed tilted rocks turned wrongly
(owner's screenshots): the CK combines the angles in another order. compare() now tries 24 conventions (axis order x
sign x transpose) and the lod step uses the best (`--lod-rotation`, default zyx- = ref_matrix).
**Rotation verified (owner, 2026-10-17):** convention zyx+ (Rz(z) Ry(y) Rx(x), positive angles; = xyz--T) matched
10,140 of 10,220 CK instances; with it the mountain LOD looked right in game. Now the default. Moving the world to an
ocean spot of Jemison (lat -0.15) placed it ~200 m lower (Riverwood at the planet's sea level, -16 m, flooded): the
overlay's height follows the planet's surface there (the sea floor). Back at -0.6, 2.281: dry again.

**Object LOD size filter (2026-10-17):** with every one of the 218,217 references in all four levels (what the CK's
mock LOD wrote), the owner's game used 30.8 of 31.9 GB RAM and stuttered / froze on the way to the coast (supported
hypothesis that object LOD is the cause: LOD draws each base's full converted model). `lod` now keeps a reference in
level 1 / 2 / 4 / 8 only when its base's largest extent x scale reaches `--object-lod-sizes` (default 8,12,24,48 m;
`0` = all) and leaves trees and plants out (`--object-lod-plants` keeps them); it prints the count per level.

**Distant sea (2026-10-17, src/fo4sf/skyrimsea.py):** cell water draws only in the loaded cells (owner: past them
the sea floor showed dry, icebergs standing on it). The planet's own ocean does draw to the horizon (owner, ocean spot
lat -0.15, offset 390: right level, no Starfield land in view) but there the engine walls the player in ("You cannot
go that way" in Riverwood) and the river water vanished. So at the land spot the `lod` step now adds flat sea pieces
at the overlay's `sea_level_m` (written by make_skyrim_overlay.py build; 0.3 m below the cell water): 10 x 10 tiles
over the map, strips and corners reaching `--sea-reach` (60 km; 20 km left Jemison land on the horizon) past it, one-sided facing up, our own material
(dark sea colour, tiling wave normals, low roughness; needs `--content-resources` / `--texconv`); they are big statics,
so object LOD draws them at every distance. `--no-distant-sea` removes them, `--sea-double-sided` if they turn out
invisible. Supported hypothesis: how water-like a flat mesh looks from afar; not yet seen in game.
First view (owner, 2026-10-17): the sea reaches the horizon round the icebergs; it read paler / milkier than the cell
water (a visible line where they meet), its 16 m wave repeat showed as a grid, and Jemison land stood past 20 km.
Now darker (12, 34, 46), roughness 60, a 48 m multi-scale wave repeat, 60 km reach; `--sea-colour R,G,B` and
`--sea-roughness` tune it without code.

**Glossy LOD (2026-10-17, src/fo4sf/lodmatfix.py):** owner's views: distant rocks, icebergs and mountains (object LOD)
look glossy and mottled, like wet metal, while the same objects up close look right. Every converted material is a
clone of the cast-iron template made non-metal by a constant metalness replacement (slot 4); supported hypothesis: the
distant renderer ignores that replacement and draws the template's metal. `lod` now gives every material under
materials\skyrim an explicit black metalness texture in slot 4 instead (needs `--texconv`; `--no-metal-fix` skips).
Not yet seen in game.

**Ocean spot works (owner, 2026-10-17):** Jemison lat -0.15, lon 2.281, `--height-offset 390 --no-skyrim-water-sea`,
`bBorderRegionsEnabled=0` under [General] in StarfieldCustom.ini: no walls, the planet's sea round Skyrim to the
horizon, no Starfield land in view. Still open there: no river water (our cell water did not draw) and the glossy LOD.
`lod --river-meshes` draws each river / lake cell as a flat water static at its level (skyrimsea.add_rivers; also in
object LOD). Not yet seen in game.
**Metal fix refuted (owner, 2026-10-17):** with the black metalness texture in all 1,141 materials (ground materials
included) the near rocks and the ground turned shiny / gold-metallic too, so it is now opt-in (`--metal-fix`,
experiment) and a stage re-run relinks the converted materials. The glossy distant objects at the ocean spot are
unexplained again (owner's hypothesis: Starfield's wet-surface effect there). River pieces drew (Riverwood's river
present) but bright opaque cyan: own material now, darker and rougher (`--river-colour`, `--river-roughness`).
**Coating at the ocean spot (owner, 2026-10-17):** every converted object there, near and far, wears an olive,
glossy, "underwater / mossy" coating; at the land spot the same mountains were grey rock. Our object materials
(sample gray_86d7593e.mat) hold only their three textures and a few replacements and inherit the rest from vanilla
PlasticPlainSmooth01 (Import + Parent); no global-layer component of their own. `lod --standalone-materials`
(experiment) rebuilds the plain opaque ones with convert_material.build_mat_standalone (generic Root parents only);
re-running stage undoes it.
Standalone materials changed nothing (owner): the coating is an effect the engine draws on top (owner: "the textures
themselves get an underwater-like feature"). compare_worlds NeonCity (a city over Volii's ocean) / NewAtlantis /
ours: both vanilla worlds have ZNAM (music), WAMB (ambient set), XEMP (environment map: Cell_CaveCube /
Cell_TestVideoCube); NewAtlantis also XWEM (water environment map) and world water lists XCLW / WHGT (heights 242 m);
ours none of them. DNAM default water: Neon 236, NewAtlantis 41, ours -200 m. `lod --world-env-from NewAtlantis` copies
ZNAM / WAMB / XEMP / XWEM into our world (then the cell index is rewritten). Supported hypothesis: the missing
environment map is the coating.

## Animated objects: the mill water wheel (2026-11-18)
Owner, in game: Riverwood's mill water wheel stands still (it should spin) and its axle renders plain white. Skyrim's
wheel (SKY_Lumbermill01WaterWheel01 / 02 in our plugin: architecture\farmhouse\lumbermill01waterwheel01.nif, 02.nif;
Solitude's ssawwaterwheel.nif the same kind) spins by keyframes in its NIF. Starfield NIFs hold no controllers; a
record attaches a graph (.agx), a .rig and an animations folder (WP-doors-research.md), and since the chicken we write
.rig / .af ourselves (CALUMI). Plan: a vanilla Starfield object that loops one clip as the template (graph + record
form), the wheel's rotating node as a one-bone rig, its Skyrim keyframes as a looping .af. Read-only first:
scripts/interior/sf_animated_object_probe.py lists Starfield's records with a graph and a rig, looping-sounding ones
first, with their folders' clips; the Skyrim wheel NIFs (creature_probe --extract-skyrim) give the spin axis, speed,
pivot and the axle's material.
Read the owner's Skyrim wheel NIFs (2026-11-18, not in Git), verified: lumbermill01waterwheel01.nif = BSFadeNode >
SawWaterWheel03 (NiNode at (459, 0, -160) units, rotated 90 deg about z: the wheel + spokes, SawWaterWheel03:5 / :19),
L1_SawWaterWheelHub (the fixed hub, a 16 x 406 x 16 cylinder), two particle systems (water off the wheel) with their
emitter meshes WheelEmitGeo01:0 / WheelEmitGeoOld01:0, and Ragdoll_Object02:0 (a cylinder along the axle); the emitter
meshes and the cylinder carry the NiAVObject hidden flag (0xF). NiControllerSequence "Idle" (cycle 0 = loop, 0 -
16.667 s) turns SawWaterWheel03 about its own Y (XYZ euler keys: x 0, z 90 deg fixed, y 0 -> -2 pi; wheel 02 +2 pi):
one turn per 16.7 s about the axle (the wheel is thin along its local Y).
The white axle: the converter drew hidden-flagged shapes. skyrimnif.hidden_blocks (flag bit 0 on a shape or on a node
above it) now leaves them out like EditorMarker geometry (reason "hidden" in the conversion report); on the wheels it
drops exactly the two emitter meshes and the axle cylinder. Needs the objects reconverted.
Starfield (owner's sf_animated_object_probe, verified): 3169 records with a graph and a rig. Constant spinners use
SimpleIdleLoop01.agx (31 records): Akila's yard fan blades (AK_Fan_Yard_02 / 03_Blade, STAT), the desk fan (MISC),
the Stroud miniatures (STAT) all on genericbehaviors\genericrig\characterassets\skeleton.rig with
genericbehaviors\idlebehaviors\rotate_y01\animations (a generic turn about Y); FloatSpinHelperFree01 (ACTI) has its own.
GenericIdleLoop.agx drives wind turbines / harvesters (On / Off / Idle states). Plan (unverified): the wheel's spinning
part (SawWaterWheel03) as a model of its own centred on the axle, axle along Y, on a STAT with SimpleIdleLoop01 + the
generic rig + rotate_y01 (a vanilla folder: no animation index run); the frame and hub stay static. Open: how a fan
blade NIF binds to the generic rig (node names), rotate_y01's speed and direction (probe --match Fan_Yard_03
--calumi --extract-to).
Built (2026-11-18, synthetic tests in tests/test_spin_parts.py and a local run on the owner's wheel 01; in game
unverified):
- skyrimnif.spin_part finds the turning node: a looping NiControllerSequence whose NiTransformData has XYZ euler keys
  with exactly one axis turning a full 2 pi, the others constant, nothing tilted inside it. On the wheels:
  SawWaterWheel03 / 02, the node's own Y, 16.667 s. Checked against the shapes: the wheel disc is thin along world X,
  which is the node's own Y after its 90 deg about Z (so the keys compose as Rz Ry Rx, the turning angle inside).
- skyrimconvert.convert_nif takes the node's shapes (hidden ones already dropped) out of the model and writes them as
  `<model>_spin.nif`, no collision, in the node's frame turned so the axis is +Y (rotate_y01 turns about Y). Where
  Skyrim turns the other way from rotate_y01 the part is written turned 180 deg about Z. rotate_y01's own direction is
  assumed: `VANILLA_SPIN_SIGN = +1`, unverified. The result's "spin" entry gives the model, pivot (metres), frame,
  bounds and period. Wheel 01: pivot (6.56, 0, -2.29) m, radius 3.66 m, written turned (Skyrim's sign -1).
- make_skyrim_objects stage (exterior.place spin=True; `--no-spin` leaves the parts out) adds a base `<edid>_Spin`
  and, with each reference of the model, a reference `<src>#spin` at the pivot, rotated by the frame composed with the
  reference's rotation (exterior.ref_angles inverts ref_matrix).
- TerrainOverlays: a base with "anim_template" is a copy of that Starfield.esm static (12F12F, AK_Fan_Yard_03_Blade:
  the graph component and keyword come along) with our model and bounds.
- In game 2026-11-18 (owner, verified): the wheel part stands in the right place (round, on the axle, edge-on to the
  stream; the white axle gone) but does not turn. Next: is the copied component alive on Nirn (the vanilla fan blade
  placed with placeatme) and how the vanilla blade NIF binds to the generic rig's bone "Root" (its node names, BSX;
  sf_animated_object_probe --extract-to now copies every matched record's model).
  Found (verified on the owner's extract, 2026-11-18): AK_Fan_Yard_03_Blade.nif is root "AK_Fan_Yard_03_Blade"
  (BSXFlags 2, its collision) -> NiNode "Rotate_Y01" with NiStringExtraData "sgoKeep", rotated so its local Y is the
  fan's (vertical) axis -> the three blade shapes. The generic rig's only bone is "Root"; the node the clip turns is
  named after the clip folder (rotate_y01), not the bone (supported: the one vanilla example read). Our part model
  had its shapes straight under the root, so nothing turned. Now the part model has the same "Rotate_Y01" (sgoKeep)
  node (skyrimconvert.SPIN_NODE, sfnif.build_static_nif animated_node), identity, since the part is already written
  with its axis on +Y. Verified in game 2026-11-18 (owner): the wheel turns, about 4 times too fast.
- Speed (2026-11-18): vanilla runs one graph at different rates with a Properties entry (PRPS: actor value 001B220E,
  float rate, 0) on ACTI records: FloatSpinHelperFree01 (none = 1), _Slow 0.25, _Slower 0.15, _Slowest 0.1,
  _Slowest02/03 0.05 (verified, owner's dump; same graph / rig / animations folder otherwise). The parts now go on a copy
  of ACTI _AnimGraph_Standard_Idle_Loop_RotateY (304C45: SimpleIdleLoop01 + genericrig + rotate_y01) carrying _Slow's
  PRPS with rate exterior.spin_speed(period) = 4.2 s / Skyrim's loop (rotate_y01's 4.2 s per turn is the owner's
  estimate; its .af did not decode): 0.252 for the wheel. PluginSpike (SPIN_PARTS) and TerrainOverlays
  (anim_template / anim_speed / anim_speed_from) set it through Mutagen's Activator.Properties by reflection.
  In game 2026-11-18 (owner, verified, fresh coc from the main menu): the ACTI copy turns, but still about 3 s per
  turn: the PRPS rate (written, 0.252, checked with the probe's --plugin dump) is not applied to this graph / rig.
  Found (owner's dumps, verified): no other rotate clip ships (probe --files: only rotate_y01, the oscillate rig and
  the animhelper_30/60/90/120 state sets). The Akila fans set the rate on the STAT itself, with the same PRPS entry:
  AK_FanCeiling01_Blades Speed01-Lazy 0.1, 02-Low 0.25, 03-Mid 0.5, 04-High 0.75; AK_FanWall01_Blade 1.5, _Lazy 0.75,
  _OFF 0; the yard fans and AK_Fan_Yard_03_Blade_Slow carry none (so _Slow's rate lives elsewhere, perhaps on its
  references). So the parts now go on a copy of STAT AK_FanWall01_Blade_Lazy (1A6C70) with that entry set
  (SpinRate in PluginSpike / TerrainOverlays). Rate: rotate_y01 turns in about 3 s at rate 1 (owner, twice; the
  clip is 11.659 s, so 4 turns), exterior.spin_speed = 2.915 s / Skyrim's loop: 0.175 for the wheel.
  In game 2026-11-19 (owner, verified): the rate works (the wheel slowed), still about twice Skyrim's speed; so
  rotate_y01 makes about 8 turns per clip, ROTATE_Y01_TURN_S = 11.659 / 8 and the wheel's rate 0.087. At 0.087 the
  owner counted 12 s per turn (2026-11-19 08:28): ROTATE_Y01_TURN_S = 12 x 0.087 = 1.04 s, the wheel's rate 0.063 for
  Skyrim's 16.7 s. Verified in game 2026-11-19 08:49 (owner): the wheel turns the right way (lower edge downstream,
  so VANILLA_SPIN_SIGN = +1 holds) at Skyrim's speed as far as can be told by counting. If the rate had done nothing: our own rig + looping .af at Skyrim's period (as the dartboard:
  rig bones named after the model's sgoKeep nodes), with a Creation Kit index run.
- Only the exterior / city converter splits the part (SkyrimConverter.split_spin, set by make_skyrim_objects
  convert): interiors, weapons and the first-run converter keep the turning part in the model, standing still, until
  their placement handles "spin" (interior Dwemer gears would otherwise vanish).
- For the installed exterior (no restage: its plugin, FormIDs, LOD stay): scripts/terrain/spin_parts.py lists the
  parts from the staged objects.json and the reconverted manifest and copies their models into FO4Port.esm's staging;
  riverwood_doors.ps1 runs it and PluginSpike (SPIN_PARTS) adds the static copies and persistent references in the
  world's persistent cell, as the outdoor furniture (`-NoSpin` leaves them out). The exterior's own wheel model loses
  its wheel when exterior_collision.ps1 refreshes the models. An exterior restaged with the parts gets none from here.
Unknown until in game: whether the copied component turns a model whose root node is not a rig bone (the generic rig's
one bone is "Root"; Starfield's AnimTemplate01.nif has no node of that name either, so the rig is taken to drive the
model root), the direction (flip VANILLA_SPIN_SIGN if it turns backwards), and the speed (rotate_y01's 11.66 s per turn
against Skyrim's 16.7 s: about 1.4 times fast; a slower clip would need our own .af in a new folder).
