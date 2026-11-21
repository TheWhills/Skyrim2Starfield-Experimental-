# Skyrim interiors (houses, inns, caves, barrows, ruins)

Branch `skyrim/armor` (on top of the exterior work). Status (updated 2026-11-17): **built and verified in game** for
Riverwood's interiors: native collision and load doors (2026-10-23, 2026-11-08), lighting and fires (2026-11-15/16);
details in the dated sections below (the first status, "offline only, not in game", was the state before those runs).

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

### PC checklist step 11 (2026-10-21)
`scripts/armor/pc_checklist.ps1` step 11 builds a batch in `<work>\interiors` (default `C:\Modding\work\s2s\interiors`; the Desktop until 2026-10-22):
`RiverwoodSleepingGiantInn` (its only load door leads outside), plus the smallest pair of rooms Skyrim joins by a
load door, each with at least 30 placed records (`batch --smallest-linked-pair`, `Source.linked_pairs`). It uses
navmesh_defaults.json from step 10, converts, checks, and runs PluginSpike when .NET is installed. It does **not**
install. `interior_test.txt` in the report has the install and uninstall commands and the in-game steps: an NPC
walking through the inn, and the door test between the pair.

### First batch run on the PC (2026-10-21)
- Both C# builds compiled on the first try: the combat plugin (one C4267 size_t warning in Game.cpp) and PluginSpike,
  with navmeshes, load doors and source_map.json. `FO4Port.esm`: 3 cells, 3 navmeshes (379 / 80 / 68 triangles, door links
  all kept), 2 load doors linked, 0 lost. Door test pair found: MorthalAlvasHouse <-> MorthalAlvasHouseCellar.
- Navmesh survey (300 vanilla interior navmeshes): vertex u32 = 1 (26,301) or 0 (8,776); triangle byte 0 (206 are 2);
  tail (12, 8) in 296 of 300. Triangle height: min 1.8, most common 1.8, median 4.63, max FLT_MAX (no ceiling), median
  2.45 on door triangles. **Supported:** the height is the clear space above the triangle in metres (1.8 = a
  human's minimum). We write the median 4.63 everywhere: right for ordinary rooms, too high under low ceilings.
  Measuring it from collision would be the proper fix if NPCs try to walk under things.
- MorthalAlvasHouse's ambient came out 0,0,0: its XCLL inherits the ambient from its lighting template (flag 0x1), and
  the cell's own field is unused. `Source.cell_lighting` now takes inherited ambient / directional colours (and both,
  for a cell with a template and no XCLL) from the Skyrim LGTM.

