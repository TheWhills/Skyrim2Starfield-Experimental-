# Exterior navmesh: Skyrim's navmeshes on the planet's Tamriel (2026-11-08)

Owner: "Can we convert the exterior mesh, and build a way to compare those meshes between Skyrim and how it appears
in Starfield". NPCs only walk on navmesh; outdoor schedules (Riverwood's villagers) need it. Interiors already carry
Skyrim's navmeshes (docs/interior/skyrim-interiors.md "Navmesh"); this does the same outdoors, without rebuilding the
installed exterior: the navmeshes go into FO4Port.esm, in overrides of the exterior's cells, like the exterior doors.

## Pieces
* `src/fo4sf/exteriornavmesh.py`: read Skyrim's exterior NAVM records (`read_skyrim`), move them into the exterior's
  frame (`frame_shift`: Skyrim units - origin_cw_m * 70, z + height_offset_m * 70; the installed exterior has origin
  [0, 0] and +385 m), split them at Starfield's 100 m cells (`split_to_cells`), rebuild search grids (`build_grid`),
  and the checks (`edge_link_problems`, `outside_cell`, `nearest_offsets`, `read_starfield_exterior`).
* `scripts/terrain/make_skyrim_navmesh.py export` -> `exterior_navmesh.json` (+ `export_report.json`);
  `compare` -> `compare.json` + `compare.html`.
* PluginSpike `EXTERIOR_NAVMESH=<exterior_navmesh.json>` (with `EXTERIOR_DIR`): each navmesh into an override of its
  exterior cell, parent = world + cell grid; door links -> the load doors made from `EXTERIOR_DOORS`, other door links
  dropped. `source_map.json` gets each navmesh key.
* `scripts/interior/navmesh_survey.py --exterior`: vanilla Starfield exterior navmeshes -> `navmesh_survey_exterior.json`
  and `navmesh_defaults_exterior.json` (fields Skyrim lacks, triangle height outdoors, grid order).
* Owner: `tools\owner\riverwood_doors.ps1 -Find "^Riverwood" -Navmesh` (survey once, export, build, compare, install).

## Why split
A Skyrim cell is 58.5 m, a Starfield cell 100 m, so most Skyrim navmeshes straddle 2-4 Starfield cells. A navmesh
belongs to one cell (its parent), and the game presumably looks for an actor's triangle in the navmeshes of the cell
it stands in (supported, not verified for Starfield). Each Starfield cell therefore gets the triangles whose centre
lies in it; no triangle is cut, so triangles overhang the cell line by under a triangle. Inner edges that now join two
pieces become a pair of edge links, as Skyrim joins its own per-cell navmeshes; links to navmeshes outside the region
are cut (open edge); a navmesh wholly inside one Starfield cell is kept as it is, with Skyrim's own grid.
`--no-split` keeps every navmesh whole (A/B). The survey's `outside_own_cell` says whether vanilla Starfield navmeshes
stay inside their cell.

## Unresolved (the survey and compare answer most of it on the PC)
* Grid order (cell index = row * divisor + column, rows along y or x): `grid_agreement` against vanilla grids; the
  export takes the survey's `grid_order` (default "yx").
* Parent grid order: NVNM stores Grid Y then Grid X (xEdit SF1 / TES5); Mutagen's `Coordinates` is read in stream
  order, so PluginSpike writes `(Y, X)`. `compare` reads the written bytes back against the cell's XCLC, the survey
  checks vanilla navmeshes (`parent_grid_vs_xclc`).
* Triangle height outdoors (interiors: the clear space above, median 4.63 m; FLT_MAX = nothing above): the survey's
  median for exterior navmeshes, else FLT_MAX.
* NAVI (navmesh info map): not written, as for the interiors. If NPCs walk within a cell but will not path across
  cells, NAVI is the next thing to try.
* In game: a spawned NPC told to walk (`<ref>.pathtoreference player 1`) across Riverwood, over a cell line.

## What compare reports
Navmesh / triangle counts (Skyrim, exported, in the plugin), vertex offsets between Skyrim's navmesh (moved into the
frame) and ours read back from FO4Port.esm, parent cell vs XCLC, triangles outside their parent cell (ours and Skyrim's
with its 58.5 m cell), edge links whose leaving edge does not lie on the triangle they name (ours and Skyrim's), door
links, and the navmesh's height above the terrain (Skyrim's LAND, + height_offset_m for ours: the exterior's BTD is
built from the same heights). compare.html: top-down, toggles for ours (one colour per navmesh), Skyrim's outlines,
door triangles, broken links (red), the 100 m Starfield and 58.5 m Skyrim cell lines.
