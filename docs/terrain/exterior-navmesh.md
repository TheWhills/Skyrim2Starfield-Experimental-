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

## What tes4skyrim found for Skyrim (owner's pointer, 2026-11-08)
bryantmh/tes4skyrim converts Oblivion's / Morrowind's pathing into Skyrim navmeshes and read the rules out of Skyrim's
pathfinder (its docs/reference/navmesh_engine_contracts.md and docs/commentary/tes5_import_navmesh.md; method only,
no code copied). What we took:
* **NAVI registration.** The pathfinder uses a navmesh only if it is listed in the Navmesh Info Map: one NAVI record in
  the master that every plugin (and DLC) overrides with entries for its own navmeshes, the game merging them. Each NVMI
  lists the navmeshes its edge links name (self excluded), its door triangles' doors, its pathing cell, a centre.
  Without it no NPC paths at all, even inside one connected navmesh. **Our interior navmeshes never had this.**
  PluginSpike now overrides Starfield.esm's NAVI (NVER and NVPP kept) with one NVMI per navmesh, interiors and exterior.
* **XNDP on load doors** (door -> the navmesh triangle in front of it): without it a load door is not a pathing node and
  an NPC never goes through it. 99 % of Skyrim's teleport doors carry it (ours: Starfield 576 of 619). Now set on every
  load door of ours that a navmesh's door triangle names.
* **The search grid**: row-major with rows along Y; a triangle is listed in every grid cell it truly overlaps (not its
  bounding box, not only its centre's cell). `build_grid` now does that.
* Cell-seam edge links are type 0 (Portal) and reciprocal; the split's seam links are Portal.
* Lookup: the game searches the navmeshes of the cell the point is in, so a navmesh's triangles belong in its cell.

## Why split
A Skyrim cell is 58.5 m, a Starfield cell 100 m, so most Skyrim navmeshes straddle 2-4 Starfield cells. A navmesh
belongs to one cell (its parent), and the game presumably looks for an actor's triangle in the navmeshes of the cell
it stands in (supported, not verified for Starfield). Each Starfield cell therefore gets the triangles whose centre
lies in it; no triangle is cut, so triangles overhang the cell line by under a triangle. Inner edges that now join two
pieces become a pair of edge links, as Skyrim joins its own per-cell navmeshes; links to navmeshes outside the region
are cut (open edge); a navmesh wholly inside one Starfield cell is kept as it is, with Skyrim's own grid.
`--no-split` keeps every navmesh whole (A/B). The survey's `outside_own_cell` says whether vanilla Starfield navmeshes
stay inside their cell.

## Measured on the owner's PC (2026-11-08, 400 vanilla exterior navmeshes, Starfield.esm + ShatteredSpace.esm NAVI)
* Parent grid is stored Y then X: 400 of 400 match their cell's XCLC (verified). Ours: 103 of 103 (compare).
* Vanilla exterior navmeshes keep every triangle centre inside their own 100 m cell (max 0.0): the split is right.
* Grid order "yx" (rows along Y): agreement 0.9998 (381 exact) against 0.5994 for "xy" (verified).
* Outdoor triangle height: the median is FLT_MAX (nothing above) (verified); vertex unknown 1, tail (12, 8).
* NAVI: Starfield.esm's 000FF1 has 56,631 entries; ShatteredSpace.esm overrides the same record with 29,270, i.e.
  its own only, so the game merges overrides (strongly supported). 79 % of vanilla NVMI end 00 00000000.
  Flags: 0x20 on 54,549 entries, exactly the ones with island data (54,549); the other 2,082 have flags 0 and no
  island, which is what we write (no island, no traversals). Vanilla also carries 590,922 precomputed traversals
  (jumps / climbs); ours have none, so converted NPCs walk only. Whether a navmesh without island data paths as well
  as one with it is unresolved (2,082 vanilla ones do without).
* Grid bounds: the vertices' bounding box except the top (max z), which is FLT_MAX ("nothing above"), in every
  sample (verified on 8 samples; 17 of 400 are whole-cell squares, the same way). The export sets the top to FLT_MAX
  and PluginSpike keeps FLT_MAX unscaled.
* Edge links whose leaving edge is not a full edge of the target triangle: Skyrim's own navmeshes have the same
  count as ours (615), so they come from Skyrim (seams that meet at T-junctions), not from the split; the check now
  measures the gap along the edge instead.
* First build: 103 navmeshes in 15 cells, 11,256 triangles, vertex offsets 0.0 m, NAVI 103 of 103, XNDP on 14 load
  doors, all pointing at a door triangle. The first NAVI tail was 0F00000000 (wrong inference in PluginSpike), fixed.

## Unresolved (the survey and compare answer most of it on the PC)
* Grid order (cell index = row * divisor + column, rows along y or x): `grid_agreement` against vanilla grids; the
  export takes the survey's `grid_order` (default "yx").
* Parent grid order: NVNM stores Grid Y then Grid X (xEdit SF1 / TES5); Mutagen's `Coordinates` is read in stream
  order, so PluginSpike writes `(Y, X)`. `compare` reads the written bytes back against the cell's XCLC, the survey
  checks vanilla navmeshes (`parent_grid_vs_xclc`).
* Triangle height outdoors (interiors: the clear space above, median 4.63 m; FLT_MAX = nothing above): the survey's
  median for exterior navmeshes, else FLT_MAX.
* NAVI merge: we override Starfield.esm's NAVI with entries for our navmeshes only, relying on the game merging the
  overrides as Skyrim's does. If Starfield took only the winning override, vanilla pathing would break while FO4Port.esm
  is loaded. The survey's `navi` section (with `--navi-esm ShatteredSpace.esm`) shows whether the DLC's own override
  carries only its own entries (then the game must merge). `$env:NAVI="off"` builds without it.
* The NVMI tail (one byte and a u32-counted array after the pathing cell) is copied from Starfield's most common one,
  read from Starfield.esm at build time.
* In game: a spawned NPC told to walk (`<ref>.pathtoreference player 1`) across Riverwood, over a cell line.

## What compare reports
Navmesh / triangle counts (Skyrim, exported, in the plugin), vertex offsets between Skyrim's navmesh (moved into the
frame) and ours read back from FO4Port.esm, parent cell vs XCLC, triangles outside their parent cell (ours and Skyrim's
with its 58.5 m cell), edge links whose leaving edge does not lie on the triangle they name (ours and Skyrim's), door
links, and the navmesh's height above the terrain (Skyrim's LAND, + height_offset_m for ours: the exterior's BTD is
built from the same heights). compare.html: top-down, toggles for ours (one colour per navmesh), Skyrim's outlines,
door triangles, broken links (red), the 100 m Starfield and 58.5 m Skyrim cell lines.
