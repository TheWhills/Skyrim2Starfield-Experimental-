# Skyrim's walled cities as their own overlays

Status (2026-11-25): **Whiterun built from the real Skyrim.esm and installed next to the installed Tamriel, with its
gate linked both ways; not yet seen in game** (the owner tests). One command: `tools\owner\cities.ps1`. The section
"Whiterun through its gate (2026-11-25)" below is the current state; the older sections describe the pieces.

## What a city is in Skyrim, and how it is read here
Whiterun, Solitude, Windhelm, Markarth and Riften are separate small worldspaces behind their gates (load doors), laid
out in Tamriel's coordinates: a city's cells sit where the city stands on the Tamriel map. Whether a city carries its
own LAND or uses its parent's (WRLD WNAM = parent, PNAM bit 0x1 "Use Land Data") is read from the file, not assumed:

* own LAND and no "Use Land Data" flag (Markarth): used as is;
* a parent and the flag, or no LAND and a parent: the parent's LAND under the city's cells, **plus a ring of 4 parent
  cells around it**, so the ground outside the walls is Tamriel's real terrain (the overlay is still sized by the city's
  own cells). **Correction (2026-11-25):** a city with the flag but a few LAND records of its own (Whiterun 7, Solitude
  20, Riften 12, Windhelm 2) used to take only those, so Whiterun's overlay was sized to 7 cells; now the flag wins;
* neither: an error naming the worldspace.

`make_skyrim_overlay.py worlds --skyrim <Skyrim.esm>` lists every worldspace with its parent, the "use parent land"
flag, cells, LAND count and extent: the real names to build from.

## The local frame
Tamriel's overlay is centred on Skyrim's origin (local = Skyrim position / 70). A city far from the origin (Markarth,
Solitude) would need a huge, mostly empty overlay that way, so `--frame local` centres the overlay on the city: the
tile's origin (`origin_cw_m`, whole 100 m cells) is subtracted from every position. Terrain heights stay absolute.
`make_skyrim_objects.py` reads the origin from the overlay's params and shifts the city's objects the same way (the
offline frame check still compares each object with the terrain under it). Tamriel builds are unchanged (origin 0).

City overlays are at least 5 x 5 cells (the outer cell ring blends into Mars), and the in-game probe plan uses city
distances (25-200 m, kept 50 m inside the edge) instead of Tamriel's (up to 3 km, 200 m inside).

