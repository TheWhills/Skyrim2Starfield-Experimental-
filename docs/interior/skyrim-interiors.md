# Skyrim interiors (houses, inns, caves, barrows, ruins)

Branch `skyrim/armor` (on top of the exterior work). Status: **export and checks offline on synthetic data; not run on
the real Skyrim.esm, not built into a plugin, not in game.**

## Path (one cell at a time)
1. `scripts/interior/make_skyrim_interior.py list --find <regex>`: interior cells with reference, light, door and
   actor counts and whether Skyrim has a `coc` marker in them.
2. `export --cell <EditorID> --work <dir>` (`src/fo4sf/skyriminterior.py`): the cell's references in the schema-v2
   export (same as the exterior objects), the models to convert, and `cell.json` for the upstream plugin writer:
   converted references, every light, and an arrival marker.
3. `scripts/terrain/make_skyrim_objects.py convert --work <dir> ...`: the same model converter as the exterior.
4. `check --work <dir>`: which placed models converted, failure reasons, and the PluginSpike command.
5. `dotnet run --project dotnet\PluginSpike -- <out> <manifest> <cell.json>`: the upstream writer builds interior cell
   `FO4Port_<cell>` in `FO4Port.esm` (its existing naming; it also writes the lighting template, image space and one
   Starfield omni light per Skyrim light, merged within 3 m; per-cell overrides in `<out>\lighting.json`).

## Arrival (where `coc` puts the player)
Skyrim's own COCMarkerHeading in the cell if it has one; else the teleport destination (XTEL) of the load door that
leads INTO the cell (where Skyrim puts you when you walk in); else the cell's first door (may face a wall). Raised 10
units so the player spawns above the floor.

## Not yet
Load doors (doors are scenery; enter with `coc`), NPCs, navmesh, Skyrim's light colours / radii (one Starfield omni
type for all), Skyrim lighting templates / fog, water planes, effects. First in-game target: a small cell (an inn or
a house), checked for walkable floors and stairs, collision at doorways and readable lighting; then a dungeon.

## First in-game test: Sleeping Giant Inn (owner, 2026-10)

`RiverwoodSleepingGiantInn`: 423 references, 151 models; 140 converted, 393 of 424 placed. In game every piece sat in
the right place with Skyrim's textures. Three findings:

- **Too dark.** PluginSpike's default lighting template (06BCF8) is a dark underground Fallout 4 base, and the inn's
  8 lights were merged within 3 m into a few small Starfield lamps. Skyrim interiors take most of their light from the
  cell's ambient lighting (not translated yet). `export` now writes `<work>\convert\lighting.json` with this cell on
  Starfield's ship interior template `006658` and `LIGHT_MERGE_M` 1; values already in the file win, and
  `--lighting-template` / `--light-merge-m` override both. Still dark in game with 006658, so lights are now
  translated (below).

### Skyrim lights -> Starfield lights

`export` carries each light reference's Skyrim LIGH data (radius, or the reference's XRDS override; colour; fade;
flicker) and the cell's own lighting (XCLL ambient / directional / fog colours, light fade, LTMP, XCIM) into
`cell.json`. PluginSpike makes one Starfield LIGH per distinct Skyrim light by copying the cell's `OMNI_LIGHT` base
(Starfield lights are physically based: `PbrLuminousPowerLm`, `PbrLightTemperatureK`) and setting radius (units / 70),
colour, an estimated colour temperature, flicker, and lumens = template lumens x `LIGHT_POWER` x fade x (radius /
template radius)^2, clamped to 0.25..16x. Knobs in `lighting.json`: `SKYRIM_LIGHTS` 0 (old behaviour), `LIGHT_POWER`,
`LIGHT_RADIUS_SCALE`, `LIGHT_TEMPERATURE` keep, and opt-in `CELL_AMBIENT` skyrim + `AMBIENT_SCALE` (the cell gets its own
XCLL: the template's values with the Skyrim ambient / directional colours). Field names come from Mutagen's Starfield
Light definition and are set by reflection; anything that does not match is printed as a "light note". Written without a
compiler in the cloud workspace (nuget blocked): first build on the owner's PC.
- **The fire pit showed as a big blue / purple crystal.** `inspect_nif.py` named it: `clutter\woodfires\
  fireplacewood01burning.nif` shape `Plane03`, the heat-haze plane above the fire, a BSLightingShaderProperty with
  Shader Flags 1 `82418309` (Refraction 0x8000 + Fire_Refraction 0x10000) and `effects\VaporTileNormal_n.dds` in the
  diffuse slot. The converter now skips refraction shapes and shapes whose diffuse is a normal map, as it skips
  effect shaders. The flames (`Flames:0/1`, effect shader on `FXFireAtlas04.dds`), the glow and the particle sparks
  are effect shaders, so the fire is logs + ash only until effects are translated (a Starfield fire FX placed at the
  same spot is the likely route). Candles have no flame shapes of their own (their flames are separate effects).
- **Doors do nothing:** expected, load doors are scenery until door linking (now: `batch`, below).

Owner's first run with translated lights (Test A): it built and set every field (no light notes), but the inn got
darker. Two of my mistakes: several light references carry an XRDS of ~10 units, which became a 0.14 m light with a
quarter of the lumens (XRDS under 64 units is now ignored, `ref_radius` keeps the raw value), and lights smaller than the
8 m / 2000 lm template had their lumens scaled down (now never below the template; only bigger lights get more).

### Settled defaults (owner's tests, 2026-10-15)

With the fixes above the inn was visible but green-grey: the cell's image space (`LGT_LUT_Int_Gen_v01_curve` 122393,
a sibling of the `v00` LUT upstream rejected for a green cast). `SfInspect imgs` listed Starfield's image spaces;
tested on the inn with template 006658, Skyrim ambient (45, 48, 48) and 4x lumens:

