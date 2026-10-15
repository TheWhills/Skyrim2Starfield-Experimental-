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
- **Doors do nothing:** expected, load doors are scenery until door linking.

Owner's first run with translated lights (Test A): it built and set every field (no light notes), but the inn got
darker. Two of my mistakes: several light references carry an XRDS of ~10 units, which became a 0.14 m light with a
quarter of the lumens (XRDS under 64 units is now ignored, `ref_radius` keeps the raw value), and lights smaller than the
8 m / 2000 lm template had their lumens scaled down (now never below the template; only bigger lights get more).
