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
  `--lighting-template` / `--light-merge-m` override both. Next: translate the Skyrim cell's XCLL ambient / directional
  colours and each LIGH's radius / colour into the choice of template and light bases.
- **The fire pit showed as a big blue / purple crystal.** `inspect_nif.py` named it: `clutter\woodfires\
  fireplacewood01burning.nif` shape `Plane03`, the heat-haze plane above the fire, a BSLightingShaderProperty with
  Shader Flags 1 `82418309` (Refraction 0x8000 + Fire_Refraction 0x10000) and `effects\VaporTileNormal_n.dds` in the
  diffuse slot. The converter now skips refraction shapes and shapes whose diffuse is a normal map, as it skips
  effect shaders. The flames (`Flames:0/1`, effect shader on `FXFireAtlas04.dds`), the glow and the particle sparks
  are effect shaders, so the fire is logs + ash only until effects are translated (a Starfield fire FX placed at the
  same spot is the likely route). Candles have no flame shapes of their own (their flames are separate effects).
- **Doors do nothing:** expected, load doors are scenery until door linking.
