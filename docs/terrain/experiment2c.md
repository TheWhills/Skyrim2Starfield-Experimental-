# Terrain experiment 2c: the real Fallout 4 objects around Red Rocket on the native terrain

Author: Claude, 2026-10-11. Branch `claude/terrain-exterior-statics`, stacked on PR #64
(`claude/terrain-overlay-records`, which contains #60, #57 and #56). Starfield 1.16.244.
Status: **built and checked offline, staged, not deployed, not queued.** It waits for a run of the same terrain
that shows the BTD relief in game (see "Prerequisite").
Labels: **verified** = checked here on files, number given; **supported** = supported hypothesis; **unresolved**.
Offline checks are not in-game acceptance.

## Prerequisite: the terrain first
Experiment 2b's first in-game attempt (runner queue `terrain_exp2b`, finished 2026-10-11 16:46:41) read
**z = -116.00 at the arrival and at all 14 probes**: flat ground, the BTD's minimum, no relief (**verified**, runner
`obs.json`). Its persistent anchor `02000800` read `-989.03 1147.20 105.14`, its own unmerged local position, so the
runner took the offset from the arrival: (-1200.0, -2700.0) whole cells. The probe `resampled_sw` ended 141.9 m from
its target (INCONCLUSIVE MOVED); the second attempt read falling positions.
Another track found that every vanilla terrain archive stores its BTDs uncompressed while our installer packs them
zlib-compressed (PR #67: **verified** for the storage, **supported** as the cause), and staged `terrain_exp2b2`
(exp2b + the BTD also under `meshes\terrain`), now queued. exp2c is built on that base (below) and must not be queued
until an exp2b-family run passes its terrain check. Until then exp2c's entry 1 would fail and entries 2 to 4 could
not be read as alignment checks.

## What it tests
The owner's step-2 check, "alignment with a familiar placed structure", now in Starfield: the exp2b terrain
([overlay-records.md](overlay-records.md): 29 x 29-cell BTD of the real heights, Location, mask, Absolute alignment,
Mars registration) plus **every Fallout 4 reference of FO4 cells x -20..-15, y 16..21 that converts**, placed at FO4
position / 70 in the same worldspace `FO4CW_Commonwealth`: 8,069 references of 1,385 converted models (351 m x 351 m).

1. Do references in the overlay worldspace's own exterior cells load, and merge with the same offset as its terrain?
   The runner takes the x/y offset from the arrival (the COC marker is a temporary reference in an exterior cell, like
   every placed object here; exp2b's arrival moved by whole cells) and, through `z_ref`, every height relative to a
   terrain probe read in the same test. The persistent anchor is still in the plan, but exp1d and exp2b show that it
   reads its unmerged position (**verified**), so it is not what the offsets rest on.
2. Does an object placed at FO4 position / 70 stand on the BTD as it stands on FO4's terrain? The Red Rocket building
   `RedRExt_Workshop01` (`000211C0`, FO4 z 7360 = 105.1429 m) stands exactly on FO4's terrain (PR #56).
3. Do the tops of large flat objects read at their converted collision height? The shop floor is measured as well, but
   only informationally (it stands 0.14 m above the terrain, under the runner's 0.5 m tolerance).

## Pipeline

| Step | Tool | Result |
|---|---|---|
| 1 export | `dotnet/Fo4Land export-exterior` (new mode, Claude's) | 36 FO4 cells, 8,960 references + 48 actors (deferred), 9 s |
| 2 select | `scripts/terrain/make_exp2c.py select` (`src/fo4sf/exterior.py`) | 8,099 to convert (1,400 models), 909 skipped with a reason |
| 3 convert | `scripts/convert_batch.py --cell-json ... --prefix fo4cw` | 1,386 models converted, 15 failed, 278 s, 2.3 GB |
| 4 stage | `make_exp2c.py stage --exp2b terrain_exp2b2` (+ `dotnet/TerrainExp2` with `objects.json`) | `C:\Modding\staging\terrain_exp2c`, plugin 829,032 B, 21 s |
| 5 check | `make_exp2c.py check --fo4 --fo4-data --sf-data` | 137 checks, **PASS**, 13 s |

### 1. Exterior export (verified)
- `dotnet/Fo4Export` (Codex's, unchanged) exports interior cells only. The new Claude-owned mode
  `Fo4Land <Fallout4.esm> export-exterior <World> <xmin> <ymin> <xmax> <ymax> <out.json>` compiles Fo4Export's
  `ReferenceExport.cs`, `KeywordExport.cs` and `TeleportDependencies.cs` in from their source files
  (`dotnet/Fo4Land/Fo4Land.csproj`). Every reference therefore has exactly the schema v2 fields of an interior
  export ([CELL-EXPORT.md](../CELL-EXPORT.md)), plus `exterior_cell` (FO4 grid) and `source_cell` (the CELL that stores it).
- Persistent references of exterior cells live in the worldspace's persistent cell in Fallout4.esm
  (`00018AA2` for Commonwealth); they are taken from there when floor(position / 4096) is in the range. Placed
  hazards and projectiles (Mutagen's `APlacedTrap` types) are positioned too and go to `deferred_refs`, like every
  placement that is neither REFR nor ACHR; a persistent placement without any position is counted in
  `exterior.persistent_unpositioned_by_type`, never dropped silently. For this range the export is unchanged by that
  fix: same references and deferred references, the new count is empty (**verified**, rerun 2026-10-11).
- Cross-check against the independent Python reader `src/fo4sf/fo4land.py` (raw group walk): the same
  9,008 FormIDs, the same cells, positions within 0.004 units (JSON float formatting), persistent flags agree
  (496 persistent, 488 objects + 8 actors).

### 2. Selection: nothing is dropped silently (verified counts)
`exterior.classify` puts every reference in one of two lists. Skipped (`skipped.json`, 939 in total):

| Reason | Refs | What |
|---|---|---|
| `type_not_translated` | 453 | decals (TextureSet) 125, lights 119, bendable splines (power lines) 110, idle markers 67, sound markers 21, acoustic spaces 11 |
| `editor_marker` | 233 | models named `*marker*` (XMarkerHeading 99, invisible generic 37, ...), the filter convert_batch applies to cell exports |
| `effect` | 107 | `effects\` meshes: wind debris, mist, paper bits, leaves (particles / fog volumes) |
| `no_model` | 66 | trigger volumes (Activator 35), PlaneMarker / CollisionMarker / LightBox statics (27), 4 armour (its world model is not in the ARMO record Mutagen reads) |
| `deferred` | 48 | actors (`PlacedNpc`): NPC translation is another track |
| `conversion_failed` | 30 | 15 models: rubble FloorChunk01/03/04/05 and the gnat swarm ("no static BSTriShape geometry"); distant clouds `Sky\CloudDistant*` and workshop borders ("only effect-shader shapes") |
| `water` | 2 | `Water\Water1024.nif` water planes: FO4 renders them with a water type; as a static they would be an opaque grey sheet |

- **Trees did not fail**: the 1,382 tree references here (`landscape\trees`) are STAT records with ordinary
  BSTriShape geometry and converted like any static. Landscape statics (grass clumps 408, grass mounds 316, rocks 340,
  roads 147, sidewalks 196, cliffs 93, guard rails 48) converted too.
- Placed by family: setdressing 2,481, trees 1,382, plants 1,197, architecture 617, grass 408, rocks 340, grass mounds
  316, precombines (`scol`) 299, sidewalks 196, props 159, roads 147, interiors (the Red Rocket models) 142, others.

### 3. Conversion
- The existing converter with `--starfield-data` (FO4's own collision bodies, rigged doors), a type list that adds
  Flora, Ingestible, Weapon, Ammunition and Armor (loose items become plain statics), and the new
  **`convert_batch.py --prefix`** (default `fo4port`, unchanged behaviour): the files go to `meshes\fo4cw`,
  `materials\fo4cw`, `textures\fo4cw`, so FO4Port's own archive (loaded later, same converter) can never override an
  experiment file at the same path.
- **Checkpoints (corrected):** `--prefix` adds nothing to the signature at its default, but the signature hashes every
  `src/fo4sf/*.py`. This PR adds `exterior.py` and `sfbodies.py` (the stacked terrain PRs below it add `btd.py`,
  `fo4land.py`, `overlay.py` and `terrain_grid.py`), so **merging it invalidates every FO4Port conversion
  checkpoint once, and every later edit of these modules does so again**, although the converter never imports them
  (**verified** from `checkpoint_signature`). Hashing only the converter's import closure would avoid it; that is the
  checkpoint owner's call (Codex, docs/CODEX-HANDOFF.md), not changed here.
- Collision of the placed references: FO4's own bodies 5,446, none in FO4 (paper, plants, rubble) 2,550, rigged door
  boxes 15, passable door 1, **guessed boxes 57** (13 precombined meshes: 11 whose debris bodies use the undecoded
  primitive encoding, one with a scaled collision node, one whose native bodies came out empty). No measuring point
  uses an object with guessed collision.
- Two models near measuring points, the road `SancRoadCrvCustom02` and `Truck03`, use `hknpDynamicCompoundShape`:
  FO4's own collision of them does not decode with `fo4collision` / `routes.collision_bodies`, so their converted
  collision rests on `meshcollision`'s compound flattening alone. Both are only in the informational entry.

### 4. Placement and plugin layout (decision)
- Position = FO4 position / 70 in the worldspace's own frame, rotation copied (radians), scale copied, rigged doors
  shifted by their hinge offset as PluginSpike does, Starfield cell = floor(x / 100 m), floor(y / 100 m) **of the
  shifted position** (16 cells, x -12..-9, y 9..12), initially disabled stays disabled (1).
  Fixed 2026-10-11 after QA: the cell was computed before the hinge shift, which put door `077A83` (at y 1100.307 m,
  cell (-10, 11)) into cell (-10, 10); `check` now also tests every reference's cell against its written position.
- All references are **temporary** in their exterior cell, the 105 that are persistent in FO4 too: nothing here
  (no scripts, aliases or linked references) needs them persistent, and 105 statics would otherwise stay loaded.
  FO4 enable parents are not translated (11 references show by default).
- **One plugin**: `FO4TerrainExp2.esm` = exp2b's records + 1,376 STAT + 9 DOOR + 8,069 REFR, EditorIDs `FO4CW_<stem>`.
  Why:
  - the meshes must ship in `<plugin> - Main.ba2` (loose files are disabled), and `exp_install.py --pack` builds
    one archive named after the first plugin;
  - the new records are allocated **after** every terrain record, so exp2b's FormIDs do not move: the anchor stays
    `02000800` and `FO4TerrainExp2_Mars.esm` is byte-identical to exp2b's;
  - nothing depends on FO4Port.esm or its archive (own EditorIDs, own asset prefix).
  - Alternatives: a separate statics plugin mastered on `FO4TerrainExp2.esm` would need its own archive, CELL
    overrides of 16 exterior cells and a third plugin in the install, for no gain; FO4Port.esm would tie the
    experiment to the main build, and PluginSpike writes interior cells only.
- The plan uses the runner's current format (z_ref, see below); `make_exp2c.py` copies every key of the base
  experiment's entry into its entries, so a key the runner learns later is carried, not lost.
- STAT records have no object bounds, as in FO4Port.esm (which loads in game); whether exteriors need them for
  culling is **unresolved**.

### 5. Reading back the converted collision (verified)
`src/fo4sf/sfbodies.py` (new) decodes the collision of our converted Starfield NIFs: every bhkNPCollisionObject's
tagfile (compressed mesh, convex hull with its radius, sphere, the box template), placed by its node's world
transform. On `RedRExt_Workshop01` it gives back FO4's own collision exactly: 3,557 vertices, 5,898 triangles,
0 differ from `fo4collision` on the source NIF. All 1,385 models decode (736,906 world triangles).
The offline surface model treats every collision layer as solid, also layers the player passes through (trigger,
non-collidable; 65 models have such bodies). That is conservative for clearance; for the landing points `check
--fo4-data` reads the layer from FO4's own collision: every judged point and the shop floor land on layer 1 (static).

## Red Rocket, as the converted collision shows it (verified offline)
- `RedRExt_Workshop02` (`001B5F12`, same origin and rotation 225 degrees as Workshop01) holds the **shop floor**,
  0.0286 m (2 FO4 units) above the origin, at 105.1714 m everywhere (512 samples, min = max), the **shop roof** at
  109.74 m (4.71 m above the terrain) and the **canopy roof** over the pumps (its collision lies between 109.95 and
  110.66 m at the points checked; exp2b's points `redrocket_1` / `redrocket_2` now land on it at 110.4923 / 110.6579).
- `RedRExt_Workshop01` (`000211C0`) holds the shop **ceiling** at 108.343 m, 3.17 m above the floor, and has **no
  floor**.
- The COC marker stands 2 m above the terrain under the canopy (107.1434 m; terrain 105.1434 m). After `coc` the
  player falls 1.88 m onto the pump island `SWIsland9x1Str01` (`00035B80`) at 105.2609 m, 0.117 m above the terrain:
  that is exp2c's `spawn_local` z.
- The terrain under the shop is 105.0293 m (BTD and FO4 LAND agree), 0.142 m below the floor.
- Yaw convention: 33 references at floor height (cabinets, counters, the tool chest, the shop door) lie inside the
  shop footprint with the clockwise heading PluginSpike and `routes.py` use; with the opposite sign, 0. So the
  convention used for the offline geometry is right for this building (**verified**; the game itself reads the
  copied angles).

## Offline results (verified, `offline_check.json`)
- **Object z - terrain z.** Red Rocket building: -0.56 mm against the decoded BTD (all three interpolation rules),
  0.00 mm against FO4's own LAND (FO4 says 0). For all 8,069 origins, the BTD under the object differs from FO4's
  terrain under it by median 1.43 mm, p95 24.8 mm, p99 56.6 mm, max 482 mm; 6,743 within 1 cm, 7,954 within 5 cm.
  The worst five are around (-877, 1047), a sharp FO4 terrain edge the 0.78 m BTD grid cannot hold (experiment 2's
  cliff note). So objects keep their FO4 height above the terrain to millimetres almost everywhere.
- **Raw walk** of `FO4TerrainExp2.esm` (independent of Mutagen): masters [Starfield.esm]; CELL 842, WRLD 1, SFBK 1,
  LCTN 1, STAT 1,376, DOOR 9, REFR 8,071 (8,069 + COC marker + anchor); 16 exterior cells with references, as
  `objects.json` says, and every reference in the cell of its written position; every REFR's base, position (within
  6.1e-5 m, float32), rotation, scale and disabled flag as written; **all 847 exp2b records unchanged**; the base's
  three Data files (BTD, its `meshes\terrain` copy, mask) and the Mars plugin byte-identical; the exp2b check (FNAM,
  XLCN, INAM/HNAM, anchor, Mars entry, mask) passes again.
- **Files**: every base model is in `Data\meshes`; the 1,385 NIFs name 3,366 geometries, 704 materials; the
  materials name 2,328 of our textures and one vanilla texture (in the Starfield texture archives): 0 missing.
- **Every landing point against FO4's own collision** (`--fo4-data`: the source NIF from the FO4 mesh archives,
  `routes.collision_bodies`, placed like the reference): the three judged object tops and both floor points within
  0.035 mm, all on layer 1; the informational points within 0.043 mm, except `flat_sancroadcrvcustom02`, whose FO4
  collision does not decode (dynamic compound, above).

## plan.json (runner format, four entries)
All entries: `coc FO4CW_RedRocketSpawn`, every key of exp2b's entry (anchor `02000800`, `settle_ms` 8000, ...),
`spawn_local` (-989.0286, 1147.2, **105.2609**) = the pump island (exp2b: 105.1434, the terrain), and
**`z_ref` `zref_ground`**: every entry has the same terrain reference probe and the runner judges every height
relative to it (`oz = read(zref_ground) - 105.0293`), so neither the arrival's z nor the anchor matters for the
verdict. Expectations are in the worldspace's own frame; the runner adds the x/y offset.
`zref_ground` (-979.0286, 1146.2) is the open, level terrain point closest to the arrival (10.05 m) that passes:
the three interpolation rules agree (105.02925 m), at most 0.02 m spread over a 0.6 m disc, no collision surface
above the terrain and no triangle reaching into a 3 m column within **1.5 m**, and reachable from the low floor drop.

| Entry | drop_z | Role | Points (x, y -> expect) | Verdict tells |
|---|---|---|---|---|
| 1 | 150 | terrain gate | `slope_2_cell_-17_18` (-983.7714, 1106.2857 -> 100.5714), `seam_sf_west` (-1000.2286, 1089.8286 -> 100.4571), `seam_fo4_east` (-991.0857, 1100.8 -> 99.5429), `zref_ground` | flat ground fails (worst 5.49 m); does not depend on the objects |
| 2 | 150 | objects | `zref_ground`, `roof_bld04angle45brickacom01` (-900.2594, 1022.3516 -> 103.8768, 15.99 m above the terrain), `top_roadaintydeathclawambush01` (-862.846, 1049.7877 -> 88.2104, 1.34 m), `redrocket_roof` (-993.3143, 1140.4142 -> 109.7408, 4.71 m) | without the objects it fails (worst 15.99 m) |
| 3 | 105.92 | informational: shop floor | `redrocket_floor_1` (-996.9562, 1135.2723 -> 105.1714), `redrocket_floor_2` (-996.4562, 1141.7723 -> 105.1714), `zref_ground` | nothing: passes with or without the floor (0.142 m < 0.5 m); read the numbers |
| 4 | 150 | informational | `zref_ground`, exp2b's `flat_1`, `flat_2`, `slope_1/3/4`, `seam_fo4_west`, `seam_sf_east`, `redrocket_1/2` (on or within 1 m of an object), `flat_sancroadcrvcustom02` and `flat_northbridge` (tops 0.05 / 0.06 m above the terrain under them) | compare the readings one by one |

- **Judged points discriminate.** A judged object point stands at least **1.0 m** (twice the runner's 0.5 m
  tolerance) above every terrain sample under its 0.6 m landing disc, so without the object the entry fails; `check`
  predicts each entry's verdict without objects and (entry 1) on flat ground with the runner's own formula and
  requires these outcomes. The first plan judged the shop floor (0.142 m above the terrain), the road (0.096 m) and
  the North bridge (0.308 m) next to real objects: with no objects loaded it would have passed (QA, 2026-10-11).
- **Terrain points** in entry 1 are exp2b's points inside the 16 object cells with no collision standing more than
  0.1 m above the terrain within **1.0 m** (the first plan used 0.6 m and kept `flat_2`, which has a car body 0.5 to
  0.64 m high 0.8 to 1.0 m away). `resampled_sw` and `resampled_ne` lie outside the object cells: exp2b's
  question (and `resampled_sw` was the probe that MOVED), not in exp2c.
- **Teleports.** The runner moves the player with `setpos x`, then `y`, then `z`, from where the player stands. With
  an assumed 0.4 m x 1.8 m cylinder, `check` tests every intermediate position for overlap with collision (walls
  included) and terrain. Entry 3 (low drop under the shop ceiling) is **clear at every position** (required). In the
  150 m entries the point order is chosen to avoid object overlaps; what is left are positions under the terrain on a
  slope (entries 1, 2, 4) and one object overlap in entry 4 (to `flat_northbridge`). The vanilla LC172World run
  (queue `terrain_A2_lc172`) moved the player between 8 probes on relief spanning about 11 m and read every probe at
  its x and y (**verified**), so positions under the terrain are probably harmless (**supported**, not shown position
  by position); whether setpos resolves an overlap with an object is **unresolved**.
- REFR FormIDs of every measured object (load-order byte 02 assumed, as the anchor) are in `expected.json`
  (`owner.refr`), e.g. Workshop02 `02002DC3`, so `prid` can find them.

## Staged files (`C:\Modding\staging\terrain_exp2c`, outside the repo)

| File | Bytes | Content |
|---|---|---|
| `FO4TerrainExp2.esm` | 829,032 | exp2b's WRLD / SFBK / LCTN / 841 cells / COC marker / anchor + 1,376 STAT, 9 DOOR, 8,069 REFR |
| `FO4TerrainExp2_Mars.esm` | 6,512 | byte-identical to exp2b's / exp2b2's |
| `Data\Terrain\FO4CW_Commonwealth.btd`, `Data\meshes\terrain\FO4CW_Commonwealth.btd`, `Data\textures\terrain\overlaymasks\fo4cw_commonwealth.dds` | | byte-identical to the base `terrain_exp2b2` (the `meshes\terrain` copy is exp2b2's addition) |
| `Data\meshes\fo4cw`, `Data\geometries`, `Data\materials\fo4cw`, `Data\textures\fo4cw` | 2.3 GB, 7,733 files | converted models |
| `plan.json`, `expected.json`, `objects.json`, `formids.json`, `skipped.json`, `exp2_params.json`, `offline_check.json`, `README.txt` | | runner input; every point with owner, landing, predicted verdicts and teleport paths; what TerrainExp2 placed; FormIDs; skipped references; builder params; offline check; manual steps and the prerequisite |

**BTD storage**: install with the BTDs stored uncompressed in the archive (PR #67's finding, **supported**), whatever
installer the run uses. **Textures**: `Data\textures\fo4cw` holds the converted DDS textures. The installer on
`claude/test-queue` packs every folder into `FO4TerrainExp2 - Main.ba2` (General), while FO4Port ships its textures
in a DDS-format `FO4Port - Textures.ba2` (deploy_starfield.py); the installer on `claude/runner-npc-nav` (PR #68)
builds `<plugin> - Textures.ba2` the same way. Without it the objects may show untextured; positions and collision do
not depend on textures.

## Running it (after the prerequisite)
Never with experiment 1 or 2b installed (same plugin names, same `MarsPlanetData` override).

    python scripts/game/testqueue.py plan-terrain --staging <FO4Port build dir> --exp-dir C:\Modding\staging\terrain_exp2c ^
        --out <queue dir> --plugins FO4TerrainExp2.esm,FO4TerrainExp2_Mars.esm
    python scripts/game/testqueue.py run --queue <queue dir>

Four tests (one per entry). Planned into a scratch folder with the runner on `claude/integration-1011` (39a3be0):
all four tests carry `z_ref zref_ground`, `spawn_local`, `anchor`, `settle_ms` (**verified**). By hand: `README.txt`.

## Reading the result

| Observation | Meaning |
|---|---|
| Entry 1 FAIL (HEIGHTS), the probes read one height | the BTD relief is still missing: the terrain question (prerequisite), not the objects; entries 2 to 4 say nothing about alignment |
| Entry 1 PASS, entry 2 PASS | objects and terrain share one frame: FO4 position / 70 on the BTD reproduces FO4's placement (step-2 check passed); then read entry 3: floor points about 0.14 m above `zref_ground` = the shop floor collision is there |
| Entry 1 PASS, entry 2 FAIL with object points at the terrain height under them (88.21 -> about 86.8, 103.88 -> 87.9, 109.74 -> 105.03) | the objects did not load (archive, cell attach, or references in an overlay worldspace are not merged) |
| Entry 1 PASS, entry 2 FAIL with object points off by one constant | the overlay merge moves references differently from the terrain (Z); compare with the arrival offset |
| Entry 1 PASS, entry 2 INCONCLUSIVE MOVED | the x/y offset differs for objects or the player was pushed off a roof: compare each `read` with the target |
| Entry 3 floor points read 105.03, the height of `zref_ground` | the player stood on the terrain: the shop floor collision did not load (the verdict still passes) |
| Entry 3 floor points read about 109.74 | the drop started above the shop roof: the drop height comes from the arrival's z (not from z_ref), off by more than 3.8 m; look at `spawn_read` |
| Objects visible but white / untextured | the textures need their own DDS archive (see Textures) |

## Unknowns
1. Everything in game; first of all the BTD relief (prerequisite).
2. Whether references in an activated overlay worldspace merge with the same offset as its terrain.
3. Texture archive format; STAT object bounds in exteriors; 8,069 references in 16 cells (performance, LOD: none).
4. The player capsule (0.6 m landing disc, 1.0 m clear radius for terrain points, 0.4 m x 1.8 m cylinder for the
   teleport check: assumptions), how `getpos z` reads on a slope, and whether setpos resolves an overlap with an object
   at an intermediate position.
5. FO4 enable parents, persistence, actors, lights, decals, power lines and water: not translated (counted above).

## Reproduce
    dotnet run --project dotnet/Fo4Land -c Release -- <Fallout4.esm> export-exterior Commonwealth -20 16 -15 21 <work>\export.json
    python scripts/terrain/make_exp2c.py select --export <work>\export.json --work <work>
    python scripts/convert_batch.py --fo4-data <FO4 Data> --staging <work>\convert --content-resources <ContentResources.zip> ^
        --texconv <Texconvx64.exe> --collision-template <template.nif> --starfield-data <Starfield Data> ^
        --cell-json <work>\convert_input.json --types Static,StaticCollection,MovableStatic,Furniture,Door,Activator,Container,MiscItem,Terminal,Flora,Ingestible,Weapon,Ammunition,Armor ^
        --prefix fo4cw --limit 100000 --resume
    python scripts/terrain/make_exp2c.py stage --work <work> --exp2b C:\Modding\staging\terrain_exp2b2 --out C:\Modding\staging\terrain_exp2c --sf-esm <Starfield.esm>
    python scripts/terrain/make_exp2c.py check --work <work> --exp2b C:\Modding\staging\terrain_exp2b2 --out C:\Modding\staging\terrain_exp2c ^
        --sf-data <Starfield Data> --fo4 <Fallout4.esm> --fo4-data <FO4 Data>
    python -m unittest tests.test_exterior tests.test_sfbodies tests.test_make_exp2c tests.test_batch_prefix

`<work>` was `C:\Modding\staging\terrain_exp2c_work`. Times: export 9 s, conversion 278 s, stage 21 s (plus about
15 s to copy 2.3 GB the first time), check 13 s (with `--fo4` and `--fo4-data`). With `FO4SF_TESTQUEUE` set to a
`scripts/game/testqueue.py` (or once it is in the tree), `tests.test_make_exp2c` also runs our entries through the
runner's own `plan_terrain` and compares `judge_heights` with the runner's `judge`.
