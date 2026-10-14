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
| `src/fo4sf/skyrimconvert.py` | `SkyrimConverter(pipeline.Converter)`: FO4's texture conversion, caps and material templates reused; Skyrim materials (diffuse + normal; alpha test -> cutout, alpha blend -> decal, effect shaders skipped); collision as boxes (below) |
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

`--max-texture 1024` keeps one archive under 4 GiB for large regions (core64c needed caps for the Commonwealth);
`check` fails when the staged Data tree would not fit one stored archive. Install exactly as the terrain
(skyrim-tamriel.md): Archive2 over `Terrain,meshes,geometries,materials,textures`, both plugins, `coc` the arrival.

## What `check` verifies, and what to read first on real data
Every base model, every geometry / material file the models name and every converted texture the materials name
exists; every reference lies inside the BTD's cells; the archive fits; and the **frame check**: each object's origin
height minus the terrain height under it. Skyrim's rocks and trees sit on the ground, so on real data the median must
be near 0 (synthetic: 0.00 m, 6 of 6 within 3 m). A large constant offset means the object and terrain frames disagree.

On the first real run also read `convert/manifest.json`: `failure_reasons` (counts), `collision` (columns / surfaces /
none per model), material fallbacks, and any model with `"collision_overlaps_render": false` or `"unsupported"`
collision shapes (layouts read from niftools' nif.xml, checked on synthetic files only).
