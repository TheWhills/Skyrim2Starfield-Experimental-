# Work packages

Each package is independent, with inputs, outputs and an acceptance test. Status values: `ready` (can start
now), `blocked:<id>` (needs another package first), `spike` (research with a go/no-go), `done`.
GitHub issues mirror these 1:1; one `## WP-xx` section = one issue.

Do the spikes (S1–S9, see [RISKS.md](RISKS.md)) before the packages that depend on them.

## WP-00: Reconnaissance (done)
Status: `done`. Measured the format gap between Fallout 4 1.10.163 and Starfield 1.16.244.
Output: `scripts/recon.py`, `scripts/recon_physics.py`, `docs/measurements/`, `docs/FORMAT-GAP.md`.

## WP-01: Project skeleton, config and manifest
Status: `ready`. Difficulty: easy.
Create the Python package `src/fo4sf/` with a CLI (`python -m fo4sf <stage>`), `config.toml` loading
(see `config.example.toml`), and a **manifest** (SQLite or JSON-lines) recording, per asset: source path,
content hash, converter version, output path, fidelity tier (T0–T4), highest verification level (L0–L4).
**Acceptance:** `python -m fo4sf status` prints a coverage table from the manifest; re-running a stage skips
unchanged inputs (hash-based); tests pass with synthetic data only.

