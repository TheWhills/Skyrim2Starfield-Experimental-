# Skyrim's exterior objects on the Tamriel overlay

Branch `skyrim/objects`, on top of [skyrim-tamriel.md](skyrim-tamriel.md) (the terrain). Status: **built and tested
offline on synthetic Skyrim data only (16 tests + the full export -> stage -> check path); not run on the real
Skyrim.esm / BSAs, not deployed, not run in game.** Labels: **verified** = measured here; **supported** = supported
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
