# Skyrim's walled cities as their own overlays

Branch `skyrim/cities` (on `skyrim/ground-textures`). Status: **built and tested offline on synthetic data only
(4 tests: parent terrain, local frame, objects, ground textures); not run on the real Skyrim.esm, not in game.**

## What a city is in Skyrim, and how it is read here
Whiterun, Solitude, Windhelm, Markarth and Riften are separate small worldspaces behind their gates (load doors), laid
out in Tamriel's coordinates: a city's cells sit where the city stands on the Tamriel map. Whether a city carries its
own LAND or uses its parent's (WRLD WNAM = parent, PNAM bit 0x1 "Use Land Data") is read from the file, not assumed:

* own LAND: used as is;
* no LAND and a parent: the parent's LAND under the city's cells, **plus a ring of 4 parent cells around it**, so the
  ground outside the walls is Tamriel's real terrain (the overlay is still sized by the city's own cells);
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

## Limits
* **One experiment installed at a time.** Every Mars plugin overrides MarsPlanetData (as every terrain experiment so
  far), so a city and Tamriel cannot be installed together yet; that needs one plugin holding several overlays and
  one registration listing them all (TerrainOverlays supports several overlays; `objects.json` holds one world).
* **No gates.** Skyrim enters a city through load doors; doors here are plain statics and lead nowhere (the FO4
  project's load-door work, PR #50, is not on this branch). Reach a city with `coc`.
* Interiors (houses, Dragonsreach, the palaces) are interior cells, not part of these worldspaces: not converted.
