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