## Alva's House: blocked stairs and an offset door prompt (analysis 2026-10-22)
Owner's report: the player stops at the head of the cellar stairs; the door's activate prompt shows a little past the
door, not on it.
- **Activation is a precise ray against the collision shape** (tes4skyrim's finding for Skyrim, `docs/commentary/
  asset_convert_collision.md` "Activation pick region"; Starfield is assumed to work the same). A prompt past the door
  means the door's collision is not where its visible mesh is.
- **Our Skyrim collision is an approximation:** the decoded Skyrim triangles (transforms verified on 2,473 models) are
  rebuilt as thin boxes behind faces within ~23 degrees of an axis, plus axis-aligned voxel boxes (0.2 m, coarsened to
  ~0.45 m when over 96 boxes) for everything else. Skyrim stair collision is often a ramp (tes4skyrim's census of vanilla
  stairs: stepped with stairs material, or a ramp), and a 30-45 degree ramp is all voxels.
- **Measured on a synthetic stairwell** (2 m drop over 3 m, landing above, plus sloped detail elsewhere using the voxel
  budget): boxes stand up to 0.47 m above the ramp and up to 0.27 m above the upper floor at the stair head, depending
  on where the floor falls in the voxel grid. Supported (not verified on the real mesh): that ledge is what stops the
  player.
- The FO4 path solved the same problem with native collision: FO4's authored compressed-mesh collision copied into
  Starfield's hknpCompressedMeshShape (`meshcollision`), **verified in game** (Prydwen stairs climbed, a Rexford door
  walked through). The Skyrim path never got it because Skyrim's Havok 2010 collision cannot be copied; it needs a
  Starfield compressed mesh built from triangles (sections, quantised vertices, AABB trees, SIMD tree).
- Also missing on interiors: object bounds (OBND) on PluginSpike's statics and load doors (the exterior path learned
  the CK treats bound-less objects as zero-sized; tes4skyrim sets OBND from every converted mesh).
- To confirm on the real meshes: `convert\manifest.json` holds each model's collision report (render vs collision
  bounds, boxes, voxel cell, bodies and layers).

## Native collision for Skyrim models (2026-10-22, offline; in-game check pending)
Fix for the stairs / door analysis above: Skyrim's own collision becomes native Starfield collision, as the FO4 path
does (verified in game there), instead of boxes.
* `src/fo4sf/cmsencode.py` builds a Havok compressed mesh (the hkcdStaticMeshTree inside hknpCompressedMeshShape) from
  triangles: spatial sections (at most 120 primitives, 250 vertex slots), 11/11/10-bit packed vertices, 21/21/22-bit
  shared vertices at section seams, data runs, and the two compressed AABB trees. The format was read off 34 FO4
  compressed meshes (50 sections, 5,449 triangles): every tree walks and every triangle sits in its leaf box with the
  codec as documented in the module (child box = parent box moved in by h^2 / 226 and l^2 / 226 of its span; 4-byte
  section nodes with odd data = internal, 5-byte top nodes with 0x80 = internal; section leafIndex = its top-tree node).
* Checks: the encoder's own strict check (tree shape, every triangle inside its leaf box with float32 decoding, sections
  inside their top-tree leaves); fo4collision's decoder reads the encoding back identically; the 34 FO4 meshes re-encoded
  from their triangles pass and come back within 6.6 mm (11-bit packing). Tests: `tests/test_cmsencode.py`.
* `meshcollision.mesh_body` writes it through the unchanged FO4 writer (`_emit_mesh`, via `cmsencode.Fo4View`), one
  Starfield body per Skyrim body, **with the Skyrim body's layer** (stair helpers stay stair helpers). Bodies on non-solid
  layers (trigger, portal, non-collidable, sound / AI volumes, picks: `NON_SOLID_LAYERS`) get no body; the box path now
  leaves them out too (before, every body was merged into one triangle soup, so a trigger volume became boxes).
* `make_skyrim_objects.py convert` uses it whenever `--starfield-data` is given (template: Bethesda's multi-shape test
  NIF, as the FO4 path); `--box-collision` keeps the old boxes. A model whose native collision fails falls back to boxes
  with the reason (`collision_report.native_error`, `manifest.json` "native_collision_errors"). The converter's cache key
  changes, so `--resume` reconverts everything once.
* Checklist step 12 (`scripts/tools/cms_survey.py`) walks vanilla Starfield compressed meshes with the same tree reader:
  it should report 0 problems (so far the format is verified on FO4 files only).
**Unresolved until the PC:** the first game load with these bodies (template / writer as for FO4, so expected to work);
whether Alva's stairs and door are fixed. Exterior objects converted with `--starfield-data` get native collision too.

## Native collision and load doors in game (owner, 2026-10-23)
- Verified: with native collision the character walks down Alva's cellar stairs and the door prompt sits on the door
  (159 of 176 models native, 0 fallbacks; the other 17 have no Skyrim collision).
- Verified: load doors need the record's Persistent flag (0x400), not just the cell's persistent group. Without it a door
  worked once, then lost its prompt until a reload and the return trip landed at the wrong end. After the fix both
  directions work. `scripts/interior/door_survey.py` (checklist step 13) on Starfield.esm: all 619 vanilla load doors
  are persistent; XTEL is 36 bytes (the last 4 always 0), its position is the landing spot by the destination door
  (median 0.21 m from it), as in Skyrim; 576 / 619 also carry XNDP (navmesh + triangle by the door, for AI) and every
  DOOR base has OBND. Ours have neither yet.
- Verified (owner, 2026-10-23: "stairs seem smooth now"; Alva's House, ramps on layer 31): going up the stairs the
  character "ran into each step" before ramps. The run found 3 flights in 2 models (FarmIntWBasementEnt01,
  FarmBWallEntrance05).
  `stairramp.py` finds flights of 3+ steps in the collision and native collision adds a ramp body through the nosings
  on layer 31 (stair helper: only actors collide). `--stair-ramp-layer 1` puts it on the static layer if 31 does not
  work in Starfield, `0` turns it off. The manifest lists the models that got ramps (`stair_ramps`).

## Doors between the exterior and the interiors (2026-11-08; offline, C# not compiled yet)
Owner: "get the Riverwood inn connected to Riverwood" (the Tamriel exterior is already on the planet). Until now doors
to the worldspace stayed scenery. Three builds, in this order:
1. `make_skyrim_interior.py batch ... --exterior`: doors to the worldspace keep their teleport (cell "exterior", Skyrim
   exterior units) and `exterior_doors.json` lists the worldspace load doors that lead into the batch (Skyrim refs,
   with their XTEL into the interior).
2. `make_skyrim_objects.py stage ... --interiors <batch work>`: those exterior references become load doors in the
   exterior plugin: a `<base>_LoadDoor` DOOR (no animation graph, as the interior load doors verified in game) and the
   reference persistent (the world's persistent cell + record flag 0x400). TerrainOverlays' `formids.json` now also
   has the world's and its persistent cell's FormIDs. The rest of the exterior is unchanged (FormIDs after the new base
   shift by one: a rebuilt exterior, not a patch to an old one).
3. PluginSpike with `EXTERIOR_DIR=<staged exterior>` and `EXTERIOR_DOORS=<batch work>\exterior_doors.json`: interior
   doors to the exterior get XTEL to the exterior plugin's door, landing point in the overlay frame (Skyrim / 70 -
   origin_cw_m, z + height_offset_m, as to_local); the exterior doors get their XTEL to our interior doors through an
   override in FO4Port.esm of the world, its persistent cell and the door references (copied from the exterior plugin;
   OFST / CLSZ left out of the override). FO4Port.esm then has the exterior plugin as a master.
Unresolved until built and run: the C# (written without a compiler), whether the world override keeps the exterior
intact in game (only record fields are copied; cells stay in the exterior plugin), and the landing heights.
**Changed the same day: no exterior rebuild needed.** The installed exterior is `C:\Modding\staging\skyrim_all` (its
SkyrimTerrainTamriel.esm matches the game's byte for byte in size and date; height offset 385 m). PluginSpike with
`EXTERIOR_DIR` / `EXTERIOR_DOORS` now overrides, in FO4Port.esm, the world and its persistent cell (copied from the
planet plugin when it overrides them, as make_planet.py does for the landing pad) and the exterior cell holding the
inn's door: the exterior's static copy of the door gets Initially Disabled, and a persistent load door of ours (a DOOR
with the same model, bounds and placement) with XTEL into the inn takes its place. Step 2 (`stage --interiors`) is only
for a future exterior rebuild; if the door is already persistent there, PluginSpike just overrides it with the XTEL.
Owner's one command: `tools\owner\riverwood_doors.ps1` (batch, convert --resume, check, PluginSpike, reinstall FO4Port).
**Verified in game (owner, 2026-11-08):** with `tools\owner\riverwood_doors.ps1` (three PluginSpike fixes on the way:
no Landscape on Starfield cells, master styles to read the exterior plugins, an explicit load order to write) the owner
walked from Riverwood into the Sleeping Giant Inn and back out through the linked doors.

## Pathing registration (2026-11-08)
tes4skyrim found that Skyrim's pathfinder ignores navmeshes not listed in the NAVI record and treats load doors without
XNDP as no pathing node; our interior navmeshes had neither. PluginSpike now writes both for every navmesh it writes
(docs/terrain/exterior-navmesh.md "What tes4skyrim found"). `$env:NAVI="off"` leaves the NAVI out. Unresolved in game.

## Fires and candles (2026-11-09, owner: convert Skyrim's own effects rather than borrow Starfield's)
Three parts: (1) the light: already Skyrim's own (each LIGH -> a Starfield light with its colour, radius, fade,
flicker; settled defaults above); (2) the flame you see: effect-shader cards (crossed planes playing an animated
atlas such as FXFireAtlas04.dds) and glows, dropped by the converter today (fire = logs + ash); candle flames are
often not in the candle's model but an add-on (a BSValueNode "AddOnNode<n>" in the model -> the ADDN record with DATA
index n, whose model is the flame); (3) particles (sparks, embers, smoke) and the heat-haze refraction plane.
Direction (owner, supported): convert Skyrim's own flame cards (one converted asset covers every placement of it) as
Starfield emissive materials playing Skyrim's atlas, particles by the route Starfield allows (its own particle system
if models can carry one, else simple cards or a Starfield effect for sparks / smoke only), haze last.
Unknowns the survey answers: which effect assets the interiors use and how often Skyrim reuses them, how they animate,
which light sits next to each; whether Starfield models carry particle blocks; which material components Starfield's
database has (a flipbook / emissive component and its fields = animated glowing materials can be written like our
other .mat files). scripts/interior/fire_survey.py (read-only) writes fire_survey.json / .md.
Survey answers (owner's run 2026-11-09, Riverwood batch): candles (table / wall / floor / chandeliers, 90 placements)
have no flame in their model, only AddOnNode slots for ADDN MPSCandleFlame01 (textures candleflame01 / candleglow01);
hearths are FireplaceWood01Burning (8: flame cards on FXFireAtlas02 / 04 + WoodFires01_g, animated; particles; one
haze plane); the bare hearth architecture carries nothing. Starfield: 0 of 60 fire-named models carry particle blocks,
its fire ADDN records all point at fxemptynode.nif (the effect lives elsewhere), and its materials have a
FlipbookComponent (IsAFlipbook, Columns, Rows, FPS, Loops) and emissive / effect settings. So: flames = converted cards
with a flipbook emissive material; candle add-ons placed by us at each AddOnNode.
2026-11-15: scripts/interior/flame_probe.py (read-only) prints what that conversion needs: the candle ADDN's model and
DATA, every effect-shader shape of the hearth / candle / add-on models (texture, flags, UV offset / scale, its
controllers: variable, frequency, start / stop, keys), AddOnNode positions, and Starfield's flipbook .mat files (a
fire one printed whole, the template our flame materials copy).
Probe results (owner, 2026-11-15): the candle add-on is ADDN 000B9FC5 MPSCandleFlame01 (DATA 49 = AddOnNode49;
table candle 1 slot, floor candle 4 at 127 units up) whose model has two effect shaders (CandleFlame01, CandleGlow01)
with no shape of their own: they are particle systems. The hearth's visible flames are two meshes "Flames:0 / :1"
(48 / 42 vertices) on FXFireAtlas04 coloured through the GradFireExplosion palette (greyscale-to-palette flags), animated
by a V Offset scroll 0 -> 1 over 5.667 s / 4.267 s, not a flipbook; a "Glow" mesh on the logs (WoodFires01_g) pulses
its emissive colour; FXFireAtlas02 and smoke are particle systems. Starfield: 527 .mat files with an active flipbook
(FireFlamethrower 8x8 at 32 fps; FireCandleFlame.mat exists). Second probe pass (same script): particle emitters /
colour / sub-texture fields, texture sizes, Starfield's material controllers (how a UV scroll is animated) and which
Starfield fire / candle meshes use which materials.
Pass 2 results (owner, 2026-11-15):
* Skyrim candle flame (MPSCandleFlame01): particle system "CandleFlame01" (CandleFlame01.dds 128x128, one frame):
  6 / s, life 0.33 s, radius 1.25 units, rising 7.5 units/s, scale 0.7 -> 1.0 -> 0.2 over life, fade in 20 % / out
  80 %, colour white to warm (0.97, 0.92, 0.88); "CandleGlow01" (CandleGlow01.dds 256x128): 5 / s, life 0.4 s, radius
  80 units, white at alpha 0.37 (a large soft halo).
* Hearth particles: "FlamesSmall01" (FXFireAtlas02 512x256 through GradFireExplosion): 15 / s, life 0.4 s, radius 16,
  rising 45 units/s from a 20-unit cylinder, scale 1 -> 0.5; "smoke" (SmokeParticles01 512x512): 15 / s, life 2 s.
  Mesh flames: FXFireAtlas04 is a 128x1024 vertical strip (scrolled V 0 -> 1); palette GradFireExplosion 256x64.
* Starfield animates material values with BSBind controllers: 508 .mat files, binding "UVOffset" in 517 mappings
  (Float2DCurveController 662) = a UV scroll is native, so Skyrim's V Offset scroll converts as a controller, not a
  baked flipbook. FireCandleFlame.mat: 1LayerEffectEmissive, flipbook 12x12 at 90 fps driven by a TimerController on
  "FlipbookAuto" (random offset), EmissiveOnlyEffect, VertexColorBlend, LuminousEmittance 75000, edge falloff.
* Starfield's lit candles (setdressing/candles/candlegen_*_lit.nif, paperlantern01_on.nif) carry the flame inside the
  model: FireCandleFlame.mat + FireCandleGlow.mat shapes. No particle blocks; its fire ADDN records are empty nodes.
Direction: candle add-ons become flame + glow cards placed in the converted candle model at each AddOnNode (Skyrim's
sizes and colours, Skyrim's textures); hearth flame meshes keep their geometry with an emissive effect material
(texture baked through the palette, V scroll as a UVOffset controller); the hearth's particle flames become a few
cards with FXFireAtlas02. Pass 3 lays out a Starfield lit candle (how its flame card is built and faces the camera),
FireCandleGlow.mat and the shortest UVOffset-controller material, the templates for both.
Pass 3 results (owner, 2026-11-15): Starfield's lit candle (candlegen_c01_lit.nif) and paper lantern are plain
static NIFs: the flame is a BSGeometry "Flame:0" (228 vertices, vertex colours) + BSLightingShaderProperty naming
FireCandleFlame.mat, beside a "Glow:0" disc on FireCandleGlow.mat (EmissiveIntensity FloatCurveController flicker,
29812 .. 45000, plus UVOffset). No billboard nodes. A UV scroll (AnimatedGlowFX_LightBeam01): Float2DCurveController on
"UVOffset", XCurve without controls, YCurve (0, 0) -> (1, 1), InputDistance / MaxInput = the loop length, Loop true,
Mask "X;Y".

### Flames v1 (2026-11-15): src/fo4sf/skyrimfire.py, used by skyrimconvert
* Hearth / campfire flame meshes (BSEffectShaderProperty whose texture matches `fire|flame|candle|woodfires`) keep
  their geometry and get an emissive effect material cloned from FiresGeneric_Sm_01_14x14.mat (soft additive,
  emissive only) with its flipbook removed: the Skyrim texture with the palette baked in (colour = palette at the
  texture's grey, alpha = palette alpha at the texture's alpha, row PALETTE_ROW = bottom), times the effect's emissive
  colour; colour BC1 sRGB, opacity BC4; VertexColorBlend when Skyrim fades by vertex alpha. Skyrim's V Offset
  controller becomes a UVOffset Float2DCurveController (FireplaceWood01Burning: 0 -> 1 over 5.667 s and 4.267 s).
  Other effect shapes (glows, magic, dust) stay skipped as before.
* Candles: every AddOnNode<n> with n in ADDON_MODELS (49 = MPSCandleFlame01) gets that add-on's flame particles as
  three crossed double-sided cards at the node (CandleFlame01.dds; half width = radius x the scale curve's peak, lifted
  by half the rise speed x life), material at FireCandleFlame's emittance (75000) with an EmissiveIntensity flicker
  (about 1 s loop, down to 70 %). Halos (particle radius over 10 units: CandleGlow01's 80) and smoke are left out.
* Not yet: the hearth's particle flames (FlamesSmall01) and smoke, the log glow's colour pulse, the heat haze.
* To check in game (supported hypotheses): flames scroll upward (else the scroll sign flips), the hearth colour is
  orange like Skyrim's (else the palette row), candle flames sit on the wicks, brightness (EMITTANCE).
* Rebuild cost: skyrimconvert changed, so the model checkpoints are invalid once and every model converts again.
Owner in game, v1 (2026-11-15, Sleeping Giant, beside Skyrim screenshots): flames present; candle cards white, very
bright with a slight flicker, static, reading as thin crossed lines (Skyrim: a small warm yellow-orange flame); hearth
flames move but are faint, small and blue (Skyrim: big orange flames, mostly the FlamesSmall01 particles, which v1
leaves out). Changes: candle emittance from FireCandleFlame's fixed 75000 to the hearth's adaptive 5000; card colour
= particle colour x the effect shader's emissive colour (Skyrim's rule; v1 used the particle colour only).
scripts/interior/flame_textures.py (read-only) renders the atlas, palette, candle and glow textures and the palette
bakes for rows 0 / 0.5 / 1 with the grey from green or from alpha into one sheet, and prints the shaders' emissive
colours and where the hearth's particle systems sit: the data to fix the palette lookup and add the particle flames.
flame_textures results (owner, 2026-11-15): GradFireExplosion (256 x 64) runs dark red -> orange -> white from its
top to its middle row and is blue only in its last rows (bottom row alpha 0 -> 237); the hearth shaders' emissive
colours are greys (Flames 0.224 / 0.275, log glow 0.196) with multiples 1.25 - 1.75, alpha 1 - so the emissive red is
the palette row (v1 used the bottom, blue row and then darkened by the grey: the faint blue flames). FXFireAtlas04 is
grey (R = G = B); CandleFlame01 is a 2 x 2 atlas of four warm flame frames (v1 showed all four on one card: the "II"),
FXFireAtlas02 a 4 x 2 atlas of orange flames whose alpha is palette-mapped; CandleGlow01 a grey halo (colour 0.39,
0.29, 0.18). FlamesSmall01 sits at z 7.99 in FireplaceWood01Burning (emitter = a 20-unit cylinder), smoke at 37.5.
Flames v2:
* Colour = palette(u = grey, v = emissive red) x emissive multiple; alpha = palette alpha(u = texture alpha,
  v = emissive alpha); unmapped colour = texture x emissive colour x multiple (skyrimfire.bake_params). Supported
  hypothesis from the data above (the greys only make sense as rows).
* Particle atlases play as Starfield flipbooks (columns x rows from the NiPSysData sub-texture offsets, else
  SUBTEXTURE_GRIDS; FLIPBOOK_FPS candle 8, hearth 10) driven by a TimerController on FlipbookAuto, as vanilla
  FireCandleFlame.mat: one frame per card, and the candles move.
* The model's own flame particles become cards too (model_flames): FlamesSmall01 = five crossed cards (one at the
  emitter, four on a ring at 55 % of its radius), 32 units wide, lifted by half their rise. Halos are particle systems
  over 40 units or named / textured "glow"; smoke stays out.
Owner in game, v2 (2026-11-15): "actually does look much better"; hearth orange with flames across the pit, candles
small and warm. Left: "a slight low quality, the fires move slower than Starfield's". Causes: Skyrim's atlases have
4 / 8 frames (Starfield's fire materials 144 - 196 at up to 90 fps) that Skyrim's particles picked at random while
rising and fading; fixed cards cycling them at 8 / 10 fps step; BC1 made the gradients blocky; the emissive multiple
baked into the colour clipped hearth cores to white. Flames v3:
* frames 12 fps (candle) / 20 fps (hearth); two layers per flame spot (LAYER2: turned 30 degrees, 80 % size, lifted a
  quarter of the flame, u mirrored, its own frame rate x 0.73) cross-fading through an OverallOpacity curve
  (CROSSFADE 0.55 - 1, opposite phases, a loop of 3 x the particle life) - a stand-in for particles being born and
  fading; OverallOpacity on effect materials is a supported hypothesis (145 vanilla materials animate it);
* colour BC7 sRGB instead of BC1;
* Skyrim's emissive multiple goes into the emittance (base x multiple x EMITTANCE_SCALE, hearth 0.5, candle 1), the
  texture keeps the palette's hue.
A slow upward drift was proposed too; a UV scroll on a flipbook would slide neighbouring frames into view, so the
cross-fade does that job instead.
particle_scan.py (owner, 2026-11-15): 79,344 Starfield NIFs (base game, DLC, Creations, our own) read, 0 with a
Gamebryo particle block (NiParticleSystem / NiPSys* / BSPSys*). **Verified**: Starfield's models carry no Gamebryo
particles, so Skyrim's particle systems cannot be copied into converted models as they are (an injected test model
could still be tried, but the engine very likely no longer has that path); cards stay the route, and Starfield's own
particle system (behind its empty-node fire ADDN records) is unresearched.
Owner on v3 (2026-11-15): hearth flames "a bit intense, three straight clots of flame; maybe better to use Starfield's
flame". Changes: hearth EMITTANCE_SCALE 0.5 -> 0.3, card ring 55 % -> 85 % of the emitter radius (RING), and a switch
`--flame-style skyrim|starfield` (riverwood_doors.ps1 -FlameStyle): "starfield" keeps the cards' places, sizes and
timing from Skyrim but plays Starfield's own fire flipbooks (FiresGeneric_Sm_01_14x14 196 frames at 30 fps for
hearths, FireCandleFlame 144 frames at 90 fps for candles; clones with their vanilla textures, our emittance, one
layer). The hearth's scrolling flame meshes keep Skyrim's texture in both styles. The style is in the checkpoint
signature, so switching reconverts the models (since 2026-11-15 later: only the flame models, per-model flame_key).
Owner, -FlameStyle starfield in game (2026-11-15): hearth flames "so subtle" (small licks over the logs), candle
flames very small, dim and thin. Starfield's fire atlases draw a small flame inside each frame, so on Skyrim-sized cards
they read smaller and fainter than Skyrim's own; Skyrim style stays the default.
Owner on v3 Skyrim style (2026-11-15): "still looked low quality, like moving pngs compared to flames". Cards are the
ceiling of the static-geometry route: Skyrim's look comes from many overlapping moving particles. Next: Starfield's
own particle fire (its fire ADDN records point at an empty NIF, so the effect is defined elsewhere).
scripts/interior/sf_fire_probe.py (read-only) lists Starfield's fire-named records with every field, the archive
file types with the fire-named files of any non-plain type, and the fire effect NIFs' contents.
sf_fire_probe results (owner, 2026-11-15). **Verified**: Starfield's particles are `.psfx` files (831, in
`Starfield - Particles.ba2`: particles\fires\firemed01.psfx, firemed02, firegenericflame, firegeneric_oit,
firepit_armisticearchives_01, hazardfire01 ...), attached to records by a `ParticleSystem_Component` (BFCB) whose PTCL
reflection data holds a ParticleSystemPath (MSTT, HAZD, EXPL, ARTO); ADDN records carry the same as PSDF (so its fire
ADDNs point at fxemptynode.nif). A ready placeable fire: MSTT 0000C78D **FireMed01** (model
Effects\EffectMarkers\ParticleMarkerOrange.nif = the editor marker); also FXP_MemorialFire 00004630. Starfield's
candle lights (LGT_Fire_Candle*) carry a BGSEffectSequenceComponent (a flicker sequence); its candles' flames are
static cards (FireCandleFlame.mat), as ours.
Flames v4, `--flame-style particles` (riverwood_doors -FlameStyle particles, a full build: the plugin changes): a
hearth model's flame particle systems become `sf_effects` in the manifest ({base 00C78D, offset_m: the emitter in
metres}); PluginSpike places that vanilla MSTT with every reference of the model (offset rotated and scaled with
the reference, initially disabled with it); the scrolling FXFireAtlas meshes are left out, the log glow stays, candles
keep the Skyrim cards. Unverified: FireMed01's size against a Skyrim hearth (scaled with the reference only), the
PluginSpike change compiling (no .NET in the cloud workspace).
Owner's build (2026-11-15 22:57): PluginSpike compiled; 8 FireMed01 references placed (Sleeping Giant 3, every
house 1), with 3 flame materials (candles, log glow).
Owner in game, v4 (2026-11-15): real moving flames, sparks and smoke in the hearth (**verified: vanilla particle-fire
MSTTs placed by our plugin burn**), but "a bit intense, looks like three flares as opposed to hearth flames": FireMed01
is a standalone medium fire with a tall smoke plume, one per FireplaceWood01Burning (the Sleeping Giant pit has 3).
Candles unchanged by design (Starfield's own candles were taken for cards; sf_firepit_probe 2026-11-16: they are a
228-vertex mesh). Next: `-ParticleFire BASE[:SCALE]` (any Starfield.esm
fire, scaled with the hearth) and `sf_fire_probe.py --only-psfx` (every record using a .psfx, fire-like ones with
their particle files and size) to choose a hearth-like fire (firemed02, firegenericflame, firepit_armisticearchives_01).
sf_fire_probe --only-psfx (owner, 2026-11-15): 853 records use a .psfx. Placeable fires (MSTT): FireMed01 00C78D
(firemed01), FireMed02 1CEDAB (firemed02), FXP_MemorialFire 004630 (firegenericflame), FXArmisticeArchives_
MemorialFire_01 20D560 (firepit_armisticearchives_01: a fire pit), FireGeneric_OIT 3E3C86 (firegeneric_oit, 2 m radius
marker). Comparison build: `-ParticleFire 004630,20D560,1CEDAB`: PluginSpike gives the k-th fire placed in the plugin
choice k mod n (the Sleeping Giant pit's three fires = the three candidates side by side; its log prints each fire's
base and position).
Comparison build (owner, 2026-11-16, 72 s): Sleeping Giant pit fires (x, metres; Orgnar's bar is at x -18.8):
20D560 fire pit at -8.47 (nearest the bar), 004630 generic flame at -7.33 (middle), 1CEDAB FireMed02 at -6.20
(farthest from the bar); houses: Alvor 004630, Faendal 20D560, Gerdur 1CEDAB, Trader 004630, Sven 20D560.
Owner in game (2026-11-16): only two of the three pit fires show; the middle one (004630, firegenericflame) is "far
too big" (a tall solid flame body at x0.84), the end one looks better (by elimination 1CEDAB FireMed02; owner unsure
it differs from FireMed01). The missing one is most likely 20D560 (Armistice Archives fire pit: its MSTT has no
bounds, EditorMarker_FX model). **Confirmed** (owner, 06:49): Faendal's house, which has only 20D560, shows no fire;
20D560 dropped from the candidates (it probably needs a script or activation to start). Next comparison:
004630 at 0.35 (a solid hearth-sized flame) and 1CEDAB at 0.8.
Second comparison (owner, 2026-11-16 06:54; 004630:0.35, 1CEDAB:0.8, 004630:0.5): "two big ones and a normal one; the
normal one looks better" = FireMed02 1CEDAB at x0.8 (placement order is the cell's reference order, not left to right:
it sat at the bar end, x -8.47). 004630 looked about as big at x0.35 as at x0.5: the particles barely follow the
reference scale. **Default now** (2026-11-16): --flame-style particles with FireMed02 at x0.8 (skyrimfire
PARTICLE_FIRE_BASE / _SCALE; riverwood_doors -FlameStyle defaults to particles); candles keep the Skyrim cards.
Owner (2026-11-16 07:03): "use Starfield's for candles as well but make them follow Skyrim's thicker teardrop shape".
`--candle-style starfield` (riverwood_doors -CandleStyle starfield; models only, so -AssetsOnly switches it):
FireCandleFlame.mat cloned as it is - its FiresGeneric_Sm_03 12 x 12 flipbook at 90 fps on its timer, its emittance
(75000) and edge falloff, no flicker of ours - on one crossed card per Skyrim candle flame, widened x1.8 and x1.1 taller
(SF_CANDLE_WIDTH / _HEIGHT) so the narrow flame in each frame fills out to Skyrim's teardrop. The 2026-11-15 "starfield"
flame style had Skyrim's card size and our emittance (5000 adaptive): "very small, not bright, quite thin".
Owner, FireMed02 default in game (2026-11-16 08:20): "the hearth flames are basically one fireball in a hearth, or 3 in
a big one, but don't look like an actual fire across the hearth" (Sleeping Giant pit: three tidy flames; a house
fireplace: one small flame in the middle). One fire per Skyrim emitter is a point; Skyrim's fire runs along the logs
through its flame meshes. Now (skyrimfire.fire_spots): the fires go along the longer side of the model's fire shapes
(flame meshes + log glow, model space), FIRE_SPACING 24.5 units (0.35 m) apart, at most FIRE_MAX 4 per model, at the
emitter's height, each x SPREAD_SCALE 0.75 when there are several; a model without fire shapes keeps one per emitter.
Owner in game (2026-11-16 08:52): the pit now burns along its length but "looks a little silly, very clearly a few
fireballs thrown in there, compared to Skyrim's that looks like a hearth burning. Do we need to figure out how Starfield
fire pits work"; candles (Starfield's flame x1.8 / x1.1) "quite thin still" -> x3.0 / x1.25. A placed MSTT fire is a
standalone fire; Starfield's own pits presumably burn with flame geometry on its layered fire materials (LayeredFireV2 /
V3, Fire_Layered_ArmisticeArchive_01). scripts/interior/sf_firepit_probe.py (read-only) lists every Starfield NIF naming
a fire material (with its shapes, materials, sizes) and the records using those NIFs.
sf_firepit_probe (owner, 2026-11-16), **verified**: Starfield has no fire-pit flame geometry. 36 of 54,651 NIFs name a
fire material: 33 candles / a paper lantern (FireCandleFlame + FireCandleGlow), 7 of ours, Firepit_Portable01 (only
the pit: metal, gravel, rocks, wood; its STAT 00146A50 carries no particles, so its fire is a separately placed particle
fire, as ours are) and two debug models: LayeredFireV2.mat on a 1 m box (effects\debugfiles\testmaterialbox.nif) and
xTests\LayeredFire.mat on a teapot. So Starfield "fire pits" are what we already did; the fireball look is the
standalone particle fire itself. Starfield's candle flame "Flame:0" is not a card but a 228-vertex / 336-triangle
mesh with vertex colours, radially symmetric (x, y +-7.0, z +-8.46 x the shape's 0.002 - 0.003 = 2.8 - 4.2 cm wide).
Two changes, one build:
* `--flame-style layered` (riverwood_doors -FlameStyle layered; a full build, the particle fires go): Skyrim's own hearth
  layout - the scrolling FXFireAtlas flame meshes, UVs stretched to 0..1 per card (skyrimfire.normalize_card_uvs), and
  the FlamesSmall01 particle cards - burns with LayeredFireV2.mat, Starfield's fire material for any geometry, cloned as
  it is (skyrimconvert.layered_fire_material; the build prints its shader model, layers and textures under
  "layered_fire"; if it cannot be read, the vanilla path is used directly). Log glow unchanged. Unresolved: how it
  looks on cards.
* `--candle-style starfield` now uses that mesh: read from the Starfield archives at build time (never stored), fitted
  to SF_CANDLE_WIDTH / _HEIGHT (x3.0 / x1.25) x Skyrim's flame (skyrimfire.sf_flame_shape: box to box, normals through
  the stretch, vertex colours kept); crossed cards when --starfield-data is missing or the mesh is not found.
Owner, -FlameStyle layered in game (2026-11-16 09:52, Sleeping Giant beside Skyrim's): the fire now runs across the
logs in licks like Skyrim's hearth, but "awfully white". Supported hypothesis: LayeredFireV2's own emittance blows it
out, as FireCandleFlame's 75000 did on our candle cards (2026-11-15). The clone now takes LAYERED_EMITTANCE (2000,
adaptive, about our orange v2 hearth: 5000 x 1.5 x 0.3) wherever it sets one (skyrimfire.set_emittance; the build's
"layered_fire" stats show the vanilla values and how many were set). If it stays white or turns grey, its textures are
greyscale and need a tint: the cloned .mat shows which fields it has.
Owner at 2000 (2026-11-16 10:14): still white (fire across the logs, finer and dimmer). The clone (**verified**, the
owner's sf_layeredfirev2.mat): 3layereffectemissive, layer 1 emissive FireColumnTile_color (4 x 2 flipbook, scrolling
in V every 1.1 s, UV x1 / x1.25), layer 2 SimpleSmokeBrightTile opacity (x5, subtractive, scrolling every 0.75 s),
layer 3 GradientFlameCurveInv opacity (the flame's shape); vanilla emittance 12000 adaptive, exposure 11.17; colour only
from LayeredEmissivityComponent.FirstLayerTint (1, 0.949, 0.922): LayeredFireV2 is a near-white fire by design. The
clone now takes FirstLayerTint LAYERED_TINT (1, 0.45, 0.12), Skyrim's fire orange (in LAYERED_EMITTANCE, so
set_emittance writes it). Candles with Starfield's flame mesh: "a small thin flicker at the wick" -> SF_CANDLE_WIDTH /
_HEIGHT x7.0 / x2.5. Both in skyrimfire.py only, so -AssetsOnly redoes just the flame models.
Owner in game (2026-11-16 10:23): hearth "looking better" (LayeredFireV2 tinted orange along Skyrim's flame layout; a
house fireplace shows a low strip of flame). Candles on Starfield's mesh x7.0 / x2.5: "a line of fire as opposed to a
teardrop shaped little flame": the flame Starfield draws in its candle flipbook is a thin streak, and stretching the
mesh does not change what the texture draws (supported hypothesis). Skyrim's own candle texture (CandleFlame01) is the
teardrop; next comparison: -CandleStyle skyrim (models only). Interior lighting (Faendal's house): "white and strong at
the lighting locations as opposed to a warm fire lit room". Before changing PluginSpike's Skyrim lights (copies of the
neutral ship omni 03D38C, temperature from the Skyrim colour, lumens x LIGHT_POWER 4): Starfield's own fire / candle
lights (SfInspect form type:Light Fire) and Faendal's Skyrim lights (cells/*Faendal*.json) for numbers.
Numbers (owner, 2026-11-16 10:33), **verified**: Faendal's house has five Skyrim lights, all 512 units (7.3 m),
flickering: four fill lights (FarmInteriorShadowLight01 / FarmInteriorLight01) colour 198,162,100 (McCamy 3623 K) and
one fire light (FarmInteriorFireLight01) 173,103,52 (2321 K); cell ambient 45,48,48 from its lighting template. Ours: a
copy of the neutral ship omni 03D38C at LIGHT_POWER 4 = 8000 lm each at 3623 / 2321 K. Starfield's own interior fire
lights: LGT_Fire_Candle_Interior 3197A4 (3000 lm, 2.5 m), LGT_Fire_Candle 3197A3 (1000 lm, 4 m), LGT_Fire_Cauldron
3197A6 (4000 lm, 8 m), LGT_Fire_Ambient 3197A1 (100 lm, 4 m): all 1900 K, colour 254,98,22, falloff exponent 2, the
candle / cauldron ones with a flicker effect sequence. So ours were twice Starfield's brightest interior fire, and Skyrim's
fill colour, warm in Skyrim's sRGB lights, sits at a near-neutral 3600 K in Starfield's (supported hypothesis for "white
and strong"). Now (export defaults, lighting.json): OMNI_LIGHT 3197A6 LGT_Fire_Cauldron as the base, LIGHT_POWER 1.5
(6000 lm at Skyrim's 7.3 m), LIGHT_TEMPERATURE warm with LIGHT_MIRED_SHIFT 95: every Skyrim light's temperature
shifted 95 mired warmer, which puts Skyrim's fire light on Starfield's 1900 K and the fill lights near 2700 K. A
lighting.json value equal to an older default (LIGHT_POWER 4) is updated on export; hand edits stay. A plugin change: a
full build. Candles, -CandleStyle skyrim (10:33): small teardrop flames (no comment yet).
Owner, that build (2026-11-16 10:45, full build 41 s; lights 6000 lm at 2695 K (fill) / 1902 K (fire), so the
temperature shift works): the inn "very flickery and incredibly dark". Two of my mistakes: LGT_Fire_Cauldron's falloff
exponent is 2 where every Riverwood Skyrim light has 1 (the light dies off much faster), and Skyrim's flicker was
written over the base's (period 0.33 s, and its movement 2 - 16 in Skyrim units taken as metres). Now LIGHT_FALLOFF
skyrim (Skyrim's falloff exponent), LIGHT_FLICKER template (Starfield's own fire flicker kept; in skyrim mode the
movement is converted to metres), LIGHT_POWER 2 (8000 lm, as before the change). The build log's light lines now show
falloff and flicker. Also seen: one inn light is 65.7 m at 64000 lm (colour 247,244,242: a Skyrim fill light with a
huge radius, clamped at 16x).
Owner, that build (10:53): "the flickering is still too much, it's controlling too much of the lighting itself, going
from dark to light ... as opposed to being a subtle flicker. It's also slightly still too dark". The base's flicker
(effect sequence, amplitude 1.33: made for a candle's own small light) swings the whole room. Now LIGHT_FLICKER subtle:
the base's EffectSequenceComponent is removed and the plain flicker (FlickerEffect Flicker, as LGT_MemorialFire) runs
at LIGHT_FLICKER_INTENSITY 0.15 every LIGHT_FLICKER_PERIOD 0.5 s, no movement; LIGHT_POWER 2.5 (10000 lm). Unresolved:
the scale of FlickerIntensityAmplitude (vanilla values 0.8 - 1.33); the light lines print it with the flicker effect and
the component count.
Owner, that build (11:05, Faendal's house): flicker no longer commented on; "let's tone it back down, the light seems
very bright right at the source" (the fireplace's back wall and the wall behind the bedside candle) -> LIGHT_POWER 2
(8000 lm). The hot spots are inverse-square falloff next to a wall (Skyrim's lights fall off over their radius instead);
if they stay, next is a softer source (Starfield's area / source-radius fields) rather than less power.
Owner (2026-11-16 11:06): "that's better, let's table this for now" - interior lighting parked at these defaults
(LGT_Fire_Cauldron base, 8000 lm, 95 mired warmer, subtle flicker, Skyrim falloff). Flames settled for now: hearths
`layered` (now riverwood_doors' default -FlameStyle and make_skyrim_objects' --flame-style default), candles `skyrim`
(the default). Open when lighting returns: hot spots next to walls (softer source), the inn's 65.7 m / 64000 lm fill
light, the cell ambient (45,48,48, neutral).

## Candles, soft style (2026-11-21, owner: "the candles just look very low quality", two crops)
Seen: a small hard-edged, pixelated sliver over the wick, no glow. Cause (verified from flame_textures, 2026-11-15):
Skyrim's CandleFlame01 is 128 x 128 with 2 x 2 frames, so a flame is 64 px stretched over the card, stepped at 12 fps,
and the glow (CandleGlow01) was left out; Starfield's candle flipbook draws a thin streak ("a line of fire", 11-16).
Now `--candle-style soft`, the default (make_skyrim_objects, riverwood_doors -CandleStyle): our own flame, drawn at
build time by skyrimfire.procedural_flame_atlas (no game asset): 4 x 4 frames of 128 x 256 px, a teardrop (half width
sqrt(y)(1 - y)^0.9, widest a third up), white-yellow core, yellow body, orange rim, a faint blue foot, the tip swaying
and the height breathing through one loop, a soft round halo (SOFT_HALO 0.3) that is gone before the card's edges;
colour BC7 sRGB + opacity BC4 on the effect template, flipbook 16 fps on its timer, the candle flicker as before. Cards:
Skyrim's centres, SOFT_CARD (2.2 x 1.6) x larger, the flame drawn in the middle at SOFT_FLAME_SCALE 1.15 x Skyrim's.
A flame-only change: -AssetsOnly redoes the candles. Unverified in game.
Owner in game, soft v1 (2026-11-21 11:07, five crops): smooth, no longer pixelated, but "just looks low quality",
"could stand to be a little warmer", "sometimes like, transparent"; from above (into a horn candle) only a faint
streak. Cause of the transparency (verified, the owner's flame_probe3: FiresGeneric_Sm_01_14x14.mat's
EffectSettingsComponent = BlendingMode SourceSoftAdditive, SoftEffect true, SoftFalloffDepth 0.35; flame_probe2:
Starfield's FireCandleFlame.mat has only EmissiveOnlyEffect + VertexColorBlend): a soft effect fades where the scene
behind it is closer than SoftFalloffDepth, and 35 cm is ten times a candle flame - the wax under it seen from above, the
horn's inside, a wall behind the candle all thinned it. Soft v2: SoftFalloffDepth 0.01 (effect_material soft_depth;
SOFT_FALLOFF_DEPTH_M) for the soft candle only; warmer colours (SOFT_COLOURS: core 1.0 / 0.85 / 0.55 instead of
near-white, orange rim), a softer edge, a see-through foot (the lower quarter at about 55 % opacity), halo 0.35. The
look ("low quality") is a supported hypothesis: the white core and the faded body read as a flat sticker; to check in
game. Still crossed vertical cards: from straight above the flame is thin (Starfield's own candle is a 3-D mesh).
Owner in game, soft v2 (2026-11-21 11:40): "the color is better, but idk its like i can see pixels". At pixel scale
(verified from the screenshot): each flame about 12 px wide, all one flat clipped white with a one-pixel step to the
dark and pink pixels on the rim. Soft v3: (1) pink - the blue foot mixed with the orange rim gave magenta, the only
texels with more blue than green: the blue is gone (test: no such texel); (2) blown out - ExposureOffset 8 (the candle
emittance) is far over the scene; supported hypothesis that it is in stops, the soft candle now takes
SOFT_EXPOSURE_OFFSET 5 (8x dimmer if so), with `-CandleExposure` / `--candle-exposure` to try others in a flame-only
build. With the inside no longer clipped, the flame's soft edge (a few pixels at this size) should show.
Owner at 5 (2026-11-21 11:52): "looks better, but its awfully white" - measured on the crop: 217 of 447 flame pixels at
240+ in all channels (mean 247 / 238 / 204). Soft v4: SOFT_EXPOSURE_OFFSET 3, core 1.0 / 0.80 / 0.45.

## Electrical buzz (2026-11-21, owner: "an ambient electrical buzz i hear, cant trace it")
Supported hypothesis: a looping sound carried by a copied Starfield record. Furniture copies keep the template's
LoopingSound (ALSH: Starfield's workbenches hum; ours copy WorkbenchIndustrial for the enchanting table, WorkbenchChem
for alchemy, NPCWelder for the forge, NPCRepairImpactWrench for the grindstone), and light copies their SoundReference
(LLSH). Skyrim's furniture and lights make no sound of their own, so PluginSpike now clears both on every copy and the
build log names the templates it took sounds off ("looping sounds removed from copies of: ..."). A plugin change: a
full build. Unverified: that it was one of these.
Owner's build (2026-11-21 10:59): "looping sounds removed from copies of: furniture WorkbenchChem, furniture
WorkbenchIndustrial" (the alchemy tables' and the enchanting table's templates; no light carried one).
Owner in game (2026-11-21 11:07): "buzzing sound is gone" - verified: the workbench templates' looping sounds.

