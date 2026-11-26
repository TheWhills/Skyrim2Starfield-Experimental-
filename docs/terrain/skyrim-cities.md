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

### In game: the market's ground (owner, 2026-11-25)
The owner's screenshots show Whiterun loaded on Nirn (verified: the city world loads on Tamriel's planet; how the owner
got in was not stated). "Some of the ground is not the right level, or in the wrong spot, mostly near the market
district": earth and moss lying over the market's cobbles and filling a stair in the wall.
* **Not the land** (verified, Skyrim.esm export vs LAND): inside the walls Whiterun's flora, rocks and markers stand a
  median 1.1 - 7 m above Tamriel's land (cells 5,-2: +163 units; 6,-1: +279; 7,-1: +331), and the city's own LAND in the
  7 cells equals Tamriel's in 5 of them. Update.esm overrides Tamriel's LAND there but changes only cells (4,-1) and
  (5,-3), by at most 56 units (0.8 m). Whiterun's floor is its 43 ground meshes (Architecture\WhiteRun\WRTerrain:
  WRMainRoadMarket, WRMainRoadPlains, WRTerWind01, the house bases ...), converted and placed; the land lies under them.
* **The cause** (verified in the NIFs): those meshes are layered. WRMainRoadMarket has a stone floor ':29'
  (WRStoneFloor02, opaque) and a grass layer ':15' (WRFieldGrass01) on the same 13.7 x 16.6 m footprint, alpha-tested
  (threshold 128) with Shader Flags 1 Vertex_Alpha: Skyrim draws the grass only where texture alpha x vertex alpha
  passes, i.e. where the vertex alpha is painted high. The converter's cutout material saw the texture's alpha only, so
  the whole grass layer drew over the stone. Geometry check: Skyrim draws 37.6 % of WRMainRoadMarket:15's area (before
  the texture's own alpha), 28 % of the moss on WRStairsWater01's steps, 73 - 75 % of WRMainRoadPlains' grass and moss.
  Same pattern on the walls' moss (WRMossAlpha01), the Rocks01 overlays of rock piles (threshold 34), hay: 105 shapes in
  Whiterun's 309 models have it (6 more are alpha-blended decals with vertex alpha, not handled).
* **The fix** (`skyrimconvert._vertex_alpha_cut`, `clip_vertex_alpha`, `vertex_alpha_bands`; tests/test_vertex_alpha.py):
  such a shape is cut along its vertex alpha. Where the vertex alpha is under threshold / 255 nothing is kept (Skyrim
  draws nothing there whatever the texture); the rest is split into 4 bands of vertex alpha, each with its own cutout
  material whose threshold is raised to make up for its vertex alpha (texture alpha >= threshold / vertex alpha, at
  the band's middle; same textures, `<stem>_va<threshold>.mat`). A texture without alpha keeps its opaque material and
  is only cut. Geometry only: vanilla Starfield materials can take the vertex colour in their alpha
  (AlphaBlenderSettings UseVertexColor / VertexColorChannel Alpha, e.g. DecalLabels01.mat, LeafDebrisPile01.mat), but
  how that combines with an opacity map is unverified, while the cut is checkable offline.
  Left alone: shapes with Shader Flags 2 Tree_Anim (shrubs and tree leaves with a BSLeafAnimNode), whose vertex alpha
  is the sway weight (supported hypothesis: WRTempleTree02:1 has vertex alpha 0 everywhere, TundraShrub01's leaves a mean
  of 21 against threshold 180, and both are full in Skyrim).
* The converter applies to every Skyrim static, so Tamriel's rocks, walls and hay get it on Tamriel's next convert. Until
  then, a fixed model that Tamriel's archives also hold under the same path (Whiterun's walls, rock piles) goes into the
  city's archive, which loads after Tamriel's (`deploy_skyrim_city.pack_plan` now compares contents, not only paths):
  both worlds show the fixed model while the city is installed.