Each city gets its own names (`SKY_WhiterunWorld`, `SkyrimTerrainWhiterunWorld.esm` + `_Mars.esm`, display name
"Whiterun"), so it never shares a plugin, worldspace or archive name with the Tamriel build. Ground textures
(`--land-textures`) are read from the worldspace the terrain comes from (Tamriel for a city on its parent's land).

## Running it
    python scripts\terrain\make_skyrim_overlay.py worlds --skyrim "<Skyrim SE>\Data\Skyrim.esm"
    python scripts\terrain\make_skyrim_overlay.py build --skyrim "<...>\Skyrim.esm" --world-edid WhiterunWorld --frame local ^
        --sf-data "<Starfield>\Data" --out C:\Modding\staging\skyrim_whiterun [--land-textures]
    python scripts\terrain\make_skyrim_objects.py export --skyrim "<...>\Skyrim.esm" --world-edid WhiterunWorld --work C:\Modding\work\whiterun
    ... select / convert / stage / check as in skyrim-objects.md, with --terrain C:\Modding\staging\skyrim_whiterun

The arrival defaults to the city's centre (`--arrival <cell EditorID or X,Y>` to choose).

## Next to the installed Tamriel (2026-11-10)
Owner: "get the worldspace for the cities like Whiterun, Solitude, Windhelm" and chose separate spaces, like Skyrim.
Offline only so far (synthetic tests), not run:

* `make_skyrim_overlay.py build --like <Tamriel staging>` reuses that build's options (its `build_command.txt`: height
  offset, ground textures, water, planet biome / climate / location parent) minus the ones that pick the land and its
  names (`LIKE_DROP`); with `--no-mars` the city writes no planet plugin of its own (the planet options still set its
  world's biome / climate).
* `scripts/terrain/register_worlds.py`: ONE registration plugin (`SkyrimWorlds_Register.esm`, loads last) overriding
  the main build's planet record (Nirn, in SkyrimTerrainTamriel_Mars.esm) with Tamriel's CNAM entry kept and one per
  city appended (Tamriel's latitude, longitude + 0.02 rad per city: about 150 km apart on the 7,484 km Nirn, so no
  overlap), and each city's location parented to the planet's surface location.
* `tools\owner\cities.ps1`: per city terrain (--like Tamriel, --no-mars), export / select / convert / stage / check,
  then register_worlds and a copy into the MO2 mod folder "S2S Skyrim Cities". Reach a city with `coc` (printed).
  (Replaced 2026-11-25: never run in that form; `--like C:\Modding\staging\skyrim_all` would have stopped, that folder
  has no build_command.txt. Now: terrain cut from the installed Tamriel, gates, install into Data; section below.)

Next: gates (Tamriel <-> city load doors, both ways: PluginSpike's exterior-door override for two exteriors), the
cities' interiors (houses, Dragonsreach: the interior batch with `--exterior` pointed at the city), their navmesh.

## Limits
* Gates: linked since 2026-11-25 (section above), unverified in game; the planet registration of several worlds is unverified in game (vanilla Mars
  lists 10 master worldspaces, so the record allows it).
* Interiors (houses, Dragonsreach, the palaces) are interior cells, not part of these worldspaces: not converted.

## Whiterun through its gate (2026-11-25)
Owner: "Whiterun first ... loads in game from Tamriel through its gate, with its terrain, objects and the exterior's
current conversions ..., installed reversibly". Built, installed and checked offline; **in game unverified**.

### How a city reaches the player: decision
Its own overlay world behind its gate, as Skyrim does and as the owner chose on 2026-11-10 (docs/ai/decisions.md).
Evidence against the other way (the city's objects merged into SKY_Tamriel): Tamriel's own cells at Whiterun hold the
walls, the main gate and **LOD stand-ins of the city** (WRBreezehome01LOD, WRJorvaskr01LOD, WRCloudDistrictTerrainLOD,
WRPlainsDistrictTerrainLOD ...: 6,102 Tamriel references in cells 2..13 x -5..2, export of Skyrim.esm); only 109 of
WhiterunWorld's 1,804 references have an identical twin there. Merging would mean removing stand-ins and duplicates by
hand per city; the overlay keeps Skyrim's own split. What blocked it before, and how each is handled:
* **Only one terrain experiment at a time** (every *_Mars plugin overrides MarsPlanetData): the city has no planet plugin
  (`--no-mars`); SkyrimWorlds_Register.esm adds it to Tamriel's planet Nirn (PNDT CNAM entry, 150 km east) instead.
* **One archive per plugin under 4 GiB** (Tamriel's planet-plugin archive is at 3.97 GB): the city has its own plugin,
  hence its own archive, and it leaves out every file Tamriel's installed archives already hold (Whiterun: 977 files,
  152 MB packed; 1,283 files, 541 MB, already in Tamriel's).
* **FO4Port.esm load doors** (it overrides the exterior and its FormIDs must stay stable): nothing of the exterior is
  rebuilt; the gates live in their own plugin, the exterior is patched only in place (one reference, same size).

### What was built
1. **Terrain cut from the installed Tamriel** (`make_skyrim_overlay.py build --terrain-from C:\Modding\staging\skyrim_all`,
   `fo4sf.btd.crop`): Whiterun stands on Tamriel's land (the flag), so its overlay's terrain file is the same cells of
   Tamriel's installed terrain file: heights, texture layers, the smooth blend, the 2.44 m tiling and half-strength
   normal maps (global materials), the grass slots. Verified offline: the cut equals Tamriel's file byte for byte
   (`cut == source slice: True`); against the city's own rebuild from Skyrim.esm it differs by a median 5 mm and only in
   the outer west / east cell columns (the blend ring, where the old build eased toward default land). Every LTEX in
   Tamriel's table is a Starfield.esm record Tamriel's plugin overrides (62 entries, all 00xxxxxx), so the city plugin
   writes no LTEX overrides of its own (it would otherwise override the same vanilla records with other choices).
   Overlay: 18 x 18 cells (1.8 km), shared-frame cells x -5..12, y -8..9, origin (400, 100) m.
2. **Objects** (export / select / convert / stage, `C:\Modding\work\city_whiterunworld`): 319 models, 315 converted in
   112 s (3 without geometry, 1 alternate-texture mismatch), 272 with native collision; 978 references, 315 STAT. The
   current converter applies Skyrim's specular and the alternate textures as their own models; snow bake found 0 snowy
   statics in Whiterun. Offline check: everything ok except "object origins sit on the terrain" (median 3.3 m): Whiterun
   stands on terrace meshes (WRTer*), so its trees and rocks are 1.7 - 7 m above the land even in cells without own LAND.
3. **Gates** (`register_worlds.py --skyrim`, `fo4sf.worldgates`): Skyrim pairs Whiterun's gate Tamriel 01B1F1 <->
   WhiterunWorld 01B1F3 (both WRDoorMainGate01, persistent, XTEL to each other; the only pair). As Riverwood's doors
   (verified 2026-11-08): two NEW persistent load doors (DOOR with the static's model, FO4Port.esm's layout) at the
   statics' places, each in an override of its world's persistent cell, XTEL to the other (landing points from
   Skyrim's XTEL in the destination's frame: 2.1 m inside the city gate facing in, 1 m outside Tamriel's facing out).
   The city world and cell records are copied with the city plugin's own FormIDs remapped to its master index (block
   BNAM, location XLCN, the large-reference grid RNAM); Tamriel's from the planet plugin keep theirs.
4. **Install** (`scripts\deploy_skyrim_city.py`, Data\SkyrimCities.deploy.json): the city plugin, its archive and the
   register plugin into Starfield\Data; the two gate statics hidden in place (Initially Disabled, sunk 1000 m, as
   apply_ref_overrides.py: another plugin's override of a temporary exterior reference did not take, 2026-11-14).
   Verified offline: install, uninstall and install again; after uninstall the Tamriel plugin's SHA-256 equals the
   pre-install one (its backup with FO4Port.esm's hides reapplied: e1879f01d348f2db...), Plugins.txt as before.
Also fixed: register_worlds.py wrote the planet's master-world list over **both** CNAM fields of Nirn's PNDT (the second
is 1 byte in another component); now only the list.

### Unverified (in game)
* that the load doors teleport between two of our overlay worlds (interior <-> exterior verified; exterior <-> exterior
  not tried), and the landing heights;
* that a second overlay world on Nirn loads (vanilla planets list up to 10 master worlds), its sky / weather / biome
  (Tamriel's), the planet's own ground beyond the city's 1.8 km (150 km from Tamriel: its procedural heights may not
  meet the overlay's edge), grass (Nirn's biome map at that spot);
* which ground Skyrim draws in the 7 own-LAND cells (supported hypothesis: the parent's, from the flag; and in cell
  (4, -1) Whiterun's wall pieces stand 2.0 - 3.9 m above Tamriel's land but 13 - 16 m above the city's own LAND);
* `coc SKY_WhiterunWorldCell5M2Spawn` (Plains District) may land under a terrace mesh: the COC marker sits 2 m above
  the land, not above the city's floor meshes. The gate is the way in.
* Whiterun's interiors (Dragonsreach, houses), NPCs, navmesh: not built; their doors are statics.

### The other cities (plan, with numbers from Skyrim.esm)
| City | Land | Own LAND | Gate pairs (Skyrim) | Plan |
|---|---|---|---|---|
| Solitude | Tamriel's (flag) | 20, ignored | 3 (2 x SDoorFrontGate, MineDoor01Load) | as Whiterun |
| Windhelm | Tamriel's (flag) | 2, ignored | 2 (WHDoorFrontGate) | as Whiterun |
| Riften | Tamriel's (flag) | 12, ignored | 4 (RTMainGate01 x 2, RiftenDoorLoad01 x 2) | as Whiterun |
| Markarth | its own (no flag) | 139 | 1 (DweDoorLarge01Load) | own heights: not a cut |

`tools\owner\cities.ps1 -Cities WhiterunWorld,SolitudeWorld,WindhelmWorld,RiftenWorld` builds them all (one register
plugin for all). Their extents include stray empty cells (Riften x -1..44, 2.7 km wide), so their overlays are larger
than the cities; harmless (more of Tamriel's land around), or pass --cells. **Markarth** differs from Tamriel's land in
129 of 139 cells (median 408 units = 5.8 m, up to 66 m), so it cannot be a cut: next is a cut of Tamriel's texture
layers with Markarth's own heights (supported hypothesis: its textures follow Tamriel's), never its own LTEX overrides.