| image space | result |
|---|---|
| `LGT_NoLut` 1C6C37 | warm wood, readable stone and bar: **default** |
| `_RENAME_Test_NaturalColorInterior_IS` 0606C1 | about the same, a little more contrast (a test record: may change) |
| `LGT_LUT_Int_Gen_v04_curve` 03D206 | dark |

`export` now writes `LIGHTING_TEMPLATE` 006658, `IMAGE_SPACE` 1C6C37, `CELL_AMBIENT` skyrim, `LIGHT_POWER` 4,
`LIGHT_MERGE_M` 1 for every Skyrim interior (values already in `lighting.json` still win).

## Navmesh (2026-10-21): Skyrim's own navmeshes, translated
NPC schedules need navmesh in every cell they use. Skyrim's navmeshes are hand-made per cell and carry the door links
AI paths through; the format changed little (`src/fo4sf/skyrimnavmesh.py` has both layouts, from xEdit's
wbDefinitionsTES5 / wbDefinitionsSF1 and Mutagen's Starfield NavmeshGeometry, format only):
* Skyrim NVNM v12 -> Starfield v17: vertices gain a u32, triangles gain a height (f32) and a byte (16 -> 21 bytes),
  edges become u16, edge links gain the edge they leave by (derived from the triangle whose flagged edge points at
  the link), cover is redesigned and waypoints are new (both start empty; Skyrim's cover-triangle list is dropped and
  counted), two u16 after the grid. Triangle flag bits are the same in both games (Mutagen's Starfield enum).
* `export` puts each cell's navmeshes in `cell.json` ("navmeshes": Starfield-layout data, Skyrim units, Skyrim form
  keys). Edge links to navmeshes outside the cell are cut cleanly (edge opened, flag cleared, links renumbered) until
  neighbouring cells are converted together.
* PluginSpike writes them as typed Mutagen `NavigationMesh` records in the cell: positions and grid / 70, parent =
  the new cell, edge links -> the cell's new navmeshes, door links -> the converted door references (`placedBySource`;
  a door that was not placed loses its link). **Not compiled yet** (no .NET packages in the cloud workspace).
* Starfield-only fields (vertex u32, triangle height and byte, the trailing pair): `navmesh_survey.py` (checklist
  step 10) reads vanilla interior navmeshes and writes `navmesh_defaults.json`; `export --navmesh-defaults` uses it.
  **Unresolved** until then: what the triangle height means (clearance? then a wrong value could block NPCs).
* First test: Sleeping Giant Inn again, with its navmesh; `tcai` / `tdetect` off, a spawned NPC told to walk
  (`<npc>.pathtoreference player 1`) should cross the room and use the stairs. If NPCs do not move, regenerate the
  cell's navmesh in the Creation Kit as the fallback and compare.

## Many interiors at once, load doors linked (2026-10-21)
`make_skyrim_interior.py batch` reads Skyrim.esm once for any number of cells (`skyriminterior.Source`) and writes one
work folder that converts and builds as one plugin:
* Cells: `--cells A,B`, `--find REGEX` (e.g. `^Riverwood`), `--connected-from CELL --depth N` (the interiors behind its
  load doors, N doors deep; doors to the worldspace end a path), `--limit`.
* Output: `exports/<cell>.json`, `cells/<cell>.json`, `cells.txt` (PluginSpike takes `@cells.txt`), one
  `convert_input.json` with every model once (one `make_skyrim_objects.py convert` for the whole batch), per-cell
  entries in `convert/lighting.json`, `batch.json` (per-cell counts, door links). `check --work` reports per cell.
* Load doors: every persistent reference with an XTEL is indexed once (worldspace and interiors). A door whose
  destination door is placed in another cell of the batch gets `"teleport"`; PluginSpike gives its converted model a
  DOOR record (`LOADDOOR:<editor id>`, no animation graph; `LOADDOOR_TEMPLATE=<hex>` copies a vanilla Starfield door
  instead), places it persistent, and after all cells sets XTEL (destination reference, landing point / 70, rotation,
  flags). A destination whose model failed to convert leaves the door as scenery (counted). Doors to the worldspace
  stay scenery until interiors and the Tamriel overlay are built together.
* Navmesh edge links are kept when the target navmesh is anywhere in the batch.
* `<out>\source_map.json` (PluginSpike): Skyrim form key of every placed reference, cell and navmesh -> new FormKey.
  NPC placement, furniture and packages (next) look Skyrim targets up here.

**Unresolved until the PC:** whether a DOOR without an animation graph activates and loads in Starfield (if not: `LOADDOOR_TEMPLATE` with a vanilla
load door). Test: batch `--connected-from RiverwoodSleepingGiantInn --depth 1`, `coc` into the inn, use a door that
leads to another converted interior.

### Checked against Mutagen's source (2026-10-21)
The C# names for navmeshes, teleports, load doors and the cell's persistent list match Mutagen's Starfield
definitions. Those files are identical at tag 0.54.4 and on the dev branch (Oct 2026), so also in the pinned
0.55.0-alpha.67, which has no tag of its own. One real bug found and fixed: Mutagen does not type the navmesh grid per
cell. `GridArrays` is one flat run of Int16 values read to the end, then an `Int32 Unknown3`. A list per cell without
counts would have written a broken grid. `cell.json` now carries `grid_raw` (each cell's u32 count as two Int16 values,
then its triangles; `skyrimnavmesh.grid_shorts`, tested against our own serializer) and `tail_int32`, and PluginSpike
copies them as they are. Still unverified until a build: the compile itself, and whether a DOOR without an animation
graph loads.
