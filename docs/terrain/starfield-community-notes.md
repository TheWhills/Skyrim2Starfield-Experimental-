# What the Starfield modding community knows that bears on the Skyrim port

Read 2026-10-14 (Nexus Mods, Nexus forums, Starfield Wiki, a CK modder's blog, GitHub). None of it is verified here;
each item is a **lead** with its source. Labels as elsewhere: **supported** = several independent reports or matches
our own measurements; **unresolved** = one report or untested.

## Collision: a route to real Starfield collision instead of boxes (unresolved, highest value)
* Bethesda's own pipeline writes Starfield collision: the **Skyrim SE CK's official Blender exporter**
  (`bgs_skyrim_tools.zip` + `io_scene_bsfbx_skyrim.zip`, from a Skyrim SE install) plus **Starfield's AssetWatcher**
  (Starfield `Tools`) turns an FBX with "Create Collider" + "Create Rigidbody" into a NIF with a "Starfield-compliant
  collision node and physics system". A commenter reports **Concave Mesh** collider type works better than the default.
  Sources: Nexus article 871 (OpheliaComplex), Nexus mod 14637.
* Starfield Wiki (3ds Max 2021 + Havok Content Tools) ranks shapes sphere < capsule < box/cylinder < convex hull <
  mesh ("extremely expensive") and recommends a few primitives over a mesh: our box approach is the cheap end of that.
* A Blender extension (Nexus mod 16979) does collider creation/editing, Static / Anim Static layers and Havok debug
  view, Windows only, "work in progress".
* What it would take: write each model's decoded Skyrim collision triangles (skyrimnif.collision_triangles) to an
  FBX next to the render mesh, drop them into an AssetWatcher source folder, and harvest the NIF's physics block.
  Unknown: whether AssetWatcher runs unattended over thousands of files, and whether mesh colliders are affordable at
  Tamriel's density. Spike before building: one rock and one building, compare in game against the box version.

## Terrain edges: the engine blends overlays into the planet (supported)
* A CK modder moving vanilla locations found the engine **auto-blends a worldspace's terrain into the surrounding
  planet terrain at its edge**; terrain cut off at the edge became **vertical walls** after blending. Vanilla
  locations ship a 16 x 16 "block pattern" of terrain blocks so the blend lines up. Source: thecommabandit.bearblog.dev.
* Consequence here: the square padding around Tamriel no longer edge-extends (which also invented ground past
  Skyrim's coast); it eases to Skyrim's default land height and stays flat to the overlay edge (skyrim-tamriel.md).

## Plugins and records (supported)
* Full master: about 16.7 M forms; **medium master: 65,535**; small: 4,095 (Nexus article 688). The object plugin
  must stay a full master (core64c: 648,358 REFR in one full master). Every vanilla record we override costs a
  load-order slot and can conflict.
* Overriding vanilla worldspace cells has broken **surface maps and scanner POI markers** in those areas (Nexus forum
  13497605, SFBGS008 cells). Our only vanilla override is Mars's planet record (PNDT); check Mars's surface map and
  scanner after installing, and keep the override to that one record.

## Meshes and materials (supported)
* Geometry lives in `geometries/<hash>/<hash>.mesh`; a mesh must stay **under 65,535 vertices** (Nexus article 268).
  sfmesh writes u16 indices and Skyrim shapes are u16-indexed, so each converted shape fits; one that did not would
  fail with a struct error, not corrupt.
* Material Editor Lite (Nexus mod 14659) edits Standard1Layer, **StandardTwoSided1Layer** and ColorEmissive `.mat`
  files with a live preview: the quickest way to inspect a converted material by hand. If materials do not show in the
  CK, use its "refresh materials" button.
* **Double-sided surfaces:** Skyrim marks them in Shader Flags 2 (SLSF2_Double_Sided, 0x10: leaves, banners,
  cloth). Done without a new material format: each such shape gets a mirrored copy of its triangles (reversed winding,
  normals negated), so it shows from both sides with the one-sided materials this pipeline writes. A shape whose
  doubled vertex count would pass 65,535 stays one-sided and is counted (`double_sided_too_big`). The first-run survey
  counts double-sided shapes; first in-game check: look at a tree from below. Unresolved: whether Starfield's
  StandardTwoSided1Layer material would be cheaper than doubled geometry (its `.mat` layout is not researched).
* After installing new textures or materials, **reset the shader cache**, or visual errors can appear (Nexus mod 16332).

## Reference scale (supported; checked here)
* ByroRedux (a Rust Bethesda-format engine) shipped a bug where a placed object's scale (XSCL) was baked into its
  collider and then applied again by the engine (colliders scale x XSCL^2: invisible walls / walk-through). Here the
  collision is written per model at scale 1 and XSCL only goes on the REFR, so this cannot happen; scaled rocks are
  still worth walking into once in game.

## Looked for, not found
* No public tool writes Starfield `.btd` terrain from a heightmap; CK users export BTDs from Terrain Edit, and one
  forum thread (13493498) reports an exported BTD not showing in game with no answer. Our BTD writer stays the
  only path; its in-game check on Mars is the evidence.
* No other Skyrim-to-Starfield port: "Project Tamriel" (2024) was announced and cancelled within days; "Starwind"
  moving to Starfield was an April Fools' story.