## WP-02: Fallout 4 archive and NIF readers
Status: `ready`. Difficulty: medium.
Promote `scripts/recon.py`'s BA2 reader into the package (add DX10 texture extraction and Fallout 4 v1 zlib
files), and add a full NIF BS-130 reader (`BSTriShape`, `BSSubIndexTriShape`, `BSLightingShaderProperty`,
`bhkNPCollisionObject`, skin + bones). Evaluate [nifly](https://github.com/ousnius/nifly) first.
**Acceptance:** extract every `.nif` from the vanilla meshes archive and parse it with zero exceptions; report
unsupported block types as a measured list.

## WP-03: Intermediate representation
Status: `ready`. Difficulty: easy.
Define the IR: mesh → glTF 2.0 (`.glb`) with extras for FO4-specific data; texture → PNG/DDS + metadata JSON;
material → JSON schema; record → JSON (one file per record, stable keys). Document it in `docs/IR.md`.
**Acceptance:** schema files + 3 hand-written examples validate; a script converts the S1 chair NIF to
IR and back to a viewable `.glb`.

## WP-04: Mesh converter (FO4 NIF → Starfield NIF + `.mesh`)
Status: `in progress`: static meshes convert offline (`src/fo4sf/convert_static.py`, see S1); still needs skinned meshes, LODs, in-game verification. Difficulty: hard (the keystone).
Productionise S1: write BS-175 NIFs and `.mesh` files, including skinned meshes, UV sets, vertex colours,
tangents/normals packing, LOD, meshlets.
**Acceptance:** round-trip tests; all vanilla `SetDressing` statics convert (T1); a random 100 render in the
CK without crashes (L2).

## WP-05: Texture converter
Status: `in progress`: colour/normal/roughness conversion works for one asset (`src/fo4sf/textures.py`, S3). Still needed: a native DX10 BA2 + LZ4 reader for bulk extraction, BC7/alpha, glow maps. Difficulty: medium.
BC1/BC3/BC5/BC7 handling with DirectXTex/`texconv`; channel repack from FO4 `_d/_n/_s/_g/_l` to Starfield's
colour/normal/roughness-metal/emissive maps; mip chain; sRGB flag correctness.
**Acceptance:** converted texture pixel stats within tolerance of a hand-made reference; every FO4 texture
converts or logs why not.

## WP-06: Material converter (`.bgsm`/`.bgem` → `.mat`)
Status: `in progress`: `.bgsm` to `.mat` works for opaque single-layer materials (`src/fo4sf/convert_material.py`, S3). Still needed: alpha, glow, two-sided, `.bgem`, metalness heuristics. Difficulty: medium.
Parse FO4 materials and emit Starfield `.mat` JSON with the mapping table in `mappings/materials/`.
**Acceptance:** 95% of vanilla `.bgsm` convert; unconverted ones are listed with reasons; chair renders (L2).

## WP-07: Collision converter
Status: `in progress`: box collision works in game (`src/fo4sf/sfcollision.py`, S6). Still needed: convex hulls, compound/mesh shapes, static bodies, converting FO4's own shapes. Difficulty: hard.
FO4 `bhkNPCollisionObject` (Havok 2014 packfile) → Starfield `bhkNPCollisionObject` (hknp tagfile): boxes,
convex hulls, then mesh shapes via decomposition.
**Acceptance:** player is blocked by converted statics in-game (L3); tests verify shape volumes agree
within 5% of the source.

## WP-08: Record translation framework (.NET / Mutagen)
Status: `in progress`: `dotnet/Fo4Export` (FO4 cell -> JSON) and the manifest/cell plugin writer in `dotnet/PluginSpike` work for STAT, CELL, REFR and lights. Difficulty: medium.
`dotnet/` solution that reads FO4 records and writes Starfield records via per-type translators and
`mappings/records/*.json`; deterministic FormID allocation (see PLAN §3.6); a report of unmapped fields.
**Acceptance:** `STAT`, `MISC`, `ALCH`, `BOOK` round-trip into a plugin xSFEdit opens cleanly (L1).

## WP-09: Weapons and ammo
Status: `blocked:WP-04,WP-06,WP-08`. Difficulty: medium.
`WEAP`, `AMMO`, `OMOD` (+ attach points / connect points) → Starfield equivalents; reuse Starfield
animations and sounds; map keywords.
**Acceptance:** the 10mm pistol equips and fires in Starfield with its FO4 mesh and material (L4).

## WP-10: Interior cells (Vault 111 slice)
Status: `in progress`: first light, `Vault111Cryo` loads as a Starfield cell with 1,365 converted references and 132 lights (`docs/spikes/WP10-vault111-first-light.md`). Still needed: lighting quality, architecture collision, navmesh, doors, decals, failed models. Difficulty: hard.
`CELL` + `REFR` (static, door, furniture, light, container) → Starfield interior, with lights translated, navmesh
generated, load doors wired.
**Acceptance:** walk the Vault 111 cryo chamber → corridor in Starfield (L3 screenshots at 5 waypoints).

## WP-11: Armor, clothing and body fitting
Status: `blocked:WP-04,S7`. Difficulty: hard.
`ARMO`/`ARMA` and skinned meshes onto Starfield's human skeleton/body; bone-weight transfer, optionally
artist-in-the-loop in Blender.
**Acceptance:** one outfit equips and animates without stretching (L4).

## WP-12: Terrain
Status: `blocked:S5`. Difficulty: very hard.
Convert FO4 `LAND` heights, vertex colours and texture layers to the representation chosen in S5; water,
cell borders, LOD.
**Acceptance:** Sanctuary Hills exterior is walkable and continuous at cell borders (L3).

## WP-13: Actors, races and faces
Status: `blocked:S7`. Difficulty: very hard.
`NPC_`, `RACE`, head parts, facegen → Starfield actor equivalents; creatures mapped onto the closest
Starfield skeleton where one exists.
**Acceptance:** a named NPC spawns with correct outfit and face, idles and walks (L4).

## WP-14: Animation
Status: `blocked:S7`. Difficulty: very hard.
Retarget or replace FO4 animations (`.hkx`) according to S7's decision.

## WP-15: Audio and voice
Status: `ready` (research) → `blocked` on S2 for records. Difficulty: hard.
`.fuz` → wav + lip data; wav → Wwise `.wem` banks with `WWED` events; FaceFX lip-sync generation. Document
the toolchain in `docs/audio.md` before building.
**Acceptance:** one voiced line plays in-game with lip movement.

## WP-16: Papyrus and gameplay systems
Status: `blocked:S2`. Difficulty: hard.
Recompile FO4 Papyrus sources against shim scripts; replacements for VATS, Pip-Boy, power armor, workshop
mode, radiation; SFSE plugin where Papyrus can't reach.
**Acceptance:** a "kill 3 raiders" quest with objective markers completes.

## WP-17: Quests and dialogue
Status: `blocked:WP-08,WP-15`. Difficulty: hard.
`QUST`, `DIAL`, `INFO`, `SCEN` translation; condition-function mapping table; scene markers.

## WP-18: Coverage dashboard, CI and docs site
Status: `ready`. Difficulty: easy.
Generate `docs/COVERAGE.md` from the manifest; enable the CI template in `ci/github-actions-ci.yml` (copy to `.github/workflows/ci.yml`; pushing it needs a GitHub token with the `workflow` scope, e.g. `gh auth refresh -s workflow`); GitHub Pages renders the docs.
**Acceptance:** CI green; coverage table updates on every push.