* **Rebuilt and reinstalled** (2026-11-26, `cities.ps1 -NoInstall` then `deploy_skyrim_city.py` uninstall / install,
  Starfield closed): 315 of 319 models in 107 s, 94 shapes cut (52 band materials); WRMainRoadMarket's grass is now 4
  parts with thresholds 230 / 187 / 158 / 137 over the uncut stone floor. Offline check as before (only "origins on the
  terrain", expected). City archive 1,406 files, 158 MB (was 977, 152 MB), of which 44 replace an older copy in
  Tamriel's archives; 1,239 files (538 MB) left to Tamriel's. **In game unverified.**

### In game, second look (owner, 2026-11-26)
"This patch on land where the road should be, also spikes from when it's in the civil war state that we don't need.
Bridge is the wrong direction near Dragonsreach." Three causes, all in Skyrim's data:
* **Land over the roads: Skyrim hides it** (verified): WhiterunWorld's CELL XCLC carries land hide flags (third u32,
  bits 0-3 = quadrants SW, SE, NW, NE): all four quadrants of (5,-2) and (6,-1), parts of (5,-3), (5,-1), (6,-3),
  (6,-2), (7,-1); Tamriel's cells have none. Skyrim draws no land there; the floor meshes are the ground. The cut terrain
  drew Tamriel's land, which came up through the roads. Now `make_skyrim_overlay.py --terrain-from` lowers the cut land
  under those 18 quadrants by `--hidden-land-depth` (15 m; 25,163 samples), every other sample stays Tamriel's exactly.
  Bit order: supported hypothesis (LAND's own quadrant order; 920 of the 1,229 references floating > 1 m above the land
  fall in hidden quadrants this way, 717 / 767 in the other orders). Where Skyrim has no mesh over a hidden quadrant it
  shows a hole; here that is a 15 m pit.
* **Civil-war spikes: enable parents** (verified): the Battle for Whiterun's barricades (StockadeBarricade01Activator),
  rubble, smoke and closed shutters hang on XMarker 0376E0 (Initially Disabled); the destroyed Grey-Mane house on
  0FC90B, Jorrvaskr's funeral on 0BBCEA, repair scaffolding on 0FC8F1, the dead Gildergreen on 046284. Selection used
  each reference's own flag only, so all were placed as if enabled. `skyrimrefs.disabled_by_parent` resolves the chain
  (child on = parent on, or off with "opposite"); `make_skyrim_objects.py select` leaves those out (skip reason
  `disabled_by_parent`: 174 in Whiterun). The market stalls on 0376E0 with "opposite" stay. Applies to the exterior's
  next build too.
* **Bridge turned: the root node's transform** (verified): WRCastleBridge01.nif's BSFadeNode turns it 90 deg about Z.
  Skyrim ignores a placed model's root transform: without the turn the bridge lies on the line to Dragonsreach's door
  and meets WRCastleEntrance01 within 1 unit; with it, it lies across, 167 units off. The converter clears root
  transforms on every placed model (`skyrimnif.clear_root_transform`; worn models keep theirs): 22 of Whiterun's
  models, among them the house bases WRBreezeBase and WRDrunkenHuntsmanBase (ground pieces turned 90 / 60 deg),
  benches, a sign, food.
