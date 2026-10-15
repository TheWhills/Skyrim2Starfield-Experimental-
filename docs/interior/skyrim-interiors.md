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