Rebuilt and reinstalled 2026-11-26 (Starfield closed): 283 models, 864 references; archive 1,513 files, 159 MB (57
newer than Tamriel's copy). **In game unverified.**

### Water: streams, pools, troughs (2026-11-26)
Owner: "It all looks right now" (the second look's fixes, verified in game); the streams are white, as Riverwood's
troughs. **How Skyrim does it** (verified, Skyrim.esm and the NIFs): the city's water is Activators whose WNAM names a
water type (WRWaterPool01 074EEA, WRStairsStreamLACT and WRTreeCircleWater01ACT 085FC8, HorseTrough01 0F762D); their
models hold a BSWaterShaderProperty shape for the surface (9 such shapes in Whiterun's models), white foam as effect
shapes (FXWhiteWater01) on top; two plain water planes Water1024WR (Water\Water1024.nif) were skipped by selection. The
converter had no material for the water shader: the neutral one, white.
**Now** (`skyrimconvert`: `is_water_shader`, `water_squares`; `make_skyrim_objects.model_water`):
* a FLAT water shape (z range <= 24 units) is not drawn; its footprint is packed with squares (grid of 1/12 of its
  smaller side, 4..24 units; squares only where the footprint is), and stage places Starfield's own placeable water on
  each square of each reference: Water16mClearLake 039FD6 (the piece Tamriel's rivers use, verified in game 2026-10-18)
  scaled to the square, at Skyrim's level, turned with the reference. Coverage: WRWaterPool01 96 %, the stream steps
  98 - 99 %, horse trough and Water1024 100 %, the Gildergreen's ring 83 %, the stream exit 73 % (curved edges under
  stone). Water1024WR planes are now selected and converted the same way (Skyrim only; FO4 keeps skipping them).
* a SLOPED one (WRGreatHousePlatform01River01, WRMainRoadPlainsRiver01, WRStairsWater01River01: 3 - 6 m drops) keeps
  Skyrim's mesh with vanilla `Materials\Effects\Environmental\Waterfall_Outside_02.mat` (2LayerEffect: foam + warp
  normal) referenced as it is (as hair cards use vanilla hair materials): **a probe**, look unverified; purely visual.
* a model that is only water (pool, ring) gets no collision. Foam effect shapes stay out (non-fire effects are not
  translated).
Whiterun: 422 water pieces on 8 references; installed 2026-11-26. **In game unverified**: tiny scales (a trough's
pieces are 0.15 - 0.5 m: scale 0.01 - 0.03), the look of the sloped probe. Riverwood's troughs: their fixed model ships
in the city archive (no more white) but their water pieces come with the exterior's next build.

### Water, second way: each Skyrim water surface on a copy of the vanilla water activator (2026-11-26)
Owner's test of the squares: water shows, but "the end has a different coloration that only goes away when you're
right next to it", the Gildergreen's water looks different near and far "and has these weird square / diamond
issues", no waterfall, and Starfield's water looks green in the sun (wanted: blue, later).
* **Why the squares failed** (supported hypothesis): every piece is its own water object with the activator's LOD
  component (ACTI 039FD6 REFL: BGSLodOwnerComponent, template "Reduction", base distance 40); far pieces draw their
  distant look (flat green), and scaled-down pieces (the ring's 281 squares, 0.3 - 2 m) switch to it almost at once.
* **What vanilla water is** (verified: Starfield - Meshes01.ba2, Starfield.esm): `Water\Water16m.nif` is a plane
  BSGeometry with NiIntegerExtraData "MaterialID" 0xA456F487 and `Materials\Water\WaterPlaceholder.mat` (+ a physics
  body); the look comes from the activator's water type WTFM (01C0CC WaterClearLake), not from the mesh.
* **Now:** the converter writes each model's water shapes as their own model `<model>_water.nif` (Skyrim's exact
  surfaces, WaterPlaceholder.mat, same MaterialID, no collision: no swimming), and stage places it with every
  reference of its model as a copy of Water16mClearLake (TerrainOverlays `water_template`: WTFM, LOD component,
  keywords kept; our model and bounds; `--water-type <WATR hex>` for another water type). Whiterun: 11 references of 10
  water models instead of 422 squares. The sloped streams go into the water models too (a probe: water on a sloped mesh
  is unverified; the vanilla Waterfall_Outside_02.mat probe drew nothing in game). `stage --water-squares` keeps the
  first way.
* **Waterfalls** are a separate thing: Skyrim's FXWaterfall* / FXWaterfallSkirtSlope effect meshes (BSEffectShader,
  FXfluidTile01 scrolling, vertex-alpha fades, mist particles), skipped as effect meshes; they need an effect material
  of their own (next).
* **Blue water:** the water type decides the colour; Starfield.esm has 15 WATR (WaterClear 000018, WaterClearLake
  01C0CC, WaterOceanClear 0560CF, WaterOceanDark 0560D0, WaterOceanAlgae 0560D1, WaterClearSterile 062BE5, ...). A
  bluer look is either another of them (`--water-type`) or our own WATR cloned with other colours.
Installed 2026-11-26. **In game unverified.**

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
